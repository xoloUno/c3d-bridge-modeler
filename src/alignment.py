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
from Autodesk.AutoCAD.Geometry import Point2d  # noqa: E402

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

    Civil 3D's `Alignment.PointLocation(station, offset, out easting, out northing)`
    surfaces in pythonnet by returning the out parameters. The exact return
    shape varies by pythonnet version; the form below works on pythonnet 3.x
    where out parameters become a tuple alongside the void return.
    """
    easting, northing = alignment_obj.PointLocation(station, offset)
    return (easting, northing)


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
