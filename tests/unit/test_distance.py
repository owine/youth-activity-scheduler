import pytest

from yas.geo.distance import great_circle_miles


def test_same_point_zero():
    assert great_circle_miles(41.88, -87.63, 41.88, -87.63) == pytest.approx(0.0, abs=0.001)


def test_known_chicago_to_nyc():
    # Chicago (41.88, -87.63) to NYC (40.71, -74.01) ≈ 712 miles
    d = great_circle_miles(41.88, -87.63, 40.71, -74.01)
    assert 700 < d < 725


def test_short_urban_distance():
    # ~1 mile apart at Chicago latitude
    d = great_circle_miles(41.881, -87.630, 41.881, -87.611)
    assert 0.8 < d < 1.2


def test_symmetry():
    d1 = great_circle_miles(41.88, -87.63, 40.71, -74.01)
    d2 = great_circle_miles(40.71, -74.01, 41.88, -87.63)
    assert d1 == pytest.approx(d2)
