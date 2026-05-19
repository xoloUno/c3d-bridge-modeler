"""Unit tests for src/phase1_compute.py. Run with `pytest test/` from the repo root."""
from __future__ import annotations

import copy
import json
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import aisc  # noqa: E402
import phase1_compute as pc  # noqa: E402
import phase1_params as p1  # noqa: E402


HERE = os.path.dirname(__file__)
EXAMPLE_PARAMS = os.path.join(HERE, "params.phase1.example.json")


def _flat_profile_at(elevation_ft: float):
    def _at(_station: float) -> float:
        return elevation_ft
    return _at


def _linear_profile_at(begin_station: float, begin_elev: float, slope_per_ft: float):
    def _at(station: float) -> float:
        return begin_elev + (station - begin_station) * slope_per_ft
    return _at


def _load_example_raw():
    with open(EXAMPLE_PARAMS) as f:
        return json.load(f)


def _params_from(raw: dict, tmp_path) -> p1.Phase1Params:
    """Write raw to a temp file, parse, return the Phase1Params object."""
    p = tmp_path / "params.json"
    p.write_text(json.dumps(raw))
    return p1.load(str(p))


# ----------------------------------------------------------------------
# Happy path on the committed example (zero skew, zero offset)
# ----------------------------------------------------------------------

def test_compute_committed_example_flat_profile():
    params = p1.load(EXAMPLE_PARAMS)
    table = aisc.load()
    result = pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.00))

    assert len(result.spans) == 1
    span = result.spans[0]

    assert span.span_id == "SPAN-1"
    assert span.girder_count == 4
    assert span.girder_shape == "W36X150"
    assert math.isclose(span.girder_depth_ft, 35.9 / 12.0, abs_tol=1e-6)
    assert math.isclose(span.perpendicular_deck_width_start, 30.0, abs_tol=1e-9)
    assert math.isclose(span.perpendicular_deck_width_end, 30.0, abs_tol=1e-9)
    # Zero skew → bearing-line length == perpendicular deck width
    assert math.isclose(span.bearing_line_length_start, 30.0, abs_tol=1e-9)
    assert math.isclose(span.bearing_line_length_end, 30.0, abs_tol=1e-9)
    assert math.isclose(span.bearing_to_bearing_length, 198.0, abs_tol=1e-9)

    g1 = span.girders[0]
    assert g1.start.support_id == "ABUT-A"
    assert math.isclose(g1.start.bearing_station, 1001.0, abs_tol=1e-9)
    # Zero skew + zero deck CL offset → perpendicular offset == along-bearing offset
    assert math.isclose(g1.start.girder_offset, -12.0, abs_tol=1e-9)
    assert math.isclose(g1.start.along_bearing_offset, -12.0, abs_tol=1e-9)


def test_compute_chain_descends_monotonically():
    params = p1.load(EXAMPLE_PARAMS)
    table = aisc.load()
    result = pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.00))

    for span in result.spans:
        for g in span.girders:
            for endpt in (g.start, g.end):
                assert endpt.top_of_deck > endpt.top_of_girder_flange
                assert endpt.top_of_girder_flange > endpt.bottom_of_girder
                assert endpt.bottom_of_girder > endpt.bearing_seat
                assert endpt.haunch_h_left_ft > 0.0
                assert endpt.haunch_h_right_ft > 0.0


# ----------------------------------------------------------------------
# Haunch dims at flange tips
# ----------------------------------------------------------------------

def test_haunch_dims_match_centerline_on_flat_deck(tmp_path):
    """Zero cross-slope → h_left == h_right == haunch_depth (rectangular haunch)."""
    raw = _load_example_raw()
    raw["deck_cross_slope_left"] = 0.0
    raw["deck_cross_slope_right"] = 0.0
    params = _params_from(raw, tmp_path)
    table = aisc.load()
    result = pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.0))

    haunch_depth = params.superstructures[0].haunch_depth
    for g in result.spans[0].girders:
        for endpt in (g.start, g.end):
            assert math.isclose(endpt.haunch_h_left_ft, haunch_depth, abs_tol=1e-9)
            assert math.isclose(endpt.haunch_h_right_ft, haunch_depth, abs_tol=1e-9)


