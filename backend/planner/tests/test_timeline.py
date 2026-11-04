import pytest

from planner.domain.timeline import HOUR, HosPolicy, Timeline, cap_speed

HOS = HosPolicy()
NO_HOS = HosPolicy(enabled=False)


@pytest.mark.parametrize(
    "drive_h, wall_h",
    [
        (0, 0),
        (5, 5),
        (8, 8),  # arriving at the 8h mark: break not taken yet
        (8.5, 9.0),  # 30-min break after 8h
        (11, 11.5),  # end of first shift, rest not yet taken
        (12, 12 + 0.5 + 10),  # one completed shift: break + 10h rest
        (19, 19 + 0.5 + 10),  # 8h into shift 2 exactly
        (20, 20 + 0.5 + 10 + 0.5),
        (23, 23 + 2 * (0.5 + 10)),  # two completed shifts, then 1h into the third
    ],
)
def test_hos_wall_offset(drive_h, wall_h):
    assert HOS.wall_offset(drive_h * HOUR) == pytest.approx(wall_h * HOUR)


def test_hos_disabled_is_identity():
    assert NO_HOS.wall_offset(30 * HOUR) == 30 * HOUR
    assert NO_HOS.stops(30 * HOUR) == []


def test_hos_stops_sequence():
    stops = HOS.stops(25 * HOUR)
    assert [(s.kind, s.drive_s / HOUR) for s in stops] == [
        ("break", 8), ("rest", 11), ("break", 19), ("rest", 22),
    ]
    # each stop starts at the wall offset of its drive position
    assert stops[1].start_offset_s == pytest.approx(11.5 * HOUR)
    assert stops[2].start_offset_s == pytest.approx((19 + 10.5) * HOUR)


def test_no_rest_when_arriving_exactly_at_shift_limit():
    assert [s.kind for s in HOS.stops(11 * HOUR)] == ["break"]
    assert HOS.stops(8 * HOUR) == []


def test_wall_offset_is_monotonic():
    prev = -1.0
    for minutes in range(0, 60 * 60, 7):
        cur = HOS.wall_offset(minutes * 60)
        assert cur >= prev
        prev = cur


def test_timeline_interpolates_distance_to_time():
    # 600 miles at a constant 60 mph = 10 h of driving
    tl = Timeline([0, 300, 600], [0, 5 * HOUR, 10 * HOUR], HOS)
    assert tl.drive_at(150) == pytest.approx(2.5 * HOUR)
    assert tl.offset_at(540) == pytest.approx(9.5 * HOUR)  # 9h driving + 30min break
    assert tl.trip_s == pytest.approx(10.5 * HOUR)
    assert tl.miles_at_drive(8 * HOUR) == pytest.approx(480)


def test_cap_speed_slows_fast_segments_only():
    # 65 mi in 30 min (130 mph) is capped to 1 h; 30 mi in 1 h is untouched
    out = cap_speed([0, 65, 95], [0, 0.5 * HOUR, 1.5 * HOUR], max_mph=65)
    assert out == pytest.approx([0, HOUR, 2 * HOUR])
