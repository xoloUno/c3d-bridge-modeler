"""Unit tests for src/elevation.py. Run with `pytest test/` from the repo root."""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import elevation  # noqa: E402


# ----------------------------------------------------------------------
# top_of_deck_at_offset — cross-slope handling
# ----------------------------------------------------------------------

def test_top_of_deck_at_crown():
    # Girder at the crown: no cross-slope contribution
    z = elevation.top_of_deck_at_offset(
        profile_elevation=100.0,
        deck_profile_offset=0.0,
        crown_offset=0.0,
        cross_slope_left_pct=-2.0,
        cross_slope_right_pct=-2.0,
        girder_offset=0.0,
    )
    assert z == 100.0


def test_top_of_deck_symmetric_crown_drops_both_sides():
    # 2% crown, 15 ft each side: deck drops 0.30 ft at each edge
    common = dict(
        profile_elevation=100.0,
        deck_profile_offset=0.0,
        crown_offset=0.0,
        cross_slope_left_pct=-2.0,
        cross_slope_right_pct=-2.0,
    )
    z_right = elevation.top_of_deck_at_offset(girder_offset=15.0, **common)
    z_left = elevation.top_of_deck_at_offset(girder_offset=-15.0, **common)
    assert math.isclose(z_right, 100.0 - 0.30, abs_tol=1e-9)
    assert math.isclose(z_left, 100.0 - 0.30, abs_tol=1e-9)


def test_top_of_deck_offset_crown():
    # Crown shifted 5 ft right of alignment; girder at +5 sits AT crown
    common = dict(
        profile_elevation=100.0,
        deck_profile_offset=0.0,
        crown_offset=5.0,
        cross_slope_left_pct=-2.0,
        cross_slope_right_pct=-2.0,
    )
    z_at_crown = elevation.top_of_deck_at_offset(girder_offset=5.0, **common)
    z_left_edge = elevation.top_of_deck_at_offset(girder_offset=-10.0, **common)
    assert math.isclose(z_at_crown, 100.0, abs_tol=1e-9)
    # Left edge is 15 ft from crown
    assert math.isclose(z_left_edge, 100.0 - 0.30, abs_tol=1e-9)


def test_top_of_deck_superelevated_one_way_slope():
    # Banked deck, both slopes negative on same sign convention but matched in
    # direction: e.g. mid-curve where the whole deck slopes 4% toward the
    # left edge. Express as right slope = +4 (rises rightward away from
    # crown — so crown is on the LEFT side of the deck) is unusual; more
    # commonly we just place crown_offset off the deck. Here we use a
    # one-sided test: positive slope right of crown.
    z = elevation.top_of_deck_at_offset(
        profile_elevation=100.0,
        deck_profile_offset=0.0,
        crown_offset=0.0,
        cross_slope_left_pct=-2.0,
        cross_slope_right_pct=2.0,  # rises away from crown
        girder_offset=10.0,
    )
    assert math.isclose(z, 100.0 + 0.20, abs_tol=1e-9)


def test_top_of_deck_with_profile_offset():
    # Profile is the PGL (top of pavement); deck top is below it by topping
    z = elevation.top_of_deck_at_offset(
        profile_elevation=100.0,
        deck_profile_offset=-0.25,  # 3 inches below PGL
        crown_offset=0.0,
        cross_slope_left_pct=-2.0,
        cross_slope_right_pct=-2.0,
        girder_offset=0.0,
    )
    assert math.isclose(z, 99.75, abs_tol=1e-9)


# ----------------------------------------------------------------------
# superstructure_elevations
# ----------------------------------------------------------------------

def test_superstructure_chain_basic():
    s = elevation.superstructure_elevations(
        top_of_deck=100.0,
        deck_depth=0.667,         # 8 in
        haunch_depth=0.0833,      # 1 in
        girder_depth=2.992,       # W36X150 d=35.9 in -> 2.991667 ft
        bearing_device_height=0.5,
    )
    assert math.isclose(s.top_of_deck, 100.0)
    assert math.isclose(s.top_of_girder_flange, 100.0 - 0.667 - 0.0833, abs_tol=1e-9)
    assert math.isclose(s.bottom_of_girder, s.top_of_girder_flange - 2.992, abs_tol=1e-9)
    assert math.isclose(s.bearing_seat, s.bottom_of_girder - 0.5, abs_tol=1e-9)


