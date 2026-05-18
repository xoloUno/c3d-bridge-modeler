"""Haunch swept-solid creation on `BRIDGE-DECK-HAUNCH`.

Civil-3D-only. Will not import on macOS.

The haunch is the concrete pad between the top of the girder's top
flange and the underside of the deck slab. In Phase 1 baseline it is
modeled as a 4-vertex trapezoid (per-bearing-line `h_left` / `h_right`
from `phase1_compute`) and swept along the same 3D path used by the
girder solid — same orientation strategy (`Align=NoAlignment`,
`Bank=False`), same anchor at `(start_x, start_y, top_of_girder_flange)`.

Constant-profile sweep approximation
------------------------------------
For a girder fully on one side of the deck crown and constant cross-
slope, `h_left` and `h_right` are constant along the girder (because
cross-slope is linear; the delta between flange-centerline and tip
doesn't depend on absolute offset). So the Phase 1 baseline sweeps a
single profile (computed from the START bearing's dims) along the
3D path.

Edge cases deferred to a later slice:
- Girder straddles the crown (left and right tips use different
  cross-slope sides)
- Station-varying `crown_offset` / `deck_cl_offset_from_alignment`
  produces materially different `h_left` / `h_right` at start vs end
  — would need `Solid3d.CreateLoftedSolid` between distinct profiles.

For now the start-profile assumption is documented and verified via
unit tests in `test/test_phase1_compute.py`.

Re-run contract
---------------
Solid geometry regenerates each run (per CLAUDE.md). This module
deletes every ModelSpace entity on `BRIDGE-DECK-HAUNCH` at the start
of `ensure_phase1_haunches` and rebuilds them from scratch.

See `src/girders.py` for the IDisposable / pythonnet-quirk notes that
apply identically here.
"""
from __future__ import annotations

import math
from typing import List, Tuple

import clr

clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.DatabaseServices import (  # noqa: E402
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
import haunch_geometry as hg
import layers
import units
import xdata


LAYER_HAUNCH = "BRIDGE-DECK-HAUNCH"
_COLOR_HAUNCH = 51  # per templates/README.md

XDATA_APP = "BRIDGE_MODELER"


class HaunchError(RuntimeError):
    pass


def ensure_phase1_haunches(
    tr,
    db,
    alignment_obj,
    params,
    compute_result,
    aisc_table,
) -> dict:
    """Regenerate haunch swept solids on `BRIDGE-DECK-HAUNCH`.

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

        # Flange width: same shape for every girder in a span (per the
        # Phase 1 Superstructure schema), so derive once per span.
        shape = aisc.get(aisc_table, span.girder_shape)
        bf_ft = units.in_to_ft(shape.bf_in)

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

            # Constant-profile baseline: use the start-bearing haunch
            # dims. For the typical Phase 1 case this exactly matches
            # the end-bearing dims; for crown-straddling or station-
            # varying-offset bridges it's an approximation pending a
            # lofted-solid upgrade.
            solid = _build_haunch_solid(
                bf_ft=bf_ft,
                h_left_ft=girder.start.haunch_h_left_ft,
                h_right_ft=girder.start.haunch_h_right_ft,
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
    bf_ft: float,
    h_left_ft: float,
    h_right_ft: float,
    start_xyz,
    end_xyz,
):
    """Sweep a 4-vertex haunch profile from start_xyz to end_xyz.

    Same orientation strategy as `girders._build_girder_solid` —
    profile pre-rotated into a vertical plane perpendicular to the
    in-plan girder direction, anchored at start_xyz, swept along a
    sloped 3D Line with `Align=NoAlignment` + `Bank=False`.
    """
    start_x, start_y, start_z = start_xyz
    end_x, end_y, end_z = end_xyz

    dx = end_x - start_x
    dy = end_y - start_y
    plan_len = math.hypot(dx, dy)
    if plan_len <= 0.0:
        raise HaunchError(
            f"haunch endpoints coincide in plan view "
            f"(start_xy={start_xyz[:2]}, end_xy={end_xyz[:2]}); "
            f"can't determine girder direction"
        )
    girder_xy = Vector3d(dx / plan_len, dy / plan_len, 0.0)
    cross_xy = Vector3d(-dy / plan_len, dx / plan_len, 0.0)

    verts = hg.haunch_profile_vertices_ft(bf_ft, h_left_ft, h_right_ft)

    pline = None
    curves = None
    regions_dboc = None
    region = None
    path = None
    try:
        pline = Polyline()
        for i, (u, v) in enumerate(verts):
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
                f"Region.CreateFromCurves returned no regions for haunch "
                f"profile (bf={bf_ft}, h_left={h_left_ft}, h_right={h_right_ft})"
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
