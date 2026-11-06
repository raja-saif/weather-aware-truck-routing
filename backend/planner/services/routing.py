"""Route generation: always returns three distinct truck route options.

Primary provider is Valhalla with the ``truck`` costing model (truck speeds,
road restrictions, gross weight). Public routers rarely return three
alternatives on long trips, so when fewer than three come back we generate
candidates by forcing the route through "via" points offset to either side of
the trip's midsection, then keep the fastest candidates that are genuinely
different roads. OSRM (car profile, re-timed with a truck speed cap) is the
fallback when Valhalla is unavailable.
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests
from django.conf import settings
from django.core.cache import cache

from ..api.errors import PlanningError, UpstreamError
from ..domain import geo
from ..domain.geo import Coord
from ..domain.timeline import cap_speed
from .http import DEFAULT_TIMEOUT, session

log = logging.getLogger(__name__)

TARGET_ROUTES = 3
TRUCK_TOP_SPEED_KPH = 105  # ~65 mph, a typical fleet speed governor
TRUCK_MAX_MPH = 65.0
TRACTOR_TARE_LB = 35_000  # empty tractor-trailer; Valhalla needs gross weight
MAX_DETOUR_RATIO = 1.6  # candidate trip time vs fastest route
MAX_OVERLAP = 0.8  # max share of a candidate running on an accepted route
MAX_BACKTRACK = 0.03  # max share of a route that doubles back on itself
ROUTE_CACHE_TTL = 60 * 60

# (fraction along the trip, perpendicular offset as a fraction of trip length)
VIA_CANDIDATES = (
    (0.5, 0.12), (0.5, -0.12), (0.5, 0.25), (0.5, -0.25),
    (0.35, 0.18), (0.35, -0.18), (0.65, 0.18), (0.65, -0.18),
)
VIA_BATCH_SIZE = 4
# No new batch of via candidates starts after this many seconds, so a slow
# public router cannot hold a request for minutes.
VIA_SEARCH_BUDGET_S = 25.0
# After Valhalla fails, skip it for a while and go straight to OSRM.
PROVIDER_DOWN_TTL = 5 * 60
VALHALLA_DOWN_KEY = "provider-down:valhalla"


@dataclass
class RawRoute:
    coords: list[Coord]
    cum_drive_s: list[float]
    provider: str
    via: Coord | None = None
    cum_miles: list[float] = field(default_factory=list)

    def __post_init__(self):
        if not self.cum_miles:
            self.cum_miles = geo.cumulative_miles(self.coords)

    @property
    def miles(self) -> float:
        return self.cum_miles[-1]

    @property
    def drive_s(self) -> float:
        return self.cum_drive_s[-1]


class RoutingUnavailable(Exception):
    """Provider unreachable, erroring or over its limits (as opposed to "no route exists")."""


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------
class ValhallaRouter:
    name = "valhalla-truck"

    def __init__(self, gross_weight_lb: float):
        self.weight_t = round(gross_weight_lb * 0.000453592, 2)

    def route(self, points: list[Coord], alternates: int = 0) -> list[RawRoute]:
        locations = []
        for i, (lat, lon) in enumerate(points):
            loc = {"lat": lat, "lon": lon, "type": "break"}
            if 0 < i < len(points) - 1:
                # Pass through without stopping; snap only to significant roads so the
                # forced detour follows a real highway corridor, not a side street.
                loc.update(type="through", search_filter={"min_road_class": "primary"})
            locations.append(loc)
        body = {
            "locations": locations,
            "costing": "truck",
            "costing_options": {"truck": {"weight": self.weight_t, "top_speed": TRUCK_TOP_SPEED_KPH}},
            "units": "miles",
            "directions_type": "maneuvers",
        }
        if alternates and len(points) == 2:
            body["alternates"] = alternates
        try:
            resp = session().post(settings.VALHALLA_URL, json=body, timeout=DEFAULT_TIMEOUT)
        except requests.RequestException as exc:
            raise RoutingUnavailable(str(exc)) from exc
        if resp.status_code == 400:
            data = _json(resp)
            if data.get("error_code") == 154:
                # The public server caps straight-line request distance (1,500 km);
                # that is a provider limit, not proof that no route exists.
                raise RoutingUnavailable(data.get("error", "distance limit"))
            raise PlanningError(_valhalla_error_message(data), code="no_route")
        if resp.status_code != 200:
            raise RoutingUnavailable(f"Valhalla HTTP {resp.status_code}")
        data = _json(resp)
        trips = [data["trip"]] + [alt["trip"] for alt in data.get("alternates", [])]
        return [self._parse_trip(t) for t in trips]

    def _parse_trip(self, trip: dict) -> RawRoute:
        coords: list[Coord] = []
        drive: list[float] = []
        t0 = 0.0
        for leg in trip["legs"]:
            shape = geo.decode_polyline(leg["shape"], precision=6)
            times = _distribute_maneuver_times(shape, leg["maneuvers"])
            start = 1 if coords else 0  # legs share their joining vertex
            coords.extend(shape[start:])
            drive.extend(t0 + t for t in times[start:])
            t0 = drive[-1]
        return RawRoute(coords=coords, cum_drive_s=drive, provider=self.name)


def _distribute_maneuver_times(shape: list[Coord], maneuvers: list[dict]) -> list[float]:
    """Per-vertex cumulative seconds: each maneuver's time spread over its vertices by distance."""
    times = [0.0] * len(shape)
    for m in maneuvers:
        b, e, total = m["begin_shape_index"], m["end_shape_index"], float(m.get("time", 0.0))
        if e <= b:
            continue
        seg = [geo.haversine_mi(shape[i], shape[i + 1]) for i in range(b, e)]
        length = sum(seg)
        acc = times[b]
        for k, i in enumerate(range(b, e)):
            share = seg[k] / length if length > 0 else 1.0 / (e - b)
            acc += total * share
            times[i + 1] = acc
    # guard against any non-monotonic glitches
    for i in range(1, len(times)):
        times[i] = max(times[i], times[i - 1])
    return times


