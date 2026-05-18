"""Deck slab lofted-solid creation on `BRIDGE-DECK`.

Civil-3D-only. Will not import on macOS.

The deck slab spans from the start bearing line to the end bearing
line, with cross-section data sourced from `compute_result.spans[i].
deck_start` and `.deck_end`. Each cross-section is a closed polygon
(parallelogram or hexagon) lying in the vertical plane that contains
its bearing line; `Solid3d.CreateLoftedSolid` builds the slab as the
linear interpolation between the two cross-sections.

Why lofted (not swept)
----------------------
For fanning decks (e.g. width 22 → 25 ft across the span), the start
and end cross-sections are different shapes. A sweep requires a
constant profile along the path; a loft handles distinct start / end
profiles. The girders and haunches above use sweeps because their
cross-sections are constant per element; the slab is the first place
in Phase 1 that genuinely needs a loft.

Cross-section orientation
-------------------------
For each cross-section, the profile is built in 2D `(u, v)` coords:
  - `u` = along-bearing distance from the alignment crossing,
    derived from the stored `perp_offset` via `u = perp_offset /
    cos(skew_deg)`.
  - `v` = absolute world Z (top_z for the top edge, `top_z -
    deck_depth` for the bottom edge).

The Matrix3d transform aligns the profile's local axes to:
  - X-axis → bearing-line direction in plan (going toward the
    alignment-LEFT side — matching the convention used by
    `bridge_lines._vertex_specs` and `point_on_skewed_bearing`).
  - Y-axis → world +Z.
  - Z-axis (profile normal) → horizontal, perpendicular to bearing
    line in plan (right-handed: X × Y = Z).

Origin maps to world `(crossing_x, crossing_y, 0)`, so the local
`(u=0, v=top_z)` lands at the alignment crossing at the deck top
elevation.

Re-run contract
---------------
Solid geometry regenerates each run. This module wipes every
ModelSpace entity on `BRIDGE-DECK` at the start of
`ensure_phase1_decks` and rebuilds from scratch.

See `src/girders.py` for the IDisposable / pythonnet-quirk notes
that apply identically here.
"""
from __future__ import annotations

import math
from typing import List, Tuple

import clr

clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.DatabaseServices import (  # noqa: E402
    DBObjectCollection,
    LoftOptions,
    OpenMode,
    Polyline,
    Region,
    Solid3d,
    SymbolUtilityServices,
)
from Autodesk.AutoCAD.Geometry import (  # noqa: E402
    Matrix3d,
    Point2d,
    Point3d,
    Vector3d,
)

import alignment as al
import layers
import xdata


LAYER_DECK = "BRIDGE-DECK"
_COLOR_DECK = 7  # white/black per templates/README.md

XDATA_APP = "BRIDGE_MODELER"


class DeckError(RuntimeError):
    pass


def ensure_phase1_decks(
    tr,
    db,
    alignment_obj,
    params,
    compute_result,
    aisc_table,
) -> dict:
    """Regenerate deck slab solids on `BRIDGE-DECK`.

    Returns `{"created": [(element_id, oid), ...], "purged": N}`.
    Solid geometry regenerates each run; any prior entities on
    `BRIDGE-DECK` are erased first.
    """
    print("[decks] entering ensure_phase1_decks")
    layers.ensure_layer(tr, db, LAYER_DECK, color=_COLOR_DECK)
    xdata.ensure_regapp(tr, db, XDATA_APP)

    purged = _purge_deck_layer(tr, db)
    if purged:
        print(f"[decks] purged {purged} prior entit{'y' if purged == 1 else 'ies'} on {LAYER_DECK}")

    created: List[Tuple[str, object]] = []

    for span in compute_result.spans:
        element_id = f"{span.span_id}.DECK"

        solid = _build_deck_solid(alignment_obj, span)
        try:
            ms_id = SymbolUtilityServices.GetBlockModelSpaceId(db)
            btr = tr.GetObject(ms_id, OpenMode.ForWrite)
            solid.Layer = LAYER_DECK
            oid = btr.AppendEntity(solid)
            tr.AddNewlyCreatedDBObject(solid, True)
        except Exception:
            solid.Dispose()
            raise

        xdata.write(tr, oid, XDATA_APP, {
            "element": "deck",
            "span_id": span.span_id,
            "id": element_id,
        })
        created.append((element_id, oid))
        print(f"[decks]   built {element_id}")

    return {"created": created, "purged": purged}


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------

def _purge_deck_layer(tr, db) -> int:
    """Erase every ModelSpace entity on `BRIDGE-DECK`."""
    ms_id = SymbolUtilityServices.GetBlockModelSpaceId(db)
    btr = tr.GetObject(ms_id, OpenMode.ForWrite)
    count = 0
    for oid in btr:
        ent = tr.GetObject(oid, OpenMode.ForRead)
        if getattr(ent, "Layer", None) != LAYER_DECK:
            continue
        ent.UpgradeOpen()
        ent.Erase()
        count += 1
    return count