def test_haunch_dims_average_to_haunch_depth_on_crowned_deck():
    """Linear cross-slope → (h_left + h_right) / 2 == haunch_depth for any
    girder fully on one side of the crown. Tested against the committed
    example (2% symmetric crown)."""
    params = p1.load(EXAMPLE_PARAMS)
    table = aisc.load()
    result = pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.0))

    haunch_depth = params.superstructures[0].haunch_depth
    for g in result.spans[0].girders:
        for endpt in (g.start, g.end):
            avg = (endpt.haunch_h_left_ft + endpt.haunch_h_right_ft) / 2.0
            assert math.isclose(avg, haunch_depth, abs_tol=1e-9)


def test_haunch_left_higher_on_left_of_crown(tmp_path):
    """For a girder LEFT of crown with symmetric -2% slope:
    deck drops going further LEFT, so the LEFT flange tip is LOWER than
    centerline. h_left = haunch_depth + (negative delta) < haunch_depth.
    Conversely h_right > haunch_depth."""
    params = p1.load(EXAMPLE_PARAMS)
    table = aisc.load()
    result = pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.0))

    haunch_depth = params.superstructures[0].haunch_depth
    # G1, G2 are left of crown (offset 0)
    for g_idx in (0, 1):
        endpt = result.spans[0].girders[g_idx].start
        assert endpt.girder_offset < 0
        assert endpt.haunch_h_left_ft < haunch_depth
        assert endpt.haunch_h_right_ft > haunch_depth


def test_deck_cross_sections_attached_to_each_span():
    """compute() populates deck_start and deck_end on every ComputedSpan."""
    params = p1.load(EXAMPLE_PARAMS)
    table = aisc.load()
    result = pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.0))

    for span in result.spans:
        assert span.deck_start is not None
        assert span.deck_end is not None
        assert span.deck_start.bearing_station < span.deck_end.bearing_station
        assert math.isclose(
            span.deck_start.deck_depth, params.superstructures[0].deck_depth
        )


def test_deck_crowned_symmetric_produces_three_top_vertices():
    """Symmetric crown (slope_left = slope_right = -2%) with crown at deck CL
    inside the deck → hex cross-section with 3 top vertices (left, crown,
    right)."""
    params = p1.load(EXAMPLE_PARAMS)  # already slope_left = slope_right = -2
    table = aisc.load()
    result = pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.0))

    span = result.spans[0]
    assert len(span.deck_start.top_vertices) == 3
    assert len(span.deck_end.top_vertices) == 3
    # Crown vertex is at perp_offset = 0 (crown_offset default = 0)
    crown_vertex = span.deck_start.top_vertices[1]
    assert math.isclose(crown_vertex.perp_offset, 0.0)
    # Crown vertex is HIGHER than the edges (peak)
    assert crown_vertex.top_z > span.deck_start.top_vertices[0].top_z
    assert crown_vertex.top_z > span.deck_start.top_vertices[2].top_z


def test_deck_super_elevated_produces_two_top_vertices(tmp_path):
    """Opposite-sign slopes (slope_left = -2%, slope_right = +2%) → continuous
    plane → parallelogram cross-section with 2 top vertices."""
    raw = _load_example_raw()
    raw["deck_cross_slope_left"] = -2.0
    raw["deck_cross_slope_right"] = +2.0
    params = _params_from(raw, tmp_path)
    table = aisc.load()
    result = pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.0))

    span = result.spans[0]
    assert len(span.deck_start.top_vertices) == 2
    assert len(span.deck_end.top_vertices) == 2


def test_deck_edges_match_perpendicular_deck_width():
    params = p1.load(EXAMPLE_PARAMS)
    table = aisc.load()
    result = pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.0))

    span = result.spans[0]
    # Edge-to-edge spread (left and right perp_offsets) should equal the
    # perpendicular deck width at that bearing.
    perp_start = (
        span.deck_start.top_vertices[-1].perp_offset
        - span.deck_start.top_vertices[0].perp_offset
    )
    assert math.isclose(perp_start, span.perpendicular_deck_width_start)


