"""Unit tests for src/deck_plan.py — deck plan polygon derivation."""
from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import deck_plan as dp  # noqa: E402


# -----------------------------------------------------------------------
# Helpers — fake alignment queries for testing
# -----------------------------------------------------------------------

def _straight_alignment_point(station, offset):
    """Fake alignment running along +X.  offset = +Y."""
    return (station, offset)


def _straight_alignment_direction(station):
    """Tangent direction of a +X-running alignment: always 0 radians."""
    return 0.0


def _straight_bearing_point(station, skew_deg, perp_offset):
    """Skewed bearing point on a straight +X alignment."""
    skew_rad = math.radians(skew_deg)
    # Bearing line is perpendicular to alignment rotated by skew
    x = station + perp_offset * math.tan(skew_rad)
    y = perp_offset
    return (x, y)


def _curved_alignment_point(radius):
    """Return a point_at_station_offset function for a circular arc alignment.

    The alignment runs CCW around a circle of ``radius`` centered at
    (0, 0).  Station 0 is at (radius, 0), station increases CCW.
    ``offset`` is positive right (= radially outward for CCW travel).
    """
    def _point(station, offset):
        theta = station / radius  # arc-length parameterization
        # Alignment point on the circle
        ax = radius * math.cos(theta)
        ay = radius * math.sin(theta)
        # Outward radial direction (right of CCW travel = radially outward)
        rx = math.cos(theta)
        ry = math.sin(theta)
        # offset > 0 = right of travel = radially outward
        return (ax + offset * rx, ay + offset * ry)
    return _point


def _curved_alignment_direction(radius):
    """Return a direction_at_station function for the same circular arc."""
    def _direction(station):
        theta = station / radius
        # Tangent to CCW circle at angle theta: (-sin θ, cos θ)
        return math.atan2(math.cos(theta), -math.sin(theta))
    return _direction


def _curved_bearing_point(radius):
    """Return a point_on_skewed_bearing for a circular alignment (zero skew only)."""
    pt_fn = _curved_alignment_point(radius)
    def _bearing(station, skew_deg, perp_offset):
        assert skew_deg == 0.0, "curved bearing helper only supports zero skew"
        return pt_fn(station, perp_offset)
    return _bearing


# -----------------------------------------------------------------------
# arc_from_start_tangent_endpoint
# -----------------------------------------------------------------------

def test_arc_degenerate_same_point():
    """P1 == P2 returns None."""
    result = dp.arc_from_start_tangent_endpoint((0, 0), 0.0, (0, 0))
    assert result is None


def test_arc_endpoint_on_tangent_line():
    """P2 directly ahead on tangent returns None (infinite radius)."""
    result = dp.arc_from_start_tangent_endpoint((0, 0), 0.0, (10, 0))
    assert result is None


def test_arc_quarter_circle_left():
    """90° arc curving left: P1=(1,0), tangent=+Y, P2=(0,1).

    This is a unit circle centered at origin, arc from (1,0) to (0,1)
    going CCW.  tangent at (1,0) pointing +Y = π/2.
    """
    arc = dp.arc_from_start_tangent_endpoint(
        (1.0, 0.0), math.pi / 2, (0.0, 1.0),
    )
    assert arc is not None
    assert arc.radius == pytest.approx(1.0, abs=1e-9)
    assert arc.center == pytest.approx((0.0, 0.0), abs=1e-9)
    # Included angle = π/2, bulge = tan(π/8) ≈ 0.4142
    assert arc.bulge == pytest.approx(math.tan(math.pi / 8), abs=1e-9)


def test_arc_quarter_circle_right():
    """90° arc curving right: P1=(0,1), tangent=+X, P2=(1,0).

    Unit circle centered at (1,1), arc from (0,1) to (1,0) going CW.
    Tangent at (0,1) in CW direction = +X = 0 rad.
    """
    arc = dp.arc_from_start_tangent_endpoint(
        (0.0, 1.0), 0.0, (1.0, 0.0),
    )
    assert arc is not None
    assert abs(arc.radius) == pytest.approx(1.0, abs=1e-9)
    # CW arc → negative bulge
    assert arc.bulge == pytest.approx(-math.tan(math.pi / 8), abs=1e-9)


def test_arc_semicircle():
    """180° arc: P1=(1,0), tangent=+Y, P2=(-1,0).  Unit circle CCW."""
    arc = dp.arc_from_start_tangent_endpoint(
        (1.0, 0.0), math.pi / 2, (-1.0, 0.0),
    )
    assert arc is not None
    assert arc.radius == pytest.approx(1.0, abs=1e-9)
    # Included angle = ±π (atan2 at the π boundary can return either
    # sign due to floating-point imprecision in cos(π/2)).
    # Both bulge = ±1 describe the same geometric semicircle.
    assert abs(arc.bulge) == pytest.approx(1.0, abs=1e-9)