def _valhalla_error_message(data: dict) -> str:
    code = data.get("error_code")
    if code in (171, 170, 172):
        return "One of the locations is too far from any road a truck can use."
    if code in (442, 443):
        return "No truck route connects these locations."
    return data.get("error", "The routing service could not plan this trip.")


class OsrmRouter:
    name = "osrm-car-capped"

    def route(self, points: list[Coord], alternates: int = 0) -> list[RawRoute]:
        path = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in points)
        params = {
            "overview": "full",
            "geometries": "polyline6",
            "annotations": "duration",
            "steps": "false",
            "alternatives": str(alternates) if alternates and len(points) == 2 else "false",
        }
        try:
            resp = session().get(f"{settings.OSRM_URL}/{path}", params=params, timeout=DEFAULT_TIMEOUT)
        except requests.RequestException as exc:
            raise RoutingUnavailable(str(exc)) from exc
        data = _json(resp)
        if resp.status_code == 400 or data.get("code") in ("NoRoute", "NoSegment"):
            raise PlanningError("No road route connects these locations.", code="no_route")
        if resp.status_code != 200 or data.get("code") != "Ok":
            raise RoutingUnavailable(f"OSRM HTTP {resp.status_code}")
        out = []
        for r in data["routes"]:
            coords = geo.decode_polyline(r["geometry"], precision=6)
            durations = [d for leg in r["legs"] for d in leg["annotation"]["duration"]]
            if len(durations) != len(coords) - 1:
                continue
            cum = [0.0]
            for d in durations:
                cum.append(cum[-1] + d)
            raw = RawRoute(coords=coords, cum_drive_s=cum, provider=self.name)
            raw.cum_drive_s = cap_speed(raw.cum_miles, raw.cum_drive_s, TRUCK_MAX_MPH)
            out.append(raw)
        return out


def _json(resp) -> dict:
    try:
        return resp.json()
    except ValueError:
        return {}


# ---------------------------------------------------------------------------
# Three-route selection
# ---------------------------------------------------------------------------
def backtrack_fraction(coords: list[Coord], cum: list[float]) -> float:
    """Share of 1-mile samples that come back within 0.3 mi of a point visited >5 mi earlier.

    Detects out-and-back spurs created when a via point snaps to a dead end.
    """
    step, dense_step, lag = 1.0, 0.2, 5.0
    samples = geo.resample(coords, cum, step)
    if len(samples) < 10:
        return 0.0
    # Query 1-mile samples against a dense (0.2 mi) index of the road already
    # driven more than ``lag`` miles earlier, so sample phase cannot hide a spur.
    dense = geo.resample(coords, cum, dense_step)
    index = geo.PointIndex([], cell_deg=0.02)
    inserted = hits = 0
    for k, p in enumerate(samples):
        while inserted < len(dense) and inserted * dense_step <= k * step - lag:
            index.add(dense[inserted])
            inserted += 1
        if index.near(p, 0.3):
            hits += 1
    return hits / len(samples)


def _distinct(candidate: RawRoute, accepted: list[RawRoute]) -> bool:
    for r in accepted:
        if max(geo.overlap_fraction(candidate.coords, r.coords), geo.overlap_fraction(r.coords, candidate.coords)) > MAX_OVERLAP:
            return False
    return True


