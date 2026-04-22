"""Pure haversine great-circle distance in miles."""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

_EARTH_MILES = 3958.7613


def great_circle_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in miles between two lat/lon points."""
    lat1_r, lat2_r = radians(lat1), radians(lat2)
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(lat1_r) * cos(lat2_r) * sin(dlon / 2) ** 2
    return 2 * _EARTH_MILES * asin(sqrt(a))
