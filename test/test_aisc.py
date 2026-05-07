"""Unit tests for src/aisc.py. Run with `pytest test/` from the repo root."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import aisc  # noqa: E402


def _valid_raw():
    return {
        "schema_version": 1,
        "units": "imperial_inches",
        "shapes": {
            "W36X150": {
                "lb_per_ft": 150.0,
                "area_in2": 44.3,
                "d_in": 35.9,
                "bf_in": 12.0,
                "tw_in": 0.625,
                "tf_in": 0.94,
                "ix_in4": 9040.0,
                "sx_in3": 504.0,
            }
        },
    }


def test_parse_valid():
    table = aisc.parse(_valid_raw())
    assert "W36X150" in table
    s = table["W36X150"]
    assert s.designation == "W36X150"
    assert s.d_in == 35.9
    assert s.bf_in == 12.0
    assert s.lb_per_ft == 150.0
    assert s.ix_in4 == 9040.0


def test_load_committed_file():
    table = aisc.load()
    assert len(table) > 200
    assert "W36X150" in table
    s = table["W36X150"]
    # Sanity check against AISC published values (will be spot-checked
    # against the printed Manual per MANUAL-TASKS.md)
    assert 35.0 < s.d_in < 37.0
    assert 11.5 < s.bf_in < 12.5
    assert s.lb_per_ft == 150.0


def test_get_normalizes_designation():
    table = aisc.parse(_valid_raw())
    assert aisc.get(table, "w36x150").designation == "W36X150"
    assert aisc.get(table, "  W36X150  ").designation == "W36X150"
    assert aisc.get(table, "W36×150").designation == "W36X150"


def test_get_missing_raises():
    table = aisc.parse(_valid_raw())
    with pytest.raises(aisc.AiscError, match="not found"):
        aisc.get(table, "W99X9999")


def test_wrong_units_raises():
    raw = _valid_raw()
    raw["units"] = "metric_mm"
    with pytest.raises(aisc.AiscError, match="units"):
        aisc.parse(raw)


def test_missing_required_field_raises():
    raw = _valid_raw()
    del raw["shapes"]["W36X150"]["d_in"]
    with pytest.raises(aisc.AiscError, match="d_in"):
        aisc.parse(raw)


def test_empty_shapes_raises():
    raw = _valid_raw()
    raw["shapes"] = {}
    with pytest.raises(aisc.AiscError, match="non-empty"):
        aisc.parse(raw)


def test_optional_fields_default_to_none():
    raw = _valid_raw()
    # Strip optional fields
    raw["shapes"]["W36X150"] = {
        "lb_per_ft": 150.0,
        "area_in2": 44.3,
        "d_in": 35.9,
        "bf_in": 12.0,
        "tw_in": 0.625,
        "tf_in": 0.94,
    }
    table = aisc.parse(raw)
    s = table["W36X150"]
    assert s.ix_in4 is None
    assert s.j_in4 is None
