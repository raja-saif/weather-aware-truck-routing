"""Best departure time (extra feature).

The spec's rules and ranking are applied unchanged; this module only asks the
same question for later departures. For each candidate delay the routes are
re-scored with weather at their new ETAs and the best route is chosen with
:func:`recommend.rank`.

Across departures, waiting itself is a cost, so the advisor picks the
*earliest* departure that reaches the fewest No Travel, then Severe, then High
miles. Average risk alone never justifies waiting. A later departure is only
suggested when it strictly improves one of those three mile counts.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Sequence

from .recommend import CRITERIA, RouteScore, deciding_criterion, rank

HOUR = 3600
DEFAULT_SHIFTS_H = tuple(range(0, 25, 2))  # leave now, +2 h, ... +24 h
MILE_CRITERIA = [c for c in CRITERIA if c.key in ("no_travel_miles", "severe_miles", "high_miles")]


@dataclass(frozen=True)
class DepartureOption:
    shift_h: int
    best: RouteScore  # best route for this departure (trip_s = its own trip time)

    @property
    def arrival_offset_s(self) -> float:
        return self.shift_h * HOUR + self.best.trip_s


def evaluate(
    score_routes: Callable[[float], Sequence[RouteScore]], shifts_h: Sequence[int] = DEFAULT_SHIFTS_H
) -> list[DepartureOption]:
    """``score_routes(shift_s)`` returns every route's score when leaving ``shift_s`` later."""
    return [DepartureOption(h, rank(score_routes(h * HOUR))[0]) for h in shifts_h]


def suggest(options: Sequence[DepartureOption]) -> tuple[DepartureOption | None, str | None]:
    """Earliest departure with the fewest risk miles, if it beats leaving now."""
    now = options[0]
    # Compare departures on risk miles only, then arrival time (avg risk deliberately ignored).
    keyed = [replace(o.best, avg_risk=0.0, trip_s=o.arrival_offset_s) for o in options]
    winner = options[keyed.index(rank(keyed)[0])]
    if winner.shift_h == 0:
        return None, None
    criterion, sign = deciding_criterion(keyed[options.index(winner)], keyed[0])
    if criterion is None or sign >= 0 or criterion not in MILE_CRITERIA:
        return None, None
    changes = [
        f"{c.label.replace(' miles', '')} {c.value(now.best):.0f} → {c.value(winner.best):.0f} mi"
        for c in MILE_CRITERIA
        if abs(c.value(now.best) - c.value(winner.best)) > 0.5
    ]
    reason = f"Leave {winner.shift_h} h later on {winner.best.name}: " + ", ".join(changes) + "."
    return winner, reason
