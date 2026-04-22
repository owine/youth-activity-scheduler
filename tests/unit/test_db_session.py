import pytest
from sqlalchemy import text

from yas.db.session import create_engine_for, session_scope


@pytest.mark.asyncio
async def test_engine_executes_trivial_query(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        result = await conn.execute(text("select 1"))
        assert result.scalar() == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_session_scope_commits_on_success(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.execute(text("create table t (id integer primary key, v text)"))
    async with session_scope(engine) as session:
        await session.execute(text("insert into t (v) values ('hi')"))
    async with engine.begin() as conn:
        rows = (await conn.execute(text("select v from t"))).all()
        assert rows == [("hi",)]
    await engine.dispose()


@pytest.mark.asyncio
async def test_session_scope_rolls_back_on_error(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.execute(text("create table t (id integer primary key, v text)"))
    with pytest.raises(RuntimeError):
        async with session_scope(engine) as session:
            await session.execute(text("insert into t (v) values ('bad')"))
            raise RuntimeError("boom")
    async with engine.begin() as conn:
        rows = (await conn.execute(text("select v from t"))).all()
        assert rows == []
    await engine.dispose()
