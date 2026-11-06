"""Weather risk classification (pure functions, no I/O).

Implements the assessment's risk table and load rules exactly. The table gives
ranges such as "25-34 mph" / "35-44 mph" whose shared edges are ambiguous for
continuous forecast values, so every band is interpreted as half-open
``[lower, upper)`` -- the lower bound belongs to the band. The two explicit
exceptions in the spec are honoured: precipitation "No Travel" starts strictly
*above* its bound (">1.00" in/hr rain, ">3.0" in/hr snow), so exactly 1.00 /
3.0 is still Severe.

Load rules escalate the *wind* classification only:

* wind >= 55 mph                     -> No Travel for any load (already the base table)
* 45-54 mph and load > 30,000 lb     -> No Travel
* 35-44 mph and load > 40,000 lb     -> Severe

The checkpoint's overall level is the worst of wind (after load rules), rain
and snow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class RiskLevel(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def key(self) -> str:
        return self.name.lower()


_LABELS = {
    RiskLevel.LOW: "Low",
    RiskLevel.MODERATE: "Moderate",
    RiskLevel.HIGH: "High",
    RiskLevel.SEVERE: "Severe",
    RiskLevel.NO_TRAVEL: "No Travel",
}

# Lower bounds of Moderate, High, Severe, No Travel.
WIND_MPH_BOUNDS = (25.0, 35.0, 45.0, 55.0)
RAIN_IN_HR_BOUNDS = (0.10, 0.25, 0.50, 1.00)
SNOW_IN_HR_BOUNDS = (0.5, 1.0, 2.0, 3.0)

LOAD_NO_TRAVEL_WIND_LB = 30_000  # 45-54 mph + load > this -> No Travel
LOAD_SEVERE_WIND_LB = 40_000  # 35-44 mph + load > this -> Severe


def _band(value: float, bounds: tuple[float, float, float, float], *, strict_top: bool) -> RiskLevel:
    """Map a value onto Low..No Travel using lower bounds ``bounds``.

    With ``strict_top`` the No Travel band starts strictly above ``bounds[3]``.
    """
    moderate, high, severe, no_travel = bounds
    if (value > no_travel) if strict_top else (value >= no_travel):
        return RiskLevel.NO_TRAVEL
    if value >= severe:
        return RiskLevel.SEVERE
    if value >= high:
        return RiskLevel.HIGH
    if value >= moderate:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def classify_wind_base(wind_mph: float) -> RiskLevel:
    return _band(wind_mph, WIND_MPH_BOUNDS, strict_top=False)


def classify_rain(rain_in_hr: float) -> RiskLevel:
    return _band(rain_in_hr, RAIN_IN_HR_BOUNDS, strict_top=True)


def classify_snow(snow_in_hr: float) -> RiskLevel:
    return _band(snow_in_hr, SNOW_IN_HR_BOUNDS, strict_top=True)


def classify_wind(wind_mph: float, load_lb: float) -> tuple[RiskLevel, str | None]:
    """Wind level after load rules, plus a human-readable note when a load rule fired."""
    base = classify_wind_base(wind_mph)
    if base == RiskLevel.SEVERE and load_lb > LOAD_NO_TRAVEL_WIND_LB:
        return RiskLevel.NO_TRAVEL, (
            f"45-54 mph wind with load over {LOAD_NO_TRAVEL_WIND_LB:,} lb: Severe escalated to No Travel"
        )
    if base == RiskLevel.HIGH and load_lb > LOAD_SEVERE_WIND_LB:
        return RiskLevel.SEVERE, (
            f"35-44 mph wind with load over {LOAD_SEVERE_WIND_LB:,} lb: High escalated to Severe"
        )
    return base, None


@dataclass(frozen=True)
class WeatherSample:
    """Weather at one place and time, in the units the risk table uses."""

    wind_mph: float
    rain_in_hr: float
    snow_in_hr: float
    gust_mph: float | None = None
    temperature_f: float | None = None
    weather_code: int | None = None
    wind_dir_deg: float | None = None  # direction the wind blows FROM (informational)

    def to_dict(self) -> dict:
        return {
            "wind_mph": self.wind_mph,
            "gust_mph": self.gust_mph,
            "rain_in_hr": self.rain_in_hr,
            "snow_in_hr": self.snow_in_hr,
            "temperature_f": self.temperature_f,
            "weather_code": self.weather_code,
            "wind_dir_deg": self.wind_dir_deg,
        }


@dataclass(frozen=True)
class RiskAssessment:
    level: RiskLevel
    wind: RiskLevel
    rain: RiskLevel
    snow: RiskLevel
    drivers: tuple[str, ...] = field(default_factory=tuple)  # conditions at the overall level
    load_rule: str | None = None

    def to_dict(self) -> dict:
        return {
            "level": self.level.key,
            "score": int(self.level),
            "label": self.level.label,
            "by_condition": {"wind": self.wind.key, "rain": self.rain.key, "snow": self.snow.key},
            "drivers": list(self.drivers),
            "load_rule": self.load_rule,
        }


def assess(sample: WeatherSample, load_lb: float) -> RiskAssessment:
    wind, load_rule = classify_wind(sample.wind_mph, load_lb)
    rain = classify_rain(sample.rain_in_hr)
    snow = classify_snow(sample.snow_in_hr)
    overall = max(wind, rain, snow)
    drivers: tuple[str, ...] = ()
    if overall > RiskLevel.LOW:
        drivers = tuple(
            name for name, lvl in (("wind", wind), ("rain", rain), ("snow", snow)) if lvl == overall
        )
    return RiskAssessment(
        level=overall,
        wind=wind,
        rain=rain,
        snow=snow,
        drivers=drivers,
        load_rule=load_rule if wind == overall else None,
    )


def rules_table() -> dict:
    """Machine-readable copy of the rules, served to the UI for legends."""
    return {
        "levels": [{"key": lvl.key, "label": lvl.label, "score": int(lvl)} for lvl in RiskLevel],
        "conditions": {
            "wind": {"unit": "mph", "bounds": list(WIND_MPH_BOUNDS), "no_travel_inclusive": True},
            "rain": {"unit": "in/hr", "bounds": list(RAIN_IN_HR_BOUNDS), "no_travel_inclusive": False},
            "snow": {"unit": "in/hr", "bounds": list(SNOW_IN_HR_BOUNDS), "no_travel_inclusive": False},
        },
        "load_rules": [
            {"wind_min_mph": 55, "load_over_lb": 0, "result": "no_travel"},
            {"wind_min_mph": 45, "wind_below_mph": 55, "load_over_lb": LOAD_NO_TRAVEL_WIND_LB, "result": "no_travel"},
            {"wind_min_mph": 35, "wind_below_mph": 45, "load_over_lb": LOAD_SEVERE_WIND_LB, "result": "severe"},
        ],
    }
