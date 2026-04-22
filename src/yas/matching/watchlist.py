"""Pure watchlist pattern matching — substring OR glob (no regex)."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from typing import Any, Literal

from yas.crawl.normalize import normalize_name
from yas.db.models._types import WatchlistPriority

# Preserve fnmatch wildcards (*, ?) while applying the same lower/strip-punct/
# collapse-whitespace rules that `normalize_name` uses on offering names.
_PATTERN_PUNCT_RE = re.compile(r"[^\w\s*?]")
_WS_RE = re.compile(r"\s+")


def _normalize_pattern(pattern: str) -> str:
    s = pattern.lower()
    s = _PATTERN_PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


@dataclass(frozen=True)
class WatchlistHit:
    entry: Any
    reason: Literal["substring", "glob"]


def _is_glob(pattern: str) -> bool:
    return "*" in pattern or "?" in pattern


def _priority_rank(priority_val: str) -> int:
    # high before normal; unknown priorities sort last.
    if priority_val == WatchlistPriority.high.value:
        return 0
    if priority_val == WatchlistPriority.normal.value:
        return 1
    return 2


def matches_watchlist(offering: Any, entries: list[Any], *, site_id: int) -> WatchlistHit | None:
    normalized_name = normalize_name(offering.name or "")

    # Stable order: priority then id asc.
    def _key(e: Any) -> tuple[int, int]:
        prio = getattr(e.priority, "value", e.priority)
        return (_priority_rank(prio), e.id)

    for entry in sorted(entries, key=_key):
        if not entry.active:
            continue
        if entry.site_id is not None and entry.site_id != site_id:
            continue
        pattern_norm = _normalize_pattern(entry.pattern)
        if _is_glob(entry.pattern):
            # fnmatchcase operates on the raw (normalized) strings.
            if fnmatch.fnmatchcase(normalized_name, pattern_norm):
                return WatchlistHit(entry=entry, reason="glob")
        else:
            if pattern_norm in normalized_name:
                return WatchlistHit(entry=entry, reason="substring")
    return None
