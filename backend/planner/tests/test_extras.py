"""Extra features: crosswind (informational) and best departure time."""

import pytest

from planner.domain import departure
from planner.domain.crosswind import bearing_deg, compass, heading_at, relative_wind
from planner.domain.geo import cumulative_miles
from planner.domain.recommend import RouteScore
from planner.domain.risk import RiskLevel as R
from planner.services.weather import HOUR, HourlySeries, _lerp_angle

from .helpers import straight_line


# ---- crosswind -------------------------------------------------------------
def test_bearings():
    assert bearing_deg((40, -100), (41, -100)) == pytest.approx(0, abs=0.01)
    assert bearing_deg((40, -100), (40, -99)) == pytest.approx(90, abs=0.5)
    assert bearing_deg((40, -100), (39, -100)) == pytest.approx(180, abs=0.01)
    assert compass(91) == "E" and compass(350) == "N" and compass(225) == "SW"


def test_heading_along_route():
    coords = straight_line((40.0, -100.0), (40.0, -95.0), 30)  # due east
    assert heading_at(coords, cumulative_miles(coords), 100) == pytest.approx(90, abs=1)


@pytest.mark.parametrize(
    "wind_from, relation, cross, head",
    [
        (90, "headwind", 0.0, 30.0),  # eastbound truck, wind from the east
        (270, "tailwind", 0.0, -30.0),
        (0, "crosswind", 30.0, 0.0),  # wind from the north, fully across
        (180, "crosswind", 30.0, 0.0),
    ],
)
def test_relative_wind_components(wind_from, relation, cross, head):
    r = relative_wind(30, 40, wind_from, heading=90)
    assert r["relation"] == relation
    assert r["crosswind_mph"] == pytest.approx(cross, abs=0.1)
    assert r["headwind_mph"] == pytest.approx(head, abs=0.1)


def test_strong_crosswind_flag_uses_gust_component():
    assert relative_wind(20, 35, 0, 90)["strong"] is True  # 35 mph gusts fully across
    assert relative_wind(20, 35, 90, 90)["strong"] is False  # same gusts head-on


def test_wind_direction_interpolates_across_north():
    assert _lerp_angle(350, 10, 0.5) % 360 == pytest.approx(0)
    s = HourlySeries(start=0, wind=(10.0, 10.0), gust=(10.0, 10.0), rain=(0.0, 0.0), snow=(0.0, 0.0),
                     temp=(50.0, 50.0), code=(0, 0), wdir=(350.0, 10.0))
    assert s.sample_at(HOUR / 2).wind_dir_deg == 0
    no_dir = HourlySeries(start=0, wind=(10.0,), gust=(10.0,), rain=(0.0,), snow=(0.0,), temp=(50.0,), code=(0,))
    assert no_dir.sample_at(0).wind_dir_deg is None


# ---- best departure ----------------------------------------------------------
def _score(rid, *, nt=0, severe=0, high=0, avg=0.0, hours=10.0):
    return RouteScore(rid, f"Route {rid}", {R.NO_TRAVEL: nt, R.SEVERE: severe, R.HIGH: high}, avg, hours * HOUR)


def test_no_suggestion_when_leaving_now_is_already_clear():
    options = departure.evaluate(lambda shift: [_score("A"), _score("B", hours=11)])
    best, reason = departure.suggest(options)
    assert best is None and reason is None
    assert [o.shift_h for o in options] == list(departure.DEFAULT_SHIFTS_H)


def test_suggests_the_earliest_departure_that_clears_the_storm():
    def scorer(shift_s):
        h = shift_s / HOUR
        storm_miles = max(0, 150 - 25 * h)  # the storm clears over ~6 hours
        return [_score("A", nt=storm_miles, avg=storm_miles / 100), _score("B", severe=storm_miles, hours=11)]

    best, reason = departure.suggest(departure.evaluate(scorer))
    assert best.shift_h == 6
    assert best.best.route_id == "A"  # at +6 h both are clear and A is faster
    # leaving now the best option is B (150 Severe beats A's 150 No Travel)
    assert reason == "Leave 6 h later on Route A: Severe 150 → 0 mi."


def test_picks_earliest_clear_departure_even_if_later_ones_have_lower_average_risk():
    def scorer(shift_s):
        h = shift_s / HOUR
        severe = 100 if h < 4 else 0
        return [_score("A", severe=severe, avg=1.0 if h < 4 else 0.3 - h / 100)]

    best, reason = departure.suggest(departure.evaluate(scorer))
    assert best.shift_h == 4
    assert reason == "Leave 4 h later on Route A: Severe 100 → 0 mi."


def test_average_risk_alone_never_triggers_a_suggestion():
    def scorer(shift_s):
        return [_score("A", high=5, avg=0.4 if shift_s == 0 else 0.1)]

    assert departure.suggest(departure.evaluate(scorer)) == (None, None)
