"""Civil 3D alignment / profile / surface query helpers.

Civil-3D-only. Will not import on macOS.

API surface used for Phase 0:
  - find_alignment(tr, name)
  - find_profile(tr, alignment, name)
  - find_surface(tr, name)
  - point_at_station(alignment, station, offset=0)  -> (x, y)
  - direction_at_station(alignment, station)        -> bearing in radians
  - elevation_at_station(profile, station)          -> z
  - surface_elevation_at(surface, x, y)             -> z
"""
from __future__ import annotations

import math

import clr

clr.AddReference("acdbmgd")
clr.AddReference("AeccDbMgd")

from Autodesk.AutoCAD.DatabaseServices import OpenMode  # noqa: E402

from c3d_doc import active_civil_doc  # noqa: E402


def find_alignment(tr, name: str):
    civ = active_civil_doc()
    for oid in civ.GetAlignmentIds():
        obj = tr.GetObject(oid, OpenMode.ForRead)
        if obj.Name == name:
            return obj
    raise ValueError(f"Alignment '{name}' not found in active drawing")


def find_profile(tr, alignment_obj, name: str):
    for oid in alignment_obj.GetProfileIds():
        prof = tr.GetObject(oid, OpenMode.ForRead)
        if prof.Name == name:
            return prof
    raise ValueError(
        f"Profile '{name}' not found on alignment '{alignment_obj.Name}'"
    )


def find_surface(tr, name: str):
    civ = active_civil_doc()
    for oid in civ.GetSurfaceIds():
        surf = tr.GetObject(oid, OpenMode.ForRead)
        if surf.Name == name:
            return surf
    raise ValueError(f"Surface '{name}' not found in active drawing")


def point_at_station(alignment_obj, station: float, offset: float = 0.0):
    """Return (easting, northing) on the alignment.

    Empirical pythonnet-3 behavior on Civil 3D 2024 Dynamo:

    - `clr.Reference[Double]()` does not exist in this pythonnet
      (the 2.x pattern was removed).
    - Calling `PointLocation(station, offset)` with only the two inputs
      raises `No method matches given arguments for PointLocation:
      (float, float)` — pythonnet here requires all 4 args.
    - Passing 4 args (with `0.0` placeholders for the easting/northing
      ref slots) succeeds, and pythonnet returns a 3-tuple
      `(None, easting, northing)` where the leading `None` is the void
      return slot.

    The defensive 2-or-3 unpack covers the observed 3-tuple shape and
    a hypothetical future 2-tuple shape (no leading void slot).
    """
    result = alignment_obj.PointLocation(station, offset, 0.0, 0.0)
    if isinstance(result, tuple):
        if len(result) == 3:
            return (result[1], result[2])
        if len(result) == 2:
            return result
    raise RuntimeError(
        f"Unexpected return from Alignment.PointLocation: "
        f"type={type(result).__name__}, value={result!r}"
    )


def direction_at_station(alignment_obj, station: float) -> float:
    """Return the alignment tangent bearing at `station` in radians.

    Math convention: 0 = +X, CCW positive. Computed numerically from two
    nearby station samples, which is robust across alignment entity types
    (lines, arcs, spirals) without depending on a specific Civil 3D API
    method whose name varies between releases.
    """
    eps = 0.5  # feet
    s0 = max(station - eps, alignment_obj.StartingStation)
    s1 = min(station + eps, alignment_obj.EndingStation)
    if s1 <= s0:
        s0, s1 = alignment_obj.StartingStation, alignment_obj.EndingStation
    x0, y0 = point_at_station(alignment_obj, s0, 0.0)
    x1, y1 = point_at_station(alignment_obj, s1, 0.0)
    return math.atan2(y1 - y0, x1 - x0)


def elevation_at_station(profile_obj, station: float) -> float:
    return profile_obj.ElevationAt(station)


def surface_elevation_at(surface_obj, x: float, y: float) -> float:
    return surface_obj.FindElevationAtXY(x, y)


# ---------------------------------------------------------------------
# alignment_entity_ranges — extract per-segment geometry types
# ---------------------------------------------------------------------

# Curvature magnitudes below this are treated as straight in the
# numerical fallback (≈ R > 2000 ft → essentially tangent for any
# bridge-scale geometry).
_CURVATURE_TANGENT_THRESHOLD = 0.0005  # 1/ft


