"""FakeLLMClient — scripted responses for integration tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from yas.llm.client import ExtractionResult, LLMClient
from yas.llm.schemas import ExtractedOffering


@dataclass
class FakeLLMClient:
    """Return `default` unless a (url, site_name) key is registered."""

    default: list[ExtractedOffering] = field(default_factory=list)
    by_url: dict[str, list[ExtractedOffering]] = field(default_factory=dict)
    by_site: dict[str, list[ExtractedOffering]] = field(default_factory=dict)
    model: str = "fake-haiku"
    cost_usd: float = 0.0001
    call_count: int = 0
    on_call: Callable[[str, str, str], None] | None = None

    async def extract_offerings(self, *, html: str, url: str, site_name: str) -> ExtractionResult:
        self.call_count += 1
        if self.on_call:
            self.on_call(html, url, site_name)
        if url in self.by_url:
            offerings = list(self.by_url[url])
        elif site_name in self.by_site:
            offerings = list(self.by_site[site_name])
        else:
            offerings = list(self.default)
        return ExtractionResult(offerings=offerings, model=self.model, cost_usd=self.cost_usd)


# Static type assertion that FakeLLMClient satisfies the protocol.
_: LLMClient = FakeLLMClient()  # pragma: no cover
