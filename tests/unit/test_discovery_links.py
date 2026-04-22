from yas.discovery.links import extract_internal_links


def test_extracts_same_host_links_with_anchor_text():
    html = """<html><body>
      <a href="/programs/">Our Programs</a>
      <a href="/register/">Register</a>
      <a href="https://example.com/schedule">Schedule</a>
    </body></html>"""
    pairs = extract_internal_links(html, "https://example.com/")
    urls = {u for u, _ in pairs}
    assert urls == {
        "https://example.com/programs/",
        "https://example.com/register/",
        "https://example.com/schedule",
    }


def test_drops_external_links():
    html = """<html><body>
      <a href="/programs/">Programs</a>
      <a href="https://other.com/whatever">Other</a>
    </body></html>"""
    pairs = extract_internal_links(html, "https://example.com/")
    urls = [u for u, _ in pairs]
    assert urls == ["https://example.com/programs/"]


def test_drops_hash_and_mailto():
    html = """<html><body>
      <a href="#section">Anchor</a>
      <a href="mailto:a@b.com">Email</a>
      <a href="tel:123">Call</a>
      <a href="/real/">Real</a>
    </body></html>"""
    pairs = extract_internal_links(html, "https://example.com/")
    urls = [u for u, _ in pairs]
    assert urls == ["https://example.com/real/"]


def test_preserves_longest_anchor_text_on_dedup():
    html = """<html><body>
      <a href="/programs/">Programs</a>
      <a href="/programs/">Browse Our Summer Programs</a>
    </body></html>"""
    pairs = extract_internal_links(html, "https://example.com/")
    assert pairs == [("https://example.com/programs/", "Browse Our Summer Programs")]


def test_strips_fragment():
    html = '<a href="/programs/#toc">Programs</a>'
    pairs = extract_internal_links(html, "https://example.com/")
    urls = [u for u, _ in pairs]
    assert urls == ["https://example.com/programs/"]


def test_handles_missing_href():
    html = """<html><body>
      <a>No href</a>
      <a href="">Empty</a>
      <a href="/real/">Real</a>
    </body></html>"""
    pairs = extract_internal_links(html, "https://example.com/")
    urls = [u for u, _ in pairs]
    assert urls == ["https://example.com/real/"]


def test_collapses_anchor_whitespace():
    html = '<a href="/x">  Summer  \n Camps   </a>'
    pairs = extract_internal_links(html, "https://example.com/")
    assert pairs == [("https://example.com/x", "Summer Camps")]
