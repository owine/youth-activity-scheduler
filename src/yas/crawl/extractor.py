"""Cache-aware LLM extraction.

Opens its own short-lived session for extraction_cache IO; independent of the
pipeline's reconcile session. A cache entry written during a run where the
reconciler later errors stays written — intentional, so retries don't re-bill."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.crawl.change_detector import content_hash, normalize
from yas.db.models import ExtractionCache
from yas.db.session import session_scope
from yas.llm.client import LLMClient
from yas.llm.schemas import ExtractedOffering


@dataclass(frozen=True)
class ExtractionResult:
    offerings: list[ExtractedOffering]
    content_hash: str
    from_cache: bool
    model: str | None        # None when from_cache=True
    cost_usd: float          # 0.0 when from_cache=True


async def extract(
    *,
    engine: AsyncEngine,
    llm: LLMClient,
    html: str,
    url: str,
    site_name: str,
) -> ExtractionResult:
    norm = normalize(html)
    h = content_hash(norm)

    # Look up cache.
    async with session_scope(engine) as s:
        cached = (
            await s.execute(select(ExtractionCache).where(ExtractionCache.content_hash == h))
        ).scalar_one_or_none()
    if cached is not None:
        offerings = [ExtractedOffering.model_validate(o) for o in cached.extracted_json.get("offerings", [])]
        return ExtractionResult(
            offerings=offerings,
            content_hash=h,
            from_cache=True,
            model=None,
            cost_usd=0.0,
        )

    # Cache miss — call LLM.
    result = await llm.extract_offerings(html=norm, url=url, site_name=site_name)

    # Persist to cache.
    async with session_scope(engine) as s:
        s.add(
            ExtractionCache(
                content_hash=h,
                extracted_json={
                    "offerings": [
                        json.loads(o.model_dump_json()) for o in result.offerings
                    ]
                },
                llm_model=result.model,
                cost_usd=result.cost_usd,
            )
        )

    return ExtractionResult(
        offerings=list(result.offerings),
        content_hash=h,
        from_cache=False,
        model=result.model,
        cost_usd=result.cost_usd,
    )
