"""Bridge skeleton creation in Civil 3D.

For Phase 1 the skeleton is one C3D Sample Line per support, placed
at `support.station` with the support's skew angle. Sample lines
serve dual purpose per scope.md:
  1. Bridge skeleton for solid generation (downstream slices read
     positions from these sample lines on update runs)
  2. Section-cut locations for drawing production

Civil-3D-only. Will not import on macOS.

API references confirmed against Camber (mzjensen/Camber, BSD-3):
  - `alignment.GetSampleLineGroupIds()`            -> ObjectIdCollection
  - `SampleLineGroup.Create(name, alignmentId)`    -> ObjectId
  - `SampleLine.Create(name, groupId, Point2dCol)` -> ObjectId

Idempotent behavior: if a sample line group with our group name
already exists on the alignment, this slice DOES NOT recreate it.
The two-mode workflow (scope.md) treats existing skeleton geometry
as authoritative — designers may have moved sample lines between
runs. Read-back of moved positions is a follow-up slice.
"""
from __future__ import annotations

import math
from typing import List

import clr

clr.AddReference("acdbmgd")
clr.AddReference("AeccDbMgd")

from Autodesk.AutoCAD.DatabaseServices import OpenMode  # noqa: E402
from Autodesk.AutoCAD.Geometry import Point2d, Point2dCollection  # noqa: E402
from Autodesk.Civil.DatabaseServices import (  # noqa: E402
    SampleLine,
    SampleLineGroup,
)

import alignment as al


SAMPLE_LINE_GROUP_NAME = "BRIDGE-SUPPORTS"
DEFAULT_OVERHANG_FT = 1.0  # extra length past each deck edge for visibility
BEARING_SUFFIX = ".BRG"  # appended to support_id for bearing-line sample lines


class SkeletonError(RuntimeError):
    pass


def ensure_support_sample_lines(
    tr,
    alignment_obj,
    supports,
    deck_widths_by_support_id: dict,
    deck_cl_offsets_by_support_id: dict,
    group_name: str = SAMPLE_LINE_GROUP_NAME,
    overhang_ft: float = DEFAULT_OVERHANG_FT,
) -> dict:
    """Create the bridge sample-line group + per-support sample lines if absent.

    Returns a dict with keys:
      - "group_id":   ObjectId of the (existing or newly created) group
      - "created":    list of (support_id, sample_line_id) for new sample lines
      - "preserved":  list of (support_id, sample_line_id) found already in place

    Re-running this function on a drawing that already has the skeleton is a
    no-op for the existing entries — the designer's manual edits are kept.
    Per-support naming uses `support.support_id`, so adding a new support to
    JSON between runs causes only the new sample line to be created.

    `deck_widths_by_support_id` carries the along-bearing length of the
    bearing line at each support (`perpendicular_deck_width / cos(skew)`).
    `deck_cl_offsets_by_support_id` carries the signed deck-CL-from-alignment
    offset at each support (sampled at the bearing station; +ve = right of
    alignment). When non-zero, sample lines extend asymmetrically from the
    alignment crossing — more reach on the deck-far side, less on the
    alignment-near side — so the line lands flush with both deck edges.
    """
    existing_group_id = _find_group_by_name(tr, alignment_obj, group_name)
    if existing_group_id is None:
        group_id = SampleLineGroup.Create(group_name, alignment_obj.ObjectId)
    else:
        group_id = existing_group_id

    group = tr.GetObject(group_id, OpenMode.ForRead)
    existing_names = _existing_sample_line_names(tr, group)

    created = []
    preserved = []
    for support in supports:
        deck_width = deck_widths_by_support_id.get(support.support_id)
        if deck_width is None:
            raise SkeletonError(
                f"deck width for support {support.support_id!r} not provided"
            )
        deck_cl_offset = deck_cl_offsets_by_support_id.get(support.support_id, 0.0)

        # Support sample line at support.station
        _ensure_one_sample_line(
            tr=tr,
            alignment_obj=alignment_obj,
            group_id=group_id,
            existing_names=existing_names,
            name=support.support_id,
            station=support.station,
            skew_deg=support.skew_angle,
            deck_width_along_bearing=deck_width,
            deck_cl_offset=deck_cl_offset,
            overhang_ft=overhang_ft,
            created=created,
            preserved=preserved,
        )

        # Bearing-line sample lines at support.station + each bearing_offset
        bearing_offsets = tuple(support.bearing_offsets)
        for i, brg_offset in enumerate(bearing_offsets):
            if abs(brg_offset) < 1e-9:
                # Coincides with support station — would duplicate the
                # support sample line; skip.
                continue
            brg_name = (
                f"{support.support_id}{BEARING_SUFFIX}"
                if len(bearing_offsets) == 1
                else f"{support.support_id}{BEARING_SUFFIX}.{i}"
            )
            _ensure_one_sample_line(
                tr=tr,
                alignment_obj=alignment_obj,
                group_id=group_id,
                existing_names=existing_names,
                name=brg_name,
                station=support.station + brg_offset,
                skew_deg=support.skew_angle,
                deck_width_along_bearing=deck_width,
                deck_cl_offset=deck_cl_offset,
                overhang_ft=overhang_ft,
                created=created,
                preserved=preserved,
            )

    return {"group_id": group_id, "created": created, "preserved": preserved}


