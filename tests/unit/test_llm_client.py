from typing import Any

import pytest

from yas.db.models._types import ProgramType
from yas.llm.client import AnthropicClient, ExtractionResult


class _FakeAnthropicMessages:
    """Mimics anthropic.AsyncAnthropic().messages.create() for unit tests."""

    def __init__(
        self,
        tool_input: dict[str, Any],
        model: str = "claude-haiku-4-5-20251001",
        usage_in: int = 1000,
        usage_out: int = 200,
    ):
        self._tool_input = tool_input
        self._model = model
        self._usage_in = usage_in
        self._usage_out = usage_out
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)

        class _Block:
            type = "tool_use"
            name = "report_offerings"
            input = self._tool_input

        class _Usage:
            input_tokens = self._usage_in
            output_tokens = self._usage_out

        class _Msg:
            stop_reason = "tool_use"
            content = [_Block()]  # noqa: RUF012
            model = self._model
            usage = _Usage()

        return _Msg()


class _FakeAnthropicClient:
    def __init__(self, messages):
        self.messages = messages


@pytest.mark.asyncio
async def test_anthropic_client_extracts_and_prices(monkeypatch):
    tool_input = {
        "offerings": [
            {"name": "Little Kickers", "program_type": "soccer", "age_min": 6, "age_max": 8},
        ]
    }
    fake = _FakeAnthropicClient(messages=_FakeAnthropicMessages(tool_input))
    client = AnthropicClient(api_key="sk-test", sdk_client=fake)
    result = await client.extract_offerings(
        html="<p>Little Kickers ages 6-8</p>", url="https://ex.com", site_name="Ex"
    )
    assert isinstance(result, ExtractionResult)
    assert len(result.offerings) == 1
    assert result.offerings[0].program_type == ProgramType.soccer
    assert result.model == "claude-haiku-4-5-20251001"
    assert result.cost_usd > 0


@pytest.mark.asyncio
async def test_anthropic_client_raises_on_schema_violation():
    bad = {"offerings": [{"name": "x", "program_type": "soccer", "unknown_field": 1}]}
    fake = _FakeAnthropicClient(messages=_FakeAnthropicMessages(bad))
    client = AnthropicClient(api_key="sk-test", sdk_client=fake)
    from yas.llm.client import ExtractionError

    with pytest.raises(ExtractionError):
        await client.extract_offerings(html="<p/>", url="u", site_name="s")


@pytest.mark.asyncio
async def test_anthropic_client_raises_when_model_did_not_call_tool():
    class _NoToolMessages:
        async def create(self, **_):
            class _TextBlock:
                type = "text"
                text = "I couldn't use the tool."

            class _Usage:
                input_tokens = 500
                output_tokens = 10

            class _Msg:
                stop_reason = "end_turn"
                content = [_TextBlock()]  # noqa: RUF012
                model = "claude-haiku-4-5-20251001"
                usage = _Usage()

            return _Msg()

    client = AnthropicClient(api_key="sk-test", sdk_client=_FakeAnthropicClient(_NoToolMessages()))
    from yas.llm.client import ExtractionError

    with pytest.raises(ExtractionError):
        await client.extract_offerings(html="<p/>", url="u", site_name="s")


@pytest.mark.asyncio
async def test_fake_llm_client_returns_scripted_response():
    from tests.fakes.llm import FakeLLMClient
    from yas.db.models._types import ProgramType
    from yas.llm.schemas import ExtractedOffering

    canned = [ExtractedOffering(name="Swim Basics", program_type=ProgramType.swim)]
    fake = FakeLLMClient(default=canned)
    res = await fake.extract_offerings(html="<p/>", url="u", site_name="s")
    assert [o.name for o in res.offerings] == ["Swim Basics"]
    assert fake.call_count == 1


