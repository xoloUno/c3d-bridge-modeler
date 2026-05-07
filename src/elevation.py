"""Bridge elevation chain (pure math).

Computes the vertical chain from top-of-deck down to top-of-footing
for one girder at one support. All inputs and outputs are in feet
(C3D US bridge convention). The caller is responsible for converting
any AISC-table inputs from inches to feet using `src/units.py`
helpers before passing them in.

Pure-logic module: must not import anything from the Civil 3D API
(`clr`, `Autodesk.*`). Importable on macOS for unit testing.

Sign conventions
----------------
- `crown_offset` is signed (+ = right of alignment).
- Girder offsets are signed (+ = right of alignment).
- `cross_slope_left_pct` and `cross_slope_right_pct` express elevation
  change per foot AWAY from the crown, in percent. Negative = downward
  away from crown (the typical crowned-roadway case).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SuperstructureElevations:
    """Vertical chain from deck top down to bearing seat, in feet."""
    top_of_deck: float
    top_of_girder_flange: float
    bottom_of_girder: float
    bearing_seat: float


@dataclass(frozen=True)
class SubstructureElevations:
    """Vertical chain from top of cap down to top of footing, in feet."""
    top_of_cap: float
    top_of_column: float
    top_of_footing: float
    column_height: float


def top_of_deck_at_offset(
    profile_elevation: float,
    deck_profile_offset: float,
    crown_offset: float,
    cross_slope_left_pct: float,
    cross_slope_right_pct: float,
    girder_offset: float,
) -> float:
    """Top-of-deck elevation at a given alignment offset, accounting for crown."""
    distance_from_crown = girder_offset - crown_offset
    if distance_from_crown >= 0.0:
        slope_pct = cross_slope_right_pct
    else:
        slope_pct = cross_slope_left_pct
    elevation_offset = (slope_pct / 100.0) * abs(distance_from_crown)
    return profile_elevation + deck_profile_offset + elevation_offset


def superstructure_elevations(
    top_of_deck: float,
    deck_depth: float,
    haunch_depth: float,
    girder_depth: float,
    bearing_device_height: float,
) -> SuperstructureElevations:
    """Chain from a known top-of-deck down to bearing seat."""
    top_of_girder_flange = top_of_deck - deck_depth - haunch_depth
    bottom_of_girder = top_of_girder_flange - girder_depth
    bearing_seat = bottom_of_girder - bearing_device_height
    return SuperstructureElevations(
        top_of_deck=top_of_deck,
        top_of_girder_flange=top_of_girder_flange,
        bottom_of_girder=bottom_of_girder,
        bearing_seat=bearing_seat,
    )


def top_of_footing(
    fg_surface_elevation: float,
    min_depth_below_fg: float,
    specified_top_of_footing: Optional[float] = None,
) -> float:
    """User override wins if provided; otherwise derive from FG and minimum cover."""
    if specified_top_of_footing is not None:
        return specified_top_of_footing
    return fg_surface_elevation - min_depth_below_fg


def substructure_elevations(
    bearing_seat: float,
    pedestal_height: float,
    cap_depth: float,
    fg_surface_elevation: float,
    min_depth_below_fg: float,
    specified_top_of_footing: Optional[float] = None,
) -> SubstructureElevations:
    """Chain from a known bearing-seat elevation down to top of footing."""
    top_of_cap = bearing_seat - pedestal_height
    top_of_column = top_of_cap - cap_depth
    tof = top_of_footing(
        fg_surface_elevation=fg_surface_elevation,
        min_depth_below_fg=min_depth_below_fg,
        specified_top_of_footing=specified_top_of_footing,
    )
    column_height = top_of_column - tof
    return SubstructureElevations(
        top_of_cap=top_of_cap,
        top_of_column=top_of_column,
        top_of_footing=tof,
        column_height=column_height,
    )
