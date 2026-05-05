"""AutoCAD `Solid3d` creation helpers. Civil-3D-only.

Phase 0 only needs axis-aligned boxes that are then rotated about Z and
translated to bridge coordinates.
"""
from __future__ import annotations

import clr

clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.DatabaseServices import (  # noqa: E402
    BlockTable,
    BlockTableRecord,
    OpenMode,
    Solid3d,
)
from Autodesk.AutoCAD.Geometry import Matrix3d, Point3d, Vector3d  # noqa: E402


def create_box(center, length: float, width: float, height: float, rotation_z_rad: float = 0.0):
    """Create an unappended `Solid3d` box.

    The box starts axis-aligned at the origin, then is rotated about Z by
    `rotation_z_rad` (CCW from +X) and translated so its centroid sits at
    `center` (a 3-tuple of world coordinates).
    """
    cx, cy, cz = center
    s = Solid3d()
    s.CreateBox(length, width, height)
    s.TransformBy(Matrix3d.Rotation(rotation_z_rad, Vector3d.ZAxis, Point3d(0, 0, 0)))
    s.TransformBy(Matrix3d.Displacement(Vector3d(cx, cy, cz)))
    return s


def append_to_modelspace(tr, db, entity, layer_name: str):
    bt = tr.GetObject(db.BlockTableId, OpenMode.ForRead)
    btr = tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForWrite)
    entity.Layer = layer_name
    oid = btr.AppendEntity(entity)
    tr.AddNewlyCreatedDBObject(entity, True)
    return oid
