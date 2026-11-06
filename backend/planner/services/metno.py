"""Fallback forecasts from MET Norway's free Locationforecast API (no key).

Used when Open-Meteo refuses (its free tier has a daily per-IP quota, which
shared cloud-hosting IPs can exhaust). One request per location, run in
parallel. The response is converted to the same hourly series and units as
Open-Meteo:

* instantaneous values (wind, gust, temperature, direction) at each hour,
  linearly interpolated where the forecast steps are 6-hourly (beyond ~2.5 days);
* precipitation for the hour *ending* at each hour (Open-Meteo's convention),
  from ``next_1_hours``, or a sixth of ``next_6_hours`` where only that exists;
* MET gives total precipitation only, so the symbol code decides rain vs snow,
  and snow depth uses Open-Meteo's ratio (1 mm water -> 0.7 cm snow).
"""

from __future__ import annotations

import bisect
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests
from django.conf import settings

from ..domain.geo import Coord
from .http import DEFAULT_TIMEOUT, session

log = logging.getLogger(__name__)

HOUR = 3600
MAX_PARALLEL = 8
SOURCE = "MET Norway"

MS_TO_MPH = 2.236936
MM_TO_IN = 1 / 25.4
SNOW_CM_PER_MM = 0.7


class Unavailable(Exception):
    pass


def _c_to_f(c: float) -> float:
    return c * 9 / 5 + 32


def _wmo_code(symbol: str | None) -> int:
    """Approximate WMO weather code for a MET symbol code (display only)."""
    if not symbol:
        return 0
    s = symbol.split("_")[0]
    if "thunder" in s:
        return 95
    if "sleet" in s:
        return 66 if "light" in s else 67
    if "snow" in s:
        return 85 if "showers" in s else (71 if "light" in s else 75 if "heavy" in s else 73)
    if "rain" in s:
        return 80 if "showers" in s else (61 if "light" in s else 65 if "heavy" in s else 63)
    return {"clearsky": 0, "fair": 1, "partlycloudy": 2, "cloudy": 3, "fog": 45}.get(s, 3)


def _snow_share(symbol: str | None, temp_c: float) -> float:
    if symbol:
        if "sleet" in symbol:
            return 0.5
        return 1.0 if "snow" in symbol else 0.0
    return 1.0 if temp_c <= 0.5 else 0.0


def _ts(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def to_series(data: dict, start: int, hours: int):
    """Convert a Locationforecast response to an hourly series starting at ``start``."""
    from .weather import HourlySeries, _lerp_angle  # local import: weather imports this module

    steps = []
    for item in data["properties"]["timeseries"]:
        d = item["data"]
        inst = d["instant"]["details"]
        steps.append((_ts(item["time"]), inst, d.get("next_1_hours"), d.get("next_6_hours")))
    if not steps:
        raise Unavailable("empty forecast")
    times = [s[0] for s in steps]

    def instant(t: int):
        i = bisect.bisect_right(times, t) - 1
        if i < 0:
            return steps[0][1], steps[0][1], 0.0
        if i >= len(steps) - 1:
            return steps[-1][1], steps[-1][1], 0.0
        f = (t - times[i]) / (times[i + 1] - times[i])
        return steps[i][1], steps[i + 1][1], f

    def precip(t_end: int):
        """(mm, symbol) for the hour ending at ``t_end``."""
        t0 = t_end - HOUR
        i = bisect.bisect_right(times, t0) - 1
        if i < 0:
            return 0.0, None
        t_step, _, n1, n6 = steps[i]
        if n1 and t_step == t0:
            return n1["details"].get("precipitation_amount", 0.0), n1.get("summary", {}).get("symbol_code")
        if n6 and t0 < t_step + 6 * HOUR:
            return n6["details"].get("precipitation_amount", 0.0) / 6, n6.get("summary", {}).get("symbol_code")
        if n1 and t0 < t_step + HOUR:
            return n1["details"].get("precipitation_amount", 0.0), n1.get("summary", {}).get("symbol_code")
        return 0.0, None

    wind, gust, rain, snow, temp, code, wdir = [], [], [], [], [], [], []
    for k in range(hours):
        t = start + k * HOUR
        a, b, f = instant(t)

        def lerp(key, default=0.0):
            va, vb = a.get(key, default), b.get(key, default)
            return va + (vb - va) * f

        w = lerp("wind_speed")
        # gusts are not forecast everywhere: a step without one uses its own wind speed
        ga = a.get("wind_speed_of_gust", a.get("wind_speed", 0.0))
        gb = b.get("wind_speed_of_gust", b.get("wind_speed", 0.0))
        g = ga + (gb - ga) * f
        tc = lerp("air_temperature")
        mm, symbol = precip(t)
        share = _snow_share(symbol, tc)
        wind.append(round(w * MS_TO_MPH, 1))
        gust.append(round(max(g, w) * MS_TO_MPH, 1))
        rain.append(round(mm * (1 - share) * MM_TO_IN, 3))
        snow.append(round(mm * share * SNOW_CM_PER_MM / 2.54, 3))
        temp.append(round(_c_to_f(tc), 1))
        code.append(_wmo_code(symbol))
        da, db = a.get("wind_from_direction", 0.0), b.get("wind_from_direction", 0.0)
        wdir.append(round(_lerp_angle(da, db, f) % 360, 1))
    return HourlySeries(
        start=start, wind=tuple(wind), gust=tuple(gust), rain=tuple(rain), snow=tuple(snow),
        temp=tuple(temp), code=tuple(code), wdir=tuple(wdir), source=SOURCE,
    )


def _fetch_one(p: Coord, start: int, hours: int):
    try:
        resp = session().get(
            settings.METNO_URL, params={"lat": f"{p[0]:.2f}", "lon": f"{p[1]:.2f}"}, timeout=DEFAULT_TIMEOUT
        )
    except requests.RequestException as exc:
        raise Unavailable(str(exc)) from exc
    if resp.status_code not in (200, 203):  # 203 = deprecated-version notice, data still valid
        raise Unavailable(f"HTTP {resp.status_code}")
    try:
        return to_series(resp.json(), start, hours)
    except (ValueError, KeyError) as exc:
        raise Unavailable(f"unexpected response: {exc}") from exc


def fetch(points: list[Coord], start: int, hours: int) -> list:
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(points))) as pool:
        return list(pool.map(lambda p: _fetch_one(p, start, hours), points))
