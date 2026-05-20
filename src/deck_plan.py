"""Pure-math helpers for the deck plan polygon (plan-view outline).

The deck plan polygon is a closed CCW polyline that defines the deck's
footprint in the XY plane.  It is the single source of truth for the
deck shape — the 3D deck solid is built by extruding this polygon and
intersecting it with the fat-deck sweep, and the BRIDGE-2D-DECK
skeleton entity is this polygon drawn into the C3D drawing.

Vertex structure
----------------
The polygon traces the deck outline in counter-clockwise order:

    start_left → start_right               (start bearing line)
    start_right → end_right                 (right edge, one or more segments)
    end_right → end_left                    (end bearing line)
    end_left → start_left                   (left edge, one or more segments)

Each segment has an associated *bulge* value (AutoCAD convention):

    bulge = tan(included_angle / 4)

where ``included_angle`` is the arc subtended between the two segment
endpoints.  Positive bulge means the arc bows to the *left* of the
chord direction; negative means it bows to the right.  A bulge of 0
is a straight segment.

Edge taper rules by alignment geometry type
-------------------------------------------

+-------------------+-----------------------------------+-----------+
| Alignment section | Edge segment                      | Bulge     |
+===================+===================================+===========+
| Tangent           | Straight, linear width taper      | 0         |
+-------------------+-----------------------------------+-----------+
| Spiral            | Straight, linear width taper      | 0         |
+-------------------+-----------------------------------+-----------+
| Curve (arc)       | Circular arc, tangent-constrained  | computed  |
|                   | to preceding segment              |           |
+-------------------+-----------------------------------+-----------+

For a fully straight alignment with constant width, the polygon
degenerates to a 4-vertex rectangle with all bulges 0.

Arc derivation
--------------
Given a start point P1 with known tangent direction T, and an endpoint
P2, a unique circular arc exists that is tangent to T at P1 and passes
through P2 (provided P2 is not on the tangent line).  The radius is:

    chord = P2 - P1
    N = unit normal to T (rotated 90° CCW)
    R = |chord|² / (2 × chord · N)

The sign of R encodes which side of T the center lies.  The bulge
follows from the included angle via ``tan(θ/4)``.

Pure-logic module: must not import anything from the Civil 3D API
(``clr``, ``Autodesk.*``). Importable on macOS for unit testing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple


# -----------------------------------------------------------------------
# Type aliases
# -----------------------------------------------------------------------

Point2D = Tuple[float, float]  # (x, y) in plan coordinates


@dataclass(frozen=True)
class ArcResult:
    """Result of fitting a tangent-constrained circular arc."""
    radius: float       # signed: positive = center left of tangent, negative = right
    bulge: float        # AutoCAD bulge = tan(included_angle / 4)
    center: Point2D     # arc center


# -----------------------------------------------------------------------
# Alignment segment descriptor
# -----------------------------------------------------------------------

# Entity types returned by the alignment query layer.  Spirals are
# treated identically to tangent lines for edge-taper purposes (the
# edge is a straight linear taper in station).
ENTITY_TANGENT = "TANGENT"
ENTITY_SPIRAL = "SPIRAL"
ENTITY_ARC = "ARC"


@dataclass(frozen=True)
class AlignmentSegment:
    """One homogeneous section of the horizontal alignment.

    ``entity_type`` is one of ENTITY_TANGENT, ENTITY_SPIRAL, ENTITY_ARC.
    ``start_station`` / ``end_station`` are clipped to the bridge extent.
    ``radius`` is the curve radius for ARC segments (positive = curves
    left, negative = curves right); ``None`` for tangent/spiral.
    """
    entity_type: str
    start_station: float
    end_station: float
    radius: Optional[float] = None


# -----------------------------------------------------------------------
# Polygon vertex descriptor
# -----------------------------------------------------------------------

@dataclass(frozen=True)
class PlanVertex:
    """One vertex of the deck plan polygon.

    ``x, y`` are world plan coordinates.  ``bulge`` is the AutoCAD
    polyline bulge for the segment FROM this vertex to the next vertex
    in the polygon.  The last vertex's bulge connects back to the first.
    """
    x: float
    y: float
    bulge: float = 0.0


# -----------------------------------------------------------------------
# Core geometric primitives
# -----------------------------------------------------------------------

_DEGENERATE_TOL = 1e-9   # ft — skip arcs shorter than this


def arc_from_start_tangent_endpoint(
    p1: Point2D,
    tangent_dir: float,
    p2: Point2D,
) -> Optional[ArcResult]:
    """Fit a circular arc through P1 → P2 that is tangent to ``tangent_dir`` at P1.

    Parameters
    ----------
    p1 : (x, y)
        Arc start point.
    tangent_dir : float
        Tangent direction at P1 in radians (math convention: 0 = +X, CCW positive).
    p2 : (x, y)
        Arc end point.

    Returns
    -------
    ArcResult or None
        ``None`` if the chord is degenerate (P1 ≈ P2) or the endpoint lies
        on the tangent line (infinite radius → straight segment).
    """
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    chord_len_sq = dx * dx + dy * dy
    if chord_len_sq < _DEGENERATE_TOL * _DEGENERATE_TOL:
        return None  # P1 ≈ P2

    # Unit normal to tangent, rotated 90° CCW
    nx = -math.sin(tangent_dir)
    ny = math.cos(tangent_dir)

    # Signed perpendicular distance of chord onto normal
    chord_dot_n = dx * nx + dy * ny
    if abs(chord_dot_n) < _DEGENERATE_TOL:
        return None  # P2 on tangent line → straight

    # Signed radius: positive = center on left of tangent direction
    R = chord_len_sq / (2.0 * chord_dot_n)

    # Arc center
    cx = p1[0] + R * nx
    cy = p1[1] + R * ny

    # Included angle via atan2 of the two radii
    # Vector from center to P1
    r1x = p1[0] - cx
    r1y = p1[1] - cy
    # Vector from center to P2
    r2x = p2[0] - cx
    r2y = p2[1] - cy

    # Signed angle from r1 to r2 (positive = CCW)
    cross = r1x * r2y - r1y * r2x
    dot = r1x * r2x + r1y * r2y
    included_angle = math.atan2(cross, dot)  # range (-π, π]

    # Bulge = tan(included_angle / 4)
    bulge = math.tan(included_angle / 4.0)

    return ArcResult(radius=R, bulge=bulge, center=(cx, cy))


def arc_through_three_points(
    p1: Point2D,
    p_mid: Point2D,
    p2: Point2D,
) -> Optional[ArcResult]:
    """Fit a circular arc through 3 non-collinear points.

    Used for the "tapering width wholly within a curve" case: sample the
    ideal linearly-tapered-offset curve at the start, midstation, and
    end of the bridge, then fit an arc through all three.  The arc
    matches the ideal curve symmetrically (deviation between samples is
    balanced).

    Parameters
    ----------
    p1, p_mid, p2 :
        Three points on the desired arc, in traversal order from p1 to
        p2 via p_mid.

    Returns
    -------
    ArcResult or None
        ``None`` if the three points are collinear (infinite radius).
    """
    x1, y1 = p1
    xm, ym = p_mid
    x2, y2 = p2

    # Center C is equidistant from p1, p_mid, p2.  Solve two perpendicular-
    # bisector equations (one from p1-to-p_mid, one from p1-to-p2):
    #   2(p_mid - p1) · C = |p_mid|² - |p1|²
    #   2(p2 - p1)    · C = |p2|²    - |p1|²
    A1 = 2.0 * (xm - x1)
    B1 = 2.0 * (ym - y1)
    K1 = xm * xm + ym * ym - x1 * x1 - y1 * y1

    A2 = 2.0 * (x2 - x1)
    B2 = 2.0 * (y2 - y1)
    K2 = x2 * x2 + y2 * y2 - x1 * x1 - y1 * y1

    det = A1 * B2 - A2 * B1
    if abs(det) < _DEGENERATE_TOL:
        return None  # Three points collinear

    cx = (K1 * B2 - K2 * B1) / det
    cy = (A1 * K2 - A2 * K1) / det

    R = math.hypot(x1 - cx, y1 - cy)

    # Determine the included angle from p1 → p_mid → p2, signed.
    # Sum the two signed angle steps (r1→rm and rm→r2).  For a well-
    # ordered triple both steps have the same sign and the total is the
    # signed traversal angle.
    r1x, r1y = x1 - cx, y1 - cy
    rmx, rmy = xm - cx, ym - cy
    r2x, r2y = x2 - cx, y2 - cy

    cross_1m = r1x * rmy - r1y * rmx
    dot_1m = r1x * rmx + r1y * rmy
    angle_1m = math.atan2(cross_1m, dot_1m)

    cross_m2 = rmx * r2y - rmy * r2x
    dot_m2 = rmx * r2x + rmy * r2y
    angle_m2 = math.atan2(cross_m2, dot_m2)

    included_angle = angle_1m + angle_m2

    bulge = math.tan(included_angle / 4.0)
    R_signed = R if included_angle > 0 else -R

    return ArcResult(radius=R_signed, bulge=bulge, center=(cx, cy))


# -----------------------------------------------------------------------
# Edge vertex derivation
# -----------------------------------------------------------------------

def _interp_offset(
    station: float,
    start_station: float,
    end_station: float,
    offset_start: float,
    offset_end: float,
) -> float:
    """Linearly interpolate perpendicular offset between two stations."""
    if abs(end_station - start_station) < _DEGENERATE_TOL:
        return offset_start
    t = (station - start_station) / (end_station - start_station)
    return offset_start + t * (offset_end - offset_start)


# Tolerance for "this edge has constant offset" (ft).  Inside this band
# we treat the edge as constant width.
_CONSTANT_OFFSET_TOL = 1e-6


def is_constant_offset(offset_start: float, offset_end: float) -> bool:
    """Return True if the edge has effectively constant offset (no taper)."""
    return abs(offset_end - offset_start) < _CONSTANT_OFFSET_TOL


def _clip_segments(
    segments: List[AlignmentSegment],
    bridge_start: float,
    bridge_end: float,
) -> List[AlignmentSegment]:
    """Return segments clipped to the bridge extent, dropping zero-length ones."""
    clipped: List[AlignmentSegment] = []
    for seg in segments:
        s0 = max(seg.start_station, bridge_start)
        s1 = min(seg.end_station, bridge_end)
        if s1 <= s0 + _DEGENERATE_TOL:
            continue
        clipped.append(AlignmentSegment(
            entity_type=seg.entity_type,
            start_station=s0,
            end_station=s1,
            radius=seg.radius,
        ))
    return clipped


def derive_edge_vertices(
    *,
    segments: List[AlignmentSegment],
    bridge_start_station: float,
    bridge_end_station: float,
    offset_start: float,
    offset_end: float,
    point_at_station_offset: "Callable[[float, float], Point2D]",
    direction_at_station: "Callable[[float], float]",
    start_xy: Optional[Point2D] = None,
    end_xy: Optional[Point2D] = None,
) -> List[PlanVertex]:
    """Derive vertices for one edge of the deck (left or right).

    Strategy is gated on width-taper state and alignment geometry:

    +---------------------------------------+-------------------------------+
    | Case                                  | Logic                         |
    +=======================================+===============================+
    | Constant offset, any alignment        | Pure offset from alignment    |
    |                                       | (concentric arcs on curves)   |
    +---------------------------------------+-------------------------------+
    | Tapering, all tangent/spiral          | Linear-in-station taper       |
    +---------------------------------------+-------------------------------+
    | Tapering, wholly within a single arc  | 3-point arc fit through       |
    |                                       | start, midstation, end        |
    +---------------------------------------+-------------------------------+
    | Tapering, one tangent↔curve transition| Walk from the tangent end;    |
    |                                       | arc tangent-constrained to    |
    |                                       | preceding edge direction      |
    +---------------------------------------+-------------------------------+
    | Tapering, multi-transition (viaduct)  | Linear-in-station vertices    |
    |                                       | at every transition; arcs on  |
    |                                       | curve segments tangent to     |
    |                                       | alignment (small kinks OK)    |
    +---------------------------------------+-------------------------------+

    ``start_xy`` / ``end_xy`` override the first / last vertex
    positions (and are used as the arc-fit endpoints). The polygon
    caller passes the actual skewed bearing-corner XY here so the
    computed bulge corresponds to the chord that the polyline will
    actually draw between. When ``None``, the endpoints come from
    ``point_at_station_offset(bridge_start_or_end, offset_start_or_end)``
    — equivalent to assuming zero skew.

    Returns vertices in bridge_start → bridge_end order.  The last
    vertex's ``bulge`` is 0 — there is no "next" edge segment in this
    edge's scope.  The polygon caller sets the closing/bearing-line
    bulge.
    """
    if start_xy is None:
        start_xy = point_at_station_offset(bridge_start_station, offset_start)
    if end_xy is None:
        end_xy = point_at_station_offset(bridge_end_station, offset_end)

    clipped = _clip_segments(segments, bridge_start_station, bridge_end_station)

    # Pure fallback: no segment info at all.
    if not clipped:
        return [
            PlanVertex(start_xy[0], start_xy[1], 0.0),
            PlanVertex(end_xy[0], end_xy[1], 0.0),
        ]

    # --- Gate 1: constant offset (no taper) ---
    if is_constant_offset(offset_start, offset_end):
        return _edge_constant_offset(
            clipped, offset_start,
            point_at_station_offset, direction_at_station,
            start_xy=start_xy, end_xy=end_xy,
        )

    # --- Gate 2: tapering, dispatch on segment configuration ---
    n_segs = len(clipped)

    if n_segs == 1:
        seg = clipped[0]
        if seg.entity_type in (ENTITY_TANGENT, ENTITY_SPIRAL):
            return _edge_tapering_linear(start_xy, end_xy)
        # ARC: wholly within a curve, use 3-point arc fit
        return _edge_tapering_within_curve_3point(
            bridge_start_station, bridge_end_station,
            offset_start, offset_end, point_at_station_offset,
            start_xy=start_xy, end_xy=end_xy,
        )

    if n_segs == 2:
        a, b = clipped
        a_is_straight = a.entity_type in (ENTITY_TANGENT, ENTITY_SPIRAL)
        b_is_straight = b.entity_type in (ENTITY_TANGENT, ENTITY_SPIRAL)
        if a_is_straight and not b_is_straight:
            # tangent/spiral → curve: walk forward from the tangent
            return _edge_tapering_single_transition_forward(
                clipped, bridge_start_station, bridge_end_station,
                offset_start, offset_end, point_at_station_offset,
                start_xy=start_xy, end_xy=end_xy,
            )
        if b_is_straight and not a_is_straight:
            # curve → tangent/spiral: walk backward from the trailing tangent
            return _edge_tapering_single_transition_backward(
                clipped, bridge_start_station, bridge_end_station,
                offset_start, offset_end, point_at_station_offset,
                start_xy=start_xy, end_xy=end_xy,
            )
        # Two straight or two curve segments: fall through to viaduct logic
        # (kinks accepted at the transition).

    # --- Gate 3: viaduct (2+ transitions, or 1 transition between non-
    #     tangent segments).  Linear-in-station vertices at every transition;
    #     ARC segments get tangent-constrained-to-alignment arcs. ---
    return _edge_tapering_viaduct(
        clipped, bridge_start_station, bridge_end_station,
        offset_start, offset_end,
        point_at_station_offset, direction_at_station,
        start_xy=start_xy, end_xy=end_xy,
    )


# -----------------------------------------------------------------------
# Edge-derivation helpers (one per gating branch)
# -----------------------------------------------------------------------

def _edge_constant_offset(
    segments: List[AlignmentSegment],
    offset: float,
    point_at_station_offset: "Callable[[float, float], Point2D]",
    direction_at_station: "Callable[[float], float]",
    *,
    start_xy: Point2D,
    end_xy: Point2D,
) -> List[PlanVertex]:
    """Pure offset from alignment geometry.  Each alignment segment
    contributes its natural shape:
    - TANGENT / SPIRAL → straight (bulge 0; spiral approximated as line)
    - ARC → concentric arc, tangent-constrained to alignment direction

    ``start_xy`` / ``end_xy`` override the first / last vertex positions
    (typically the skewed bearing corners). For ARC segments at the
    ends, the bulge is recomputed using ``start_xy`` / ``end_xy`` as
    the chord endpoint so the polyline arc matches the actual chord.
    """
    vertices: List[PlanVertex] = []
    n_segs = len(segments)
    for i, seg in enumerate(segments):
        is_first = i == 0
        is_last = i == n_segs - 1

        # Pin the first/last vertex positions to start_xy/end_xy; other
        # boundary samples come from the alignment query.
        if is_first:
            x0, y0 = start_xy
        else:
            x0, y0 = point_at_station_offset(seg.start_station, offset)
        if is_last:
            x1, y1 = end_xy
        else:
            x1, y1 = point_at_station_offset(seg.end_station, offset)

        if not vertices:
            vertices.append(PlanVertex(x0, y0, 0.0))

        if seg.entity_type == ENTITY_ARC:
            tangent_dir = direction_at_station(seg.start_station)
            arc = arc_from_start_tangent_endpoint(
                (x0, y0), tangent_dir, (x1, y1),
            )
            if arc is not None:
                prev = vertices[-1]
                vertices[-1] = PlanVertex(prev.x, prev.y, arc.bulge)
        # TANGENT / SPIRAL: bulge stays 0

        vertices.append(PlanVertex(x1, y1, 0.0))

    return vertices


def _edge_tapering_linear(start_xy: Point2D, end_xy: Point2D) -> List[PlanVertex]:
    """Linear-in-station taper — single straight segment from start to end."""
    return [
        PlanVertex(start_xy[0], start_xy[1], 0.0),
        PlanVertex(end_xy[0], end_xy[1], 0.0),
    ]


def _edge_tapering_within_curve_3point(
    bridge_start: float,
    bridge_end: float,
    offset_start: float,
    offset_end: float,
    point_at_station_offset: "Callable[[float, float], Point2D]",
    *,
    start_xy: Point2D,
    end_xy: Point2D,
) -> List[PlanVertex]:
    """Tapering width wholly on one arc segment: fit through 3 points.

    Endpoints (start, end) are taken from ``start_xy`` / ``end_xy``
    (typically the skewed bearing corners — the polyline's actual
    vertices). The mid-sample comes from the alignment at midstation
    with the linearly-interpolated mid-offset. This ensures the bulge
    is correct for the chord the polyline will actually draw.
    """
    s_mid = 0.5 * (bridge_start + bridge_end)
    off_mid = 0.5 * (offset_start + offset_end)
    p_mid = point_at_station_offset(s_mid, off_mid)

    arc = arc_through_three_points(start_xy, p_mid, end_xy)
    bulge = arc.bulge if arc is not None else 0.0

    return [
        PlanVertex(start_xy[0], start_xy[1], bulge),
        PlanVertex(end_xy[0], end_xy[1], 0.0),
    ]


def _edge_tapering_single_transition_forward(
    segments: List[AlignmentSegment],
    bridge_start: float,
    bridge_end: float,
    offset_start: float,
    offset_end: float,
    point_at_station_offset: "Callable[[float, float], Point2D]",
    *,
    start_xy: Point2D,
    end_xy: Point2D,
) -> List[PlanVertex]:
    """tangent/spiral → curve, walking forward.

    The tangent segment is a straight line from ``start_xy`` to the
    transition point. Its direction is determined by these two endpoints
    (NOT the alignment tangent — for tapering the two differ). The
    curve segment is an arc tangent-constrained to that direction at
    the transition, ending at ``end_xy``.
    """
    tan_seg, arc_seg = segments

    off_at_transition = _interp_offset(
        tan_seg.end_station, bridge_start, bridge_end,
        offset_start, offset_end,
    )
    p0 = start_xy
    p_trans = point_at_station_offset(tan_seg.end_station, off_at_transition)
    p1 = end_xy

    # Direction of the tangent edge segment (skewed-corner-aware).
    edge_dir = math.atan2(p_trans[1] - p0[1], p_trans[0] - p0[0])

    arc = arc_from_start_tangent_endpoint(p_trans, edge_dir, p1)
    arc_bulge = arc.bulge if arc is not None else 0.0

    return [
        PlanVertex(p0[0], p0[1], 0.0),
        PlanVertex(p_trans[0], p_trans[1], arc_bulge),
        PlanVertex(p1[0], p1[1], 0.0),
    ]


def _edge_tapering_single_transition_backward(
    segments: List[AlignmentSegment],
    bridge_start: float,
    bridge_end: float,
    offset_start: float,
    offset_end: float,
    point_at_station_offset: "Callable[[float, float], Point2D]",
    *,
    start_xy: Point2D,
    end_xy: Point2D,
) -> List[PlanVertex]:
    """curve → tangent/spiral, walking backward from the trailing tangent.

    The trailing tangent's forward direction is determined by the
    transition point and ``end_xy``. The leading curve is fit as an
    arc whose forward tangent at the transition matches that direction.
    """
    arc_seg, tan_seg = segments

    off_at_transition = _interp_offset(
        tan_seg.start_station, bridge_start, bridge_end,
        offset_start, offset_end,
    )
    p0 = start_xy
    p_trans = point_at_station_offset(tan_seg.start_station, off_at_transition)
    p1 = end_xy

    edge_dir_fwd = math.atan2(p1[1] - p_trans[1], p1[0] - p_trans[0])

    # Fit backward (p_trans → p0); reversing flips the bulge sign.
    arc_backward = arc_from_start_tangent_endpoint(
        p_trans, edge_dir_fwd + math.pi, p0,
    )
    arc_bulge_fwd = -arc_backward.bulge if arc_backward is not None else 0.0

    return [
        PlanVertex(p0[0], p0[1], arc_bulge_fwd),
        PlanVertex(p_trans[0], p_trans[1], 0.0),
        PlanVertex(p1[0], p1[1], 0.0),
    ]


def _edge_tapering_viaduct(
    segments: List[AlignmentSegment],
    bridge_start: float,
    bridge_end: float,
    offset_start: float,
    offset_end: float,
    point_at_station_offset: "Callable[[float, float], Point2D]",
    direction_at_station: "Callable[[float], float]",
    *,
    start_xy: Point2D,
    end_xy: Point2D,
) -> List[PlanVertex]:
    """Multi-transition (viaduct) tapering.  Vertices placed at every
    segment boundary at linearly-interpolated offsets.  ARC segments
    get arcs tangent to the alignment direction at their start (NOT
    tangent to the preceding edge segment).  Small kinks accepted at
    transitions.

    First and last vertices are pinned to ``start_xy`` / ``end_xy``;
    arc bulges on the first / last ARC segment are recomputed against
    these endpoints so the polyline arc shape matches the chord.
    """
    vertices: List[PlanVertex] = []
    n_segs = len(segments)
    for i, seg in enumerate(segments):
        is_first = i == 0
        is_last = i == n_segs - 1

        off_seg_start = _interp_offset(
            seg.start_station, bridge_start, bridge_end,
            offset_start, offset_end,
        )
        off_seg_end = _interp_offset(
            seg.end_station, bridge_start, bridge_end,
            offset_start, offset_end,
        )

        if is_first:
            x0, y0 = start_xy
        else:
            x0, y0 = point_at_station_offset(seg.start_station, off_seg_start)
        if is_last:
            x1, y1 = end_xy
        else:
            x1, y1 = point_at_station_offset(seg.end_station, off_seg_end)

        if not vertices:
            vertices.append(PlanVertex(x0, y0, 0.0))

        if seg.entity_type == ENTITY_ARC:
            tangent_dir = direction_at_station(seg.start_station)
            arc = arc_from_start_tangent_endpoint(
                (x0, y0), tangent_dir, (x1, y1),
            )
            if arc is not None:
                prev = vertices[-1]
                vertices[-1] = PlanVertex(prev.x, prev.y, arc.bulge)

        vertices.append(PlanVertex(x1, y1, 0.0))

    return vertices


# -----------------------------------------------------------------------
# Full polygon assembly
# -----------------------------------------------------------------------

def derive_deck_plan_polygon(
    *,
    segments: List[AlignmentSegment],
    bridge_start_station: float,
    bridge_end_station: float,
    start_left_offset: float,
    start_right_offset: float,
    end_left_offset: float,
    end_right_offset: float,
    start_skew_deg: float,
    end_skew_deg: float,
    point_at_station_offset: "Callable[[float, float], Point2D]",
    direction_at_station: "Callable[[float], float]",
    point_on_skewed_bearing: "Callable[[float, float, float], Point2D]",
) -> List[PlanVertex]:
    """Derive the complete closed deck plan polygon.

    Returns vertices in CCW order with bulges.  The polygon is closed
    implicitly (last vertex connects back to first via the last vertex's
    bulge).

    Parameters
    ----------
    segments :
        Alignment entity ranges covering the bridge extent, sorted by
        station.
    bridge_start_station, bridge_end_station :
        Stations at the start and end bearing lines.
    start_left_offset, start_right_offset :
        Perpendicular offsets of the left and right deck edges at the
        start bearing.  Left is negative, right is positive.
    end_left_offset, end_right_offset :
        Same at the end bearing.
    start_skew_deg, end_skew_deg :
        Skew angles at start and end supports.
    point_at_station_offset :
        ``f(station, perp_offset) -> (x, y)`` — alignment query.
    direction_at_station :
        ``f(station) -> radians`` — alignment tangent direction.
    point_on_skewed_bearing :
        ``f(station, skew_deg, perp_offset) -> (x, y)`` — point on a
        skewed bearing line at a support.

    Returns
    -------
    List of PlanVertex forming the closed CCW polygon.
    """
    # ---- 1. Bearing-line corner points ----
    start_left_xy = point_on_skewed_bearing(
        bridge_start_station, start_skew_deg, start_left_offset,
    )
    start_right_xy = point_on_skewed_bearing(
        bridge_start_station, start_skew_deg, start_right_offset,
    )
    end_right_xy = point_on_skewed_bearing(
        bridge_end_station, end_skew_deg, end_right_offset,
    )
    end_left_xy = point_on_skewed_bearing(
        bridge_end_station, end_skew_deg, end_left_offset,
    )

    # ---- 2. Right edge: start_right → end_right (ahead-station) ----
    # Pass the skewed bearing corners as start_xy/end_xy so the arc
    # bulges are computed for the chord that the polyline will actually
    # draw — for skewed supports the skewed corners differ from the
    # alignment-perpendicular crossings, and using the un-skewed chord
    # gives wrong arc shapes (verified by midstation width measurement).
    right_edge = derive_edge_vertices(
        segments=segments,
        bridge_start_station=bridge_start_station,
        bridge_end_station=bridge_end_station,
        offset_start=start_right_offset,
        offset_end=end_right_offset,
        point_at_station_offset=point_at_station_offset,
        direction_at_station=direction_at_station,
        start_xy=start_right_xy,
        end_xy=end_right_xy,
    )

    # ---- 3. Left edge: start_left → end_left (ahead-station) ----
    left_edge = derive_edge_vertices(
        segments=segments,
        bridge_start_station=bridge_start_station,
        bridge_end_station=bridge_end_station,
        offset_start=start_left_offset,
        offset_end=end_left_offset,
        point_at_station_offset=point_at_station_offset,
        direction_at_station=direction_at_station,
        start_xy=start_left_xy,
        end_xy=end_left_xy,
    )

    # ---- 4. Assemble polygon (CCW) ----
    #
    # Winding:
    #   start_left → start_right        (start bearing, straight)
    #   start_right → ... → end_right   (right edge, taper/arcs)
    #   end_right → end_left            (end bearing, straight)
    #   end_left → ... → start_left     (left edge, reversed, taper/arcs)
    #
    # The right edge is traversed forward (start→end).
    # The left edge is traversed backward (end→start) for CCW winding.

    polygon: List[PlanVertex] = []

    # Start bearing: start_left → start_right (straight segment)
    polygon.append(PlanVertex(start_left_xy[0], start_left_xy[1], 0.0))

    # Right edge (skip first vertex — it overlaps with start_right
    # bearing corner.  Use bearing corner's exact position instead.)
    # The bearing corner is start_right; the first right_edge vertex
    # is computed from the alignment at bridge_start_station — they
    # should be very close but the bearing corner respects skew.
    polygon.append(PlanVertex(start_right_xy[0], start_right_xy[1],
                              right_edge[0].bulge if right_edge else 0.0))

    # Intermediate + final right-edge vertices (skip first, which is the
    # start corner we already placed)
    for v in right_edge[1:-1]:
        polygon.append(v)

    # End bearing: end_right → end_left (straight segment)
    # Use the exact bearing corner for end_right, taking the last
    # right-edge vertex's bulge as the segment into it.
    polygon.append(PlanVertex(end_right_xy[0], end_right_xy[1], 0.0))
    polygon.append(PlanVertex(end_left_xy[0], end_left_xy[1],
                              0.0))  # bulge set below from left_edge

    # Left edge, reversed (end→start direction for CCW).
    # Reverse the left_edge list.  When reversing, the bulge on vertex i
    # (which connects to vertex i+1 in forward order) now connects to
    # vertex i-1 in the reversed list.  So in the reversed list, vertex
    # j's bulge should be the *previous* vertex's (j+1 in original) bulge,
    # negated (reversing traversal direction flips the arc sign).
    left_reversed = _reverse_edge_with_bulges(left_edge)

    # The first vertex of left_reversed corresponds to end_left (already
    # placed as the bearing corner).  Assign its bulge to that corner.
    if left_reversed:
        end_left_idx = len(polygon) - 1
        polygon[end_left_idx] = PlanVertex(
            polygon[end_left_idx].x,
            polygon[end_left_idx].y,
            left_reversed[0].bulge,
        )

    # Intermediate reversed-left-edge vertices.  Skip first (= end_left,
    # already placed as the bearing corner) and skip last (= start_left,
    # which is polygon[0] — the polygon is closed implicitly, so we do
    # NOT duplicate it).
    #
    # The closing bulge (last polygon vertex → polygon[0]) is carried by
    # the last vertex we actually append:
    #   - No intermediates (2-element reversed): end_left already has the
    #     closing bulge from left_reversed[0].bulge.
    #   - With intermediates: left_reversed[-2] is the last intermediate,
    #     and its bulge is the segment leading to start_left.
    for v in left_reversed[1:-1]:
        polygon.append(v)

    return polygon


def _reverse_edge_with_bulges(edge: List[PlanVertex]) -> List[PlanVertex]:
    """Reverse an edge vertex list, flipping bulge associations.

    In the forward list, vertex[i].bulge describes the segment from
    vertex[i] to vertex[i+1].  When we reverse traversal direction:
    - The segment that was vertex[i] → vertex[i+1] becomes
      vertex[i+1] → vertex[i].
    - Reversing an arc flips the bulge sign (the arc bows to the
      opposite side relative to the new chord direction).

    So in the reversed list, the vertex that was at position i gets the
    negated bulge of the vertex at position i-1 in the original list.
    The last vertex in the reversed list (= first in original) gets
    bulge 0 (its original bulge described a segment that no longer
    exists in this edge's scope — it would be the bearing-line segment).
    """
    if len(edge) <= 1:
        return list(edge)

    n = len(edge)
    reversed_verts: List[PlanVertex] = []
    for j in range(n):
        orig_idx = n - 1 - j
        if j == n - 1:
            # Last vertex in reversed list → no next segment in this edge
            bulge = 0.0
        else:
            # This vertex was originally at orig_idx.
            # The segment from this vertex goes to orig_idx - 1 in original.
            # That segment was described by edge[orig_idx - 1].bulge.
            # Reverse direction → negate.
            bulge = -edge[orig_idx - 1].bulge
        v = edge[orig_idx]
        reversed_verts.append(PlanVertex(v.x, v.y, bulge))

    return reversed_verts


# -----------------------------------------------------------------------
# Convenience: straight-alignment fallback
# -----------------------------------------------------------------------

def straight_deck_polygon(
    *,
    start_left: Point2D,
    start_right: Point2D,
    end_right: Point2D,
    end_left: Point2D,
) -> List[PlanVertex]:
    """Build a 4-vertex rectangle/trapezoid polygon for a straight bridge.

    All bulges are 0 (straight segments).  CCW winding.
    """
    return [
        PlanVertex(start_left[0], start_left[1], 0.0),
        PlanVertex(start_right[0], start_right[1], 0.0),
        PlanVertex(end_right[0], end_right[1], 0.0),
        PlanVertex(end_left[0], end_left[1], 0.0),
    ]