def alignment_entity_ranges(alignment_obj, start_station, end_station):
    """Return alignment entity ranges within [start_station, end_station].

    The result is a list of tuples ``(entity_type, start_sta, end_sta,
    radius)`` ordered by station, where:
      - ``entity_type`` ∈ {"TANGENT", "SPIRAL", "ARC"}
      - ``radius`` is the signed arc radius for ARC entries (positive =
        center on left of travel direction, i.e. CCW curve), and ``None``
        for TANGENT/SPIRAL.
      - Sub-segments are clipped to the bridge extent.

    Primary path: walk ``alignment_obj.Entities`` and recurse into
    composite entities (SpiralCurveSpiral and the like) to extract leaf
    line/arc/spiral entities. This is the first use of ``Entities``
    via pythonnet-3 in this codebase, so it is wrapped in a broad
    try/except.

    Fallback: numerical curvature detection by sampling
    ``direction_at_station`` at 1 ft intervals. Curvature is the
    derivative of bearing with respect to station; near-zero curvature
    means tangent, non-zero means arc (with radius = 1/curvature). This
    fallback merges spirals into the surrounding region, which is fine
    for our scope (the polygon-derivation gating treats spirals as
    straight tapers identical to tangents).

    Returns
    -------
    list[tuple[str, float, float, Optional[float]]]
    """
    if end_station <= start_station:
        return []

    try:
        leaves = _entities_via_collection(alignment_obj)
        if not leaves:
            raise RuntimeError("alignment_obj.Entities yielded no leaves")
    except Exception as exc:  # noqa: BLE001 — defensive: any pythonnet failure
        print(
            f"[alignment] alignment_obj.Entities walk failed "
            f"({type(exc).__name__}: {exc}); falling back to curvature detection"
        )
        leaves = _entities_via_curvature(
            alignment_obj, start_station, end_station,
        )

    return _clip_and_sort(leaves, start_station, end_station)


def _entities_via_collection(alignment_obj):
    """Walk ``alignment_obj.Entities``, returning leaf entity tuples."""
    leaves = []
    for entity in _iter_dotnet_collection(alignment_obj.Entities):
        _walk_entity(entity, leaves)
    return leaves


def _iter_dotnet_collection(coll):
    """Iterate a .NET collection robustly under pythonnet-3.

    Tries Python iteration, then Count + indexer (via ``get_Item``),
    then ``GetEnumerator()``. Order matters: pythonnet-3 may surface
    different behaviors for different collection types.
    """
    try:
        return iter(coll)
    except TypeError:
        pass

    try:
        n = coll.Count
        return (coll.get_Item(i) for i in range(n))
    except Exception:  # noqa: BLE001
        pass

    enumerator = coll.GetEnumerator()

    def _gen():
        while enumerator.MoveNext():
            yield enumerator.Current

    return _gen()


def _entity_type_name(entity) -> str:
    """Return the bare enum-value name of ``entity.EntityType``.

    ``str(entity.EntityType)`` in pythonnet often returns the fully
    qualified name (``"Autodesk.Civil.DatabaseServices.AlignmentEntityType.Arc"``);
    take the last dotted segment for a stable comparison.
    """
    return str(entity.EntityType).split(".")[-1]


def _walk_entity(entity, leaves):
    """Recursively classify ``entity`` and append leaves to ``leaves``."""
    et = _entity_type_name(entity)

    # Composite entity check first: composites expose SubEntityCount > 1
    # and we should walk into them. Simple leaves have SubEntityCount of
    # 0 or 1 (some APIs report 1 for "self").
    sub_count = int(getattr(entity, "SubEntityCount", 0) or 0)
    is_composite = sub_count > 1 or any(
        token in et for token in ("LineLine", "ArcArc", "SpiralCurve",
                                  "SpiralLine", "SCS", "LineSpiral",
                                  "CurveCurve", "Compound")
    )

    if is_composite and sub_count > 0:
        for i in range(sub_count):
            try:
                sub = entity.SubEntityByIndex(i)
            except Exception:  # noqa: BLE001
                # Some entities expose GetSubEntityById or similar
                try:
                    sub = entity.GetSubEntityByIndex(i)
                except Exception:  # noqa: BLE001
                    continue
            _walk_entity(sub, leaves)
        return

    # Leaf classification by name fragment
    if et == "Arc" or et.endswith("Arc") and "ArcArc" not in et:
        _append_arc(entity, leaves)
        return

    if et == "Line" or (et.endswith("Line") and "LineLine" not in et):
        _append_tangent(entity, leaves)
        return

    if et == "Spiral" or (et.endswith("Spiral")
                          and "CurveSpiral" not in et
                          and "LineSpiral" not in et):
        _append_spiral(entity, leaves)
        return

    # Unknown leaf — treat as tangent so the build can still proceed.
    print(f"[alignment] unknown leaf entity type {et!r}; treating as TANGENT")
    _append_tangent(entity, leaves)


def _append_arc(entity, leaves):
    """Append an ARC tuple with signed radius (positive = CCW)."""
    try:
        radius_mag = float(entity.Radius)
    except Exception:  # noqa: BLE001
        radius_mag = 0.0
    try:
        clockwise = bool(entity.Clockwise)
    except Exception:  # noqa: BLE001
        # Fall back to numerically detecting direction from start/end tangents
        clockwise = False
    # Math convention: positive radius = center on left of travel direction
    radius_signed = -radius_mag if clockwise else radius_mag
    leaves.append((
        "ARC",
        float(entity.StartStation),
        float(entity.EndStation),
        radius_signed,
    ))