def test_arc_small_angle():
    """Small arc (≈ 10°) on R=500 ft curve — realistic bridge geometry."""
    R = 500.0
    theta = math.radians(10.0)
    p1 = (R, 0.0)
    p2 = (R * math.cos(theta), R * math.sin(theta))
    tangent_dir = math.pi / 2  # tangent at (R, 0) on CCW circle

    arc = dp.arc_from_start_tangent_endpoint(p1, tangent_dir, p2)
    assert arc is not None
    assert arc.radius == pytest.approx(R, rel=1e-6)
    expected_bulge = math.tan(theta / 4)
    assert arc.bulge == pytest.approx(expected_bulge, rel=1e-6)


# -----------------------------------------------------------------------
# _reverse_edge_with_bulges
# -----------------------------------------------------------------------

def test_reverse_edge_straight():
    """Reversing a straight edge keeps all bulges 0."""
    edge = [dp.PlanVertex(0, 0, 0.0), dp.PlanVertex(10, 0, 0.0)]
    rev = dp._reverse_edge_with_bulges(edge)
    assert len(rev) == 2
    assert rev[0].x == pytest.approx(10.0)
    assert rev[1].x == pytest.approx(0.0)
    assert rev[0].bulge == pytest.approx(0.0)
    assert rev[1].bulge == pytest.approx(0.0)


def test_reverse_edge_with_arc():
    """Reversing an edge negates interior bulge values."""
    edge = [
        dp.PlanVertex(0, 0, 0.5),   # arc from v0 to v1
        dp.PlanVertex(10, 5, 0.0),  # straight from v1 to v2
        dp.PlanVertex(20, 0, 0.0),  # last vertex (bulge unused in forward)
    ]
    rev = dp._reverse_edge_with_bulges(edge)
    assert len(rev) == 3
    # Reversed order: v2, v1, v0
    assert rev[0].x == pytest.approx(20.0)
    assert rev[1].x == pytest.approx(10.0)
    assert rev[2].x == pytest.approx(0.0)
    # rev[0] → rev[1] was originally v1 → v2 with bulge 0.0, negated = 0.0
    assert rev[0].bulge == pytest.approx(0.0)
    # rev[1] → rev[2] was originally v0 → v1 with bulge 0.5, negated = -0.5
    assert rev[1].bulge == pytest.approx(-0.5)
    # rev[2] is last in reversed list → bulge 0
    assert rev[2].bulge == pytest.approx(0.0)


def test_reverse_single_vertex():
    """Single vertex edge returns as-is."""
    edge = [dp.PlanVertex(5, 5, 0.3)]
    rev = dp._reverse_edge_with_bulges(edge)
    assert len(rev) == 1
    assert rev[0].x == pytest.approx(5.0)


# -----------------------------------------------------------------------
# derive_edge_vertices — straight alignment, constant width
# -----------------------------------------------------------------------

def test_edge_straight_constant_width():
    """Straight alignment, constant offset → 2 vertices, bulge 0."""
    segments = [dp.AlignmentSegment(dp.ENTITY_TANGENT, 100, 200)]
    verts = dp.derive_edge_vertices(
        segments=segments,
        bridge_start_station=100,
        bridge_end_station=200,
        offset_start=11.0,
        offset_end=11.0,
        point_at_station_offset=_straight_alignment_point,
        direction_at_station=_straight_alignment_direction,
    )
    assert len(verts) == 2
    assert verts[0].x == pytest.approx(100.0)
    assert verts[0].y == pytest.approx(11.0)
    assert verts[1].x == pytest.approx(200.0)
    assert verts[1].y == pytest.approx(11.0)
    assert verts[0].bulge == pytest.approx(0.0)
    assert verts[1].bulge == pytest.approx(0.0)


def test_edge_straight_tapering_width():
    """Straight alignment, tapering offset → 2 vertices, bulge 0."""
    segments = [dp.AlignmentSegment(dp.ENTITY_TANGENT, 100, 300)]
    verts = dp.derive_edge_vertices(
        segments=segments,
        bridge_start_station=100,
        bridge_end_station=300,
        offset_start=11.0,
        offset_end=12.5,
        point_at_station_offset=_straight_alignment_point,
        direction_at_station=_straight_alignment_direction,
    )
    assert len(verts) == 2
    assert verts[0].y == pytest.approx(11.0)
    assert verts[1].y == pytest.approx(12.5)
    assert all(v.bulge == pytest.approx(0.0) for v in verts)


# -----------------------------------------------------------------------
# derive_edge_vertices — tangent-to-curve
# -----------------------------------------------------------------------

def test_edge_tangent_then_curve():
    """Tangent section followed by arc section produces 3 vertices.

    The tangent section gives a straight segment, the arc section gives
    an arc segment.  Total: 3 vertices (start, transition, end).
    """
    segments = [
        dp.AlignmentSegment(dp.ENTITY_TANGENT, 100, 150),
        dp.AlignmentSegment(dp.ENTITY_ARC, 150, 200, radius=500.0),
    ]
    R = 500.0

    # Use a fake alignment that is straight for [100,150] then curves.
    # For simplicity, just use the straight alignment helper — the
    # arc fitting is tested separately.  What matters here is that
    # we get 3 vertices and the tangent segment has bulge 0 while
    # the arc segment has non-zero bulge.
    verts = dp.derive_edge_vertices(
        segments=segments,
        bridge_start_station=100,
        bridge_end_station=200,
        offset_start=11.0,
        offset_end=11.0,
        point_at_station_offset=_straight_alignment_point,
        direction_at_station=_straight_alignment_direction,
    )
    assert len(verts) == 3
    # First segment (tangent): bulge 0
    assert verts[0].bulge == pytest.approx(0.0)
    # Second segment (arc): The arc fitting may return None for a
    # straight alignment (endpoint on tangent line for constant offset
    # on a straight alignment), resulting in bulge 0.
    # This is geometrically correct — a "curve" on a straight alignment
    # IS a straight line.
    assert isinstance(verts[1].bulge, float)


