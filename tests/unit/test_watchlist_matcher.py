from dataclasses import dataclass

from yas.db.models._types import WatchlistPriority
from yas.matching.watchlist import matches_watchlist


@dataclass
class _Entry:
    id: int
    pattern: str
    site_id: int | None = None
    priority: str = WatchlistPriority.normal.value
    active: bool = True


@dataclass
class _Offering:
    id: int = 1
    site_id: int = 1
    name: str = ""


def test_substring_match():
    e = _Entry(id=1, pattern="kickers")
    o = _Offering(name="Little Kickers Saturday")
    hit = matches_watchlist(o, [e], site_id=1)
    assert hit is not None
    assert hit.reason == "substring"


def test_substring_case_insensitive():
    e = _Entry(id=1, pattern="KICKERS")
    o = _Offering(name="Little Kickers Saturday")
    hit = matches_watchlist(o, [e], site_id=1)
    assert hit is not None


def test_glob_match():
    e = _Entry(id=1, pattern="little *")
    o = _Offering(name="Little Sluggers Spring")
    hit = matches_watchlist(o, [e], site_id=1)
    assert hit is not None
    assert hit.reason == "glob"


def test_fnmatch_requires_full_string_match_not_substring():
    # Pins a gotcha: fnmatchcase matches the WHOLE string, not a substring.
    # `t?ball` (normalized to `t ball`) does NOT match `t ball coach pitch`
    # because fnmatch requires the pattern to cover the whole name. Users who
    # want substring semantics with wildcards should write `*t*ball*`.
    e = _Entry(id=1, pattern="t?ball")
    o = _Offering(name="T-ball Coach Pitch")  # normalized: "t ball coach pitch"
    assert matches_watchlist(o, [e], site_id=1) is None


def test_glob_wildcards_are_substring_equivalent_when_bracketed():
    e = _Entry(id=1, pattern="*kickers*")
    o = _Offering(name="Little Kickers Saturday")
    hit = matches_watchlist(o, [e], site_id=1)
    assert hit is not None
    assert hit.reason == "glob"


def test_site_id_scope_matches_across_sites_when_null():
    e = _Entry(id=1, pattern="soccer", site_id=None)
    o1 = _Offering(site_id=1, name="Spring Soccer")
    o2 = _Offering(site_id=2, name="Summer Soccer")
    assert matches_watchlist(o1, [e], site_id=1) is not None
    assert matches_watchlist(o2, [e], site_id=2) is not None


def test_site_id_scope_rejects_wrong_site():
    e = _Entry(id=1, pattern="soccer", site_id=5)
    o = _Offering(site_id=1, name="Spring Soccer")
    assert matches_watchlist(o, [e], site_id=1) is None


def test_priority_high_beats_normal():
    e_high = _Entry(id=2, pattern="kickers", priority=WatchlistPriority.high.value)
    e_normal = _Entry(id=1, pattern="kickers", priority=WatchlistPriority.normal.value)
    o = _Offering(name="Little Kickers")
    hit = matches_watchlist(o, [e_normal, e_high], site_id=1)
    assert hit is not None
    assert hit.entry.id == 2  # high wins


def test_among_same_priority_lowest_id_wins():
    e1 = _Entry(id=1, pattern="kickers")
    e2 = _Entry(id=2, pattern="kickers")
    o = _Offering(name="Little Kickers")
    hit = matches_watchlist(o, [e2, e1], site_id=1)
    assert hit.entry.id == 1


def test_inactive_entries_ignored():
    e = _Entry(id=1, pattern="kickers", active=False)
    o = _Offering(name="Little Kickers")
    assert matches_watchlist(o, [e], site_id=1) is None


def test_no_match_returns_none():
    e = _Entry(id=1, pattern="baseball")
    o = _Offering(name="Spring Soccer")
    assert matches_watchlist(o, [e], site_id=1) is None
