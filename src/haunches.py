"""Haunch swept-and-trimmed solid creation on `BRIDGE-DECK-HAUNCH`.

Civil-3D-only. Will not import on macOS.

The haunch is the concrete pad between the top of the girder's top
flange and the underside of the deck slab. We model it in two steps
to guarantee its top precisely follows the deck soffit:

  1. Build an **over-tall rectangular box** along each girder: bf
     wide (flange width), `haunch_depth + 0.5 × deck_depth` tall,
     swept along the same 3D path as the girder, with the same
     `Align=NoAlignment` + `Bank=False` orientation. The box's top
     sits ABOVE the design deck soffit but BELOW the design deck
     top — i.e., the box "stabs into" the deck slab.
  2. **Boolean-subtract the deck** (a fat-deck cutter equivalent to
     the deck slab in plan footprint, but using the cheap pre-trim
     sweep so we don't depend on the actual deck Solid3d's lifecycle)
     from the over-tall box. The subtract removes the portion of
     the haunch that overlaps the deck — i.e., everything ABOVE the
     deck soffit. What's left is the haunch from top-of-flange up
     to deck soffit, with the top surface matching the deck soffit
     exactly.

Why this is better than a constant-trapezoid sweep
--------------------------------------------------
The prior implementation built a 4-vertex trapezoid cross-section
with `h_left` / `h_right` derived from the elevation chain at the
flange tips. That solved the design intent on the girder's own
cross-section (perpendicular to the fanning girder), but in alignment-
perpendicular sections it picked up a small longitudinal-grade
contribution from the oblique cut (the left and right top edges of
the haunch were at different t-fractions along the girder when the
section plane crossed them). For Erik's ±10° asymmetric bridge that
came out at 2.09% / 1.9% in alignment-perpendicular sections, vs.
the design 2.0%.

The boolean-trim approach forces the haunch top to coincide with the
deck soffit at every point in the plan — by construction. The
remaining slope deviation drops from ~0.09% to ~0.008% (just the
projection of bf onto alignment-perpendicular under a small fan
angle), which is negligible and geometrically unavoidable without
breaking girder-flange alignment.

Re-run contract
---------------
Solid geometry regenerates each run. This module wipes every
ModelSpace entity on `BRIDGE-DECK-HAUNCH` at the start of
`ensure_phase1_haunches` and rebuilds them from scratch.

See `src/girders.py` for the IDisposable / pythonnet-quirk notes
that apply identically here.
"""
from __future__ import annotations

import math
from typing import Callable, List, Tuple

import clr

clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.DatabaseServices import (  # noqa: E402
    BooleanOperationType,
    DBObjectCollection,
    Line,
    OpenMode,
    Polyline,
    Region,
    Solid3d,
    SweepOptionsAlignOption,
    SweepOptionsBuilder,
    SymbolUtilityServices,
)
from Autodesk.AutoCAD.Geometry import (  # noqa: E402
    Matrix3d,
    Point2d,
    Point3d,
    Vector3d,
)

import aisc
import alignment as al
import decks
import layers
import units
import xdata


LAYER_HAUNCH = "BRIDGE-DECK-HAUNCH"
_COLOR_HAUNCH = 51  # per templates/README.md

XDATA_APP = "BRIDGE_MODELER"

# Over-tall fudge for the rectangular haunch box. Computed per-haunch as
# `haunch_depth + _OVERTALL_RATIO × deck_depth`, which:
#   - guarantees the box's top sits ABOVE the deck soffit (allowing
#     the boolean trim to do its work), and
#   - keeps the top BELOW the deck top so no extra material survives
#     above the deck after the subtract.
_OVERTALL_RATIO = 0.5


class HaunchError(RuntimeError):
    pass


