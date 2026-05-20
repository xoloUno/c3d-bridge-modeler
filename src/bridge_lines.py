"""bridge_lines.py module v7 — single-arc edge polylines for DIMRADIUS.

Bridge reference-line creation in Civil 3D.

For Phase 1 the tool creates plain AutoCAD `Polyline` entities for
edge-of-deck (left + right) and — when `deck_cl_offset_from_alignment`
is non-zero — bridge centerline. These polylines live on a
`BRIDGE-NOPLOT` layer that is locked and non-plotting by default:

  - **Snappable + dimensionable** — DIMRADIUS / DIMLINEAR / DIMANGULAR
    on plan production sheets target these polylines. AutoCAD dimensions
    work fine against polyline endpoints, vertices, and arc segments.
  - **Locked** — designers can't accidentally move them. The lock is at
    the layer level, which prevents user-level commands but does not
    block programmatic `BlockTableRecord.AppendEntity()` (the path the
    tool itself uses).
  - **Non-plotting** — once deck solids exist (next slice), the deck's
    projected edges are visible in plan via Hidden visual style. These
    helper polylines are pure dimensioning targets and don't need to
    appear on plotted sheets.

Why polylines instead of true Civil 3D Alignments? The Alignment.Create
API has same-arity overloads (ObjectId vs string variants) that
pythonnet 3 doesn't reliably disambiguate; we documented the
.Overloads[T...] workaround in CLAUDE.md (PythonNet 3 quirks). For
Phase 1 reference geometry, polylines deliver the same end-user value
(snap, dimension, layer-managed display) without the API friction.

Phase 2 may revisit this for curved-girder workflows that need
station/offset queries via `alignment.PointLocation`. The CLAUDE.md
Overloads[] note captures the path back to true alignments when
that need arises.

Civil-3D-only. Will not import on macOS.
"""
from __future__ import annotations

import math
from typing import List, Tuple

import clr

clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.DatabaseServices import (  # noqa: E402
    OpenMode,
    Polyline,
    SymbolUtilityServices,
)
from Autodesk.AutoCAD.Geometry import Point2d  # noqa: E402

import alignment as al
import layers
import xdata


# Layer for bridge reference lines (edges + CL); created locked and
# non-plotting so users can snap/dimension to them but not accidentally
# move them, and so they don't clutter plotted sheets.
NOPLOT_LAYER = "BRIDGE-NOPLOT"
NOPLOT_LAYER_COLOR = 6  # magenta — distinct from default colors

# RegApp + xdata key for tagging our polylines so we can find them on
# subsequent runs. Reuses the same RegApp the deck/pier solids tag with.
XDATA_APP = "BRIDGE_MODELER"
XDATA_KEY = "bridge_line"
# Schema version stamped on each polyline at creation time. Bump when
# the polyline-generation algorithm changes in a way that invalidates
# previously-created polylines — `_ensure_polyline` then erases stale
# tagged polylines (or untagged-with-our-name polylines created before
# this stamp existed) and regenerates them on the next run. Designer
# edits to a polyline whose schema_version matches the current code
# are still preserved via the find-or-create path.
_SCHEMA_VERSION_KEY = "schema_version"
_SCHEMA_VERSION = "v7b-single-arc"

# Reference-line names. Phase 1 = single bridge per drawing; multi-bridge
# namespacing is an open question (scope.md "Open Questions").
NAME_EDGE_LEFT = "BRIDGE-EDGE-L"
NAME_EDGE_RIGHT = "BRIDGE-EDGE-R"
NAME_BRIDGE_CL = "BRIDGE-CL"


class BridgeLineError(RuntimeError):
    pass