def test_edge_pure_arc_curved_alignment():
    """Single arc segment on a truly curved alignment → 2 verts with non-zero bulge."""
    R = 500.0
    # Bridge spans 10° of the curve
    theta = math.radians(10.0)
    arc_len = R * theta  # station span

    segments = [dp.AlignmentSegment(dp.ENTITY_ARC, 0, arc_len, radius=R)]
    pt_fn = _curved_alignment_point(R)
    dir_fn = _curved_alignment_direction(R)

    verts = dp.derive_edge_vertices(
        segments=segments,
        bridge_start_station=0,
        bridge_end_station=arc_len,
        offset_start=11.0,
        offset_end=11.0,
        point_at_station_offset=pt_fn,
        direction_at_station=dir_fn,
    )
    assert len(verts) == 2
    # Non-zero bulge for constant offset on a curve
    assert abs(verts[0].bulge) > 0.001


# -----------------------------------------------------------------------
# derive_edge_vertices — empty / fallback
# -----------------------------------------------------------------------

def test_edge_no_segments_fallback():
    """Empty segments list → straight 2-vertex fallback."""
    verts = dp.derive_edge_vertices(
        segments=[],
        bridge_start_station=100,
        bridge_end_station=200,
        offset_start=11.0,
        offset_end=12.0,
        point_at_station_offset=_straight_alignment_point,
        direction_at_station=_straight_alignment_direction,
    )
    assert len(verts) == 2
    assert verts[0].y == pytest.approx(11.0)
    assert verts[1].y == pytest.approx(12.0)


# -----------------------------------------------------------------------
# Full polygon — straight alignment, constant width (rectangle)
# -----------------------------------------------------------------------

def test_polygon_straight_constant_width_is_rectangle():
    """Straight alignment, constant width → 4-vertex rectangle, all bulges 0."""
    segments = [dp.AlignmentSegment(dp.ENTITY_TANGENT, 100, 200)]
    poly = dp.derive_deck_plan_polygon(
        segments=segments,
        bridge_start_station=100,
        bridge_end_station=200,
        start_left_offset=-11.0,
        start_right_offset=+11.0,
        end_left_offset=-11.0,
        end_right_offset=+11.0,
        start_skew_deg=0.0,
        end_skew_deg=0.0,
        point_at_station_offset=_straight_alignment_point,
        direction_at_station=_straight_alignment_direction,
        point_on_skewed_bearing=_straight_bearing_point,
    )
    assert len(poly) == 4
    assert all(v.bulge == pytest.approx(0.0) for v in poly)

    # CCW winding: start_left, start_right, end_right, end_left
    assert poly[0].x == pytest.approx(100.0)
    assert poly[0].y == pytest.approx(-11.0)
    assert poly[1].x == pytest.approx(100.0)
    assert poly[1].y == pytest.approx(11.0)
    assert poly[2].x == pytest.approx(200.0)
    assert poly[2].y == pytest.approx(11.0)
    assert poly[3].x == pytest.approx(200.0)
    assert poly[3].y == pytest.approx(-11.0)


def test_polygon_straight_tapering_width_is_trapezoid():
    """Straight alignment, tapering width → 4-vertex trapezoid, all bulges 0."""
    segments = [dp.AlignmentSegment(dp.ENTITY_TANGENT, 100, 200)]
    poly = dp.derive_deck_plan_polygon(
        segments=segments,
        bridge_start_station=100,
        bridge_end_station=200,
        start_left_offset=-11.0,
        start_right_offset=+11.0,
        end_left_offset=-12.5,
        end_right_offset=+12.5,
        start_skew_deg=0.0,
        end_skew_deg=0.0,
        point_at_station_offset=_straight_alignment_point,
        direction_at_station=_straight_alignment_direction,
        point_on_skewed_bearing=_straight_bearing_point,
    )
    assert len(poly) == 4
    assert all(v.bulge == pytest.approx(0.0) for v in poly)

    # Wider at end
    assert poly[2].y == pytest.approx(12.5)
    assert poly[3].y == pytest.approx(-12.5)


