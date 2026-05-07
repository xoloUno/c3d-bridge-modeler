"""Station-varying scalar profiles with linear interpolation.

Some bridge parameters (`crown_offset`, `deck_cl_offset_from_alignment`,
…) are constant for simple bridges but vary along the alignment for
complex ones (superelevation transitions, flared/widened decks, etc.).
Rather than forcing scalar-only or array-only, we accept either form
in the JSON and represent the result uniformly as a `StationProfile`.

JSON forms:

  Scalar:  `0.0`               # constant across the bridge envelope
  Array:   [{"station": s, "value": v}, ...]
                                # at least 2 entries, ascending by station,
                                # spans [begin_station, end_station]

Pure-logic module: must not import anything from the Civil 3D API
(`clr`, `Autodesk.*`). Importable on macOS for unit testing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple, Union


class StationProfileError(ValueError):
    pass


@dataclass(frozen=True)
class StationProfile:
    """Piecewise-linear scalar function of station.

    `points` is an ordered tuple of `(station, value)` pairs sorted by
    station. `at(s)` returns the linearly-interpolated value at station
    `s`; outside the range of the control points, the endpoint value is
    held flat (no extrapolation).
    """
    name: str
    points: Tuple[Tuple[float, float], ...]

    def at(self, station: float) -> float:
        if not self.points:
            raise StationProfileError(f"{self.name}: profile has no control points")

        if station <= self.points[0][0]:
            return self.points[0][1]
        if station >= self.points[-1][0]:
            return self.points[-1][1]

        for i in range(len(self.points) - 1):
            s0, v0 = self.points[i]
            s1, v1 = self.points[i + 1]
            if s0 <= station <= s1:
                if s1 == s0:  # coincident control points; honor the earlier value
                    return v0
                t = (station - s0) / (s1 - s0)
                return v0 + t * (v1 - v0)

        # Defensive — should be unreachable given the bracketing above
        raise StationProfileError(
            f"{self.name}: failed to bracket station {station} in profile {self.points}"
        )

    def is_effectively_constant_zero(self, tolerance: float = 1e-9) -> bool:
        """True iff every control point's value is within `tolerance` of zero.

        Used to decide whether a separate bridge-CL sub-alignment is worth
        creating: when `deck_cl_offset_from_alignment` is constant zero, the
        existing roadway alignment already serves as the deck centerline,
        so no extra alignment is needed.
        """
        return all(abs(v) <= tolerance for _s, v in self.points)


def parse(
    raw: Union[float, int, list],
    *,
    begin_station: float,
    end_station: float,
    name: str,
) -> StationProfile:
    """Parse a station-profile spec from JSON (scalar or array of points)."""
    if isinstance(raw, bool):
        # Booleans are ints in Python — reject explicitly so we don't silently
        # accept `true` / `false` as 1.0 / 0.0
        raise StationProfileError(f"{name}: boolean value not allowed")

    if isinstance(raw, (int, float)):
        v = float(raw)
        return StationProfile(
            name=name,
            points=((begin_station, v), (end_station, v)),
        )

    if isinstance(raw, list):
        if len(raw) < 2:
            raise StationProfileError(
                f"{name}: array form must have at least 2 entries"
            )
        points = []
        for i, entry in enumerate(raw):
            if not isinstance(entry, dict):
                raise StationProfileError(
                    f"{name}[{i}] must be an object {{'station': ..., 'value': ...}}"
                )
            for key in ("station", "value"):
                if key not in entry:
                    raise StationProfileError(f"{name}[{i}] missing {key!r}")
            s = float(entry["station"])
            v = float(entry["value"])
            points.append((s, v))

        for i in range(len(points) - 1):
            if points[i][0] >= points[i + 1][0]:
                raise StationProfileError(
                    f"{name}: stations must be strictly ascending "
                    f"(violation at index {i}: {points[i][0]} >= {points[i+1][0]})"
                )
        if points[0][0] > begin_station:
            raise StationProfileError(
                f"{name}: first control point station {points[0][0]} "
                f"is past begin_station {begin_station} — must cover bridge envelope"
            )
        if points[-1][0] < end_station:
            raise StationProfileError(
                f"{name}: last control point station {points[-1][0]} "
                f"is before end_station {end_station} — must cover bridge envelope"
            )
        return StationProfile(name=name, points=tuple(points))

    raise StationProfileError(
        f"{name}: must be a number (constant) or list of "
        f"{{station, value}} entries; got {type(raw).__name__}"
    )