def ensure_phase1_bridge_lines(
    tr,
    db,
    alignment_obj,
    params,
    compute_result,
) -> dict:
    """Create or preserve edge-of-deck and (optionally) bridge-CL polylines.

    Returns {"created": [(name, oid)], "preserved": [(name, oid)]}.
    Idempotent across runs — once a polyline tagged with one of our
    names exists in the drawing, this function leaves it alone (matching
    the two-mode workflow).
    """
    print("[bridge_lines] entering ensure_phase1_bridge_lines (v7)")
    # Use the original-signature ensure_layer (color only) so we don't
    # depend on a fresh layers.py reload — empirically OneDrive + Python's
    # __pycache__ can leave stale .pyc files even after a clean git pull.
    # Set IsPlottable / IsLocked directly on the LayerTableRecord here.
    layer_id = layers.ensure_layer(tr, db, NOPLOT_LAYER, color=NOPLOT_LAYER_COLOR)
    _set_layer_plot_and_lock(tr, layer_id, plottable=False, locked=True)
    xdata.ensure_regapp(tr, db, XDATA_APP)

    # Vertex specs: (station, skew_angle_deg) for each polyline vertex. At
    # the start/end bearing stations the polyline's edge points must land on
    # the SKEWED bearing line, not at the perpendicular offset at the
    # bearing-station alignment crossing — otherwise the deck edge polyline
    # ignores the supports' skew and renders as if the bearings were square.
    vertex_specs = _vertex_specs(params, compute_result)
    width_at = _width_at_station_fn(compute_result)
    deck_cl_at = params.deck_cl_offset_from_alignment.at

    left_offset_fn = lambda sta: deck_cl_at(sta) - width_at(sta) / 2.0
    right_offset_fn = lambda sta: deck_cl_at(sta) + width_at(sta) / 2.0

    left_pts = [
        al.point_on_skewed_bearing(
            alignment_obj, sta, skew, left_offset_fn(sta)
        )
        for sta, skew in vertex_specs
    ]
    right_pts = [
        al.point_on_skewed_bearing(
            alignment_obj, sta, skew, right_offset_fn(sta)
        )
        for sta, skew in vertex_specs
    ]

    # Arc bulges so DIMRADIUS works on curved alignments.  On straight
    # alignments every midpoint is collinear → bulge = 0 → straight
    # segments, identical to previous behaviour.
    left_bulges = _compute_arc_bulges(
        alignment_obj, vertex_specs, left_pts, left_offset_fn
    )
    right_bulges = _compute_arc_bulges(
        alignment_obj, vertex_specs, right_pts, right_offset_fn
    )

    created: List[Tuple[str, object]] = []
    preserved: List[Tuple[str, object]] = []
    regenerated: List[Tuple[str, object, object]] = []

    _ensure_polyline(
        tr, db, NAME_EDGE_LEFT, left_pts, left_bulges,
        created, preserved, regenerated,
    )
    _ensure_polyline(
        tr, db, NAME_EDGE_RIGHT, right_pts, right_bulges,
        created, preserved, regenerated,
    )

    if not params.deck_cl_offset_from_alignment.is_effectively_constant_zero():
        # Bridge CL is along the alignment direction at deck CL (no skew —
        # it's a longitudinal line, not a bearing line).
        cl_offset_fn = lambda sta: deck_cl_at(sta)
        cl_pts = [
            al.point_on_skewed_bearing(alignment_obj, sta, skew, cl_offset_fn(sta))
            for sta, skew in vertex_specs
        ]
        cl_bulges = _compute_arc_bulges(
            alignment_obj, vertex_specs, cl_pts, cl_offset_fn
        )
        _ensure_polyline(
            tr, db, NAME_BRIDGE_CL, cl_pts, cl_bulges,
            created, preserved, regenerated,
        )

    for name, _oid, stale_version in regenerated:
        print(
            f"[bridge_lines] regenerated {name} (stale schema_version="
            f"{stale_version!r}; current={_SCHEMA_VERSION!r})"
        )

    return {
        "created": created,
        "preserved": preserved,
        "regenerated": regenerated,
    }


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------

