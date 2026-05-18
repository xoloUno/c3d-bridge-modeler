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
