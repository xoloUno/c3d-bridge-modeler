"""Bridge sub-alignment creation in Civil 3D.

For Phase 1 the tool creates edge-of-deck sub-alignments (left and right)
and — when `deck_cl_offset_from_alignment` is non-zero — a bridge
centerline sub-alignment. These are true Civil 3D Alignments (not
sample lines), so DIMRADIUS works on plan-view dimensions.

Phase 1 simplification: sub-alignments are STRAIGHT chords between the
start and end bearing-line stations. If `deck_cl_offset_from_alignment`
has internal control points (station-varying), each control point
becomes an additional vertex on the bridge-CL polyline; edges follow
the same vertex set with the perpendicular deck width applied at each.

Civil-3D-only. Will not import on macOS.

API references confirmed against Camber (mzjensen/Camber, BSD-3):
    civDb.PolylineOptions
        .AddCurvesBetweenTangents = false
        .EraseExistingEntities = true
        .PlineId = polyline.ObjectId

    Alignment.Create(cdoc, polylineOptions, name,
                     site_name (str, "" for siteless),
                     layer_name, style_name, label_set_name)
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import clr

clr.AddReference("acdbmgd")
clr.AddReference("AeccDbMgd")

from Autodesk.AutoCAD.DatabaseServices import (  # noqa: E402
    OpenMode,
    Polyline,
    SymbolUtilityServices,
)
from Autodesk.AutoCAD.Geometry import Point2d  # noqa: E402
from Autodesk.Civil.DatabaseServices import (  # noqa: E402
    Alignment,
    PolylineOptions,
)

import alignment as al
import layers


# Layer for all bridge skeleton sub-alignments (edges + CL); kept as one
# layer for Phase 1 to minimize template-DWG dependencies. Phase 1b can
# split into BRIDGE-SKELETON-EDGE / BRIDGE-SKELETON-CL if useful.
SKELETON_LAYER = "BRIDGE-SKELETON-EDGE"
SKELETON_LAYER_COLOR = 6  # magenta — distinct from green/red default

# Sub-alignment names. Phase 1 = single bridge per drawing; multi-bridge
# namespacing is an open question (scope.md "Open Questions").
NAME_EDGE_LEFT = "BRIDGE-EDGE-L"
NAME_EDGE_RIGHT = "BRIDGE-EDGE-R"
NAME_BRIDGE_CL = "BRIDGE-CL"


# Preferred names per C3D 2024 ship defaults; we fall back to whatever the
# drawing actually has if these aren't present (templates and locales vary —
# e.g. some templates only have "Major Minor" / "All Labels" / etc., not
# "_No Labels"). The actual style + label set used at create time is logged
# so verification can spot-check it.
PREFERRED_ALIGNMENT_STYLES = ("Standard", "Basic", "_No Display")
PREFERRED_LABEL_SETS = (
    "_No Labels",
    "_None",
    "None",
    "Standard",
    "Major Minor",
    "All Labels",
)


class SubAlignmentError(RuntimeError):
    pass


_MODULE_BANNER = "[sub_alignment] module v4 (empty-labelset bypass) loaded"
print(_MODULE_BANNER)


def ensure_phase1_sub_alignments(
    tr,
    db,
    civ_doc,
    alignment_obj,
    params,
    compute_result,
) -> dict:
    """Create or preserve edge-of-deck and (optionally) bridge-CL sub-alignments.

    Returns a dict with keys "created" and "preserved"; each is a list of
    (name, ObjectId) tuples. Idempotent across runs — once an alignment
    with one of our names exists on the drawing, this function leaves it
    alone (matching the two-mode workflow).
    """
    print("[sub_alignment] entering ensure_phase1_sub_alignments (v4)")
    layers.ensure_layer(tr, db, SKELETON_LAYER, color=SKELETON_LAYER_COLOR)

    # Alignment style: we still resolve from what's in the drawing (Standard
    # usually exists; if not we take the first available).
    available_styles = _collect_style_names(tr, civ_doc.Styles.AlignmentStyles)
    print(f"[sub_alignment] available alignment styles: {available_styles!r}")
    style_name = _pick_first_available(
        available_styles, PREFERRED_ALIGNMENT_STYLES, kind="AlignmentStyle"
    )

    # Label set: pass empty string ("") to mirror how `siteName=""` is treated
    # by Alignment.Create (= no site). The previous slice tried name-based
    # resolution but Civil 3D's internal name-to-ObjectId lookup rejected
    # everything we tried; rather than play whack-a-mole with template names,
    # bypass the lookup entirely.
    label_set_name = ""

    print(
        f"[sub_alignment] using alignment style={style_name!r}, "
        f"label set={label_set_name!r} (empty = no label set)"
    )

    # Build vertex lists: one per control point of deck_cl_offset profile,
    # plus the start and end bearing stations as outer endpoints. For the
    # "constant zero" case we need just the two outer endpoints.
    vertex_stations = _vertex_stations(params, compute_result)

    width_at = _width_at_station_fn(compute_result)
    deck_cl_at = params.deck_cl_offset_from_alignment.at

    left_pts = [
        _point_at(alignment_obj, s, deck_cl_at(s) - width_at(s) / 2.0)
        for s in vertex_stations
    ]
    right_pts = [
        _point_at(alignment_obj, s, deck_cl_at(s) + width_at(s) / 2.0)
        for s in vertex_stations
    ]

    created: List[Tuple[str, object]] = []
    preserved: List[Tuple[str, object]] = []

    _ensure_alignment(
        tr, db, civ_doc, NAME_EDGE_LEFT, left_pts,
        style_name, label_set_name, created, preserved,
    )
    _ensure_alignment(
        tr, db, civ_doc, NAME_EDGE_RIGHT, right_pts,
        style_name, label_set_name, created, preserved,
    )

    # Bridge CL: only if deck_cl_offset is not effectively zero everywhere
    if not params.deck_cl_offset_from_alignment.is_effectively_constant_zero():
        cl_pts = [
            _point_at(alignment_obj, s, deck_cl_at(s)) for s in vertex_stations
        ]
        _ensure_alignment(
            tr, db, civ_doc, NAME_BRIDGE_CL, cl_pts,
            style_name, label_set_name, created, preserved,
        )

    return {"created": created, "preserved": preserved}


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------

def _vertex_stations(params, compute_result) -> List[float]:
    """Return the sorted list of stations defining the bridge-skeleton polyline.

    Always includes the start and end bearing stations from the (single,
    Phase 1) span, plus any internal control points of
    `deck_cl_offset_from_alignment` that fall strictly inside the bearing
    range.
    """
    if not compute_result.spans:
        raise SubAlignmentError("compute_result has no spans")
    if len(compute_result.spans) != 1:
        raise SubAlignmentError(
            "Phase 1 expects a single span; multi-span sub-alignments are "
            "deferred to Phase 2"
        )
    span = compute_result.spans[0]
    # The span's girders[*].start.bearing_station / .end.bearing_station are
    # all consistent, so use the first girder for the endpoints.
    g0 = span.girders[0]
    s_begin = g0.start.bearing_station
    s_end = g0.end.bearing_station

    stations = [s_begin, s_end]
    for s, _v in params.deck_cl_offset_from_alignment.points:
        if s_begin < s < s_end:
            stations.append(s)
    return sorted(stations)


def _width_at_station_fn(compute_result):
    """Return a callable `width(station) -> ft` linearly interpolating
    perpendicular deck width between the start and end of the (single) span.
    """
    span = compute_result.spans[0]
    s0 = span.girders[0].start.bearing_station
    s1 = span.girders[0].end.bearing_station
    w0 = span.perpendicular_deck_width_start
    w1 = span.perpendicular_deck_width_end

    def _at(station: float) -> float:
        if s1 == s0:
            return w0
        if station <= s0:
            return w0
        if station >= s1:
            return w1
        t = (station - s0) / (s1 - s0)
        return w0 + t * (w1 - w0)

    return _at


def _point_at(alignment_obj, station: float, offset: float) -> Tuple[float, float]:
    return al.point_at_station(alignment_obj, station, offset)


def _ensure_alignment(
    tr,
    db,
    civ_doc,
    name: str,
    points_xy: List[Tuple[float, float]],
    style_name: str,
    label_set_name: str,
    created: list,
    preserved: list,
) -> None:
    """If an alignment with this name already exists, preserve it; otherwise
    create one from a 2+ point polyline (which is then erased)."""
    existing_id = _find_alignment_id_by_name(tr, civ_doc, name)
    if existing_id is not None:
        preserved.append((name, existing_id))
        return

    pline_id = _create_polyline(tr, db, points_xy)

    options = PolylineOptions()
    options.AddCurvesBetweenTangents = False  # Phase 1 = STRAIGHT
    options.EraseExistingEntities = True
    options.PlineId = pline_id

    alignment_id = Alignment.Create(
        civ_doc,
        options,
        name,
        "",                          # site name; "" = siteless
        SKELETON_LAYER,
        style_name,
        label_set_name,
    )
    created.append((name, alignment_id))


def _collect_style_names(tr, id_collection) -> List[str]:
    names = []
    for oid in id_collection:
        obj = tr.GetObject(oid, OpenMode.ForRead)
        # Strip whitespace defensively — some templates ship with names that
        # have stray leading/trailing spaces, and Alignment.Create's name
        # lookup is exact-match (a leading space breaks the round-trip).
        name = obj.Name
        if isinstance(name, str):
            name = name.strip()
        names.append(name)
    return names


def _pick_first_available(
    available: List[str], preferred: Tuple[str, ...], *, kind: str
) -> str:
    if not available:
        raise SubAlignmentError(
            f"Drawing has no {kind} entries — cannot create alignment"
        )
    for name in preferred:
        if name in available:
            return name
    return available[0]


def _find_alignment_id_by_name(tr, civ_doc, name: str):
    for oid in civ_doc.GetAlignmentIds():
        obj = tr.GetObject(oid, OpenMode.ForRead)
        if obj.Name == name:
            return oid
    return None


def _create_polyline(tr, db, points_xy: List[Tuple[float, float]]):
    """Create a 2D Polyline in ModelSpace from XY points, return its ObjectId.

    The polyline is a temporary scaffold for Alignment.Create; it gets
    erased automatically by `PolylineOptions.EraseExistingEntities = True`.
    """
    if len(points_xy) < 2:
        raise SubAlignmentError(
            f"polyline needs ≥ 2 points; got {len(points_xy)}"
        )

    pline = Polyline()
    for i, (x, y) in enumerate(points_xy):
        pline.AddVertexAt(i, Point2d(x, y), 0.0, 0.0, 0.0)

    bt_record_id = SymbolUtilityServices.GetBlockModelSpaceId(db)
    btr = tr.GetObject(bt_record_id, OpenMode.ForWrite)
    btr.AppendEntity(pline)
    tr.AddNewlyCreatedDBObject(pline, True)
    return pline.ObjectId
