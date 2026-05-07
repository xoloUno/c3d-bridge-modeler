"""AISC W-shape lookup table.

Loads `data/aisc_w_shapes.json` and exposes shapes by designation.
Values are stored in AISC native units (inches, lb/ft); use
`src/units.py` helpers to convert to drawing units when generating
geometry.

Pure-logic module: must not import anything from the Civil 3D API
(`clr`, `Autodesk.*`). Importable on macOS for unit testing.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class WShape:
    designation: str
    lb_per_ft: float
    area_in2: float
    d_in: float
    bf_in: float
    tw_in: float
    tf_in: float
    kdes_in: Optional[float] = None
    T_in: Optional[float] = None
    ix_in4: Optional[float] = None
    sx_in3: Optional[float] = None
    zx_in3: Optional[float] = None
    rx_in: Optional[float] = None
    iy_in4: Optional[float] = None
    sy_in3: Optional[float] = None
    zy_in3: Optional[float] = None
    ry_in: Optional[float] = None
    j_in4: Optional[float] = None


_REQUIRED_FIELDS = ("lb_per_ft", "area_in2", "d_in", "bf_in", "tw_in", "tf_in")
_EXPECTED_UNITS = "imperial_inches"


class AiscError(ValueError):
    pass


def default_data_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "data", "aisc_w_shapes.json"))


def load(path: Optional[str] = None) -> Dict[str, WShape]:
    """Load and validate the W-shape table. Returns dict keyed by designation."""
    if path is None:
        path = default_data_path()
    with open(path) as f:
        raw = json.load(f)
    return parse(raw)


def parse(raw: dict) -> Dict[str, WShape]:
    units = raw.get("units")
    if units != _EXPECTED_UNITS:
        raise AiscError(
            f"Expected units={_EXPECTED_UNITS!r}, got {units!r}. "
            f"Metric data files are not yet supported."
        )

    shapes_raw = raw.get("shapes")
    if not isinstance(shapes_raw, dict) or not shapes_raw:
        raise AiscError("'shapes' must be a non-empty dict")

    out: Dict[str, WShape] = {}
    for designation, fields in shapes_raw.items():
        if not isinstance(fields, dict):
            raise AiscError(f"Shape {designation!r}: entry must be a dict")
        missing = [k for k in _REQUIRED_FIELDS if k not in fields]
        if missing:
            raise AiscError(f"Shape {designation!r} missing required fields: {missing}")
        out[designation] = WShape(
            designation=designation,
            lb_per_ft=float(fields["lb_per_ft"]),
            area_in2=float(fields["area_in2"]),
            d_in=float(fields["d_in"]),
            bf_in=float(fields["bf_in"]),
            tw_in=float(fields["tw_in"]),
            tf_in=float(fields["tf_in"]),
            kdes_in=_opt_float(fields, "kdes_in"),
            T_in=_opt_float(fields, "T_in"),
            ix_in4=_opt_float(fields, "ix_in4"),
            sx_in3=_opt_float(fields, "sx_in3"),
            zx_in3=_opt_float(fields, "zx_in3"),
            rx_in=_opt_float(fields, "rx_in"),
            iy_in4=_opt_float(fields, "iy_in4"),
            sy_in3=_opt_float(fields, "sy_in3"),
            zy_in3=_opt_float(fields, "zy_in3"),
            ry_in=_opt_float(fields, "ry_in"),
            j_in4=_opt_float(fields, "j_in4"),
        )
    return out


def get(table: Dict[str, WShape], designation: str) -> WShape:
    """Look up a shape, raising AiscError with a helpful message if missing."""
    key = _normalize(designation)
    shape = table.get(key)
    if shape is None:
        raise AiscError(
            f"Shape {designation!r} not found in AISC table "
            f"(normalized to {key!r}). Available: {len(table)} shapes "
            f"({_sample_keys(table)})."
        )
    return shape


def _normalize(designation: str) -> str:
    return designation.strip().upper().replace("×", "X").replace("*", "X")


def _opt_float(d: dict, key: str) -> Optional[float]:
    v = d.get(key)
    return None if v is None else float(v)


def _sample_keys(table: Dict[str, WShape]) -> str:
    keys = sorted(table.keys())
    return ", ".join(keys[:3] + ["..."] + keys[-3:]) if len(keys) > 6 else ", ".join(keys)