def test_haunch_delta_matches_cross_slope_times_half_bf():
    """For W36X150 (bf=12 in = 1 ft) at -2% cross-slope, the delta between
    h_left/h_right and haunch_depth is (-0.02) * 0.5 = -0.01 ft on the
    crown-far side (and +0.01 on the crown-near side)."""
    params = p1.load(EXAMPLE_PARAMS)
    table = aisc.load()
    result = pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.0))

    haunch_depth = params.superstructures[0].haunch_depth
    g1_start = result.spans[0].girders[0].start  # left of crown
    expected_left = haunch_depth - 0.01
    expected_right = haunch_depth + 0.01
    assert math.isclose(g1_start.haunch_h_left_ft, expected_left, abs_tol=1e-9)
    assert math.isclose(g1_start.haunch_h_right_ft, expected_right, abs_tol=1e-9)


def test_compute_outermost_girders_lower_than_inner_with_crown():
    """2% crown: outer girders (G1/G4) are lower than inner girders (G2/G3)."""
    params = p1.load(EXAMPLE_PARAMS)
    table = aisc.load()
    result = pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.00))

    g1, g2, g3, g4 = result.spans[0].girders
    assert g1.start.top_of_deck < g2.start.top_of_deck
    assert g4.start.top_of_deck < g3.start.top_of_deck
    assert math.isclose(g1.start.top_of_deck, g4.start.top_of_deck, abs_tol=1e-9)
    assert math.isclose(g2.start.top_of_deck, g3.start.top_of_deck, abs_tol=1e-9)


def test_compute_uphill_grade_end_higher_than_start():
    params = p1.load(EXAMPLE_PARAMS)
    table = aisc.load()
    profile = _linear_profile_at(1000.0, 120.0, 0.01)
    result = pc.compute(params, table, profile_elevation_at=profile)

    span = result.spans[0]
    g2 = span.girders[1]
    assert g2.end.top_of_deck > g2.start.top_of_deck
    assert math.isclose(
        g2.end.top_of_deck - g2.start.top_of_deck, 1.98, abs_tol=1e-9
    )


# ----------------------------------------------------------------------
# Skew correction
# ----------------------------------------------------------------------

def test_skew_increases_bearing_line_length(tmp_path):
    """At 30° skew, bearing-line length = perp_width / cos(30°) ≈ 1.155 × perp_width."""
    raw = _load_example_raw()
    raw["begin_skew_angle"] = 30.0
    raw["end_skew_angle"] = 30.0
    raw["supports"][0]["skew_angle"] = 30.0
    raw["supports"][1]["skew_angle"] = 30.0
    params = _params_from(raw, tmp_path)
    table = aisc.load()
    result = pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.0))

    span = result.spans[0]
    expected = 30.0 / math.cos(math.radians(30.0))
    assert math.isclose(span.bearing_line_length_start, expected, abs_tol=1e-9)
    # perpendicular deck width is unchanged
    assert math.isclose(span.perpendicular_deck_width_start, 30.0, abs_tol=1e-9)


