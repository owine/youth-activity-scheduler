# Phase 2 — Crawl Pipeline MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use @superpowers:subagent-driven-development (recommended) or @superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Follow @superpowers:test-driven-development throughout. Apply @superpowers:verification-before-completion before marking any task done.

**Goal:** Stand up an end-to-end crawl pipeline that, given a site URL via HTTP API, fetches the page on a fixed cadence, detects change by content hash, calls Claude Haiku to extract structured offerings against a strict Pydantic schema, caches the extraction so unchanged pages never re-call the API, reconciles new/updated/withdrawn offerings against prior state, and records everything in `crawl_runs`.

**Architecture:** Single worker process hosts two `asyncio` tasks inside one `TaskGroup`: the Phase 1 heartbeat loop, and a new scheduler loop that selects due pages and dispatches them through `pipeline.crawl_page`, which composes `fetcher → change_detector → extractor (with extraction_cache) → reconciler`. Fetcher owns one shared `httpx.AsyncClient` and one lazily-launched Playwright Chromium browser. Site registration goes through a new `/api/sites` FastAPI router.

**Tech Stack:** Python 3.12, Anthropic SDK (Haiku, tool-use), SQLAlchemy 2.0 async, Pydantic V2, httpx, Playwright Chromium, selectolax (HTML parser), aiohttp (test fixture server), FastAPI, pytest + pytest-asyncio + respx.

**Reference spec:** `docs/superpowers/specs/2026-04-22-phase-2-crawl-pipeline-design.md`. Parent spec: `docs/superpowers/specs/2026-04-21-youth-activity-scheduler-design.md` §4.

---

## Deliverables (phase exit criteria)

- `uv run pytest` green; new tests exercise every new module
- `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` clean
- `docker compose up -d`: three services healthy; `POST /api/sites` registering the Lil Sluggers URL produces at least one real offering within 90 s of the scheduler tick
- `llm_cost_usd > 0` on first crawl; `llm_calls = 0` on a second crawl of the unchanged page (cache hit)
- Every fetch/extract failure lands in `crawl_runs.error_text` — no silent failures
- `GET /docs` lists all 7 site-management endpoints
- `scripts/smoke_phase2.sh` passes end-to-end with a real `YAS_ANTHROPIC_API_KEY`

## Conventions

- **Branch:** create and work on `phase-2-crawl-pipeline` off `main` (do NOT commit to `main`). Final merge with `--no-ff`.
- **TDD discipline:** failing test → verify fails → implement → verify passes → commit, one task at a time.
- **Commits:** conventional style. One commit per task unless a reviewer-driven fix justifies a second.
- **Imports:** absolute (`from yas.x import y`). Tests under `tests/` follow existing pyproject mypy override (relaxed).
- **Pydantic V2 everywhere** — `ConfigDict(extra="forbid")` on extraction schemas, `model_config` not `Config`.
- **Timestamps** tz-aware UTC; never naive datetimes in Python.
- **Under mypy strict:** if a `# type: ignore[...]` is flagged unused, remove it. We've seen this repeatedly.
- **Git signing via 1Password SSH:** if a commit fails with "1Password: failed to fill whole buffer", stop and surface it — do not retry repeatedly.

---

## File structure delta (target state after Phase 2)

```
src/yas/
├── crawl/                    # NEW package
│   ├── __init__.py
│   ├── normalize.py          # normalize_name() — shared with matcher (Phase 3)
│   ├── change_detector.py    # normalize() + content_hash()
│   ├── fetcher.py            # DefaultFetcher (httpx + Playwright)
│   ├── extractor.py          # extract() with extraction_cache lookup
│   ├── reconciler.py         # reconcile() → new/updated/withdrawn/unchanged
│   ├── scheduler.py          # crawl_scheduler_loop()
│   └── pipeline.py           # crawl_page() orchestrator
├── llm/                      # NEW package
│   ├── __init__.py
│   ├── schemas.py            # ExtractedOffering, ExtractionResponse
│   ├── prompt.py             # build_extraction_prompt()
│   └── client.py             # LLMClient protocol + AnthropicClient
├── web/
│   ├── app.py                # MODIFIED — mount site-management router, add fetcher+llm to AppState
│   ├── deps.py               # MODIFIED — AppState carries fetcher+llm
│   └── routes/               # NEW package
│       ├── __init__.py
│       ├── sites.py          # /api/sites + /api/sites/{id}/pages
│       └── sites_schemas.py  # Pydantic request/response models
├── worker/
│   └── runner.py             # MODIFIED — TaskGroup with heartbeat + scheduler
├── config.py                 # MODIFIED — crawl_scheduler_* + llm_extraction_model
├── db/models/_types.py       # MODIFIED — add DayOfWeek enum
└── __main__.py               # MODIFIED — pass fetcher+llm through to run_worker

tests/
├── fakes/                    # NEW
│   └── llm.py                # FakeLLMClient
├── fixtures/                 # NEW
│   ├── server.py             # aiohttp FixtureSite
│   └── sites/
│       └── lilsluggers/
│           └── spring-session-24.html   # captured snapshot
├── unit/
│   ├── test_normalize.py
│   ├── test_change_detector.py
│   ├── test_llm_schemas.py
│   ├── test_llm_prompt.py
│   ├── test_llm_client.py
│   ├── test_extractor.py
│   ├── test_reconciler.py
│   └── test_fetcher.py
└── integration/
    ├── test_pipeline.py
    ├── test_scheduler.py
    ├── test_api_sites.py
    └── test_playwright_fetcher.py

scripts/
└── smoke_phase2.sh           # NEW

pyproject.toml                # MODIFIED — deps
Dockerfile                    # MODIFIED — playwright install
.env.example                  # MODIFIED — new YAS_ vars
```

---

## Task 1 — Branch, dependencies, and config additions

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/yas/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Cut the feature branch**

```bash
cd /Users/owine/Git/youth-activity-scheduler
git checkout main
git pull --ff-only origin main 2>/dev/null || true   # no remote yet — harmless
git checkout -b phase-2-crawl-pipeline
```

- [ ] **Step 2: Add runtime + dev dependencies**

Edit `pyproject.toml`:

In `[project].dependencies`, add:
```
  "selectolax>=0.3.21",
  "playwright>=1.42.0",
```

In `[dependency-groups].dev`, add:
```
  "aiohttp>=3.9.0",
```

Then sync:
```bash
uv sync
```

Expected: new packages resolved. `selectolax` provides a fast C-based HTML parser. `playwright` provides the Python client; the browser binaries are installed at runtime (see Task 12).

- [ ] **Step 3: Write a failing test for the new config fields**

`tests/unit/test_config.py` — append these tests:

```python
def test_crawl_scheduler_defaults(monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.crawl_scheduler_enabled is True
    assert s.crawl_scheduler_tick_s == 30
    assert s.crawl_scheduler_batch_size == 10
    assert s.llm_extraction_model == "claude-haiku-4-5-20251001"


def test_crawl_scheduler_overrides(monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("YAS_CRAWL_SCHEDULER_TICK_S", "5")
    monkeypatch.setenv("YAS_CRAWL_SCHEDULER_BATCH_SIZE", "3")
    monkeypatch.setenv("YAS_CRAWL_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("YAS_LLM_EXTRACTION_MODEL", "claude-sonnet-4-6")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.crawl_scheduler_tick_s == 5
    assert s.crawl_scheduler_batch_size == 3
    assert s.crawl_scheduler_enabled is False
    assert s.llm_extraction_model == "claude-sonnet-4-6"
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: new tests fail with `AttributeError: 'Settings' object has no attribute 'crawl_scheduler_tick_s'`.

- [ ] **Step 5: Add the fields**

Edit `src/yas/config.py` — add to the `Settings` class (alongside the existing worker fields):

```python
    # Crawl scheduler
    crawl_scheduler_enabled: bool = True
    crawl_scheduler_tick_s: int = 30
    crawl_scheduler_batch_size: int = 10

    # LLM extraction
    llm_extraction_model: str = "claude-haiku-4-5-20251001"
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_config.py -v
uv run ruff check .
uv run mypy src
```

Expected: all green.

- [ ] **Step 7: Update `.env.example`**

Append:
```
# Crawl scheduler
# YAS_CRAWL_SCHEDULER_TICK_S=30
# YAS_CRAWL_SCHEDULER_BATCH_SIZE=10
# YAS_CRAWL_SCHEDULER_ENABLED=true

# LLM
# YAS_LLM_EXTRACTION_MODEL=claude-haiku-4-5-20251001
```

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock src/yas/config.py tests/unit/test_config.py .env.example
git commit -m "chore: add selectolax+playwright+aiohttp deps and phase-2 settings"
```

---

## Task 2 — Name normalization + HTML change detector

**Files:**
- Create: `src/yas/crawl/__init__.py`
- Create: `src/yas/crawl/normalize.py`
- Create: `src/yas/crawl/change_detector.py`
- Create: `tests/unit/test_normalize.py`
- Create: `tests/unit/test_change_detector.py`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_normalize.py`:
```python
from yas.crawl.normalize import normalize_name


def test_normalize_name_lowercases():
    assert normalize_name("Little Kickers") == "little kickers"


def test_normalize_name_strips_punctuation():
    assert normalize_name("Soccer: Saturday!") == "soccer saturday"


def test_normalize_name_collapses_whitespace():
    assert normalize_name("  many   spaces\tand\n\nnewlines ") == "many spaces and newlines"


def test_normalize_name_handles_empty():
    assert normalize_name("") == ""
    assert normalize_name("   ") == ""
```

`tests/unit/test_change_detector.py`:
```python
from yas.crawl.change_detector import content_hash, normalize


BASE = """<!doctype html>
<html><head><title>x</title></head>
<body>
<header><nav>Home | About</nav></header>
<main>
  <h1>Spring Soccer</h1>
  <p>Ages 6-8 on Saturday 9am.</p>
</main>
<footer>&copy; 2026</footer>
<script>console.log('never');</script>
</body></html>
"""


def test_normalize_strips_nav_footer_script():
    out = normalize(BASE)
    assert "Home | About" not in out
    assert "&copy; 2026" not in out
    assert "console.log" not in out
    assert "Spring Soccer" in out
    assert "Ages 6-8 on Saturday 9am." in out


def test_normalize_collapses_whitespace():
    noisy = "<main><p>a</p>\n\n   <p>b</p>\t<p>  c  </p></main>"
    assert normalize(noisy).split() == ["a", "b", "c"]


def test_normalize_removes_data_and_aria_and_style():
    html = """<main><div data-test="x" aria-hidden="true" style="color:red">hi</div></main>"""
    out = normalize(html)
    # Content preserved; attribute values dropped.
    assert "hi" in out
    assert "data-test" not in out
    assert "aria-hidden" not in out
    assert "color:red" not in out


def test_normalize_drops_noise_classes():
    html = """<main>
      <div class="cookie-banner">accept</div>
      <div class="timestamp">2026-04-22T12:34</div>
      <p class="content">real</p>
    </main>"""
    out = normalize(html)
    assert "accept" not in out
    assert "2026-04-22" not in out
    assert "real" in out


def test_content_hash_stable_across_irrelevant_changes():
    a = normalize(BASE)
    bumped = BASE.replace("<footer>&copy; 2026</footer>", "<footer>&copy; 2027</footer>")
    b = normalize(bumped)
    assert content_hash(a) == content_hash(b)


def test_content_hash_changes_with_real_content():
    a = normalize(BASE)
    different = BASE.replace("Spring Soccer", "Summer Soccer")
    b = normalize(different)
    assert content_hash(a) != content_hash(b)


def test_content_hash_deterministic_across_calls():
    a = normalize(BASE)
    assert content_hash(a) == content_hash(a)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_normalize.py tests/unit/test_change_detector.py -v`
Expected: import errors.

- [ ] **Step 3: Create `src/yas/crawl/__init__.py`**

Empty file.

- [ ] **Step 4: Implement `src/yas/crawl/normalize.py`**

```python
"""Name normalization shared by the reconciler (today) and the matcher (Phase 3)."""

