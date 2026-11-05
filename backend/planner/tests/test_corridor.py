import math

import pytest

from planner.domain import geo
from planner.domain.corridor import corridor_grid, inv_merc_y, merc_y

from .helpers import straight_line


def test_mercator_roundtrip():
    for lat in (-60, -10, 0, 33.3, 47.6, 70):
        assert inv_merc_y(merc_y(lat)) == pytest.approx(lat)


def test_grid_is_square_in_mercator_and_ordered():
    route = straight_line((35.0, -110.0), (45.0, -90.0), 200)
    g = corridor_grid([route], max_cells=400)
    step_rad = math.radians(g.step_deg)
    ys = [merc_y(lat) for lat in g.lats]
    assert all(a > b for a, b in zip(ys, ys[1:]))  # north -> south
    assert all(b - a == pytest.approx(g.step_deg) for a, b in zip(g.lons, g.lons[1:]))
    assert all(a - b == pytest.approx(step_rad) for a, b in zip(ys, ys[1:]))


def test_active_cells_respect_budget_and_follow_the_route():
    route = straight_line((35.0, -110.0), (45.0, -90.0), 200)
    g = corridor_grid([route], radius_mi=40, max_cells=300)
    assert 0 < len(g.cells) <= 300
    index = geo.PointIndex(geo.resample(route, geo.cumulative_miles(route), 2.0), cell_deg=1.0)
    for cell in g.cells:
        assert index.near(g.coord(cell), 40.0)
    # the corners of the bbox are far from a diagonal route: inactive
    assert (0, len(g.lons) - 1) not in g.cells


def test_short_route_keeps_minimum_resolution():
    g = corridor_grid([straight_line((40.0, -100.0), (40.0, -99.0), 20)], max_cells=1000)
    assert g.step_deg == pytest.approx(0.1)
    coarse = corridor_grid([straight_line((40.0, -100.0), (40.0, -99.0), 20)], max_cells=100)
    assert coarse.step_deg > 0.1 and len(coarse.cells) <= 100


def test_corners_enclose_all_nodes():
    g = corridor_grid([straight_line((30.0, -100.0), (34.0, -96.0), 50)], max_cells=200)
    (w, n), (e, _), (_, s), _ = g.corners
    assert w < min(g.lons) and e > max(g.lons)
    assert n > max(g.lats) and s < min(g.lats)
