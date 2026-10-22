"""Unit tests for src/haunch_geometry.py."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import haunch_geometry as hg  # noqa: E402


# ----------------------------------------------------------------------
# Basic shape contract
# ----------------------------------------------------------------------

def test_returns_four_vertices():
    verts = hg.haunch_profile_vertices_ft(bf_ft=1.0, h_left_ft=0.5, h_right_ft=0.5)
    assert len(verts) == 4


def test_vertices_are_2tuples_of_floats():
    verts = hg.haunch_profile_vertices_ft(bf_ft=1.0, h_left_ft=0.5, h_right_ft=0.5)
    for v in verts:
        assert isinstance(v, tuple)
        assert len(v) == 2
        assert isinstance(v[0], float)
        assert isinstance(v[1], float)


# ----------------------------------------------------------------------
# Bottom edge sits at v=0 (anchors on top of girder flange)
# ----------------------------------------------------------------------

def test_bottom_edge_at_v_zero():
    verts = hg.haunch_profile_vertices_ft(bf_ft=1.0, h_left_ft=0.5, h_right_ft=0.5)
    # V0 and V1 are the bottom corners
    assert verts[0][1] == 0.0
    assert verts[1][1] == 0.0


def test_bottom_edge_spans_flange_width():
    verts = hg.haunch_profile_vertices_ft(bf_ft=1.5, h_left_ft=0.5, h_right_ft=0.5)
    assert verts[0][0] == pytest.approx(-0.75)
    assert verts[1][0] == pytest.approx(+0.75)


# ----------------------------------------------------------------------
# Top edge follows h_left / h_right
# ----------------------------------------------------------------------

def test_top_corners_use_h_left_and_h_right():
    """Profile +u side maps to alignment-LEFT after the Civil-3D-side
    cross_xy = 90°-CCW transform, so `h_left_ft` is placed at the
    (+bf/2, ...) vertex and `h_right_ft` at the (-bf/2, ...) vertex.
    See `haunch_geometry.py` module docstring."""
    verts = hg.haunch_profile_vertices_ft(bf_ft=1.0, h_left_ft=0.6, h_right_ft=0.4)
    # V2 = alignment-LEFT top at (+bf/2, h_left_ft)
    # V3 = alignment-RIGHT top at (-bf/2, h_right_ft)
    assert verts[2] == pytest.approx((0.5, 0.6))
    assert verts[3] == pytest.approx((-0.5, 0.4))


def test_symmetric_input_is_a_rectangle():
    """h_left == h_right → trapezoid degenerates to a rectangle."""
    verts = hg.haunch_profile_vertices_ft(bf_ft=1.0, h_left_ft=0.5, h_right_ft=0.5)
    # Top corners at same v
    assert verts[2][1] == verts[3][1] == 0.5
    # Bottom corners at same v
    assert verts[0][1] == verts[1][1] == 0.0
    # Width = bf at both top and bottom
    assert verts[1][0] - verts[0][0] == pytest.approx(1.0)
    assert verts[2][0] - verts[3][0] == pytest.approx(1.0)


def test_asymmetric_top_edge_slopes_correctly_in_profile():
    """For h_left > h_right: the +u (alignment-LEFT) top vertex sits
    HIGHER in profile-v than the -u (alignment-RIGHT) top vertex."""
    verts = hg.haunch_profile_vertices_ft(bf_ft=1.0, h_left_ft=0.51, h_right_ft=0.49)
    # V2 is the +u top vertex (alignment-LEFT); V3 is -u (alignment-RIGHT)
    assert verts[2][1] > verts[3][1]
    assert verts[2] == pytest.approx((0.5, 0.51))
    assert verts[3] == pytest.approx((-0.5, 0.49))


# ----------------------------------------------------------------------
# Winding: clockwise from bottom-left, matching girder_geometry
# ----------------------------------------------------------------------

def test_winding_traces_full_outline():
    """4 vertices: two at v=0 (bottom edge), two at v>0 (top edge);
    one of each on each side of u=0 (left/right of web)."""
    verts = hg.haunch_profile_vertices_ft(bf_ft=1.0, h_left_ft=0.5, h_right_ft=0.5)
    assert verts[0][0] < 0 and verts[0][1] == 0.0  # bottom at -u
    assert verts[1][0] > 0 and verts[1][1] == 0.0  # bottom at +u
    assert verts[2][0] > 0 and verts[2][1] > 0.0   # top at +u
    assert verts[3][0] < 0 and verts[3][1] > 0.0   # top at -u


# ----------------------------------------------------------------------
# Degenerate inputs
# ----------------------------------------------------------------------

def test_zero_bf_raises():
    with pytest.raises(ValueError):
        hg.haunch_profile_vertices_ft(bf_ft=0.0, h_left_ft=0.5, h_right_ft=0.5)


def test_negative_bf_raises():
    with pytest.raises(ValueError):
        hg.haunch_profile_vertices_ft(bf_ft=-1.0, h_left_ft=0.5, h_right_ft=0.5)


def test_zero_h_left_raises():
    with pytest.raises(ValueError):
        hg.haunch_profile_vertices_ft(bf_ft=1.0, h_left_ft=0.0, h_right_ft=0.5)


def test_negative_h_right_raises():
    with pytest.raises(ValueError):
        hg.haunch_profile_vertices_ft(bf_ft=1.0, h_left_ft=0.5, h_right_ft=-0.1)


# ----------------------------------------------------------------------
# Chamfer: 0 keeps today's trapezoid; >0 is an outward 45° hexagon
# ----------------------------------------------------------------------

def test_zero_chamfer_is_exactly_the_four_vertex_profile():
    """Default and explicit 0 return the same 4-tuple, coordinates included."""
    kwargs = dict(bf_ft=1.0, h_left_ft=0.6, h_right_ft=0.4)
    default = hg.haunch_profile_vertices_ft(**kwargs)
    explicit = hg.haunch_profile_vertices_ft(**kwargs, chamfer_ft=0.0)
    assert explicit == default
    assert default == (
        (-0.5, 0.0),
        (0.5, 0.0),
        (0.5, 0.6),
        (-0.5, 0.4),
    )


def test_positive_chamfer_is_wider_hexagon():
    """Top outer corners flare past the flange; bottom stays on the flange."""
    bf = 1.0
    h_left = 0.6
    h_right = 0.4
    chamfer = 0.1
    verts = hg.haunch_profile_vertices_ft(
        bf_ft=bf, h_left_ft=h_left, h_right_ft=h_right, chamfer_ft=chamfer,
    )
    half = bf / 2.0
    expected = (
        (-half, 0.0),
        (+half, 0.0),
        (+half, h_left - chamfer),
        (+half + chamfer, h_left),
        (-half - chamfer, h_right),
        (-half, h_right - chamfer),
    )
    assert len(verts) == len(expected)
    for got, want in zip(verts, expected):
        assert got == pytest.approx(want)
    bottom_width = verts[1][0] - verts[0][0]
    top_width = verts[3][0] - verts[4][0]
    assert bottom_width == pytest.approx(bf)
    assert top_width == pytest.approx(bf + 2.0 * chamfer)
    assert top_width > bf


def test_chamfer_fillet_is_equal_leg_45_degrees():
    """One chamfer size sets both legs, so each fillet is 45° in (u, v)."""
    chamfer = 0.083
    verts = hg.haunch_profile_vertices_ft(
        bf_ft=1.0, h_left_ft=0.5, h_right_ft=0.5, chamfer_ft=chamfer,
    )
    # Alignment-LEFT fillet climbs outward (+u) by one chamfer.
    assert verts[3][0] - verts[2][0] == pytest.approx(chamfer)
    assert verts[3][1] - verts[2][1] == pytest.approx(chamfer)
    # Alignment-RIGHT outer vertex is one chamfer outside the flange,
    # and one chamfer above the end of the vertical face.
    assert verts[5][0] - verts[4][0] == pytest.approx(chamfer)
    assert verts[4][1] - verts[5][1] == pytest.approx(chamfer)


def test_chamfered_outline_stays_clockwise():
    verts = hg.haunch_profile_vertices_ft(
        bf_ft=1.0, h_left_ft=0.6, h_right_ft=0.4, chamfer_ft=0.1,
    )
    assert verts[0][0] < 0 and verts[0][1] == 0.0
    assert verts[1][0] > 0 and verts[1][1] == 0.0
    assert verts[3][0] > verts[1][0]  # left top is outside the flange
    assert verts[4][0] < verts[0][0]  # right top is outside the flange
    def _twice_area(pts):
        total = 0.0
        for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
            total += x1 * y2 - x2 * y1
        return total

    plain = hg.haunch_profile_vertices_ft(
        bf_ft=1.0, h_left_ft=0.6, h_right_ft=0.4,
    )
    # Same winding sense as the unchamfered trapezoid.
    assert _twice_area(verts) * _twice_area(plain) > 0.0


def test_chamfer_just_under_shorter_side_is_accepted():
    verts = hg.haunch_profile_vertices_ft(
        bf_ft=1.0, h_left_ft=0.5, h_right_ft=0.3, chamfer_ft=0.299,
    )
    assert len(verts) == 6
    assert verts[4][1] == pytest.approx(0.3)


def test_chamfer_equal_to_left_height_raises():
    with pytest.raises(ValueError, match="either side"):
        hg.haunch_profile_vertices_ft(
            bf_ft=1.0, h_left_ft=0.2, h_right_ft=0.5, chamfer_ft=0.2,
        )


def test_chamfer_equal_to_right_height_raises():
    with pytest.raises(ValueError, match="either side"):
        hg.haunch_profile_vertices_ft(
            bf_ft=1.0, h_left_ft=0.5, h_right_ft=0.2, chamfer_ft=0.2,
        )


def test_chamfer_taller_than_both_sides_raises():
    with pytest.raises(ValueError, match="h_left_ft=0.4"):
        hg.haunch_profile_vertices_ft(
            bf_ft=1.0, h_left_ft=0.4, h_right_ft=0.35, chamfer_ft=0.5,
        )


def test_negative_chamfer_raises():
    with pytest.raises(ValueError, match="chamfer_ft must be >= 0"):
        hg.haunch_profile_vertices_ft(
            bf_ft=1.0, h_left_ft=0.5, h_right_ft=0.5, chamfer_ft=-0.01,
        )
