"""Claude client that performs structured extraction via tool use.

The model is prompted to call a `report_offerings` tool whose input_schema
mirrors `ExtractionResponse`. We extract the tool input, validate it with
pydantic, and compute per-call cost from token usage.

A generic `call_tool` method provides the same underlying pattern for other
discovery-specific tool calls (e.g. the classifier)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import ValidationError

from yas.llm.prompt import build_extraction_prompt
from yas.llm.schemas import ExtractedOffering, ExtractionResponse
from yas.logging import get_logger

log = get_logger("yas.llm.client")

# Public per-MTok pricing as (input, output), matched by model-ID prefix so dated
# snapshots (claude-haiku-4-5-20251001) resolve to their alias. Update if Anthropic
# revises. Longest prefix wins, so 4-x entries can't be shadowed by a shorter one.
#
# Cache-token rates are deliberately absent: this workload sends unique page HTML
# per call behind a content-hash cache, so there is no reusable prefix to cache.
_PRICING_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    # Standard rate. Introductory pricing ($2.00/$10.00) applies through 2026-08-31;
    # priced at standard here so we over-estimate rather than under-report.
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-fable-5": (10.00, 50.00),
}

# Enough headroom for a listing page of many sessions. Truncation is now a hard
# error (see _call_messages), and unused output tokens are never billed, so the
# only cost of a generous cap is the ceiling we never hit.
DEFAULT_MAX_TOKENS = 16000


@dataclass(frozen=True)
class ExtractionResult:
    offerings: list[ExtractedOffering]
    model: str
    cost_usd: float


class ExtractionError(Exception):
    """LLM call succeeded but output didn't conform to our schema."""

    def __init__(self, raw: str, detail: str):
        super().__init__(detail)
        self.raw = raw
        self.detail = detail


class ToolCallError(Exception):
    """Generic tool-use call failed — model did not invoke the requested tool."""

    def __init__(self, raw: str, detail: str):
        super().__init__(detail)
        self.raw = raw
        self.detail = detail


class _ToolUseFailure(Exception):
    """Internal: the call returned, but not a usable tool input.

    Carries a ready-made `detail` so the public wrappers only have to pick which
    exception type to re-raise as.
    """

    def __init__(self, raw: str, detail: str):
        super().__init__(detail)
        self.raw = raw
        self.detail = detail


class LLMClient(Protocol):
    async def extract_offerings(
        self, *, html: str, url: str, site_name: str
    ) -> ExtractionResult: ...

    async def call_tool(
        self,
        *,
        system: str,
        user: str,
        tool_name: str,
        tool_description: str,
        input_schema: dict[str, Any],
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> tuple[dict[str, Any], str, float]: ...


def _tool_schema() -> dict[str, Any]:
    """input_schema for the report_offerings tool — derived from Pydantic."""
    return ExtractionResponse.model_json_schema()


class AnthropicClient:
    """Production LLM client backed by the Anthropic SDK."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-haiku-4-5-20251001",
        *,
        sdk_client: Any | None = None,
    ) -> None:
        self._model = model
        if sdk_client is not None:
            self._client = sdk_client
        else:
            # Import lazily so tests can run without the SDK wired up.
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(api_key=api_key)

    async def _call_messages(
        self,
        *,
        system: str,
        user: str,
        tool_name: str,
        tool_description: str,
        input_schema: dict[str, Any],
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> tuple[dict[str, Any], str, float]:
        tool = {
            "name": tool_name,
            "description": tool_description,
            "input_schema": input_schema,
        }
        msg = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool_name},
            messages=[{"role": "user", "content": user}],
        )
        stop_reason = str(getattr(msg, "stop_reason", "?"))
        # A max_tokens cutoff truncates the tool input mid-JSON. It may still parse
        # into a well-formed-but-short result, which the reconciler would read as
        # "these offerings are gone" and withdraw. Never let it through.
        if stop_reason == "max_tokens":
            raise _ToolUseFailure(
                raw=_dump_msg(msg),
                detail=(
                    f"response truncated at max_tokens={max_tokens} "
                    f"(stop_reason=max_tokens); result is incomplete"
                ),
            )
        tool_input = _find_tool_input(msg, tool_name)
        if tool_input is None:
            raise _ToolUseFailure(
                raw=_dump_msg(msg),
                detail=f"model stopped without calling {tool_name} (stop_reason={stop_reason})",
            )
        cost = _estimate_cost_usd(msg)
        model = str(getattr(msg, "model", self._model))
        return tool_input, model, cost

    async def call_tool(
        self,
        *,
        system: str,
        user: str,
        tool_name: str,
        tool_description: str,
        input_schema: dict[str, Any],
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> tuple[dict[str, Any], str, float]:
        try:
            return await self._call_messages(
                system=system,
                user=user,
                tool_name=tool_name,
                tool_description=tool_description,
                input_schema=input_schema,
                max_tokens=max_tokens,
            )
        except _ToolUseFailure as exc:
            raise ToolCallError(raw=exc.raw, detail=exc.detail) from exc

    async def extract_offerings(self, *, html: str, url: str, site_name: str) -> ExtractionResult:
        system, user = build_extraction_prompt(html=html, url=url, site_name=site_name)
        try:
            tool_input, model, cost = await self._call_messages(
                system=system,
                user=user,
                tool_name="report_offerings",
                tool_description="Report the list of offerings extracted from the page.",
                input_schema=_tool_schema(),
            )
        except _ToolUseFailure as exc:
            raise ExtractionError(raw=exc.raw, detail=exc.detail) from exc
        try:
            parsed = ExtractionResponse.model_validate(tool_input)
        except ValidationError as exc:
            raise ExtractionError(raw=str(tool_input), detail=str(exc)) from exc
        return ExtractionResult(
            offerings=list(parsed.offerings),
            model=model,
            cost_usd=cost,
        )


def _find_tool_input(msg: Any, tool_name: str = "report_offerings") -> dict[str, Any] | None:
    for block in getattr(msg, "content", []) or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name:
            inp = getattr(block, "input", None)
            if isinstance(inp, dict):
                return inp
    return None


def _dump_msg(msg: Any) -> str:
    """A diagnostic handle for the failed call — deliberately not the response body.

    The assistant message echoes scraped page content, and the truncation path
    calls this exactly when that content is largest. Log the request id and
    stop_reason; pull the body from the Anthropic console if you need it.
    """
    return (
        f"id={getattr(msg, 'id', '?')} "
        f"stop_reason={getattr(msg, 'stop_reason', '?')} "
        f"model={getattr(msg, 'model', '?')}"
    )


def _rate_for(model: str) -> tuple[float, float] | None:
    match = ""
    for prefix in _PRICING_PER_MTOK:
        if model.startswith(prefix) and len(prefix) > len(match):
            match = prefix
    return _PRICING_PER_MTOK[match] if match else None


def _estimate_cost_usd(msg: Any) -> float:
    """Price the call from the model that actually answered.

    An unknown model yields 0.0 plus a warning rather than a guess: a missing
    number is visibly missing, whereas one silently computed at the wrong tier
    corrupts the spend totals surfaced on crawl runs.
    """
    usage = getattr(msg, "usage", None)
    if usage is None:
        return 0.0
    model = str(getattr(msg, "model", "") or "")
    rate = _rate_for(model)
    if rate is None:
        log.warning("llm.unknown_model_pricing", model=model)
        return 0.0
    in_per_mtok, out_per_mtok = rate
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    return (inp / 1_000_000) * in_per_mtok + (out / 1_000_000) * out_per_mtok
