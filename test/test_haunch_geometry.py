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
    verts = hg.haunch_profile_vertices_ft(bf_ft=1.0, h_left_ft=0.6, h_right_ft=0.4)
    # V2 = top-right at (+bf/2, h_right); V3 = top-left at (-bf/2, h_left)
    assert verts[2] == pytest.approx((0.5, 0.4))
    assert verts[3] == pytest.approx((-0.5, 0.6))


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


def test_asymmetric_top_edge_slopes():
    """For h_left > h_right (girder on the down-slope side, left tip closer
    to crown), the top edge slopes down going right."""
    verts = hg.haunch_profile_vertices_ft(bf_ft=1.0, h_left_ft=0.51, h_right_ft=0.49)
    assert verts[3][1] > verts[2][1]


# ----------------------------------------------------------------------
# Winding: clockwise from bottom-left, matching girder_geometry
# ----------------------------------------------------------------------

def test_winding_clockwise_from_bottom_left():
    verts = hg.haunch_profile_vertices_ft(bf_ft=1.0, h_left_ft=0.5, h_right_ft=0.5)
    assert verts[0][0] < 0 and verts[0][1] == 0.0  # bottom-left
    assert verts[1][0] > 0 and verts[1][1] == 0.0  # bottom-right
    assert verts[2][0] > 0 and verts[2][1] > 0.0   # top-right
    assert verts[3][0] < 0 and verts[3][1] > 0.0   # top-left


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