def _append_tangent(entity, leaves):
    leaves.append((
        "TANGENT",
        float(entity.StartStation),
        float(entity.EndStation),
        None,
    ))


def _append_spiral(entity, leaves):
    leaves.append((
        "SPIRAL",
        float(entity.StartStation),
        float(entity.EndStation),
        None,
    ))


def _entities_via_curvature(alignment_obj, start_station, end_station):
    """Numerical fallback when ``alignment_obj.Entities`` is unusable.

    Samples ``direction_at_station`` at ~1 ft intervals across the
    bridge extent, computes curvature, and groups consecutive samples
    into TANGENT / ARC segments. SPIRAL detection is omitted; spirals
    register as ARC segments with varying curvature, which the polygon
    derivation handles correctly (treated like an arc).
    """
    span_length = end_station - start_station
    n_samples = max(20, int(math.ceil(span_length / 1.0)))
    dt = span_length / n_samples

    # Per-interval curvature
    intervals = []  # list of (s0, s1, curvature)
    for i in range(n_samples):
        s0 = start_station + i * dt
        s1 = s0 + dt
        dir0 = direction_at_station(alignment_obj, s0)
        dir1 = direction_at_station(alignment_obj, s1)
        dtheta = dir1 - dir0
        # Normalize to (-π, π]
        while dtheta > math.pi:
            dtheta -= 2.0 * math.pi
        while dtheta <= -math.pi:
            dtheta += 2.0 * math.pi
        intervals.append((s0, s1, dtheta / dt))

    if not intervals:
        return [("TANGENT", start_station, end_station, None)]

    # Group consecutive intervals by curvature regime
    def _regime(c):
        return "ARC" if abs(c) > _CURVATURE_TANGENT_THRESHOLD else "TANGENT"

    segments = []
    cur_type = _regime(intervals[0][2])
    cur_start = intervals[0][0]
    cur_curvs = [intervals[0][2]]

    for s0, s1, c in intervals[1:]:
        new_type = _regime(c)
        if new_type != cur_type:
            avg_c = sum(cur_curvs) / len(cur_curvs)
            radius = (1.0 / avg_c) if cur_type == "ARC" and abs(avg_c) > 1e-12 else None
            segments.append((cur_type, cur_start, s0, radius))
            cur_start = s0
            cur_type = new_type
            cur_curvs = [c]
        else:
            cur_curvs.append(c)

    avg_c = sum(cur_curvs) / len(cur_curvs)
    radius = (1.0 / avg_c) if cur_type == "ARC" and abs(avg_c) > 1e-12 else None
    segments.append((cur_type, cur_start, end_station, radius))

    return segments


def _clip_and_sort(leaves, start_station, end_station):
    """Clip leaf entities to the bridge extent and sort by station."""
    clipped = []
    for et, s0, s1, radius in leaves:
        cs0 = max(s0, start_station)
        cs1 = min(s1, end_station)
        if cs1 <= cs0:
            continue
        clipped.append((et, cs0, cs1, radius))
    clipped.sort(key=lambda r: r[1])
    return clipped


def point_on_skewed_bearing(
    alignment_obj,
    station: float,
    skew_deg: float,
    perp_offset: float,
):
    """XY of the point at perpendicular offset `perp_offset` from alignment,
    *on the bearing line* skewed by `skew_deg` (CCW from perpendicular).

    For zero skew, equivalent to `point_at_station(alignment, station,
    perp_offset)`. For non-zero skew, the point shifts along the alignment
    direction by `perp_offset × tan(skew_deg)` so that the chord from the
    alignment crossing to the point lies on the skewed bearing line —
    matching the skewed sample line endpoint that downstream geometry
    (deck slab, abutment back of backwall, girder bearing points) lines up
    with.

    Sign convention matches Civil 3D's `PointLocation`: `+perp_offset` is
    right of alignment when looking ahead-station, `-perp_offset` is left.
    """
    if skew_deg == 0.0:
        return point_at_station(alignment_obj, station, perp_offset)

    cx, cy = point_at_station(alignment_obj, station, 0.0)
    alignment_dir_rad = direction_at_station(alignment_obj, station)
    skew_rad = math.radians(skew_deg)
    # `perp_left_dir` is the direction of the skewed bearing line going
    # toward the LEFT side of alignment (math convention: +Y when alignment
    # heads +X). For a point at C3D `+perp_offset` (right side), we go the
    # opposite distance along this direction; `L = -perp_offset / cos(skew)`
    # handles both signs correctly.
    perp_left_dir = alignment_dir_rad + math.pi / 2.0 + skew_rad
    L = -perp_offset / math.cos(skew_rad)
    return (
        cx + L * math.cos(perp_left_dir),
        cy + L * math.sin(perp_left_dir),
    )