def _set_layer_plot_and_lock(tr, layer_id, *, plottable: bool, locked: bool) -> None:
    """Reconcile the IsPlottable / IsLocked flags on a LayerTableRecord."""
    rec = tr.GetObject(layer_id, OpenMode.ForRead)
    needs_plot = bool(rec.IsPlottable) != bool(plottable)
    needs_lock = bool(rec.IsLocked) != bool(locked)
    if not (needs_plot or needs_lock):
        return
    rec.UpgradeOpen()
    if needs_plot:
        rec.IsPlottable = plottable
    if needs_lock:
        rec.IsLocked = locked

def _vertex_specs(params, compute_result) -> List[Tuple[float, float]]:
    """Return sorted [(station, skew_deg), ...] for each polyline vertex.

    Edge polylines anchor at SUPPORT stations (where the sample lines /
    abutment CLs are), NOT at bearing-line stations. That matches the
    deck's plan-view extent — what plan-production dimensions target —
    rather than the bearing line that sits inside the deck slab.

    Returns just the start and end support vertices — the arc bulge on
    the single segment between them captures the alignment curvature.
    On straight alignments the bulge is 0 and the result is identical
    to a straight chord.
    """
    if not compute_result.spans:
        raise BridgeLineError("compute_result has no spans")
    if len(compute_result.spans) != 1:
        raise BridgeLineError(
            "Phase 1 expects a single span; multi-span bridge lines are "
            "deferred to Phase 2"
        )
    span = compute_result.spans[0]
    supports_by_id = {s.support_id: s for s in params.supports}
    start_support = supports_by_id[span.start_support_id]
    end_support = supports_by_id[span.end_support_id]

    specs: List[Tuple[float, float]] = [
        (start_support.station, start_support.skew_angle),
        (end_support.station, end_support.skew_angle),
    ]
    return specs


def _width_at_station_fn(compute_result):
    """Linearly-interpolated perpendicular deck width between span ends."""
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


def _compute_arc_bulges(
    alignment_obj,
    vertex_specs: List[Tuple[float, float]],
    points_xy: List[Tuple[float, float]],
    offset_fn,
) -> List[float]:
    """Compute polyline arc bulges so segments follow the alignment curve.

    For each consecutive vertex pair, sample the alignment at the
    mid-station with the same perpendicular offset.  The sagitta
    (distance from chord midpoint to the true curve midpoint) divided
    by the half-chord length equals ``tan(θ/4)`` — exactly AutoCAD's
    bulge definition.  On straight alignments every midpoint is
    collinear with its endpoints, so the bulge is 0.
    """
    bulges: List[float] = []
    for i in range(len(vertex_specs) - 1):
        mid_sta = (vertex_specs[i][0] + vertex_specs[i + 1][0]) / 2.0
        mid_pt = al.point_on_skewed_bearing(
            alignment_obj, mid_sta, 0.0, offset_fn(mid_sta)
        )
        bulges.append(
            _bulge_from_three_points(points_xy[i], mid_pt, points_xy[i + 1])
        )
    bulges.append(0.0)  # last vertex has no outgoing segment
    return bulges


def _bulge_from_three_points(
    p1: Tuple[float, float],
    p_mid: Tuple[float, float],
    p2: Tuple[float, float],
) -> float:
    """Derive the AutoCAD polyline bulge from an arc's three points.

    *p1* and *p2* are the segment endpoints; *p_mid* is a point on the
    arc near the chord midpoint (sampled at the mid-station).

    AutoCAD bulge = ``tan(θ/4)`` = sagitta / half-chord.
    Sign convention: positive when the arc bulges to the LEFT of the
    direction p1 → p2 (counterclockwise arc).
    """
    chord_mx = (p1[0] + p2[0]) / 2.0
    chord_my = (p1[1] + p2[1]) / 2.0
    sag_x = p_mid[0] - chord_mx
    sag_y = p_mid[1] - chord_my
    sag = math.hypot(sag_x, sag_y)
    half_chord = math.hypot(p2[0] - p1[0], p2[1] - p1[1]) / 2.0
    if half_chord < 1e-9 or sag < 1e-9:
        return 0.0
    bulge_mag = sag / half_chord
    # Cross product of chord direction and sagitta gives sign.
    cross = (p2[0] - p1[0]) * sag_y - (p2[1] - p1[1]) * sag_x
    return -bulge_mag if cross >= 0 else bulge_mag


