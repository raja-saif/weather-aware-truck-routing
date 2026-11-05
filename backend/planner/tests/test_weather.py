from urllib.parse import parse_qs, urlparse

import pytest
import responses
from django.core.cache import cache
from django.test import override_settings

from planner.api.errors import UpstreamError
from planner.services import weather
from planner.services.weather import HOUR, HourlySeries, Window

URL = "https://meteo.test/v1/forecast"
T0 = 1_800_000_000 // HOUR * HOUR  # an hour-aligned instant


@pytest.fixture(autouse=True)
def _settings():
    cache.clear()
    with override_settings(OPEN_METEO_URL=URL, OPEN_METEO_API_KEY=""):
        yield


def series(**overrides):
    base = dict(
        start=T0,
        wind=(10.0, 20.0, 30.0),
        gust=(15.0, 25.0, 35.0),
        rain=(0.0, 0.2, 0.6),
        snow=(0.0, 0.0, 1.5),
        temp=(30.0, 32.0, 34.0),
        code=(0, 61, 73),
    )
    base.update(overrides)
    return HourlySeries(**base)


def test_snap_to_lattice():
    assert weather.snap((40.0249, -100.0251)) == (40.0, -100.05)
    assert weather.snap((40.026, -99.974)) == (40.05, -99.95)


def test_window_is_hour_aligned_and_padded():
    w = Window.covering(T0 + 1200, 5 * HOUR)
    assert w.start == T0
    assert w.end == T0 + 7 * HOUR  # ceil(T0+5h20m) = T0+6h, plus one spare hour
    assert w.hours == 8


def test_sample_interpolates_wind_and_uses_hour_ending_for_precip():
    s = series().sample_at(T0 + 1.5 * HOUR)
    assert s.wind_mph == pytest.approx(25.0)
    assert s.temperature_f == pytest.approx(33.0)
    # 1.5h falls in the hour ending at index 2
    assert s.rain_in_hr == pytest.approx(0.6)
    assert s.snow_in_hr == pytest.approx(1.5)
    assert s.weather_code == 73


def test_sample_exactly_on_the_hour_and_clamped_outside():
    s = series().sample_at(T0 + HOUR)
    assert s.wind_mph == 20.0 and s.rain_in_hr == pytest.approx(0.2)
    assert series().sample_at(T0 - 999).wind_mph == 10.0
    assert series().sample_at(T0 + 99 * HOUR).wind_mph == 30.0


def _payload(n, window, wind=12.0):
    hours = window.hours
    return [
        {
            "hourly": {
                "time": [window.start + k * HOUR for k in range(hours)],
                "wind_speed_10m": [wind] * hours,
                "wind_gusts_10m": [wind + 5] * hours,
                "rain": [0.1] * hours,
                "showers": [0.05] * (hours - 1) + [None],
                "snowfall": [0.0] * hours,
                "weather_code": [61] * hours,
                "temperature_2m": [40.0] * hours,
            }
        }
        for _ in range(n)
    ]


@responses.activate
def test_fetch_batches_dedupes_and_caches():
    window = Window(T0, T0 + 3 * HOUR)
    calls = []

    def cb(request):
        q = parse_qs(urlparse(request.url).query)
        n = len(q["latitude"][0].split(","))
        calls.append((n, q))
        import json

        return 200, {}, json.dumps(_payload(n, window))

    responses.add_callback(responses.GET, URL, callback=cb)
    # 250 distinct lattice points + duplicates that snap onto them
    pts = [(30 + i * 0.05, -100.0) for i in range(250)] + [(30.01, -100.01)]
    out = weather.fetch(pts, window)
    assert len(out) == 250
    assert sorted(n for n, _ in calls) == [50, 100, 100]
    q = calls[0][1]
    assert q["wind_speed_unit"] == ["mph"] and q["precipitation_unit"] == ["inch"]
    assert q["start_hour"][0].endswith(":00")
    any_series = next(iter(out.values()))
    assert any_series.rain[0] == pytest.approx(0.15)  # rain + showers
    assert any_series.rain[-1] == pytest.approx(0.15)  # null carried forward

    calls.clear()
    weather.fetch(pts[:10], window)
    assert calls == []  # served from cache


@responses.activate
def test_fetch_field_coarsens_lattice_to_stay_within_budget():
    import json

    window = Window(T0, T0 + HOUR)
    responses.add_callback(
        responses.GET, URL,
        callback=lambda r: (200, {}, json.dumps(_payload(len(parse_qs(urlparse(r.url).query)["latitude"][0].split(",")), window))),
    )
    pts = [(30 + i * 0.05, -100.0) for i in range(40)]  # 40 points 0.05 deg apart
    fine = weather.fetch_field(pts, window, max_locations=50)
    assert fine.lattice == 0.05 and len(fine.series) == 40
    coarse = weather.fetch_field(pts, window, max_locations=25)
    assert coarse.lattice == 0.1 and len(coarse.series) <= 25
    # every original point resolves through the chosen lattice
    assert all(coarse.at(p) for p in pts)


@responses.activate
def test_rate_limit_is_reported_clearly():
    responses.get(URL, status=429, json={"reason": "Too many requests"})
    with pytest.raises(UpstreamError) as exc:
        weather.fetch([(40.0, -100.0)], Window(T0, T0 + HOUR))
    assert exc.value.code == "weather_rate_limited"