def _ensure_one_sample_line(
    *,
    tr,
    alignment_obj,
    group_id,
    existing_names,
    name: str,
    station: float,
    skew_deg: float,
    deck_width_along_bearing: float,
    deck_cl_offset: float,
    overhang_ft: float,
    created: list,
    preserved: list,
) -> None:
    """Create one sample line if absent; preserve if already present."""
    if name in existing_names:
        preserved.append((name, existing_names[name]))
        return

    endpoints = _skewed_endpoints(
        alignment_obj=alignment_obj,
        station=station,
        skew_deg=skew_deg,
        deck_width_along_bearing=deck_width_along_bearing,
        deck_cl_offset=deck_cl_offset,
        overhang_ft=overhang_ft,
    )
    points = Point2dCollection()
    for x, y in endpoints:
        points.Add(Point2d(x, y))

    sl_id = SampleLine.Create(name, group_id, points)
    created.append((name, sl_id))


def _find_group_by_name(tr, alignment_obj, group_name: str):
    """Return the ObjectId of the named sample line group on this alignment, or None."""
    for slg_id in alignment_obj.GetSampleLineGroupIds():
        slg = tr.GetObject(slg_id, OpenMode.ForRead)
        if slg.Name == group_name:
            return slg_id
    return None


def _existing_sample_line_names(tr, group) -> dict:
    """Return a dict of {sample_line_name: object_id} for the given group."""
    out = {}
    for sl_id in group.GetSampleLineIds():
        sl = tr.GetObject(sl_id, OpenMode.ForRead)
        out[sl.Name] = sl_id
    return out


def _skewed_endpoints(
    alignment_obj,
    station: float,
    skew_deg: float,
    deck_width_along_bearing: float,
    deck_cl_offset: float,
    overhang_ft: float,
) -> List[tuple]:
    """Return [(x_left, y_left), (x_right, y_right)] for a sample line.

    Per-side along-bearing displacement from the alignment crossing
    (positive sign = toward right of alignment):

        LEFT  = deck_cl_offset / cos(skew) − deck_width_along_bearing/2 − overhang_ft
        RIGHT = deck_cl_offset / cos(skew) + deck_width_along_bearing/2 + overhang_ft

    `deck_width_along_bearing` is the bearing-line length
    (`perpendicular_deck_width / cos(skew)`). `deck_cl_offset` is the signed
    perpendicular distance from the alignment to the deck centerline at the
    support's bearing station (+ve = right of alignment). `deck_cl_offset /
    cos(skew)` is the along-bearing shift of the deck CL crossing from the
    alignment crossing, so the LEFT/RIGHT endpoints land flush with the
    deck edges plus `overhang_ft` (along-bearing) on either side.

    Equivalence: when `deck_cl_offset == 0`, LEFT = −half_length and RIGHT
    = +half_length where half_length = deck_width/2 + overhang_ft —
    bit-identical to the prior symmetric formula at any skew.

    Skew sign convention: 0 deg = perpendicular to alignment. Positive skew
    rotates the sample line CCW (as seen from above) from the perpendicular,
    so a +30 deg skewed sample line tips its left end ahead-station.
    """
    cx, cy = al.point_at_station(alignment_obj, station, 0.0)
    alignment_dir_rad = al.direction_at_station(alignment_obj, station)
    skew_rad = math.radians(skew_deg)
    cos_skew = math.cos(skew_rad)
    perp_left_dir = alignment_dir_rad + math.pi / 2.0 + skew_rad

    half_brg = deck_width_along_bearing / 2.0
    shift_along = deck_cl_offset / cos_skew
    along_left = shift_along - half_brg - overhang_ft
    along_right = shift_along + half_brg + overhang_ft

    # perp_left_dir points to the LEFT of alignment along the skewed bearing
    # line, so we negate the right-positive along-bearing distances.
    return [
        (cx - along_left * math.cos(perp_left_dir),
         cy - along_left * math.sin(perp_left_dir)),
        (cx - along_right * math.cos(perp_left_dir),
         cy - along_right * math.sin(perp_left_dir)),
    ]


def deck_widths_by_support_id(compute_result) -> dict:
    """Build {support_id: max_along_bearing_length_ft} from a Phase1ComputeResult.

    Sample lines run ALONG the (skewed) bearing line, so their length is the
    along-bearing distance from left edge of deck to right edge of deck —
    `perpendicular_deck_width / cos(skew)` at that support. The compute
    result already exposes this as `bearing_line_length_start/end`.

    For Phase 1 single-span this is straightforward: a support is referenced
    as either the start or end of one span. For multi-span (Phase 2+) an
    intermediate pier is end of span N and start of span N+1; both bearing-
    line lengths should agree, but we take the max defensively.
    """
    widths = {}
    for span in compute_result.spans:
        for sid, w in (
            (span.start_support_id, span.bearing_line_length_start),
            (span.end_support_id, span.bearing_line_length_end),
        ):
            widths[sid] = max(widths.get(sid, 0.0), w)
    return widths


def deck_cl_offsets_by_support_id(params, compute_result) -> dict:
    """Build {support_id: deck_cl_offset_at_bearing_station_ft}.

    Sampled at each support's bearing station (matching how `bridge_lines`
    and the elevation chain evaluate the station-varying deck CL offset),
    so the sample line's asymmetric extension stays consistent with the
    edge-of-deck polylines created at the same support.
    """
    offsets = {}
    for span in compute_result.spans:
        for endpt in (span.girders[0].start, span.girders[0].end):
            offsets[endpt.support_id] = params.deck_cl_offset_from_alignment.at(
                endpt.bearing_station
            )
    return offsets
