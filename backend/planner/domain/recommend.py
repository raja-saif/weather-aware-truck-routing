"""Route ranking and recommendation (pure functions, no I/O).

Routes are compared lexicographically, exactly in the order the spec gives,
with one stricter tier in front:

0. Fewest No Travel miles   (No Travel is worse than Severe, so it ranks first)
1. Fewest Severe miles
2. Fewest High miles
3. Lowest average risk       (distance-weighted mean score, 0=Low .. 4=No Travel)
4. Shortest travel time      (door-to-door, including any HOS stops)

Mile comparisons ignore differences under 0.5 mi (float noise). Average risk
differences under 0.05 are treated as ties so that, when two routes are
equally safe in practice, travel time decides -- the "balance weather risk and
travel time" requirement.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cmp_to_key
from typing import Sequence

from .risk import RiskLevel

MILES_TOLERANCE = 0.5
AVG_RISK_TOLERANCE = 0.05


@dataclass(frozen=True)
class RouteScore:
    route_id: str
    name: str
    miles_by_level: dict[RiskLevel, float]
    avg_risk: float
    trip_s: float

    @property
    def no_travel_miles(self) -> float:
        return self.miles_by_level.get(RiskLevel.NO_TRAVEL, 0.0)

    @property
    def severe_miles(self) -> float:
        return self.miles_by_level.get(RiskLevel.SEVERE, 0.0)

    @property
    def high_miles(self) -> float:
        return self.miles_by_level.get(RiskLevel.HIGH, 0.0)


@dataclass(frozen=True)
class Criterion:
    key: str
    label: str
    tolerance: float

    def value(self, s: RouteScore) -> float:
        return getattr(s, self.key)


CRITERIA = (
    Criterion("no_travel_miles", "No Travel miles", MILES_TOLERANCE),
    Criterion("severe_miles", "Severe miles", MILES_TOLERANCE),
    Criterion("high_miles", "High miles", MILES_TOLERANCE),
    Criterion("avg_risk", "average risk", AVG_RISK_TOLERANCE),
    Criterion("trip_s", "travel time", 0.0),
)


def deciding_criterion(a: RouteScore, b: RouteScore) -> tuple[Criterion | None, int]:
    """First criterion separating ``a`` from ``b`` and the sign (-1: a better)."""
    for c in CRITERIA:
        diff = c.value(a) - c.value(b)
        if abs(diff) > c.tolerance:
            return c, -1 if diff < 0 else 1
    return None, 0


def rank(scores: Sequence[RouteScore]) -> list[RouteScore]:
    """Best first. Ties keep input order (stable sort)."""
    return sorted(scores, key=cmp_to_key(lambda a, b: deciding_criterion(a, b)[1]))


def _fmt_hours(seconds: float) -> str:
    minutes = round(abs(seconds) / 60)
    h, m = divmod(minutes, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


def explain(best: RouteScore, other: RouteScore) -> str:
    """One sentence on why ``best`` beats ``other``."""
    c, _ = deciding_criterion(best, other)
    if c is None:
        return f"{best.name} and {other.name} are equivalent on every criterion."
    if c.key == "trip_s":
        return (
            f"Same Severe and High exposure as {other.name} and similar average risk "
            f"({best.avg_risk:.2f} vs {other.avg_risk:.2f}), but {_fmt_hours(other.trip_s - best.trip_s)} faster."
        )
    if c.key == "avg_risk":
        return (
            f"Same Severe and High exposure as {other.name}, but lower average risk "
            f"({best.avg_risk:.2f} vs {other.avg_risk:.2f})."
        )
    return (
        f"{c.value(best):.0f} {c.label} vs {c.value(other):.0f} on {other.name}."
    )


def recommend(scores: Sequence[RouteScore]) -> dict:
    """Ranking plus a human-readable justification for the winner."""
    ordered = rank(scores)
    best = ordered[0]
    comparisons = []
    for other in ordered[1:]:
        c, _ = deciding_criterion(best, other)
        comparisons.append(
            {"route_id": other.route_id, "decided_by": c.key if c else None, "reason": explain(best, other)}
        )
    warnings = []
    if best.no_travel_miles > MILES_TOLERANCE:
        warnings.append(
            "Every route crosses No Travel conditions at this departure time. "
            "Consider delaying departure or waiting out the weather."
        )
    elif best.severe_miles > MILES_TOLERANCE:
        warnings.append("The recommended route still includes Severe weather miles. Drive with caution.")
    return {
        "route_id": best.route_id,
        "ranking": [s.route_id for s in ordered],
        "comparisons": comparisons,
        "warnings": warnings,
        "criteria": [c.label for c in CRITERIA],
    }
