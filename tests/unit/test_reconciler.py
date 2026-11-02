from datetime import date, time

import pytest
from sqlalchemy import select

from yas.crawl.reconciler import reconcile
from yas.db.base import Base
from yas.db.models import Kid, Match, Offering, Page, Site
from yas.db.models._types import OfferingStatus, ProgramType
from yas.db.session import create_engine_for, session_scope
from yas.llm.schemas import ExtractedOffering


async def _setup(tmp_path):
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/r.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        site = Site(name="Test", base_url="https://t")
        s.add(site)
        await s.flush()
        page = Page(site_id=site.id, url="https://t/p")
        s.add(page)
        await s.flush()
        site_id, page_id = site.id, page.id
    return engine, site_id, page_id


def _offering(name, program_type=ProgramType.soccer, start_date=None, **extra):
    return ExtractedOffering(name=name, program_type=program_type, start_date=start_date, **extra)


@pytest.mark.asyncio
async def test_empty_to_some_inserts(tmp_path):
    engine, _, page_id = await _setup(tmp_path)
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        result = await reconcile(s, page, [_offering("Kickers", start_date=date(2026, 5, 1))])
    assert len(result.new) == 1 and not result.updated and not result.withdrawn
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Offering))).scalars().all()
        assert len(rows) == 1
        assert rows[0].status == OfferingStatus.active
    await engine.dispose()


@pytest.mark.asyncio
async def test_same_key_same_fields_is_unchanged(tmp_path):
    engine, _, page_id = await _setup(tmp_path)
    o = _offering("Kickers", age_min=6, age_max=8, start_date=date(2026, 5, 1))
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        await reconcile(s, page, [o])
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        result = await reconcile(s, page, [o])
    assert result.new == [] and result.updated == [] and result.withdrawn == []
    assert len(result.unchanged) == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_same_key_different_price_triggers_update(tmp_path):
    engine, _, page_id = await _setup(tmp_path)
    key_args = dict(name="Kickers", start_date=date(2026, 5, 1))
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        await reconcile(s, page, [_offering(price_cents=8500, **key_args)])
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        result = await reconcile(s, page, [_offering(price_cents=9500, **key_args)])
    assert len(result.updated) == 1 and result.new == []
    async with session_scope(engine) as s:
        row = (await s.execute(select(Offering))).scalars().one()
        assert row.price_cents == 9500
    await engine.dispose()


@pytest.mark.asyncio
async def test_missing_key_withdraws(tmp_path):
    engine, _, page_id = await _setup(tmp_path)
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        await reconcile(s, page, [_offering("Kickers", start_date=date(2026, 5, 1))])
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        result = await reconcile(s, page, [])
    assert len(result.withdrawn) == 1
    async with session_scope(engine) as s:
        row = (await s.execute(select(Offering))).scalars().one()
        assert row.status == OfferingStatus.withdrawn
    await engine.dispose()


@pytest.mark.asyncio
async def test_different_start_dates_are_different_keys(tmp_path):
    engine, _, page_id = await _setup(tmp_path)
    o1 = _offering("Kickers", start_date=date(2026, 5, 1))
    o2 = _offering("Kickers", start_date=date(2026, 6, 1))
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        await reconcile(s, page, [o1])
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        result = await reconcile(s, page, [o2])
    assert len(result.new) == 1 and len(result.withdrawn) == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_null_start_date_matches_across_runs(tmp_path):
    engine, _, page_id = await _setup(tmp_path)
    o = _offering("Kickers", start_date=None, age_min=5, age_max=7)
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        await reconcile(s, page, [o])
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        result = await reconcile(s, page, [o])
    assert result.new == [] and result.updated == []
    assert len(result.unchanged) == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_withdrawn_reappearance_inserts_new_row(tmp_path):
    engine, _, page_id = await _setup(tmp_path)
    o = _offering("Kickers", start_date=date(2026, 5, 1))
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        await reconcile(s, page, [o])
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        await reconcile(s, page, [])  # withdraw
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        result = await reconcile(s, page, [o])  # reappear
    assert len(result.new) == 1
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Offering))).scalars().all()
        assert len(rows) == 2  # old withdrawn + new active
    await engine.dispose()


@pytest.mark.asyncio
async def test_location_name_creates_or_reuses_location(tmp_path):
    engine, _site_id, page_id = await _setup(tmp_path)
    o = _offering(
        "Kickers",
        start_date=date(2026, 5, 1),
        location_name="Lincoln Park Rec",
        location_address="123 N Clark St",
    )
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        await reconcile(s, page, [o])
    # second reconcile, same location name — should NOT create a duplicate.
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        await reconcile(s, page, [o])
    async with session_scope(engine) as s:
        from yas.db.models import Location

        rows = (await s.execute(select(Location))).scalars().all()
        assert len(rows) == 1
        assert rows[0].name == "Lincoln Park Rec"
    await engine.dispose()


