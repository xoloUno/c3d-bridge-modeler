"""Phase 1 end-to-end pure-math orchestrator.

Ties together the Phase 1 params schema, the AISC W-shape table, and
the elevation chain to produce a complete computed result for a Phase 1
bridge: per girder, per bearing line, the top-of-deck / top-of-flange
/ bottom-of-girder / bearing-seat elevations, plus the alignment
station and offset of each bearing-line-girder intersection.

The result is the structured data that downstream code consumes:
- The C3D-side geometry generator uses station, offset, top-of-flange,
  and bottom-of-girder to position girder solids and haunches.
- The drawing-production layer (Phase 1b/3) uses this same data to
  emit elevation tables.

Pure-logic module: must not import anything from the Civil 3D API
(`clr`, `Autodesk.*`). The caller injects profile-elevation lookups
as a callable so the same orchestrator runs against C3D data
shortcuts in production and against canned test data on macOS.

Skew-correction math
--------------------
Girder spacings (`left_edge_to_G1_*`, `girder_spacings_*`,
`Gn_to_right_edge_*`) are along the bearing line — what's printed on
plans next to the bearing-line dimension string. The deck width is
specified perpendicular to alignment via `perpendicular_deck_width_*`.

For a support skewed by θ:
    bearing_line_distance = perpendicular_deck_width / cos(θ)

For a girder at along-bearing distance b from the deck centerline,
its perpendicular distance from the alignment is:
    perpendicular_offset = b · cos(θ) + deck_cl_offset_from_alignment

That perpendicular offset is what `alignment.PointLocation(station,
offset)` and the cross-slope math both consume.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

import aisc
import elevation
import phase1_params as p1
import units


class Phase1ComputeError(ValueError):
    pass


# ----------------------------------------------------------------------
# Result dataclasses
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class GirderAtBearing:
    """Computed state of one girder at one bearing line."""
    support_id: str
    bearing_station: float       # ft, on main alignment
    girder_offset: float         # ft, perpendicular offset, signed (+ = right of alignment)
    along_bearing_offset: float  # ft, signed offset along bearing line (+ = toward right edge of deck)
    top_of_deck: float
    top_of_girder_flange: float
    bottom_of_girder: float
    bearing_seat: float          # ft (informational; refined in Phase 1b)
    haunch_h_left_ft: float      # ft, haunch height at left flange tip (u = -bf/2)
    haunch_h_right_ft: float     # ft, haunch height at right flange tip (u = +bf/2)


@dataclass(frozen=True)
class GirderInSpan:
    girder_index: int            # 1-based (G1, G2, ...)
    start: GirderAtBearing
    end: GirderAtBearing


@dataclass(frozen=True)
class ComputedSpan:
    span_id: str
    start_support_id: str
    end_support_id: str
    girder_count: int
    girder_type: str
    girder_shape: str
    girder_depth_ft: float
    perpendicular_deck_width_start: float
    perpendicular_deck_width_end: float
    bearing_line_length_start: float       # along-bearing length at start support
    bearing_line_length_end: float         # along-bearing length at end support
    bearing_to_bearing_length: float       # girder span (along main alignment)
    girders: Tuple[GirderInSpan, ...]


@dataclass(frozen=True)
class Phase1ComputeResult:
    spans: Tuple[ComputedSpan, ...]


# ----------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------

DEFAULT_BEARING_DEVICE_HEIGHT_FT = 0.5  # 6"; refined in Phase 1b with typed bearings


def compute(
    params: p1.Phase1Params,
    aisc_table: Dict[str, aisc.WShape],
    profile_elevation_at: Callable[[float], float],
    bearing_device_height_ft: float = DEFAULT_BEARING_DEVICE_HEIGHT_FT,
) -> Phase1ComputeResult:
    """Run the full Phase 1 chain. Caller supplies a profile-elevation lookup."""
    aisc_errors = p1.validate_against_aisc(params, aisc_table)
    if aisc_errors:
        raise Phase1ComputeError("; ".join(aisc_errors))

    supports_by_id = {s.support_id: s for s in params.supports}
    spans_out = []

    for span, super_ in zip(params.spans, params.superstructures):
        start_support = supports_by_id[span.start_support_id]
        end_support = supports_by_id[span.end_support_id]

        start_bearing_station = _bearing_station(start_support)
        end_bearing_station = _bearing_station(end_support)

        start_profile_elev = profile_elevation_at(start_bearing_station)
        end_profile_elev = profile_elevation_at(end_bearing_station)

        # Resolve along-bearing girder offsets at start and end, using
        # perpendicular_deck_width + skew to derive the missing edge
        # spacing if needed.
        start_along, start_bearing_len = _resolve_along_bearing_offsets(
            perp_deck_width=super_.perpendicular_deck_width_start,
            skew_deg=start_support.skew_angle,
            left_edge_to_G1=super_.left_edge_to_G1_start,
            girder_spacings=super_.girder_spacings_start,
            Gn_to_right_edge=super_.Gn_to_right_edge_start,
            where=f"{span.span_id} @ {start_support.support_id} (start)",
        )
        end_along, end_bearing_len = _resolve_along_bearing_offsets(
            perp_deck_width=super_.perpendicular_deck_width_end,
            skew_deg=end_support.skew_angle,
            left_edge_to_G1=super_.left_edge_to_G1_end,
            girder_spacings=super_.girder_spacings_end,
            Gn_to_right_edge=super_.Gn_to_right_edge_end,
            where=f"{span.span_id} @ {end_support.support_id} (end)",
        )

        girder_depth_ft = _girder_depth_ft(super_, aisc_table)
        flange_width_ft = _flange_width_ft(super_, aisc_table)

        deck_cl_offset_start = params.deck_cl_offset_from_alignment.at(start_bearing_station)
        deck_cl_offset_end = params.deck_cl_offset_from_alignment.at(end_bearing_station)

        girders_out = []
        for g_idx in range(super_.girder_count):
            start_state = _girder_at_bearing(
                params,
                super_,
                support_id=start_support.support_id,
                bearing_station=start_bearing_station,
                profile_elevation=start_profile_elev,
                along_bearing_offset_from_deck_cl=start_along[g_idx],
                skew_deg=start_support.skew_angle,
                deck_cl_offset_from_alignment=deck_cl_offset_start,
                girder_depth_ft=girder_depth_ft,
                flange_width_ft=flange_width_ft,
                bearing_device_height_ft=bearing_device_height_ft,
            )
            end_state = _girder_at_bearing(
                params,
                super_,
                support_id=end_support.support_id,
                bearing_station=end_bearing_station,
                profile_elevation=end_profile_elev,
                along_bearing_offset_from_deck_cl=end_along[g_idx],
                skew_deg=end_support.skew_angle,
                deck_cl_offset_from_alignment=deck_cl_offset_end,
                girder_depth_ft=girder_depth_ft,
                flange_width_ft=flange_width_ft,
                bearing_device_height_ft=bearing_device_height_ft,
            )
            girders_out.append(
                GirderInSpan(girder_index=g_idx + 1, start=start_state, end=end_state)
            )

        spans_out.append(
            ComputedSpan(
                span_id=span.span_id,
                start_support_id=start_support.support_id,
                end_support_id=end_support.support_id,
                girder_count=super_.girder_count,
                girder_type=super_.girder_type,
                girder_shape=super_.girder_shape,
                girder_depth_ft=girder_depth_ft,
                perpendicular_deck_width_start=super_.perpendicular_deck_width_start,
                perpendicular_deck_width_end=super_.perpendicular_deck_width_end,
                bearing_line_length_start=start_bearing_len,
                bearing_line_length_end=end_bearing_len,
                bearing_to_bearing_length=end_bearing_station - start_bearing_station,
                girders=tuple(girders_out),
            )
        )

    return Phase1ComputeResult(spans=tuple(spans_out))


# ----------------------------------------------------------------------
# Internals — geometry helpers
# ----------------------------------------------------------------------

def _bearing_station(support: p1.Support) -> float:
    """Bearing-line station for a single-bearing support (Phase 1)."""
    if len(support.bearing_offsets) != 1:
        raise Phase1ComputeError(
            f"Support {support.support_id!r} has {len(support.bearing_offsets)} "
            f"bearing offsets; multi-bearing handling is Phase 2+"
        )
    return support.station + support.bearing_offsets[0]


def _girder_depth_ft(
    super_: p1.Superstructure, aisc_table: Dict[str, aisc.WShape]
) -> float:
    if super_.girder_type == "W_SHAPE":
        shape = aisc.get(aisc_table, super_.girder_shape)
        return units.in_to_ft(shape.d_in)
    raise Phase1ComputeError(
        f"girder_type {super_.girder_type!r} not yet supported by orchestrator "
        f"(PLATE_GIRDER and others are deferred to follow-up slices)"
    )


def _flange_width_ft(
    super_: p1.Superstructure, aisc_table: Dict[str, aisc.WShape]
) -> float:
    if super_.girder_type == "W_SHAPE":
        shape = aisc.get(aisc_table, super_.girder_shape)
        return units.in_to_ft(shape.bf_in)
    raise Phase1ComputeError(
        f"girder_type {super_.girder_type!r} not yet supported by orchestrator "
        f"(PLATE_GIRDER and others are deferred to follow-up slices)"
    )


def _resolve_along_bearing_offsets(
    *,
    perp_deck_width: float,
    skew_deg: float,
    left_edge_to_G1: Optional[float],
    girder_spacings: Tuple[float, ...],
    Gn_to_right_edge: Optional[float],
    where: str,
) -> Tuple[Tuple[float, ...], float]:
    """Compute (girder along-bearing offsets from deck CL, along-bearing length).

    Derives the missing edge spacing from `perpendicular_deck_width / cos(skew)`
    and the spacings + the specified edge spacing. Sign convention for
    along-bearing offsets: +ve = toward right edge of deck.
    """
    cos_skew = math.cos(math.radians(skew_deg))
    if cos_skew <= 0.0:
        raise Phase1ComputeError(
            f"{where}: skew {skew_deg}° produces non-positive cos(skew); "
            f"|skew| must be < 90 degrees"
        )
    bearing_line_dist = perp_deck_width / cos_skew

    if left_edge_to_G1 is None and Gn_to_right_edge is None:
        # Validated at parse time, defensive
        raise Phase1ComputeError(
            f"{where}: both edge spacings are None — should have been caught by parse()"
        )
    if left_edge_to_G1 is None:
        left_edge_to_G1 = bearing_line_dist - sum(girder_spacings) - Gn_to_right_edge
    elif Gn_to_right_edge is None:
        Gn_to_right_edge = bearing_line_dist - sum(girder_spacings) - left_edge_to_G1

    if left_edge_to_G1 < 0.0:
        raise Phase1ComputeError(
            f"{where}: derived left_edge_to_G1 is negative ({left_edge_to_G1:.3f} ft) — "
            f"perpendicular_deck_width/cos(skew) = {bearing_line_dist:.3f} ft is smaller "
            f"than spacings + Gn_to_right_edge"
        )
    if Gn_to_right_edge < 0.0:
        raise Phase1ComputeError(
            f"{where}: derived Gn_to_right_edge is negative ({Gn_to_right_edge:.3f} ft) — "
            f"perpendicular_deck_width/cos(skew) = {bearing_line_dist:.3f} ft is smaller "
            f"than spacings + left_edge_to_G1"
        )

    # Along-bearing offsets, with deck CL at 0 (positive = right edge direction)
    left_edge_along_bearing = -bearing_line_dist / 2.0
    along = [left_edge_along_bearing + left_edge_to_G1]  # G1
    for s in girder_spacings:
        along.append(along[-1] + s)
    return tuple(along), bearing_line_dist


def _girder_at_bearing(
    params: p1.Phase1Params,
    super_: p1.Superstructure,
    *,
    support_id: str,
    bearing_station: float,
    profile_elevation: float,
    along_bearing_offset_from_deck_cl: float,
    skew_deg: float,
    deck_cl_offset_from_alignment: float,
    girder_depth_ft: float,
    flange_width_ft: float,
    bearing_device_height_ft: float,
) -> GirderAtBearing:
    cos_skew = math.cos(math.radians(skew_deg))
    perpendicular_offset = (
        along_bearing_offset_from_deck_cl * cos_skew + deck_cl_offset_from_alignment
    )

    crown_offset_here = params.crown_offset.at(bearing_station)

    top_of_deck = elevation.top_of_deck_at_offset(
        profile_elevation=profile_elevation,
        deck_profile_offset=params.deck_profile_offset,
        crown_offset=crown_offset_here,
        cross_slope_left_pct=params.deck_cross_slope_left,
        cross_slope_right_pct=params.deck_cross_slope_right,
        girder_offset=perpendicular_offset,
    )
    sup = elevation.superstructure_elevations(
        top_of_deck=top_of_deck,
        deck_depth=super_.deck_depth,
        haunch_depth=super_.haunch_depth,
        girder_depth=girder_depth_ft,
        bearing_device_height=bearing_device_height_ft,
    )

    # Haunch heights at the flange tips: evaluate top_of_deck at the
    # tips' perpendicular offsets, subtract deck_depth and the (flat)
    # top_of_girder_flange Z. For a girder fully on one side of the
    # crown with constant cross-slope, both are constant along the
    # girder, so a constant-profile sweep on the Civil-3D side is
    # accurate. Crown-straddling and station-varying crown / deck-CL
    # offsets are handled correctly by this per-bearing-line evaluation
    # (though the Phase 1 baseline sweep uses only the start values —
    # see `haunches.py` for the build-time approximation).
    half_bf = flange_width_ft / 2.0
    top_of_deck_left_tip = elevation.top_of_deck_at_offset(
        profile_elevation=profile_elevation,
        deck_profile_offset=params.deck_profile_offset,
        crown_offset=crown_offset_here,
        cross_slope_left_pct=params.deck_cross_slope_left,
        cross_slope_right_pct=params.deck_cross_slope_right,
        girder_offset=perpendicular_offset - half_bf,
    )
    top_of_deck_right_tip = elevation.top_of_deck_at_offset(
        profile_elevation=profile_elevation,
        deck_profile_offset=params.deck_profile_offset,
        crown_offset=crown_offset_here,
        cross_slope_left_pct=params.deck_cross_slope_left,
        cross_slope_right_pct=params.deck_cross_slope_right,
        girder_offset=perpendicular_offset + half_bf,
    )
    haunch_h_left = top_of_deck_left_tip - super_.deck_depth - sup.top_of_girder_flange
    haunch_h_right = top_of_deck_right_tip - super_.deck_depth - sup.top_of_girder_flange

    return GirderAtBearing(
        support_id=support_id,
        bearing_station=bearing_station,
        girder_offset=perpendicular_offset,
        along_bearing_offset=along_bearing_offset_from_deck_cl,
        top_of_deck=sup.top_of_deck,
        top_of_girder_flange=sup.top_of_girder_flange,
        bottom_of_girder=sup.bottom_of_girder,
        bearing_seat=sup.bearing_seat,
        haunch_h_left_ft=haunch_h_left,
        haunch_h_right_ft=haunch_h_right,
    )


# ----------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------

def format_text_report(result: Phase1ComputeResult) -> str:
    """Render the computed result as a human-readable text table.

    `offset` column = perpendicular offset from alignment (ft, + = right of
    alignment), which is what `alignment.PointLocation(station, offset)`
    consumes. The along-bearing offset (from deck CL) is shown in
    parentheses as a sanity-check.
    """
    lines = []
    for span in result.spans:
        lines.append(
            f"== {span.span_id} ({span.start_support_id} → {span.end_support_id}) =="
        )
        lines.append(
            f"   {span.girder_count} × {span.girder_shape} "
            f"(d={span.girder_depth_ft:.3f} ft); "
            f"L_bearing={span.bearing_to_bearing_length:.2f} ft; "
            f"perp deck width {span.perpendicular_deck_width_start:.2f} → "
            f"{span.perpendicular_deck_width_end:.2f} ft "
            f"(along-bearing {span.bearing_line_length_start:.2f} → "
            f"{span.bearing_line_length_end:.2f})"
        )
        header = (
            f"   {'girder':<8} {'support':<10} {'station':>10} "
            f"{'perp_off':>9} {'along_brg':>10} "
            f"{'top_deck':>10} {'top_flg':>10} {'bot_grdr':>10} {'brg_seat':>10} "
            f"{'hnch_L':>8} {'hnch_R':>8}"
        )
        lines.append(header)
        for g in span.girders:
            for endpt, label in ((g.start, "start"), (g.end, "end")):
                lines.append(
                    f"   G{g.girder_index:<2} {label:<5} {endpt.support_id:<10} "
                    f"{endpt.bearing_station:>10.2f} "
                    f"{endpt.girder_offset:>9.3f} {endpt.along_bearing_offset:>10.3f} "
                    f"{endpt.top_of_deck:>10.3f} {endpt.top_of_girder_flange:>10.3f} "
                    f"{endpt.bottom_of_girder:>10.3f} {endpt.bearing_seat:>10.3f} "
                    f"{endpt.haunch_h_left_ft:>8.3f} {endpt.haunch_h_right_ft:>8.3f}"
                )
        lines.append("")
    return "\n".join(lines)