from __future__ import annotations

import re

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def normalize_name(s: str) -> str:
    """lowercase → strip punctuation → collapse whitespace → trim."""
    s = s.lower()
    s = _PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s
```

- [ ] **Step 5: Implement `src/yas/crawl/change_detector.py`**

```python
"""HTML normalization + content hashing for cheap change detection."""

from __future__ import annotations

import hashlib
import re

from selectolax.parser import HTMLParser

_NOISE_TAGS = ("script", "style", "noscript", "nav", "footer", "header", "aside")
_NOISE_CLASS_TERMS = ("cookie", "banner", "notification", "timestamp", "csrf", "track")
_NOISE_ATTR_PREFIXES = ("data-", "aria-")
_NOISE_ATTRS = {"style"}
_WS_RE = re.compile(r"\s+")


def normalize(html: str) -> str:
    """Strip dynamic/navigational noise; return canonical visible text."""
    tree = HTMLParser(html)
    # 1. Kill whole subtrees that never contribute stable content.
    for tag in _NOISE_TAGS:
        for node in tree.css(tag):
            node.decompose()
    # 2. Drop elements whose class name contains any noise term.
    for node in tree.css("[class]"):
        classes = (node.attributes.get("class") or "").lower()
        if any(term in classes for term in _NOISE_CLASS_TERMS):
            node.decompose()
    # 3. Strip attributes everywhere so presentational churn can't change the hash.
    for node in tree.css("*"):
        attrs = dict(node.attributes or {})
        for name in list(attrs.keys()):
            if (
                name in _NOISE_ATTRS
                or any(name.startswith(prefix) for prefix in _NOISE_ATTR_PREFIXES)
            ):
                del node.attrs[name]
    # 4. Emit visible text only.
    text = tree.body.text(separator=" ", strip=True) if tree.body else ""
    # 5. Collapse whitespace.
    return _WS_RE.sub(" ", text).strip()


def content_hash(normalized: str) -> str:
    """SHA-256 of the normalized string; hex-digested."""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
```

> Note: `selectolax`'s `node.attrs` supports `del` for attribute removal. If a future selectolax release changes the API, replace the loop with `node.attrs = {k: v for k, v in attrs.items() if not unwanted(k)}`. Verify behavior with the tests after any selectolax upgrade.

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/unit/test_normalize.py tests/unit/test_change_detector.py -v
uv run pytest
uv run ruff check .
uv run mypy src
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/yas/crawl/__init__.py src/yas/crawl/normalize.py src/yas/crawl/change_detector.py tests/unit/test_normalize.py tests/unit/test_change_detector.py
git commit -m "feat(crawl): add name + HTML normalization and content hashing"
```

---

## Task 3 — LLM schemas + DayOfWeek enum + prompt builder

**Files:**
- Modify: `src/yas/db/models/_types.py` (add `DayOfWeek`)
- Create: `src/yas/llm/__init__.py`
- Create: `src/yas/llm/schemas.py`
- Create: `src/yas/llm/prompt.py`
- Create: `tests/unit/test_llm_schemas.py`
- Create: `tests/unit/test_llm_prompt.py`

- [ ] **Step 1: Write the failing schema tests**

`tests/unit/test_llm_schemas.py`:
```python
from datetime import date, datetime, time

import pytest
from pydantic import ValidationError

from yas.db.models._types import ProgramType
from yas.llm.schemas import ExtractedOffering, ExtractionResponse


def _minimal(**overrides):
    base = {"name": "Little Kickers", "program_type": ProgramType.soccer}
    base.update(overrides)
    return base


def test_minimal_offering_is_valid():
    o = ExtractedOffering(**_minimal())
    assert o.name == "Little Kickers"
    assert o.program_type == ProgramType.soccer
    assert o.age_min is None
    assert o.days_of_week == []


def test_offering_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ExtractedOffering(**_minimal(unknown="x"))


def test_offering_rejects_unknown_program_type():
    with pytest.raises(ValidationError):
        ExtractedOffering(**_minimal(program_type="rhetoric"))


def test_offering_accepts_dates_and_times():
    o = ExtractedOffering(
        **_minimal(
            age_min=6,
            age_max=8,
            start_date=date(2026, 5, 3),
            end_date=date(2026, 6, 21),
            time_start=time(9, 0),
            time_end=time(10, 0),
            days_of_week=["sat"],
            registration_opens_at=datetime(2026, 4, 25, 9, 0),
            price_cents=8500,
        )
    )
    assert o.price_cents == 8500
    assert o.days_of_week == ["sat"]


def test_extraction_response_collects_offerings():
    r = ExtractionResponse(offerings=[ExtractedOffering(**_minimal())])
    assert len(r.offerings) == 1


def test_extraction_response_rejects_unknown_top_level():
    with pytest.raises(ValidationError):
        ExtractionResponse(offerings=[], model="oops")
```

`tests/unit/test_llm_prompt.py`:
```python
from yas.llm.prompt import build_extraction_prompt


def test_prompt_contains_site_and_url_and_html():
    system, user = build_extraction_prompt(
        html="<p>Spring Soccer, ages 6-8</p>",
        url="https://example.com/spring",
        site_name="Example Sports",
    )
    assert "program_type" in system
    assert "null rather than guessing" in system.lower()
    assert "https://example.com/spring" in user
    assert "Example Sports" in user
    assert "Spring Soccer, ages 6-8" in user


def test_prompt_mentions_fixed_program_vocabulary():
    system, _ = build_extraction_prompt(html="", url="", site_name="x")
    for tag in ("soccer", "swim", "martial_arts", "art", "music", "stem", "dance",
                "gym", "multisport", "outdoor", "academic", "camp_general"):
        assert tag in system


def test_prompt_asks_for_structured_output_tool_use():
    system, _ = build_extraction_prompt(html="", url="", site_name="x")
    # The model is called with a tool; the prompt should direct it to use the tool.
    assert "report_offerings" in system
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_llm_schemas.py tests/unit/test_llm_prompt.py -v`
Expected: import errors.

- [ ] **Step 3: Add `DayOfWeek` enum**

Edit `src/yas/db/models/_types.py` — append after the existing enums:

```python
class DayOfWeek(StrEnum):
    mon = "mon"
    tue = "tue"
    wed = "wed"
    thu = "thu"
    fri = "fri"
    sat = "sat"
    sun = "sun"
```

- [ ] **Step 4: Create `src/yas/llm/__init__.py`**

Empty file.

- [ ] **Step 5: Implement `src/yas/llm/schemas.py`**

```python
"""Pydantic schemas for LLM-extracted offerings.

Strict — `extra="forbid"` so drift in model output surfaces loudly instead of
silently poisoning the `offerings` table. Field names mirror the ORM columns
we can actually extract; location is split into name+address so the reconciler
can get_or_create the Location row."""

from __future__ import annotations

from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict

from yas.db.models._types import DayOfWeek, ProgramType


class ExtractedOffering(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    age_min: int | None = None
    age_max: int | None = None
    program_type: ProgramType
    start_date: date | None = None
    end_date: date | None = None
    days_of_week: list[DayOfWeek] = []
    time_start: time | None = None
    time_end: time | None = None
    location_name: str | None = None
    location_address: str | None = None
    price_cents: int | None = None
    registration_opens_at: datetime | None = None
    registration_url: str | None = None


class ExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offerings: list[ExtractedOffering]
```

- [ ] **Step 6: Implement `src/yas/llm/prompt.py`**

```python
"""Prompt construction for the extraction tool call.

The system prompt declares the role, the fixed `program_type` vocabulary, date
format conventions, and a "prefer null to guessing" instruction. The user
message carries the (normalized) HTML, URL, and site name."""

from __future__ import annotations

_PROGRAM_TYPES = (
    "soccer", "swim", "martial_arts", "art", "music", "stem", "dance",
    "gym", "multisport", "outdoor", "academic", "camp_general", "unknown",
)

_SYSTEM = f"""You extract youth activity offerings from a single web page into a
structured list. You are called with a tool named `report_offerings` — always
respond by invoking that tool with the offerings you find. Do not write prose.

For each offering, fill these fields where the page makes them clear:
- name (required, as the program is advertised)
- description (optional, 1–2 sentences)
- age_min / age_max (inclusive, integer years)
- program_type: one of {", ".join(_PROGRAM_TYPES)}. Pick the closest match;
  use "unknown" only when truly unclassifiable.
- start_date / end_date (YYYY-MM-DD)
- days_of_week: subset of ["mon","tue","wed","thu","fri","sat","sun"]
- time_start / time_end (HH:MM, 24-hour)
- location_name, location_address (if a specific venue is named)
- price_cents (integer, e.g. $85.00 → 8500)
- registration_opens_at (YYYY-MM-DDTHH:MM timezone-naive acceptable)
- registration_url

Strict rules:
1. If a field is not clearly stated on the page, return null rather than guessing.
   Plausible inference from context is fine; fabrication is not.
2. One entry per distinct offering. If the page lists multiple sessions of the
   same program (e.g. "Session 1", "Session 2"), emit them as separate items.
3. If the page lists no offerings, return an empty list."""


def build_extraction_prompt(*, html: str, url: str, site_name: str) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for the extraction call."""
    user = (
        f"Site: {site_name}\n"
        f"URL: {url}\n"
        f"\n"
        f"--- page content ---\n"
        f"{html}\n"
        f"--- end page content ---"
    )
    return _SYSTEM, user
```

- [ ] **Step 7: Run tests**

```bash
uv run pytest tests/unit/test_llm_schemas.py tests/unit/test_llm_prompt.py -v
uv run pytest
uv run ruff check .
uv run mypy src
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add src/yas/db/models/_types.py src/yas/llm/ tests/unit/test_llm_schemas.py tests/unit/test_llm_prompt.py
git commit -m "feat(llm): add extraction schemas, DayOfWeek enum, and prompt builder"
```

---

## Task 4 — LLM client (protocol + AnthropicClient + Fake)

**Files:**
- Create: `src/yas/llm/client.py`
- Create: `tests/fakes/__init__.py`
- Create: `tests/fakes/llm.py`
- Create: `tests/unit/test_llm_client.py`

Pricing constants for Claude Haiku (2026-04 rates) will live in `client.py` so cost calculation is local to the call site. Rates are public; if Anthropic changes them we update one file.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_llm_client.py`:
```python
import json
from typing import Any

import pytest

from yas.db.models._types import ProgramType
from yas.llm.client import AnthropicClient, ExtractionResult


class _FakeAnthropicMessages:
    """Mimics anthropic.AsyncAnthropic().messages.create() for unit tests."""

    def __init__(self, tool_input: dict[str, Any], model: str = "claude-haiku-4-5-20251001",
                 usage_in: int = 1000, usage_out: int = 200):
        self._tool_input = tool_input
        self._model = model
        self._usage_in = usage_in
        self._usage_out = usage_out

    async def create(self, **_kwargs):
        class _Block:
            type = "tool_use"
            name = "report_offerings"
            input = self._tool_input

        class _Usage:
            input_tokens = self._usage_in
            output_tokens = self._usage_out

        class _Msg:
            stop_reason = "tool_use"
            content = [_Block()]
            model = self._model
            usage = _Usage()

        return _Msg()


class _FakeAnthropicClient:
    def __init__(self, messages):
        self.messages = messages


@pytest.mark.asyncio
async def test_anthropic_client_extracts_and_prices(monkeypatch):
    tool_input = {
        "offerings": [
            {"name": "Little Kickers", "program_type": "soccer", "age_min": 6, "age_max": 8},
        ]
    }
    fake = _FakeAnthropicClient(messages=_FakeAnthropicMessages(tool_input))
    client = AnthropicClient(api_key="sk-test", sdk_client=fake)
    result = await client.extract_offerings(
        html="<p>Little Kickers ages 6-8</p>", url="https://ex.com", site_name="Ex"
    )
    assert isinstance(result, ExtractionResult)
    assert len(result.offerings) == 1
    assert result.offerings[0].program_type == ProgramType.soccer
    assert result.model == "claude-haiku-4-5-20251001"
    assert result.cost_usd > 0


