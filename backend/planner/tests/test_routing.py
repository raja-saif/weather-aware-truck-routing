import json

import pytest
import responses
from django.core.cache import cache
from django.test import override_settings

from planner.api.errors import PlanningError
from planner.domain import geo
from planner.services import routing

from .helpers import encode_polyline, straight_line, valhalla_trip

VALHALLA = "https://valhalla.test/route"
OSRM = "https://osrm.test/route/v1/driving"
ORIGIN, DEST = (40.0, -100.0), (40.0, -95.0)  # ~265 miles due east


@pytest.fixture(autouse=True)
def _settings():
    cache.clear()
    with override_settings(VALHALLA_URL=VALHALLA, OSRM_URL=OSRM):
        yield


def _arc(bulge: float) -> list:
    """A west->east line bowed north/south by ``bulge`` degrees (distinct corridors)."""
    out = []
    for k in range(60):
        t = k / 59
        out.append((40.0 + bulge * 4 * t * (1 - t), -100.0 + 5 * t))
    return out


def test_polyline_helper_roundtrip():
    pts = [(40.123456, -100.654321), (40.2, -99.9)]
    assert geo.decode_polyline(encode_polyline(pts)) == pts


def test_maneuver_time_is_distributed_by_distance():
    shape = [(0.0, 0.0), (0.0, 1.0), (0.0, 3.0)]  # second segment twice as long
    times = routing._distribute_maneuver_times(shape, [{"begin_shape_index": 0, "end_shape_index": 2, "time": 300}])
    assert times == pytest.approx([0, 100, 300])


@responses.activate
def test_valhalla_three_alternates_are_used_directly():
    trips = [valhalla_trip(_arc(b), 4 * 3600 + i * 600) for i, b in enumerate((0.0, 1.0, -1.0))]
    responses.post(VALHALLA, json={"trip": trips[0], "alternates": [{"trip": t} for t in trips[1:]]})
    routes, notes = routing.get_routes(ORIGIN, DEST, load_lb=40_000)
    assert len(routes) == 3 and notes == []
    assert [r.provider for r in routes] == ["valhalla-truck"] * 3
    assert routes[0].drive_s < routes[1].drive_s < routes[2].drive_s
    body = json.loads(responses.calls[0].request.body)
    assert body["costing"] == "truck"
    assert body["costing_options"]["truck"]["weight"] == pytest.approx((40_000 + 35_000) * 0.000453592, abs=0.01)
    assert body["alternates"] == 2


@responses.activate
def test_missing_alternates_are_generated_with_via_points():
    responses.post(VALHALLA, json={"trip": valhalla_trip(_arc(0.0), 4 * 3600)})  # primary only

    def via_callback(request):
        via = json.loads(request.body)["locations"][1]
        bulge = 1.2 if via["lat"] > 40 else -1.2
        return 200, {}, json.dumps({"trip": valhalla_trip(_arc(bulge), 4.5 * 3600)})

    responses.add_callback(responses.POST, VALHALLA, callback=via_callback)
    routes, _ = routing.get_routes(ORIGIN, DEST, load_lb=20_000)
    assert len(routes) == 3
    assert routes[0].via is None and all(r.via for r in routes[1:])
    via_body = json.loads(responses.calls[1].request.body)
    assert via_body["locations"][1]["type"] == "through"
    assert via_body["locations"][1]["search_filter"] == {"min_road_class": "primary"}


@responses.activate
def test_valhalla_distance_limit_falls_back_to_osrm():
    responses.post(VALHALLA, status=400, json={"error_code": 154, "error": "Path distance exceeds the max distance limit"})
    osrm_routes = []
    for b in (0.0, 1.0, -1.0):
        coords = _arc(b)
        osrm_routes.append(
            {"geometry": encode_polyline(coords), "legs": [{"annotation": {"duration": [10.0] * (len(coords) - 1)}}]}
        )
    responses.get(f"{OSRM}/-100.000000,40.000000;-95.000000,40.000000", json={"code": "Ok", "routes": osrm_routes})
    routes, notes = routing.get_routes(ORIGIN, DEST, load_lb=20_000)
    assert len(routes) == 3
    assert routes[0].provider == "osrm-car-capped"
    assert "930 miles" in notes[0]
    # car timings (10 s per ~4.5 mi segment) must be slowed to the 65 mph truck cap
    assert routes[0].miles / (routes[0].drive_s / 3600) == pytest.approx(65, abs=0.5)


@responses.activate
def test_no_route_is_a_planning_error():
    responses.post(VALHALLA, status=400, json={"error_code": 442, "error": "No path could be found"})
    with pytest.raises(PlanningError) as exc:
        routing.get_routes(ORIGIN, DEST, load_lb=20_000)
    assert exc.value.code == "no_route"


def test_same_location_rejected():
    with pytest.raises(PlanningError):
        routing.get_routes(ORIGIN, (40.001, -100.001), load_lb=1)


def test_backtrack_detects_out_and_back_spur():
    out = straight_line((40.0, -100.0), (40.0, -99.0), 40)
    spur = straight_line((40.0, -99.0), (40.3, -99.0), 20)
    back = list(reversed(spur))[1:]
    rest = straight_line((40.0, -99.0), (40.0, -98.0), 40)[1:]
    coords = out + spur[1:] + back + rest
    assert routing.backtrack_fraction(coords, geo.cumulative_miles(coords)) > routing.MAX_BACKTRACK
    clean = out + rest
    assert routing.backtrack_fraction(clean, geo.cumulative_miles(clean)) == 0


def test_via_points_are_offset_to_both_sides():
    base = routing.RawRoute(coords=_arc(0.0), cum_drive_s=[i * 60.0 for i in range(60)], provider="x")
    vias = routing.via_points(ORIGIN, DEST, base)
    assert len(vias) == len(routing.VIA_CANDIDATES)
    assert vias[0][0] > 40 > vias[1][0]  # +offset is north (left of an eastbound trip)
