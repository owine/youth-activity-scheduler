from yas.db.models._types import ProgramType
from yas.matching.aliases import INTEREST_ALIASES


def test_every_program_type_has_alias_entry():
    for pt in ProgramType:
        if pt == ProgramType.unknown:
            continue
        assert pt.value in INTEREST_ALIASES, f"{pt.value} missing from INTEREST_ALIASES"


def test_aliases_are_lowercase_no_punctuation_clones():
    for _key, values in INTEREST_ALIASES.items():
        for v in values:
            assert v == v.lower(), f"alias '{v}' is not lowercase"
