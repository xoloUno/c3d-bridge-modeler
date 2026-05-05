"""Unit tests for src/params.py. Run with `pytest test/` from the repo root."""
from __future__ import annotations

import os
import sys

import pytest

# Make src/ importable without installing the package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import params  # noqa: E402


def _valid_raw():
    return {
        "alignment_name": "A",
        "profile_name": "P",
        "eg_surface_name": "EG",
        "begin_station": 1000.0,
        "end_station": 1200.0,
        "deck_width": 30.0,
        "deck_depth": 1.0,
        "piers": [
            {"id": "PIER-1", "station": 1066.67, "length": 4.0, "width": 4.0, "height": 20.0},
            {"id": "PIER-2", "station": 1133.33, "length": 4.0, "width": 4.0, "height": 20.0},
        ],
    }


def test_parse_valid():
    p = params.parse(_valid_raw())
    assert p.alignment_name == "A"
    assert p.begin_station == 1000.0
    assert p.end_station == 1200.0
    assert len(p.piers) == 2
    assert p.piers[0].id == "PIER-1"


def test_load_from_disk_matches_committed_file():
    here = os.path.dirname(__file__)
    p = params.load(os.path.join(here, "params.phase0.json"))
    assert p.alignment_name == "ALIGN-MAINLINE"
    assert len(p.piers) == 2


def test_missing_top_level_key_raises():
    raw = _valid_raw()
    del raw["alignment_name"]
    with pytest.raises(params.ParamsError, match="alignment_name"):
        params.parse(raw)


def test_missing_pier_key_raises():
    raw = _valid_raw()
    del raw["piers"][0]["station"]
    with pytest.raises(params.ParamsError, match="station"):
        params.parse(raw)


def test_pier_list_too_short_raises():
    raw = _valid_raw()
    raw["piers"] = raw["piers"][:1]
    with pytest.raises(params.ParamsError, match="at least 2"):
        params.parse(raw)


def test_station_ordering_validated():
    raw = _valid_raw()
    raw["begin_station"], raw["end_station"] = raw["end_station"], raw["begin_station"]
    with pytest.raises(params.ParamsError, match="begin_station"):
        params.parse(raw)


def test_pier_outside_range_raises():
    raw = _valid_raw()
    raw["piers"][0]["station"] = 999.0
    with pytest.raises(params.ParamsError, match="outside bridge range"):
        params.parse(raw)
