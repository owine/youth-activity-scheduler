import httpx
import pytest

from tests.fixtures.server import fixture_site, load_fixture


@pytest.mark.asyncio
async def test_fixture_site_serves_pages():
    html = load_fixture("lilsluggers/spring-session-24.html")
    async with fixture_site(pages={"/spring": html}) as site:
        async with httpx.AsyncClient() as c:
            r = await c.get(site.url("/spring"))
        assert r.status_code == 200
        assert "Session" in r.text or "session" in r.text


@pytest.mark.asyncio
async def test_fixture_site_404s_unknown_path():
    async with fixture_site() as site:
        async with httpx.AsyncClient() as c:
            r = await c.get(site.url("/missing"))
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_fixture_site_mutation_changes_content():
    async with fixture_site(pages={"/x": "<p>a</p>"}) as site:
        async with httpx.AsyncClient() as c:
            r1 = await c.get(site.url("/x"))
            site.set_page("/x", "<p>b</p>")
            r2 = await c.get(site.url("/x"))
    assert "a" in r1.text and "b" in r2.text
