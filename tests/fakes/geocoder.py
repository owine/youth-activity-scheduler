"""FakeGeocoder — scripted responses for integration tests."""

from __future__ import annotations

from dataclasses import dataclass, field

from yas.geo.client import GeocodeResult


@dataclass
class FakeGeocoder:
    fixtures: dict[str, GeocodeResult] = field(default_factory=dict)
    misses: set[str] = field(default_factory=set)
    errors: set[str] = field(default_factory=set)
    call_count: int = 0

    async def geocode(self, address: str) -> GeocodeResult | None:
        self.call_count += 1
        key = address.lower().strip()
        if key in self.errors:
            raise RuntimeError(f"simulated geocode error for {address!r}")
        if key in self.misses:
            return None
        return self.fixtures.get(key)
