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

# Claude Haiku 4.5 public pricing (2026-04). Update here if Anthropic revises.
# Input: $1.00 / 1M tokens. Output: $5.00 / 1M tokens.
_HAIKU_IN_PER_MTOK = 1.00
_HAIKU_OUT_PER_MTOK = 5.00


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


class _ToolMissingError(Exception):
    """Internal: the model did not call the expected tool."""

    def __init__(self, raw: str, stop_reason: str):
        super().__init__(stop_reason)
        self.raw = raw
        self.stop_reason = stop_reason


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
        max_tokens: int = 4096,
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
        max_tokens: int = 4096,
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
        tool_input = _find_tool_input(msg, tool_name)
        if tool_input is None:
            raise _ToolMissingError(
                raw=_dump_msg(msg),
                stop_reason=str(getattr(msg, "stop_reason", "?")),
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
        max_tokens: int = 4096,
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
        except _ToolMissingError as exc:
            raise ToolCallError(
                raw=exc.raw,
                detail=f"model stopped without calling {tool_name} (stop_reason={exc.stop_reason})",
            ) from exc

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
        except _ToolMissingError as exc:
            raise ExtractionError(
                raw=exc.raw,
                detail=f"model stopped without calling report_offerings (stop_reason={exc.stop_reason})",
            ) from exc
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
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == tool_name
        ):
            inp = getattr(block, "input", None)
            if isinstance(inp, dict):
                return inp
    return None


def _dump_msg(msg: Any) -> str:
    try:
        return repr(msg)
    except Exception:
        return "<unrepresentable message>"


def _estimate_cost_usd(msg: Any) -> float:
    usage = getattr(msg, "usage", None)
    if usage is None:
        return 0.0
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    return (inp / 1_000_000) * _HAIKU_IN_PER_MTOK + (out / 1_000_000) * _HAIKU_OUT_PER_MTOK
