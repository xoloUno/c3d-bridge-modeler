"""Unit conversion helpers.

AISC shape data is stored in inches (its native published unit) so the
JSON file can be spot-checked directly against the printed Manual.
Civil 3D bridge drawings in the US are typically set to decimal feet,
so geometry-generation code converts at the boundary using these
helpers.

Pure-logic module: must not import anything from the Civil 3D API
(`clr`, `Autodesk.*`). Importable on macOS for unit testing.
"""
from __future__ import annotations


IN_PER_FT = 12.0
MM_PER_IN = 25.4


def in_to_ft(inches: float) -> float:
    return inches / IN_PER_FT


def ft_to_in(feet: float) -> float:
    return feet * IN_PER_FT


def in_to_mm(inches: float) -> float:
    return inches * MM_PER_IN


def mm_to_in(mm: float) -> float:
    return mm / MM_PER_IN


def ft_to_mm(feet: float) -> float:
    return feet * IN_PER_FT * MM_PER_IN


def mm_to_ft(mm: float) -> float:
    return mm / (IN_PER_FT * MM_PER_IN)