@pytest.mark.asyncio
async def test_anthropic_client_raises_on_schema_violation():
    bad = {"offerings": [{"name": "x", "program_type": "soccer", "unknown_field": 1}]}
    fake = _FakeAnthropicClient(messages=_FakeAnthropicMessages(bad))
    client = AnthropicClient(api_key="sk-test", sdk_client=fake)
    from yas.llm.client import ExtractionError

    with pytest.raises(ExtractionError):
        await client.extract_offerings(html="<p/>", url="u", site_name="s")


@pytest.mark.asyncio
async def test_anthropic_client_raises_when_model_did_not_call_tool():
    class _NoToolMessages:
        async def create(self, **_):
            class _TextBlock:
                type = "text"
                text = "I couldn't use the tool."

            class _Usage:
                input_tokens = 500
                output_tokens = 10

            class _Msg:
                stop_reason = "end_turn"
                content = [_TextBlock()]
                model = "claude-haiku-4-5-20251001"
                usage = _Usage()

            return _Msg()

    client = AnthropicClient(api_key="sk-test", sdk_client=_FakeAnthropicClient(_NoToolMessages()))
    from yas.llm.client import ExtractionError

    with pytest.raises(ExtractionError):
        await client.extract_offerings(html="<p/>", url="u", site_name="s")


@pytest.mark.asyncio
async def test_fake_llm_client_returns_scripted_response():
    from yas.db.models._types import ProgramType
    from yas.llm.schemas import ExtractedOffering
    from tests.fakes.llm import FakeLLMClient

    canned = [ExtractedOffering(name="Swim Basics", program_type=ProgramType.swim)]
    fake = FakeLLMClient(default=canned)
    res = await fake.extract_offerings(html="<p/>", url="u", site_name="s")
    assert [o.name for o in res.offerings] == ["Swim Basics"]
    assert fake.call_count == 1
```

- [ ] **Step 2: Run to verify fails**

Run: `uv run pytest tests/unit/test_llm_client.py -v`
Expected: import errors.

- [ ] **Step 3: Implement `src/yas/llm/client.py`**

```python
"""Claude client that performs structured extraction via tool use.

The model is prompted to call a `report_offerings` tool whose input_schema
mirrors `ExtractionResponse`. We extract the tool input, validate it with
pydantic, and compute per-call cost from token usage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import ValidationError

from yas.llm.prompt import build_extraction_prompt
from yas.llm.schemas import ExtractedOffering, ExtractionResponse


# Claude Haiku 4.5 public pricing (2026-04). Update here if Anthropic revises.
# Input: $1.00 / 1M tokens. Output: $5.00 / 1M tokens.
_HAIKU_IN_PER_MTOK = 1.00
_HAIKU_OUT_PER_MTOK = 5.00


@dataclass(frozen=True)
class ExtractionResult:
    offerings: list[ExtractedOffering]
    model: str
    cost_usd: float


class ExtractionError(Exception):
    """LLM call succeeded but output didn't conform to our schema."""

    def __init__(self, raw: str, detail: str):
        super().__init__(detail)
        self.raw = raw
        self.detail = detail


class LLMClient(Protocol):
    async def extract_offerings(
        self, *, html: str, url: str, site_name: str
    ) -> ExtractionResult: ...


def _tool_schema() -> dict[str, Any]:
    """input_schema for the report_offerings tool — derived from Pydantic."""
    return ExtractionResponse.model_json_schema()


class AnthropicClient:
    """Production LLM client backed by the Anthropic SDK."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-haiku-4-5-20251001",
        *,
        sdk_client: Any | None = None,
    ) -> None:
        self._model = model
        if sdk_client is not None:
            self._client = sdk_client
        else:
            # Import lazily so tests can run without the SDK wired up.
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(api_key=api_key)

    async def extract_offerings(
        self, *, html: str, url: str, site_name: str
    ) -> ExtractionResult:
        system, user = build_extraction_prompt(html=html, url=url, site_name=site_name)
        tool = {
            "name": "report_offerings",
            "description": "Report the list of offerings extracted from the page.",
            "input_schema": _tool_schema(),
        }
        msg = await self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=system,
            tools=[tool],
            tool_choice={"type": "tool", "name": "report_offerings"},
            messages=[{"role": "user", "content": user}],
        )
        tool_input = _find_tool_input(msg)
        if tool_input is None:
            raise ExtractionError(
                raw=_dump_msg(msg),
                detail=f"model stopped without calling report_offerings (stop_reason={getattr(msg, 'stop_reason', '?')})",
            )
        try:
            parsed = ExtractionResponse.model_validate(tool_input)
        except ValidationError as exc:
            raise ExtractionError(raw=str(tool_input), detail=str(exc)) from exc
        cost = _estimate_cost_usd(msg)
        return ExtractionResult(
            offerings=list(parsed.offerings),
            model=getattr(msg, "model", self._model),
            cost_usd=cost,
        )


def _find_tool_input(msg: Any) -> dict[str, Any] | None:
    for block in getattr(msg, "content", []) or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "report_offerings":
            inp = getattr(block, "input", None)
            if isinstance(inp, dict):
                return inp
    return None


def _dump_msg(msg: Any) -> str:
    try:
        return repr(msg)
    except Exception:
        return "<unrepresentable message>"


def _estimate_cost_usd(msg: Any) -> float:
    usage = getattr(msg, "usage", None)
    if usage is None:
        return 0.0
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    return (inp / 1_000_000) * _HAIKU_IN_PER_MTOK + (out / 1_000_000) * _HAIKU_OUT_PER_MTOK
```

- [ ] **Step 4: Implement `tests/fakes/__init__.py`** (empty)

- [ ] **Step 5: Implement `tests/fakes/llm.py`**

```python
"""FakeLLMClient — scripted responses for integration tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

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

    async def extract_offerings(
        self, *, html: str, url: str, site_name: str
    ) -> ExtractionResult:
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
```

- [ ] **Step 6: Run tests and gates**

```bash
uv run pytest tests/unit/test_llm_client.py -v
uv run pytest
uv run ruff check .
uv run mypy src
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/yas/llm/client.py tests/fakes/ tests/unit/test_llm_client.py
git commit -m "feat(llm): add AnthropicClient with tool-use extraction and FakeLLMClient"
```

---

## Task 5 — Extractor (cache-aware)

**Files:**
- Create: `src/yas/crawl/extractor.py`
- Create: `tests/unit/test_extractor.py`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_extractor.py`:
```python
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
    assert llm.call_count == 1   # not called again
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
```

- [ ] **Step 2: Run to verify fails**

Run: `uv run pytest tests/unit/test_extractor.py -v`
Expected: import error.

- [ ] **Step 3: Implement `src/yas/crawl/extractor.py`**

```python
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
```

- [ ] **Step 4: Run tests + gates**

```bash
uv run pytest tests/unit/test_extractor.py -v
uv run pytest
uv run ruff check .
uv run mypy src
```

- [ ] **Step 5: Commit**

```bash
git add src/yas/crawl/extractor.py tests/unit/test_extractor.py
git commit -m "feat(crawl): add cache-aware LLM extractor"
```

---

## Task 6 — Reconciler

**Files:**
- Create: `src/yas/crawl/reconciler.py`
- Create: `tests/unit/test_reconciler.py`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_reconciler.py`:
```python
from datetime import date

import pytest
from sqlalchemy import select

from yas.crawl.reconciler import reconcile
from yas.db.base import Base
from yas.db.models import Offering, Page, Site
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
        await reconcile(s, page, [])   # withdraw
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        result = await reconcile(s, page, [o])   # reappear
    assert len(result.new) == 1
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Offering))).scalars().all()
        assert len(rows) == 2  # old withdrawn + new active
    await engine.dispose()


@pytest.mark.asyncio
async def test_location_name_creates_or_reuses_location(tmp_path):
    engine, site_id, page_id = await _setup(tmp_path)
    o = _offering("Kickers", start_date=date(2026, 5, 1),
                  location_name="Lincoln Park Rec", location_address="123 N Clark St")
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
```

- [ ] **Step 2: Run to verify fails**

Run: `uv run pytest tests/unit/test_reconciler.py -v`
Expected: import error.

- [ ] **Step 3: Implement `src/yas/crawl/reconciler.py`**

```python
"""Diff extracted offerings against the DB and classify each row."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.crawl.normalize import normalize_name
from yas.db.models import Location, Offering, Page
from yas.db.models._types import OfferingStatus, ProgramType
from yas.llm.schemas import ExtractedOffering


# Fields compared for deciding "updated" vs "unchanged".
_COMPARE_FIELDS = (
    "name", "description", "age_min", "age_max", "program_type",
    "start_date", "end_date", "days_of_week", "time_start", "time_end",
    "location_id", "price_cents", "registration_opens_at", "registration_url",
)


@dataclass(frozen=True)
class ReconcileResult:
    new: list[int] = field(default_factory=list)
    updated: list[int] = field(default_factory=list)
    withdrawn: list[int] = field(default_factory=list)
    unchanged: list[int] = field(default_factory=list)


async def reconcile(
    session: AsyncSession,
    page: Page,
    extracted: list[ExtractedOffering],
) -> ReconcileResult:
    """Diff `extracted` against active offerings for `page`; mutate session accordingly.

    Does NOT commit. Caller controls the transaction."""
    existing_rows = (
        await session.execute(
            select(Offering).where(
                Offering.page_id == page.id,
                Offering.status == OfferingStatus.active,
            )
        )
    ).scalars().all()
    existing_by_key: dict[tuple[str, Any], Offering] = {
        (r.normalized_name, r.start_date): r for r in existing_rows
    }

    now = datetime.now(UTC)
    result = ReconcileResult()
    matched_keys: set[tuple[str, Any]] = set()

    for e in extracted:
        norm = normalize_name(e.name)
        key = (norm, e.start_date)
        matched_keys.add(key)
        location_id = await _location_id(session, page.site_id, e)
        desired = _offering_fields(e, norm, location_id)

        existing = existing_by_key.get(key)
        if existing is None:
            row = Offering(
                site_id=page.site_id,
                page_id=page.id,
                status=OfferingStatus.active,
                raw_json=_raw_json(e),
                first_seen=now,
                last_seen=now,
                **desired,
            )
            session.add(row)
            await session.flush()  # populate id
            result.new.append(row.id)
        else:
            # Compare the subset of fields we treat as user-visible.
            differs = any(
                getattr(existing, f) != desired[f] for f in _COMPARE_FIELDS
                if f in desired
            )
            existing.raw_json = _raw_json(e)
            existing.last_seen = now
            if differs:
                for f in _COMPARE_FIELDS:
                    if f in desired:
                        setattr(existing, f, desired[f])
                result.updated.append(existing.id)
            else:
                result.unchanged.append(existing.id)

    for key, row in existing_by_key.items():
        if key not in matched_keys:
            row.status = OfferingStatus.withdrawn
            row.last_seen = now
            result.withdrawn.append(row.id)

    return result


def _offering_fields(e: ExtractedOffering, norm: str, location_id: int | None) -> dict[str, Any]:
    return {
        "name": e.name,
        "normalized_name": norm,
        "description": e.description,
        "age_min": e.age_min,
        "age_max": e.age_max,
        "program_type": e.program_type,
        "start_date": e.start_date,
        "end_date": e.end_date,
        "days_of_week": [d.value for d in e.days_of_week],
        "time_start": e.time_start,
        "time_end": e.time_end,
        "location_id": location_id,
        "price_cents": e.price_cents,
        "registration_opens_at": e.registration_opens_at,
        "registration_url": e.registration_url,
    }


def _raw_json(e: ExtractedOffering) -> dict[str, Any]:
    import json
    return json.loads(e.model_dump_json())


async def _location_id(session: AsyncSession, site_id: int, e: ExtractedOffering) -> int | None:
    if not e.location_name:
        return None
    norm = normalize_name(e.location_name)
    existing = (
        await session.execute(
            select(Location).where(Location.name == e.location_name)
        )
    ).scalars().first()
    if existing is not None:
        return existing.id
    # Scope dedup loosely — same normalized name anywhere is "same" location.
    any_norm = (
        await session.execute(select(Location))
    ).scalars().all()
    for loc in any_norm:
        if normalize_name(loc.name) == norm:
            return loc.id
    loc = Location(name=e.location_name, address=e.location_address)
    session.add(loc)
    await session.flush()
    return loc.id
```

> Note: the `days_of_week` field in the ORM is a JSON list of strings. We store `[d.value for d in e.days_of_week]` to keep the DB content string-typed regardless of whether the enum class is `StrEnum` (its `value` is already a string). `e.program_type` is a `ProgramType` StrEnum — assignment to `Mapped[ProgramType]` works because StrEnum IS a str. The ORM column stores the raw string.

- [ ] **Step 4: Run tests and gates**

```bash
uv run pytest tests/unit/test_reconciler.py -v
uv run pytest
uv run ruff check .
uv run mypy src
```

Expected: all 8 reconciler tests pass, full suite green.

- [ ] **Step 5: Commit**

```bash
git add src/yas/crawl/reconciler.py tests/unit/test_reconciler.py
git commit -m "feat(crawl): add reconciler with per-page offering diff"
```

---

## Task 7 — Fixture server (test infrastructure)

**Files:**
- Create: `tests/fixtures/__init__.py`
- Create: `tests/fixtures/server.py`
- Create: `tests/fixtures/sites/__init__.py`
- Create: `tests/fixtures/sites/lilsluggers/__init__.py`
- Create: `tests/fixtures/sites/lilsluggers/spring-session-24.html` (captured snapshot)

- [ ] **Step 1: Capture the real Lil Sluggers HTML**

```bash
curl -sSL https://www.lilsluggerschicago.com/spring-session-24.html \
  -o tests/fixtures/sites/lilsluggers/spring-session-24.html
```

If the fetch fails or returns an error page, commit a minimal representative fixture instead (ok for Phase 2 — we'll refresh when testing for real):

```html
<!-- tests/fixtures/sites/lilsluggers/spring-session-24.html -->
<!doctype html>
<html><body>
  <main>
    <h1>Spring Session 24</h1>
    <h2>Tots (ages 2-3)</h2>
    <p>Saturdays 9:00-9:45 AM. Starts April 13, 2026. $120.</p>
    <h2>Stars (ages 4-5)</h2>
    <p>Saturdays 10:00-10:45 AM. Starts April 13, 2026. $120.</p>
  </main>
</body></html>
```

- [ ] **Step 2: Create the empty package marker files**

`tests/fixtures/__init__.py`, `tests/fixtures/sites/__init__.py`, `tests/fixtures/sites/lilsluggers/__init__.py` — all empty.

- [ ] **Step 3: Implement the fixture server**

`tests/fixtures/server.py`:
```python
"""Local aiohttp server for hermetic crawl tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestServer


