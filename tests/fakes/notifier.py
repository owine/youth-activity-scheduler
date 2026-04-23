"""FakeNotifier — records send() calls; configurable transient/non-transient failures."""

from __future__ import annotations

from dataclasses import dataclass, field

from yas.alerts.channels.base import (
    NotifierCapability,
    NotifierMessage,
    SendResult,
)


@dataclass
class FakeNotifier:
    name: str = "fake"
    capabilities: set[NotifierCapability] = field(
        default_factory=lambda: {NotifierCapability.email}
    )
    records: list[NotifierMessage] = field(default_factory=list)
    # Queue of pre-baked results; if empty, every send returns ok=True.
    result_queue: list[SendResult] = field(default_factory=list)
    call_count: int = 0

    async def send(self, msg: NotifierMessage) -> SendResult:
        self.call_count += 1
        self.records.append(msg)
        if self.result_queue:
            return self.result_queue.pop(0)
        return SendResult(ok=True, transient_failure=False, detail="fake ok")

    async def aclose(self) -> None:
        pass

    def queue_transient_failure(self, detail: str = "boom") -> None:
        self.result_queue.append(SendResult(ok=False, transient_failure=True, detail=detail))

    def queue_permanent_failure(self, detail: str = "no auth") -> None:
        self.result_queue.append(SendResult(ok=False, transient_failure=False, detail=detail))
