import os
import subprocess
import sys


def test_main_prints_usage_when_no_mode():
    r = subprocess.run(
        [sys.executable, "-m", "yas"],
        capture_output=True,
        text=True,
        env={**os.environ, "YAS_ANTHROPIC_API_KEY": "sk-test"},
    )
    assert r.returncode != 0
    assert "usage" in (r.stderr + r.stdout).lower()


def test_main_accepts_known_modes():
    # We don't actually run api/worker here (they block). Just check arg parsing
    # by calling --help which short-circuits before booting anything.
    r = subprocess.run(
        [sys.executable, "-m", "yas", "--help"],
        capture_output=True,
        text=True,
        env={**os.environ, "YAS_ANTHROPIC_API_KEY": "sk-test"},
    )
    assert r.returncode == 0
    combined = r.stdout + r.stderr
    for mode in ("api", "worker", "all"):
        assert mode in combined