FIXTURES_DIR = Path(__file__).resolve().parent / "sites"


@dataclass
class FixtureSite:
    base_url: str
    _pages: dict[str, str] = field(default_factory=dict)
    _server: TestServer | None = None

    def set_page(self, path: str, html: str) -> None:
        """Swap the body served for `path` at runtime (for change-detection tests)."""
        if not path.startswith("/"):
            path = "/" + path
        self._pages[path] = html

    def url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url.rstrip('/')}{path}"


@asynccontextmanager
async def fixture_site(
    *,
    pages: dict[str, str] | None = None,
) -> AsyncIterator[FixtureSite]:
    """Start a local aiohttp app serving `pages` (path -> HTML). Yield a handle."""
    site = FixtureSite(base_url="")
    if pages:
        for k, v in pages.items():
            site.set_page(k, v)

    async def handler(request: web.Request) -> web.Response:
        path = request.path
        html = site._pages.get(path)
        if html is None:
            return web.Response(status=404, text=f"no page registered for {path}")
        return web.Response(body=html.encode("utf-8"), content_type="text/html")

    app = web.Application()
    app.router.add_get("/{tail:.*}", handler)
    server = TestServer(app, port=0)
    await server.start_server()
    try:
        site.base_url = str(server.make_url("/"))
        site._server = server
        yield site
    finally:
        await server.close()


def load_fixture(relative_path: str) -> str:
    """Read a captured HTML fixture under tests/fixtures/sites/."""
    return (FIXTURES_DIR / relative_path).read_text(encoding="utf-8")
```

- [ ] **Step 4: Quick sanity test**

Write a tiny test that stands the server up and fetches a page — this both exercises the fixture infrastructure and gives Task 8/9 confidence.

Create `tests/integration/test_fixture_server.py`:
```python
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
```

- [ ] **Step 5: Run and commit**

```bash
uv run pytest tests/integration/test_fixture_server.py -v
uv run pytest
uv run ruff check .
uv run mypy src
git add tests/fixtures/ tests/integration/test_fixture_server.py
git commit -m "test: add local aiohttp fixture server for crawl tests"
```

---

## Task 8 — Fetcher (httpx + retry; Playwright hook only)

This task implements the httpx fetcher end-to-end plus the structural hook for Playwright. Task 9 fills in the Playwright branch and its tests. Splitting keeps each task reviewable.

**Files:**
- Create: `src/yas/crawl/fetcher.py`
- Create: `tests/unit/test_fetcher.py`

- [ ] **Step 1: Write the failing httpx tests**

`tests/unit/test_fetcher.py`:
```python
import asyncio

import pytest
import respx
from httpx import Response

from yas.crawl.fetcher import DefaultFetcher, FetchError
from yas.config import get_settings


async def _mk_fetcher():
    _ = get_settings   # typecheck — settings import exercised
    return DefaultFetcher()


class _Page:
    def __init__(self, url):
        self.url = url

class _Site:
    def __init__(self, id, needs_browser=False, crawl_hints=None):
        self.id = id
        self.needs_browser = needs_browser
        self.crawl_hints = crawl_hints or {}


@pytest.mark.asyncio
@respx.mock
async def test_fetch_happy_path():
    respx.get("https://example.com/p").mock(return_value=Response(200, html="<html><body>ok</body></html>"))
    fetcher = await _mk_fetcher()
    try:
        result = await fetcher.fetch(_Page("https://example.com/p"), _Site(id=1))
        assert result.status_code == 200
        assert "ok" in result.html
        assert result.used_browser is False
    finally:
        await fetcher.aclose()


@pytest.fixture
def _fast_backoffs(monkeypatch):
    """Shrink fetcher backoffs so the retry tests don't burn ~15s of real sleep."""
    from yas.crawl import fetcher as fetcher_mod

    monkeypatch.setattr(fetcher_mod, "_BACKOFFS_S", (0.0, 0.0, 0.0))


@pytest.mark.asyncio
@respx.mock
async def test_fetch_retries_on_429_then_succeeds(_fast_backoffs):
    route = respx.get("https://example.com/p").mock(side_effect=[
        Response(429),
        Response(200, html="<html>ok</html>"),
    ])
    fetcher = await _mk_fetcher()
    try:
        result = await fetcher.fetch(_Page("https://example.com/p"), _Site(id=1))
        assert result.status_code == 200
        assert route.call_count == 2
    finally:
        await fetcher.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_fetch_gives_up_after_exhausting_retries(_fast_backoffs):
    respx.get("https://example.com/p").mock(return_value=Response(503))
    fetcher = await _mk_fetcher()
    try:
        with pytest.raises(FetchError):
            await fetcher.fetch(_Page("https://example.com/p"), _Site(id=1))
    finally:
        await fetcher.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_fetch_does_not_retry_on_4xx_other_than_429():
    route = respx.get("https://example.com/p").mock(return_value=Response(404))
    fetcher = await _mk_fetcher()
    try:
        with pytest.raises(FetchError):
            await fetcher.fetch(_Page("https://example.com/p"), _Site(id=1))
        assert route.call_count == 1
    finally:
        await fetcher.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_fetch_enforces_per_site_concurrency_of_1():
    """Two concurrent fetches against the same site_id must execute serially."""
    order: list[str] = []

    async def handler(request):
        order.append("start")
        await asyncio.sleep(0.05)
        order.append("end")
        return Response(200, html="<p/>")

    respx.get("https://example.com/a").mock(side_effect=handler)
    respx.get("https://example.com/b").mock(side_effect=handler)
    fetcher = await _mk_fetcher()
    try:
        await asyncio.gather(
            fetcher.fetch(_Page("https://example.com/a"), _Site(id=1)),
            fetcher.fetch(_Page("https://example.com/b"), _Site(id=1)),
        )
    finally:
        await fetcher.aclose()

    # With a per-site lock, we never see start-start-end-end.
    for i in range(len(order) - 1):
        if order[i] == "start":
            assert order[i + 1] == "end"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_fetcher.py -v`
Expected: import error.

- [ ] **Step 3: Implement the fetcher**

`src/yas/crawl/fetcher.py`:
```python
"""Fetcher: httpx by default, Playwright when site.needs_browser=True.

One shared httpx.AsyncClient. One lazily-launched Chromium browser + context.
Per-site concurrency of 1 via an asyncio.Lock dict. robots.txt is ignored by
default; sites with crawl_hints['respect_robots'] = True are checked."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


_USER_AGENT = "yas/0.1 (+https://github.com/example/youth-activity-scheduler)"
_TIMEOUT = httpx.Timeout(30.0)
_RETRY_CODES = {429, 502, 503, 504}
_BACKOFFS_S = (1.0, 4.0, 10.0)   # 3 attempts total (initial + 2 retries after the first wait)


@dataclass(frozen=True)
class FetchResult:
    url: str
    status_code: int
    html: str
    used_browser: bool
    elapsed_ms: int


class FetchError(Exception):
    def __init__(self, status: int | None, url: str, cause: str):
        super().__init__(f"fetch {url} failed: status={status} cause={cause}")
        self.status = status
        self.url = url
        self.cause = cause


class Fetcher(Protocol):
    async def fetch(self, page: Any, site: Any) -> FetchResult: ...
    async def aclose(self) -> None: ...


class DefaultFetcher:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
            follow_redirects=True,
        )
        self._site_locks: dict[int, asyncio.Lock] = {}
        self._browser: Any = None
        self._browser_context: Any = None
        self._playwright: Any = None
        self._browser_lock = asyncio.Lock()

    def _lock_for(self, site_id: int) -> asyncio.Lock:
        lock = self._site_locks.get(site_id)
        if lock is None:
            lock = asyncio.Lock()
            self._site_locks[site_id] = lock
        return lock

    async def fetch(self, page: Any, site: Any) -> FetchResult:
        async with self._lock_for(getattr(site, "id", 0)):
            started = time.monotonic()
            if getattr(site, "needs_browser", False):
                html, status, final_url, used_browser = await self._fetch_browser(page.url)
            else:
                html, status, final_url = await self._fetch_http(page.url)
                used_browser = False
            return FetchResult(
                url=final_url,
                status_code=status,
                html=html,
                used_browser=used_browser,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )

    async def _fetch_http(self, url: str) -> tuple[str, int, str]:
        last_err: Exception | None = None
        last_status: int | None = None
        for attempt in range(len(_BACKOFFS_S) + 1):
            try:
                r = await self._http.get(url)
                if r.status_code in _RETRY_CODES:
                    last_status = r.status_code
                    if attempt < len(_BACKOFFS_S):
                        await asyncio.sleep(_BACKOFFS_S[attempt])
                        continue
                    raise FetchError(r.status_code, url, f"exhausted retries on {r.status_code}")
                if r.status_code >= 400:
                    raise FetchError(r.status_code, url, f"http {r.status_code}")
                return r.text, r.status_code, str(r.url)
            except FetchError:
                raise
            except httpx.TransportError as exc:
                last_err = exc
                if attempt < len(_BACKOFFS_S):
                    await asyncio.sleep(_BACKOFFS_S[attempt])
                    continue
                raise FetchError(None, url, f"transport: {exc}") from exc
        # Should be unreachable.
        raise FetchError(last_status, url, f"unexpected fall-through: {last_err}")

    async def _fetch_browser(self, url: str) -> tuple[str, int, str, bool]:
        # Task 9 fills this in end-to-end.
        raise NotImplementedError("Playwright branch implemented in Task 9")

    async def aclose(self) -> None:
        await self._http.aclose()
        if self._browser_context is not None:
            try:
                await self._browser_context.close()
            except Exception:
                pass
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
```

- [ ] **Step 4: Run tests and gates**

```bash
uv run pytest tests/unit/test_fetcher.py -v
uv run pytest
uv run ruff check .
uv run mypy src
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/yas/crawl/fetcher.py tests/unit/test_fetcher.py
git commit -m "feat(crawl): add DefaultFetcher http path with retries and per-site lock"
```

---

## Task 9 — Fetcher Playwright branch

**Files:**
- Modify: `src/yas/crawl/fetcher.py`
- Create: `tests/integration/test_playwright_fetcher.py`

- [ ] **Step 1: Install Chromium locally**

```bash
uv run playwright install chromium
```

This is a one-time dev-machine setup (~150 MB download). CI and Docker install it via Task 12.

- [ ] **Step 2: Write the failing Playwright test**

`tests/integration/test_playwright_fetcher.py`:
```python
"""Playwright fetcher integration test.

