import math

import pytest

from planner.domain import geo


def test_haversine_known_distance():
    # Chicago -> Denver great-circle is ~920 miles.
    assert geo.haversine_mi((41.8781, -87.6298), (39.7392, -104.9903)) == pytest.approx(920, abs=5)


def test_decode_polyline_precision5_reference():
    # Reference example from Google's polyline documentation.
    pts = geo.decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@", precision=5)
    assert pts == [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]


def test_checkpoint_distances_include_origin_and_destination():
    assert geo.checkpoint_distances(52, 25) == [0, 25, 50, 52]
    assert geo.checkpoint_distances(50, 25) == [0, 25, 50]
    # a mark within half a mile of the destination is dropped; gaps never exceed the interval
    assert geo.checkpoint_distances(50.3, 25) == [0, 25, 50.3]
    assert geo.checkpoint_distances(8, 10) == [0, 8]
    marks = geo.checkpoint_distances(1013.7, 10)
    assert max(b - a for a, b in zip(marks, marks[1:])) <= 10


def test_coverage_sums_to_route_length():
    marks = geo.checkpoint_distances(137.4, 10)
    cov = geo.coverage_miles(marks)
    assert sum(cov) == pytest.approx(137.4)
    assert cov[0] == pytest.approx(5)  # origin covers half of the first interval
    assert cov[1] == pytest.approx(10)


def test_point_at_interpolates_linearly():
    coords = [(0.0, 0.0), (0.0, 1.0), (0.0, 2.0)]
    cum = geo.cumulative_miles(coords)
    lat, lon = geo.point_at(coords, cum, cum[-1] * 0.75)
    assert lat == pytest.approx(0)
    assert lon == pytest.approx(1.5)
    assert geo.point_at(coords, cum, -5) == (0.0, 0.0)
    assert geo.point_at(coords, cum, 1e9) == (0.0, 2.0)


def test_simplify_drops_collinear_points_keeps_corners():
    coords = [(0.0, x / 10) for x in range(11)] + [(x / 10, 1.0) for x in range(1, 11)]
    kept = geo.simplify_indices(coords, tolerance_mi=0.1)
    assert kept == [0, 10, 20]


def test_overlap_identical_and_disjoint_routes():
    a = [(40.0, -100 + x / 10) for x in range(51)]
    b = [(41.0, -100 + x / 10) for x in range(51)]  # ~69 miles north
    assert geo.overlap_fraction(a, a) == pytest.approx(1.0)
    assert geo.overlap_fraction(a, b) == 0.0


def test_overlap_partial():
    shared = [(40.0, -100 + x / 10) for x in range(21)]  # first ~106 mi shared
    a = shared + [(40.0, -98 + x / 10) for x in range(1, 21)]
    b = shared + [(40.0 + x / 10, -98.0) for x in range(1, 21)]
    frac = geo.overlap_fraction(a, b)
    assert 0.45 < frac < 0.6


def test_bbox():
    assert geo.bbox([(1, 2), (3, -4)]) == (1, -4, 3, 2)
    assert math.isfinite(geo.EARTH_RADIUS_MI)