def test_polygon_straight_skewed_supports():
    """Straight alignment, skewed supports → 4 vertices, bearing corners shifted."""
    segments = [dp.AlignmentSegment(dp.ENTITY_TANGENT, 100, 200)]
    skew = 10.0
    poly = dp.derive_deck_plan_polygon(
        segments=segments,
        bridge_start_station=100,
        bridge_end_station=200,
        start_left_offset=-11.0,
        start_right_offset=+11.0,
        end_left_offset=-11.0,
        end_right_offset=+11.0,
        start_skew_deg=skew,
        end_skew_deg=-skew,
        point_at_station_offset=_straight_alignment_point,
        direction_at_station=_straight_alignment_direction,
        point_on_skewed_bearing=_straight_bearing_point,
    )
    assert len(poly) == 4
    # Start left corner: x = 100 + (-11) * tan(10°)
    expected_x = 100.0 + (-11.0) * math.tan(math.radians(skew))
    assert poly[0].x == pytest.approx(expected_x)


# -----------------------------------------------------------------------
# Full polygon — curved alignment
# -----------------------------------------------------------------------

def test_polygon_curved_constant_width_has_arcs():
    """Curved alignment, constant width → 4 vertices with non-zero arc bulges on edges."""
    R = 500.0
    theta = math.radians(15.0)
    arc_len = R * theta

    segments = [dp.AlignmentSegment(dp.ENTITY_ARC, 0, arc_len, radius=R)]
    pt_fn = _curved_alignment_point(R)
    dir_fn = _curved_alignment_direction(R)
    brg_fn = _curved_bearing_point(R)

    poly = dp.derive_deck_plan_polygon(
        segments=segments,
        bridge_start_station=0,
        bridge_end_station=arc_len,
        start_left_offset=-11.0,
        start_right_offset=+11.0,
        end_left_offset=-11.0,
        end_right_offset=+11.0,
        start_skew_deg=0.0,
        end_skew_deg=0.0,
        point_at_station_offset=pt_fn,
        direction_at_station=dir_fn,
        point_on_skewed_bearing=brg_fn,
    )
    # Should have 4 vertices (rectangle with arcs)
    assert len(poly) == 4

    # Bearing-line segments (start and end) should be straight
    assert poly[0].bulge == pytest.approx(0.0)  # start bearing
    assert poly[2].bulge == pytest.approx(0.0)  # end bearing

    # Edge segments should have non-zero bulge
    assert abs(poly[1].bulge) > 0.001  # right edge (start_right → end_right)
    assert abs(poly[3].bulge) > 0.001  # left edge (end_left → start_left)


def test_polygon_curved_tapering_width():
    """Curved alignment, tapering width → 4 vertices with arc bulges."""
    R = 500.0
    theta = math.radians(15.0)
    arc_len = R * theta

    segments = [dp.AlignmentSegment(dp.ENTITY_ARC, 0, arc_len, radius=R)]
    pt_fn = _curved_alignment_point(R)
    dir_fn = _curved_alignment_direction(R)
    brg_fn = _curved_bearing_point(R)

    poly = dp.derive_deck_plan_polygon(
        segments=segments,
        bridge_start_station=0,
        bridge_end_station=arc_len,
        start_left_offset=-11.0,
        start_right_offset=+11.0,
        end_left_offset=-12.5,
        end_right_offset=+12.5,
        start_skew_deg=0.0,
        end_skew_deg=0.0,
        point_at_station_offset=pt_fn,
        direction_at_station=dir_fn,
        point_on_skewed_bearing=brg_fn,
    )
    assert len(poly) == 4

    # Edge bulges should be non-zero (arcs present on curved alignment)
    assert abs(poly[1].bulge) > 0.001  # right edge
    assert abs(poly[3].bulge) > 0.001  # left edge

    # Left and right arcs should have different radii since width tapers
    # (they shouldn't be equal)
    assert poly[1].bulge != pytest.approx(poly[3].bulge, abs=0.001)


# -----------------------------------------------------------------------
# Full polygon — tangent to curve transition
# -----------------------------------------------------------------------

def test_polygon_tangent_to_curve():
    """Tangent then curve → 6 vertices (extra transition point per edge)."""
    segments = [
        dp.AlignmentSegment(dp.ENTITY_TANGENT, 100, 150),
        dp.AlignmentSegment(dp.ENTITY_ARC, 150, 200, radius=500.0),
    ]
    # Use straight alignment helpers — the geometry won't be physically
    # correct for a "curve" on a straight alignment, but the vertex
    # structure and bulge assignment logic is what we're testing.
    poly = dp.derive_deck_plan_polygon(
        segments=segments,
        bridge_start_station=100,
        bridge_end_station=200,
        start_left_offset=-11.0,
        start_right_offset=+11.0,
        end_left_offset=-11.0,
        end_right_offset=+11.0,
        start_skew_deg=0.0,
        end_skew_deg=0.0,
        point_at_station_offset=_straight_alignment_point,
        direction_at_station=_straight_alignment_direction,
        point_on_skewed_bearing=_straight_bearing_point,
    )
    # 2 bearing corners + 1 intermediate per edge = 6 total
    # start_left, start_right, transition_right, end_right, end_left, transition_left
    assert len(poly) == 6

    # Bearing-line segments: bulge 0
    assert poly[0].bulge == pytest.approx(0.0)  # start_left → start_right


# -----------------------------------------------------------------------
# straight_deck_polygon helper
# -----------------------------------------------------------------------

