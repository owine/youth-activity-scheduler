from yas.llm.prompt import build_extraction_prompt


def test_prompt_contains_site_and_url_and_html():
    system, user = build_extraction_prompt(
        html="<p>Spring Soccer, ages 6-8</p>",
        url="https://example.com/spring",
        site_name="Example Sports",
    )
    assert "program_type" in system
    assert "null rather than guessing" in system.lower()
    assert "https://example.com/spring" in user
    assert "Example Sports" in user
    assert "Spring Soccer, ages 6-8" in user


def test_prompt_mentions_fixed_program_vocabulary():
    system, _ = build_extraction_prompt(html="", url="", site_name="x")
    for tag in (
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
    ):
        assert tag in system


def test_prompt_asks_for_structured_output_tool_use():
    system, _ = build_extraction_prompt(html="", url="", site_name="x")
    # The model is called with a tool; the prompt should direct it to use the tool.
    assert "report_offerings" in system


def test_prompt_gives_crawl_date_so_a_yearless_date_can_be_resolved():
    """Pages like Lil Sluggers write "October 26th - December 19th" with no year.
    Without the crawl date the model can only guess the year or return null."""
    from datetime import date

    system, user = build_extraction_prompt(
        html="<p>Fall Session 2: October 26th - December 19th</p>",
        url="u",
        site_name="s",
        today=date(2026, 11, 2),
    )
    assert "Crawled on: 2026-11-02" in user
    assert "omits the year" in system
    assert "no more than two months before the crawl date" in system


def test_prompt_defaults_crawl_date_to_today_utc():
    from datetime import UTC, datetime

    before = datetime.now(UTC).date()
    _, user = build_extraction_prompt(html="", url="u", site_name="s")
    after = datetime.now(UTC).date()  # the call can straddle UTC midnight
    assert any(f"Crawled on: {d.isoformat()}" in user for d in (before, after))
