"""Test helpers: polyline encoding and synthetic provider payloads."""

from planner.domain.geo import Coord


def encode_polyline(coords: list[Coord], precision: int = 6) -> str:
    factor = 10**precision
    out, prev_lat, prev_lon = [], 0, 0
    for lat, lon in coords:
        ilat, ilon = round(lat * factor), round(lon * factor)
        for delta in (ilat - prev_lat, ilon - prev_lon):
            v = ~(delta << 1) if delta < 0 else delta << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        prev_lat, prev_lon = ilat, ilon
    return "".join(out)


def straight_line(start: Coord, end: Coord, n: int = 50) -> list[Coord]:
    return [
        (start[0] + (end[0] - start[0]) * k / (n - 1), start[1] + (end[1] - start[1]) * k / (n - 1))
        for k in range(n)
    ]


def valhalla_trip(coords: list[Coord], seconds: float) -> dict:
    half = len(coords) // 2
    return {
        "legs": [
            {
                "shape": encode_polyline(coords),
                "maneuvers": [
                    {"begin_shape_index": 0, "end_shape_index": half, "time": seconds / 2, "length": 0},
                    {"begin_shape_index": half, "end_shape_index": len(coords) - 1, "time": seconds / 2, "length": 0},
                    {"begin_shape_index": len(coords) - 1, "end_shape_index": len(coords) - 1, "time": 0, "length": 0},
                ],
            }
        ],
        "summary": {"time": seconds},
    }