def test_superstructure_zero_haunch():
    s = elevation.superstructure_elevations(
        top_of_deck=50.0,
        deck_depth=1.0,
        haunch_depth=0.0,
        girder_depth=3.0,
        bearing_device_height=0.5,
    )
    assert s.top_of_girder_flange == 49.0
    assert s.bottom_of_girder == 46.0
    assert s.bearing_seat == 45.5


# ----------------------------------------------------------------------
# top_of_footing
# ----------------------------------------------------------------------

def test_top_of_footing_derived_from_fg():
    # No user override: depth-below-FG rule applies
    assert elevation.top_of_footing(
        fg_surface_elevation=105.0,
        min_depth_below_fg=4.0,
    ) == 101.0


def test_top_of_footing_user_override_wins():
    # User-specified value takes precedence over the FG-derived default
    z = elevation.top_of_footing(
        fg_surface_elevation=105.0,
        min_depth_below_fg=4.0,
        specified_top_of_footing=98.5,
    )
    assert z == 98.5


def test_top_of_footing_user_override_can_be_above_default():
    # Explicit user value of 102 (shallower than 101 default) is honored
    z = elevation.top_of_footing(
        fg_surface_elevation=105.0,
        min_depth_below_fg=4.0,
        specified_top_of_footing=102.0,
    )
    assert z == 102.0


# ----------------------------------------------------------------------
# substructure_elevations
# ----------------------------------------------------------------------

def test_substructure_chain_basic():
    s = elevation.substructure_elevations(
        bearing_seat=95.0,
        pedestal_height=0.5,        # 6 in
        cap_depth=3.5,
        fg_surface_elevation=85.0,
        min_depth_below_fg=4.0,
    )
    assert math.isclose(s.top_of_cap, 94.5, abs_tol=1e-9)
    assert math.isclose(s.top_of_column, 91.0, abs_tol=1e-9)
    assert math.isclose(s.top_of_footing, 81.0, abs_tol=1e-9)
    assert math.isclose(s.column_height, 10.0, abs_tol=1e-9)


def test_substructure_chain_with_specified_footing():
    s = elevation.substructure_elevations(
        bearing_seat=95.0,
        pedestal_height=0.5,
        cap_depth=3.5,
        fg_surface_elevation=85.0,
        min_depth_below_fg=4.0,
        specified_top_of_footing=78.0,
    )
    assert s.top_of_footing == 78.0
    assert math.isclose(s.column_height, 91.0 - 78.0, abs_tol=1e-9)


# ----------------------------------------------------------------------
# End-to-end realistic case — sanity check against scope.md example
# ----------------------------------------------------------------------

def test_full_chain_realistic_w36x150():
    """W36X150 girder, 2% crowned deck, single-column pier — full chain."""
    # Inputs in feet
    top_of_deck = elevation.top_of_deck_at_offset(
        profile_elevation=120.00,
        deck_profile_offset=-0.25,        # PGL is top of pavement; deck is 3" below
        crown_offset=0.0,
        cross_slope_left_pct=-2.0,
        cross_slope_right_pct=-2.0,
        girder_offset=-12.0,              # G2 of a 4-girder bridge
    )
    # 12 ft from crown, slope 2%: drop of 0.24 ft. Plus -0.25 deck offset.
    assert math.isclose(top_of_deck, 120.00 - 0.25 - 0.24, abs_tol=1e-9)

    sup = elevation.superstructure_elevations(
        top_of_deck=top_of_deck,
        deck_depth=0.6667,                # 8 in
        haunch_depth=0.0833,              # 1 in
        girder_depth=35.9 / 12.0,         # W36X150 d=35.9 in
        bearing_device_height=0.5,        # 6 in
    )
    sub = elevation.substructure_elevations(
        bearing_seat=sup.bearing_seat,
        pedestal_height=0.5,
        cap_depth=4.0,
        fg_surface_elevation=100.0,
        min_depth_below_fg=4.0,
    )

    # Sanity: chain is monotonically descending
    assert sup.top_of_deck > sup.top_of_girder_flange > sup.bottom_of_girder
    assert sup.bottom_of_girder > sup.bearing_seat
    assert sup.bearing_seat > sub.top_of_cap > sub.top_of_column > sub.top_of_footing
    # Column height is positive (column not buried) and matches arithmetic
    assert sub.column_height > 0
    assert math.isclose(
        sub.column_height, sub.top_of_column - sub.top_of_footing, abs_tol=1e-9
    )
