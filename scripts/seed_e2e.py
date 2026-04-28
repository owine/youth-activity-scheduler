"""Seed deterministic e2e fixtures into a fresh DB."""

import asyncio
from datetime import UTC, datetime, timedelta

from yas.db.base import Base
from yas.db.models import (
    Alert,
    CrawlRun,
    HouseholdSettings,
    Kid,
    Match,
    Offering,
    Page,
    Site,
)
from yas.db.models._types import AlertType, CrawlStatus, PageKind
from yas.db.session import create_engine_for, session_scope


async def main(db_url: str) -> None:
    engine = create_engine_for(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    now = datetime.now(UTC)
    async with session_scope(engine) as s:
        s.add(HouseholdSettings(id=1, default_max_distance_mi=20.0))
        s.add(Kid(id=1, name="Sam", dob=datetime(2019, 5, 1).date()))
        s.add(Site(id=1, name="Lil Sluggers", base_url="https://x", needs_browser=False))
        await s.flush()
        s.add(
            Page(
                id=1,
                site_id=1,
                url="https://x/schedule",
                kind=PageKind.schedule.value,
            )
        )
        await s.flush()
        s.add(
            Offering(
                id=1,
                site_id=1,
                page_id=1,
                name="Spring T-Ball",
                normalized_name="spring-t-ball",
                start_date=(now + timedelta(days=14)).date(),
                registration_opens_at=now + timedelta(days=1),
                status="active",
            )
        )
        await s.flush()
        s.add(
            Match(
                kid_id=1,
                offering_id=1,
                score=0.94,
                reasons={"watchlist": True},
                computed_at=now,
            )
        )
        s.add(
            Alert(
                type=AlertType.watchlist_hit.value,
                kid_id=1,
                site_id=1,
                channels=["email"],
                scheduled_for=now - timedelta(hours=1),
                dedup_key="seed-1",
                payload_json={"offering_name": "Spring T-Ball", "site_name": "Lil Sluggers"},
            )
        )
        s.add(
            CrawlRun(
                site_id=1,
                started_at=now - timedelta(hours=2),
                finished_at=now - timedelta(hours=2, minutes=-1),
                status=CrawlStatus.ok.value,
                pages_fetched=3,
                changes_detected=1,
                llm_calls=0,
                llm_cost_usd=0.0,
            )
        )
    await engine.dispose()


if __name__ == "__main__":
    import sys

    asyncio.run(main(sys.argv[1]))
