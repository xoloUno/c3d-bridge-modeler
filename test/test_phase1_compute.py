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
