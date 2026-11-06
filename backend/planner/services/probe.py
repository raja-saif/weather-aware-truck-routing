"""Reachability check for every third-party provider, as seen from this server.

Public APIs sometimes rate-limit or block cloud-hosting IP ranges, which only
shows up once deployed. ``GET /api/health/upstreams`` makes one tiny request to
each provider in parallel and reports status and latency. Results are cached
briefly so the endpoint cannot be used to hammer the providers.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import requests
from django.conf import settings
from django.core.cache import cache

from .http import session

CACHE_KEY = "upstream-probe"
CACHE_TTL = 60
TIMEOUT = (5, 8)

# Two points in downtown Dallas: a trivially short route.
_A, _B = (32.7767, -96.7970), (32.7831, -96.8067)


def _probes() -> dict:
    return {
        "valhalla": lambda: session().post(
            settings.VALHALLA_URL,
            json={"locations": [{"lat": _A[0], "lon": _A[1]}, {"lat": _B[0], "lon": _B[1]}],
                  "costing": "truck", "directions_type": "none"},
            timeout=TIMEOUT,
        ),
        "osrm": lambda: session().get(
            f"{settings.OSRM_URL}/{_A[1]},{_A[0]};{_B[1]},{_B[0]}", params={"overview": "false"}, timeout=TIMEOUT
        ),
        "photon": lambda: session().get(settings.PHOTON_URL, params={"q": "Dallas", "limit": 1}, timeout=TIMEOUT),
        "open_meteo_geocoding": lambda: session().get(
            settings.OPEN_METEO_GEOCODING_URL, params={"name": "Dallas", "count": 1}, timeout=TIMEOUT
        ),
        "open_meteo_forecast": lambda: session().get(
            settings.OPEN_METEO_URL,
            params={"latitude": _A[0], "longitude": _A[1], "hourly": "wind_speed_10m", "forecast_days": 1},
            timeout=TIMEOUT,
        ),
        "metno_forecast": lambda: session().get(
            settings.METNO_URL, params={"lat": f"{_A[0]:.2f}", "lon": f"{_A[1]:.2f}"}, timeout=TIMEOUT
        ),
    }


def _run(call) -> dict:
    t0 = time.perf_counter()
    try:
        resp = call()
        ok = resp.status_code == 200
        out = {"ok": ok, "status": resp.status_code}
        if not ok:
            out["detail"] = resp.text[:200]
    except requests.RequestException as exc:
        out = {"ok": False, "status": None, "detail": f"{type(exc).__name__}: {exc}"[:200]}
    out["ms"] = round((time.perf_counter() - t0) * 1000)
    return out


def check_all() -> dict:
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached
    probes = _probes()
    with ThreadPoolExecutor(max_workers=len(probes)) as pool:
        results = dict(zip(probes, pool.map(_run, probes.values())))
    cache.set(CACHE_KEY, results, CACHE_TTL)
    return results
