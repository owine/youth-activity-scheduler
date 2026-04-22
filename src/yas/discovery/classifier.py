"""LLM classifier that scores discovery candidates 0-1 for program-detail fit.

Uses Claude Haiku via the existing AnthropicClient.call_tool path with a
discovery-specific prompt and Pydantic schema. Hallucinated URLs are
dropped; missing input URLs implicitly score 0.0."""

from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yas.discovery.heads import HeadInfo
from yas.logging import get_logger

log = get_logger("yas.discovery.classifier")


class ScoredCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    score: float = Field(ge=0.0, le=1.0)
    reason: str


class ClassificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidates: list[ScoredCandidate]


class ClassificationError(Exception):
    def __init__(self, raw: str, detail: str):
        super().__init__(detail)
        self.raw = raw
        self.detail = detail


class ClassifierLLMClient(Protocol):
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


_SYSTEM = """You classify pages on a youth activity / sports / enrichment site.
Given a list of URLs with titles, meta descriptions, and kind (html or pdf),
identify pages that contain actual program or schedule DETAIL — dates, ages,
times, prices, registration info.

Reject: navigation/landing pages, "our programs" overviews without details,
registration routers (the /register/ page itself), news/blog posts, team
rosters, "about us" / "contact" / "policies" pages, login/account pages,
homepages unless they clearly ARE the schedule.

For each URL, assign a score in [0.0, 1.0] and a one-line reason. Prefer
precision over recall — missing a page is better than recommending a bad one.

Call `report_candidates` with your ranked list. Do not invent URLs not in
the input."""


def build_classifier_prompt(candidates: list[HeadInfo], *, site_name: str) -> tuple[str, str]:
    items = [
        {
            "url": c.url,
            "title": c.title,
            "meta": c.meta_description,
            "kind": c.kind,
            "anchor_text": c.anchor_text,
        }
        for c in candidates
    ]
    user = (
        f"Site: {site_name}\n\n"
        f"Candidates (JSON):\n{json.dumps(items, indent=2, ensure_ascii=False)}"
    )
    return _SYSTEM, user


def _tool_schema() -> dict[str, Any]:
    return ClassificationResponse.model_json_schema()


async def classify_candidates(
    candidates: list[HeadInfo],
    *,
    llm_client: ClassifierLLMClient,
    site_name: str,
) -> list[ScoredCandidate]:
    if not candidates:
        return []

    system, user = build_classifier_prompt(candidates, site_name=site_name)
    tool_input, model, cost_usd = await llm_client.call_tool(
        system=system,
        user=user,
        tool_name="report_candidates",
        tool_description="Report the scored list of discovery candidates.",
        input_schema=_tool_schema(),
    )
    try:
        parsed = ClassificationResponse.model_validate(tool_input)
    except ValidationError as exc:
        raise ClassificationError(raw=str(tool_input), detail=str(exc)) from exc

    log.info(
        "discovery.classifier.call",
        model=model,
        cost_usd=cost_usd,
        candidates_in=len(candidates),
        scored_out=len(parsed.candidates),
    )

    valid_urls = {c.url for c in candidates}
    by_url: dict[str, ScoredCandidate] = {}
    for sc in parsed.candidates:
        if sc.url not in valid_urls:
            log.warning("discovery.classifier.hallucinated_url", url=sc.url)
            continue
        by_url[sc.url] = sc

    # Fill zero-score defaults for any input URL the model didn't rate.
    result: list[ScoredCandidate] = []
    for c in candidates:
        existing = by_url.get(c.url)
        if existing is not None:
            result.append(existing)
        else:
            result.append(ScoredCandidate(url=c.url, score=0.0, reason="not scored"))
    return result
