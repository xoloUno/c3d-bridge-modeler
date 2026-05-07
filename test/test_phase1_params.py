"""Unit tests for src/phase1_params.py. Run with `pytest test/` from the repo root."""
from __future__ import annotations

import copy
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import aisc  # noqa: E402
import phase1_params as p1  # noqa: E402


def _valid_raw():
    return {
        "alignment_name": "A",
        "profile_name": "P",
        "eg_surface_name": "EG",
        "fg_surface_name": "FG",
        "template_dwg": "templates/x.dwg",
        "begin_station": 1000.0,
        "end_station": 1200.0,
        "begin_skew_angle": 0.0,
        "end_skew_angle": 0.0,
        "deck_cross_slope_left": -2.0,
        "deck_cross_slope_right": -2.0,
        "crown_offset": 0.0,
        "deck_profile_offset": -0.25,
        "follow_superelevation": False,
        "supports": [
            {
                "support_id": "ABUT-A",
                "support_type": "ABUTMENT_SEAT",
                "station": 1000.0,
                "skew_angle": 0.0,
                "bearing_offsets": [1.0],
            },
            {
                "support_id": "ABUT-B",
                "support_type": "ABUTMENT_SEAT",
                "station": 1200.0,
                "bearing_offsets": [-1.0],
            },
        ],
        "spans": [
            {"span_id": "SPAN-1", "start_support_id": "ABUT-A", "end_support_id": "ABUT-B"}
        ],
        "superstructures": [
            {
                "girder_type": "W_SHAPE",
                "girder_shape": "W36X150",
                "girder_count": 4,
                "girder_spacing_mode": "EQUAL",
                "left_edge_to_G1_start": 3.0,
                "girder_spacings_start": [8.0, 8.0, 8.0],
                "Gn_to_right_edge_start": 3.0,
                "left_edge_to_G1_end": 3.0,
                "girder_spacings_end": [8.0, 8.0, 8.0],
                "Gn_to_right_edge_end": 3.0,
                "girder_geometry": "STRAIGHT",
                "deck_depth": 0.667,
                "haunch_depth": 0.0833,
                "haunch_width_mode": "MATCH_TOP_FLANGE",
                "end_diaphragm": True,
            }
        ],
    }


# ----------------------------------------------------------------------
# Happy path
# ----------------------------------------------------------------------

def test_parse_valid():
    params = p1.parse(_valid_raw())
    assert params.alignment_name == "A"
    assert len(params.supports) == 2
    assert params.supports[0].support_id == "ABUT-A"
    assert params.supports[0].bearing_offsets == (1.0,)
    assert params.spans[0].span_id == "SPAN-1"
    assert params.superstructures[0].girder_shape == "W36X150"
    assert params.superstructures[0].girder_spacings_start == (8.0, 8.0, 8.0)


def test_load_committed_example():
    here = os.path.dirname(__file__)
    params = p1.load(os.path.join(here, "params.phase1.example.json"))
    assert params.alignment_name == "EXAMPLE-ALIGNMENT"
    assert len(params.supports) == 2
    assert params.superstructures[0].girder_shape == "W36X150"


# ----------------------------------------------------------------------
# Validation: structural
# ----------------------------------------------------------------------

def test_missing_top_level_key_raises():
    raw = _valid_raw()
    del raw["alignment_name"]
    with pytest.raises(p1.Phase1ParamsError, match="alignment_name"):
        p1.parse(raw)


def test_station_ordering_validated():
    raw = _valid_raw()
    raw["begin_station"], raw["end_station"] = raw["end_station"], raw["begin_station"]
    with pytest.raises(p1.Phase1ParamsError, match="begin_station"):
        p1.parse(raw)


def test_unknown_support_type_raises():
    raw = _valid_raw()
    raw["supports"][0]["support_type"] = "MAGIC_PIER"
    with pytest.raises(p1.Phase1ParamsError, match="support_type"):
        p1.parse(raw)


def test_duplicate_support_id_raises():
    raw = _valid_raw()
    raw["supports"][1]["support_id"] = "ABUT-A"
    with pytest.raises(p1.Phase1ParamsError, match="Duplicate"):
        p1.parse(raw)


def test_span_unknown_support_ref_raises():
    raw = _valid_raw()
    raw["spans"][0]["end_support_id"] = "DOES-NOT-EXIST"
    with pytest.raises(p1.Phase1ParamsError, match="unknown support_id"):
        p1.parse(raw)


def test_support_outside_bridge_range_raises():
    raw = _valid_raw()
    raw["supports"][0]["station"] = 999.0
    with pytest.raises(p1.Phase1ParamsError, match="outside bridge range"):
        p1.parse(raw)


