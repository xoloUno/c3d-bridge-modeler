"""Deck slab construction via sweep + boolean trim on `BRIDGE-DECK`.

Civil-3D-only. Will not import on macOS.

Construction strategy
---------------------
Rather than lofting between two skewed-bearing cross-sections (which
introduces a TWIST artifact when the two supports have different skew
angles, distorting the alignment-perpendicular cross-slope), we:

  1. Build a **fat deck**: sweep a wider-than-actual alignment-
     perpendicular cross-section along the alignment's 3D path
     (alignment XY + profile Z), running from before the start corner
     to past the end corner. With the cross-section perpendicular to
     alignment and constant along the sweep, the design-intent cross-
     slope is preserved exactly everywhere.
  2. Build a **trim volume**: vertically extrude the deck plan polygon
     (4 corners derived from compute_result + the skewed-bearing helper
     — same math the `BRIDGE-NOPLOT` edge polylines use) up by a tall
     extent so it fully contains the fat deck.
  3. Boolean **intersect** the fat deck with the trim volume → final
     deck with correct cross-slope AND correct skewed plan footprint.

This is how a human modeler would draw it: extrude a generous deck,
then cut away the triangular corners outside the actual deck plan.

Limitations (deferred to later slices)
--------------------------------------
- Assumes a **straight horizontal alignment**. With Bank=False on the
  sweep, the cross-section doesn't rotate with the path; a curved
  alignment would produce a straight prism instead of a curved deck.
- Vertical alignment curves ARE handled (the sweep path follows the
  profile via a sampled 3D polyline), as long as the horizontal
  alignment is straight.
- Future Phase 2+ work could add multi-point cross-section sampling
  along a curved horizontal alignment.

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
from typing import Callable, List, Optional, Tuple

import clr

clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.DatabaseServices import (  # noqa: E402
    BooleanOperationType,
    DBObjectCollection,
    Entity,
    OpenMode,
    Polyline,
    Polyline3d,
    Poly3dType,
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
    Point3dCollection,
    Vector3d,
)

import alignment as al
import deck_geometry as dg
import layers
import xdata


LAYER_DECK = "BRIDGE-DECK"
_COLOR_DECK = 7  # white/black per templates/README.md

XDATA_APP = "BRIDGE_MODELER"

# Sweep path / cross-section buffers (ft). Generous on both axes so
# the fat deck always covers the trim volume.
_PATH_STATION_BUFFER_FT = 5.0
_CROSS_SECTION_PERP_BUFFER_FT = 5.0
# Number of path sample stations between the extreme stations. More
# samples → better vertical-curve fidelity. 21 = every ~4 ft for a
# typical 80 ft bridge.
_PATH_SAMPLE_COUNT = 21
# Trim volume vertical extent (ft). The trim solid extrudes from
# -_TRIM_BELOW to +_TRIM_ABOVE in world Z; chosen to comfortably
# contain any realistic bridge deck.
_TRIM_BELOW_FT = -1000.0
_TRIM_ABOVE_FT = +1000.0


class DeckError(RuntimeError):
    pass


def ensure_phase1_decks(
    tr,
    db,
    alignment_obj,
    params,
    compute_result,
    aisc_table,
    profile_elevation_at: Callable[[float], float],
) -> dict:
    """Regenerate deck slab solids on `BRIDGE-DECK`.

    Returns `{"created": [(element_id, oid), ...], "purged": N}`.
    Solid geometry regenerates each run; any prior entities on
    `BRIDGE-DECK` are erased first.

    `profile_elevation_at` must return the alignment's PGL elevation
    at any station — same callable phase1_build constructs from the
    Civil 3D profile object.
    """
    print("[decks] entering ensure_phase1_decks")
    layers.ensure_layer(tr, db, LAYER_DECK, color=_COLOR_DECK)
    xdata.ensure_regapp(tr, db, XDATA_APP)

    purged = _purge_deck_layer(tr, db)
    if purged:
        print(f"[decks] purged {purged} prior entit{'y' if purged == 1 else 'ies'} on {LAYER_DECK}")

    supports_by_id = {s.support_id: s for s in params.supports}
    created: List[Tuple[str, object]] = []

    for span in compute_result.spans:
        element_id = f"{span.span_id}.DECK"
        start_support = supports_by_id[span.start_support_id]
        end_support = supports_by_id[span.end_support_id]

        solid = _build_deck_solid(
            alignment_obj=alignment_obj,
            params=params,
            span=span,
            start_support=start_support,
            end_support=end_support,
            profile_elevation_at=profile_elevation_at,
        )
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


def build_fat_deck_cutter(
    *,
    alignment_obj,
    params,
    span,
    profile_elevation_at: Callable[[float], float],
    station_buffer_ft: float = 20.0,
    perp_buffer_ft: float = 10.0,
):
    """Build a non-database-resident "fat" deck `Solid3d` for use as a
    boolean cutter (e.g. by `haunches` when trimming over-tall haunch
    boxes to the deck soffit).

    The cutter is a swept solid (skipping the trim step) wider and
    longer than the actual deck — generous in both axes so any haunch
    inside the deck plan is fully contained in its plan footprint.
    Caller owns the returned `Solid3d` and must `.Dispose()` it (or
    consume it via a boolean op).
    """
    min_station = span.deck_start.bearing_station - station_buffer_ft
    max_station = span.deck_end.bearing_station + station_buffer_ft
    perp_offsets = [
        tv.perp_offset
        for tv in tuple(span.deck_start.top_vertices) + tuple(span.deck_end.top_vertices)
    ]
    min_perp = min(perp_offsets) - perp_buffer_ft
    max_perp = max(perp_offsets) + perp_buffer_ft
    return _build_fat_deck_swept(
        alignment_obj=alignment_obj,
        params=params,
        span=span,
        min_station=min_station,
        max_station=max_station,
        min_perp=min_perp,
        max_perp=max_perp,
        profile_elevation_at=profile_elevation_at,
    )


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


def _build_deck_solid(
    *,
    alignment_obj,
    params,
    span,
    start_support,
    end_support,
    profile_elevation_at: Callable[[float], float],
):
    """Build the final deck solid via sweep + boolean trim."""
    # 1) Compute the four deck plan corners (world XY).
    corners = _deck_plan_corners(
        alignment_obj=alignment_obj,
        span=span,
        start_support=start_support,
        end_support=end_support,
    )

    # 2) Determine the station range and cross-section perp range.
    corner_stations = [c[0] for c in corners]
    corner_perps = [c[1] for c in corners]

    min_station = min(corner_stations) - _PATH_STATION_BUFFER_FT
    max_station = max(corner_stations) + _PATH_STATION_BUFFER_FT
    min_perp = min(corner_perps) - _CROSS_SECTION_PERP_BUFFER_FT
    max_perp = max(corner_perps) + _CROSS_SECTION_PERP_BUFFER_FT

    # 3) Build the fat deck (sweep) and the trim volume (vertical
    #    extrusion), then intersect.
    fat_deck = None
    trim_solid = None
    try:
        fat_deck = _build_fat_deck_swept(
            alignment_obj=alignment_obj,
            params=params,
            span=span,
            min_station=min_station,
            max_station=max_station,
            min_perp=min_perp,
            max_perp=max_perp,
            profile_elevation_at=profile_elevation_at,
        )
        trim_solid = _build_trim_solid(corners_xy=[(c[2], c[3]) for c in corners])

        # Boolean intersect: fat_deck ∩ trim_solid → final deck.
        # Operates in place: fat_deck is mutated to hold the result.
        # `BooleanOperation` consumes the other solid (it gets cleared,
        # not just modified), so we must NOT dispose trim_solid after
        # — but it's still owned by us and not in the database, so we
        # do dispose it in the finally block.
        try:
            boolean_op = fat_deck.BooleanOperation.Overloads[
                BooleanOperationType, Solid3d
            ]
            boolean_op(BooleanOperationType.BoolIntersect, trim_solid)
        except Exception:
            raise

        # Hand ownership of fat_deck back to the caller; null it out
        # locally so the finally block doesn't double-dispose.
        result = fat_deck
        fat_deck = None
        return result
    finally:
        if trim_solid is not None:
            trim_solid.Dispose()
        if fat_deck is not None:
            fat_deck.Dispose()


def _deck_plan_corners(
    *,
    alignment_obj,
    span,
    start_support,
    end_support,
) -> List[Tuple[float, float, float, float]]:
    """Return the 4 deck plan-view corners.

    Each entry is `(bearing_station, perp_offset, world_x, world_y)`.
    Order: start-LEFT, start-RIGHT, end-RIGHT, end-LEFT
    (counter-clockwise when looking down with alignment heading +X).
    """
    def _corner(deck_cs, perp_offset, support):
        x, y = al.point_on_skewed_bearing(
            alignment_obj,
            deck_cs.bearing_station,
            support.skew_angle,
            perp_offset,
        )
        return (deck_cs.bearing_station, perp_offset, x, y)

    deck_start = span.deck_start
    deck_end = span.deck_end

    start_left_perp = deck_start.top_vertices[0].perp_offset
    start_right_perp = deck_start.top_vertices[-1].perp_offset
    end_left_perp = deck_end.top_vertices[0].perp_offset
    end_right_perp = deck_end.top_vertices[-1].perp_offset

    return [
        _corner(deck_start, start_left_perp, start_support),
        _corner(deck_start, start_right_perp, start_support),
        _corner(deck_end, end_right_perp, end_support),
        _corner(deck_end, end_left_perp, end_support),
    ]


def _build_fat_deck_swept(
    *,
    alignment_obj,
    params,
    span,
    min_station: float,
    max_station: float,
    min_perp: float,
    max_perp: float,
    profile_elevation_at: Callable[[float], float],
):
    """Sweep an alignment-perpendicular cross-section along the
    alignment 3D path.

    Returns the swept `Solid3d` (caller owns it).
    """
    deck_depth = span.deck_start.deck_depth

    # Build the 3D path as a Polyline3d sampling profile Z at each
    # interior station between min/max. The path is along the alignment
    # XY (straight horizontal alignment assumed) with Z = profile + the
    # deck_profile_offset (which makes the path follow the deck-top
    # crown elevation — and v=0 of the cross-section then sits at that
    # path Z, anchoring the cross-section's crown to the path).
    path_points = _build_path_3d_points(
        alignment_obj=alignment_obj,
        min_station=min_station,
        max_station=max_station,
        profile_elevation_at=profile_elevation_at,
        deck_profile_offset=params.deck_profile_offset,
    )

    pline3d = None
    pline = None
    curves = None
    regions_dboc = None
    region = None
    try:
        # Build the path Polyline3d.
        pts_collection = Point3dCollection()
        for pt in path_points:
            pts_collection.Add(pt)
        pline3d = Polyline3d(Poly3dType.SimplePoly, pts_collection, False)

        # Build the alignment-perpendicular fat cross-section in
        # profile-local (u, v) coords. u = perp_offset (alignment-
        # perpendicular distance, signed). v = Z OFFSET from the path
        # point (so v=0 at the crown). The crown is at u = crown_offset.
        cross_verts = _fat_cross_section_uv(
            params=params,
            span=span,
            min_perp=min_perp,
            max_perp=max_perp,
            deck_depth=deck_depth,
        )

        pline = Polyline()
        for i, (u, v) in enumerate(cross_verts):
            pline.AddVertexAt(i, Point2d(u, v), 0.0, 0.0, 0.0)
        pline.Closed = True

        # Orient the cross-section in the alignment-perpendicular
        # vertical plane at the START of the path. profile-X → +Y world
        # (alignment-LEFT direction for an east-heading alignment) was
        # used elsewhere; here we use the +Y direction perpendicular to
        # the alignment direction at the start of the path. The cross-
        # section's local X = the alignment-perpendicular-LEFT
        # direction (so positive u = alignment-LEFT, mirroring the
        # convention compute uses for storing perp_offset values: deck
        # CL is at -perp, and the cross-section u corresponds to perp).
        start_dir_rad = al.direction_at_station(alignment_obj, min_station)
        # alignment-LEFT direction in plan: rotate alignment direction
        # 90° CCW.
        align_left_xy = Vector3d(
            -math.sin(start_dir_rad), math.cos(start_dir_rad), 0.0
        )
        # Perpendicular-to-(alignment-LEFT and Z) in plan: this is the
        # alignment-AHEAD direction (the sweep direction).
        align_ahead_xy = Vector3d(
            math.cos(start_dir_rad), math.sin(start_dir_rad), 0.0
        )
        # Profile X = align_left_xy (+u maps to alignment-LEFT).
        # Profile Y = world +Z (vertical, the v axis).
        # Profile Z = align_ahead_xy (the normal-of-cross-section, the
        #   sweep direction). Right-handed: X × Y = Z.
        # NOTE: this opposite sign on `align_left_xy` vs the
        # alignment-perpendicular offset convention means u → perp_offset
        # is `u = -perp_offset`. We handle this by negating perp inside
        # the cross-section builder so the cross-section's "left" lands
        # on alignment-LEFT.
        xform = Matrix3d.AlignCoordinateSystem(
            Point3d(0.0, 0.0, 0.0),
            Vector3d.XAxis, Vector3d.YAxis, Vector3d.ZAxis,
            path_points[0],
            align_left_xy, Vector3d.ZAxis, align_ahead_xy,
        )
        pline.TransformBy(xform)

        curves = DBObjectCollection()
        curves.Add(pline)
        regions_dboc = Region.CreateFromCurves(curves)
        if regions_dboc.Count == 0:
            raise DeckError(
                "Region.CreateFromCurves returned no regions for fat deck "
                "cross-section."
            )
        region = regions_dboc.get_Item(0)

        # Sweep options: Align=NoAlignment + Bank=False so the cross-
        # section keeps its alignment-perpendicular orientation
        # throughout the (possibly vertically-curved) path.
        opts_builder = SweepOptionsBuilder()
        opts_builder.Align = SweepOptionsAlignOption.NoAlignment
        opts_builder.Bank = False
        opts_builder.TwistAngle = 0.0
        opts = opts_builder.ToSweepOptions()

        solid = Solid3d()
        try:
            solid.CreateSweptSolid(region, pline3d, opts)
        except Exception:
            solid.Dispose()
            raise
        return solid
    finally:
        if region is not None:
            region.Dispose()
        if regions_dboc is not None:
            regions_dboc.Dispose()
        if pline is not None:
            pline.Dispose()
        if curves is not None:
            curves.Dispose()
        if pline3d is not None:
            pline3d.Dispose()


def _build_path_3d_points(
    *,
    alignment_obj,
    min_station: float,
    max_station: float,
    profile_elevation_at: Callable[[float], float],
    deck_profile_offset: float,
) -> List[Point3d]:
    """Sample the alignment + profile at evenly-spaced stations,
    returning a list of 3D path points.

    Path Z = profile_elevation + deck_profile_offset, i.e. the deck-top
    elevation at the crown. The cross-section's v=0 anchors to this Z,
    matching the elevation chain.
    """
    pts: List[Point3d] = []
    n = max(2, _PATH_SAMPLE_COUNT)
    for i in range(n):
        t = i / float(n - 1)
        station = min_station + t * (max_station - min_station)
        x, y = al.point_at_station(alignment_obj, station, 0.0)
        z = profile_elevation_at(station) + deck_profile_offset
        pts.append(Point3d(x, y, z))
    return pts


def _fat_cross_section_uv(
    *,
    params,
    span,
    min_perp: float,
    max_perp: float,
    deck_depth: float,
) -> Tuple[Tuple[float, float], ...]:
    """Build the fat cross-section's `(u, v)` vertices, where u is
    measured in the alignment-LEFT direction and v is the Z-offset
    from the path's elevation at the crown.

    Reuses `deck_geometry.deck_cross_section` for the vertex layout
    (crown-kink detection etc.). The v-values returned are RELATIVE
    to the crown (which sits at v=0), NOT absolute Z — the caller's
    Matrix3d transform anchors the cross-section to the path point
    where v=0 maps to path Z.
    """
    # Crown perp at this span: we use the start-bearing crown_offset
    # (constant per the typical Phase 1 case). For station-varying
    # crown_offset, the fat cross-section won't track the variation —
    # a follow-up slice.
    crown_perp = params.crown_offset.at(span.deck_start.bearing_station)

    # Top-of-deck elevations at the cross-section vertices, expressed
    # relative to the crown's top_of_deck:
    # delta = (slope/100) * |perp - crown|
    def _v_at(perp: float) -> float:
        if perp == crown_perp:
            return 0.0
        if perp < crown_perp:
            slope = params.deck_cross_slope_left
        else:
            slope = params.deck_cross_slope_right
        return (slope / 100.0) * abs(perp - crown_perp)

    # We want positive u to correspond to alignment-LEFT (negative
    # perp_offset in C3D's convention), because Matrix3d maps profile
    # +X axis onto `align_left_xy`. So the cross-section's left/right
    # in u space is mirrored relative to perp space:
    #   u  =  -perp
    # The wider extent: u from -max_perp to -min_perp.
    cs = dg.deck_cross_section(
        deck_left_perp=min_perp,    # alignment-perpendicular convention
        deck_right_perp=max_perp,
        deck_top_left_z=_v_at(min_perp),
        deck_top_right_z=_v_at(max_perp),
        deck_depth=deck_depth,
        crown_perp=crown_perp,
        deck_top_crown_z=_v_at(crown_perp),
    )

    # Mirror perp → u (u = -perp). v values stay as-is.
    return tuple((-perp, v) for (perp, v) in cs.vertices)


def _build_trim_solid(corners_xy: List[Tuple[float, float]]):
    """Extrude the deck plan polygon vertically into a tall prism.

    The prism extends from `_TRIM_BELOW_FT` to `_TRIM_ABOVE_FT` in Z,
    so its boolean intersection with the fat deck preserves only the
    fat-deck's XY extent within the polygon.
    """
    if len(corners_xy) < 3:
        raise DeckError(
            f"trim polygon needs >= 3 corners; got {len(corners_xy)}"
        )

    pline = None
    curves = None
    regions_dboc = None
    region = None
    try:
        pline = Polyline()
        pline.Elevation = _TRIM_BELOW_FT  # place polyline at low Z
        for i, (x, y) in enumerate(corners_xy):
            pline.AddVertexAt(i, Point2d(x, y), 0.0, 0.0, 0.0)
        pline.Closed = True

        curves = DBObjectCollection()
        curves.Add(pline)
        regions_dboc = Region.CreateFromCurves(curves)
        if regions_dboc.Count == 0:
            raise DeckError(
                f"Region.CreateFromCurves failed for trim polygon with "
                f"{len(corners_xy)} corners: {corners_xy}"
            )
        region = regions_dboc.get_Item(0)

        height = _TRIM_ABOVE_FT - _TRIM_BELOW_FT
        solid = Solid3d()
        try:
            solid.CreateExtrudedSolid(region, Vector3d(0.0, 0.0, height), _zero_taper_options())
        except Exception:
            solid.Dispose()
            raise
        return solid
    finally:
        if region is not None:
            region.Dispose()
        if regions_dboc is not None:
            regions_dboc.Dispose()
        if curves is not None:
            curves.Dispose()
        if pline is not None:
            pline.Dispose()


def _zero_taper_options():
    """Return a SweepOptions configured for a straight-extrusion (no
    taper, no twist, no banking) — used by `CreateExtrudedSolid`."""
    builder = SweepOptionsBuilder()
    builder.Align = SweepOptionsAlignOption.NoAlignment
    builder.Bank = False
    builder.TwistAngle = 0.0
    return builder.ToSweepOptions()
