"""Pure-math helpers for haunch cross-section geometry.

The haunch is the concrete pad between the top of the steel girder's
top flange and the underside of the deck slab. With no chamfer it is
a 4-vertex trapezoid. A positive `chamfer_ft` flares the top outer
corners outward, and the outline becomes a 6-vertex hexagon.

Coordinate convention
---------------------
The profile lives in a 2D plane with axes `(u, v)`:

    v
    │     /───\\        ← top, sloped from (+bf/2, h_left) to (-bf/2, h_right)
    │    /     \\
    │   ┌───────┐       ← v = 0  (bottom; sits on top of girder top flange)
    │   ↑       ↑
    │ u=-bf/2  u=+bf/2
    └──────────────────── u

`v = 0` lines up with the top of the girder's top flange — same datum
as the girder profile's `v = 0`, so the haunch and the girder share an
identical 3D anchor at `(start_x, start_y, top_of_girder_flange_z)`.
The Civil-3D-side caller is responsible for that anchor.

Profile-`u` vs alignment-side mapping
-------------------------------------
`h_left_ft` and `h_right_ft` refer to the haunch height on the
**alignment-LEFT** and **alignment-RIGHT** sides of the girder (in
Civil 3D's convention: `+perp_offset = right of alignment looking
ahead-station`).

The Civil-3D-side caller transforms the profile via `Matrix3d.Align-
CoordinateSystem` with the profile's local X (=`u`) mapped onto
`cross_xy = 90° CCW(girder_direction)` — and CCW from the
ahead-station girder direction lands on alignment-LEFT (negative
`perp_offset`). So profile `+u` ends up on alignment-LEFT, and `-u`
on alignment-RIGHT.

To make the placement match the engineer-facing `h_left` / `h_right`
naming, this builder puts `h_left_ft` at `(+bf/2, h_left_ft)` and
`h_right_ft` at `(-bf/2, h_right_ft)` — opposite of what
"left = negative u" intuition might suggest. The cross-slope direction
of the haunch top therefore matches the deck soffit cross-slope.

(Phase 1's asymmetric-haunch trapezoid was the first thing that
exposed this convention; the symmetric I-shape girder profile in
`girder_geometry.py` was unaffected by it, since the I-shape is
left-right mirror-symmetric.)

Chamfer
-------
`chamfer_ft` is the leg length of an equal-leg 45° fillet added
outside each top corner (a concrete fillet for formwork release).
The spec gives one size and no angle, so both legs are that size:

- vertical faces stay on `u = ±bf/2` from the flange (`v = 0`) up to
  `side_height - chamfer_ft`
- each fillet then runs outward and upward with `Δu = Δv = chamfer_ft`
- the outer top vertices sit one chamfer outside the flange edge, at
  the full side height: `(+bf/2 + chamfer, h_left)` and
  `(-bf/2 - chamfer, h_right)`
- the top edge joins those two vertices, so its slope is
  `(h_left - h_right) / (bf + 2·chamfer)`

`chamfer_ft == 0` skips the fillet vertices and returns the original
4-tuple. A chamfer must be `>= 0` and strictly less than both
`h_left_ft` and `h_right_ft`; otherwise the vertical face on that
side disappears or drops through the flange.

The swept solid in `haunches.py` does not consume this outline yet.
It still sweeps an over-tall rectangle and trims it with the deck.

Constant-profile assumption
---------------------------
For a girder fully on one side of the deck crown and constant cross-
slope, both `h_left` and `h_right` are constant along the girder, so a
single swept solid (constant profile along the path) is accurate. For
girders that straddle the crown — or for bridges with station-varying
`crown_offset` / `deck_cl_offset_from_alignment` — a lofted solid
between distinct start / end profiles would be more accurate; that's
deferred to a later slice.

Units
-----
All inputs and outputs are in feet (matching the drawing-side
convention). The caller is responsible for converting AISC `bf_in`
via `units.in_to_ft` before calling.

Pure-logic module: must not import anything from the Civil 3D API
(`clr`, `Autodesk.*`). Importable on macOS for unit testing.
"""
from __future__ import annotations

from typing import Tuple


Vertex = Tuple[float, float]


def haunch_profile_vertices_ft(
    bf_ft: float,
    h_left_ft: float,
    h_right_ft: float,
    chamfer_ft: float = 0.0,
) -> Tuple[Vertex, ...]:
    """Return the closed haunch outline in `(u, v)` feet.

    `chamfer_ft == 0` (the default) returns the 4-vertex trapezoid.
    `chamfer_ft > 0` returns a 6-vertex hexagon whose top is wider than
    the flange by `2 * chamfer_ft`. See the module docstring for the
    45° fillet placement.

    Vertices trace clockwise starting at the bottom-left, so the
    Civil-3D-side polyline winding matches the girder profile builder
    (`girder_geometry.i_shape_profile_vertices_ft`).
    """
    if bf_ft <= 0.0:
        raise ValueError(f"bf_ft must be > 0; got {bf_ft}")
    if h_left_ft <= 0.0:
        raise ValueError(
            f"h_left_ft must be > 0; got {h_left_ft}. A non-positive haunch "
            f"height means the deck bottom is at or below the girder top "
            f"flange — geometry would self-intersect."
        )
    if h_right_ft <= 0.0:
        raise ValueError(
            f"h_right_ft must be > 0; got {h_right_ft}. A non-positive haunch "
            f"height means the deck bottom is at or below the girder top "
            f"flange — geometry would self-intersect."
        )
    if chamfer_ft < 0.0:
        raise ValueError(f"chamfer_ft must be >= 0; got {chamfer_ft}")
    if chamfer_ft >= h_left_ft or chamfer_ft >= h_right_ft:
        raise ValueError(
            f"chamfer_ft ({chamfer_ft}) does not fit in the haunch height on "
            f"either side (h_left_ft={h_left_ft}, h_right_ft={h_right_ft}); "
            f"chamfer must be < the height on each side"
        )

    half_bf = bf_ft / 2.0
    # See module docstring: profile +u maps to alignment-LEFT after the
    # Civil-3D-side Matrix3d transform (cross_xy is 90° CCW from girder
    # direction), so h_left_ft goes at +bf/2 and h_right_ft at -bf/2.
    if chamfer_ft == 0.0:
        return (
            (-half_bf, 0.0),         # 0: bottom on alignment-RIGHT side
            (+half_bf, 0.0),         # 1: bottom on alignment-LEFT side
            (+half_bf, h_left_ft),   # 2: top on alignment-LEFT side
            (-half_bf, h_right_ft),  # 3: top on alignment-RIGHT side
        )
    return (
        (-half_bf, 0.0),                              # bottom, alignment-RIGHT
        (+half_bf, 0.0),                              # bottom, alignment-LEFT
        (+half_bf, h_left_ft - chamfer_ft),           # left vertical face ends
        (+half_bf + chamfer_ft, h_left_ft),           # outer top, alignment-LEFT
        (-half_bf - chamfer_ft, h_right_ft),          # outer top, alignment-RIGHT
        (-half_bf, h_right_ft - chamfer_ft),          # right vertical face ends
    )
