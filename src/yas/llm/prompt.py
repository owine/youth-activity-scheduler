"""Prompt construction for the extraction tool call.

The system prompt declares the role, the fixed `program_type` vocabulary, date
format conventions, and a "prefer null to guessing" instruction. The user
message carries the crawl date, the (normalized) HTML, URL, and site name."""

from __future__ import annotations

from datetime import UTC, date, datetime

from yas.db.models._types import ProgramType

# Derived from the enum the tool schema validates against, so the prompt can't
# drift from it again. A hand-copied list had fallen 30+ values behind (no
# "tennis"), which Haiku 5.5 followed literally and misfiled tennis as "racquet".
_PROGRAM_TYPES = tuple(t.value for t in ProgramType)

_SYSTEM = f"""You extract youth activity offerings from a single web page into a
structured list. You are called with a tool named `report_offerings` — always
respond by invoking that tool with the offerings you find. Do not write prose.

For each offering, fill these fields where the page makes them clear:
- name (required, as the program is advertised)
- description (optional, 1-2 sentences)
- age_min / age_max (inclusive, integer years)
- program_type: one of {", ".join(_PROGRAM_TYPES)}. Pick the most specific
  match; use an umbrella value (racquet, multisport, camp_general) only when no
  specific one fits, and "unknown" only when truly unclassifiable.
- start_date / end_date (YYYY-MM-DD)
- days_of_week: subset of ["mon","tue","wed","thu","fri","sat","sun"]
- attends_one_day: true only when the page says a family picks ONE of the
  listed days ("choose a day of the week", "classes meet one day per week",
  "pick your day"). Pages often say this once, in a sign-up note for the whole
  page; it then applies to every item on that page that lists several days.
  False when everyone attends every listed day, as at a Mon-Fri camp, and false
  when the page doesn't say.
- time_start / time_end (HH:MM, 24-hour)
- location_name, location_address (if a specific venue is named)
- price_cents (integer, e.g. $85.00 → 8500)
- registration_opens_at (YYYY-MM-DDTHH:MM timezone-naive acceptable)
- registration_url

Strict rules:
1. If a field is not clearly stated on the page, return null rather than guessing.
   Plausible inference from context is fine; fabrication is not.
2. One entry per distinct offering. Separate sessions of a program ("Session 1",
   "Session 2") are separate items. When a session is offered at several times,
   emit one item per time slot as the page groups them: days the page lists
   together under one time share an item, and days the page lists separately get
   their own. "Mon-Fri 10:30 am & 4:00 pm, Sat 9:00 am" is three items (mon-fri
   10:30, mon-fri 16:00, sat 09:00); "Saturday 9:00 am, Sunday 9:00 am" is two.
   If the page states how long a class lasts, derive time_end from it.
3. If the page lists no offerings, return an empty list.
4. When a date omits the year ("October 26th - December 19th"), infer the year
   from the crawl date given with the page. This is inference from context under
   rule 1, not guessing. Pages list current and upcoming sessions, and sometimes
   ones that just finished, so:
   - give end_date (start_date, if there is no end) the earliest year that puts it
     no more than two months before the crawl date;
   - give start_date the latest year that keeps it on or before end_date, so a
     session crossing New Year starts in the earlier year;
   - give registration_opens_at the latest year that keeps it on or before
     start_date.
   If the page pairs a date with a weekday ("Sat, Oct 24"), use the year in which
   they match instead."""


def build_extraction_prompt(
    *, html: str, url: str, site_name: str, today: date | None = None
) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for the extraction call.

    `today` is the crawl date, defaulting to today in UTC. Some pages give dates
    without a year, and rule 4 resolves them against it, looking forward: a summer
    camp advertised in November is next summer's, not the one just gone. Without
    the date, Haiku 4.5 guessed (2024 and 2025 for pages crawled in 2026) and
    Haiku 5.5 returns null.
    The date goes in the user message, which already varies per page.
    """
    crawled = (today or datetime.now(UTC).date()).isoformat()
    user = (
        f"Site: {site_name}\nURL: {url}\nCrawled on: {crawled}\n\n"
        f"--- page content ---\n{html}\n--- end page content ---"
    )
    return _SYSTEM, user