async def _run(engine, page_id, extracted):
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        return await reconcile(s, page, extracted)


async def _active(engine):
    async with session_scope(engine) as s:
        rows = (
            await s.execute(select(Offering).where(Offering.status == OfferingStatus.active))
        ).scalars()
        return sorted((tuple(r.days_of_week), r.time_start) for r in rows)


def _slots(*specs):
    """Same name and start date, different weekly slots, as Johnny's Junior Jets lists."""
    return [
        _offering(
            "Junior Jets",
            program_type=ProgramType.hockey,
            start_date=date(2026, 9, 7),
            days_of_week=days,
            time_start=t,
        )
        for days, t in specs
    ]


_JETS = (
    (["wed"], time(16, 45)),
    (["sat"], time(9, 0)),
    (["sat"], time(9, 50)),
    (["sun"], time(9, 0)),
    (["sun"], time(9, 50)),
)


@pytest.mark.asyncio
async def test_same_name_slots_are_reconciled_one_to_one(tmp_path):
    """Slots sharing (name, start_date) used to collapse into one dict entry on the
    second crawl: every slot overwrote one row and the rest stayed active, stale."""
    engine, _, page_id = await _setup(tmp_path)
    first = await _run(engine, page_id, _slots(*_JETS))
    assert len(first.new) == 5

    again = await _run(engine, page_id, _slots(*_JETS))
    assert again.new == [] and again.updated == [] and again.withdrawn == []
    assert sorted(again.unchanged) == sorted(first.new)
    assert len(await _active(engine)) == 5
    await engine.dispose()


@pytest.mark.asyncio
async def test_removing_one_slot_withdraws_only_that_slot(tmp_path):
    engine, _, page_id = await _setup(tmp_path)
    await _run(engine, page_id, _slots(*_JETS))

    result = await _run(engine, page_id, _slots(*_JETS[:4]))
    assert len(result.withdrawn) == 1 and len(result.unchanged) == 4
    assert result.new == [] and result.updated == []
    assert (("sun",), time(9, 50)) not in await _active(engine)
    await engine.dispose()


@pytest.mark.asyncio
async def test_moved_slot_is_an_update_not_a_withdraw_and_new(tmp_path):
    """A slot whose time changes keeps its row (and its matches and enrollments)."""
    engine, _, page_id = await _setup(tmp_path)
    first = await _run(engine, page_id, _slots(*_JETS))

    moved = (*_JETS[:4], (["sun"], time(10, 30)))
    result = await _run(engine, page_id, _slots(*moved))
    assert result.new == [] and result.withdrawn == []
    assert len(result.updated) == 1 and len(result.unchanged) == 4
    assert result.updated[0] in first.new
    assert (("sun",), time(10, 30)) in await _active(engine)
    await engine.dispose()


@pytest.mark.asyncio
async def test_existing_duplicate_rows_are_cleaned_up(tmp_path):
    """Prod already holds same-name rows left behind by the old collapse. When the
    page now lists fewer slots, the extras are withdrawn rather than left active."""
    engine, _, page_id = await _setup(tmp_path)
    await _run(engine, page_id, _slots(*_JETS))

    result = await _run(engine, page_id, _slots(*_JETS[:2]))
    assert len(result.unchanged) == 2 and len(result.withdrawn) == 3
    assert len(await _active(engine)) == 2
    await engine.dispose()


def _cohort(name, ages, days, t):
    return _offering(
        name,
        program_type=ProgramType.baseball,
        start_date=date(2026, 3, 2),
        age_min=ages[0],
        age_max=ages[1],
        days_of_week=days,
        time_start=t,
    )


@pytest.mark.asyncio
async def test_same_slot_cohorts_keep_their_rows_when_the_page_reorders(tmp_path):
    """Two age groups in one slot under one name are not interchangeable: matches and
    enrollments hang off each row, so a reorder must not swap their details."""
    engine, _, page_id = await _setup(tmp_path)
    young = _cohort("T-Ball", (4, 5), ["mon"], time(16, 0))
    older = _cohort("T-Ball", (6, 8), ["mon"], time(16, 0))
    first = await _run(engine, page_id, [young, older])

    again = await _run(engine, page_id, [older, young])
    assert again.updated == [] and again.new == [] and again.withdrawn == []
    async with session_scope(engine) as s:
        ages = {r.id: (r.age_min, r.age_max) for r in (await s.execute(select(Offering))).scalars()}
    assert ages == {first.new[0]: (4, 5), first.new[1]: (6, 8)}
    await engine.dispose()


