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


class SkeletonError(RuntimeError):
    pass


def ensure_support_sample_lines(
    tr,
    alignment_obj,
    supports,
    deck_widths_by_support_id: dict,
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
        if support.support_id in existing_names:
            preserved.append((support.support_id, existing_names[support.support_id]))
            continue

        deck_width = deck_widths_by_support_id.get(support.support_id)
        if deck_width is None:
            raise SkeletonError(
                f"deck width for support {support.support_id!r} not provided"
            )
        half_length = deck_width / 2.0 + overhang_ft

        endpoints = _skewed_endpoints(
            alignment_obj=alignment_obj,
            station=support.station,
            skew_deg=support.skew_angle,
            half_length=half_length,
        )
        points = Point2dCollection()
        for x, y in endpoints:
            points.Add(Point2d(x, y))

        sl_id = SampleLine.Create(support.support_id, group_id, points)
        created.append((support.support_id, sl_id))

    return {"group_id": group_id, "created": created, "preserved": preserved}


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
    half_length: float,
) -> List[tuple]:
    """Return [(x_left, y_left), (x_right, y_right)] for a sample line.

    Skew sign convention: 0 deg = perpendicular to alignment. Positive skew
    rotates the sample line CCW (as seen from above) from the perpendicular,
    so a +30 deg skewed sample line tips its left end ahead-station.
    """
    cx, cy = al.point_at_station(alignment_obj, station, 0.0)
    alignment_dir_rad = al.direction_at_station(alignment_obj, station)
    skew_rad = math.radians(skew_deg)
    perp_left_dir = alignment_dir_rad + math.pi / 2.0 + skew_rad

    dx = half_length * math.cos(perp_left_dir)
    dy = half_length * math.sin(perp_left_dir)
    left = (cx + dx, cy + dy)
    right = (cx - dx, cy - dy)
    return [left, right]


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
