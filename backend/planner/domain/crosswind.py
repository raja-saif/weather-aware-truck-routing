"""Crosswind relative to the truck's heading (extra feature, informational only).

Wind blowing across a high-sided trailer is what tips trucks, so the UI shows
the crosswind component next to each checkpoint. It does NOT feed the risk
level or the ranking: those follow the spec's table, which uses wind speed.

Meteorological wind direction is where the wind blows FROM, so with a relative
angle ``a = wind_from - heading``:

* headwind component = speed * cos(a)  (positive: blowing in the driver's face)
* crosswind component = speed * |sin(a)|
"""

from __future__ import annotations

import math
from typing import Sequence

from . import geo
from .geo import Coord

STRONG_GUST_CROSSWIND_MPH = 30.0  # typical high-profile vehicle advisory level


def bearing_deg(a: Coord, b: Coord) -> float:
    """Initial compass bearing from ``a`` to ``b`` (0 = north, 90 = east)."""
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlon = math.radians(b[1] - a[1])
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return math.degrees(math.atan2(x, y)) % 360


def heading_at(coords: Sequence[Coord], cum: Sequence[float], miles: float, span_mi: float = 0.5) -> float:
    """Direction of travel around ``miles``, measured over a short span to smooth out kinks."""
    lo = max(miles - span_mi, 0.0)
    hi = min(miles + span_mi, cum[-1])
    if hi - lo < 1e-6:
        lo, hi = 0.0, cum[-1]
    return bearing_deg(geo.point_at(coords, cum, lo), geo.point_at(coords, cum, hi))


def relative_wind(
    wind_mph: float, gust_mph: float | None, wind_from_deg: float, heading: float
) -> dict:
    angle = math.radians((wind_from_deg - heading + 180) % 360 - 180)
    cross_factor = abs(math.sin(angle))
    head = wind_mph * math.cos(angle)
    deg = abs(math.degrees(angle))
    relation = "headwind" if deg <= 45 else "tailwind" if deg >= 135 else "crosswind"
    gust_cross = (gust_mph or wind_mph) * cross_factor
    return {
        "heading_deg": round(heading),
        "crosswind_mph": round(wind_mph * cross_factor, 1),
        "gust_crosswind_mph": round(gust_cross, 1),
        "headwind_mph": round(head, 1),
        "relation": relation,
        "strong": gust_cross >= STRONG_GUST_CROSSWIND_MPH,
    }


def compass(deg: float) -> str:
    points = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
    return points[int((deg % 360 + 22.5) // 45) % 8]
