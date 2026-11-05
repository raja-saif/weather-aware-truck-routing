"""Place search via Photon (OpenStreetMap data, built for type-ahead), cached."""

from __future__ import annotations

import hashlib
import re

import requests
from django.conf import settings
from django.core.cache import cache

from ..api.errors import PlanningError, UpstreamError
from .http import session

CACHE_TTL = 24 * 60 * 60
_LATLON = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*[, ]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


def parse_latlon(text: str) -> tuple[float, float] | None:
    m = _LATLON.match(text)
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None


def _label(props: dict) -> str:
    street = " ".join(p for p in (props.get("housenumber"), props.get("street")) if p)
    name = props.get("name")
    parts = [name, street if street != name else None, props.get("city") if props.get("city") != name else None,
             props.get("state") if props.get("state") != name else None]
    country = props.get("countrycode", "").upper()
    if country and country != "US":
        parts.append(props.get("country"))
    return ", ".join(p for p in parts if p)


def search(query: str, limit: int = 6) -> list[dict]:
    query = query.strip()
    coords = parse_latlon(query)
    if coords:
        return [{"label": f"{coords[0]:.5f}, {coords[1]:.5f}", "lat": coords[0], "lon": coords[1], "kind": "coordinates"}]
    key = "geo:" + hashlib.sha1(f"{query.lower()}|{limit}".encode()).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        resp = session().get(
            settings.PHOTON_URL, params={"q": query, "limit": limit + 4, "lang": "en"}, timeout=(5, 10)
        )
    except requests.RequestException as exc:
        raise UpstreamError("Place search is unavailable right now.", code="geocoding_unavailable") from exc
    if resp.status_code != 200:
        raise UpstreamError("Place search is unavailable right now.", code="geocoding_unavailable")
    results, seen = [], set()
    for feature in resp.json().get("features", []):
        props = feature.get("properties", {})
        lon, lat = feature["geometry"]["coordinates"][:2]
        label = _label(props)
        if not label or label in seen:
            continue
        seen.add(label)
        results.append({"label": label, "lat": lat, "lon": lon, "kind": props.get("osm_value") or props.get("type")})
        if len(results) >= limit:
            break
    cache.set(key, results, CACHE_TTL)
    return results


def resolve(query: str) -> tuple[float, float, str]:
    """Best match for free text the user typed without picking a suggestion."""
    results = search(query, limit=1)
    if not results:
        raise PlanningError(f"Could not find a place called “{query}”.", code="place_not_found")
    best = results[0]
    return best["lat"], best["lon"], best["label"]
