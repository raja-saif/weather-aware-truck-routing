"""Heatmap grid along the trip corridor (pure functions, no I/O).

The grid is square in Web Mercator: columns are evenly spaced in longitude and
rows evenly spaced in Mercator y with the same step. Each node is therefore one
square pixel of an image the map can stretch over its four corners with no
distortion, so the heatmap lines up exactly with the route lines at every zoom.

Only nodes within ``radius_mi`` of a route are "active" (fetched and drawn);
the spacing grows until the active count fits the weather-API budget.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from . import geo
from .geo import Coord

MILES_PER_DEG_LAT = 69.172


def merc_y(lat: float) -> float:
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def inv_merc_y(y: float) -> float:
    return math.degrees(2 * math.atan(math.exp(y)) - math.pi / 2)


@dataclass(frozen=True)
class CorridorGrid:
    lats: list[float]  # north -> south (image row order)
    lons: list[float]  # west -> east
    step_deg: float
    cells: list[tuple[int, int]]  # active (row, col)
    corners: list[list[float]]  # [lon, lat] of image TL, TR, BR, BL

    def coord(self, cell: tuple[int, int]) -> Coord:
        return (self.lats[cell[0]], self.lons[cell[1]])


def _build(routes: Sequence[Sequence[Coord]], step_deg: float, radius_mi: float, index: geo.PointIndex) -> CorridorGrid:
    south, west, north, east = geo.bbox(p for r in routes for p in r)
    pad_lat = radius_mi / MILES_PER_DEG_LAT
    mean_lat = (south + north) / 2
    pad_lon = radius_mi / (MILES_PER_DEG_LAT * max(math.cos(math.radians(mean_lat)), 0.2))
    west, east = west - pad_lon, east + pad_lon
    south, north = max(south - pad_lat, -84), min(north + pad_lat, 84)

    step_rad = math.radians(step_deg)
    ncols = max(2, math.ceil((east - west) / step_deg) + 1)
    y_top, y_bottom = merc_y(north), merc_y(south)
    nrows = max(2, math.ceil((y_top - y_bottom) / step_rad) + 1)
    lons = [west + c * step_deg for c in range(ncols)]
    ys = [y_top - r * step_rad for r in range(nrows)]
    lats = [inv_merc_y(y) for y in ys]

    cells = [
        (r, c)
        for r, lat in enumerate(lats)
        for c, lon in enumerate(lons)
        if index.near((lat, lon), radius_mi)
    ]
    half = step_rad / 2
    n_edge, s_edge = inv_merc_y(ys[0] + half), inv_merc_y(ys[-1] - half)
    w_edge, e_edge = lons[0] - step_deg / 2, lons[-1] + step_deg / 2
    corners = [[w_edge, n_edge], [e_edge, n_edge], [e_edge, s_edge], [w_edge, s_edge]]
    return CorridorGrid(lats=lats, lons=lons, step_deg=step_deg, cells=cells, corners=corners)


def corridor_grid(
    routes: Sequence[Sequence[Coord]], *, radius_mi: float = 40.0, max_cells: int = 300, min_step_deg: float = 0.1
) -> CorridorGrid:
    """Finest grid (step >= ``min_step_deg``) whose active cells fit ``max_cells``."""
    samples = []
    total_mi = 0.0
    for r in routes:
        cum = geo.cumulative_miles(r)
        total_mi += cum[-1]
        samples.extend(geo.resample(r, cum, 2.0) if cum[-1] > 0 else r)
    # bucket size must cover the search radius in degrees (longitude degrees shrink with latitude)
    max_abs_lat = max(abs(p[0]) for p in samples)
    cell_deg = radius_mi / (MILES_PER_DEG_LAT * max(math.cos(math.radians(max_abs_lat)), 0.2)) + 0.01
    index = geo.PointIndex(samples, cell_deg=cell_deg)

    # Start near the answer: corridor area / budget gives the cell size in miles.
    # Routes overlap, so the area is overestimated; start a bit finer than that.
    mean_lat = sum(p[0] for p in samples) / len(samples)
    deg_mi = MILES_PER_DEG_LAT * max(math.cos(math.radians(mean_lat)), 0.2)
    estimate = 0.7 * math.sqrt(total_mi * 2 * radius_mi / max_cells) / deg_mi
    step = round(max(min_step_deg, math.floor(estimate / 0.05) * 0.05), 2)
    while True:
        grid = _build(routes, step, radius_mi, index)
        if len(grid.cells) <= max_cells:
            return grid
        # coarsen roughly in proportion to the overshoot; always grow by >= 0.05 deg
        target = step * math.sqrt(len(grid.cells) / max_cells)
        step = round(max(step + 0.05, round(target / 0.05) * 0.05), 2)
