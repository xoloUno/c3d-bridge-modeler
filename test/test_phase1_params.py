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
        "deck_cl_offset_from_alignment": 0.0,
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
                "perpendicular_deck_width_start": 30.0,
                "perpendicular_deck_width_end": 30.0,
                "left_edge_to_G1_start": 3.0,
                "girder_spacings_start": [8.0, 8.0, 8.0],
                "Gn_to_right_edge_start": None,
                "left_edge_to_G1_end": 3.0,
                "girder_spacings_end": [8.0, 8.0, 8.0],
                "Gn_to_right_edge_end": None,
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
    assert params.superstructures[0].perpendicular_deck_width_start == 30.0


def test_load_committed_example():
    here = os.path.dirname(__file__)
    params = p1.load(os.path.join(here, "params.phase1.example.json"))
    assert params.alignment_name == "EXAMPLE-ALIGNMENT"
    assert len(params.supports) == 2
    assert params.superstructures[0].girder_shape == "W36X150"
    assert params.superstructures[0].perpendicular_deck_width_start == 30.0
    # Example uses left_edge specified, right_edge derived
    assert params.superstructures[0].left_edge_to_G1_start == 3.0
    assert params.superstructures[0].Gn_to_right_edge_start is None


def test_constant_offsets_become_two_point_profile():
    params = p1.parse(_valid_raw())
    assert params.crown_offset.at(1000.0) == 0.0
    assert params.crown_offset.at(1100.0) == 0.0
    assert params.deck_cl_offset_from_alignment.at(1100.0) == 0.0


def test_station_varying_crown_offset_rejected():
    """Station-varying crown_offset is deferred (Phase 2+) — the deck
    solid is a constant-section sweep, so accepting station variation
    would silently ignore the input. Parse must reject it.
    """
    raw = _valid_raw()
    raw["crown_offset"] = [
        {"station": 1000.0, "value": 9.0},
        {"station": 1200.0, "value": 0.0},
    ]
    with pytest.raises(p1.Phase1ParamsError, match="station-varying crown_offset"):
        p1.parse(raw)


def test_station_varying_deck_cl_offset_rejected():
    """Station-varying deck_cl_offset_from_alignment is deferred (Phase 2+)
    for the same reason as crown_offset above.
    """
    raw = _valid_raw()
    raw["deck_cl_offset_from_alignment"] = [
        {"station": 1000.0, "value": 0.0},
        {"station": 1200.0, "value": 4.0},
    ]
    with pytest.raises(
        p1.Phase1ParamsError,
        match="station-varying deck_cl_offset_from_alignment",
    ):
        p1.parse(raw)


def test_array_form_constant_value_accepted():
    """Array-form with two equal endpoints is still constant — must pass."""
    raw = _valid_raw()
    raw["crown_offset"] = [
        {"station": 1000.0, "value": 3.0},
        {"station": 1200.0, "value": 3.0},
    ]
    params = p1.parse(raw)
    assert params.crown_offset.at(1000.0) == 3.0
    assert params.crown_offset.at(1100.0) == 3.0
    assert params.crown_offset.at(1200.0) == 3.0


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


def test_haunch_width_must_be_positive_when_specified():
    raw = _valid_raw()
    raw["superstructures"][0]["haunch_width_mode"] = "CUSTOM"
    raw["superstructures"][0]["haunch_width"] = 0.0
    with pytest.raises(p1.Phase1ParamsError, match="haunch_width must be > 0"):
        p1.parse(raw)


def test_custom_haunch_width_propagates_to_superstructure():
    raw = _valid_raw()
    raw["superstructures"][0]["haunch_width_mode"] = "CUSTOM"
    raw["superstructures"][0]["haunch_width"] = 1.5
    params = p1.parse(raw)
    assert params.superstructures[0].haunch_width_mode == "CUSTOM"
    assert params.superstructures[0].haunch_width == 1.5


# ----------------------------------------------------------------------
# Numeric input validation
# ----------------------------------------------------------------------

@pytest.mark.parametrize("field", ["deck_depth", "haunch_depth"])
def test_depth_must_be_positive(field):
    raw = _valid_raw()
    raw["superstructures"][0][field] = 0.0
    with pytest.raises(p1.Phase1ParamsError, match=f"{field} must be > 0"):
        p1.parse(raw)


