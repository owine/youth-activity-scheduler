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
    for tag in ("soccer", "swim", "martial_arts", "art", "music", "stem", "dance",
                "gym", "multisport", "outdoor", "academic", "camp_general"):
        assert tag in system


def test_prompt_asks_for_structured_output_tool_use():
    system, _ = build_extraction_prompt(html="", url="", site_name="x")
    # The model is called with a tool; the prompt should direct it to use the tool.
    assert "report_offerings" in system