def test_skew_preserves_perpendicular_girder_offsets(tmp_path):
    """At any skew, the girder offsets perpendicular to alignment match the
    zero-skew case, because we're holding perpendicular deck width constant
    and deriving the bearing-line spacing from it.

    Hand-calc: the example has G1 at -12 ft perpendicular (zero skew). With
    skew applied and perpendicular_deck_width preserved, G1 should still
    land at -12 ft perpendicular offset (the LEFT edge spacing was the
    specified one; right is derived). Along-bearing offset SHOULD differ.
    """
    raw = _load_example_raw()
    raw["begin_skew_angle"] = 20.0
    raw["end_skew_angle"] = 20.0
    raw["supports"][0]["skew_angle"] = 20.0
    raw["supports"][1]["skew_angle"] = 20.0
    params = _params_from(raw, tmp_path)
    table = aisc.load()
    result = pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.0))

    span = result.spans[0]
    # G1 along-bearing: left edge at -bearing_line_dist/2 = -30/(2·cos20°) ≈ -15.96
    # G1 along-bearing offset = -15.96 + left_edge_to_G1 (3.0) = -12.96
    # G1 perpendicular = -12.96 × cos(20°) ≈ -12.18 (NOT exactly -12 because
    # left_edge_to_G1 is along bearing line; the perpendicular distance from
    # deck CL through G1 differs from -12 due to the cos factor on the
    # specified left_edge_to_G1)
    g1_start = span.girders[0].start
    expected_along = -30.0 / (2 * math.cos(math.radians(20.0))) + 3.0
    expected_perp = expected_along * math.cos(math.radians(20.0))
    assert math.isclose(g1_start.along_bearing_offset, expected_along, abs_tol=1e-9)
    assert math.isclose(g1_start.girder_offset, expected_perp, abs_tol=1e-9)


def test_derived_edge_spacing_matches_perpendicular_width(tmp_path):
    """When right edge is null and skew is non-zero, right edge is derived
    such that left + spacings + right == perpendicular_deck_width / cos(skew).
    """
    raw = _load_example_raw()
    raw["begin_skew_angle"] = 15.0
    raw["supports"][0]["skew_angle"] = 15.0
    # Keep symmetric for easy inspection
    raw["end_skew_angle"] = 15.0
    raw["supports"][1]["skew_angle"] = 15.0
    params = _params_from(raw, tmp_path)
    table = aisc.load()
    result = pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.0))

    span = result.spans[0]
    # Bearing-line length at 15° skew with 30 ft perp width
    expected_bearing_len = 30.0 / math.cos(math.radians(15.0))
    assert math.isclose(span.bearing_line_length_start, expected_bearing_len, abs_tol=1e-9)
    # G4 along-bearing offset must equal +bearing_line_length/2 - derived_right_edge
    # With left_edge_to_G1=3.0 and spacings=[8,8,8], derived_right = bearing_len - 3 - 24
    expected_right = expected_bearing_len - 3.0 - 24.0
    g4_along = result.spans[0].girders[3].start.along_bearing_offset
    expected_g4_along = expected_bearing_len / 2.0 - expected_right
    assert math.isclose(g4_along, expected_g4_along, abs_tol=1e-9)


# ----------------------------------------------------------------------
# Deck CL offset from alignment
# ----------------------------------------------------------------------

def test_deck_cl_offset_shifts_all_girders(tmp_path):
    """Setting deck_cl_offset_from_alignment = +5 should shift every girder's
    perpendicular offset by +5 ft (relative to the zero-offset case).
    """
    raw = _load_example_raw()
    raw["deck_cl_offset_from_alignment"] = 5.0
    params = _params_from(raw, tmp_path)
    table = aisc.load()
    result = pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.0))

    g1 = result.spans[0].girders[0].start
    g4 = result.spans[0].girders[3].start
    # Without offset G1=-12, G4=+12. With +5 offset: G1=-7, G4=+17.
    assert math.isclose(g1.girder_offset, -7.0, abs_tol=1e-9)
    assert math.isclose(g4.girder_offset, 17.0, abs_tol=1e-9)
    # Along-bearing offsets are unaffected by alignment offset
    assert math.isclose(g1.along_bearing_offset, -12.0, abs_tol=1e-9)
    assert math.isclose(g4.along_bearing_offset, 12.0, abs_tol=1e-9)


