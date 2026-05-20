"""deck_polygon.py — deck plan polygon as a skeleton entity in C3D.

The deck plan polygon is the single source of truth for the deck's
plan-view footprint. It lives on the ``BRIDGE-2D-DECK`` layer as a
closed AutoCAD ``Polyline`` whose vertices and bulges describe the
deck outline. The deck solid is built FROM this polygon (boolean-
intersect with the fat-deck sweep — see ``decks.py``).

Two-mode workflow
-----------------
Once a polygon tagged with our xdata exists in the drawing with a
matching ``schema_version``, this module preserves it on subsequent
runs. Designers can grip-edit individual vertices (move corners,
adjust arc bulges) and the changes survive re-runs — the deck solid
regenerates from the edited polygon.

If the polygon is missing, or its ``schema_version`` is stale, this
module regenerates it from ``deck_plan.derive_deck_plan_polygon()``.

Layer
-----
``BRIDGE-2D-DECK`` is plottable (the polygon defines the deck plan
shape and SHOULD appear on plan sheets) and unlocked (designers need
to grip-edit it). Color 142 (light blue).

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
import deck_plan as dp
import layers
import xdata


# Layer for the deck plan polygon (designer-editable, plottable).
LAYER_NAME = "BRIDGE-2D-DECK"
LAYER_COLOR = 142  # light blue — distinct from BRIDGE-NOPLOT (magenta)

# Xdata RegApp + key. Reuses the project-wide BRIDGE_MODELER RegApp.
XDATA_APP = "BRIDGE_MODELER"
XDATA_KEY = "deck_polygon"
XDATA_NAME = "DECK-PLAN"  # value stored under XDATA_KEY for find-or-create

# Schema version. Bump when the polygon-generation algorithm changes in
# a way that invalidates previously-created polygons; the next run
# erases stale ones and regenerates them.
_SCHEMA_VERSION_KEY = "schema_version"
_SCHEMA_VERSION = "v2-subentity-classification"


class DeckPolygonError(RuntimeError):
    pass


def ensure_deck_plan_polygon(
    tr,
    db,
    alignment_obj,
    params,
    compute_result,
) -> dict:
    """Find-or-create the deck plan polygon on the BRIDGE-2D-DECK layer.

    Returns a dict with keys:
      - ``created``: list of (name, oid) when a new polygon was created
      - ``preserved``: list of (name, oid) when an existing one was kept
      - ``regenerated``: list of (name, oid, stale_version) when stale
        schema_version triggered a regenerate
      - ``vertices``: the polygon vertices (read back from the persisted
        polyline so downstream consumers can use the live geometry,
        including any designer edits)
    """
    print("[deck_polygon] entering ensure_deck_plan_polygon")

    layer_id = layers.ensure_layer(
        tr, db, LAYER_NAME, color=LAYER_COLOR,
        plottable=True, locked=False,
    )
    _set_layer_plot_and_lock(tr, layer_id, plottable=True, locked=False)
    xdata.ensure_regapp(tr, db, XDATA_APP)

    created: List[Tuple[str, object]] = []
    preserved: List[Tuple[str, object]] = []
    regenerated: List[Tuple[str, object, object]] = []

    existing_id, existing_version = _find_tagged_polygon(tr, db)

    if existing_id is not None and existing_version == _SCHEMA_VERSION:
        # Preserve designer edits — read vertices back from the polyline
        pline = tr.GetObject(existing_id, OpenMode.ForRead)
        vertices = _read_vertices_from_polyline(pline)
        preserved.append((XDATA_NAME, existing_id))
        print(
            f"[deck_polygon] preserved existing polygon "
            f"({len(vertices)} vertices, schema_version={existing_version!r})"
        )
        return {
            "created": created,
            "preserved": preserved,
            "regenerated": regenerated,
            "vertices": vertices,
        }

    # Erase stale polygon if present
    if existing_id is not None:
        # Layer is unlocked but use force-open just in case a user locked it
        stale_ent = tr.GetObject(existing_id, OpenMode.ForWrite, False, True)
        stale_ent.Erase()
        regenerated.append((XDATA_NAME, existing_id, existing_version))
        print(
            f"[deck_polygon] erased stale polygon "
            f"(schema_version={existing_version!r}; current={_SCHEMA_VERSION!r})"
        )

    # Derive a fresh polygon from params + alignment
    vertices = _derive_polygon(alignment_obj, params, compute_result)

    pline = _create_polyline(tr, db, vertices)
    xdata.write(tr, pline.ObjectId, XDATA_APP, {
        XDATA_KEY: XDATA_NAME,
        _SCHEMA_VERSION_KEY: _SCHEMA_VERSION,
    })
    if existing_id is None:
        created.append((XDATA_NAME, pline.ObjectId))
        print(f"[deck_polygon] created new polygon ({len(vertices)} vertices)")
    # else: already counted in regenerated above; new polyline replaces it

    return {
        "created": created,
        "preserved": preserved,
        "regenerated": regenerated,
        "vertices": vertices,
    }


# ----------------------------------------------------------------------
# Polygon derivation: turn params + alignment into PlanVertex list
# ----------------------------------------------------------------------

def _derive_polygon(alignment_obj, params, compute_result) -> List[dp.PlanVertex]:
    """Pull alignment geometry + bridge params → call deck_plan."""
    if not compute_result.spans:
        raise DeckPolygonError("compute_result has no spans")
    if len(compute_result.spans) != 1:
        raise DeckPolygonError(
            "Phase 1 expects a single span; multi-span polygon derivation "
            "is deferred"
        )

    span = compute_result.spans[0]
    supports_by_id = {s.support_id: s for s in params.supports}
    start_support = supports_by_id[span.start_support_id]
    end_support = supports_by_id[span.end_support_id]

    # Bridge extent — use the bearing stations of the first/last supports
    bridge_start = start_support.station
    bridge_end = end_support.station

    # Pull alignment geometry segments within the bridge extent
    try:
        seg_tuples = al.alignment_entity_ranges(
            alignment_obj, bridge_start, bridge_end,
        )
    except Exception as exc:  # noqa: BLE001
        print(
            f"[deck_polygon] alignment_entity_ranges failed "
            f"({type(exc).__name__}: {exc}); treating bridge as all-tangent"
        )
        seg_tuples = [("TANGENT", bridge_start, bridge_end, None)]

    segments = [
        dp.AlignmentSegment(
            entity_type=et,
            start_station=s0,
            end_station=s1,
            radius=radius,
        )
        for (et, s0, s1, radius) in seg_tuples
    ]
    print(
        f"[deck_polygon] alignment segments within bridge: "
        f"{[(s.entity_type, round(s.start_station, 2), round(s.end_station, 2)) for s in segments]}"
    )

    # Edge offsets at start and end bearings — use the deck cl shift +
    # the superstructure widths.  At each support the deck width is the
    # superstructure's perpendicular_deck_width_{start|end}.
    super_ = compute_result.spans[0]
    dcl_start = params.deck_cl_offset_from_alignment.at(bridge_start)
    dcl_end = params.deck_cl_offset_from_alignment.at(bridge_end)
    w_start = super_.perpendicular_deck_width_start
    w_end = super_.perpendicular_deck_width_end

    start_left = dcl_start - w_start / 2.0
    start_right = dcl_start + w_start / 2.0
    end_left = dcl_end - w_end / 2.0
    end_right = dcl_end + w_end / 2.0

    # Closures matching the deck_plan callable signatures
    def point_at(station, perp_offset):
        return al.point_at_station(alignment_obj, station, perp_offset)

    def direction_at(station):
        return al.direction_at_station(alignment_obj, station)

    def point_on_skewed_bearing(station, skew_deg, perp_offset):
        return al.point_on_skewed_bearing(
            alignment_obj, station, skew_deg, perp_offset,
        )

    polygon = dp.derive_deck_plan_polygon(
        segments=segments,
        bridge_start_station=bridge_start,
        bridge_end_station=bridge_end,
        start_left_offset=start_left,
        start_right_offset=start_right,
        end_left_offset=end_left,
        end_right_offset=end_right,
        start_skew_deg=start_support.skew_angle,
        end_skew_deg=end_support.skew_angle,
        point_at_station_offset=point_at,
        direction_at_station=direction_at,
        point_on_skewed_bearing=point_on_skewed_bearing,
    )
    return polygon


# ----------------------------------------------------------------------
# Polyline I/O
# ----------------------------------------------------------------------

def _create_polyline(tr, db, vertices: List[dp.PlanVertex]) -> Polyline:
    """Append a closed AutoCAD Polyline with the given vertices+bulges."""
    if len(vertices) < 3:
        raise DeckPolygonError(
            f"deck plan polygon needs >= 3 vertices; got {len(vertices)}"
        )

    pline = Polyline()
    for i, v in enumerate(vertices):
        pline.AddVertexAt(i, Point2d(v.x, v.y), v.bulge, 0.0, 0.0)
    pline.Closed = True
    pline.Layer = LAYER_NAME

    bt_record_id = SymbolUtilityServices.GetBlockModelSpaceId(db)
    btr = tr.GetObject(bt_record_id, OpenMode.ForWrite)
    btr.AppendEntity(pline)
    tr.AddNewlyCreatedDBObject(pline, True)

    return pline


def _read_vertices_from_polyline(pline: Polyline) -> List[dp.PlanVertex]:
    """Read vertices + bulges back from a Polyline (supports designer edits)."""
    vertices: List[dp.PlanVertex] = []
    n = int(pline.NumberOfVertices)
    for i in range(n):
        p = pline.GetPoint2dAt(i)
        bulge = float(pline.GetBulgeAt(i))
        vertices.append(dp.PlanVertex(float(p.X), float(p.Y), bulge))
    return vertices


def _find_tagged_polygon(tr, db):
    """Find the deck plan polygon by xdata tag. Returns (entity_id, version).

    Returns ``(None, None)`` if no tagged polygon is found.
    """
    bt_record_id = SymbolUtilityServices.GetBlockModelSpaceId(db)
    btr = tr.GetObject(bt_record_id, OpenMode.ForRead)
    for entity_id in btr:
        entity = tr.GetObject(entity_id, OpenMode.ForRead)
        if not isinstance(entity, Polyline):
            continue
        if entity.Layer != LAYER_NAME:
            continue
        data = xdata.read(entity, XDATA_APP)
        if data and data.get(XDATA_KEY) == XDATA_NAME:
            return entity_id, data.get(_SCHEMA_VERSION_KEY)
    return None, None


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