@pytest.mark.asyncio
async def test_anthropic_client_raises_when_response_truncated_by_max_tokens():
    """A max_tokens cutoff yields a partial tool input — never treat it as a complete result.

    The reconciler diffs extracted offerings against active DB rows and withdraws
    anything missing, so a silently truncated list retracts real programs.
    """

    class _TruncatedMessages(_FakeAnthropicMessages):
        async def create(self, **kwargs):
            msg = await super().create(**kwargs)
            msg.stop_reason = "max_tokens"
            return msg

    # Parses cleanly against the schema — only stop_reason reveals the truncation.
    tool_input = {"offerings": [{"name": "Session 1", "program_type": "soccer"}]}
    fake = _FakeAnthropicClient(messages=_TruncatedMessages(tool_input))
    client = AnthropicClient(api_key="sk-test", sdk_client=fake)
    from yas.llm.client import ExtractionError

    with pytest.raises(ExtractionError, match="max_tokens"):
        await client.extract_offerings(html="<p/>", url="u", site_name="s")


class _RefusedMessages(_FakeAnthropicMessages):
    """A refusal can land mid-generation, so give it a partial, schema-valid tool input."""

    def __init__(self, tool_input, category: str | None):
        super().__init__(tool_input)
        self._category = category

    async def create(self, **kwargs):
        msg = await super().create(**kwargs)
        msg.stop_reason = "refusal"
        category = self._category

        class _StopDetails:
            type = "refusal"
            explanation = None

        _StopDetails.category = category  # type: ignore[attr-defined]
        msg.stop_details = _StopDetails() if category is not None else None
        return msg


@pytest.mark.asyncio
@pytest.mark.parametrize("category", ["general_harms", None])
async def test_extract_offerings_raises_refused_with_category(category):
    """HTTP 200 + stop_reason=refusal must never be read as an (empty or partial) result."""
    from yas.llm.client import ExtractionError, ExtractionRefused

    tool_input = {"offerings": [{"name": "Session 1", "program_type": "soccer"}]}
    fake = _FakeAnthropicClient(messages=_RefusedMessages(tool_input, category))
    client = AnthropicClient(api_key="sk-test", sdk_client=fake)

    with pytest.raises(ExtractionRefused, match="refusal") as info:
        await client.extract_offerings(html="<p/>", url="u", site_name="s")
    assert info.value.category == category
    # Existing `except ExtractionError` handlers keep catching it.
    assert isinstance(info.value, ExtractionError)


@pytest.mark.asyncio
async def test_call_tool_raises_on_refusal():
    from yas.llm.client import ToolCallError

    fake = _FakeAnthropicClient(messages=_RefusedMessages({"candidates": []}, "cyber"))
    client = AnthropicClient(api_key="sk-test", sdk_client=fake)

    with pytest.raises(ToolCallError, match="category=cyber"):
        await client.call_tool(
            system="s",
            user="u",
            tool_name="report_offerings",
            tool_description="d",
            input_schema={"type": "object"},
        )


@pytest.mark.asyncio
async def test_extraction_lets_haiku_5_5_think_before_calling_the_tool():
    """A forced tool call skips thinking; extraction uses auto + an explicit effort."""
    messages = _FakeAnthropicMessages({"offerings": []}, model="claude-haiku-5-5")
    client = AnthropicClient(
        api_key="sk-test", model="claude-haiku-5-5", sdk_client=_FakeAnthropicClient(messages)
    )
    await client.extract_offerings(html="<p/>", url="u", site_name="s")

    [call] = messages.calls
    assert call["tool_choice"] == {"type": "auto"}
    assert call["output_config"] == {"effort": "medium"}
    assert call["max_tokens"] == 20000
    # Nothing Haiku 5.5 rejects with a 400.
    for rejected in ("temperature", "top_p", "top_k", "thinking", "fallbacks"):
        assert rejected not in call
    assert call["messages"][-1]["role"] == "user"  # no prefill


@pytest.mark.asyncio
async def test_extraction_on_haiku_4_5_sends_the_old_forced_request():
    """Haiku 4.5 400s on `effort`, and setting YAS_LLM_EXTRACTION_MODEL back to it
    is the rollback, so it must get exactly the pre-5.5 request."""
    messages = _FakeAnthropicMessages({"offerings": []})
    client = AnthropicClient(
        api_key="sk-test",
        model="claude-haiku-4-5-20251001",
        sdk_client=_FakeAnthropicClient(messages),
    )
    await client.extract_offerings(html="<p/>", url="u", site_name="s")

    [call] = messages.calls
    assert call["tool_choice"] == {"type": "tool", "name": "report_offerings"}
    assert "output_config" not in call