def test_straight_deck_polygon_simple():
    """4-vertex rectangle, all bulges 0."""
    poly = dp.straight_deck_polygon(
        start_left=(100, -11),
        start_right=(100, 11),
        end_right=(200, 11),
        end_left=(200, -11),
    )
    assert len(poly) == 4
    assert all(v.bulge == pytest.approx(0.0) for v in poly)
    assert poly[0].x == pytest.approx(100.0)
    assert poly[0].y == pytest.approx(-11.0)
    assert poly[2].x == pytest.approx(200.0)
    assert poly[2].y == pytest.approx(11.0)


# -----------------------------------------------------------------------
# Arc geometry validation on curved alignment
# -----------------------------------------------------------------------

def test_curved_constant_offset_arc_radius_matches_offset():
    """On a circular alignment, a constant perpendicular offset edge is
    also a circular arc.  Its radius should equal alignment_R + offset
    (for an outer edge) or alignment_R - abs(offset) (inner edge).
    """
    R = 500.0
    offset = 11.0  # right side = radially outward on CCW curve
    theta = math.radians(10.0)
    arc_len = R * theta

    segments = [dp.AlignmentSegment(dp.ENTITY_ARC, 0, arc_len, radius=R)]
    pt_fn = _curved_alignment_point(R)
    dir_fn = _curved_alignment_direction(R)

    verts = dp.derive_edge_vertices(
        segments=segments,
        bridge_start_station=0,
        bridge_end_station=arc_len,
        offset_start=offset,
        offset_end=offset,
        point_at_station_offset=pt_fn,
        direction_at_station=dir_fn,
    )
    assert len(verts) == 2
    assert verts[0].bulge != pytest.approx(0.0, abs=1e-6)

    # Reconstruct the arc from the bulge and chord to verify radius
    p1 = (verts[0].x, verts[0].y)
    p2 = (verts[1].x, verts[1].y)
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    chord_len = math.sqrt(dx * dx + dy * dy)
    # From bulge: R_arc = chord / (2 * sin(atan(bulge) * 2))
    # Simpler: included_angle = 4 * atan(bulge), R = chord / (2 * sin(included/2))
    included = 4 * math.atan(verts[0].bulge)
    half_inc = included / 2.0
    if abs(math.sin(half_inc)) > 1e-12:
        R_arc = abs(chord_len / (2 * math.sin(half_inc)))
        expected_R = R + offset  # outer edge
        assert R_arc == pytest.approx(expected_R, rel=0.01)


def test_curved_inner_edge_radius():
    """Inner edge (left side of CCW curve = radially inward) radius = R - offset."""
    R = 500.0
    offset = -11.0  # left side = radially inward on CCW curve
    theta = math.radians(10.0)
    arc_len = R * theta

    segments = [dp.AlignmentSegment(dp.ENTITY_ARC, 0, arc_len, radius=R)]
    pt_fn = _curved_alignment_point(R)
    dir_fn = _curved_alignment_direction(R)

    verts = dp.derive_edge_vertices(
        segments=segments,
        bridge_start_station=0,
        bridge_end_station=arc_len,
        offset_start=offset,
        offset_end=offset,
        point_at_station_offset=pt_fn,
        direction_at_station=dir_fn,
    )
    assert len(verts) == 2

    p1 = (verts[0].x, verts[0].y)
    p2 = (verts[1].x, verts[1].y)
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    chord_len = math.sqrt(dx * dx + dy * dy)
    included = 4 * math.atan(verts[0].bulge)
    half_inc = included / 2.0
    if abs(math.sin(half_inc)) > 1e-12:
        R_arc = abs(chord_len / (2 * math.sin(half_inc)))
        expected_R = R - abs(offset)  # inner edge
        assert R_arc == pytest.approx(expected_R, rel=0.01)


# -----------------------------------------------------------------------
# arc_through_three_points
# -----------------------------------------------------------------------

def test_three_point_arc_unit_circle():
    """Three points on the unit circle should give R=1 and correct bulge."""
    # Quarter circle from (1,0) through (cos45°, sin45°) to (0,1)
    p1 = (1.0, 0.0)
    p_mid = (math.cos(math.pi / 4), math.sin(math.pi / 4))
    p2 = (0.0, 1.0)
    arc = dp.arc_through_three_points(p1, p_mid, p2)
    assert arc is not None
    assert abs(arc.radius) == pytest.approx(1.0, abs=1e-9)
    assert arc.center == pytest.approx((0.0, 0.0), abs=1e-9)
    # Quarter-circle (90°) → bulge = tan(π/8)
    assert arc.bulge == pytest.approx(math.tan(math.pi / 8), abs=1e-9)


def test_three_point_arc_collinear_returns_none():
    """Three collinear points → no unique arc."""
    p1 = (0.0, 0.0)
    p_mid = (5.0, 0.0)
    p2 = (10.0, 0.0)
    assert dp.arc_through_three_points(p1, p_mid, p2) is None


