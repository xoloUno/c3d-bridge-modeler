"""Phase 1 parameter file loading and validation.

Phase 1 scope: straight steel girder superstructure (deck, girders,
haunches), single or multi-span, with flared/variable girder spacing
and skewed supports. Substructure is Phase 1b (separate schema). Plate
girders, curved girder geometry, diaphragms, and haunch chamfer are
all deferred past this slice.

All linear dimensions and stations are in feet. Cross slopes are in
percent (% rise per foot, signed). Skew angles are in degrees from
perpendicular (0 = square).

Coordinate convention: alignment is at the deck centerline. Crown is
offset from the alignment by `crown_offset` (signed, + = right).
Girder offsets are computed from the spacing arrays assuming alignment
at deck CL.

Pure-logic module: must not import anything from the Civil 3D API
(`clr`, `Autodesk.*`). Importable on macOS for unit testing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ----------------------------------------------------------------------
# Allowed enum values (Phase 1 subset of the full schema in scope.md)
# ----------------------------------------------------------------------

GIRDER_TYPES_PHASE_1 = ("W_SHAPE",)  # PLATE_GIRDER deferred to next slice
GIRDER_GEOMETRY_PHASE_1 = ("STRAIGHT",)  # CURVED_RADIUS / FOLLOW_ALIGNMENT = Phase 2+
GIRDER_SPACING_MODES = ("EQUAL", "CUSTOM")
HAUNCH_WIDTH_MODES = ("MATCH_TOP_FLANGE", "CUSTOM")
SUPPORT_TYPES = (
    "ABUTMENT_SEAT",
    "ABUTMENT_INTEGRAL",
    "PIER_SINGLE_COLUMN",
    "PIER_MULTI_COLUMN",
    "PIER_WALL",
    "STRADDLE_BENT",
    "NONE",
)


class Phase1ParamsError(ValueError):
    pass


# ----------------------------------------------------------------------
# Dataclasses
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class Support:
    support_id: str
    support_type: str
    station: float
    skew_angle: float = 0.0
    offset: float = 0.0
    bearing_offsets: Tuple[float, ...] = (0.0,)


@dataclass(frozen=True)
class Span:
    span_id: str
    start_support_id: str
    end_support_id: str


@dataclass(frozen=True)
class Superstructure:
    """Per-span superstructure spec. Phase 1 = W-shape girders, straight."""
    girder_type: str
    girder_shape: str
    girder_count: int
    girder_spacing_mode: str
    left_edge_to_G1_start: float
    girder_spacings_start: Tuple[float, ...]
    Gn_to_right_edge_start: float
    left_edge_to_G1_end: float
    girder_spacings_end: Tuple[float, ...]
    Gn_to_right_edge_end: float
    deck_depth: float
    haunch_depth: float
    haunch_width_mode: str = "MATCH_TOP_FLANGE"
    haunch_width: Optional[float] = None
    girder_geometry: str = "STRAIGHT"
    end_diaphragm: bool = False
    topping_depth: float = 0.0


@dataclass(frozen=True)
class Phase1Params:
    # Civil 3D references
    alignment_name: str
    profile_name: str
    eg_surface_name: str
    fg_surface_name: str
    template_dwg: str

    # Bridge geometry envelope
    begin_station: float
    end_station: float
    begin_skew_angle: float
    end_skew_angle: float

    # Deck cross-section
    deck_cross_slope_left: float
    deck_cross_slope_right: float
    crown_offset: float
    deck_profile_offset: float
    follow_superelevation: bool

    # Skeleton
    supports: Tuple[Support, ...]
    spans: Tuple[Span, ...]
    superstructures: Tuple[Superstructure, ...]  # parallel to spans


# ----------------------------------------------------------------------
# Loader and validator
# ----------------------------------------------------------------------

_REQUIRED_TOP_LEVEL = (
    "alignment_name", "profile_name", "eg_surface_name", "fg_surface_name",
    "template_dwg",
    "begin_station", "end_station",
    "begin_skew_angle", "end_skew_angle",
    "deck_cross_slope_left", "deck_cross_slope_right",
    "crown_offset", "deck_profile_offset", "follow_superelevation",
    "supports", "spans", "superstructures",
)
_REQUIRED_SUPPORT = ("support_id", "support_type", "station")
_REQUIRED_SPAN = ("span_id", "start_support_id", "end_support_id")
_REQUIRED_SUPER = (
    "girder_type", "girder_shape", "girder_count", "girder_spacing_mode",
    "left_edge_to_G1_start", "girder_spacings_start", "Gn_to_right_edge_start",
    "left_edge_to_G1_end", "girder_spacings_end", "Gn_to_right_edge_end",
    "deck_depth", "haunch_depth",
)


def load(path: str) -> Phase1Params:
    with open(path) as f:
        return parse(json.load(f))


def parse(raw: dict) -> Phase1Params:
    _require_keys(raw, _REQUIRED_TOP_LEVEL, "top-level params")

    begin = float(raw["begin_station"])
    end = float(raw["end_station"])
    if begin >= end:
        raise Phase1ParamsError(
            f"begin_station ({begin}) must be < end_station ({end})"
        )

    supports = tuple(_parse_support(s, i) for i, s in enumerate(raw["supports"]))
    _require_unique_ids(supports, "support_id")

    spans = tuple(_parse_span(s, i) for i, s in enumerate(raw["spans"]))
    _require_unique_ids(spans, "span_id")

    if not spans:
        raise Phase1ParamsError("spans must be non-empty")

    superstructures_raw = raw["superstructures"]
    if not isinstance(superstructures_raw, list):
        raise Phase1ParamsError("superstructures must be a list")
    if len(superstructures_raw) != len(spans):
        raise Phase1ParamsError(
            f"superstructures count ({len(superstructures_raw)}) "
            f"must equal spans count ({len(spans)})"
        )
    superstructures = tuple(
        _parse_superstructure(s, i) for i, s in enumerate(superstructures_raw)
    )

    _validate_span_support_refs(spans, supports)
    _validate_supports_in_range(supports, begin, end)

    return Phase1Params(
        alignment_name=str(raw["alignment_name"]),
        profile_name=str(raw["profile_name"]),
        eg_surface_name=str(raw["eg_surface_name"]),
        fg_surface_name=str(raw["fg_surface_name"]),
        template_dwg=str(raw["template_dwg"]),
        begin_station=begin,
        end_station=end,
        begin_skew_angle=float(raw["begin_skew_angle"]),
        end_skew_angle=float(raw["end_skew_angle"]),
        deck_cross_slope_left=float(raw["deck_cross_slope_left"]),
        deck_cross_slope_right=float(raw["deck_cross_slope_right"]),
        crown_offset=float(raw["crown_offset"]),
        deck_profile_offset=float(raw["deck_profile_offset"]),
        follow_superelevation=bool(raw["follow_superelevation"]),
        supports=supports,
        spans=spans,
        superstructures=superstructures,
    )


def _parse_support(raw: dict, idx: int) -> Support:
    _require_keys(raw, _REQUIRED_SUPPORT, f"supports[{idx}]")
    stype = str(raw["support_type"])
    if stype not in SUPPORT_TYPES:
        raise Phase1ParamsError(
            f"supports[{idx}].support_type {stype!r} not in {SUPPORT_TYPES}"
        )
    bearing_offsets_raw = raw.get("bearing_offsets", [0.0])
    if not isinstance(bearing_offsets_raw, list) or not bearing_offsets_raw:
        raise Phase1ParamsError(
            f"supports[{idx}].bearing_offsets must be a non-empty list"
        )
    return Support(
        support_id=str(raw["support_id"]),
        support_type=stype,
        station=float(raw["station"]),
        skew_angle=float(raw.get("skew_angle", 0.0)),
        offset=float(raw.get("offset", 0.0)),
        bearing_offsets=tuple(float(v) for v in bearing_offsets_raw),
    )


def _parse_span(raw: dict, idx: int) -> Span:
    _require_keys(raw, _REQUIRED_SPAN, f"spans[{idx}]")
    return Span(
        span_id=str(raw["span_id"]),
        start_support_id=str(raw["start_support_id"]),
        end_support_id=str(raw["end_support_id"]),
    )


def _parse_superstructure(raw: dict, idx: int) -> Superstructure:
    where = f"superstructures[{idx}]"
    _require_keys(raw, _REQUIRED_SUPER, where)

    girder_type = str(raw["girder_type"])
    if girder_type not in GIRDER_TYPES_PHASE_1:
        raise Phase1ParamsError(
            f"{where}.girder_type {girder_type!r} not supported in Phase 1 "
            f"(allowed: {GIRDER_TYPES_PHASE_1})"
        )

    spacing_mode = str(raw["girder_spacing_mode"])
    if spacing_mode not in GIRDER_SPACING_MODES:
        raise Phase1ParamsError(
            f"{where}.girder_spacing_mode {spacing_mode!r} not in {GIRDER_SPACING_MODES}"
        )

    geometry = str(raw.get("girder_geometry", "STRAIGHT"))
    if geometry not in GIRDER_GEOMETRY_PHASE_1:
        raise Phase1ParamsError(
            f"{where}.girder_geometry {geometry!r} not supported in Phase 1 "
            f"(allowed: {GIRDER_GEOMETRY_PHASE_1})"
        )

    haunch_mode = str(raw.get("haunch_width_mode", "MATCH_TOP_FLANGE"))
    if haunch_mode not in HAUNCH_WIDTH_MODES:
        raise Phase1ParamsError(
            f"{where}.haunch_width_mode {haunch_mode!r} not in {HAUNCH_WIDTH_MODES}"
        )
    haunch_width = raw.get("haunch_width")
    if haunch_mode == "CUSTOM" and haunch_width is None:
        raise Phase1ParamsError(
            f"{where}.haunch_width is required when haunch_width_mode == 'CUSTOM'"
        )

    girder_count = int(raw["girder_count"])
    if girder_count < 2:
        raise Phase1ParamsError(f"{where}.girder_count must be >= 2 (got {girder_count})")

    spacings_start = _parse_spacings(raw["girder_spacings_start"], girder_count, where, "start")
    spacings_end = _parse_spacings(raw["girder_spacings_end"], girder_count, where, "end")

    return Superstructure(
        girder_type=girder_type,
        girder_shape=str(raw["girder_shape"]),
        girder_count=girder_count,
        girder_spacing_mode=spacing_mode,
        left_edge_to_G1_start=float(raw["left_edge_to_G1_start"]),
        girder_spacings_start=spacings_start,
        Gn_to_right_edge_start=float(raw["Gn_to_right_edge_start"]),
        left_edge_to_G1_end=float(raw["left_edge_to_G1_end"]),
        girder_spacings_end=spacings_end,
        Gn_to_right_edge_end=float(raw["Gn_to_right_edge_end"]),
        deck_depth=float(raw["deck_depth"]),
        haunch_depth=float(raw["haunch_depth"]),
        haunch_width_mode=haunch_mode,
        haunch_width=None if haunch_width is None else float(haunch_width),
        girder_geometry=geometry,
        end_diaphragm=bool(raw.get("end_diaphragm", False)),
        topping_depth=float(raw.get("topping_depth", 0.0)),
    )


def _parse_spacings(raw, girder_count: int, where: str, side: str) -> Tuple[float, ...]:
    if not isinstance(raw, list):
        raise Phase1ParamsError(f"{where}.girder_spacings_{side} must be a list")
    expected = girder_count - 1
    if len(raw) != expected:
        raise Phase1ParamsError(
            f"{where}.girder_spacings_{side} length {len(raw)} "
            f"!= girder_count - 1 ({expected})"
        )
    return tuple(float(v) for v in raw)


def _require_keys(raw: dict, keys, where: str) -> None:
    missing = [k for k in keys if k not in raw]
    if missing:
        raise Phase1ParamsError(f"{where} missing required keys: {missing}")


def _require_unique_ids(items, id_attr: str) -> None:
    ids = [getattr(it, id_attr) for it in items]
    seen = set()
    dups = []
    for i in ids:
        if i in seen:
            dups.append(i)
        seen.add(i)
    if dups:
        raise Phase1ParamsError(f"Duplicate {id_attr}: {dups}")


def _validate_span_support_refs(spans, supports) -> None:
    ids = {s.support_id for s in supports}
    for sp in spans:
        for ref in (sp.start_support_id, sp.end_support_id):
            if ref not in ids:
                raise Phase1ParamsError(
                    f"Span {sp.span_id} references unknown support_id {ref!r}"
                )


def _validate_supports_in_range(supports, begin: float, end: float) -> None:
    for s in supports:
        if not (begin <= s.station <= end):
            raise Phase1ParamsError(
                f"Support {s.support_id} station {s.station} outside bridge range "
                f"[{begin}, {end}]"
            )


# ----------------------------------------------------------------------
# Helpers — pure math, used by build orchestration and tests
# ----------------------------------------------------------------------

def girder_offsets_at_bearing(
    left_edge_to_G1: float,
    girder_spacings: Tuple[float, ...],
    Gn_to_right_edge: float,
) -> Tuple[float, ...]:
    """Return signed offsets (ft) of each girder centerline from the deck CL.

    Assumes alignment at deck CL: deck spans symmetrically [-W/2, +W/2]
    where W is the total deck width derived from the spacing arrays.
    """
    deck_width = left_edge_to_G1 + sum(girder_spacings) + Gn_to_right_edge
    left_edge = -deck_width / 2.0
    offsets = [left_edge + left_edge_to_G1]
    for spacing in girder_spacings:
        offsets.append(offsets[-1] + spacing)
    return tuple(offsets)


def deck_width(
    left_edge_to_G1: float,
    girder_spacings: Tuple[float, ...],
    Gn_to_right_edge: float,
) -> float:
    return left_edge_to_G1 + sum(girder_spacings) + Gn_to_right_edge


def validate_against_aisc(params: Phase1Params, aisc_table: dict) -> List[str]:
    """Cross-validate W-shape designations against the loaded AISC table.

    Returns a list of error strings (empty if all shapes resolve). Caller
    can raise or report as preferred. AISC table loading is the caller's
    responsibility (see src/aisc.load).
    """
    errors: List[str] = []
    for i, sup in enumerate(params.superstructures):
        if sup.girder_type != "W_SHAPE":
            continue
        # Use the same normalization src/aisc.get applies
        key = sup.girder_shape.strip().upper().replace("×", "X").replace("*", "X")
        if key not in aisc_table:
            errors.append(
                f"superstructures[{i}].girder_shape {sup.girder_shape!r} "
                f"not found in AISC table"
            )
    return errors
