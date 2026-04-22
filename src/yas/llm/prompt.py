"""Prompt construction for the extraction tool call.

The system prompt declares the role, the fixed `program_type` vocabulary, date
format conventions, and a "prefer null to guessing" instruction. The user
message carries the (normalized) HTML, URL, and site name."""

from __future__ import annotations

_PROGRAM_TYPES = (
    "soccer",
    "swim",
    "martial_arts",
    "art",
    "music",
    "stem",
    "dance",
    "gym",
    "multisport",
    "outdoor",
    "academic",
    "camp_general",
    "unknown",
)

_SYSTEM = f"""You extract youth activity offerings from a single web page into a
structured list. You are called with a tool named `report_offerings` — always
respond by invoking that tool with the offerings you find. Do not write prose.

For each offering, fill these fields where the page makes them clear:
- name (required, as the program is advertised)
- description (optional, 1-2 sentences)
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
        f"Site: {site_name}\nURL: {url}\n\n--- page content ---\n{html}\n--- end page content ---"
    )
    return _SYSTEM, user
