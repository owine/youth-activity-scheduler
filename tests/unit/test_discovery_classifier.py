import pytest

from yas.discovery.classifier import (
    ClassificationError,
    ScoredCandidate,
    build_classifier_prompt,
    classify_candidates,
)
from yas.discovery.heads import HeadInfo


def _head(url: str, title: str = "", meta: str | None = None, kind: str = "html",
          anchor: str | None = None) -> HeadInfo:
    return HeadInfo(url=url, title=title, meta_description=meta, kind=kind, anchor_text=anchor)


def test_prompt_mentions_html_and_pdf_and_anchor_text():
    system, user = build_classifier_prompt(
        [_head("https://x/a", "Summer Camps"),
         _head("https://x/b.pdf", "spring.pdf", kind="pdf"),
         _head("https://x/c", "Programs", anchor="Our Programs")],
        site_name="X",
    )
    assert "report_candidates" in system
    assert "program or schedule" in system.lower()
    # User payload has each URL/title.
    assert "https://x/a" in user
    assert "Summer Camps" in user
    assert "https://x/b.pdf" in user
    assert "pdf" in user.lower()
    assert "https://x/c" in user
    assert "Our Programs" in user


class _FakeClient:
    """Duck-typed to satisfy the minimal surface classifier uses on AnthropicClient."""

    def __init__(self, canned_input: dict):
        self.canned = canned_input

    async def call_tool(self, **_: object) -> tuple[dict, str, float]:
        # Return (tool_input, model_name, cost_usd)
        return self.canned, "fake-haiku", 0.002


@pytest.mark.asyncio
async def test_classify_filters_hallucinated_urls(monkeypatch):
    candidates = [_head("https://x/a", "A"), _head("https://x/b", "B")]
    canned = {
        "candidates": [
            {"url": "https://x/a", "score": 0.9, "reason": "looks like program page"},
            {"url": "https://x/HALLUCINATED", "score": 1.0, "reason": "nonexistent URL"},
        ],
    }
    client = _FakeClient(canned)
    results = await classify_candidates(candidates, llm_client=client, site_name="X")
    # Hallucinated URL dropped; a->0.9 kept, b->0.0 implicit default
    urls = {r.url: r.score for r in results}
    assert urls == {"https://x/a": 0.9, "https://x/b": 0.0}


@pytest.mark.asyncio
async def test_classify_scores_zero_for_missing_urls():
    candidates = [_head("https://x/a"), _head("https://x/b"), _head("https://x/c")]
    canned = {
        "candidates": [
            {"url": "https://x/a", "score": 0.5, "reason": "maybe"},
        ],
    }
    client = _FakeClient(canned)
    results = await classify_candidates(candidates, llm_client=client, site_name="X")
    score_by_url = {r.url: r.score for r in results}
    assert score_by_url["https://x/a"] == 0.5
    assert score_by_url["https://x/b"] == 0.0
    assert score_by_url["https://x/c"] == 0.0


@pytest.mark.asyncio
async def test_classify_raises_on_invalid_tool_input():
    candidates = [_head("https://x/a")]
    # Missing required "reason" field and score out of range.
    bad = {"candidates": [{"url": "https://x/a", "score": 5.0}]}
    client = _FakeClient(bad)
    with pytest.raises(ClassificationError):
        await classify_candidates(candidates, llm_client=client, site_name="X")


@pytest.mark.asyncio
async def test_classify_empty_input_returns_empty():
    client = _FakeClient({"candidates": []})
    results = await classify_candidates([], llm_client=client, site_name="X")
    assert results == []


def test_scored_candidate_validates_score_range():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ScoredCandidate(url="https://x", score=1.5, reason="bad")
