import pytest

from planner.domain.risk import (
    RiskLevel as R,
    WeatherSample,
    assess,
    classify_rain,
    classify_snow,
    classify_wind,
    classify_wind_base,
)


@pytest.mark.parametrize(
    "mph, expected",
    [
        (0, R.LOW), (24.9, R.LOW), (25, R.MODERATE), (34.9, R.MODERATE),
        (35, R.HIGH), (44.9, R.HIGH), (45, R.SEVERE), (54.9, R.SEVERE),
        (55, R.NO_TRAVEL), (80, R.NO_TRAVEL),
    ],
)
def test_wind_table(mph, expected):
    assert classify_wind_base(mph) == expected


@pytest.mark.parametrize(
    "inches, expected",
    [
        (0, R.LOW), (0.099, R.LOW), (0.10, R.MODERATE), (0.249, R.MODERATE),
        (0.25, R.HIGH), (0.499, R.HIGH), (0.50, R.SEVERE), (1.00, R.SEVERE),
        (1.001, R.NO_TRAVEL),
    ],
)
def test_rain_table(inches, expected):
    assert classify_rain(inches) == expected


@pytest.mark.parametrize(
    "inches, expected",
    [
        (0, R.LOW), (0.49, R.LOW), (0.5, R.MODERATE), (0.99, R.MODERATE),
        (1.0, R.HIGH), (1.99, R.HIGH), (2.0, R.SEVERE), (3.0, R.SEVERE),
        (3.01, R.NO_TRAVEL),
    ],
)
def test_snow_table(inches, expected):
    assert classify_snow(inches) == expected


@pytest.mark.parametrize(
    "mph, load, expected, rule_fired",
    [
        # >= 55 mph: No Travel for any load
        (55, 0, R.NO_TRAVEL, False),
        (60, 80_000, R.NO_TRAVEL, False),
        # 45-54 mph: No Travel only when load strictly > 30,000 lb
        (45, 30_000, R.SEVERE, False),
        (45, 30_001, R.NO_TRAVEL, True),
        (54.9, 45_000, R.NO_TRAVEL, True),
        # 35-44 mph: Severe only when load strictly > 40,000 lb
        (35, 40_000, R.HIGH, False),
        (35, 40_001, R.SEVERE, True),
        (44.9, 35_000, R.HIGH, False),  # 30k-40k: the 35-44 mph rule does not apply
        # below 35 mph: load never matters
        (34.9, 80_000, R.MODERATE, False),
    ],
)
def test_load_rules(mph, load, expected, rule_fired):
    level, note = classify_wind(mph, load)
    assert level == expected
    assert (note is not None) == rule_fired


def test_overall_is_worst_condition_and_reports_drivers():
    result = assess(WeatherSample(wind_mph=30, rain_in_hr=0.3, snow_in_hr=0), load_lb=10_000)
    assert result.level == R.HIGH
    assert result.drivers == ("rain",)
    assert result.load_rule is None


def test_load_rule_reported_when_it_drives_overall_level():
    result = assess(WeatherSample(wind_mph=40, rain_in_hr=0.0, snow_in_hr=0.6), load_lb=42_000)
    assert result.level == R.SEVERE
    assert result.drivers == ("wind",)
    assert "40,000" in result.load_rule


def test_ties_list_every_driver():
    result = assess(WeatherSample(wind_mph=36, rain_in_hr=0.3, snow_in_hr=1.2), load_lb=0)
    assert result.level == R.HIGH
    assert result.drivers == ("wind", "rain", "snow")


def test_calm_weather_is_low_with_no_drivers():
    result = assess(WeatherSample(wind_mph=5, rain_in_hr=0, snow_in_hr=0), load_lb=80_000)
    assert result.level == R.LOW
    assert result.drivers == ()
    assert result.to_dict()["label"] == "Low"
