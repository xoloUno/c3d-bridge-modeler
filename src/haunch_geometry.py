"""Pure-math helpers for haunch cross-section geometry.

The haunch is the concrete pad between the top of the steel girder's
top flange and the underside of the deck slab. In Phase 1 baseline it
is modeled as a 4-vertex trapezoid (the ideal hexagonal-with-chamfers
shape from the project memory is deferred to a later slice).

Coordinate convention
---------------------
The profile lives in a 2D plane with axes `(u, v)`:

    v
    │     /───\\        ← top, sloped from (-bf/2, h_left) to (+bf/2, h_right)
    │    /     \\
    │   ┌───────┐       ← v = 0  (bottom; sits on top of girder top flange)
    │   ↑       ↑
    │ u=-bf/2  u=+bf/2
    └──────────────────── u

`v = 0` lines up with the top of the girder's top flange — same datum
as the girder profile's `v = 0`, so the haunch and the girder share an
identical 3D anchor at `(start_x, start_y, top_of_girder_flange_z)`.
The Civil-3D-side caller is responsible for that anchor.

`h_left` and `h_right` are the haunch heights at the left and right
flange tips. For a girder fully on one side of the deck crown and
constant cross-slope, both are constant along the girder, so a single
swept solid (constant profile along the path) is accurate. For girders
that straddle the crown — or for bridges with station-varying
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
) -> Tuple[Vertex, ...]:
    """Return the closed 4-vertex haunch outline in `(u, v)` feet.

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

    half_bf = bf_ft / 2.0
    return (
        (-half_bf, 0.0),         # 0: bottom-left, on top of girder flange
        (+half_bf, 0.0),         # 1: bottom-right, on top of girder flange
        (+half_bf, h_right_ft),  # 2: top-right, under deck bottom
        (-half_bf, h_left_ft),   # 3: top-left, under deck bottom
    )
