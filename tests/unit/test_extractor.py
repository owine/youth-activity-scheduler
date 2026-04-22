import pytest
from sqlalchemy import select

from tests.fakes.llm import FakeLLMClient
from yas.crawl.change_detector import content_hash, normalize
from yas.crawl.extractor import extract
from yas.db.base import Base
from yas.db.models import ExtractionCache
from yas.db.models._types import ProgramType
from yas.db.session import create_engine_for, session_scope
from yas.llm.schemas import ExtractedOffering

PAGE = "<html><body><main><h1>Soccer</h1><p>Saturdays 9am</p></main></body></html>"


async def _mk_engine(tmp_path):
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/e.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


@pytest.mark.asyncio
async def test_extract_calls_llm_on_cache_miss(tmp_path):
    engine = await _mk_engine(tmp_path)
    llm = FakeLLMClient(default=[ExtractedOffering(name="Soccer", program_type=ProgramType.soccer)])
    result = await extract(engine=engine, llm=llm, html=PAGE, url="u", site_name="s")
    assert result.from_cache is False
    assert len(result.offerings) == 1
    assert llm.call_count == 1
    assert result.model == "fake-haiku"
    # cache row written
    async with session_scope(engine) as s:
        rows = (await s.execute(select(ExtractionCache))).scalars().all()
        assert len(rows) == 1
        assert rows[0].content_hash == content_hash(normalize(PAGE))
    await engine.dispose()


@pytest.mark.asyncio
async def test_extract_returns_cached_on_hit(tmp_path):
    engine = await _mk_engine(tmp_path)
    llm = FakeLLMClient(default=[ExtractedOffering(name="Soccer", program_type=ProgramType.soccer)])
    # prime
    await extract(engine=engine, llm=llm, html=PAGE, url="u", site_name="s")
    assert llm.call_count == 1
    # hit
    result = await extract(engine=engine, llm=llm, html=PAGE, url="u", site_name="s")
    assert result.from_cache is True
    assert result.cost_usd == 0.0
    assert result.model is None
    assert llm.call_count == 1  # not called again
    assert [o.name for o in result.offerings] == ["Soccer"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_extract_propagates_extraction_error(tmp_path):
    engine = await _mk_engine(tmp_path)

    class _BadLLM:
        async def extract_offerings(self, *, html, url, site_name):
            from yas.llm.client import ExtractionError

            raise ExtractionError(raw="{}", detail="nope")

    from yas.llm.client import ExtractionError

    with pytest.raises(ExtractionError):
        await extract(engine=engine, llm=_BadLLM(), html=PAGE, url="u", site_name="s")

    # no cache row written on failure
    async with session_scope(engine) as s:
        rows = (await s.execute(select(ExtractionCache))).scalars().all()
        assert rows == []
    await engine.dispose()
