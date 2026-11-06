"""MET Norway fallback: conversion to Open-Meteo's hourly conventions, and failover."""

from datetime import datetime, timezone

import pytest
import responses
from django.core.cache import cache
from django.test import override_settings

from planner.api.errors import UpstreamError
from planner.services import metno, weather
from planner.services.weather import HOUR, Window

OM = "https://meteo.test/v1/forecast"
MET = "https://met.test/locationforecast"
T0 = 1_800_000_000 // HOUR * HOUR


@pytest.fixture(autouse=True)
def _settings():
    cache.clear()
    with override_settings(OPEN_METEO_URL=OM, OPEN_METEO_API_KEY="", METNO_URL=MET):
        yield


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _step(ts, wind_ms, temp_c, n1=None, n6=None, gust_ms=None, direction=90.0):
    details = {"wind_speed": wind_ms, "air_temperature": temp_c, "wind_from_direction": direction}
    if gust_ms is not None:
        details["wind_speed_of_gust"] = gust_ms
    data = {"instant": {"details": details}}
    if n1:
        data["next_1_hours"] = {"summary": {"symbol_code": n1[1]}, "details": {"precipitation_amount": n1[0]}}
    if n6:
        data["next_6_hours"] = {"summary": {"symbol_code": n6[1]}, "details": {"precipitation_amount": n6[0]}}
    return {"time": _iso(ts), "data": data}


def _forecast(steps):
    return {"properties": {"timeseries": steps}}


def test_units_and_hour_ending_precipitation():
    data = _forecast([
        _step(T0, 10.0, 0.0, n1=(2.54, "heavyrain"), gust_ms=15.0),
        _step(T0 + HOUR, 20.0, 10.0, n1=(5.0, "snow")),
    ])
    s = metno.to_series(data, T0, 2)
    assert s.source == "MET Norway"
    assert s.wind == (22.4, 44.7)  # m/s -> mph
    assert s.gust[0] == 33.6 and s.gust[1] == 44.7  # missing gust falls back to the wind speed
    assert s.temp == (32.0, 50.0)
    # Open-Meteo convention: the value at hour h covers the hour *ending* at h
    assert s.rain == (0.0, 0.1) and s.snow == (0.0, 0.0)
    assert s.code[1] == 65  # heavy rain


def test_six_hour_steps_are_interpolated_and_spread():
    data = _forecast([
        _step(T0, 0.0, -5.0, n6=(6.0, "snow")),
        _step(T0 + 6 * HOUR, 12.0, -5.0),
    ])
    s = metno.to_series(data, T0, 7)
    assert s.wind[3] == pytest.approx(6.0 * metno.MS_TO_MPH, abs=0.1)  # halfway between steps
    # 6 mm over 6 h -> 1 mm/h of water -> 0.7 cm/h of snow depth, in inches
    assert s.snow[1] == pytest.approx(0.7 / 2.54, abs=0.001)
    assert s.rain[1] == 0.0
    assert s.code[1] == 73


def test_wmo_mapping():
    assert metno._wmo_code("clearsky_day") == 0
    assert metno._wmo_code("rainandthunder") == 95
    assert metno._wmo_code("lightrainshowers_night") == 80
    assert metno._wmo_code("heavysnow") == 75


@responses.activate
def test_open_meteo_quota_falls_back_to_met_norway_and_is_skipped_afterwards():
    responses.get(OM, status=429, json={"reason": "Daily API request limit exceeded."})
    responses.get(MET, json=_forecast([_step(T0, 10.0, 5.0), _step(T0 + HOUR, 10.0, 5.0)]))
    window = Window(T0, T0 + HOUR)
    got = weather.fetch([(40.0, -100.0), (41.0, -100.0)], window)
    assert {s.source for s in got.values()} == {"MET Norway"}
    assert sum(1 for c in responses.calls if c.request.url.startswith(OM)) == 1

    weather.fetch([(42.0, -100.0)], window)  # Open-Meteo is not asked again during the cool-down
    assert sum(1 for c in responses.calls if c.request.url.startswith(OM)) == 1
    assert sum(1 for c in responses.calls if c.request.url.startswith(MET)) == 3


@responses.activate
def test_both_weather_providers_down_reports_the_original_error():
    responses.get(OM, status=429, json={"reason": "Too many requests"})
    responses.get(MET, status=503)
    with pytest.raises(UpstreamError) as exc:
        weather.fetch([(40.0, -100.0)], Window(T0, T0 + HOUR))
    assert exc.value.code == "weather_rate_limited"
