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


def test_main_initialises_error_reporting_before_migrating(monkeypatch):
    """Every mode goes through main(), so init there covers api, worker and all.

    It must precede migrations: a failed upgrade is exactly the startup crash
    worth reporting, and the FastAPI integration has to be set up before
    create_app builds the app.
    """
    import yas.__main__ as entry
    import yas.db.migrations as migrations

    calls: list[str] = []
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(entry, "init_sentry", lambda _settings: calls.append("init_sentry"))
    monkeypatch.setattr(migrations, "upgrade_to_head", lambda _url: calls.append("migrate"))

    assert entry.main(["migrate"]) == 0
    assert calls == ["init_sentry", "migrate"]