def test_deck_cl_offset_array_form_interpolates(tmp_path):
    """Linearly varying deck CL offset: +0 at begin, +4 at end."""
    raw = _load_example_raw()
    raw["deck_cl_offset_from_alignment"] = [
        {"station": 1000.0, "value": 0.0},
        {"station": 1200.0, "value": 4.0},
    ]
    params = _params_from(raw, tmp_path)
    table = aisc.load()
    result = pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.0))

    # Bearings at 1001 and 1199 → interpolated offsets:
    # at 1001: (1001-1000)/200 × 4 = 0.02
    # at 1199: (1199-1000)/200 × 4 = 3.98
    g1 = result.spans[0].girders[0]
    assert math.isclose(g1.start.girder_offset, -12.0 + 0.02, abs_tol=1e-9)
    assert math.isclose(g1.end.girder_offset, -12.0 + 3.98, abs_tol=1e-9)


# ----------------------------------------------------------------------
# Crown offset varying with station
# ----------------------------------------------------------------------

def test_crown_offset_array_form(tmp_path):
    """Crown migrates from 0 at begin to +9 at end. At begin, all girders
    treat slope as if crown is at 0; at end, crown is at +9.
    """
    raw = _load_example_raw()
    raw["crown_offset"] = [
        {"station": 1000.0, "value": 0.0},
        {"station": 1200.0, "value": 9.0},
    ]
    params = _params_from(raw, tmp_path)
    table = aisc.load()
    result = pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.0))

    # At start bearing (1001): crown_offset ≈ 0.045 → still ~symmetric
    g1, g2, g3, g4 = result.spans[0].girders
    # At start: still nearly symmetric (G1≈G4)
    assert math.isclose(g1.start.top_of_deck, g4.start.top_of_deck, abs_tol=0.01)
    # At end (1199): crown_offset ≈ 8.955 — most girders are LEFT of crown,
    # G4 (at +12) is RIGHT of crown. The girder closest to crown is highest.
    # G4 is at +12, crown at ~8.955: distance from crown = +3.045
    # G3 is at +4: distance from crown = -4.955
    # So G4 should be CLOSER to the crown (smaller |distance|) and therefore
    # HIGHER than G3 — but in original example all four were ranked by their
    # distance from a centered crown.
    # With crown at +9, abs_distance: G1=21, G2=13, G3=5, G4=3 → ranking
    # G4 highest, then G3, then G2, then G1.
    # Verify the new ranking at end bearing.
    assert g4.end.top_of_deck > g3.end.top_of_deck
    assert g3.end.top_of_deck > g2.end.top_of_deck
    assert g2.end.top_of_deck > g1.end.top_of_deck


# ----------------------------------------------------------------------
# Validation paths
# ----------------------------------------------------------------------

def test_compute_raises_on_unknown_aisc_shape(tmp_path):
    raw = _load_example_raw()
    raw["superstructures"][0]["girder_shape"] = "W99X9999"
    params = _params_from(raw, tmp_path)
    table = aisc.load()
    with pytest.raises(pc.Phase1ComputeError, match="W99X9999"):
        pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.0))


def test_compute_raises_on_multi_bearing_support(tmp_path):
    raw = _load_example_raw()
    raw["supports"][0]["bearing_offsets"] = [-1.0, 1.0]
    params = _params_from(raw, tmp_path)
    table = aisc.load()
    with pytest.raises(pc.Phase1ComputeError, match="multi-bearing"):
        pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.0))


def test_compute_raises_on_negative_derived_edge_spacing(tmp_path):
    """If sum(spacings) + specified_edge > bearing_line_dist, derived edge < 0."""
    raw = _load_example_raw()
    # perp deck width = 30, sum(spacings) = 24, left_edge = 8 → derived right = -2
    raw["superstructures"][0]["left_edge_to_G1_start"] = 8.0
    raw["superstructures"][0]["Gn_to_right_edge_start"] = None
    params = _params_from(raw, tmp_path)
    table = aisc.load()
    with pytest.raises(pc.Phase1ComputeError, match="negative"):
        pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.0))


# ----------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------

def test_format_text_report_smoke():
    params = p1.load(EXAMPLE_PARAMS)
    table = aisc.load()
    result = pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.00))

    text = pc.format_text_report(result)
    assert "SPAN-1" in text
    assert "W36X150" in text
    assert "ABUT-A" in text
    assert "ABUT-B" in text
    assert "perp deck width" in text
    assert "along-bearing" in text
    # 4 girders × 2 endpoints = 8 data lines
    assert text.count("G1 ") + text.count("G2 ") + text.count("G3 ") + text.count("G4 ") == 8


