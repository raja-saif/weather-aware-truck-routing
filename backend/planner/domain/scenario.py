"""Optional "demo storm" weather scenario (pure functions, no I/O).

Real forecasts are often calm, which leaves the risk rules, load rules and
ranking invisible in a demo. The storm scenario overlays a synthetic,
slowly-drifting storm on top of the *real* forecast so every part of the
pipeline can be exercised on demand. It is opt-in and clearly labelled in the
UI; live forecasts are always the default.

The storm is placed where the fastest route's truck would meet it mid-trip, so
the alternatives (which pass further away) are exposed to less of it, and the
recommendation logic has a real trade-off to make.

Intensity falls off with a Gaussian profile ``exp(-(d / radius)^2)``:

* wind  +48 mph and gusts +60 mph at the core (~50 mph: Severe; No Travel when load > 30,000 lb)
* precipitation +0.9 in/hr at the core, as rain above 34 F and as snow
  (+2.6 in/hr) at or below it
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from . import geo
from .geo import Coord
from .risk import WeatherSample

HOUR = 3600.0


@dataclass(frozen=True)
class Storm:
    lat: float  # centre at time ``t0``
    lon: float
    t0: float  # unix seconds
    v_north_mph: float
    v_east_mph: float
    radius_mi: float = 110.0
    wind_add_mph: float = 48.0
    gust_add_mph: float = 60.0
    rain_add_in: float = 0.9
    snow_add_in: float = 2.6

    @classmethod
    def meeting_route(cls, coords: list[Coord], cum_miles: list[float], meet_offset_s: float, departure_ts: float) -> "Storm":
        """Storm centred on the route's midpoint at the time the truck gets there, drifting east-northeast."""
        lat, lon = geo.point_at(coords, cum_miles, cum_miles[-1] / 2)
        return cls(lat=round(lat, 4), lon=round(lon, 4), t0=round(departure_ts + meet_offset_s), v_north_mph=6.0, v_east_mph=14.0)

    def centre(self, t: float) -> Coord:
        hours = (t - self.t0) / HOUR
        lat = self.lat + self.v_north_mph * hours / 69.172
        lon = self.lon + self.v_east_mph * hours / (69.172 * math.cos(math.radians(self.lat)))
        return (lat, lon)

    def intensity(self, p: Coord, t: float) -> float:
        d = geo.haversine_mi(p, self.centre(t))
        return math.exp(-((d / self.radius_mi) ** 2))

    def apply(self, sample: WeatherSample, p: Coord, t: float) -> WeatherSample:
        k = self.intensity(p, t)
        if k < 0.01:
            return sample
        cold = sample.temperature_f is not None and sample.temperature_f <= 34
        return WeatherSample(
            wind_mph=round(sample.wind_mph + self.wind_add_mph * k, 1),
            gust_mph=round((sample.gust_mph or sample.wind_mph) + self.gust_add_mph * k, 1),
            rain_in_hr=round(sample.rain_in_hr + (0 if cold else self.rain_add_in * k), 3),
            snow_in_hr=round(sample.snow_in_hr + (self.snow_add_in * k if cold else 0), 3),
            temperature_f=sample.temperature_f,
            weather_code=(73 if cold else 65) if k > 0.3 else sample.weather_code,
            wind_dir_deg=sample.wind_dir_deg,
        )

    def to_dict(self) -> dict:
        return asdict(self)
