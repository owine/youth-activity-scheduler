import json
import logging

import structlog

from yas.logging import configure_logging, get_logger


def test_configure_logging_emits_json(capsys):
    configure_logging(level="INFO")
    log = get_logger("test")
    log.info("hello", kid_id=42)
    captured = capsys.readouterr()
    # structlog default ProcessorFormatter routes through stdlib logging → stderr
    lines = [line for line in captured.err.splitlines() if line.strip()]
    assert lines, "no log output captured"
    payload = json.loads(lines[-1])
    assert payload["event"] == "hello"
    assert payload["kid_id"] == 42
    assert payload["level"] == "info"


def test_log_level_respected(capsys):
    configure_logging(level="WARNING")
    log = get_logger("test")
    log.info("invisible")
    log.warning("visible")
    captured = capsys.readouterr()
    assert "invisible" not in captured.err
    assert "visible" in captured.err


def test_get_logger_returns_structlog():
    configure_logging(level="INFO")
    log = get_logger("x")
    # BoundLogger has .bind()
    assert hasattr(log, "bind")


def teardown_function():
    # Reset stdlib logging handlers between tests.
    for name in list(logging.root.manager.loggerDict):
        logging.getLogger(name).handlers.clear()
    logging.root.handlers.clear()
    # Also reset structlog: configure_logging() installs a filtering
    # wrapper_class baked at a specific level (e.g. WARNING in
    # test_log_level_respected). The wrapper filters BEFORE any processor
    # runs, so leaving it in place silently drops DEBUG events in any later
    # test in the suite -- including unrelated integration tests that assert
    # on debug-level log events.
    structlog.reset_defaults()
