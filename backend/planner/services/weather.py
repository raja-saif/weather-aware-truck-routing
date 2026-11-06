"""Hourly forecasts from Open-Meteo, batched and cached (MET Norway as fallback).

* Locations are snapped to a 0.05 deg lattice (~3.5 mi). Forecast models run at
  3-13 km resolution, so this loses nothing, and it lets checkpoints on shared
  highway stretches (and repeat requests) reuse one forecast.
* Up to 100 locations per HTTP request; batches run in parallel.
* ``sample_at`` evaluates a series at an arbitrary instant:
  - wind, gusts, temperature are instantaneous values -> linear interpolation
  - rain, snow (and weather code) are totals over the *preceding* hour in
    Open-Meteo -> use the hour that ends at/after the instant, i.e. the hour
    the truck is actually driving through. Units are already in/hr.
"""

from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import requests
from django.conf import settings
from django.core.cache import cache

from ..api.errors import UpstreamError
from ..domain.geo import Coord
from ..domain.risk import WeatherSample
from . import metno
from .http import DEFAULT_TIMEOUT, session

log = logging.getLogger(__name__)

# After Open-Meteo refuses (e.g. its daily free quota on a shared cloud IP),
# use the MET Norway fallback for a while without asking Open-Meteo first.
OPEN_METEO_DOWN_KEY = "provider-down:open-meteo"
PROVIDER_DOWN_TTL = 30 * 60

LATTICE_DEG = 0.05
# Coarser lattices used when a request would exceed the location budget (the
# free API allows 600 location-calls per minute).
LATTICE_STEPS = (0.05, 0.075, 0.1, 0.125, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5)
BATCH_SIZE = 100
MAX_PARALLEL = 4
CACHE_TTL = 30 * 60
HOUR = 3600
HOURLY_VARS = (
    "wind_speed_10m", "wind_gusts_10m", "wind_direction_10m", "rain", "showers", "snowfall", "weather_code", "temperature_2m",
)


def snap(p: Coord, lattice: float = LATTICE_DEG) -> Coord:
    return (round(round(p[0] / lattice) * lattice, 2), round(round(p[1] / lattice) * lattice, 2))


@dataclass(frozen=True)
class HourlySeries:
    start: int  # unix seconds of the first hour
    wind: tuple[float, ...]
    gust: tuple[float, ...]
    rain: tuple[float, ...]  # rain + showers, in/hr
    snow: tuple[float, ...]  # snowfall, in/hr
    temp: tuple[float, ...]
    code: tuple[int, ...]
    wdir: tuple[float, ...] = ()  # direction the wind blows FROM, degrees (optional)
    source: str = "Open-Meteo"

    @property
    def hours(self) -> int:
        return len(self.wind)

    def sample_at(self, t: float) -> WeatherSample:
        pos = (t - self.start) / HOUR
        pos = min(max(pos, 0.0), self.hours - 1)
        lo = int(math.floor(pos))
        hi = min(lo + 1, self.hours - 1)
        f = pos - lo
        ending = int(math.ceil(pos))  # hour whose accumulation window contains t

        def lerp(arr):
            return arr[lo] + (arr[hi] - arr[lo]) * f

        return WeatherSample(
            wind_mph=round(lerp(self.wind), 1),
            gust_mph=round(lerp(self.gust), 1),
            rain_in_hr=round(self.rain[ending], 3),
            snow_in_hr=round(self.snow[ending], 3),
            temperature_f=round(lerp(self.temp), 1),
            weather_code=self.code[ending],
            wind_dir_deg=round(_lerp_angle(self.wdir[lo], self.wdir[hi], f)) % 360 if self.wdir else None,
        )

    def hour(self, k: int) -> WeatherSample:
        """Values at hour index ``k`` (heatmap frames)."""
        return WeatherSample(
            wind_mph=self.wind[k], gust_mph=self.gust[k], rain_in_hr=self.rain[k], snow_in_hr=self.snow[k],
            temperature_f=self.temp[k], weather_code=self.code[k],
            wind_dir_deg=self.wdir[k] if self.wdir else None,
        )


def _lerp_angle(a: float, b: float, f: float) -> float:
    """Interpolate compass angles along the shorter arc (350 -> 10 passes through 0)."""
    diff = (b - a + 180) % 360 - 180
    return a + diff * f


