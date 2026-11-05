"""API tests with routing and weather providers stubbed out (no network)."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from django.core.cache import cache
from django.test import Client

from planner.services import routing, weather
from planner.services.weather import HOUR, HourlySeries

from .helpers import straight_line


def _route(bulge: float, hours: float) -> routing.RawRoute:
    coords = [(40.0 + bulge * 4 * (k / 99) * (1 - k / 99), -100.0 + 10 * k / 99) for k in range(100)]
    drive = [hours * HOUR * k / 99 for k in range(100)]
    return routing.RawRoute(coords=coords, cum_drive_s=drive, provider="stub")


class _StormField:
    """Calm everywhere except a 45 mph wind band between lon -97 and -96."""

    lattice = 0.05

    def __init__(self, start):
        self.start = start
        self.series = {}

    def at(self, p):
        return self._series(45.0 if -97.0 <= p[1] <= -96.0 else 5.0)

    def _series(self, wind):
        cache = self.__dict__.setdefault("_cache", {})
        if wind not in cache:
            n = 200
            cache[wind] = HourlySeries(
                start=self.start, wind=(wind,) * n, gust=(wind,) * n, rain=(0.0,) * n,
                snow=(0.0,) * n, temp=(50.0,) * n, code=(0,) * n,
            )
        return cache[wind]


@pytest.fixture
def stubbed(monkeypatch):
    cache.clear()
    north, fast, south = _route(1.5, 9.5), _route(0.0, 9.0), _route(-1.5, 9.8)

    def fake_routes(origin, dest, load_lb):
        return [fast, north, south], []

    def fake_field(points, window, **kw):
        list(points)
        return _StormField(window.start)

    monkeypatch.setattr(routing, "get_routes", fake_routes)
    monkeypatch.setattr(weather, "fetch_field", fake_field)


def _body(**overrides):
    body = {
        "origin": {"label": "Origin", "lat": 40.0, "lon": -100.0},
        "destination": {"label": "Dest", "lat": 40.0, "lon": -90.0},
        "departure_time": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        "load_weight_lb": 20_000,
        "interval_miles": 10,
        "hos_breaks": True,
    }
    body.update(overrides)
    return body


def _post(body):
    return Client().post("/api/plan", data=json.dumps(body), content_type="application/json")


def test_plan_shape_and_invariants(stubbed):
    resp = _post(_body())
    assert resp.status_code == 200
    data = resp.json()
    assert [r["id"] for r in data["routes"]] == ["A", "B", "C"]
    for r in data["routes"]:
        cps = r["checkpoints"]
        gaps = [b["miles"] - a["miles"] for a, b in zip(cps, cps[1:])]
        assert max(gaps) <= 10.05
        assert sum(c["coverage_mi"] for c in cps) == pytest.approx(r["distance_mi"], abs=0.5)
        assert sum(r["summary"]["miles_by_level"].values()) == pytest.approx(r["distance_mi"], abs=0.5)
        etas = [c["offset_s"] for c in cps]
        assert etas == sorted(etas) and etas[0] == 0
        assert r["geometry"]["t"] == sorted(r["geometry"]["t"])
        assert len(r["geometry"]["coords"]) == len(r["geometry"]["t"]) == len(r["geometry"]["mi"])


def test_light_load_wind_band_is_severe_and_fastest_route_still_wins_on_equal_exposure(stubbed):
    data = _post(_body(load_weight_lb=20_000)).json()
    # 45 mph with a light load is Severe on every route (all cross the band)
    for r in data["routes"]:
        assert r["summary"]["severe_miles"] > 0
        assert r["summary"]["no_travel_miles"] == 0
    assert data["recommendation"]["route_id"] in {"A", "B", "C"}


def test_heavy_load_turns_wind_band_into_no_travel_and_warns(stubbed):
    data = _post(_body(load_weight_lb=35_000)).json()
    for r in data["routes"]:
        assert r["summary"]["no_travel_miles"] > 0
        assert r["summary"]["severe_miles"] == 0
    cp = next(c for c in data["routes"][0]["checkpoints"] if c["risk"]["level"] == "no_travel")
    assert "30,000" in cp["risk"]["load_rule"]
    assert "No Travel" in data["recommendation"]["warnings"][0]


def test_hos_toggle_changes_trip_time_not_drive_time(stubbed):
    with_hos = _post(_body(hos_breaks=True)).json()["routes"][0]
    without = _post(_body(hos_breaks=False)).json()["routes"][0]
    assert with_hos["drive_s"] == without["drive_s"]
    assert with_hos["trip_s"] == with_hos["drive_s"] + 1800  # 9 h drive -> one 30-min break
    assert without["trip_s"] == without["drive_s"]
    assert [s["kind"] for s in with_hos["stops"]] == ["break"]


@pytest.mark.parametrize(
    "overrides, field",
    [
        ({"load_weight_lb": -1}, "load_weight_lb"),
        ({"load_weight_lb": 500_000}, "load_weight_lb"),
        ({"interval_miles": 15}, "interval_miles"),
        ({"departure_time": "2020-01-01T00:00:00Z"}, "departure_time"),
        ({"departure_time": (datetime.now(timezone.utc) + timedelta(days=9)).isoformat()}, "departure_time"),
        ({"origin": {"label": ""}}, "origin"),
    ],
)
def test_validation_errors(stubbed, overrides, field):
    resp = _post(_body(**overrides))
    assert resp.status_code == 400
    assert field in resp.json()["error"]["fields"]


def test_heatmap_frames_cover_48_hours_with_load_aware_risk(stubbed):
    route = [[-100.0 + k / 10, 40.0] for k in range(101)]  # [lon, lat], crosses the wind band
    body = {
        "departure_time": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        "load_weight_lb": 35_000,
        "routes": [route],
    }
    resp = Client().post("/api/heatmap", data=json.dumps(body), content_type="application/json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["hours"] == 49
    n_cells = len(data["grid"]["cells"])
    assert 0 < n_cells <= 150
    for key in ("risk", "wind", "rain", "snow"):
        assert len(data["frames"][key]) == 49
        assert all(len(frame) == n_cells for frame in data["frames"][key])
    # 45 mph + 35,000 lb -> No Travel inside the band, Low outside
    assert set(data["frames"]["risk"][0]) == {0, 4}


def test_heatmap_rejects_bad_coordinates(stubbed):
    body = {"departure_time": datetime.now(timezone.utc).isoformat(), "load_weight_lb": 1, "routes": [[[500, 40], [1, 2]]]}
    resp = Client().post("/api/heatmap", data=json.dumps(body), content_type="application/json")
    assert resp.status_code == 400


def test_rules_endpoint():
    data = Client().get("/api/rules").json()
    assert data["conditions"]["wind"]["bounds"] == [25.0, 35.0, 45.0, 55.0]
    assert data["ranking_criteria"][1] == "Severe miles"


def test_straight_line_helper():
    assert len(straight_line((0, 0), (1, 1), 5)) == 5
