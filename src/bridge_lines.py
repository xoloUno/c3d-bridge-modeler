"""bridge_lines.py module v4 — anchor at support stations, not bearings.

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
    print("[bridge_lines] entering ensure_phase1_bridge_lines (v4)")
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

    left_pts = [
        al.point_on_skewed_bearing(
            alignment_obj, sta, skew, deck_cl_at(sta) - width_at(sta) / 2.0
        )
        for sta, skew in vertex_specs
    ]
    right_pts = [
        al.point_on_skewed_bearing(
            alignment_obj, sta, skew, deck_cl_at(sta) + width_at(sta) / 2.0
        )
        for sta, skew in vertex_specs
    ]

    created: List[Tuple[str, object]] = []
    preserved: List[Tuple[str, object]] = []

    _ensure_polyline(tr, db, NAME_EDGE_LEFT, left_pts, created, preserved)
    _ensure_polyline(tr, db, NAME_EDGE_RIGHT, right_pts, created, preserved)

    if not params.deck_cl_offset_from_alignment.is_effectively_constant_zero():
        # Bridge CL is along the alignment direction at deck CL (no skew —
        # it's a longitudinal line, not a bearing line).
        cl_pts = [
            al.point_on_skewed_bearing(alignment_obj, sta, skew, deck_cl_at(sta))
            for sta, skew in vertex_specs
        ]
        _ensure_polyline(tr, db, NAME_BRIDGE_CL, cl_pts, created, preserved)

    return {"created": created, "preserved": preserved}


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

    Always includes:
      - start support station with start support's skew angle
      - end support station with end support's skew angle
    Optionally includes internal control points of
    `deck_cl_offset_from_alignment` (strictly between the supports) with
    skew_deg = 0 (no support there → no bearing-line skew applies).
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

    s_begin = start_support.station
    s_end = end_support.station

    specs: List[Tuple[float, float]] = [
        (s_begin, start_support.skew_angle),
        (s_end, end_support.skew_angle),
    ]
    for s, _v in params.deck_cl_offset_from_alignment.points:
        if s_begin < s < s_end:
            specs.append((s, 0.0))
    specs.sort(key=lambda spec: spec[0])
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


def _ensure_polyline(
    tr,
    db,
    name: str,
    points_xy: List[Tuple[float, float]],
    created: list,
    preserved: list,
) -> None:
    """Find-or-create a tagged polyline. Idempotent across runs."""
    existing_id = _find_tagged_polyline(tr, db, name)
    if existing_id is not None:
        preserved.append((name, existing_id))
        return

    if len(points_xy) < 2:
        raise BridgeLineError(
            f"polyline {name!r} needs >= 2 points; got {len(points_xy)}"
        )

    pline = Polyline()
    for i, (x, y) in enumerate(points_xy):
        pline.AddVertexAt(i, Point2d(x, y), 0.0, 0.0, 0.0)
    pline.Layer = NOPLOT_LAYER

    bt_record_id = SymbolUtilityServices.GetBlockModelSpaceId(db)
    btr = tr.GetObject(bt_record_id, OpenMode.ForWrite)
    btr.AppendEntity(pline)
    tr.AddNewlyCreatedDBObject(pline, True)

    xdata.write(tr, pline.ObjectId, XDATA_APP, {XDATA_KEY: name})
    created.append((name, pline.ObjectId))


def _find_tagged_polyline(tr, db, name: str):
    """Scan ModelSpace for a Polyline on NOPLOT_LAYER with matching xdata name."""
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
            return entity_id
    return None