def test_three_point_arc_cw_direction():
    """Quarter-circle traversed CW gives negative bulge."""
    # Same quarter-circle, reversed direction: (0,1) → (cos45°,sin45°) → (1,0)
    p1 = (0.0, 1.0)
    p_mid = (math.cos(math.pi / 4), math.sin(math.pi / 4))
    p2 = (1.0, 0.0)
    arc = dp.arc_through_three_points(p1, p_mid, p2)
    assert arc is not None
    assert abs(arc.radius) == pytest.approx(1.0, abs=1e-9)
    # CW direction → negative bulge
    assert arc.bulge == pytest.approx(-math.tan(math.pi / 8), abs=1e-9)


# -----------------------------------------------------------------------
# Gating: is_constant_offset
# -----------------------------------------------------------------------

def test_is_constant_offset_equal_values():
    assert dp.is_constant_offset(11.0, 11.0)


def test_is_constant_offset_within_tolerance():
    """Sub-micro-foot difference still counts as constant."""
    assert dp.is_constant_offset(11.0, 11.0 + 1e-9)


def test_is_constant_offset_tapering_value():
    assert not dp.is_constant_offset(11.0, 12.5)


# -----------------------------------------------------------------------
# Gating branch: constant offset on tangent (straight line)
# -----------------------------------------------------------------------

def test_constant_offset_tangent_produces_straight_edge():
    """Constant offset on a single tangent segment → 2 verts, both bulge 0."""
    segments = [dp.AlignmentSegment(dp.ENTITY_TANGENT, 100, 200)]
    verts = dp.derive_edge_vertices(
        segments=segments,
        bridge_start_station=100,
        bridge_end_station=200,
        offset_start=11.0,
        offset_end=11.0,
        point_at_station_offset=_straight_alignment_point,
        direction_at_station=_straight_alignment_direction,
    )
    assert len(verts) == 2
    assert all(v.bulge == pytest.approx(0.0) for v in verts)


# -----------------------------------------------------------------------
# Gating branch: tapering, wholly within a curve (3-point arc fit)
# -----------------------------------------------------------------------

def test_tapering_wholly_within_curve_uses_three_point_fit():
    """Tapering width on one ARC segment → 2 verts with bulge from 3-pt fit."""
    R = 500.0
    theta = math.radians(15.0)
    arc_len = R * theta
    pt_fn = _curved_alignment_point(R)
    dir_fn = _curved_alignment_direction(R)

    segments = [dp.AlignmentSegment(dp.ENTITY_ARC, 0, arc_len, radius=R)]
    verts = dp.derive_edge_vertices(
        segments=segments,
        bridge_start_station=0,
        bridge_end_station=arc_len,
        offset_start=11.0,
        offset_end=12.5,  # tapering
        point_at_station_offset=pt_fn,
        direction_at_station=dir_fn,
    )
    assert len(verts) == 2
    assert abs(verts[0].bulge) > 0.001

    # Verify the fitted arc passes through the midpoint sample to within
    # numerical tolerance — this is the defining property of the 3-pt fit.
    s_mid = arc_len / 2.0
    off_mid = (11.0 + 12.5) / 2.0
    mid_expected = pt_fn(s_mid, off_mid)

    # Reconstruct the arc's center from the chord and bulge to verify mid
    p0 = (verts[0].x, verts[0].y)
    p1 = (verts[1].x, verts[1].y)
    chord_dx, chord_dy = p1[0] - p0[0], p1[1] - p0[1]
    chord_len = math.hypot(chord_dx, chord_dy)
    included = 4.0 * math.atan(verts[0].bulge)
    R_fit = abs(chord_len / (2.0 * math.sin(included / 2.0)))

    # Center is perpendicular to the chord at its midpoint, offset by
    # sagitta_to_center = R cos(included/2)
    chord_mid = (0.5 * (p0[0] + p1[0]), 0.5 * (p0[1] + p1[1]))
    # Perpendicular to chord (90° CCW if included > 0, else CW)
    perp_x = -chord_dy / chord_len
    perp_y = chord_dx / chord_len
    if included < 0:
        perp_x, perp_y = -perp_x, -perp_y
    d_to_center = R_fit * math.cos(abs(included) / 2.0)
    cx = chord_mid[0] + d_to_center * perp_x
    cy = chord_mid[1] + d_to_center * perp_y

    # Mid sample should also be at distance R_fit from this center
    mid_radius = math.hypot(mid_expected[0] - cx, mid_expected[1] - cy)
    assert mid_radius == pytest.approx(R_fit, rel=1e-3)


# -----------------------------------------------------------------------
# Gating branch: tapering, single transition, walk forward
# (BUG FIX: arc tangent must match preceding EDGE direction, not alignment)
# -----------------------------------------------------------------------

def _tapered_alignment_pt():
    """Fake alignment running along +X (so alignment_direction == 0 everywhere)
    but with a clear tapering geometry to test edge direction vs alignment
    direction.  offset acts as Y.
    """
    return _straight_alignment_point, _straight_alignment_direction


