"""Unit tests for src/units.py. Run with `pytest test/` from the repo root."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import units  # noqa: E402


def test_in_to_ft_round_numbers():
    assert units.in_to_ft(12.0) == 1.0
    assert units.in_to_ft(36.0) == 3.0
    assert units.in_to_ft(0.0) == 0.0


def test_ft_to_in_round_numbers():
    assert units.ft_to_in(1.0) == 12.0
    assert units.ft_to_in(2.5) == 30.0


def test_in_ft_round_trip():
    for v in (35.9, 12.0, 0.625, 100.0, 0.0):
        assert abs(units.in_to_ft(units.ft_to_in(v)) - v) < 1e-12
        assert abs(units.ft_to_in(units.in_to_ft(v)) - v) < 1e-12


def test_in_to_mm():
    assert units.in_to_mm(1.0) == 25.4
    assert units.in_to_mm(0.0) == 0.0


def test_mm_to_in():
    assert units.mm_to_in(25.4) == 1.0


def test_ft_to_mm_round_trip():
    for v in (1.0, 5.5, 100.0):
        assert abs(units.mm_to_ft(units.ft_to_mm(v)) - v) < 1e-12