Skipped if Chromium binaries aren't installed (CI + Docker install them)."""

from __future__ import annotations

import pathlib

import pytest


def _has_chromium() -> bool:
    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except ImportError:
        return False
    # Presence of the browser binary is checked at launch; skip if missing.
    import shutil

    # A cheap heuristic: CI/dev installs leave chromium in the playwright cache.
    cache = pathlib.Path.home() / ".cache" / "ms-playwright"
    return cache.exists() and any(cache.glob("chromium-*"))


pytestmark = pytest.mark.skipif(not _has_chromium(), reason="Chromium not installed")


class _Page:
    def __init__(self, url):
        self.url = url


class _Site:
    def __init__(self, id, needs_browser=True, crawl_hints=None):
        self.id = id
        self.needs_browser = needs_browser
        self.crawl_hints = crawl_hints or {}


JS_PAGE = """<!doctype html>
<html><body>
<div id="greet">waiting</div>
<script>
  setTimeout(() => {
    document.getElementById('greet').textContent = 'hello-from-js';
  }, 10);
</script>
</body></html>
"""


@pytest.mark.asyncio
async def test_playwright_fetches_post_script_dom(tmp_path):
    from yas.crawl.fetcher import DefaultFetcher

    html_path = tmp_path / "js.html"
    html_path.write_text(JS_PAGE, encoding="utf-8")
    url = html_path.as_uri()

    fetcher = DefaultFetcher()
    try:
        result = await fetcher.fetch(_Page(url), _Site(id=1, needs_browser=True))
        assert result.used_browser is True
        assert "hello-from-js" in result.html
    finally:
        await fetcher.aclose()
```

- [ ] **Step 3: Run to confirm it fails with NotImplementedError**

Run: `uv run pytest tests/integration/test_playwright_fetcher.py -v`
Expected: NotImplementedError from the Task 8 stub.

- [ ] **Step 4: Implement the Playwright branch in the fetcher**

Replace the `_fetch_browser` method in `src/yas/crawl/fetcher.py` with:

```python
    async def _fetch_browser(self, url: str) -> tuple[str, int, str, bool]:
        async with self._browser_lock:
            if self._browser is None:
                from playwright.async_api import async_playwright

                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(headless=True)
                self._browser_context = await self._browser.new_context(
                    user_agent=_USER_AGENT,
                )
        page = await self._browser_context.new_page()
        try:
            response = await page.goto(url, wait_until="networkidle", timeout=30000)
            status = response.status if response is not None else 200
            if status >= 400:
                raise FetchError(status, url, f"browser http {status}")
            # Give late-firing setTimeout/DOM updates one tick.
            await page.wait_for_load_state("networkidle")
            html = await page.content()
            final_url = page.url
            return html, status, final_url, True
        finally:
            await page.close()
```

- [ ] **Step 5: Run the Playwright test**

```bash
uv run pytest tests/integration/test_playwright_fetcher.py -v
uv run pytest   # full suite
uv run ruff check .
uv run mypy src
```

Expected: Playwright test passes (assuming browser installed in Step 1); full suite green. If Chromium isn't installed locally, the test skips — that's fine.

- [ ] **Step 6: Commit**

```bash
git add src/yas/crawl/fetcher.py tests/integration/test_playwright_fetcher.py
git commit -m "feat(crawl): implement Playwright Chromium fetch path"
```

---

## Task 10 — Pipeline orchestrator + integration tests

**Files:**
- Create: `src/yas/crawl/pipeline.py`
- Create: `tests/integration/test_pipeline.py`

- [ ] **Step 1: Write the failing integration tests**

`tests/integration/test_pipeline.py`:
```python
from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.fakes.llm import FakeLLMClient
from tests.fixtures.server import fixture_site
from yas.crawl.fetcher import DefaultFetcher
from yas.crawl.pipeline import crawl_page
from yas.db.base import Base
from yas.db.models import CrawlRun, Offering, Page, Site
from yas.db.models._types import CrawlStatus, ProgramType
from yas.db.session import create_engine_for, session_scope
from yas.llm.schemas import ExtractedOffering


PAGE = """<!doctype html><html><body><main>
<h1>Tots Baseball</h1><p>Ages 2-3. Sat 9am.</p>
</main></body></html>"""


async def _init_db(tmp_path):
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/pipe.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


async def _register(engine, site_url, page_url):
    async with session_scope(engine) as s:
        site = Site(name="Test", base_url=site_url)
        s.add(site)
        await s.flush()
        page = Page(site_id=site.id, url=page_url)
        s.add(page)
        await s.flush()
        return site.id, page.id


@pytest.mark.asyncio
async def test_crawl_page_happy_path(tmp_path):
    engine = await _init_db(tmp_path)
    async with fixture_site(pages={"/p": PAGE}) as fx:
        fetcher = DefaultFetcher()
        llm = FakeLLMClient(default=[ExtractedOffering(name="Tots Baseball", program_type=ProgramType.multisport, age_min=2, age_max=3)])
        site_id, page_id = await _register(engine, fx.base_url, fx.url("/p"))
        try:
            async with session_scope(engine) as s:
                site = (await s.execute(select(Site).where(Site.id == site_id))).scalar_one()
                page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
            await crawl_page(engine=engine, fetcher=fetcher, llm=llm, page=page, site=site)
        finally:
            await fetcher.aclose()
    async with session_scope(engine) as s:
        offerings = (await s.execute(select(Offering))).scalars().all()
        runs = (await s.execute(select(CrawlRun))).scalars().all()
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        assert [o.name for o in offerings] == ["Tots Baseball"]
        assert len(runs) == 1
        assert runs[0].status == CrawlStatus.ok
        assert runs[0].pages_fetched == 1
        assert runs[0].changes_detected == 1
        assert runs[0].llm_calls == 1
        assert page.content_hash is not None
        assert page.last_fetched is not None
        assert page.next_check_at is not None
    await engine.dispose()


@pytest.mark.asyncio
async def test_crawl_page_cache_hit_on_repeat(tmp_path):
    engine = await _init_db(tmp_path)
    async with fixture_site(pages={"/p": PAGE}) as fx:
        fetcher = DefaultFetcher()
        llm = FakeLLMClient(default=[ExtractedOffering(name="Tots Baseball", program_type=ProgramType.multisport)])
        site_id, page_id = await _register(engine, fx.base_url, fx.url("/p"))
        try:
            async with session_scope(engine) as s:
                site = (await s.execute(select(Site).where(Site.id == site_id))).scalar_one()
                page1 = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
            await crawl_page(engine=engine, fetcher=fetcher, llm=llm, page=page1, site=site)
            async with session_scope(engine) as s:
                page2 = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
                site2 = (await s.execute(select(Site).where(Site.id == site_id))).scalar_one()
            await crawl_page(engine=engine, fetcher=fetcher, llm=llm, page=page2, site=site2)
        finally:
            await fetcher.aclose()
    assert llm.call_count == 1     # cache hit on second crawl
    async with session_scope(engine) as s:
        runs = (await s.execute(select(CrawlRun).order_by(CrawlRun.id))).scalars().all()
        assert len(runs) == 2
        assert runs[1].status == CrawlStatus.ok
        assert runs[1].llm_calls == 0          # short-circuited by unchanged hash
        assert runs[1].changes_detected == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_crawl_page_records_fetch_failure(tmp_path):
    engine = await _init_db(tmp_path)
    # Fixture server returns 500 for anything.

    async def server():
        from aiohttp import web
        app = web.Application()

        async def handler(_req):
            return web.Response(status=500)

        app.router.add_get("/{tail:.*}", handler)
        from aiohttp.test_utils import TestServer
        s = TestServer(app, port=0)
        await s.start_server()
        return s

    srv = await server()
    try:
        fetcher = DefaultFetcher()
        llm = FakeLLMClient()
        site_id, page_id = await _register(engine, str(srv.make_url("/")), str(srv.make_url("/p")))
        try:
            async with session_scope(engine) as s:
                site = (await s.execute(select(Site).where(Site.id == site_id))).scalar_one()
                page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
            await crawl_page(engine=engine, fetcher=fetcher, llm=llm, page=page, site=site)
        finally:
            await fetcher.aclose()
    finally:
        await srv.close()
    async with session_scope(engine) as s:
        runs = (await s.execute(select(CrawlRun))).scalars().all()
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        assert len(runs) == 1
        assert runs[0].status == CrawlStatus.failed
        assert runs[0].error_text and "500" in runs[0].error_text
        assert page.consecutive_failures == 1
    await engine.dispose()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/test_pipeline.py -v`
Expected: import errors.

- [ ] **Step 3: Implement the pipeline orchestrator**

`src/yas/crawl/pipeline.py`:
```python
"""Compose the crawl stages into one end-to-end function + CrawlRun bookkeeping."""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.crawl.extractor import extract
from yas.crawl.fetcher import FetchError, Fetcher
from yas.crawl.reconciler import reconcile
from yas.db.models import CrawlRun, Page, Site
from yas.db.models._types import CrawlStatus
from yas.db.session import session_scope
from yas.llm.client import ExtractionError, LLMClient
from yas.logging import get_logger

log = get_logger("yas.crawl.pipeline")

_MAX_BACKOFF_MULTIPLIER = 4


@dataclass(frozen=True)
class CrawlResult:
    status: CrawlStatus
    pages_fetched: int
    changes_detected: int
    llm_calls: int
    llm_cost_usd: float
    error_text: str | None


