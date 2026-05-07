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
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Tuple

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
    girder_offset: float         # ft, signed (+ = right of alignment CL)
    top_of_deck: float           # ft
    top_of_girder_flange: float  # ft
    bottom_of_girder: float      # ft
    bearing_seat: float          # ft (informational; refined in Phase 1b)


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
    deck_width_start: float
    deck_width_end: float
    bearing_to_bearing_length: float
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

        start_offsets = p1.girder_offsets_at_bearing(
            super_.left_edge_to_G1_start,
            super_.girder_spacings_start,
            super_.Gn_to_right_edge_start,
        )
        end_offsets = p1.girder_offsets_at_bearing(
            super_.left_edge_to_G1_end,
            super_.girder_spacings_end,
            super_.Gn_to_right_edge_end,
        )

        girder_depth_ft = _girder_depth_ft(super_, aisc_table)

        girders_out = []
        for g_idx in range(super_.girder_count):
            start_state = _girder_at_bearing(
                params, super_,
                support_id=start_support.support_id,
                bearing_station=start_bearing_station,
                profile_elevation=start_profile_elev,
                girder_offset=start_offsets[g_idx],
                girder_depth_ft=girder_depth_ft,
                bearing_device_height_ft=bearing_device_height_ft,
            )
            end_state = _girder_at_bearing(
                params, super_,
                support_id=end_support.support_id,
                bearing_station=end_bearing_station,
                profile_elevation=end_profile_elev,
                girder_offset=end_offsets[g_idx],
                girder_depth_ft=girder_depth_ft,
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
                deck_width_start=p1.deck_width(
                    super_.left_edge_to_G1_start,
                    super_.girder_spacings_start,
                    super_.Gn_to_right_edge_start,
                ),
                deck_width_end=p1.deck_width(
                    super_.left_edge_to_G1_end,
                    super_.girder_spacings_end,
                    super_.Gn_to_right_edge_end,
                ),
                bearing_to_bearing_length=end_bearing_station - start_bearing_station,
                girders=tuple(girders_out),
            )
        )

    return Phase1ComputeResult(spans=tuple(spans_out))


# ----------------------------------------------------------------------
# Internals
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


def _girder_at_bearing(
    params: p1.Phase1Params,
    super_: p1.Superstructure,
    *,
    support_id: str,
    bearing_station: float,
    profile_elevation: float,
    girder_offset: float,
    girder_depth_ft: float,
    bearing_device_height_ft: float,
) -> GirderAtBearing:
    top_of_deck = elevation.top_of_deck_at_offset(
        profile_elevation=profile_elevation,
        deck_profile_offset=params.deck_profile_offset,
        crown_offset=params.crown_offset,
        cross_slope_left_pct=params.deck_cross_slope_left,
        cross_slope_right_pct=params.deck_cross_slope_right,
        girder_offset=girder_offset,
    )
    sup = elevation.superstructure_elevations(
        top_of_deck=top_of_deck,
        deck_depth=super_.deck_depth,
        haunch_depth=super_.haunch_depth,
        girder_depth=girder_depth_ft,
        bearing_device_height=bearing_device_height_ft,
    )
    return GirderAtBearing(
        support_id=support_id,
        bearing_station=bearing_station,
        girder_offset=girder_offset,
        top_of_deck=sup.top_of_deck,
        top_of_girder_flange=sup.top_of_girder_flange,
        bottom_of_girder=sup.bottom_of_girder,
        bearing_seat=sup.bearing_seat,
    )


# ----------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------

def format_text_report(result: Phase1ComputeResult) -> str:
    """Render the computed result as a human-readable text table.

    Useful for visual sanity checks during development and for the
    Phase 1b elevation-table CSV export.
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
            f"deck width {span.deck_width_start:.2f} → {span.deck_width_end:.2f} ft"
        )
        header = (
            f"   {'girder':<8} {'support':<10} {'station':>10} {'offset':>8} "
            f"{'top_deck':>10} {'top_flg':>10} {'bot_grdr':>10} {'brg_seat':>10}"
        )
        lines.append(header)
        for g in span.girders:
            for endpt, label in ((g.start, "start"), (g.end, "end")):
                lines.append(
                    f"   G{g.girder_index:<2} {label:<5} {endpt.support_id:<10} "
                    f"{endpt.bearing_station:>10.2f} {endpt.girder_offset:>8.3f} "
                    f"{endpt.top_of_deck:>10.3f} {endpt.top_of_girder_flange:>10.3f} "
                    f"{endpt.bottom_of_girder:>10.3f} {endpt.bearing_seat:>10.3f}"
                )
        lines.append("")
    return "\n".join(lines)
