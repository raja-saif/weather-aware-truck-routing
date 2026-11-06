"""Deployment resilience: place-search fallback and the upstream probe endpoint."""

import pytest
import responses
from django.core.cache import cache
from django.test import Client, override_settings

from planner.api.errors import UpstreamError
from planner.services import geocoding

PHOTON = "https://photon.test/api/"
OM_GEO = "https://geo.test/v1/search"
VALHALLA = "https://valhalla.test/route"
OSRM = "https://osrm.test/route/v1/driving"
FORECAST = "https://forecast.test/v1/forecast"


@pytest.fixture(autouse=True)
def _settings():
    cache.clear()
    with override_settings(
        PHOTON_URL=PHOTON, OPEN_METEO_GEOCODING_URL=OM_GEO, VALHALLA_URL=VALHALLA, OSRM_URL=OSRM,
        OPEN_METEO_URL=FORECAST,
    ):
        yield


@responses.activate
def test_photon_result_is_used_when_available():
    responses.get(PHOTON, json={"features": [{
        "geometry": {"coordinates": [-96.8, 32.78]},
        "properties": {"name": "Dallas", "state": "Texas", "countrycode": "US", "osm_value": "city"},
    }]})
    assert geocoding.search("Dallas") == [{"label": "Dallas, Texas", "lat": 32.78, "lon": -96.8, "kind": "city"}]
    assert len(responses.calls) == 1


@responses.activate
def test_blocked_photon_falls_back_to_open_meteo_geocoder():
    responses.get(PHOTON, status=403)
    responses.get(OM_GEO, json={"results": [
        {"name": "Dallas", "admin1": "Texas", "country": "United States", "country_code": "US",
         "latitude": 32.78, "longitude": -96.8},
        {"name": "Dallas", "admin1": "Ontario", "country": "Canada", "country_code": "CA",
         "latitude": 43.0, "longitude": -80.0},
    ]})
    results = geocoding.search("Dallas, TX")
    assert [r["label"] for r in results] == ["Dallas, Texas", "Dallas, Ontario, Canada"]
    # only the place name goes to the fallback, which cannot parse "City, ST"
    assert responses.calls[1].request.params["name"] == "Dallas"


@responses.activate
def test_both_geocoders_down_is_a_clear_upstream_error():
    responses.get(PHOTON, status=429)
    responses.get(OM_GEO, status=500)
    with pytest.raises(UpstreamError) as exc:
        geocoding.search("Dallas")
    assert exc.value.code == "geocoding_unavailable"


@responses.activate
def test_upstreams_endpoint_reports_each_provider():
    responses.post(VALHALLA, json={"trip": {}})
    responses.get(f"{OSRM}/-96.797,32.7767;-96.8067,32.7831", json={"code": "Ok"})
    responses.get(PHOTON, status=403, body="blocked")
    responses.get(OM_GEO, json={"results": []})
    responses.get(FORECAST, json={"hourly": {}})
    data = Client().get("/api/health/upstreams").json()
    providers = data["providers"]
    assert data["ok"] is False
    assert providers["photon"] == {"ok": False, "status": 403, "detail": "blocked", "ms": providers["photon"]["ms"]}
    assert all(providers[k]["ok"] for k in ("valhalla", "osrm", "open_meteo_geocoding", "open_meteo_forecast"))