@dataclass(frozen=True)
class Window:
    """Hour-aligned [start, end] (inclusive) in unix seconds."""

    start: int
    end: int

    @classmethod
    def covering(cls, t0: float, duration_s: float) -> "Window":
        start = int(t0 // HOUR * HOUR)
        end = int(math.ceil((t0 + duration_s) / HOUR) * HOUR) + HOUR
        return cls(start, end)

    @property
    def hours(self) -> int:
        return (self.end - self.start) // HOUR + 1


def _fmt(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M")


def _clean(values: list, default: float = 0.0) -> tuple:
    """Open-Meteo may return nulls at the edge of a model's range; carry the last value forward."""
    out, last = [], default
    for v in values:
        if v is None:
            v = last
        out.append(v)
        last = v
    return tuple(out)


def _parse(item: dict, window: Window) -> HourlySeries:
    h = item["hourly"]
    times = h["time"]
    if not times or times[0] != window.start:
        raise UpstreamError("Weather service returned an unexpected time range.", code="weather_unavailable")
    rain = _clean(h["rain"])
    showers = _clean(h["showers"])
    return HourlySeries(
        start=times[0],
        wind=_clean(h["wind_speed_10m"]),
        gust=_clean(h["wind_gusts_10m"]),
        rain=tuple(round(r + s, 3) for r, s in zip(rain, showers)),
        snow=_clean(h["snowfall"]),
        temp=_clean(h["temperature_2m"]),
        code=tuple(int(c) for c in _clean(h["weather_code"], 0)),
        wdir=_clean(h.get("wind_direction_10m") or []),
    )


def _fetch_batch(points: list[Coord], window: Window) -> list[HourlySeries]:
    params = {
        "latitude": ",".join(f"{p[0]:.2f}" for p in points),
        "longitude": ",".join(f"{p[1]:.2f}" for p in points),
        "hourly": ",".join(HOURLY_VARS),
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "temperature_unit": "fahrenheit",
        "timeformat": "unixtime",
        "timezone": "GMT",
        "start_hour": _fmt(window.start),
        "end_hour": _fmt(window.end),
    }
    if settings.OPEN_METEO_API_KEY:
        params["apikey"] = settings.OPEN_METEO_API_KEY
    try:
        resp = session().get(settings.OPEN_METEO_URL, params=params, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        raise UpstreamError("Weather service is unreachable. Please try again shortly.", code="weather_unavailable") from exc
    if resp.status_code == 429:
        raise UpstreamError(
            "Weather service rate limit reached. Please wait a minute and try again.",
            code="weather_rate_limited", status_code=503,
        )
    if resp.status_code != 200:
        reason = ""
        try:
            reason = resp.json().get("reason", "")
        except ValueError:
            pass
        log.error("Open-Meteo HTTP %s: %s", resp.status_code, reason)
        raise UpstreamError(f"Weather service error: {reason or resp.status_code}", code="weather_unavailable")
    data = resp.json()
    items = data if isinstance(data, list) else [data]
    if len(items) != len(points):
        raise UpstreamError("Weather service returned an incomplete response.", code="weather_unavailable")
    return [_parse(item, window) for item in items]


def _fetch_open_meteo(points: list[Coord], window: Window) -> list[HourlySeries]:
    batches = [points[i : i + BATCH_SIZE] for i in range(0, len(points), BATCH_SIZE)]
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(batches))) as pool:
        fetched = list(pool.map(lambda b: _fetch_batch(b, window), batches))
    return [s for batch in fetched for s in batch]


def _fetch_missing(points: list[Coord], window: Window) -> list[HourlySeries]:
    """Open-Meteo first; MET Norway when Open-Meteo is over quota or down."""
    error: UpstreamError | None = None
    if not cache.get(OPEN_METEO_DOWN_KEY):
        try:
            return _fetch_open_meteo(points, window)
        except UpstreamError as exc:
            log.warning("Open-Meteo failed (%s); falling back to MET Norway", exc.code)
            cache.set(OPEN_METEO_DOWN_KEY, True, PROVIDER_DOWN_TTL)
            error = exc
    try:
        return metno.fetch(points, window.start, window.hours)
    except metno.Unavailable as exc:
        log.error("MET Norway fallback failed: %s", exc)
        raise error or UpstreamError(
            "Weather service is unreachable. Please try again shortly.", code="weather_unavailable"
        ) from exc


def _cache_key(p: Coord, window: Window) -> str:
    return f"wx:{p[0]:.2f},{p[1]:.2f}:{window.start}:{window.end}"


@dataclass(frozen=True)
class WeatherField:
    """Forecasts for a set of points, looked up through the lattice they were snapped to."""

    lattice: float
    series: dict[Coord, HourlySeries]

    def at(self, p: Coord) -> HourlySeries:
        return self.series[snap(p, self.lattice)]


def fetch_field(points: Iterable[Coord], window: Window, *, max_locations: int = 400) -> WeatherField:
    """Like :func:`fetch`, using the finest lattice whose location count fits the budget."""
    pts = list(points)
    for lattice in LATTICE_STEPS:
        if len({snap(p, lattice) for p in pts}) <= max_locations:
            break
    return WeatherField(lattice, fetch(pts, window, lattice=lattice))


def fetch(points: Iterable[Coord], window: Window, *, lattice: float = LATTICE_DEG) -> dict[Coord, HourlySeries]:
    """Forecast series for every point, keyed by its snapped lattice coordinate."""
    keys = sorted({snap(p, lattice) for p in points})
    cache_keys = {k: _cache_key(k, window) for k in keys}
    hits = cache.get_many(list(cache_keys.values()))
    result: dict[Coord, HourlySeries] = {}
    missing = []
    for k in keys:
        series = hits.get(cache_keys[k])
        if series is None:
            missing.append(k)
        else:
            result[k] = series
    if missing:
        fresh = {}
        for k, series in zip(missing, _fetch_missing(missing, window)):
            result[k] = series
            fresh[cache_keys[k]] = series
        cache.set_many(fresh, CACHE_TTL)
    log.info("weather: %d locations (%d cached, %d fetched)", len(keys), len(keys) - len(missing), len(missing))
    return result
