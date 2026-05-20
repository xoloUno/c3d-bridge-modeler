"""Phase 1 parameter file loading and validation.

Phase 1 scope: straight steel girder superstructure (deck, girders,
haunches), single or multi-span, with flared/variable girder spacing
and skewed supports. Substructure is Phase 1b (separate schema). Plate
girders, curved girder geometry, diaphragms, and haunch chamfer are
all deferred past this slice.

All linear dimensions and stations are in feet. Cross slopes are in
percent (% rise per foot, signed). Skew angles are in degrees from
perpendicular (0 = square).

Coordinate convention
---------------------
- Civil 3D alignment offset: signed distance perpendicular to alignment;
  positive = right of alignment when looking ahead-station.
- Deck centerline (deck CL): a line parallel to the alignment that runs
  through the middle of the deck cross-section. May be offset from
  alignment via `deck_cl_offset_from_alignment` (signed, + = deck CL
  to right of alignment).
- Girder spacings (`left_edge_to_G1_*`, `girder_spacings_*`,
  `Gn_to_right_edge_*`): measured ALONG THE BEARING LINE, which is
  what's labeled on plans next to the bearing-line dimension string.
  For zero-skew supports, along-bearing distance = perpendicular
  distance. For skewed supports the two differ by `1/cos(skew)`.
- Perpendicular deck width (`perpendicular_deck_width_*`): the deck's
  true width measured perpendicular to alignment. This is the
  reference dimension; bearing-line distance is derived as
  `perpendicular_deck_width / cos(skew)` at the relevant support.

Edge-spacing rule
-----------------
Per side (start / end), specify exactly ONE of `left_edge_to_G1` or
`Gn_to_right_edge`. The other must be `null` and is derived at compute
time from `perpendicular_deck_width`, the skew angle at that support,
and the spacings array. This keeps the deck width and girder spacings
geometrically consistent on skewed bridges.

Pure-logic module: must not import anything from the Civil 3D API
(`clr`, `Autodesk.*`). Importable on macOS for unit testing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import deck_geometry as dg
import station_profile as sp


# ----------------------------------------------------------------------
# Allowed enum values (Phase 1 subset of the full schema in scope.md)
# ----------------------------------------------------------------------

GIRDER_TYPES_PHASE_1 = ("W_SHAPE",)
GIRDER_GEOMETRY_PHASE_1 = ("STRAIGHT",)
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

    # Perpendicular-to-alignment deck width at each end of the span.
    perpendicular_deck_width_start: float
    perpendicular_deck_width_end: float

    # Along-bearing-line measurements. Exactly one of left/right edge
    # spacing is non-None per side; the other is derived in compute().
    left_edge_to_G1_start: Optional[float]
    girder_spacings_start: Tuple[float, ...]
    Gn_to_right_edge_start: Optional[float]
    left_edge_to_G1_end: Optional[float]
    girder_spacings_end: Tuple[float, ...]
    Gn_to_right_edge_end: Optional[float]

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
    # template_dwg: path to a bridge-template DWG that supplies layer
    # definitions, linetypes, skeleton styles, and the BRIDGE_IFC
    # PropertySet. CURRENTLY PARSED BUT NOT CONSUMED — the build
    # creates layers ad-hoc and writes xdata (not IFC PropSets). The
    # field is retained so user params keep validating once the
    # template loader lands. See MANUAL-TASKS.md "Bridge template DWG".
    template_dwg: str

    # Bridge geometry envelope
    begin_station: float
    end_station: float
    begin_skew_angle: float
    end_skew_angle: float

    # Deck cross-section. `crown_offset` and `deck_cl_offset_from_alignment`
    # may vary along the bridge — they're stored as StationProfile so that
    # `at(station)` can be queried at any bearing-line station.
    deck_cross_slope_left: float
    deck_cross_slope_right: float
    crown_offset: sp.StationProfile
    deck_cl_offset_from_alignment: sp.StationProfile
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
    "crown_offset", "deck_cl_offset_from_alignment",
    "deck_profile_offset", "follow_superelevation",
    "supports", "spans", "superstructures",
)
_REQUIRED_SUPPORT = ("support_id", "support_type", "station")
_REQUIRED_SPAN = ("span_id", "start_support_id", "end_support_id")
_REQUIRED_SUPER = (
    "girder_type", "girder_shape", "girder_count", "girder_spacing_mode",
    "perpendicular_deck_width_start", "perpendicular_deck_width_end",
    "girder_spacings_start", "girder_spacings_end",
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

    crown_profile = _parse_station_profile(
        raw["crown_offset"], begin, end, "crown_offset"
    )
    deck_cl_profile = _parse_station_profile(
        raw["deck_cl_offset_from_alignment"], begin, end,
        "deck_cl_offset_from_alignment",
    )
    # Phase-1 capability gate: the deck solid is built by sweeping a
    # constant cross-section. station-varying crown_offset would change
    # the cross-section shape along the bridge — not supported.
    # Shifting deck_cl_offset_from_alignment is allowed IFF the deck
    # cross-section has no crown kink at any bearing (deferred check
    # below — requires parsed supports/superstructures to know widths).
    if not crown_profile.is_effectively_constant():
        raise Phase1ParamsError(
            "station-varying crown_offset is not yet supported by the deck "
            "solid (constant-section sweep); collapse to a single value "
            "until station-varying cross-section lands in Phase 2+"
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

    cross_slope_left = float(raw["deck_cross_slope_left"])
    cross_slope_right = float(raw["deck_cross_slope_right"])
    _validate_shifting_dcl_has_no_crown_kink(
        deck_cl_profile=deck_cl_profile,
        crown_profile=crown_profile,
        cross_slope_left=cross_slope_left,
        cross_slope_right=cross_slope_right,
        supports=supports,
        spans=spans,
        superstructures=superstructures,
    )

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
        crown_offset=crown_profile,
        deck_cl_offset_from_alignment=deck_cl_profile,
        deck_profile_offset=float(raw["deck_profile_offset"]),
        follow_superelevation=_parse_follow_superelevation(raw["follow_superelevation"]),
        supports=supports,
        spans=spans,
        superstructures=superstructures,
    )


def _parse_station_profile(raw, begin: float, end: float, name: str) -> sp.StationProfile:
    try:
        return sp.parse(raw, begin_station=begin, end_station=end, name=name)
    except sp.StationProfileError as exc:
        raise Phase1ParamsError(str(exc)) from exc


def _parse_follow_superelevation(raw) -> bool:
    """Strict boolean parse + Phase-1 capability gate.

    Avoid Python's `bool("false") is True` foot-gun by requiring a true
    JSON boolean, then reject `true` until alignment-superelevation
    tracking is implemented (deferred to Phase 2+). Setting `true` today
    would not actually alter the geometry, so silently accepting it
    misrepresents the tool's behavior.
    """
    if not isinstance(raw, bool):
        raise Phase1ParamsError(
            f"follow_superelevation must be a JSON boolean (true/false); "
            f"got {type(raw).__name__} {raw!r}"
        )
    if raw:
        raise Phase1ParamsError(
            "follow_superelevation=true is not yet supported "
            "(alignment superelevation tracking is deferred to Phase 2+); "
            "set follow_superelevation=false until the feature lands"
        )
    return raw


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
    if haunch_width is not None and float(haunch_width) <= 0:
        raise Phase1ParamsError(
            f"{where}.haunch_width must be > 0 when specified "
            f"(got {haunch_width})"
        )

    girder_count = int(raw["girder_count"])
    if girder_count < 2:
        raise Phase1ParamsError(f"{where}.girder_count must be >= 2 (got {girder_count})")

    spacings_start = _parse_spacings(raw["girder_spacings_start"], girder_count, where, "start")
    spacings_end = _parse_spacings(raw["girder_spacings_end"], girder_count, where, "end")

    left_start, right_start = _parse_edge_pair(
        raw, where, "start",
        ("left_edge_to_G1_start", "Gn_to_right_edge_start"),
    )
    left_end, right_end = _parse_edge_pair(
        raw, where, "end",
        ("left_edge_to_G1_end", "Gn_to_right_edge_end"),
    )

    perp_width_start = float(raw["perpendicular_deck_width_start"])
    perp_width_end = float(raw["perpendicular_deck_width_end"])
    if perp_width_start <= 0 or perp_width_end <= 0:
        raise Phase1ParamsError(
            f"{where}.perpendicular_deck_width_* must be positive"
        )

    deck_depth = float(raw["deck_depth"])
    if deck_depth <= 0:
        raise Phase1ParamsError(
            f"{where}.deck_depth must be > 0 (got {deck_depth})"
        )
    haunch_depth = float(raw["haunch_depth"])
    if haunch_depth <= 0:
        raise Phase1ParamsError(
            f"{where}.haunch_depth must be > 0 (got {haunch_depth})"
        )
    topping_depth = float(raw.get("topping_depth", 0.0))
    if topping_depth < 0:
        raise Phase1ParamsError(
            f"{where}.topping_depth must be >= 0 (got {topping_depth})"
        )

    return Superstructure(
        girder_type=girder_type,
        girder_shape=str(raw["girder_shape"]),
        girder_count=girder_count,
        girder_spacing_mode=spacing_mode,
        perpendicular_deck_width_start=perp_width_start,
        perpendicular_deck_width_end=perp_width_end,
        left_edge_to_G1_start=left_start,
        girder_spacings_start=spacings_start,
        Gn_to_right_edge_start=right_start,
        left_edge_to_G1_end=left_end,
        girder_spacings_end=spacings_end,
        Gn_to_right_edge_end=right_end,
        deck_depth=deck_depth,
        haunch_depth=haunch_depth,
        haunch_width_mode=haunch_mode,
        haunch_width=None if haunch_width is None else float(haunch_width),
        girder_geometry=geometry,
        end_diaphragm=bool(raw.get("end_diaphragm", False)),
        topping_depth=topping_depth,
    )


def _parse_edge_pair(
    raw: dict,
    where: str,
    side: str,
    keys: Tuple[str, str],
) -> Tuple[Optional[float], Optional[float]]:
    """Return (left_edge_to_G1, Gn_to_right_edge) for one side; exactly one must be specified."""
    left_key, right_key = keys
    left = raw.get(left_key)
    right = raw.get(right_key)

    if left is None and right is None:
        raise Phase1ParamsError(
            f"{where}: exactly one of {left_key} / {right_key} must be specified "
            f"(both are null)"
        )
    if left is not None and right is not None:
        raise Phase1ParamsError(
            f"{where}: exactly one of {left_key} / {right_key} must be specified "
            f"(both have values; the other must be null so it can be derived from "
            f"perpendicular_deck_width_{side} and the skew at that support)"
        )

    left_f = None if left is None else float(left)
    right_f = None if right is None else float(right)
    if left_f is not None and left_f <= 0:
        raise Phase1ParamsError(
            f"{where}.{left_key} must be > 0 when specified (got {left_f})"
        )
    if right_f is not None and right_f <= 0:
        raise Phase1ParamsError(
            f"{where}.{right_key} must be > 0 when specified (got {right_f})"
        )
    return (left_f, right_f)


def _parse_spacings(raw, girder_count: int, where: str, side: str) -> Tuple[float, ...]:
    if not isinstance(raw, list):
        raise Phase1ParamsError(f"{where}.girder_spacings_{side} must be a list")
    expected = girder_count - 1
    if len(raw) != expected:
        raise Phase1ParamsError(
            f"{where}.girder_spacings_{side} length {len(raw)} "
            f"!= girder_count - 1 ({expected})"
        )
    values = tuple(float(v) for v in raw)
    for i, v in enumerate(values):
        if v <= 0:
            raise Phase1ParamsError(
                f"{where}.girder_spacings_{side}[{i}] must be > 0 (got {v})"
            )
    return values


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


def _validate_shifting_dcl_has_no_crown_kink(
    *,
    deck_cl_profile: sp.StationProfile,
    crown_profile: sp.StationProfile,
    cross_slope_left: float,
    cross_slope_right: float,
    supports: Tuple,
    spans: Tuple,
    superstructures: Tuple,
) -> None:
    """When deck CL shifts along the bridge, require no crown kink at any
    bearing.

    The deck solid is built via a constant cross-section sweep boolean-
    intersected with the trim polygon.  A laterally-shifting deck CL is
    accommodated by widening the fat-deck cross-section and letting the
    trim polygon cut the correct footprint — but ONLY if the cross-
    section has no crown vertex (i.e., it's a 4-corner parallelogram
    rather than a 6-vertex hexagon).  A hexagonal section would need a
    different crown position at each bearing, which a constant-section
    sweep can't deliver.

    "No crown kink" means either: (a) the crown is outside the deck at
    every bearing, or (b) the cross-slopes have opposite signs
    (super-elevated) — both make the cross-section a parallelogram.
    """
    if deck_cl_profile.is_effectively_constant():
        return  # No shift — unchanged behavior

    # Per-bearing kink check.  Iterate each (span, side) pair so each
    # bearing's actual width is used.
    supports_by_id = {s.support_id: s for s in supports}
    bearings_with_widths: List[Tuple[str, float, float]] = []  # (label, station, perp_width)
    for span, super_ in zip(spans, superstructures):
        start_sup = supports_by_id[span.start_support_id]
        end_sup = supports_by_id[span.end_support_id]
        bearings_with_widths.append((
            f"{span.span_id}.start ({start_sup.support_id})",
            start_sup.station,
            super_.perpendicular_deck_width_start,
        ))
        bearings_with_widths.append((
            f"{span.span_id}.end ({end_sup.support_id})",
            end_sup.station,
            super_.perpendicular_deck_width_end,
        ))

    for label, station, perp_width in bearings_with_widths:
        dcl = deck_cl_profile.at(station)
        crown = crown_profile.at(station)
        left_perp = dcl - perp_width / 2.0
        right_perp = dcl + perp_width / 2.0

        if dg.crown_kink_present(
            slope_left_pct=cross_slope_left,
            slope_right_pct=cross_slope_right,
            deck_left_perp=left_perp,
            deck_right_perp=right_perp,
            crown_perp=crown,
        ):
            raise Phase1ParamsError(
                f"shifting deck_cl_offset_from_alignment is only supported "
                f"when the deck cross-section has no crown kink at any bearing; "
                f"bearing {label} at station {station} has a crown straddle "
                f"(crown_perp={crown}, deck=[{left_perp}, {right_perp}]) with "
                f"same-sign cross-slopes ({cross_slope_left}, {cross_slope_right}). "
                f"To use a shifting deck CL, either: (a) shift the deck so the "
                f"crown stays outside [left, right] at every bearing, or (b) use "
                f"opposite-sign cross-slopes (super-elevation), or (c) keep "
                f"deck_cl_offset_from_alignment constant."
            )


# ----------------------------------------------------------------------
# Helpers — pure math, used by build orchestration and tests
# ----------------------------------------------------------------------

def validate_against_aisc(params: Phase1Params, aisc_table: dict) -> List[str]:
    """Cross-validate W-shape designations against the loaded AISC table."""
    errors: List[str] = []
    for i, sup in enumerate(params.superstructures):
        if sup.girder_type != "W_SHAPE":
            continue
        key = sup.girder_shape.strip().upper().replace("×", "X").replace("*", "X")
        if key not in aisc_table:
            errors.append(
                f"superstructures[{i}].girder_shape {sup.girder_shape!r} "
                f"not found in AISC table"
            )
    return errors