def test_superstructure_count_must_match_spans():
    raw = _valid_raw()
    raw["superstructures"].append(copy.deepcopy(raw["superstructures"][0]))
    with pytest.raises(p1.Phase1ParamsError, match="superstructures count"):
        p1.parse(raw)


def test_girder_spacings_length_validated():
    raw = _valid_raw()
    raw["superstructures"][0]["girder_spacings_start"] = [8.0, 8.0]  # too short
    with pytest.raises(p1.Phase1ParamsError, match="girder_spacings_start"):
        p1.parse(raw)


def test_girder_count_minimum():
    raw = _valid_raw()
    raw["superstructures"][0]["girder_count"] = 1
    raw["superstructures"][0]["girder_spacings_start"] = []
    raw["superstructures"][0]["girder_spacings_end"] = []
    with pytest.raises(p1.Phase1ParamsError, match="girder_count must be >= 2"):
        p1.parse(raw)


def test_phase1_rejects_plate_girder():
    raw = _valid_raw()
    raw["superstructures"][0]["girder_type"] = "PLATE_GIRDER"
    with pytest.raises(p1.Phase1ParamsError, match="not supported in Phase 1"):
        p1.parse(raw)


def test_phase1_rejects_curved_geometry():
    raw = _valid_raw()
    raw["superstructures"][0]["girder_geometry"] = "FOLLOW_ALIGNMENT"
    with pytest.raises(p1.Phase1ParamsError, match="not supported in Phase 1"):
        p1.parse(raw)


def test_haunch_width_required_when_custom():
    raw = _valid_raw()
    raw["superstructures"][0]["haunch_width_mode"] = "CUSTOM"
    with pytest.raises(p1.Phase1ParamsError, match="haunch_width is required"):
        p1.parse(raw)


# ----------------------------------------------------------------------
# Helpers: girder offsets and deck width
# ----------------------------------------------------------------------

def test_girder_offsets_symmetric_4_girder():
    # 3 + 8 + 8 + 8 + 3 = 30 ft deck
    # G1 at -15+3 = -12, G2 at -4, G3 at +4, G4 at +12
    offsets = p1.girder_offsets_at_bearing(
        left_edge_to_G1=3.0,
        girder_spacings=(8.0, 8.0, 8.0),
        Gn_to_right_edge=3.0,
    )
    assert offsets == (-12.0, -4.0, 4.0, 12.0)


def test_girder_offsets_asymmetric_flared_end():
    # Flared end: spacings widen
    # 3 + 8 + 9 + 10 + 3 = 33 ft deck
    # left edge at -16.5; G1 at -13.5, G2 at -5.5, G3 at 3.5, G4 at 13.5
    offsets = p1.girder_offsets_at_bearing(
        left_edge_to_G1=3.0,
        girder_spacings=(8.0, 9.0, 10.0),
        Gn_to_right_edge=3.0,
    )
    assert math.isclose(offsets[0], -13.5, abs_tol=1e-9)
    assert math.isclose(offsets[1], -5.5, abs_tol=1e-9)
    assert math.isclose(offsets[2], 3.5, abs_tol=1e-9)
    assert math.isclose(offsets[3], 13.5, abs_tol=1e-9)


def test_deck_width_helper():
    assert p1.deck_width(3.0, (8.0, 8.0, 8.0), 3.0) == 30.0


def test_girder_offsets_2_girder():
    offsets = p1.girder_offsets_at_bearing(
        left_edge_to_G1=2.0,
        girder_spacings=(10.0,),
        Gn_to_right_edge=2.0,
    )
    # 14 ft deck, edges at +/-7, G1 at -5, G2 at +5
    assert offsets == (-5.0, 5.0)


# ----------------------------------------------------------------------
# AISC cross-validation
# ----------------------------------------------------------------------

def test_aisc_cross_validation_clean():
    params = p1.parse(_valid_raw())
    table = aisc.load()
    errors = p1.validate_against_aisc(params, table)
    assert errors == []


def test_aisc_cross_validation_unknown_shape():
    raw = _valid_raw()
    raw["superstructures"][0]["girder_shape"] = "W99X9999"
    params = p1.parse(raw)
    table = aisc.load()
    errors = p1.validate_against_aisc(params, table)
    assert len(errors) == 1
    assert "W99X9999" in errors[0]


def test_aisc_cross_validation_normalizes_designation():
    raw = _valid_raw()
    raw["superstructures"][0]["girder_shape"] = "w36x150"  # lowercase
    params = p1.parse(raw)
    table = aisc.load()
    errors = p1.validate_against_aisc(params, table)
    assert errors == []
