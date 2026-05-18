"""Pure-math helpers for steel girder cross-section geometry.

Builds the 2D outline of an AISC W-shape I-beam in profile-local
coordinates, ready for the Civil-3D-side code to extrude / sweep into
a 3D solid.

Coordinate convention
---------------------
The profile lives in a 2D plane with axes `(u, v)`:

    v
    │
    │     ┌─────────┐       ← v = 0 (top of top flange)
    │     │         │       ← v = -tf
    │     │  ┌───┐  │
    │     │  │   │  │       (web, x = ±tw/2)
    │     │  │   │  │
    │     │  └───┘  │       ← v = -(d - tf)
    │     │         │
    │     └─────────┘       ← v = -d  (bottom of bottom flange)
    │     ↑         ↑
    │   u=-bf/2   u=+bf/2
    └──────────────────── u

`v = 0` lines up with the AISC top-of-flange elevation produced by the
elevation chain (`top_of_girder_flange` from `elevation.py`), so the
Civil-3D-side caller can place the profile origin directly at world
`(start_x, start_y, top_of_girder_flange_z)` without further offset.

Units
-----
AISC W-shape dimensions are stored in inches (their native published
unit) so the JSON table can be spot-checked against the printed Manual.
This module returns vertices in **feet** to match the rest of the
drawing-side toolchain — US bridge DWGs are typically in decimal feet,
and downstream `Solid3d` calls consume world coordinates.

Pure-logic module: must not import anything from the Civil 3D API
(`clr`, `Autodesk.*`). Importable on macOS for unit testing.
"""
from __future__ import annotations

from typing import Tuple

import aisc
import units


Vertex = Tuple[float, float]


def i_shape_profile_vertices_ft(shape: aisc.WShape) -> Tuple[Vertex, ...]:
    """Return the closed I-shape outline as 12 `(u, v)` vertices in feet.

    The vertices trace the outline clockwise starting at the top-left
    corner of the top flange. The closing segment (V12 → V0) is implicit
    — the caller marks the polyline as closed when materializing it.

    The 12 corners are::

        V0 ─── V1
        │       │
        V11    V2
            │
            ... web ...
            │
        V10    V3
        │       │
        V9     V4
        │       │
        V8 ─── V5  ← actually V6/V7 between; see code below

    See module docstring for axes and units. `tw_in` is the web
    thickness; `tf_in` the flange thickness; `bf_in` the flange width;
    `d_in` the overall depth.
    """
    bf = units.in_to_ft(shape.bf_in)
    tf = units.in_to_ft(shape.tf_in)
    tw = units.in_to_ft(shape.tw_in)
    d = units.in_to_ft(shape.d_in)

    if tf <= 0.0 or tw <= 0.0 or bf <= 0.0 or d <= 0.0:
        raise ValueError(
            f"W-shape {shape.designation!r} has non-positive dim(s): "
            f"bf={bf} tf={tf} tw={tw} d={d} (all in ft after in→ft)"
        )
    if 2.0 * tf >= d:
        raise ValueError(
            f"W-shape {shape.designation!r}: 2*tf ({2*tf:.4f} ft) >= d "
            f"({d:.4f} ft); top + bottom flanges would meet/overlap"
        )
    if tw >= bf:
        raise ValueError(
            f"W-shape {shape.designation!r}: tw ({tw:.4f} ft) >= bf "
            f"({bf:.4f} ft); web would be wider than the flanges"
        )

    half_bf = bf / 2.0
    half_tw = tw / 2.0
    v_top_flange_bottom = -tf
    v_bot_flange_top = -(d - tf)
    v_bottom = -d

    return (
        (-half_bf, 0.0),                       # 0: top-left of top flange
        (+half_bf, 0.0),                       # 1: top-right of top flange
        (+half_bf, v_top_flange_bottom),       # 2: bottom-right of top flange
        (+half_tw, v_top_flange_bottom),       # 3: top of web on the right
        (+half_tw, v_bot_flange_top),          # 4: bottom of web on the right
        (+half_bf, v_bot_flange_top),          # 5: top-right of bottom flange
        (+half_bf, v_bottom),                  # 6: bottom-right of bottom flange
        (-half_bf, v_bottom),                  # 7: bottom-left of bottom flange
        (-half_bf, v_bot_flange_top),          # 8: top-left of bottom flange
        (-half_tw, v_bot_flange_top),          # 9: bottom of web on the left
        (-half_tw, v_top_flange_bottom),       # 10: top of web on the left
        (-half_bf, v_top_flange_bottom),       # 11: bottom-left of top flange
    )
