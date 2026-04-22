"""Orchestrator: seed → sitemap + links → filter → heads → classify → filter + cap."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from yas.config import Settings
from yas.discovery.classifier import ClassificationError, classify_candidates
from yas.discovery.filters import is_junk
from yas.discovery.heads import HeadInfo, scrape_heads_concurrently
from yas.discovery.links import extract_internal_links
from yas.discovery.sitemap import fetch_sitemap_urls
from yas.logging import get_logger

log = get_logger("yas.discovery")


@dataclass(frozen=True)
class DiscoveryStats:
    sitemap_urls: int
    link_urls: int
    filtered_junk: int
    fetched_heads: int
    classified: int
    returned: int


@dataclass(frozen=True)
class DiscoveryCandidate:
    url: str
    title: str
    kind: Literal["html", "pdf"]
    score: float
    reason: str


@dataclass(frozen=True)
class DiscoveryResult:
    site_id: int
    seed_url: str
    stats: DiscoveryStats
    candidates: list[DiscoveryCandidate] = field(default_factory=list)


class DiscoveryError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


async def discover_site(
    *,
    site: Any,  # duck-typed: needs .id, .name, .base_url
    http_client: httpx.AsyncClient,
    llm_client: Any,  # duck-typed: ClassifierLLMClient
    settings: Settings,
    min_score: float | None = None,
    max_candidates: int | None = None,
) -> DiscoveryResult:
    min_score_f = min_score if min_score is not None else settings.discovery_min_score
    max_out = max_candidates if max_candidates is not None else settings.discovery_max_returned

    # 1. Seed fetch.
    try:
        r = await http_client.get(site.base_url, timeout=settings.discovery_head_fetch_timeout_s)
    except httpx.TransportError as exc:
        raise DiscoveryError("seed_fetch_failed", str(exc)) from exc
    if r.status_code >= 400:
        raise DiscoveryError("seed_fetch_failed", f"status={r.status_code}")
    seed_html = r.text

    # 2. Sitemap + link extraction in parallel.
    sitemap_task = asyncio.create_task(fetch_sitemap_urls(site.base_url, http_client=http_client))
    link_pairs = extract_internal_links(seed_html, site.base_url)
    sitemap_urls = await sitemap_task

    # 3. Union with sitemap-first ordering; capture anchor text from link side.
    link_anchor_by_url = dict(link_pairs)
    union_ordered: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for url in sitemap_urls:
        if url in seen:
            continue
        seen.add(url)
        union_ordered.append((url, link_anchor_by_url.get(url)))
    for url, anchor in link_pairs:
        if url in seen:
            continue
        seen.add(url)
        union_ordered.append((url, anchor))

    # 4. Junk filter.
    filtered_out = 0
    kept: list[tuple[str, str | None]] = []
    for u, a in union_ordered:
        if is_junk(u):
            filtered_out += 1
            continue
        kept.append((u, a))

    # 5. Pre-LLM cap.
    capped = kept[: settings.discovery_max_candidates]

    # 6. Head scrape.
    head_results = await scrape_heads_concurrently(
        capped,
        http_client=http_client,
        timeout_s=settings.discovery_head_fetch_timeout_s,
        concurrency=settings.discovery_head_fetch_concurrency,
    )
    heads: list[HeadInfo] = [h for h in head_results if h is not None]

    # 7. Classify.
    try:
        scored = await classify_candidates(heads, llm_client=llm_client, site_name=site.name)
    except ClassificationError as exc:
        raise DiscoveryError("classification_failed", exc.detail) from exc

    # 8. Filter by min_score and cap.
    by_url = {h.url: h for h in heads}
    enriched = [(by_url[sc.url], sc) for sc in scored if sc.url in by_url]
    enriched.sort(key=lambda pair: pair[1].score, reverse=True)
    out: list[DiscoveryCandidate] = []
    for head, sc in enriched:
        if sc.score < min_score_f:
            continue
        out.append(
            DiscoveryCandidate(
                url=head.url,
                title=head.title,
                kind=head.kind,
                score=sc.score,
                reason=sc.reason,
            )
        )
        if len(out) >= max_out:
            break

    stats = DiscoveryStats(
        sitemap_urls=len(sitemap_urls),
        link_urls=len(link_pairs),
        filtered_junk=filtered_out,
        fetched_heads=len(heads),
        classified=len(scored),
        returned=len(out),
    )
    log.info("discovery.complete", site_id=site.id, **vars(stats))
    return DiscoveryResult(site_id=site.id, seed_url=site.base_url, stats=stats, candidates=out)
