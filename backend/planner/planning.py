"""Trip planning use case: routes -> checkpoints -> weather at ETA -> risk -> recommendation."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from django.conf import settings

from .domain import corridor, departure, geo
from .domain.crosswind import heading_at, relative_wind
from .domain.geo import Coord
from .domain.recommend import RouteScore, recommend
from .domain.risk import RiskAssessment, RiskLevel, WeatherSample, assess
from .domain.scenario import Storm
from .domain.timeline import HosPolicy, Timeline
from .services import routing, weather

log = logging.getLogger(__name__)

ROUTE_IDS = "ABC"
GEOMETRY_TOLERANCE_MI = 0.03  # ~50 m: visually lossless at highway zooms
DEPARTURE_SEARCH_H = max(departure.DEFAULT_SHIFTS_H)


@dataclass(frozen=True)
class Place:
    lat: float
    lon: float
    label: str

    @property
    def coord(self) -> Coord:
        return (self.lat, self.lon)


@dataclass(frozen=True)
class TripRequest:
    origin: Place
    destination: Place
    departure: datetime
    load_lb: float
    interval_mi: int
    hos: bool
    scenario: str = "live"  # "live" or "storm" (synthetic demo storm over the real forecast)
    storm: Storm | None = None  # reuse a previous plan's demo storm instead of placing a new one


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(round(ts), tz=timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class _Prepared:
    raw: routing.RawRoute
    timeline: Timeline
    marks: list[float]
    coverage: list[float]
    points: list[Coord]
    offsets: list[float]
    headings: list[float]


def _prepare(raw: routing.RawRoute, interval: float, hos: HosPolicy) -> _Prepared:
    timeline = Timeline(raw.cum_miles, raw.cum_drive_s, hos)
    marks = geo.checkpoint_distances(raw.miles, interval)
    return _Prepared(
        raw=raw,
        timeline=timeline,
        marks=marks,
        coverage=geo.coverage_miles(marks),
        points=[geo.point_at(raw.coords, raw.cum_miles, d) for d in marks],
        offsets=[timeline.offset_at(d) for d in marks],
        headings=[heading_at(raw.coords, raw.cum_miles, d) for d in marks],
    )


def _geometry(p: _Prepared) -> tuple[dict, list[dict]]:
    """Simplified line with per-vertex wall-clock offsets, plus HOS stops.

    Each stop is inserted as two vertices at the same place (arrive, depart),
    so interpolating position over time keeps the truck parked during it.
    """
    raw, tl = p.raw, p.timeline
    keep = geo.simplify_indices(raw.coords, GEOMETRY_TOLERANCE_MI)
    rows = [(raw.cum_miles[i], raw.coords[i], tl.hos.wall_offset(raw.cum_drive_s[i])) for i in keep]
    stops = []
    for stop in tl.stops():
        miles = tl.miles_at_drive(stop.drive_s)
        lat, lon = geo.point_at(raw.coords, raw.cum_miles, miles)
        stops.append(
            {
                "kind": stop.kind,
                "lat": round(lat, 5),
                "lon": round(lon, 5),
                "miles": round(miles, 1),
                "start_offset_s": round(stop.start_offset_s),
                "duration_s": round(stop.duration_s),
            }
        )
        rows.append((miles, (lat, lon), stop.start_offset_s))
        rows.append((miles, (lat, lon), stop.start_offset_s + stop.duration_s))
    rows.sort(key=lambda r: (r[0], r[2]))
    return (
        {
            "coords": [[round(c[1], 5), round(c[0], 5)] for _, c, _ in rows],  # GeoJSON order
            "t": [round(t) for _, _, t in rows],
            "mi": [round(m, 2) for m, _, _ in rows],
        },
        stops,
    )


def plan_trip(req: TripRequest) -> dict:
    t_start = time.perf_counter()
    raw_routes, notes = routing.get_routes(req.origin.coord, req.destination.coord, req.load_lb)
    hos = HosPolicy(enabled=req.hos)
    prepared = [_prepare(r, req.interval_mi, hos) for r in raw_routes]
    t_routes = time.perf_counter()

    dep_ts = req.departure.timestamp()
    # The extra hours let the departure advisor re-score later departures with the same forecasts.
    window = weather.Window.covering(
        dep_ts, max(p.timeline.trip_s for p in prepared) + DEPARTURE_SEARCH_H * weather.HOUR
    )
    field = weather.fetch_field(
        (pt for p in prepared for pt in p.points), window, max_locations=settings.WEATHER_MAX_LOCATIONS
    )
    t_weather = time.perf_counter()

    storm = None
    if req.scenario == "storm":
        fastest = prepared[0]  # routes are sorted fastest first
        storm = req.storm or Storm.meeting_route(
            fastest.raw.coords, fastest.raw.cum_miles, fastest.timeline.offset_at(fastest.raw.miles / 2), dep_ts
        )

    def assess_at(p: _Prepared, k: int, t: float) -> tuple[WeatherSample, RiskAssessment]:
        sample = field.at(p.points[k]).sample_at(t)
        if storm:
            sample = storm.apply(sample, p.points[k], t)
        return sample, assess(sample, req.load_lb)

    def score_route(p: _Prepared, rid: str, shift_s: float = 0.0) -> RouteScore:
        miles = {lvl: 0.0 for lvl in RiskLevel}
        weighted = 0.0
        for k, (off, cov) in enumerate(zip(p.offsets, p.coverage)):
            level = assess_at(p, k, dep_ts + shift_s + off)[1].level
            miles[level] += cov
            weighted += cov * int(level)
        return RouteScore(rid, f"Route {rid}", miles, weighted / p.raw.miles if p.raw.miles else 0.0, p.timeline.trip_s)

    routes_out, scores = [], []
    for idx, p in enumerate(prepared):
        rid = ROUTE_IDS[idx]
        miles_by_level = {lvl: 0.0 for lvl in RiskLevel}
        weighted = 0.0
        checkpoints = []
        worst, worst_level = 0, RiskLevel.LOW
        max_cross, strong_cross = 0.0, 0
        for k, (mark, pt, off, cov) in enumerate(zip(p.marks, p.points, p.offsets, p.coverage)):
            sample, risk = assess_at(p, k, dep_ts + off)
            rel = None
            if sample.wind_dir_deg is not None:
                rel = relative_wind(sample.wind_mph, sample.gust_mph, sample.wind_dir_deg, p.headings[k])
                max_cross = max(max_cross, rel["crosswind_mph"])
                strong_cross += rel["strong"]
            miles_by_level[risk.level] += cov
            weighted += cov * int(risk.level)
            if risk.level > worst_level:
                worst, worst_level = k, risk.level
            checkpoints.append(
                {
                    "index": k,
                    "miles": round(mark, 1),
                    "lat": round(pt[0], 5),
                    "lon": round(pt[1], 5),
                    "offset_s": round(off),
                    "eta": _iso(dep_ts + off),
                    "coverage_mi": round(cov, 2),
                    "weather": sample.to_dict(),
                    "risk": risk.to_dict(),
                    "wind_relative": rel,  # extra, informational: never used for risk or ranking
                }
            )
        total = p.raw.miles
        avg_risk = weighted / total if total else 0.0
        score = RouteScore(rid, f"Route {rid}", miles_by_level, avg_risk, p.timeline.trip_s)
        scores.append(score)
        geometry, stops = _geometry(p)
        routes_out.append(
            {
                "id": rid,
                "name": score.name,
                "provider": p.raw.provider,
                "distance_mi": round(total, 1),
                "drive_s": round(p.timeline.drive_s),
                "trip_s": round(p.timeline.trip_s),
                "arrival": _iso(dep_ts + p.timeline.trip_s),
                "summary": {
                    "miles_by_level": {lvl.key: round(m, 1) for lvl, m in miles_by_level.items()},
                    "no_travel_miles": round(score.no_travel_miles, 1),
                    "severe_miles": round(score.severe_miles, 1),
                    "high_miles": round(score.high_miles, 1),
                    "avg_risk": round(avg_risk, 3),
                    "max_level": checkpoints[worst]["risk"]["level"],
                    "worst_checkpoint": worst,
                    "checkpoint_count": len(checkpoints),
                    "max_crosswind_mph": round(max_cross, 1),
                    "strong_crosswind_checkpoints": strong_cross,
                },
                "geometry": geometry,
                "stops": stops,
                "checkpoints": checkpoints,
            }
        )

    rec = recommend(scores)
    advice = _departure_advice(
        departure.evaluate(lambda shift_s: [score_route(p, ROUTE_IDS[i], shift_s) for i, p in enumerate(prepared)]),
        dep_ts,
    )
    rank_of = {rid: i + 1 for i, rid in enumerate(rec["ranking"])}
    for r in routes_out:
        r["rank"] = rank_of[r["id"]]
        r["recommended"] = r["id"] == rec["route_id"]

    t_end = time.perf_counter()
    log.info(
        "plan: %d routes, %d checkpoints, %d wx locations (lattice %.2f) | routing %.2fs weather %.2fs total %.2fs",
        len(routes_out), sum(len(r["checkpoints"]) for r in routes_out), len(field.series), field.lattice,
        t_routes - t_start, t_weather - t_routes, t_end - t_start,
    )
    return {
        "request": {
            "origin": {"label": req.origin.label, "lat": req.origin.lat, "lon": req.origin.lon},
            "destination": {"label": req.destination.label, "lat": req.destination.lat, "lon": req.destination.lon},
            "departure": _iso(dep_ts),
            "load_lb": req.load_lb,
            "interval_mi": req.interval_mi,
            "hos": req.hos,
        },
        "routes": routes_out,
        "recommendation": rec,
        "departure_advice": advice,
        "notes": notes,
        "weather": {
            "source": "Open-Meteo",
            "lattice_deg": field.lattice,
            "locations": len(field.series),
            "window_start": _iso(window.start),
            "window_end": _iso(window.end),
            "scenario": req.scenario,
            "storm": storm.to_dict() if storm else None,
        },
        "timing_ms": {
            "routing": round((t_routes - t_start) * 1000),
            "weather": round((t_weather - t_routes) * 1000),
            "total": round((t_end - t_start) * 1000),
        },
    }


def _departure_advice(options: list[departure.DepartureOption], dep_ts: float) -> dict:
    """Extra feature: the same ranking evaluated for later departures (rules unchanged)."""
    best, reason = departure.suggest(options)

    def row(o: departure.DepartureOption) -> dict:
        b = o.best
        return {
            "shift_h": o.shift_h,
            "departure": _iso(dep_ts + o.shift_h * weather.HOUR),
            "route_id": b.route_id,
            "no_travel_miles": round(b.no_travel_miles, 1),
            "severe_miles": round(b.severe_miles, 1),
            "high_miles": round(b.high_miles, 1),
            "avg_risk": round(b.avg_risk, 3),
            "arrival": _iso(dep_ts + o.arrival_offset_s),
        }

    return {
        "options": [row(o) for o in options],
        "suggestion": {**row(best), "reason": reason} if best else None,
    }


HEATMAP_HOURS = 48


def plan_heatmap(
    departure: datetime, load_lb: float, routes_lonlat: list[list[list[float]]], storm: Storm | None = None
) -> dict:
    """Hourly (0-48 h) weather and risk on a grid along the trip corridor.

    All frames are returned at once so the UI slider never waits on the network.
    Precipitation values at hour ``h`` are totals for the hour ending at ``h``.
    ``storm`` is the demo-scenario storm returned by the plan, applied identically here.
    """
    t0 = time.perf_counter()
    routes = [[(lat, lon) for lon, lat in r] for r in routes_lonlat]
    max_cells = settings.HEATMAP_MAX_CELLS
    grid = corridor.corridor_grid(routes, max_cells=max_cells)
    start = int(departure.timestamp() // weather.HOUR * weather.HOUR)
    window = weather.Window(start, start + HEATMAP_HOURS * weather.HOUR)
    nodes = [grid.coord(c) for c in grid.cells]
    field = weather.fetch_field(nodes, window, max_locations=max_cells + 20)
    series = [field.at(n) for n in nodes]

    frames = {"risk": [], "wind": [], "rain": [], "snow": []}
    for h in range(window.hours):
        risk, wind, rain, snow = [], [], [], []
        t = start + h * weather.HOUR
        for node, s in zip(nodes, series):
            sample = s.hour(h)
            if storm:
                sample = storm.apply(sample, node, t)
            risk.append(int(assess(sample, load_lb).level))
            wind.append(round(sample.wind_mph, 1))
            rain.append(round(sample.rain_in_hr, 3))
            snow.append(round(sample.snow_in_hr, 3))
        frames["risk"].append(risk)
        frames["wind"].append(wind)
        frames["rain"].append(rain)
        frames["snow"].append(snow)

    log.info("heatmap: %d cells x %d hours, step %.2f deg, %.2fs",
             len(nodes), window.hours, grid.step_deg, time.perf_counter() - t0)
    return {
        "start": _iso(start),
        "step_s": weather.HOUR,
        "hours": window.hours,
        "load_lb": load_lb,
        "grid": {
            "lats": [round(v, 5) for v in grid.lats],
            "lons": [round(v, 5) for v in grid.lons],
            "step_deg": grid.step_deg,
            "cells": [list(c) for c in grid.cells],
            "corners": [[round(lon, 5), round(lat, 5)] for lon, lat in grid.corners],
        },
        "frames": frames,
    }


def departure_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or datetime.now(timezone.utc)
    return now - timedelta(hours=1), now + timedelta(days=7)