@pytest.mark.asyncio
async def test_call_tool_stays_forced_on_haiku_5_5():
    """The 256-token digest top-line can't afford thinking."""
    messages = _FakeAnthropicMessages({"top_line": "x"}, model="claude-haiku-5-5")
    client = AnthropicClient(
        api_key="sk-test", model="claude-haiku-5-5", sdk_client=_FakeAnthropicClient(messages)
    )
    await client.call_tool(
        system="s",
        user="u",
        tool_name="report_offerings",
        tool_description="d",
        input_schema={"type": "object"},
        max_tokens=256,
    )

    [call] = messages.calls
    assert call["tool_choice"] == {"type": "tool", "name": "report_offerings"}
    assert "output_config" not in call


@pytest.mark.asyncio
async def test_tool_input_is_found_after_thinking_blocks():
    """With thinking on, content starts with thinking blocks, so read by type, not index."""

    class _ThinkingFirst(_FakeAnthropicMessages):
        async def create(self, **kwargs):
            msg = await super().create(**kwargs)

            class _Thinking:
                type = "thinking"
                thinking = ""  # omitted by default on Haiku 5.5
                signature = "sig"

            msg.content = [_Thinking(), *msg.content]
            return msg

    tool_input = {"offerings": [{"name": "Tots", "program_type": "baseball"}]}
    fake = _FakeAnthropicClient(_ThinkingFirst(tool_input, model="claude-haiku-5-5"))
    client = AnthropicClient(api_key="sk-test", model="claude-haiku-5-5", sdk_client=fake)
    result = await client.extract_offerings(html="<p/>", url="u", site_name="s")
    assert [o.name for o in result.offerings] == ["Tots"]


def test_prompt_offers_every_program_type():
    """A hand-copied list once fell 30+ values behind the enum (no "tennis")."""
    from yas.db.models._types import ProgramType
    from yas.llm.prompt import build_extraction_prompt

    system, _ = build_extraction_prompt(html="", url="u", site_name="s")
    for t in ProgramType:
        assert t.value in system


def test_default_model_is_haiku_5_5():
    """The constructor default and the Settings default must not drift apart."""
    from yas.config import Settings

    client = AnthropicClient(api_key="sk-test", sdk_client=object())
    assert client._model == "claude-haiku-5-5"
    assert Settings.model_fields["llm_extraction_model"].default == "claude-haiku-5-5"


@pytest.mark.asyncio
async def test_call_tool_raises_when_response_truncated_by_max_tokens():
    class _TruncatedMessages(_FakeAnthropicMessages):
        async def create(self, **kwargs):
            msg = await super().create(**kwargs)
            msg.stop_reason = "max_tokens"
            return msg

    fake = _FakeAnthropicClient(messages=_TruncatedMessages({"candidates": []}))
    client = AnthropicClient(api_key="sk-test", sdk_client=fake)
    from yas.llm.client import ToolCallError

    with pytest.raises(ToolCallError, match="max_tokens"):
        await client.call_tool(
            system="s",
            user="u",
            tool_name="report_offerings",
            tool_description="d",
            input_schema={"type": "object"},
        )


@pytest.mark.asyncio
async def test_default_max_tokens_leaves_room_for_large_pages():
    """4096 truncated real listing pages; the cap must clear observed page sizes."""
    seen: dict[str, Any] = {}

    class _CapturingMessages(_FakeAnthropicMessages):
        async def create(self, **kwargs):
            seen.update(kwargs)
            return await super().create(**kwargs)

    fake = _FakeAnthropicClient(messages=_CapturingMessages({"offerings": []}))
    client = AnthropicClient(api_key="sk-test", sdk_client=fake)
    await client.extract_offerings(html="<p/>", url="u", site_name="s")
    assert seen["max_tokens"] >= 16000