def via_points(origin: Coord, dest: Coord, base: RawRoute) -> list[Coord]:
    """Candidate via points offset perpendicular to the origin->destination axis."""
    straight = geo.haversine_mi(origin, dest)
    mean_lat = math.radians((origin[0] + dest[0]) / 2)
    # local planar frame in miles
    dx = (dest[1] - origin[1]) * 69.172 * math.cos(mean_lat)
    dy = (dest[0] - origin[0]) * 69.172
    norm = math.hypot(dx, dy) or 1.0
    px, py = -dy / norm, dx / norm  # unit perpendicular (left of travel)
    out = []
    for frac, offset in VIA_CANDIDATES:
        anchor = geo.point_at(base.coords, base.cum_miles, base.miles * frac)
        off_mi = offset * straight
        lat = anchor[0] + (py * off_mi) / 69.172
        lon = anchor[1] + (px * off_mi) / (69.172 * math.cos(math.radians(anchor[0])))
        out.append((round(lat, 5), round(lon, 5)))
    return out


def _select(origin: Coord, dest: Coord, router) -> tuple[list[RawRoute], list[str]]:
    notes: list[str] = []
    accepted: list[RawRoute] = []
    for r in router.route([origin, dest], alternates=TARGET_ROUTES - 1):
        if _distinct(r, accepted):
            accepted.append(r)
    fastest = min(r.drive_s for r in accepted)
    if len(accepted) >= TARGET_ROUTES:
        return accepted[:TARGET_ROUTES], notes

    vias = via_points(origin, dest, accepted[0])
    deadline = time.monotonic() + VIA_SEARCH_BUDGET_S
    for start in range(0, len(vias), VIA_BATCH_SIZE):
        if time.monotonic() > deadline:
            log.warning("%s: via search stopped after %.0f s budget", router.name, VIA_SEARCH_BUDGET_S)
            break
        batch = vias[start : start + VIA_BATCH_SIZE]
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            results = list(pool.map(lambda v: _try_via(router, origin, v, dest), batch))
        candidates = sorted((r for r in results if r is not None), key=lambda r: r.drive_s)
        for cand in candidates:
            if cand.drive_s > fastest * MAX_DETOUR_RATIO:
                continue
            if backtrack_fraction(cand.coords, cand.cum_miles) > MAX_BACKTRACK:
                continue
            if _distinct(cand, accepted):
                accepted.append(cand)
            if len(accepted) >= TARGET_ROUTES:
                return accepted, notes
    notes.append(
        f"Only {len(accepted)} distinct practical route(s) exist between these points; "
        "showing all that were found."
    )
    return accepted, notes


def _try_via(router, origin: Coord, via: Coord, dest: Coord) -> RawRoute | None:
    try:
        routes = router.route([origin, via, dest])
    except (PlanningError, RoutingUnavailable) as exc:
        log.info("via candidate %s rejected: %s", via, exc)
        return None
    if not routes:
        return None
    routes[0].via = via
    return routes[0]


def get_routes(origin: Coord, dest: Coord, load_lb: float) -> tuple[list[RawRoute], list[str]]:
    """Three distinct route options (fewer only if the road network has no more), fastest first."""
    if geo.haversine_mi(origin, dest) < 0.5:
        raise PlanningError("Origin and destination are the same place.", code="same_location")
    gross = load_lb + TRACTOR_TARE_LB
    key = "routes:" + hashlib.sha1(
        f"{origin[0]:.4f},{origin[1]:.4f}|{dest[0]:.4f},{dest[1]:.4f}|{round(gross, -3)}".encode()
    ).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return cached

    # All three options must come from one provider so travel times are comparable.
    best: tuple[list[RawRoute], list[str]] | None = None
    fallback_reason = "the truck routing service could not return three options"
    if cache.get(VALHALLA_DOWN_KEY):
        fallback_reason = "the truck routing service is unavailable"
    else:
        try:
            best = _select(origin, dest, ValhallaRouter(gross))
        except RoutingUnavailable as exc:
            log.warning("Valhalla unavailable (%s); falling back to OSRM", exc)
            if "distance limit" in str(exc):
                fallback_reason = "the free truck routing service is limited to about 930 miles"
            else:
                fallback_reason = "the truck routing service is unavailable"
                cache.set(VALHALLA_DOWN_KEY, True, PROVIDER_DOWN_TTL)
    if best is None or len(best[0]) < TARGET_ROUTES:
        try:
            routes, notes = _select(origin, dest, OsrmRouter())
            if best is None or len(routes) > len(best[0]):
                notes.insert(
                    0,
                    f"Routes use general road routing re-timed with a 65 mph truck speed cap, "
                    f"because {fallback_reason}.",
                )
                best = (routes, notes)
        except RoutingUnavailable as exc:
            if best is None:
                raise UpstreamError(
                    "Routing service is temporarily unavailable. Please try again shortly.",
                    code="routing_unavailable",
                ) from exc

    routes, notes = best
    routes.sort(key=lambda r: r.drive_s)
    result = (routes, notes)
    cache.set(key, result, ROUTE_CACHE_TTL)
    return result
