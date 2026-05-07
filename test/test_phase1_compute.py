"""Unit tests for src/phase1_compute.py. Run with `pytest test/` from the repo root."""
from __future__ import annotations

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
    """Return a profile-elevation lookup that returns a constant elevation."""
    def _at(_station: float) -> float:
        return elevation_ft
    return _at


def _linear_profile_at(begin_station: float, begin_elev: float, slope_per_ft: float):
    """Return a linear-grade profile lookup."""
    def _at(station: float) -> float:
        return begin_elev + (station - begin_station) * slope_per_ft
    return _at


# ----------------------------------------------------------------------
# Happy path on the committed example
# ----------------------------------------------------------------------

def test_compute_committed_example_flat_profile():
    params = p1.load(EXAMPLE_PARAMS)
    table = aisc.load()

    # Flat profile at elevation 120.00 ft across the bridge
    result = pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.00))

    assert len(result.spans) == 1
    span = result.spans[0]

    assert span.span_id == "SPAN-1"
    assert span.girder_count == 4
    assert span.girder_shape == "W36X150"
    # W36X150 d = 35.9 in = 2.99166... ft
    assert math.isclose(span.girder_depth_ft, 35.9 / 12.0, abs_tol=1e-6)
    assert math.isclose(span.deck_width_start, 30.0, abs_tol=1e-9)
    assert math.isclose(span.deck_width_end, 30.0, abs_tol=1e-9)
    # Bearings at sta 1001 and 1199 → 198 ft
    assert math.isclose(span.bearing_to_bearing_length, 198.0, abs_tol=1e-9)

    assert len(span.girders) == 4
    g1 = span.girders[0]
    assert g1.girder_index == 1
    assert g1.start.support_id == "ABUT-A"
    assert math.isclose(g1.start.bearing_station, 1001.0, abs_tol=1e-9)
    assert math.isclose(g1.start.girder_offset, -12.0, abs_tol=1e-9)
    assert g1.end.support_id == "ABUT-B"
    assert math.isclose(g1.end.bearing_station, 1199.0, abs_tol=1e-9)


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
    params = p1.load(EXAMPLE_PARAMS)  # already has -2% L/R cross slopes, crown at 0
    table = aisc.load()
    result = pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.00))

    g1, g2, g3, g4 = result.spans[0].girders
    # All four girders should follow the crown profile: G2 and G3 highest, G1 and G4 lower
    assert g1.start.top_of_deck < g2.start.top_of_deck
    assert g4.start.top_of_deck < g3.start.top_of_deck
    # Symmetric deck → G1 == G4, G2 == G3 at start bearing
    assert math.isclose(g1.start.top_of_deck, g4.start.top_of_deck, abs_tol=1e-9)
    assert math.isclose(g2.start.top_of_deck, g3.start.top_of_deck, abs_tol=1e-9)


def test_compute_uphill_grade_end_higher_than_start():
    params = p1.load(EXAMPLE_PARAMS)
    table = aisc.load()
    # 1% uphill grade starting at sta 1000 elev 120
    profile = _linear_profile_at(1000.0, 120.0, 0.01)
    result = pc.compute(params, table, profile_elevation_at=profile)

    span = result.spans[0]
    # Pick the same girder at start and end; elevation should rise across the span
    g2 = span.girders[1]
    assert g2.end.top_of_deck > g2.start.top_of_deck
    # Rise = 1% × (1199 - 1001) = 1.98 ft
    assert math.isclose(
        g2.end.top_of_deck - g2.start.top_of_deck, 1.98, abs_tol=1e-9
    )


# ----------------------------------------------------------------------
# Validation paths
# ----------------------------------------------------------------------

def test_compute_raises_on_unknown_aisc_shape(tmp_path):
    import json
    raw = json.load(open(EXAMPLE_PARAMS))
    raw["superstructures"][0]["girder_shape"] = "W99X9999"
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps(raw))

    params = p1.load(str(bad_path))
    table = aisc.load()
    with pytest.raises(pc.Phase1ComputeError, match="W99X9999"):
        pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.0))


def test_compute_raises_on_multi_bearing_support(tmp_path):
    import json
    raw = json.load(open(EXAMPLE_PARAMS))
    raw["supports"][0]["bearing_offsets"] = [-1.0, 1.0]  # two bearings
    bad_path = tmp_path / "multi.json"
    bad_path.write_text(json.dumps(raw))

    params = p1.load(str(bad_path))
    table = aisc.load()
    with pytest.raises(pc.Phase1ComputeError, match="multi-bearing"):
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
    assert "G1" in text and "G4" in text
    # Each girder appears twice (start + end), 4 girders → 8 data lines
    assert text.count("G1 ") + text.count("G2 ") + text.count("G3 ") + text.count("G4 ") == 8


# ----------------------------------------------------------------------
# Cross-slope sanity at the chain boundary
# ----------------------------------------------------------------------

def test_outer_girder_top_of_deck_matches_manual_calc():
    """Hand-calc top-of-deck at G1: profile=120, deck_offset=-0.25, slope=-2%, offset=-12 ft."""
    params = p1.load(EXAMPLE_PARAMS)
    table = aisc.load()
    result = pc.compute(params, table, profile_elevation_at=_flat_profile_at(120.00))

    g1_start = result.spans[0].girders[0].start
    # top_of_deck = 120 + (-0.25) + (-0.02 × 12) = 120 - 0.25 - 0.24 = 119.51
    assert math.isclose(g1_start.top_of_deck, 119.51, abs_tol=1e-9)
    # top_of_girder_flange = 119.51 - 0.667 - 0.0833 = 118.7597
    assert math.isclose(
        g1_start.top_of_girder_flange,
        119.51 - 0.667 - 0.0833,
        abs_tol=1e-9,
    )