async def crawl_page(
    *,
    engine: AsyncEngine,
    fetcher: Fetcher,
    llm: LLMClient,
    page: Page,
    site: Site,
) -> CrawlResult:
    started = datetime.now(UTC)

    async with session_scope(engine) as s:
        run = CrawlRun(site_id=site.id, started_at=started, status=CrawlStatus.ok)
        s.add(run)
        await s.flush()
        run_id = run.id

    try:
        result = await _do_crawl(engine=engine, fetcher=fetcher, llm=llm, page=page, site=site)
    except Exception as exc:  # pragma: no cover — defensive
        tb = traceback.format_exc()
        log.error("pipeline.unexpected", error=str(exc), traceback=tb[:2000])
        result = CrawlResult(
            status=CrawlStatus.failed,
            pages_fetched=0,
            changes_detected=0,
            llm_calls=0,
            llm_cost_usd=0.0,
            error_text=f"unexpected: {exc}",
        )

    # Finalize the run row.
    finished = datetime.now(UTC)
    async with session_scope(engine) as s:
        run = (await s.execute(select(CrawlRun).where(CrawlRun.id == run_id))).scalar_one()
        run.finished_at = finished
        run.status = result.status
        run.pages_fetched = result.pages_fetched
        run.changes_detected = result.changes_detected
        run.llm_calls = result.llm_calls
        run.llm_cost_usd = result.llm_cost_usd
        run.error_text = result.error_text

    return result


async def _do_crawl(
    *,
    engine: AsyncEngine,
    fetcher: Fetcher,
    llm: LLMClient,
    page: Page,
    site: Site,
) -> CrawlResult:
    try:
        fetched = await fetcher.fetch(page, site)
    except FetchError as exc:
        await _apply_failure(engine, page, site, error_text=str(exc))
        return CrawlResult(
            status=CrawlStatus.failed, pages_fetched=0, changes_detected=0,
            llm_calls=0, llm_cost_usd=0.0, error_text=str(exc),
        )

    # Short-circuit when content hasn't changed.
    from yas.crawl.change_detector import content_hash, normalize
    new_hash = content_hash(normalize(fetched.html))
    if page.content_hash is not None and page.content_hash == new_hash:
        await _apply_unchanged(engine, page, site)
        return CrawlResult(
            status=CrawlStatus.ok, pages_fetched=1, changes_detected=0,
            llm_calls=0, llm_cost_usd=0.0, error_text=None,
        )

    # Extract + reconcile.
    try:
        ex = await extract(engine=engine, llm=llm, html=fetched.html, url=fetched.url, site_name=site.name)
    except ExtractionError as exc:
        await _apply_next_check(engine, page, site)
        return CrawlResult(
            status=CrawlStatus.failed, pages_fetched=1, changes_detected=0,
            llm_calls=1, llm_cost_usd=0.0,
            error_text=f"extraction_failed: {exc.detail[:500]}",
        )

    async with session_scope(engine) as s:
        page_row = (await s.execute(select(Page).where(Page.id == page.id))).scalar_one()
        reconcile_result = await reconcile(s, page_row, ex.offerings)
        page_row.content_hash = new_hash
        page_row.last_fetched = datetime.now(UTC)
        page_row.last_changed = datetime.now(UTC)
        page_row.consecutive_failures = 0
        page_row.next_check_at = _schedule_next(site)

    for oid in reconcile_result.new:
        log.info("offering.new", offering_id=oid, site_id=site.id)
    for oid in reconcile_result.updated:
        log.info("offering.updated", offering_id=oid, site_id=site.id)
    for oid in reconcile_result.withdrawn:
        log.info("offering.withdrawn", offering_id=oid, site_id=site.id)
    log.info("page.changed", page_id=page.id, site_id=site.id, new_hash=new_hash)

    changes = len(reconcile_result.new) + len(reconcile_result.updated) + len(reconcile_result.withdrawn)
    return CrawlResult(
        status=CrawlStatus.ok, pages_fetched=1, changes_detected=changes,
        llm_calls=0 if ex.from_cache else 1,
        llm_cost_usd=ex.cost_usd,
        error_text=None,
    )


async def _apply_failure(engine: AsyncEngine, page: Page, site: Site, *, error_text: str) -> None:
    async with session_scope(engine) as s:
        row = (await s.execute(select(Page).where(Page.id == page.id))).scalar_one()
        row.consecutive_failures = (row.consecutive_failures or 0) + 1
        row.last_fetched = datetime.now(UTC)
        backoff_mul = min(2 ** row.consecutive_failures, _MAX_BACKOFF_MULTIPLIER)
        row.next_check_at = datetime.now(UTC) + timedelta(seconds=site.default_cadence_s * backoff_mul)


async def _apply_unchanged(engine: AsyncEngine, page: Page, site: Site) -> None:
    async with session_scope(engine) as s:
        row = (await s.execute(select(Page).where(Page.id == page.id))).scalar_one()
        row.last_fetched = datetime.now(UTC)
        row.consecutive_failures = 0
        row.next_check_at = _schedule_next(site)


async def _apply_next_check(engine: AsyncEngine, page: Page, site: Site) -> None:
    async with session_scope(engine) as s:
        row = (await s.execute(select(Page).where(Page.id == page.id))).scalar_one()
        row.last_fetched = datetime.now(UTC)
        row.next_check_at = _schedule_next(site)


def _schedule_next(site: Site) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=site.default_cadence_s)
```

- [ ] **Step 4: Run integration tests**

```bash
uv run pytest tests/integration/test_pipeline.py -v
uv run pytest
uv run ruff check .
uv run mypy src
```

Expected: 3 pipeline tests pass, full suite green.

- [ ] **Step 5: Commit**

```bash
git add src/yas/crawl/pipeline.py tests/integration/test_pipeline.py
git commit -m "feat(crawl): add pipeline orchestrator with CrawlRun bookkeeping"
```

---

## Task 11 — Scheduler loop + worker integration

**Files:**
- Create: `src/yas/crawl/scheduler.py`
- Modify: `src/yas/worker/runner.py`
- Modify: `src/yas/web/deps.py` (AppState now carries fetcher + llm)
- Modify: `src/yas/web/app.py` (construct fetcher + llm)
- Modify: `src/yas/__main__.py` (pass through)
- Create: `tests/integration/test_scheduler.py`

- [ ] **Step 1: Write the failing scheduler integration test**

`tests/integration/test_scheduler.py`:
```python
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from tests.fakes.llm import FakeLLMClient
from tests.fixtures.server import fixture_site
from yas.config import Settings
from yas.crawl.fetcher import DefaultFetcher
from yas.crawl.scheduler import crawl_scheduler_loop
from yas.db.base import Base
from yas.db.models import Offering, Page, Site
from yas.db.models._types import ProgramType
from yas.db.session import create_engine_for, session_scope
from yas.llm.schemas import ExtractedOffering


PAGE = "<html><body><main><h1>Baseball</h1></main></body></html>"


async def _init(tmp_path):
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/sched.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


@pytest.mark.asyncio
async def test_scheduler_picks_due_page_and_runs_pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    settings = Settings(_env_file=None, crawl_scheduler_tick_s=1, crawl_scheduler_batch_size=5)  # type: ignore[call-arg]
    engine = await _init(tmp_path)

    async with fixture_site(pages={"/p": PAGE}) as fx:
        async with session_scope(engine) as s:
            site = Site(name="Test", base_url=fx.base_url, default_cadence_s=3600)
            s.add(site)
            await s.flush()
            s.add(Page(site_id=site.id, url=fx.url("/p"), next_check_at=datetime.now(UTC) - timedelta(seconds=1)))

        fetcher = DefaultFetcher()
        llm = FakeLLMClient(default=[ExtractedOffering(name="Baseball", program_type=ProgramType.multisport)])
        task = asyncio.create_task(crawl_scheduler_loop(engine=engine, settings=settings, fetcher=fetcher, llm=llm))
        try:
            # Wait until an offering shows up OR timeout.
            for _ in range(60):
                async with session_scope(engine) as s:
                    offerings = (await s.execute(select(Offering))).scalars().all()
                if offerings:
                    break
                await asyncio.sleep(0.2)
            assert offerings and offerings[0].name == "Baseball"
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await fetcher.aclose()
    await engine.dispose()


