import pytest

from yas.alerts.channels.base import (
    NotifierCapability,
    NotifierMessage,
    SendResult,
)
from yas.db.models._types import AlertType


def test_send_result_shape():
    r = SendResult(ok=True, transient_failure=False, detail="sent")
    assert r.ok is True


def test_notifier_message_urgent_default_false():
    m = NotifierMessage(
        kid_id=1,
        alert_type=AlertType.new_match,
        subject="Sub",
        body_plain="body",
    )
    assert m.urgent is False
    assert m.body_html is None


@pytest.mark.asyncio
async def test_fake_notifier_records_sends():
    from tests.fakes.notifier import FakeNotifier

    f = FakeNotifier(name="fake", capabilities={NotifierCapability.email})
    msg = NotifierMessage(
        kid_id=1,
        alert_type=AlertType.new_match,
        subject="s",
        body_plain="b",
    )
    result = await f.send(msg)
    assert f.name == "fake"
    assert NotifierCapability.email in f.capabilities
    assert f.records == [msg]
    assert f.call_count == 1
    assert result.ok is True


def test_notifier_capability_push_emergency_distinct():
    assert NotifierCapability.push_emergency != NotifierCapability.push