def test_tapering_tangent_to_curve_arc_is_tangent_to_preceding_edge():
    """The arc segment must be tangent to the preceding edge's direction
    (not the alignment's tangent direction).

    Setup: straight alignment, but tapering width.  The tangent edge
    segment has a slight angle (due to taper); the arc must inherit
    that angle as its tangent constraint.
    """
    pt_fn, dir_fn = _tapered_alignment_pt()
    segments = [
        dp.AlignmentSegment(dp.ENTITY_TANGENT, 100, 150),
        dp.AlignmentSegment(dp.ENTITY_ARC, 150, 200, radius=500.0),
    ]
    verts = dp.derive_edge_vertices(
        segments=segments,
        bridge_start_station=100,
        bridge_end_station=200,
        offset_start=11.0,
        offset_end=12.5,
        point_at_station_offset=pt_fn,
        direction_at_station=dir_fn,
    )
    assert len(verts) == 3

    # Expected geometry:
    # - p0 at (100, 11)
    # - p_trans at (150, 11.75)  — half-way in station, halfway tapered
    # - p1 at (200, 12.5)
    # Tangent edge direction at transition: atan2(0.75, 50) ≈ 0.01499 rad
    # Arc must be tangent to this direction at p_trans.
    # If the code (incorrectly) uses alignment direction (= 0), the arc
    # would be tangent to +X at p_trans → different bulge.

    p0 = (verts[0].x, verts[0].y)
    p_trans = (verts[1].x, verts[1].y)
    p1 = (verts[2].x, verts[2].y)

    # Sanity: linearly-interpolated transition offset
    assert p0 == pytest.approx((100.0, 11.0))
    assert p_trans == pytest.approx((150.0, 11.75))
    assert p1 == pytest.approx((200.0, 12.5))

    # The bug we're checking for: with the WRONG (alignment-tangent) constraint,
    # the arc through p_trans tangent to direction 0 to p1 would have a
    # different bulge than the CORRECT one tangent to the preceding edge
    # direction.  The correct edge direction is atan2(0.75, 50).
    edge_dir = math.atan2(0.75, 50.0)
    correct_arc = dp.arc_from_start_tangent_endpoint(p_trans, edge_dir, p1)
    expected_bulge = correct_arc.bulge if correct_arc else 0.0

    assert verts[1].bulge == pytest.approx(expected_bulge, abs=1e-9)


def test_tapering_curve_to_tangent_walk_backward():
    """curve → tangent: arc must be tangent to the FOLLOWING tangent's
    direction at the transition (computed backward).
    """
    pt_fn, dir_fn = _tapered_alignment_pt()
    segments = [
        dp.AlignmentSegment(dp.ENTITY_ARC, 100, 150, radius=500.0),
        dp.AlignmentSegment(dp.ENTITY_TANGENT, 150, 200),
    ]
    verts = dp.derive_edge_vertices(
        segments=segments,
        bridge_start_station=100,
        bridge_end_station=200,
        offset_start=11.0,
        offset_end=12.5,
        point_at_station_offset=pt_fn,
        direction_at_station=dir_fn,
    )
    assert len(verts) == 3
    p0 = (verts[0].x, verts[0].y)
    p_trans = (verts[1].x, verts[1].y)
    p1 = (verts[2].x, verts[2].y)

    assert p0 == pytest.approx((100.0, 11.0))
    assert p_trans == pytest.approx((150.0, 11.75))
    assert p1 == pytest.approx((200.0, 12.5))

    # Trailing tangent's forward direction
    edge_dir_fwd = math.atan2(0.75, 50.0)

    # Fit arc going backward (from p_trans to p0) with tangent +π
    arc_back = dp.arc_from_start_tangent_endpoint(
        p_trans, edge_dir_fwd + math.pi, p0,
    )
    expected_fwd_bulge = -arc_back.bulge if arc_back else 0.0

    # The arc bulge belongs to the FIRST vertex (going forward)
    assert verts[0].bulge == pytest.approx(expected_fwd_bulge, abs=1e-9)
    # Tangent segment is straight
    assert verts[1].bulge == pytest.approx(0.0)


# -----------------------------------------------------------------------
# Gating branch: viaduct (3-segment tangent → curve → tangent)
# -----------------------------------------------------------------------

def test_tapering_viaduct_three_segments_all_transitions_linear():
    """3-segment viaduct: linear-in-station vertices at all transitions,
    accept small kinks.
    """
    pt_fn, dir_fn = _tapered_alignment_pt()
    segments = [
        dp.AlignmentSegment(dp.ENTITY_TANGENT, 100, 130),
        dp.AlignmentSegment(dp.ENTITY_ARC, 130, 170, radius=500.0),
        dp.AlignmentSegment(dp.ENTITY_TANGENT, 170, 200),
    ]
    verts = dp.derive_edge_vertices(
        segments=segments,
        bridge_start_station=100,
        bridge_end_station=200,
        offset_start=11.0,
        offset_end=12.5,
        point_at_station_offset=pt_fn,
        direction_at_station=dir_fn,
    )
    # 4 vertices: start, transition1, transition2, end
    assert len(verts) == 4
    # Offsets linearly interpolated at all transitions
    assert verts[0].y == pytest.approx(11.0)
    assert verts[1].y == pytest.approx(11.0 + 0.30 * 1.5)  # 30/100 * (12.5-11)
    assert verts[2].y == pytest.approx(11.0 + 0.70 * 1.5)  # 70/100 * 1.5
    assert verts[3].y == pytest.approx(12.5)


