import pytest

from planner.domain import geo
from planner.domain.risk import RiskLevel, WeatherSample, assess
from planner.domain.scenario import HOUR, Storm

from .helpers import straight_line

CALM = WeatherSample(wind_mph=8, rain_in_hr=0.0, snow_in_hr=0.0, gust_mph=12, temperature_f=50)
T0 = 1_800_000_000


def storm():
    return Storm(lat=40.0, lon=-100.0, t0=T0, v_north_mph=0, v_east_mph=14)


def test_core_is_severe_and_no_travel_for_heavy_loads():
    s = storm().apply(CALM, (40.0, -100.0), T0)
    assert s.wind_mph == pytest.approx(56.0)
    assert assess(s, 10_000).level == RiskLevel.NO_TRAVEL  # >= 55 mph for any load
    edge = storm().apply(CALM, geo.point_at([(40.0, -100.0), (40.0, -97.0)], [0, geo.haversine_mi((40, -100), (40, -97))], 60), T0)
    assert 35 <= edge.wind_mph < 55


def test_intensity_decays_with_distance_and_storm_drifts_east():
    st = storm()
    assert st.intensity((40.0, -100.0), T0) == pytest.approx(1.0)
    assert st.intensity((40.0, -97.0), T0) == pytest.approx(0.12, abs=0.01)  # ~159 mi away
    assert st.intensity((40.0, -96.0), T0) < 0.03  # ~212 mi away
    later = st.centre(T0 + 10 * HOUR)
    assert later[1] > -100.0 and later[0] == pytest.approx(40.0)


def test_far_points_are_untouched():
    assert storm().apply(CALM, (45.0, -80.0), T0) is CALM


def test_cold_air_turns_precip_to_snow():
    cold = WeatherSample(wind_mph=5, rain_in_hr=0, snow_in_hr=0, temperature_f=28)
    s = storm().apply(cold, (40.0, -100.0), T0)
    assert s.rain_in_hr == 0 and s.snow_in_hr == pytest.approx(2.6)


def test_meeting_route_targets_midpoint_at_arrival_time():
    coords = straight_line((40.0, -100.0), (40.0, -90.0), 50)
    cum = geo.cumulative_miles(coords)
    st = Storm.meeting_route(coords, cum, meet_offset_s=5 * HOUR, departure_ts=T0)
    assert st.lon == pytest.approx(-95.0, abs=0.01)
    assert st.t0 == T0 + 5 * HOUR
