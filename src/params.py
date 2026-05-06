"""Phase 0 parameter file loading and validation.

Pure-logic module: must not import anything from the Civil 3D API
(`clr`, `Autodesk.*`). Importable on macOS for unit testing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Pier:
    id: str
    station: float
    length: float
    width: float
    height: float


@dataclass(frozen=True)
class Phase0Params:
    alignment_name: str
    profile_name: str
    eg_surface_name: str
    begin_station: float
    end_station: float
    deck_width: float
    deck_depth: float
    piers: List[Pier]


_REQUIRED_TOP_LEVEL = (
    "alignment_name",
    "profile_name",
    "eg_surface_name",
    "begin_station",
    "end_station",
    "deck_width",
    "deck_depth",
    "piers",
)
_REQUIRED_PIER = ("id", "station", "length", "width", "height")


class ParamsError(ValueError):
    pass


def load(path: str) -> Phase0Params:
    with open(path) as f:
        return parse(json.load(f))


def parse(raw: dict) -> Phase0Params:
    missing = [k for k in _REQUIRED_TOP_LEVEL if k not in raw]
    if missing:
        raise ParamsError(f"Missing required keys: {missing}")

    if not isinstance(raw["piers"], list) or len(raw["piers"]) < 2:
        raise ParamsError("piers must be a list with at least 2 entries")

    begin = float(raw["begin_station"])
    end = float(raw["end_station"])
    if begin >= end:
        raise ParamsError(
            f"begin_station ({begin}) must be less than end_station ({end})"
        )

    piers: List[Pier] = []
    for i, p in enumerate(raw["piers"]):
        missing_p = [k for k in _REQUIRED_PIER if k not in p]
        if missing_p:
            raise ParamsError(f"Pier index {i} missing keys: {missing_p}")
        pier = Pier(
            id=str(p["id"]),
            station=float(p["station"]),
            length=float(p["length"]),
            width=float(p["width"]),
            height=float(p["height"]),
        )
        if not (begin <= pier.station <= end):
            raise ParamsError(
                f"Pier {pier.id} station {pier.station} outside bridge range "
                f"[{begin}, {end}]"
            )
        piers.append(pier)

    return Phase0Params(
        alignment_name=str(raw["alignment_name"]),
        profile_name=str(raw["profile_name"]),
        eg_surface_name=str(raw["eg_surface_name"]),
        begin_station=begin,
        end_station=end,
        deck_width=float(raw["deck_width"]),
        deck_depth=float(raw["deck_depth"]),
        piers=piers,
    )