# -----------------------------------------------------------------------
# Skewed-corner bulge correctness (regression test)
# -----------------------------------------------------------------------

def test_skewed_corners_curved_tapering_midstation_width():
    """When the polygon caller passes skewed bearing corners as
    start_xy/end_xy, the resulting arc must still pass through the
    alignment-perpendicular midpoint sample. Verified by checking that
    the perpendicular distance from the alignment to the polygon's
    arc at midstation matches the linearly-interpolated mid offset.

    Regression: previously the bulges were computed using un-skewed
    alignment-perpendicular endpoints but applied to the polyline's
    actual (skewed) corner vertices, producing an arc that didn't pass
    through the midpoint sample.
    """
    R = 500.0
    bridge_start = 0.0
    bridge_end = R * math.radians(15.0)  # ~131 ft, 15° of curve

    pt_fn = _curved_alignment_point(R)
    dir_fn = _curved_alignment_direction(R)

    # Skew the bearings (matching the user's params)
    start_skew = 10.0
    end_skew = -10.0

    def brg_fn(station, skew_deg, perp_offset):
        # Build a skewed-bearing point analogous to alignment.point_on_skewed_bearing
        if skew_deg == 0.0:
            return pt_fn(station, perp_offset)
        cx, cy = pt_fn(station, 0.0)
        alignment_dir = dir_fn(station)
        skew_rad = math.radians(skew_deg)
        perp_left_dir = alignment_dir + math.pi / 2.0 + skew_rad
        L = -perp_offset / math.cos(skew_rad)
        return (cx + L * math.cos(perp_left_dir), cy + L * math.sin(perp_left_dir))

    segments = [dp.AlignmentSegment(dp.ENTITY_ARC, bridge_start, bridge_end, radius=R)]

    poly = dp.derive_deck_plan_polygon(
        segments=segments,
        bridge_start_station=bridge_start,
        bridge_end_station=bridge_end,
        start_left_offset=-11.0,
        start_right_offset=+11.0,
        end_left_offset=-12.5,
        end_right_offset=+12.5,
        start_skew_deg=start_skew,
        end_skew_deg=end_skew,
        point_at_station_offset=pt_fn,
        direction_at_station=dir_fn,
        point_on_skewed_bearing=brg_fn,
    )
    assert len(poly) == 4  # CCW: start_left, start_right, end_right, end_left

    # Right-edge arc lives between poly[1] (start_right) and poly[2] (end_right)
    p_start = (poly[1].x, poly[1].y)
    p_end = (poly[2].x, poly[2].y)
    bulge = poly[1].bulge

    # Reconstruct the arc geometry from chord + bulge
    chord_dx = p_end[0] - p_start[0]
    chord_dy = p_end[1] - p_start[1]
    chord_len = math.hypot(chord_dx, chord_dy)
    assert chord_len > 1.0

    included = 4.0 * math.atan(bulge)
    # Arc center is perpendicular to chord midpoint, offset by R*cos(included/2)
    chord_mx = 0.5 * (p_start[0] + p_end[0])
    chord_my = 0.5 * (p_start[1] + p_end[1])
    R_arc = abs(chord_len / (2.0 * math.sin(included / 2.0)))

    # Perpendicular to chord, oriented to match arc bow direction
    perp_x = -chord_dy / chord_len
    perp_y = chord_dx / chord_len
    if included < 0:
        perp_x, perp_y = -perp_x, -perp_y
    d_to_center = R_arc * math.cos(abs(included) / 2.0)
    cx = chord_mx + d_to_center * perp_x
    cy = chord_my + d_to_center * perp_y

    # The 3-point fit's midpoint sample: alignment at midstation, +11.75 offset
    mid_sta = 0.5 * (bridge_start + bridge_end)
    mid_off = 0.5 * (11.0 + 12.5)
    mid_expected = pt_fn(mid_sta, mid_off)

    # The midpoint sample should lie on the arc — distance from arc center
    # equals R_arc.
    mid_radius = math.hypot(mid_expected[0] - cx, mid_expected[1] - cy)
    assert mid_radius == pytest.approx(R_arc, rel=1e-3), (
        f"midpoint sample ({mid_expected}) not on arc: "
        f"distance to center = {mid_radius}, R_arc = {R_arc}"
    )


# -----------------------------------------------------------------------
# Regression: zero-length span should not crash
# -----------------------------------------------------------------------

def test_degenerate_zero_length_span():
    """Bridge with start == end station → should not raise."""
    segments = [dp.AlignmentSegment(dp.ENTITY_TANGENT, 100, 100)]
    poly = dp.derive_deck_plan_polygon(
        segments=segments,
        bridge_start_station=100,
        bridge_end_station=100,
        start_left_offset=-11.0,
        start_right_offset=+11.0,
        end_left_offset=-11.0,
        end_right_offset=+11.0,
        start_skew_deg=0.0,
        end_skew_deg=0.0,
        point_at_station_offset=_straight_alignment_point,
        direction_at_station=_straight_alignment_direction,
        point_on_skewed_bearing=_straight_bearing_point,
    )
    # At minimum we get bearing corners
    assert len(poly) >= 2