def ensure_phase1_haunches(
    tr,
    db,
    alignment_obj,
    params,
    compute_result,
    aisc_table,
    profile_elevation_at: Callable[[float], float],
) -> dict:
    """Regenerate haunch solids on `BRIDGE-DECK-HAUNCH`.

    Returns `{"created": [(element_id, oid), ...], "purged": N}`.
    Solid geometry regenerates each run; any prior entities on
    `BRIDGE-DECK-HAUNCH` are erased first.
    """
    print("[haunches] entering ensure_phase1_haunches")
    layers.ensure_layer(tr, db, LAYER_HAUNCH, color=_COLOR_HAUNCH)
    xdata.ensure_regapp(tr, db, XDATA_APP)

    purged = _purge_haunch_layer(tr, db)
    if purged:
        print(f"[haunches] purged {purged} prior entit{'y' if purged == 1 else 'ies'} on {LAYER_HAUNCH}")

    supports_by_id = {s.support_id: s for s in params.supports}
    created: List[Tuple[str, object]] = []

    for span in compute_result.spans:
        start_support = supports_by_id[span.start_support_id]
        end_support = supports_by_id[span.end_support_id]
        shape = aisc.get(aisc_table, span.girder_shape)
        bf_ft = units.in_to_ft(shape.bf_in)
        deck_depth_ft = span.deck_start.deck_depth
        # Haunch depth comes from the params (constant per superstructure
        # in Phase 1). We retrieve it via the per-girder `haunch_h_left_ft`
        # average — that field is haunch_depth ± cross-slope contribution,
        # so the average across the bridge is exactly haunch_depth.
        haunch_depth_ft = (
            span.girders[0].start.haunch_h_left_ft
            + span.girders[0].start.haunch_h_right_ft
        ) / 2.0
        over_tall_height_ft = haunch_depth_ft + _OVERTALL_RATIO * deck_depth_ft

        for girder in span.girders:
            element_id = f"{span.span_id}.G{girder.girder_index}.HAUNCH"

            start_xy = al.point_on_skewed_bearing(
                alignment_obj,
                girder.start.bearing_station,
                start_support.skew_angle,
                girder.start.girder_offset,
            )
            end_xy = al.point_on_skewed_bearing(
                alignment_obj,
                girder.end.bearing_station,
                end_support.skew_angle,
                girder.end.girder_offset,
            )

            start_xyz = (start_xy[0], start_xy[1], girder.start.top_of_girder_flange)
            end_xyz = (end_xy[0], end_xy[1], girder.end.top_of_girder_flange)

            solid = _build_haunch_solid(
                alignment_obj=alignment_obj,
                params=params,
                span=span,
                profile_elevation_at=profile_elevation_at,
                bf_ft=bf_ft,
                over_tall_height_ft=over_tall_height_ft,
                start_xyz=start_xyz,
                end_xyz=end_xyz,
            )
            try:
                ms_id = SymbolUtilityServices.GetBlockModelSpaceId(db)
                btr = tr.GetObject(ms_id, OpenMode.ForWrite)
                solid.Layer = LAYER_HAUNCH
                oid = btr.AppendEntity(solid)
                tr.AddNewlyCreatedDBObject(solid, True)
            except Exception:
                solid.Dispose()
                raise

            xdata.write(tr, oid, XDATA_APP, {
                "element": "haunch",
                "span_id": span.span_id,
                "girder_index": girder.girder_index,
                "id": element_id,
            })
            created.append((element_id, oid))
            print(f"[haunches]   built {element_id}")

    return {"created": created, "purged": purged}


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------

def _purge_haunch_layer(tr, db) -> int:
    """Erase every ModelSpace entity on `BRIDGE-DECK-HAUNCH`."""
    ms_id = SymbolUtilityServices.GetBlockModelSpaceId(db)
    btr = tr.GetObject(ms_id, OpenMode.ForWrite)
    count = 0
    for oid in btr:
        ent = tr.GetObject(oid, OpenMode.ForRead)
        if getattr(ent, "Layer", None) != LAYER_HAUNCH:
            continue
        ent.UpgradeOpen()
        ent.Erase()
        count += 1
    return count


