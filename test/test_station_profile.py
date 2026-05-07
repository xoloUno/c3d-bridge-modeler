"""Unit tests for src/station_profile.py. Run with `pytest test/` from the repo root."""
from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import station_profile as sp  # noqa: E402


# ----------------------------------------------------------------------
# Scalar form
# ----------------------------------------------------------------------

def test_scalar_creates_two_point_flat_profile():
    p = sp.parse(2.5, begin_station=100.0, end_station=200.0, name="x")
    assert p.points == ((100.0, 2.5), (200.0, 2.5))
    assert p.at(100.0) == 2.5
    assert p.at(150.0) == 2.5
    assert p.at(200.0) == 2.5


def test_scalar_zero_works():
    p = sp.parse(0, begin_station=0.0, end_station=100.0, name="x")
    assert p.at(50.0) == 0.0


def test_scalar_negative_works():
    p = sp.parse(-3.5, begin_station=0.0, end_station=100.0, name="x")
    assert p.at(50.0) == -3.5


def test_bool_rejected():
    with pytest.raises(sp.StationProfileError, match="boolean"):
        sp.parse(True, begin_station=0.0, end_station=100.0, name="x")


def test_string_rejected():
    with pytest.raises(sp.StationProfileError, match="must be a number"):
        sp.parse("0.0", begin_station=0.0, end_station=100.0, name="x")


# ----------------------------------------------------------------------
# Array form
# ----------------------------------------------------------------------

def test_array_two_points_linear():
    p = sp.parse(
        [{"station": 0.0, "value": 0.0}, {"station": 100.0, "value": 10.0}],
        begin_station=0.0,
        end_station=100.0,
        name="x",
    )
    assert p.at(0.0) == 0.0
    assert p.at(50.0) == 5.0
    assert p.at(100.0) == 10.0


def test_array_three_points_piecewise_linear():
    p = sp.parse(
        [
            {"station": 0.0, "value": 0.0},
            {"station": 50.0, "value": 10.0},
            {"station": 100.0, "value": 0.0},
        ],
        begin_station=0.0,
        end_station=100.0,
        name="x",
    )
    assert p.at(25.0) == 5.0
    assert p.at(50.0) == 10.0
    assert p.at(75.0) == 5.0


def test_array_held_flat_outside_range():
    p = sp.parse(
        [{"station": 100.0, "value": 5.0}, {"station": 200.0, "value": 10.0}],
        begin_station=100.0,
        end_station=200.0,
        name="x",
    )
    # Outside the control point range → endpoint value held
    assert p.at(50.0) == 5.0
    assert p.at(250.0) == 10.0


def test_realistic_crown_migration():
    # Crown migrates from offset +9 (at begin) to 0 (at end) — common in
    # superelevation transitions where the deck rolls from crowned to
    # one-way slope as it approaches a curve.
    p = sp.parse(
        [
            {"station": 10992.64, "value": 9.0},
            {"station": 11071.87, "value": 0.0},
        ],
        begin_station=10992.64,
        end_station=11071.87,
        name="crown_offset",
    )
    midpoint = (10992.64 + 11071.87) / 2.0
    assert math.isclose(p.at(midpoint), 4.5, abs_tol=1e-9)


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------

def test_array_too_short():
    with pytest.raises(sp.StationProfileError, match="at least 2"):
        sp.parse(
            [{"station": 0.0, "value": 0.0}],
            begin_station=0.0, end_station=100.0, name="x",
        )


def test_array_entries_must_be_objects():
    with pytest.raises(sp.StationProfileError, match="must be an object"):
        sp.parse(
            [0.0, 100.0],
            begin_station=0.0, end_station=100.0, name="x",
        )


def test_array_missing_station_or_value():
    with pytest.raises(sp.StationProfileError, match="missing 'value'"):
        sp.parse(
            [{"station": 0.0}, {"station": 100.0, "value": 10.0}],
            begin_station=0.0, end_station=100.0, name="x",
        )


def test_array_must_be_strictly_ascending():
    with pytest.raises(sp.StationProfileError, match="strictly ascending"):
        sp.parse(
            [
                {"station": 100.0, "value": 0.0},
                {"station": 50.0, "value": 5.0},
            ],
            begin_station=0.0, end_station=100.0, name="x",
        )


def test_array_duplicate_stations_rejected():
    with pytest.raises(sp.StationProfileError, match="strictly ascending"):
        sp.parse(
            [
                {"station": 50.0, "value": 0.0},
                {"station": 50.0, "value": 5.0},
            ],
            begin_station=0.0, end_station=100.0, name="x",
        )


def test_array_first_point_must_cover_begin():
    with pytest.raises(sp.StationProfileError, match="begin_station"):
        sp.parse(
            [
                {"station": 50.0, "value": 0.0},
                {"station": 100.0, "value": 5.0},
            ],
            begin_station=10.0, end_station=100.0, name="x",
        )


def test_array_last_point_must_cover_end():
    with pytest.raises(sp.StationProfileError, match="end_station"):
        sp.parse(
            [
                {"station": 0.0, "value": 0.0},
                {"station": 50.0, "value": 5.0},
            ],
            begin_station=0.0, end_station=100.0, name="x",
        )


def test_unsupported_type():
    with pytest.raises(sp.StationProfileError, match="must be a number"):
        sp.parse(
            {"station": 0.0},
            begin_station=0.0, end_station=100.0, name="x",
        )


# ----------------------------------------------------------------------
# is_effectively_constant_zero
# ----------------------------------------------------------------------

def test_constant_zero_is_zero():
    p = sp.parse(0.0, begin_station=0.0, end_station=100.0, name="x")
    assert p.is_effectively_constant_zero()


def test_nearly_zero_within_tolerance_is_zero():
    p = sp.parse(1e-12, begin_station=0.0, end_station=100.0, name="x")
    assert p.is_effectively_constant_zero()
    assert p.is_effectively_constant_zero(tolerance=1e-9)


def test_constant_nonzero_is_not_zero():
    p = sp.parse(5.0, begin_station=0.0, end_station=100.0, name="x")
    assert not p.is_effectively_constant_zero()


def test_negative_constant_is_not_zero():
    p = sp.parse(-5.0, begin_station=0.0, end_station=100.0, name="x")
    assert not p.is_effectively_constant_zero()


def test_array_with_one_nonzero_value_is_not_zero():
    p = sp.parse(
        [{"station": 0.0, "value": 0.0}, {"station": 100.0, "value": 1.0}],
        begin_station=0.0, end_station=100.0, name="x",
    )
    assert not p.is_effectively_constant_zero()


def test_array_all_zeros_is_zero():
    p = sp.parse(
        [
            {"station": 0.0, "value": 0.0},
            {"station": 50.0, "value": 0.0},
            {"station": 100.0, "value": 0.0},
        ],
        begin_station=0.0, end_station=100.0, name="x",
    )
    assert p.is_effectively_constant_zero()


def test_value_just_above_tolerance_is_not_zero():
    p = sp.parse(0.001, begin_station=0.0, end_station=100.0, name="x")
    assert not p.is_effectively_constant_zero(tolerance=1e-9)
    assert p.is_effectively_constant_zero(tolerance=0.01)