def _ensure_polyline(
    tr,
    db,
    name: str,
    points_xy: List[Tuple[float, float]],
    bulges: List[float],
    created: list,
    preserved: list,
    regenerated: list,
) -> None:
    """Find-or-create a tagged polyline.

    Polylines stamped with the current `_SCHEMA_VERSION` are preserved
    (so designer edits to position survive re-runs). Polylines whose
    stamp is missing or doesn't match — created by an earlier algorithm
    version, e.g. when this module anchored at bearing stations instead
    of support stations — are erased and regenerated against the
    current code.
    """
    existing_id, existing_version = _find_tagged_polyline(tr, db, name)
    if existing_id is not None and existing_version == _SCHEMA_VERSION:
        preserved.append((name, existing_id))
        return

    if existing_id is not None:
        # `BRIDGE-NOPLOT` is locked at the layer level (see
        # `_set_layer_plot_and_lock` above) so users can't accidentally
        # move/erase the polylines from the AutoCAD UI. The lock blocks
        # `OpenMode.ForWrite` even though we OWN the entity — pass
        # `forceOpenOnLockedLayer=True` (4th arg) so the self-heal can
        # erase the stale entity. AppendEntity (used below for the
        # replacement polyline) bypasses the lock natively.
        stale_ent = tr.GetObject(
            existing_id, OpenMode.ForWrite, False, True
        )
        stale_ent.Erase()
        regenerated.append((name, existing_id, existing_version))

    if len(points_xy) < 2:
        raise BridgeLineError(
            f"polyline {name!r} needs >= 2 points; got {len(points_xy)}"
        )

    pline = Polyline()
    for i, (x, y) in enumerate(points_xy):
        pline.AddVertexAt(i, Point2d(x, y), bulges[i], 0.0, 0.0)
    pline.Layer = NOPLOT_LAYER

    bt_record_id = SymbolUtilityServices.GetBlockModelSpaceId(db)
    btr = tr.GetObject(bt_record_id, OpenMode.ForWrite)
    btr.AppendEntity(pline)
    tr.AddNewlyCreatedDBObject(pline, True)

    xdata.write(tr, pline.ObjectId, XDATA_APP, {
        XDATA_KEY: name,
        _SCHEMA_VERSION_KEY: _SCHEMA_VERSION,
    })
    if existing_id is None:
        created.append((name, pline.ObjectId))
    # If existing_id was non-None we already recorded it in `regenerated`
    # above — the new polyline replaces it, so don't double-count.


def _find_tagged_polyline(tr, db, name: str):
    """Find a tagged polyline by name. Returns `(entity_id, schema_version)`.

    `schema_version` is None when the polyline was tagged but had no
    schema_version key written (created by an older module version).
    Returns `(None, None)` when no tagged polyline matches.
    """
    bt_record_id = SymbolUtilityServices.GetBlockModelSpaceId(db)
    btr = tr.GetObject(bt_record_id, OpenMode.ForRead)
    for entity_id in btr:
        entity = tr.GetObject(entity_id, OpenMode.ForRead)
        # Polyline (lightweight 2D) is the type we create; ignore other entities
        if not isinstance(entity, Polyline):
            continue
        if entity.Layer != NOPLOT_LAYER:
            continue
        data = xdata.read(entity, XDATA_APP)
        if data and data.get(XDATA_KEY) == name:
            return entity_id, data.get(_SCHEMA_VERSION_KEY)
    return None, None