def _build_haunch_solid(
    *,
    alignment_obj,
    params,
    span,
    profile_elevation_at: Callable[[float], float],
    bf_ft: float,
    over_tall_height_ft: float,
    start_xyz,
    end_xyz,
):
    """Build a final haunch solid: over-tall rectangular box minus the
    deck (= rectangular box clipped from above by the deck soffit)."""
    over_tall = None
    deck_cutter = None
    try:
        over_tall = _build_overtall_box(
            bf_ft=bf_ft,
            over_tall_height_ft=over_tall_height_ft,
            start_xyz=start_xyz,
            end_xyz=end_xyz,
        )
        deck_cutter = decks.build_fat_deck_cutter(
            alignment_obj=alignment_obj,
            params=params,
            span=span,
            profile_elevation_at=profile_elevation_at,
        )
        # `BooleanOperation` mutates `over_tall` to hold (over_tall − deck)
        # and consumes `deck_cutter` (its body is moved into the operation).
        # Disposing `deck_cutter` after is still required to free the
        # managed wrapper.
        try:
            over_tall.BooleanOperation(BooleanOperationType.BoolSubtract, deck_cutter)
        except Exception:
            raise

        # Hand ownership of the trimmed solid back to the caller.
        result = over_tall
        over_tall = None
        return result
    finally:
        if deck_cutter is not None:
            deck_cutter.Dispose()
        if over_tall is not None:
            over_tall.Dispose()


def _build_overtall_box(
    *,
    bf_ft: float,
    over_tall_height_ft: float,
    start_xyz,
    end_xyz,
):
    """Build a rectangular `bf × over_tall_height` swept prism along
    the girder path. The box's bottom sits on the top of the girder
    flange at v=0; its top is at v=over_tall_height (above the design
    deck soffit, intended to be trimmed by a subsequent boolean op).
    """
    start_x, start_y, start_z = start_xyz
    end_x, end_y, end_z = end_xyz

    dx = end_x - start_x
    dy = end_y - start_y
    plan_len = math.hypot(dx, dy)
    if plan_len <= 0.0:
        raise HaunchError(
            f"haunch endpoints coincide in plan view "
            f"(start_xy={start_xyz[:2]}, end_xy={end_xyz[:2]})"
        )
    girder_xy = Vector3d(dx / plan_len, dy / plan_len, 0.0)
    cross_xy = Vector3d(-dy / plan_len, dx / plan_len, 0.0)

    half_bf = bf_ft / 2.0
    # Rectangle in profile (u, v) coords. The same `cross_xy = 90°-CCW`
    # convention used by `girder_geometry` applies; for a symmetric
    # rectangle the alignment-left vs. -right assignment is moot.
    rect_verts = (
        (-half_bf, 0.0),                       # 0: bottom on alignment-RIGHT side
        (+half_bf, 0.0),                       # 1: bottom on alignment-LEFT side
        (+half_bf, over_tall_height_ft),       # 2: top on alignment-LEFT side
        (-half_bf, over_tall_height_ft),       # 3: top on alignment-RIGHT side
    )

    pline = None
    curves = None
    regions_dboc = None
    region = None
    path = None
    try:
        pline = Polyline()
        for i, (u, v) in enumerate(rect_verts):
            pline.AddVertexAt(i, Point2d(u, v), 0.0, 0.0, 0.0)
        pline.Closed = True

        xform = Matrix3d.AlignCoordinateSystem(
            Point3d(0.0, 0.0, 0.0),
            Vector3d.XAxis, Vector3d.YAxis, Vector3d.ZAxis,
            Point3d(start_x, start_y, start_z),
            cross_xy, Vector3d.ZAxis, girder_xy,
        )
        pline.TransformBy(xform)

        curves = DBObjectCollection()
        curves.Add(pline)
        regions_dboc = Region.CreateFromCurves(curves)
        if regions_dboc.Count == 0:
            raise HaunchError(
                "Region.CreateFromCurves returned no regions for haunch "
                "over-tall rectangular profile"
            )
        region = regions_dboc.get_Item(0)

        path = Line(
            Point3d(start_x, start_y, start_z),
            Point3d(end_x, end_y, end_z),
        )

        opts_builder = SweepOptionsBuilder()
        opts_builder.Align = SweepOptionsAlignOption.NoAlignment
        opts_builder.Bank = False
        opts_builder.TwistAngle = 0.0
        opts = opts_builder.ToSweepOptions()

        solid = Solid3d()
        try:
            solid.CreateSweptSolid(region, path, opts)
        except Exception:
            solid.Dispose()
            raise
        return solid
    finally:
        if path is not None:
            path.Dispose()
        if region is not None:
            region.Dispose()
        if regions_dboc is not None:
            regions_dboc.Dispose()
        if pline is not None:
            pline.Dispose()
        if curves is not None:
            curves.Dispose()
