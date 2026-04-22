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
