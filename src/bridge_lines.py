"""Bridge reference-line creation in Civil 3D.

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

from typing import List, Optional, Tuple

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
    print("[bridge_lines] entering ensure_phase1_bridge_lines")
    layers.ensure_layer(
        tr, db, NOPLOT_LAYER,
        color=NOPLOT_LAYER_COLOR,
        plottable=False,
        locked=True,
    )
    xdata.ensure_regapp(tr, db, XDATA_APP)

    # Vertex stations: bearing-line endpoints + any internal control
    # points of the deck_cl_offset profile.
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

    _ensure_polyline(tr, db, NAME_EDGE_LEFT, left_pts, created, preserved)
    _ensure_polyline(tr, db, NAME_EDGE_RIGHT, right_pts, created, preserved)

    if not params.deck_cl_offset_from_alignment.is_effectively_constant_zero():
        cl_pts = [
            _point_at(alignment_obj, s, deck_cl_at(s)) for s in vertex_stations
        ]
        _ensure_polyline(tr, db, NAME_BRIDGE_CL, cl_pts, created, preserved)

    return {"created": created, "preserved": preserved}


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------

def _vertex_stations(params, compute_result) -> List[float]:
    """Sorted stations defining the bridge polyline.

    Always includes start and end bearing stations from the (single,
    Phase 1) span, plus any internal control points of
    `deck_cl_offset_from_alignment` strictly inside the bearing range.
    """
    if not compute_result.spans:
        raise BridgeLineError("compute_result has no spans")
    if len(compute_result.spans) != 1:
        raise BridgeLineError(
            "Phase 1 expects a single span; multi-span bridge lines are "
            "deferred to Phase 2"
        )
    span = compute_result.spans[0]
    g0 = span.girders[0]
    s_begin = g0.start.bearing_station
    s_end = g0.end.bearing_station

    stations = [s_begin, s_end]
    for s, _v in params.deck_cl_offset_from_alignment.points:
        if s_begin < s < s_end:
            stations.append(s)
    return sorted(stations)


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


def _point_at(alignment_obj, station: float, offset: float) -> Tuple[float, float]:
    return al.point_at_station(alignment_obj, station, offset)


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
