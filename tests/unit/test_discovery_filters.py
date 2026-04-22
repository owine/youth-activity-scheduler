import pytest

from yas.discovery.filters import is_junk

# Each: (url, expected_is_junk)
_CASES = [
    # Path prefixes — rejected
    ("https://example.com/wp-admin/", True),
    ("https://example.com/wp-content/uploads/foo.png", True),
    ("https://example.com/wp-json/api/v2", True),
    ("https://example.com/feed/", True),
    ("https://example.com/author/jane/", True),
    ("https://example.com/tag/soccer/", True),
    ("https://example.com/category/news/", True),
    ("https://example.com/comments/feed", True),
    ("https://example.com/login", True),
    ("https://example.com/account", True),
    ("https://example.com/cart", True),
    ("https://example.com/checkout", True),
    # Query signatures — rejected
    ("https://example.com/?replytocom=123", True),
    ("https://example.com/?s=search+term", True),
    # File extensions — rejected
    ("https://example.com/sitemap.xml", True),
    ("https://example.com/logo.png", True),
    ("https://example.com/hero.jpg", True),
    ("https://example.com/icon.svg", True),
    ("https://example.com/style.css", True),
    ("https://example.com/app.js", True),
    ("https://example.com/font.woff2", True),
    # PDFs — ALLOWED
    ("https://example.com/spring-2026.pdf", False),
    ("https://example.com/programs/brochure.PDF", False),
    # Real-looking program pages — ALLOWED
    ("https://example.com/programs/summer-camps/", False),
    ("https://example.com/register", False),
    ("https://example.com/schedule-2026", False),
    ("https://example.com/", False),
]


@pytest.mark.parametrize("url,expected", _CASES)
def test_is_junk(url, expected):
    assert is_junk(url) is expected
