import json
import logging
import traceback

import structlog

from yas.logging import configure_logging, get_logger, traceback_tail


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


def _chained_error(context_len: int) -> RuntimeError:
    """A RuntimeError raised while handling a ValueError with a long message.

    The chained context is printed first, so its length pushes the final line —
    the one naming the error being reported — as far from the start as we like.
    """
    try:
        try:
            raise ValueError("x" * context_len)
        except ValueError as err:
            raise RuntimeError("THE_ERROR") from err
    except RuntimeError as exc:
        return exc
    raise AssertionError("unreachable")


def test_traceback_tail_returns_a_short_traceback_whole():
    exc = _chained_error(context_len=10)
    assert traceback_tail(exc) == "".join(traceback.format_exception(exc))


def test_traceback_tail_keeps_the_end_of_a_long_traceback():
    exc = _chained_error(context_len=5000)
    tb = traceback_tail(exc)
    assert len(tb) <= 2000
    assert tb.rstrip().endswith("RuntimeError: THE_ERROR")
    # Marked, so a reader knows the opening frames are missing, not corrupt.
    assert tb.startswith("[truncated")


def _raise_with_huge_message() -> None:
    raise RuntimeError("HUGE " + "p" * 5000)


def test_traceback_tail_keeps_the_raising_frame_when_the_message_alone_is_too_long():
    """A message over the limit must not crowd out the frame that raised it.

    SQLAlchemy errors embed the statement's parameters in str(exc), and the
    backoff write's parameters carry the crawl error's text, so this happens.
    The full message is logged separately as `error`.
    """
    try:
        _raise_with_huge_message()
    except RuntimeError as caught:
        exc = caught
    tb = traceback_tail(exc)
    assert len(tb) <= 2000
    assert "in _raise_with_huge_message" in tb
    assert "RuntimeError: HUGE ppp" in tb


def test_traceback_tail_keeps_a_true_suffix_of_an_exception_group():
    # A group prints its members *after* its own lines, so splitting off the
    # final lines would splice the text; it falls back to a plain tail.
    try:
        raise ExceptionGroup("GROUP", [ValueError("m" * 3000), RuntimeError("LAST_MEMBER")])
    except ExceptionGroup as caught:
        exc = caught
    tb = traceback_tail(exc)
    assert len(tb) <= 2000
    assert tb.startswith("[truncated]\n")
    assert "".join(traceback.format_exception(exc)).endswith(tb.removeprefix("[truncated]\n"))


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
