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

    async def create(self, **_kwargs):
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
