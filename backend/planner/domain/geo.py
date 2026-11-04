"""Geometry helpers for route polylines (pure functions, no I/O).

Coordinates are ``(lat, lon)`` tuples in degrees; distances are statute miles.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections import defaultdict
from typing import Iterable, Sequence

Coord = tuple[float, float]

EARTH_RADIUS_MI = 3958.7613
METERS_PER_MILE = 1609.344


def haversine_mi(a: Coord, b: Coord) -> float:
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(min(1.0, math.sqrt(h)))


def decode_polyline(encoded: str, precision: int = 6) -> list[Coord]:
    """Decode a Google-style encoded polyline (Valhalla uses precision 6)."""
    coords: list[Coord] = []
    factor = 10**precision
    index = lat = lon = 0
    length = len(encoded)
    while index < length:
        deltas = []
        for _ in range(2):
            result = shift = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lon += deltas[1]
        coords.append((lat / factor, lon / factor))
    return coords


def cumulative_miles(coords: Sequence[Coord]) -> list[float]:
    cum = [0.0]
    for i in range(1, len(coords)):
        cum.append(cum[-1] + haversine_mi(coords[i - 1], coords[i]))
    return cum


def locate(cum: Sequence[float], distance: float) -> tuple[int, float]:
    """Segment index ``i`` and fraction ``f`` such that the point lies f of the way from vertex i to i+1."""
    if distance <= 0 or len(cum) < 2:
        return 0, 0.0
    if distance >= cum[-1]:
        return len(cum) - 2, 1.0
    i = bisect_right(cum, distance) - 1
    seg = cum[i + 1] - cum[i]
    return i, (distance - cum[i]) / seg if seg > 0 else 0.0


def interpolate(values: Sequence[float], i: int, f: float) -> float:
    return values[i] + (values[i + 1] - values[i]) * f if f else values[i]


def point_at(coords: Sequence[Coord], cum: Sequence[float], distance: float) -> Coord:
    i, f = locate(cum, distance)
    if len(coords) == 1:
        return coords[0]
    (la1, lo1), (la2, lo2) = coords[i], coords[i + 1]
    return (la1 + (la2 - la1) * f, lo1 + (lo2 - lo1) * f)


def checkpoint_distances(total_miles: float, interval_miles: float) -> list[float]:
    """Distances of checkpoints: the origin, every ``interval`` miles, and the destination.

    Gaps never exceed ``interval_miles``. The destination is always included;
    an interval mark within half a mile of it is dropped so two checkpoints
    never sit on top of each other.
    """
    if interval_miles <= 0:
        raise ValueError("interval must be positive")
    marks = [0.0]
    d = interval_miles
    while d < total_miles - 0.5:
        marks.append(d)
        d += interval_miles
    if total_miles > 0:
        marks.append(total_miles)
    return marks


def coverage_miles(marks: Sequence[float]) -> list[float]:
    """Miles of road each checkpoint represents (nearest-checkpoint attribution).

    Checkpoint k covers the road from the midpoint with its predecessor to the
    midpoint with its successor, so the coverages sum to the route length.
    """
    n = len(marks)
    if n == 1:
        return [0.0]
    out = []
    for k in range(n):
        lo = marks[0] if k == 0 else (marks[k - 1] + marks[k]) / 2
        hi = marks[-1] if k == n - 1 else (marks[k] + marks[k + 1]) / 2
        out.append(hi - lo)
    return out


def _to_local_xy(coords: Sequence[Coord]) -> list[tuple[float, float]]:
    """Equirectangular projection in miles around the mean latitude (fine for simplification)."""
    mean_lat = math.radians(sum(c[0] for c in coords) / len(coords))
    kx = EARTH_RADIUS_MI * math.cos(mean_lat) * math.pi / 180
    ky = EARTH_RADIUS_MI * math.pi / 180
    return [(c[1] * kx, c[0] * ky) for c in coords]


def simplify_indices(coords: Sequence[Coord], tolerance_mi: float) -> list[int]:
    """Douglas-Peucker; returns indices of kept vertices (first and last always kept)."""
    n = len(coords)
    if n <= 2:
        return list(range(n))
    xy = _to_local_xy(coords)
    keep = bytearray(n)
    keep[0] = keep[-1] = 1
    stack = [(0, n - 1)]
    tol2 = tolerance_mi * tolerance_mi
    while stack:
        start, end = stack.pop()
        (x1, y1), (x2, y2) = xy[start], xy[end]
        dx, dy = x2 - x1, y2 - y1
        seg2 = dx * dx + dy * dy
        best, best_d2 = -1, tol2
        for i in range(start + 1, end):
            px, py = xy[i]
            if seg2 == 0:
                d2 = (px - x1) ** 2 + (py - y1) ** 2
            else:
                t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / seg2))
                d2 = (px - x1 - t * dx) ** 2 + (py - y1 - t * dy) ** 2
            if d2 > best_d2:
                best, best_d2 = i, d2
        if best > 0:
            keep[best] = 1
            stack.append((start, best))
            stack.append((best, end))
    return [i for i in range(n) if keep[i]]


def resample(coords: Sequence[Coord], cum: Sequence[float], step_mi: float) -> list[Coord]:
    """Points every ``step_mi`` along the line (plus the end point)."""
    total = cum[-1]
    pts = [point_at(coords, cum, d) for d in _frange(0.0, total, step_mi)]
    pts.append(coords[-1])
    return pts


def _frange(start: float, stop: float, step: float) -> Iterable[float]:
    k = 0
    while start + k * step < stop:
        yield start + k * step
        k += 1


class PointIndex:
    """Grid-bucket spatial index for "is any point within r miles?" queries.

    ``cell_deg`` must be at least the query radius in degrees (0.02 deg ~ 1.4 mi).
    """

    def __init__(self, points: Sequence[Coord], cell_deg: float):
        self.cell = cell_deg
        self.buckets: dict[tuple[int, int], list[Coord]] = defaultdict(list)
        for p in points:
            self.add(p)

    def add(self, p: Coord) -> None:
        self.buckets[self._key(p)].append(p)

    def _key(self, p: Coord) -> tuple[int, int]:
        return int(math.floor(p[0] / self.cell)), int(math.floor(p[1] / self.cell))

    def near(self, p: Coord, radius_mi: float) -> bool:
        ki, kj = self._key(p)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for q in self.buckets.get((ki + di, kj + dj), ()):
                    if haversine_mi(p, q) <= radius_mi:
                        return True
        return False


def overlap_fraction(a: Sequence[Coord], b: Sequence[Coord], *, tolerance_mi: float = 0.75, step_mi: float = 1.0) -> float:
    """Share of route ``a``'s length that runs within ``tolerance_mi`` of route ``b``."""
    cum_a, cum_b = cumulative_miles(a), cumulative_miles(b)
    if cum_a[-1] == 0:
        return 1.0
    samples_a = resample(a, cum_a, step_mi)
    # Densify b so consecutive points are closer than the tolerance.
    index = PointIndex(resample(b, cum_b, tolerance_mi / 2), cell_deg=0.05)
    hits = sum(1 for p in samples_a if index.near(p, tolerance_mi))
    return hits / len(samples_a)


def bbox(points: Iterable[Coord]) -> tuple[float, float, float, float]:
    """(south, west, north, east)."""
    lats, lons = zip(*points)
    return min(lats), min(lons), max(lats), max(lons)