@pytest.mark.asyncio
async def test_moved_slots_pair_by_the_part_that_did_not_move(tmp_path):
    """Saturday and Sunday both move 9:00 -> 9:30 and the page lists Sunday first.
    Each row keeps its own day rather than pairing by row order."""
    engine, _, page_id = await _setup(tmp_path)
    first = await _run(engine, page_id, _slots((["sat"], time(9, 0)), (["sun"], time(9, 0))))
    sat_id, sun_id = first.new

    result = await _run(engine, page_id, _slots((["sun"], time(9, 30)), (["sat"], time(9, 30))))
    assert sorted(result.updated) == sorted([sat_id, sun_id])
    async with session_scope(engine) as s:
        days = {r.id: r.days_of_week for r in (await s.execute(select(Offering))).scalars()}
    assert days == {sat_id: ["sat"], sun_id: ["sun"]}
    await engine.dispose()


@pytest.mark.asyncio
async def test_withdrawing_an_offering_deletes_its_matches(tmp_path):
    """The sweep never revisits withdrawn offerings and match readers don't filter
    on offering status, so a kept match would show a removed program forever."""
    engine, _, page_id = await _setup(tmp_path)
    first = await _run(engine, page_id, _slots(*_JETS[:2]))
    kept_id, gone_id = first.new
    async with session_scope(engine) as s:
        kid = Kid(name="Sam", dob=date(2019, 1, 1))
        s.add(kid)
        await s.flush()
        s.add_all(
            [
                Match(kid_id=kid.id, offering_id=kept_id, score=0.9, reasons={}),
                Match(kid_id=kid.id, offering_id=gone_id, score=0.9, reasons={}),
            ]
        )

    result = await _run(engine, page_id, _slots(*_JETS[:1]))
    assert result.withdrawn == [gone_id]
    async with session_scope(engine) as s:
        remaining = [m.offering_id for m in (await s.execute(select(Match))).scalars()]
    assert remaining == [kept_id]
    await engine.dispose()


@pytest.mark.asyncio
async def test_a_dropped_cohort_withdraws_its_own_row_not_its_neighbours(tmp_path):
    """Two cohorts share a slot; the page drops the younger one and edits the older
    one's end date, so the most specific tier misses. Pairing must still go by age:
    rewriting the younger row as the older cohort would move its enrollments."""
    engine, _, page_id = await _setup(tmp_path)
    young = _cohort("T-Ball", (5, 7), ["mon"], time(9, 0))
    older = _cohort("T-Ball", (8, 10), ["mon"], time(9, 0))
    young_id, older_id = (await _run(engine, page_id, [young, older])).new

    edited = older.model_copy(update={"end_date": date(2026, 6, 1)})
    result = await _run(engine, page_id, [edited])
    assert result.updated == [older_id]
    assert result.withdrawn == [young_id]
    await engine.dispose()


@pytest.mark.asyncio
async def test_slots_that_shift_together_keep_their_rows(tmp_path):
    """Mon 9:00 and Mon 10:00 both move half an hour, and the page lists the later
    one first. Ages can't tell them apart, so pairing goes by schedule order."""
    engine, _, page_id = await _setup(tmp_path)
    nine_id, ten_id = (
        await _run(engine, page_id, _slots((["mon"], time(9, 0)), (["mon"], time(10, 0))))
    ).new

    result = await _run(engine, page_id, _slots((["mon"], time(10, 30)), (["mon"], time(9, 30))))
    assert sorted(result.updated) == sorted([nine_id, ten_id])
    async with session_scope(engine) as s:
        starts = {r.id: r.time_start for r in (await s.execute(select(Offering))).scalars()}
    assert starts == {nine_id: time(9, 30), ten_id: time(10, 30)}
    await engine.dispose()


@pytest.mark.asyncio
async def test_a_dropped_slot_among_shifting_slots_withdraws_its_own_row(tmp_path):
    """9:00, 10:00, 11:00 become 10:15 and 11:15: 9:00 was dropped and the rest moved.
    The 9:00 row is the one withdrawn; the others keep their own rows."""
    engine, _, page_id = await _setup(tmp_path)
    nine, ten, eleven = (
        await _run(
            engine,
            page_id,
            _slots((["mon"], time(9, 0)), (["mon"], time(10, 0)), (["mon"], time(11, 0))),
        )
    ).new

    result = await _run(engine, page_id, _slots((["mon"], time(11, 15)), (["mon"], time(10, 15))))
    assert result.withdrawn == [nine]
    async with session_scope(engine) as s:
        starts = {
            r.id: r.time_start
            for r in (await s.execute(select(Offering))).scalars()
            if r.status == OfferingStatus.active
        }
    assert starts == {ten: time(10, 15), eleven: time(11, 15)}
    await engine.dispose()