@pytest.mark.asyncio
async def test_cost_is_priced_from_the_model_that_answered():
    """Pricing follows msg.model, not the Haiku rates baked in at import time."""
    fake = _FakeAnthropicClient(
        messages=_FakeAnthropicMessages(
            {"offerings": []}, model="claude-opus-5", usage_in=1_000_000, usage_out=1_000_000
        )
    )
    client = AnthropicClient(api_key="sk-test", sdk_client=fake)
    result = await client.extract_offerings(html="<p/>", url="u", site_name="s")
    # Opus 5: $5.00/MTok in + $25.00/MTok out.
    assert result.cost_usd == pytest.approx(30.0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "expected"),
    [
        # Sonnet 5's launch price became standard; the planned $3/$15 never happened.
        ("claude-sonnet-5", 2.00 + 10.00),
        # Must not fall through to the shorter claude-opus-5 prefix ($5/$25).
        ("claude-opus-5-5", 4.00 + 20.00),
    ],
)
async def test_cost_uses_the_published_rate_card(model: str, expected: float):
    fake = _FakeAnthropicClient(
        messages=_FakeAnthropicMessages(
            {"offerings": []}, model=model, usage_in=1_000_000, usage_out=1_000_000
        )
    )
    client = AnthropicClient(api_key="sk-test", sdk_client=fake)
    result = await client.extract_offerings(html="<p/>", url="u", site_name="s")
    assert result.cost_usd == pytest.approx(expected)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("usage_in", "expected"),
    [
        # At the threshold: $0.10/MTok in + $0.50/MTok out on 1M output.
        (100_000, 0.01 + 0.50),
        # One token past it, the whole call moves to $0.50/MTok in + $2.50/MTok out.
        (100_001, 100_001 * 0.50 / 1_000_000 + 2.50),
    ],
)
async def test_haiku_5_5_rate_card_steps_up_past_100k_prompt_tokens(usage_in: int, expected: float):
    fake = _FakeAnthropicClient(
        messages=_FakeAnthropicMessages(
            {"offerings": []}, model="claude-haiku-5-5", usage_in=usage_in, usage_out=1_000_000
        )
    )
    client = AnthropicClient(api_key="sk-test", sdk_client=fake)
    result = await client.extract_offerings(html="<p/>", url="u", site_name="s")
    assert result.cost_usd == pytest.approx(expected)


@pytest.mark.asyncio
async def test_unknown_model_reports_zero_cost_rather_than_guessing():
    """A missing number is honest; a plausible wrong one silently corrupts spend totals."""
    fake = _FakeAnthropicClient(
        messages=_FakeAnthropicMessages(
            {"offerings": []}, model="claude-something-unreleased", usage_in=1_000_000
        )
    )
    client = AnthropicClient(api_key="sk-test", sdk_client=fake)
    result = await client.extract_offerings(html="<p/>", url="u", site_name="s")
    assert result.cost_usd == 0.0


@pytest.mark.asyncio
async def test_error_raw_identifies_the_call_without_echoing_page_content():
    """`raw` is a diagnostic handle, not a transcript — the response echoes scraped HTML."""

    class _NoToolMessages(_FakeAnthropicMessages):
        async def create(self, **kwargs):
            msg = await super().create(**kwargs)
            msg.content = [type("_T", (), {"type": "text", "text": "SECRET_PAGE_BODY"})()]
            msg.stop_reason = "end_turn"
            msg.id = "msg_01abc"
            return msg

    fake = _FakeAnthropicClient(messages=_NoToolMessages({"offerings": []}))
    client = AnthropicClient(api_key="sk-test", sdk_client=fake)
    from yas.llm.client import ExtractionError

    with pytest.raises(ExtractionError) as ei:
        await client.extract_offerings(html="<p/>", url="u", site_name="s")
    assert "msg_01abc" in ei.value.raw
    assert "end_turn" in ei.value.raw
    assert "SECRET_PAGE_BODY" not in ei.value.raw