@pytest.mark.asyncio
async def test_scheduler_skips_inactive_and_muted_sites(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    settings = Settings(_env_file=None, crawl_scheduler_tick_s=1)  # type: ignore[call-arg]
    engine = await _init(tmp_path)

    async with fixture_site(pages={"/p": PAGE}) as fx:
        async with session_scope(engine) as s:
            inactive = Site(name="Inactive", base_url=fx.base_url, active=False, default_cadence_s=3600)
            muted = Site(
                name="Muted", base_url=fx.base_url,
                muted_until=datetime.now(UTC) + timedelta(hours=1),
                default_cadence_s=3600,
            )
            s.add_all([inactive, muted])
            await s.flush()
            s.add(Page(site_id=inactive.id, url=fx.url("/p"), next_check_at=datetime.now(UTC) - timedelta(seconds=1)))
            s.add(Page(site_id=muted.id,    url=fx.url("/p"), next_check_at=datetime.now(UTC) - timedelta(seconds=1)))

        fetcher = DefaultFetcher()
        llm = FakeLLMClient()
        task = asyncio.create_task(crawl_scheduler_loop(engine=engine, settings=settings, fetcher=fetcher, llm=llm))
        try:
            await asyncio.sleep(3)  # enough for ~3 ticks
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await fetcher.aclose()
    # Nothing crawled — active-site filter held.
    # Note: muted sites DO still have pages crawled when they are the alert-mute
    # case in spec §3; but the scheduler here is gated by the site.muted_until
    # row condition per spec §3.6 → so neither site gets crawled.
    assert llm.call_count == 0
    await engine.dispose()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/test_scheduler.py -v`
Expected: import error.

> *Scope clarification:* the spec's distinction between **mute** (still crawl, skip alerts) and **pause** (stop crawling) is expressed at two different layers. For Phase 2 we only have the scheduler; it skips rows with `site.active=False` (paused) and *also* any `muted_until > now` (treated as paused for Phase 2). Phase 4 (alerting) reintroduces the finer-grained "mute the *alerts* but keep crawling" behavior. The test above reflects Phase 2's behavior.

- [ ] **Step 3: Implement the scheduler loop**

`src/yas/crawl/scheduler.py`:
```python
"""Poll for due pages and dispatch them through the pipeline."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.config import Settings
from yas.crawl.fetcher import Fetcher
from yas.crawl.pipeline import crawl_page
from yas.db.models import Page, Site
from yas.db.session import session_scope
from yas.llm.client import LLMClient
from yas.logging import get_logger

log = get_logger("yas.crawl.scheduler")


async def crawl_scheduler_loop(
    *,
    engine: AsyncEngine,
    settings: Settings,
    fetcher: Fetcher,
    llm: LLMClient,
) -> None:
    """Forever: every tick, find due pages, run them, await completion."""
    log.info("scheduler.start", tick_s=settings.crawl_scheduler_tick_s,
             batch_size=settings.crawl_scheduler_batch_size)
    try:
        while True:
            await _tick(engine=engine, settings=settings, fetcher=fetcher, llm=llm)
            await asyncio.sleep(settings.crawl_scheduler_tick_s)
    except asyncio.CancelledError:
        log.info("scheduler.stop")
        raise


async def _tick(
    *,
    engine: AsyncEngine,
    settings: Settings,
    fetcher: Fetcher,
    llm: LLMClient,
) -> None:
    now = datetime.now(UTC)
    async with session_scope(engine) as s:
        rows = (
            await s.execute(
                select(Page, Site)
                .join(Site, Page.site_id == Site.id)
                .where(
                    Site.active.is_(True),
                    or_(Site.muted_until.is_(None), Site.muted_until < now),
                    or_(Page.next_check_at.is_(None), Page.next_check_at <= now),
                )
                .order_by(Page.next_check_at.nulls_first())
                .limit(settings.crawl_scheduler_batch_size)
            )
        ).all()
        # Detach so we can use across sessions without lazy-load surprises.
        s.expunge_all()

    if not rows:
        return

    log.info("scheduler.tick", due=len(rows))
    tasks = [
        asyncio.create_task(
            crawl_page(engine=engine, fetcher=fetcher, llm=llm, page=page, site=site)
        )
        for page, site in rows
    ]
    await asyncio.gather(*tasks, return_exceptions=True)
```

- [ ] **Step 4: Extend AppState and create_app**

Edit `src/yas/web/deps.py`:

```python
"""Shared FastAPI dependencies."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from yas.config import Settings
from yas.crawl.fetcher import Fetcher
from yas.llm.client import LLMClient


class AppState:
    def __init__(
        self,
        engine: AsyncEngine,
        settings: Settings,
        fetcher: Fetcher | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        self.engine = engine
        self.settings = settings
        self.fetcher = fetcher
        self.llm = llm
```

Edit `src/yas/web/app.py`'s `create_app` to accept `fetcher` and `llm` kwargs and plumb them into `AppState`:

```python
def create_app(
    engine: AsyncEngine | None = None,
    settings: Settings | None = None,
    *,
    fetcher: Fetcher | None = None,
    llm: LLMClient | None = None,
) -> FastAPI:
    ...
    state = AppState(engine=e, settings=s, fetcher=fetcher, llm=llm)
    app.state.yas = state
    ...
```

Add the necessary imports at the top:
```python
from yas.crawl.fetcher import Fetcher
from yas.llm.client import LLMClient
```

- [ ] **Step 5: Update the worker runner**

Replace the body of `src/yas/worker/runner.py` with:

```python
"""Worker runner — heartbeat loop + crawl scheduler loop in a TaskGroup."""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncEngine

from yas.config import Settings
from yas.crawl.fetcher import DefaultFetcher, Fetcher
from yas.crawl.scheduler import crawl_scheduler_loop
from yas.llm.client import AnthropicClient, LLMClient
from yas.logging import get_logger
from yas.worker.heartbeat import beat_once

log = get_logger("yas.worker")


async def _heartbeat_loop(engine: AsyncEngine, settings: Settings) -> None:
    log.info("heartbeat.start", interval_s=settings.worker_heartbeat_interval_s)
    try:
        while True:
            ts = await beat_once(engine)
            log.debug("worker.heartbeat", ts=ts.isoformat())
            await asyncio.sleep(settings.worker_heartbeat_interval_s)
    except asyncio.CancelledError:
        log.info("heartbeat.stop")
        raise


async def run_worker(
    engine: AsyncEngine,
    settings: Settings,
    *,
    fetcher: Fetcher | None = None,
    llm: LLMClient | None = None,
) -> None:
    own_fetcher = fetcher is None
    fetcher = fetcher or DefaultFetcher()
    llm = llm or AnthropicClient(
        api_key=settings.anthropic_api_key,
        model=settings.llm_extraction_model,
    )
    log.info("worker.start")
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_heartbeat_loop(engine, settings))
            if settings.crawl_scheduler_enabled:
                tg.create_task(
                    crawl_scheduler_loop(engine=engine, settings=settings, fetcher=fetcher, llm=llm)
                )
    finally:
        if own_fetcher:
            await fetcher.aclose()
        log.info("worker.stop")
```

- [ ] **Step 6: Update `__main__.py` to construct + share the same fetcher/llm across api and worker in `all` mode**

Replace the `_run_all` and the `mode == "all"` branch with plumbing that constructs one `DefaultFetcher` and one `AnthropicClient` at startup and passes them to both `create_app` and `run_worker`:

```python
async def _run_all(settings: Settings, engine: AsyncEngine) -> None:
    from yas.crawl.fetcher import DefaultFetcher
    from yas.llm.client import AnthropicClient
    fetcher = DefaultFetcher()
    llm = AnthropicClient(api_key=settings.anthropic_api_key, model=settings.llm_extraction_model)
    try:
        config = uvicorn.Config(
            create_app(engine=engine, settings=settings, fetcher=fetcher, llm=llm),
            host=settings.host,
            port=settings.port,
            log_config=None,
        )
        server = uvicorn.Server(config)
        worker_task = asyncio.create_task(
            run_worker(engine, settings, fetcher=fetcher, llm=llm)
        )
        try:
            await server.serve()
        finally:
            worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker_task
    finally:
        await fetcher.aclose()
```

And the `api` branch: `create_app(engine=engine, settings=settings)` still works (no fetcher/llm needed for just `/healthz`+`/readyz`). Leave it as-is.

Make sure `contextlib` and the types are imported at top.

- [ ] **Step 7: Run the full suite**

```bash
uv run pytest -v
uv run ruff check .
uv run mypy src
```

Expected: 2 new scheduler tests pass, full suite green.

- [ ] **Step 8: Commit**

```bash
git add src/yas/crawl/scheduler.py src/yas/web/ src/yas/worker/runner.py src/yas/__main__.py tests/integration/test_scheduler.py
git commit -m "feat(worker): add crawl scheduler loop and TaskGroup integration"
```

---

## Task 12 — Site-management HTTP API

**Files:**
- Create: `src/yas/web/routes/__init__.py`
- Create: `src/yas/web/routes/sites.py`
- Create: `src/yas/web/routes/sites_schemas.py`
- Modify: `src/yas/web/app.py` (mount router)
- Create: `tests/integration/test_api_sites.py`

- [ ] **Step 1: Write the failing API tests**

`tests/integration/test_api_sites.py`:
```python
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from yas.db.base import Base
from yas.db.models import Page, Site
from yas.db.session import create_engine_for, session_scope
from yas.web.app import create_app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    url = f"sqlite+aiosqlite:///{tmp_path}/api.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app = create_app(engine=engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_and_list_site(client):
    c, _ = client
    r = await c.post("/api/sites", json={
        "name": "Lil Sluggers",
        "base_url": "https://example.com/",
        "needs_browser": True,
        "default_cadence_s": 3600,
        "pages": [{"url": "https://example.com/p", "kind": "schedule"}],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] > 0
    assert body["name"] == "Lil Sluggers"
    assert len(body["pages"]) == 1
    r = await c.get("/api/sites")
    assert r.status_code == 200
    assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_get_site_returns_pages(client):
    c, _ = client
    created = await c.post("/api/sites", json={
        "name": "X", "base_url": "https://x/",
        "pages": [{"url": "https://x/a"}, {"url": "https://x/b"}],
    })
    site_id = created.json()["id"]
    r = await c.get(f"/api/sites/{site_id}")
    assert r.status_code == 200
    assert {p["url"] for p in r.json()["pages"]} == {"https://x/a", "https://x/b"}


@pytest.mark.asyncio
async def test_patch_site(client):
    c, _ = client
    created = await c.post("/api/sites", json={"name": "X", "base_url": "https://x/"})
    sid = created.json()["id"]
    r = await c.patch(f"/api/sites/{sid}", json={"active": False, "default_cadence_s": 60})
    assert r.status_code == 200
    body = r.json()
    assert body["active"] is False
    assert body["default_cadence_s"] == 60


@pytest.mark.asyncio
async def test_delete_site_cascades(client):
    c, engine = client
    created = await c.post("/api/sites", json={
        "name": "X", "base_url": "https://x/",
        "pages": [{"url": "https://x/a"}],
    })
    sid = created.json()["id"]
    r = await c.delete(f"/api/sites/{sid}")
    assert r.status_code == 204
    async with session_scope(engine) as s:
        assert (await s.execute(select(Site))).scalars().all() == []
        assert (await s.execute(select(Page))).scalars().all() == []


@pytest.mark.asyncio
async def test_add_and_remove_page(client):
    c, _ = client
    created = await c.post("/api/sites", json={"name": "X", "base_url": "https://x/"})
    sid = created.json()["id"]
    r = await c.post(f"/api/sites/{sid}/pages", json={"url": "https://x/added"})
    assert r.status_code == 201
    pid = r.json()["id"]
    r = await c.delete(f"/api/sites/{sid}/pages/{pid}")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_crawl_now_resets_next_check_at(client):
    c, engine = client
    created = await c.post("/api/sites", json={
        "name": "X", "base_url": "https://x/",
        "pages": [{"url": "https://x/a"}],
    })
    sid = created.json()["id"]
    # Simulate a future-scheduled page.
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page))).scalars().one()
        from datetime import UTC, datetime, timedelta
        page.next_check_at = datetime.now(UTC) + timedelta(days=1)
    r = await c.post(f"/api/sites/{sid}/crawl-now")
    assert r.status_code == 202
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page))).scalars().one()
        from datetime import UTC, datetime
        # tz-aware comparison
        next_check = page.next_check_at.replace(tzinfo=UTC) if page.next_check_at.tzinfo is None else page.next_check_at
        assert next_check <= datetime.now(UTC) + __import__("datetime").timedelta(seconds=1)


@pytest.mark.asyncio
async def test_get_nonexistent_site_returns_404(client):
    c, _ = client
    r = await c.get("/api/sites/999")
    assert r.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/test_api_sites.py -v`
Expected: import error / 404 everywhere.

- [ ] **Step 3: Implement `src/yas/web/routes/sites_schemas.py`**

```python
"""Pydantic models for the /api/sites endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class PageIn(BaseModel):
    url: HttpUrl
    kind: str = "schedule"


class PageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    url: str
    kind: str
    content_hash: str | None = None
    last_fetched: datetime | None = None
    next_check_at: datetime | None = None


class SiteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    base_url: HttpUrl
    needs_browser: bool = False
    default_cadence_s: int = 6 * 3600
    crawl_hints: dict[str, Any] = {}
    pages: list[PageIn] = []


class SiteUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: bool | None = None
    muted_until: datetime | None = None
    default_cadence_s: int | None = None
    needs_browser: bool | None = None
    crawl_hints: dict[str, Any] | None = None


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    base_url: str
    adapter: str
    needs_browser: bool
    active: bool
    default_cadence_s: int
    muted_until: datetime | None
    pages: list[PageOut] = []
```

- [ ] **Step 4: Implement `src/yas/web/routes/sites.py`**

```python
"""HTTP endpoints for managing sites and their tracked pages."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from yas.db.models import Page, Site
from yas.db.session import session_scope
from yas.web.routes.sites_schemas import (
    PageIn,
    PageOut,
    SiteCreate,
    SiteOut,
    SiteUpdate,
)


router = APIRouter(prefix="/api/sites", tags=["sites"])


def _engine(req: Request):
    return req.app.state.yas.engine


@router.post("", response_model=SiteOut, status_code=status.HTTP_201_CREATED)
async def create_site(payload: SiteCreate, request: Request) -> SiteOut:
    now = datetime.now(UTC)
    async with session_scope(_engine(request)) as s:
        site = Site(
            name=payload.name,
            base_url=str(payload.base_url),
            needs_browser=payload.needs_browser,
            default_cadence_s=payload.default_cadence_s,
            crawl_hints=payload.crawl_hints,
        )
        s.add(site)
        await s.flush()
        for p in payload.pages:
            s.add(Page(site_id=site.id, url=str(p.url), kind=p.kind, next_check_at=now))
        await s.flush()
        pages = (
            await s.execute(select(Page).where(Page.site_id == site.id).order_by(Page.id))
        ).scalars().all()
        return SiteOut.model_validate({
            **_site_attrs(site),
            "pages": [PageOut.model_validate(p) for p in pages],
        })


@router.get("", response_model=list[SiteOut])
async def list_sites(request: Request) -> list[SiteOut]:
    async with session_scope(_engine(request)) as s:
        sites = (await s.execute(select(Site).order_by(Site.id))).scalars().all()
        out: list[SiteOut] = []
        for site in sites:
            pages = (
                await s.execute(select(Page).where(Page.site_id == site.id).order_by(Page.id))
            ).scalars().all()
            out.append(SiteOut.model_validate({
                **_site_attrs(site),
                "pages": [PageOut.model_validate(p) for p in pages],
            }))
        return out


@router.get("/{site_id}", response_model=SiteOut)
async def get_site(site_id: int, request: Request) -> SiteOut:
    async with session_scope(_engine(request)) as s:
        site = (await s.execute(select(Site).where(Site.id == site_id))).scalar_one_or_none()
        if site is None:
            raise HTTPException(status_code=404, detail=f"site {site_id} not found")
        pages = (
            await s.execute(select(Page).where(Page.site_id == site_id).order_by(Page.id))
        ).scalars().all()
        return SiteOut.model_validate({
            **_site_attrs(site),
            "pages": [PageOut.model_validate(p) for p in pages],
        })


