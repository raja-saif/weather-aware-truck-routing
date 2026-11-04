"""Truck timeline: converts distance along a route into estimated arrival times.

Driving time comes from the routing provider (per-vertex cumulative seconds).
On top of that, an optional simplified FMCSA Hours-of-Service model inserts
mandatory stops, because a long-haul truck cannot drive straight through and
weather must be sampled at the time the truck *actually* reaches a checkpoint:

* a 30-minute break once 8 hours of driving have accumulated in a shift
* a 10-hour off-duty rest after 11 hours of driving (the shift limit)

Assumptions (documented in the README): the driver starts with a fresh clock,
and pickup, drop-off and fuel stops are not modelled.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from typing import Sequence

HOUR = 3600.0


@dataclass(frozen=True)
class HosPolicy:
    enabled: bool = True
    drive_before_break_s: float = 8 * HOUR
    break_s: float = 0.5 * HOUR
    shift_drive_s: float = 11 * HOUR
    rest_s: float = 10 * HOUR

    def wall_offset(self, drive_s: float) -> float:
        """Seconds since departure at which ``drive_s`` seconds of driving are completed.

        Stops that start exactly at ``drive_s`` are not yet included (the truck
        has just arrived there).
        """
        if not self.enabled or drive_s <= 0:
            return max(drive_s, 0.0)
        shifts_done = math.ceil(drive_s / self.shift_drive_s) - 1
        into_shift = drive_s - shifts_done * self.shift_drive_s
        offset = drive_s + shifts_done * (self.break_s + self.rest_s)
        if into_shift > self.drive_before_break_s:
            offset += self.break_s
        return offset

    def stops(self, total_drive_s: float) -> list["Stop"]:
        """Mandatory stops taken strictly before arrival."""
        if not self.enabled:
            return []
        out: list[Stop] = []
        shift = 0
        while True:
            base = shift * self.shift_drive_s
            brk = base + self.drive_before_break_s
            rest = base + self.shift_drive_s
            if brk >= total_drive_s:
                break
            out.append(Stop("break", brk, self.wall_offset(brk), self.break_s))
            if rest >= total_drive_s:
                break
            out.append(Stop("rest", rest, self.wall_offset(rest), self.rest_s))
            shift += 1
        return out


@dataclass(frozen=True)
class Stop:
    kind: str  # "break" (30 min) or "rest" (10 h)
    drive_s: float  # driving time completed when the stop starts
    start_offset_s: float  # wall-clock seconds since departure when the stop starts
    duration_s: float


class Timeline:
    """Maps miles along a route to driving time and wall-clock offset."""

    def __init__(self, cum_miles: Sequence[float], cum_drive_s: Sequence[float], hos: HosPolicy):
        if len(cum_miles) != len(cum_drive_s) or len(cum_miles) < 2:
            raise ValueError("timeline needs matching arrays with at least two vertices")
        self.cum_miles = list(cum_miles)
        self.cum_drive_s = list(cum_drive_s)
        self.hos = hos

    @property
    def total_miles(self) -> float:
        return self.cum_miles[-1]

    @property
    def drive_s(self) -> float:
        return self.cum_drive_s[-1]

    @property
    def trip_s(self) -> float:
        return self.hos.wall_offset(self.drive_s)

    def drive_at(self, miles: float) -> float:
        return _interp(self.cum_miles, self.cum_drive_s, miles)

    def miles_at_drive(self, drive_s: float) -> float:
        return _interp(self.cum_drive_s, self.cum_miles, drive_s)

    def offset_at(self, miles: float) -> float:
        """Wall-clock seconds after departure when the truck reaches ``miles``."""
        return self.hos.wall_offset(self.drive_at(miles))

    def stops(self) -> list[Stop]:
        return self.hos.stops(self.drive_s)


def _interp(xs: Sequence[float], ys: Sequence[float], x: float) -> float:
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect_right(xs, x) - 1
    # skip zero-length steps (duplicate x) by moving to the last equal index
    span = xs[i + 1] - xs[i]
    if span <= 0:
        return ys[i + 1]
    return ys[i] + (ys[i + 1] - ys[i]) * (x - xs[i]) / span


def cap_speed(cum_miles: Sequence[float], cum_drive_s: Sequence[float], max_mph: float) -> list[float]:
    """Re-time a car-profile route so no segment is driven faster than ``max_mph``."""
    out = [0.0]
    for i in range(1, len(cum_miles)):
        seg_mi = cum_miles[i] - cum_miles[i - 1]
        seg_s = max(cum_drive_s[i] - cum_drive_s[i - 1], 0.0)
        out.append(out[-1] + max(seg_s, seg_mi / max_mph * HOUR))
    return out
