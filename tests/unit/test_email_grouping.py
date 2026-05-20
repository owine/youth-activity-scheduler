"""Pure unit tests for the digest site->program grouping helper."""

from __future__ import annotations

from yas.email.builders import _group_matches_by_site, _program_label


def _m(site_id, site_name, program_type, name, score):
    return {
        "offering_id": hash((site_id, name)) & 0xFFFF,
        "offering_name": name,
        "site_id": site_id,
        "site_name": site_name,
        "program_type": program_type,
        "score": score,
        "start_date": None,
        "price_cents": None,
        "registration_opens_at": None,
        "registration_url": None,
    }


def test_program_label_titlecases_and_maps_unknown():
    assert _program_label("soccer") == "Soccer"
    assert _program_label("martial_arts") == "Martial Arts"
    assert _program_label("unknown") == "Other"


def test_groups_by_site_then_program():
    # Flat list, already score-sorted desc (as gather_digest_payload produces).
    matches = [
        _m(1, "Park District", "soccer", "Soccer Camp", 0.91),
        _m(1, "Park District", "swim", "Summer Swim", 0.80),
        _m(1, "Park District", "soccer", "Lil Kickers", 0.74),
        _m(2, "YMCA", "dance", "Ballet I", 0.66),
    ]
    groups = _group_matches_by_site(matches)

    # Two sites, ordered by best score desc: Park District (0.91) then YMCA (0.66).
    assert [g["site_name"] for g in groups] == ["Park District", "YMCA"]

    park = groups[0]
    # Programs ordered by their best offering's score: soccer (0.91) before swim (0.80).
    assert [p["program_type"] for p in park["programs"]] == ["soccer", "swim"]
    assert [p["program_label"] for p in park["programs"]] == ["Soccer", "Swim"]
    # Offerings within soccer ordered by score desc.
    soccer = park["programs"][0]
    assert [o["offering_name"] for o in soccer["offerings"]] == ["Soccer Camp", "Lil Kickers"]

    ymca = groups[1]
    assert ymca["site_id"] == 2
    assert [p["program_type"] for p in ymca["programs"]] == ["dance"]


def test_empty_list_returns_empty():
    assert _group_matches_by_site([]) == []


def test_missing_site_name_groups_under_blank():
    groups = _group_matches_by_site([_m(5, "", "art", "Painting", 0.5)])
    assert groups[0]["site_id"] == 5
    assert groups[0]["site_name"] == ""