def _build_deck_solid(alignment_obj, span):
    """Build a lofted deck slab between the start and end cross-sections."""
    start_region = None
    start_pline = None
    start_curves = None
    start_regions_dboc = None
    end_region = None
    end_pline = None
    end_curves = None
    end_regions_dboc = None
    loft_curves = None
    try:
        start_region, start_pline, start_curves, start_regions_dboc = (
            _build_cross_section_region(alignment_obj, span.deck_start)
        )
        end_region, end_pline, end_curves, end_regions_dboc = (
            _build_cross_section_region(alignment_obj, span.deck_end)
        )

        loft_curves = DBObjectCollection()
        loft_curves.Add(start_region)
        loft_curves.Add(end_region)

        # No guide curves, no path — simple linear loft between two
        # cross-sections in two different planes. Default LoftOptions
        # produces a ruled-surface solid which is exactly what we want
        # for a straight bridge deck.
        opts = LoftOptions()

        solid = Solid3d()
        try:
            # `pathCurve` argument is the path along which to loft. For a
            # plain two-cross-section loft (no path, no guides), pass None
            # / null and AutoCAD generates the connecting ruled surface
            # between the cross-sections.
            solid.CreateLoftedSolid(loft_curves, None, None, opts)
        except Exception:
            solid.Dispose()
            raise
        return solid
    finally:
        # Disposal order: highest-level outputs first.
        if loft_curves is not None:
            loft_curves.Dispose()
        if start_region is not None:
            start_region.Dispose()
        if start_regions_dboc is not None:
            start_regions_dboc.Dispose()
        if start_pline is not None:
            start_pline.Dispose()
        if start_curves is not None:
            start_curves.Dispose()
        if end_region is not None:
            end_region.Dispose()
        if end_regions_dboc is not None:
            end_regions_dboc.Dispose()
        if end_pline is not None:
            end_pline.Dispose()
        if end_curves is not None:
            end_curves.Dispose()


def _build_cross_section_region(alignment_obj, deck_cs):
    """Build a Region for one deck cross-section.

    Returns (region, polyline, curves_dboc, regions_dboc) so the caller
    can dispose them in the correct order after the loft completes.
    """
    crossing_xy = al.point_at_station(alignment_obj, deck_cs.bearing_station, 0.0)
    alignment_dir = al.direction_at_station(alignment_obj, deck_cs.bearing_station)
    skew_rad = math.radians(deck_cs.skew_angle)

    # Bearing-line direction in plan, going toward alignment-LEFT.
    # Matches the convention in `point_on_skewed_bearing`:
    # perp_left_dir = alignment_dir + pi/2 + skew.
    bearing_left_dir_rad = alignment_dir + math.pi / 2.0 + skew_rad
    bearing_dir_xy = Vector3d(
        math.cos(bearing_left_dir_rad), math.sin(bearing_left_dir_rad), 0.0
    )
    # Perpendicular to bearing line in plan (right-handed: X × Y = Z, where
    # X = bearing_dir, Y = world +Z). cross product gives (Xy, -Xx, 0).
    perp_to_bearing_xy = Vector3d(bearing_dir_xy.Y, -bearing_dir_xy.X, 0.0)

    # In the (u, v) profile: u = along-bearing distance from the alignment
    # crossing (signed; -ve toward alignment-LEFT side, +ve toward
    # alignment-RIGHT). Note `bearing_dir_xy` points toward alignment-LEFT,
    # so a vertex at perp_offset X (alignment-perpendicular) lands at u =
    # -X / cos(skew) on the bearing line (negate because moving alignment-
    # LEFT corresponds to NEGATIVE perp_offset, but our X axis points
    # toward alignment-LEFT).
    cos_skew = math.cos(skew_rad)

    def _u_from_perp(perp_offset: float) -> float:
        return -perp_offset / cos_skew

    # Build the closed cross-section polygon: top edge left→right, then
    # bottom edge right→left.
    poly_uv: List[Tuple[float, float]] = []
    for tv in deck_cs.top_vertices:
        poly_uv.append((_u_from_perp(tv.perp_offset), tv.top_z))
    for tv in reversed(deck_cs.top_vertices):
        poly_uv.append((_u_from_perp(tv.perp_offset), tv.top_z - deck_cs.deck_depth))

    # Build a 2D Polyline at XY origin tracing the (u, v) vertices, then
    # transform it into the bearing-line vertical plane.
    pline = Polyline()
    for i, (u, v) in enumerate(poly_uv):
        pline.AddVertexAt(i, Point2d(u, v), 0.0, 0.0, 0.0)
    pline.Closed = True

    xform = Matrix3d.AlignCoordinateSystem(
        Point3d(0.0, 0.0, 0.0),
        Vector3d.XAxis, Vector3d.YAxis, Vector3d.ZAxis,
        Point3d(crossing_xy[0], crossing_xy[1], 0.0),
        bearing_dir_xy, Vector3d.ZAxis, perp_to_bearing_xy,
    )
    pline.TransformBy(xform)

    curves = DBObjectCollection()
    curves.Add(pline)
    regions_dboc = Region.CreateFromCurves(curves)
    if regions_dboc.Count == 0:
        # Dispose what we've built before raising — the caller's try/finally
        # won't have references yet.
        regions_dboc.Dispose()
        curves.Dispose()
        pline.Dispose()
        raise DeckError(
            f"Region.CreateFromCurves returned no regions for deck cross-"
            f"section at bearing_station {deck_cs.bearing_station}"
        )
    region = regions_dboc.get_Item(0)
    return region, pline, curves, regions_dboc
