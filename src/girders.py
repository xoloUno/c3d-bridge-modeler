"""Steel girder swept-solid creation on `BRIDGE-GIRDER`.

Civil-3D-only. Will not import on macOS.

The I-shape cross-section is built in profile-local coordinates by
`src/girder_geometry.py` (pure math), then materialized here as an
AutoCAD `Polyline` → `Region` → `Solid3d` via `CreateSweptSolid`.

Orientation strategy (`Bank=False`)
-----------------------------------
For a graded bridge, real fabricated girders have **plumb webs** — the
web stays vertical from end to end, and the top and bottom flange edges
follow the grade as parallel slanted lines. To get that geometry from
a single sweep call, we pre-orient the profile in world space:

  - Profile X-axis (`u`, horizontal across web)  → `cross_xy`
    (horizontal direction perpendicular to girder in plan, +90° CCW
    from the girder direction)
  - Profile Y-axis (`v`, vertical)                → world +Z
  - Profile Z-axis (normal)                       → `girder_xy`
    (horizontal direction along girder in plan)

…and use `SweepOptions.Align = NoAlignment` so the sweep does NOT
re-rotate the profile to be perpendicular to the (sloped) path. With
the profile fixed in this vertical orientation, the path's slope is
realized only as a *translation*: top and bottom flange edges of the
swept solid become the sloped lines we want, and the web stays plumb.

`Bank=False` (called out in CLAUDE.md) is also set explicitly for
clarity; for the straight 3D `Line` paths used in Phase 1 it has no
effect (banking only kicks in on curved paths), but stays meaningful
when Phase 2 introduces curved girders.

Re-run contract
---------------
Per the two-mode workflow documented in CLAUDE.md, solid geometry
regenerates on each run while skeleton elements are preserved. This
module deletes every ModelSpace entity on `BRIDGE-GIRDER` at the start
of `ensure_phase1_girders` and rebuilds them from scratch. The
companion skeleton layer is `BRIDGE-SKELETON-GIRDER` (different layer)
and is NOT touched.

IDisposable cleanup
-------------------
`Polyline`, `Region`, `Line`, `DBObjectCollection`, and (on creation
failure) `Solid3d` are all .NET IDisposable. Per the pythonnet-3 quirk
documented in CLAUDE.md, `with` statements around these types misroute
`__exit__` to `OnExit(int)` during exception unwinding. We use explicit
`try / finally` with `.Dispose()` calls instead.
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
import girder_geometry as gg
import layers
import xdata


LAYER_GIRDER = "BRIDGE-GIRDER"
_COLOR_GIRDER = 1  # red, per templates/README.md

XDATA_APP = "BRIDGE_MODELER"


class GirderError(RuntimeError):
    pass


def ensure_phase1_girders(
    tr,
    db,
    alignment_obj,
    params,
    compute_result,
    aisc_table,
) -> dict:
    """Regenerate steel girder swept solids on `BRIDGE-GIRDER`.

    Returns `{"created": [(element_id, oid), ...], "purged": N}`.
    Solid geometry regenerates each run; any prior entities on
    `BRIDGE-GIRDER` are erased first.
    """
    print("[girders] entering ensure_phase1_girders")
    layers.ensure_layer(tr, db, LAYER_GIRDER, color=_COLOR_GIRDER)
    xdata.ensure_regapp(tr, db, XDATA_APP)

    purged = _purge_girder_layer(tr, db)
    if purged:
        print(f"[girders] purged {purged} prior entit{'y' if purged == 1 else 'ies'} on {LAYER_GIRDER}")

    supports_by_id = {s.support_id: s for s in params.supports}
    created: List[Tuple[str, object]] = []

    for span in compute_result.spans:
        start_support = supports_by_id[span.start_support_id]
        end_support = supports_by_id[span.end_support_id]
        shape = aisc.get(aisc_table, span.girder_shape)

        for girder in span.girders:
            element_id = f"{span.span_id}.G{girder.girder_index}"

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

            solid = _build_girder_solid(shape, start_xyz, end_xyz)
            try:
                ms_id = SymbolUtilityServices.GetBlockModelSpaceId(db)
                btr = tr.GetObject(ms_id, OpenMode.ForWrite)
                solid.Layer = LAYER_GIRDER
                oid = btr.AppendEntity(solid)
                tr.AddNewlyCreatedDBObject(solid, True)
            except Exception:
                solid.Dispose()
                raise

            xdata.write(tr, oid, XDATA_APP, {
                "element": "girder",
                "span_id": span.span_id,
                "girder_index": girder.girder_index,
                "girder_shape": span.girder_shape,
                "id": element_id,
            })
            created.append((element_id, oid))
            print(f"[girders]   built {element_id} ({span.girder_shape})")

    return {"created": created, "purged": purged}


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------

def _purge_girder_layer(tr, db) -> int:
    """Erase every ModelSpace entity on `BRIDGE-GIRDER`.

    Solid geometry is regenerated each run (CLAUDE.md re-run contract);
    we own this layer, so a wholesale wipe is the simplest policy.
    Skeleton sub-alignments live on `BRIDGE-SKELETON-GIRDER` (different
    layer) and are NOT affected.

    DATA-LOSS SURFACE: this also erases any non-tool entity a user
    placed on `BRIDGE-GIRDER` (e.g. copied solids, manual annotations),
    and is unsafe for multi-bridge drawings — both bridges share the
    layer. Tighten to xdata-filtered + bridge-id-scoped purge before
    enabling multi-bridge drawings.
    """
    ms_id = SymbolUtilityServices.GetBlockModelSpaceId(db)
    btr = tr.GetObject(ms_id, OpenMode.ForWrite)
    count = 0
    for oid in btr:
        ent = tr.GetObject(oid, OpenMode.ForRead)
        if getattr(ent, "Layer", None) != LAYER_GIRDER:
            continue
        ent.UpgradeOpen()
        ent.Erase()
        count += 1
    return count


def _build_girder_solid(shape, start_xyz, end_xyz):
    """Build a swept-solid girder from start_xyz to end_xyz.

    The caller is responsible for appending the returned `Solid3d` to
    ModelSpace and writing xdata. The Solid3d is NOT yet in the
    database; if the caller can't append, it must call `.Dispose()`.
    """
    start_x, start_y, start_z = start_xyz
    end_x, end_y, end_z = end_xyz

    dx = end_x - start_x
    dy = end_y - start_y
    plan_len = math.hypot(dx, dy)
    if plan_len <= 0.0:
        raise GirderError(
            f"girder endpoints coincide in plan view "
            f"(start_xy={start_xyz[:2]}, end_xy={end_xyz[:2]}); "
            f"can't determine girder direction"
        )
    girder_xy = Vector3d(dx / plan_len, dy / plan_len, 0.0)
    cross_xy = Vector3d(-dy / plan_len, dx / plan_len, 0.0)  # 90° CCW

    verts = gg.i_shape_profile_vertices_ft(shape)

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

        # Move profile from XY-at-origin into the vertical plane
        # perpendicular to `girder_xy`, with origin (top-center of top
        # flange) at start_xyz.
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
            raise GirderError(
                f"Region.CreateFromCurves returned no regions for "
                f"{shape.designation} profile — outline did not form a "
                f"closed loop"
            )
        region = regions_dboc.get_Item(0)

        path = Line(
            Point3d(start_x, start_y, start_z),
            Point3d(end_x, end_y, end_z),
        )

        # `SweepOptions` itself is the immutable result; the settable
        # surface lives on `SweepOptionsBuilder`. Direct property
        # assignment on `SweepOptions` is rejected with a setter-missing
        # error on the AutoCAD 2024 .NET runtime.
        opts_builder = SweepOptionsBuilder()
        # NoAlignment: do NOT auto-rotate profile to be perpendicular
        # to the (sloped) path tangent; keep our pre-set vertical
        # orientation so the web stays plumb on graded paths.
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