@router.patch("/{site_id}", response_model=SiteOut)
async def update_site(site_id: int, patch: SiteUpdate, request: Request) -> SiteOut:
    async with session_scope(_engine(request)) as s:
        site = (await s.execute(select(Site).where(Site.id == site_id))).scalar_one_or_none()
        if site is None:
            raise HTTPException(status_code=404, detail=f"site {site_id} not found")
        for field, value in patch.model_dump(exclude_unset=True).items():
            setattr(site, field, value)
        await s.flush()
        pages = (
            await s.execute(select(Page).where(Page.site_id == site_id).order_by(Page.id))
        ).scalars().all()
        return SiteOut.model_validate({
            **_site_attrs(site),
            "pages": [PageOut.model_validate(p) for p in pages],
        })


@router.delete("/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_site(site_id: int, request: Request) -> None:
    async with session_scope(_engine(request)) as s:
        site = (await s.execute(select(Site).where(Site.id == site_id))).scalar_one_or_none()
        if site is None:
            raise HTTPException(status_code=404, detail=f"site {site_id} not found")
        await s.delete(site)


@router.post("/{site_id}/pages", response_model=PageOut, status_code=status.HTTP_201_CREATED)
async def add_page(site_id: int, payload: PageIn, request: Request) -> PageOut:
    now = datetime.now(UTC)
    async with session_scope(_engine(request)) as s:
        site = (await s.execute(select(Site).where(Site.id == site_id))).scalar_one_or_none()
        if site is None:
            raise HTTPException(status_code=404, detail=f"site {site_id} not found")
        page = Page(site_id=site_id, url=str(payload.url), kind=payload.kind, next_check_at=now)
        s.add(page)
        await s.flush()
        return PageOut.model_validate(page)


@router.delete("/{site_id}/pages/{page_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_page(site_id: int, page_id: int, request: Request) -> None:
    async with session_scope(_engine(request)) as s:
        page = (
            await s.execute(select(Page).where(Page.id == page_id, Page.site_id == site_id))
        ).scalar_one_or_none()
        if page is None:
            raise HTTPException(status_code=404, detail=f"page {page_id} not found")
        await s.delete(page)


@router.post("/{site_id}/crawl-now", status_code=status.HTTP_202_ACCEPTED)
async def crawl_now(site_id: int, request: Request) -> dict[str, int]:
    now = datetime.now(UTC)
    async with session_scope(_engine(request)) as s:
        site = (await s.execute(select(Site).where(Site.id == site_id))).scalar_one_or_none()
        if site is None:
            raise HTTPException(status_code=404, detail=f"site {site_id} not found")
        pages = (await s.execute(select(Page).where(Page.site_id == site_id))).scalars().all()
        for p in pages:
            p.next_check_at = now
        return {"scheduled": len(pages)}


def _site_attrs(site: Site) -> dict:
    return {
        "id": site.id,
        "name": site.name,
        "base_url": site.base_url,
        "adapter": site.adapter,
        "needs_browser": site.needs_browser,
        "active": site.active,
        "default_cadence_s": site.default_cadence_s,
        "muted_until": site.muted_until,
    }
```

- [ ] **Step 5: Create `src/yas/web/routes/__init__.py`**

```python
from yas.web.routes.sites import router as sites_router

__all__ = ["sites_router"]
```

- [ ] **Step 6: Mount the router in `create_app`**

Edit `src/yas/web/app.py` — at the bottom of `create_app`, before the shutdown hook:

```python
    from yas.web.routes import sites_router
    app.include_router(sites_router)
```

- [ ] **Step 7: Run tests and gates**

```bash
uv run pytest tests/integration/test_api_sites.py -v
uv run pytest
uv run ruff check .
uv run mypy src
```

Expected: 7 API tests pass, full suite green.

- [ ] **Step 8: Commit**

```bash
git add src/yas/web/routes/ src/yas/web/app.py tests/integration/test_api_sites.py
git commit -m "feat(web): add /api/sites site-management endpoints"
```

---

## Task 13 — Dockerfile + compose + Playwright install

**Files:**
- Modify: `Dockerfile`

- [ ] **Step 1: Add Playwright install step**

Edit `Dockerfile`. After the second `uv sync` (the one that installs the project), add:

```dockerfile
# Install Chromium + its OS deps. Done after uv sync so `playwright` is on PATH.
RUN uv run playwright install --with-deps chromium
```

(`--with-deps` pulls in the apt packages Chromium needs — fonts, libnss, etc.)

- [ ] **Step 2: Rebuild and smoke-test end-to-end**

```bash
rm -f data/activities.db*
docker compose build
docker compose up -d
sleep 15

# Health should be green.
curl -s localhost:8080/healthz
curl -s localhost:8080/readyz

# Register a tiny test site using the new API.
curl -sS -X POST localhost:8080/api/sites \
  -H 'content-type: application/json' \
  -d '{"name":"Smoke","base_url":"https://httpbin.org/","pages":[{"url":"https://httpbin.org/html"}]}'

# Watch a tick happen. With scheduler tick=30s, give it ~45s.
sleep 45
docker compose logs yas-worker | grep -E "scheduler|crawl|offering" | tail -20

# Expect either success or a graceful schema failure in crawl_runs.error_text
sqlite3 data/activities.db 'select id, status, pages_fetched, changes_detected, llm_calls, substr(coalesce(error_text,""),1,120) from crawl_runs'

docker compose down
```

Expected: `/healthz` 200, site created (201), at least one `crawl_runs` row recorded. With a nonop API key, the extraction call will fail (authentication error surfaced as `ExtractionError` → `crawl_runs.status=failed` → `error_text` populated). That failure is the *expected* shape — no silent failures.

- [ ] **Step 3: Commit**

```bash
git add Dockerfile
git commit -m "chore(docker): install Chromium with deps for Playwright fetcher"
```

---

## Task 14 — Smoke script + README + phase exit verification

**Files:**
- Create: `scripts/smoke_phase2.sh`
- Modify: `README.md`

- [ ] **Step 1: Create the smoke script**

```bash
mkdir -p scripts
```

`scripts/smoke_phase2.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Phase 2 end-of-phase manual smoke. Requires:
#   - Docker Compose
#   - A real YAS_ANTHROPIC_API_KEY in .env
#   - Network access to www.lilsluggerschicago.com

cd "$(dirname "$0")/.."

if ! grep -q '^YAS_ANTHROPIC_API_KEY=sk-' .env 2>/dev/null || grep -q '^YAS_ANTHROPIC_API_KEY=sk-test-nonop$' .env; then
  echo "ERROR: .env must set YAS_ANTHROPIC_API_KEY to a real key." >&2
  exit 2
fi

rm -f data/activities.db data/activities.db-shm data/activities.db-wal
docker compose up -d yas-migrate
docker compose logs yas-migrate | tail -5
docker compose up -d yas-worker yas-api
sleep 10

echo "Registering Lil Sluggers..."
curl -sS -X POST localhost:8080/api/sites \
  -H 'content-type: application/json' \
  -d '{
    "name": "Lil Sluggers Chicago",
    "base_url": "https://www.lilsluggerschicago.com/",
    "needs_browser": true,
    "pages": [
      {"url": "https://www.lilsluggerschicago.com/spring-session-24.html", "kind": "schedule"}
    ]
  }' | jq .

echo "Waiting 90s for scheduler tick + crawl + extract..."
sleep 90

echo ""
echo "--- site detail ---"
curl -sS localhost:8080/api/sites/1 | jq .

echo ""
echo "--- offerings ---"
sqlite3 data/activities.db 'select id, name, program_type, age_min, age_max, start_date, time_start from offerings'

echo ""
echo "--- last 5 crawl_runs ---"
sqlite3 data/activities.db 'select id, site_id, status, pages_fetched, changes_detected, llm_calls, printf("%.5f", llm_cost_usd), substr(coalesce(error_text,""),1,120) from crawl_runs order by id desc limit 5'

echo ""
echo "Re-running crawl-now to verify cache hit on second run..."
curl -sS -X POST localhost:8080/api/sites/1/crawl-now | jq .
sleep 45

echo ""
echo "--- last 5 crawl_runs after second run ---"
sqlite3 data/activities.db 'select id, site_id, status, pages_fetched, changes_detected, llm_calls, printf("%.5f", llm_cost_usd), substr(coalesce(error_text,""),1,120) from crawl_runs order by id desc limit 5'

echo ""
echo "done. bringing compose down..."
docker compose down
```

```bash
chmod +x scripts/smoke_phase2.sh
```

- [ ] **Step 2: Update README**

Edit `README.md` — add a **Managing sites** section after the Quickstart:

```markdown
## Managing sites (Phase 2 API)

Sites and their tracked pages are registered via HTTP. The API is
un-authed and bound to the container network; expose it only on
trusted hosts.

```bash
# Register a site with one tracked schedule page.
curl -sS -X POST localhost:8080/api/sites \
  -H 'content-type: application/json' \
  -d '{
    "name": "Example Sports",
    "base_url": "https://example.com/",
    "needs_browser": false,
    "pages": [{"url": "https://example.com/schedule", "kind": "schedule"}]
  }'

curl localhost:8080/api/sites              # list
curl localhost:8080/api/sites/1            # one site with pages
curl -X POST localhost:8080/api/sites/1/crawl-now   # schedule now
curl -X DELETE localhost:8080/api/sites/1  # remove site + pages + offerings
```

`robots.txt` is **ignored by default**. Set `crawl_hints: {"respect_robots": true}` on a site to opt in.

The scheduler ticks every 30 s and crawls pages whose `next_check_at` is in the past, respecting `site.default_cadence_s` after each successful crawl.
```

Also add a line to the **Project layout** section:

```
  crawl/           fetcher, change detector, extractor, reconciler, scheduler, pipeline
  llm/             Pydantic schemas, prompt builder, AnthropicClient
  web/routes/      site-management HTTP endpoints
```

- [ ] **Step 3: Final verification — all phase exit gates**

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -v
rm -f data/activities.db*
docker compose build
docker compose up -d
sleep 15
curl -s localhost:8080/healthz
curl -s localhost:8080/readyz
docker compose down
```

Each must be green.

Then (with a **real** `YAS_ANTHROPIC_API_KEY` in `.env`):

```bash
./scripts/smoke_phase2.sh
```

Expected output:

- First run: at least one `offerings` row with non-null core fields, `crawl_runs.status=ok`, `llm_calls=1`, `llm_cost_usd > 0` (typically < $0.01)
- Second run: `llm_calls=0` on the new run (extraction_cache hit observed)

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke_phase2.sh README.md
git commit -m "docs: add phase-2 smoke script and site-management quickstart"
```

---

## Phase 2 exit checklist

Apply @superpowers:verification-before-completion before declaring this phase done. Every box below must be verified with an actual command, not asserted.

- [ ] `uv run ruff check .` clean
- [ ] `uv run ruff format --check .` clean
- [ ] `uv run mypy src` clean
- [ ] `uv run pytest` — all prior Phase 1 tests plus Phase 2 additions green
- [ ] `docker compose up -d`: migrate + worker + api healthy
- [ ] `POST /api/sites` + `POST /api/sites/{id}/pages` flow round-trips via `GET /api/sites`
- [ ] `/docs` lists all 7 site-management endpoints with schemas
- [ ] `scripts/smoke_phase2.sh` succeeds against the real Lil Sluggers URL with a real API key
- [ ] Second smoke run against the unchanged page reports `llm_calls=0` on the new crawl_runs row
- [ ] No silent failures: every fetch/extract failure in a smoke test shows up in `crawl_runs.error_text`

When all boxes check, Phase 2 is complete. Merge with `--no-ff` to `main`, then proceed to **Phase 3 — Matching & watchlist**, written as its own plan.
