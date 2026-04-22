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