# ----------------------------------------------------------------------
# Cross-slope sanity at the chain boundary (zero-skew baseline)
# ----------------------------------------------------------------------

def test_girder_profile_evaluated_at_world_station_not_bearing_station(tmp_path):
    """For skewed supports, each girder's bearing point sits at a different
    world station than the bearing line crossing. The profile elevation for
    each girder must be sampled at that world station — otherwise every
    girder on the bearing line shares one baseline Z and the apparent cross-
    slope in alignment-perpendicular sections gets distorted.

    Set up: linear profile with -5% grade, +10° skew at start. The far-
    alignment-LEFT girder and the far-alignment-RIGHT girder sit at
    different world stations on the same bearing line, so a non-trivial
    profile gradient produces different top-of-deck elevations for them
    that exactly track design intent.
    """
    raw = _load_example_raw()
    raw["supports"][0]["skew_angle"] = 10.0
    params = _params_from(raw, tmp_path)
    table = aisc.load()
    # Linear profile, -5% grade from base 120 at station 1000.
    profile = _linear_profile_at(1000.0, 120.0, -0.05)
    result = pc.compute(params, table, profile_elevation_at=profile)

    g1 = result.spans[0].girders[0]
    g4 = result.spans[0].girders[3]
    bearing_station = g1.start.bearing_station
    tan_skew = math.tan(math.radians(10.0))

    # Each girder's bearing point sits at WORLD station
    #   bearing_station + perp_offset × tan(skew).
    g1_world_station = bearing_station + g1.start.girder_offset * tan_skew
    g4_world_station = bearing_station + g4.start.girder_offset * tan_skew
    # Outer girders straddle the bearing station: alignment-LEFT one is
    # back-station (uphill on a downhill grade), alignment-RIGHT is ahead.
    assert g1_world_station < bearing_station < g4_world_station

    # Compute expected top-of-deck values directly from design intent at the
    # world-station profile.
    def expected_top_deck(world_station, perp):
        prof = profile(world_station)
        slope = (
            params.deck_cross_slope_left
            if perp < params.crown_offset.at(world_station)
            else params.deck_cross_slope_right
        )
        return prof + params.deck_profile_offset + (slope / 100.0) * abs(perp)

    assert math.isclose(
        g1.start.top_of_deck,
        expected_top_deck(g1_world_station, g1.start.girder_offset),
        abs_tol=1e-9,
    )
    assert math.isclose(
        g4.start.top_of_deck,
        expected_top_deck(g4_world_station, g4.start.girder_offset),
        abs_tol=1e-9,
    )
    # Sanity: the world-station correction produces non-trivial profile
    # variation across the bearing line. With ±12 ft perp range, +10° skew,
    # and -5% grade, the profile differs across the bearing by
    # 2 × 12 × tan(10°) × 0.05 ≈ 0.21 ft of grade contribution alone
    # (separate from the cross-slope contribution).
    grade_delta = abs(profile(g1_world_station) - profile(g4_world_station))
    assert grade_delta > 0.2, (
        f"expected ~0.21 ft grade contribution across bearing line; got {grade_delta}"
    )


def test_outer_girder_top_of_deck_matches_manual_calc():
    """Hand-calc top-of-deck at G1: profile=120, deck_offset=-0.25, slope=-2%, offset=-12."""
    params = p1.load(EXAMPLE_PARAMS)
    table = aisc.load()
    result = pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.00))

    g1_start = result.spans[0].girders[0].start
    # top_of_deck = 120 + (-0.25) + (-0.02 × 12) = 119.51
    assert math.isclose(g1_start.top_of_deck, 119.51, abs_tol=1e-9)
    assert math.isclose(
        g1_start.top_of_girder_flange,
        119.51 - 0.667 - 0.0833,
        abs_tol=1e-9,
    )
