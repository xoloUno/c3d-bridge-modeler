"""Unit tests for src/deck_geometry.py."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import deck_geometry as dg  # noqa: E402


# ----------------------------------------------------------------------
# 4-vertex parallelogram (no crown kink)
# ----------------------------------------------------------------------

def test_no_crown_arg_returns_parallelogram():
    cs = dg.deck_cross_section(
        deck_left_perp=-15.0,
        deck_right_perp=+15.0,
        deck_top_left_z=100.0,
        deck_top_right_z=100.6,  # super-elevated +2% over 30 ft
        deck_depth=0.667,
    )
    assert not cs.has_crown_kink
    assert cs.is_parallelogram
    assert len(cs.vertices) == 4


def test_parallelogram_top_then_bottom_winding():
    """Vertices trace top-left → top-right → bottom-right → bottom-left."""
    cs = dg.deck_cross_section(
        deck_left_perp=-10.0,
        deck_right_perp=+10.0,
        deck_top_left_z=100.0,
        deck_top_right_z=101.0,
        deck_depth=0.5,
    )
    expected = (
        (-10.0, 100.0),    # top-left
        (+10.0, 101.0),    # top-right
        (+10.0, 100.5),    # bottom-right
        (-10.0, 99.5),     # bottom-left
    )
    assert cs.vertices == expected


def test_parallelogram_bottom_parallel_to_top():
    cs = dg.deck_cross_section(
        deck_left_perp=-12.0,
        deck_right_perp=+8.0,
        deck_top_left_z=50.0,
        deck_top_right_z=50.4,
        deck_depth=0.667,
    )
    # top-left → bottom-left has vertical drop = deck_depth
    assert cs.vertices[0][1] - cs.vertices[3][1] == pytest.approx(0.667)
    # top-right → bottom-right has vertical drop = deck_depth
    assert cs.vertices[1][1] - cs.vertices[2][1] == pytest.approx(0.667)


# ----------------------------------------------------------------------
# 6-vertex hexagon (crown straddles the deck, kink case)
# ----------------------------------------------------------------------

def test_crown_kink_inside_deck_returns_hex():
    cs = dg.deck_cross_section(
        deck_left_perp=-15.0,
        deck_right_perp=+15.0,
        deck_top_left_z=99.7,
        deck_top_right_z=99.7,
        deck_depth=0.667,
        crown_perp=0.0,
        deck_top_crown_z=100.0,  # 0.3 ft higher (peak)
    )
    assert cs.has_crown_kink
    assert not cs.is_parallelogram
    assert len(cs.vertices) == 6


def test_hex_winding_includes_crown_at_top_and_bottom():
    cs = dg.deck_cross_section(
        deck_left_perp=-15.0,
        deck_right_perp=+15.0,
        deck_top_left_z=99.7,
        deck_top_right_z=99.7,
        deck_depth=0.5,
        crown_perp=0.0,
        deck_top_crown_z=100.0,
    )
    # Top edge: left → crown → right
    assert cs.vertices[0] == pytest.approx((-15.0, 99.7))
    assert cs.vertices[1] == pytest.approx((0.0, 100.0))
    assert cs.vertices[2] == pytest.approx((+15.0, 99.7))
    # Bottom edge: right → crown → left (mirrored, deck_depth lower)
    assert cs.vertices[3] == pytest.approx((+15.0, 99.2))
    assert cs.vertices[4] == pytest.approx((0.0, 99.5))
    assert cs.vertices[5] == pytest.approx((-15.0, 99.2))


def test_crown_outside_deck_returns_parallelogram():
    """Crown well to the right of the deck → no kink."""
    cs = dg.deck_cross_section(
        deck_left_perp=-20.0,
        deck_right_perp=-5.0,
        deck_top_left_z=99.4,
        deck_top_right_z=99.7,
        deck_depth=0.667,
        crown_perp=0.0,
        deck_top_crown_z=100.0,  # caller provided, but crown is outside
    )
    assert not cs.has_crown_kink
    assert len(cs.vertices) == 4


def test_crown_at_deck_edge_returns_parallelogram():
    """Strictly-between, not just at the edge."""
    cs = dg.deck_cross_section(
        deck_left_perp=0.0,
        deck_right_perp=+15.0,
        deck_top_left_z=100.0,
        deck_top_right_z=99.7,
        deck_depth=0.667,
        crown_perp=0.0,
        deck_top_crown_z=100.0,
    )
    assert not cs.has_crown_kink


# ----------------------------------------------------------------------
# crown_kink_present helper
# ----------------------------------------------------------------------

def test_kink_present_typical_crown():
    assert dg.crown_kink_present(
        slope_left_pct=-2.0,
        slope_right_pct=-2.0,
        deck_left_perp=-15.0,
        deck_right_perp=+15.0,
        crown_perp=0.0,
    )


def test_no_kink_super_elevated():
    """Opposite-sign slopes produce a continuous plane, no kink."""
    assert not dg.crown_kink_present(
        slope_left_pct=-2.0,
        slope_right_pct=+2.0,
        deck_left_perp=-15.0,
        deck_right_perp=+15.0,
        crown_perp=0.0,
    )


def test_no_kink_zero_slope_one_side():
    assert not dg.crown_kink_present(
        slope_left_pct=0.0,
        slope_right_pct=-2.0,
        deck_left_perp=-15.0,
        deck_right_perp=+15.0,
        crown_perp=0.0,
    )


def test_no_kink_crown_outside_deck():
    assert not dg.crown_kink_present(
        slope_left_pct=-2.0,
        slope_right_pct=-2.0,
        deck_left_perp=-15.0,
        deck_right_perp=+15.0,
        crown_perp=-20.0,  # to the left of the deck
    )


# ----------------------------------------------------------------------
# Degenerate inputs
# ----------------------------------------------------------------------

def test_zero_deck_depth_raises():
    with pytest.raises(ValueError):
        dg.deck_cross_section(
            deck_left_perp=-10.0,
            deck_right_perp=+10.0,
            deck_top_left_z=100.0,
            deck_top_right_z=100.5,
            deck_depth=0.0,
        )


def test_negative_deck_depth_raises():
    with pytest.raises(ValueError):
        dg.deck_cross_section(
            deck_left_perp=-10.0,
            deck_right_perp=+10.0,
            deck_top_left_z=100.0,
            deck_top_right_z=100.5,
            deck_depth=-0.5,
        )


def test_inverted_edges_raises():
    """deck_left_perp >= deck_right_perp is a config error."""
    with pytest.raises(ValueError):
        dg.deck_cross_section(
            deck_left_perp=+10.0,
            deck_right_perp=-10.0,
            deck_top_left_z=100.0,
            deck_top_right_z=100.5,
            deck_depth=0.5,
        )