def test_topping_depth_must_be_nonnegative():
    raw = _valid_raw()
    raw["superstructures"][0]["topping_depth"] = -0.1
    with pytest.raises(p1.Phase1ParamsError, match="topping_depth must be >= 0"):
        p1.parse(raw)


def test_girder_spacing_must_be_positive():
    raw = _valid_raw()
    raw["superstructures"][0]["girder_spacings_start"] = [8.0, 0.0, 8.0]
    with pytest.raises(p1.Phase1ParamsError, match="girder_spacings_start"):
        p1.parse(raw)


def test_edge_spacing_must_be_positive_when_specified():
    raw = _valid_raw()
    raw["superstructures"][0]["left_edge_to_G1_start"] = -1.0
    raw["superstructures"][0]["Gn_to_right_edge_start"] = None
    with pytest.raises(p1.Phase1ParamsError, match="left_edge_to_G1_start"):
        p1.parse(raw)


# ----------------------------------------------------------------------
# follow_superelevation strict-bool + deferred-feature gate
# ----------------------------------------------------------------------

def test_follow_superelevation_true_rejected():
    """`true` is parsed-but-unimplemented; reject so callers know."""
    raw = _valid_raw()
    raw["follow_superelevation"] = True
    with pytest.raises(p1.Phase1ParamsError, match="follow_superelevation=true"):
        p1.parse(raw)


def test_follow_superelevation_must_be_bool_not_string():
    """`bool('false')` is True — guard the foot-gun by requiring a JSON bool."""
    raw = _valid_raw()
    raw["follow_superelevation"] = "false"
    with pytest.raises(p1.Phase1ParamsError, match="must be a JSON boolean"):
        p1.parse(raw)


# ----------------------------------------------------------------------
# Edge spacing exactly-one-of validation
# ----------------------------------------------------------------------

def test_both_edge_spacings_specified_rejected():
    raw = _valid_raw()
    raw["superstructures"][0]["Gn_to_right_edge_start"] = 3.0  # both now specified
    with pytest.raises(p1.Phase1ParamsError, match="exactly one of"):
        p1.parse(raw)


def test_both_edge_spacings_null_rejected():
    raw = _valid_raw()
    raw["superstructures"][0]["left_edge_to_G1_start"] = None
    raw["superstructures"][0]["Gn_to_right_edge_start"] = None
    with pytest.raises(p1.Phase1ParamsError, match="exactly one of"):
        p1.parse(raw)


def test_left_specified_right_null_works():
    raw = _valid_raw()
    raw["superstructures"][0]["left_edge_to_G1_start"] = 3.0
    raw["superstructures"][0]["Gn_to_right_edge_start"] = None
    params = p1.parse(raw)
    assert params.superstructures[0].left_edge_to_G1_start == 3.0
    assert params.superstructures[0].Gn_to_right_edge_start is None


def test_right_specified_left_null_works():
    raw = _valid_raw()
    raw["superstructures"][0]["left_edge_to_G1_start"] = None
    raw["superstructures"][0]["Gn_to_right_edge_start"] = 3.0
    params = p1.parse(raw)
    assert params.superstructures[0].left_edge_to_G1_start is None
    assert params.superstructures[0].Gn_to_right_edge_start == 3.0


def test_perpendicular_deck_width_must_be_positive():
    raw = _valid_raw()
    raw["superstructures"][0]["perpendicular_deck_width_start"] = -1.0
    with pytest.raises(p1.Phase1ParamsError, match="must be positive"):
        p1.parse(raw)


def test_perpendicular_deck_width_zero_rejected():
    raw = _valid_raw()
    raw["superstructures"][0]["perpendicular_deck_width_start"] = 0.0
    with pytest.raises(p1.Phase1ParamsError, match="must be positive"):
        p1.parse(raw)


# ----------------------------------------------------------------------
# Station profile validation surfacing through phase1_params errors
# ----------------------------------------------------------------------

def test_crown_offset_array_must_cover_envelope():
    raw = _valid_raw()
    raw["crown_offset"] = [
        {"station": 1010.0, "value": 0.0},  # past begin_station = 1000
        {"station": 1200.0, "value": 0.0},
    ]
    with pytest.raises(p1.Phase1ParamsError, match="begin_station"):
        p1.parse(raw)


def test_crown_offset_array_too_short():
    raw = _valid_raw()
    raw["crown_offset"] = [{"station": 1000.0, "value": 0.0}]
    with pytest.raises(p1.Phase1ParamsError, match="at least 2"):
        p1.parse(raw)


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
