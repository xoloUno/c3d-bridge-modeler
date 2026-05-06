"""AutoCAD layer and linetype helpers. Civil-3D-only."""
from __future__ import annotations

import clr

clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.Colors import Color, ColorMethod  # noqa: E402
from Autodesk.AutoCAD.DatabaseServices import (  # noqa: E402
    LayerTableRecord,
    OpenMode,
)


def ensure_layer(tr, db, name: str, color: int = 7, linetype: str = "Continuous"):
    """Idempotent: create the layer if missing, otherwise return existing id.

    Uses `lt.get_Item(name)` rather than `lt[name]` because pythonnet 3
    (Civil 3D 2024 Dynamo) does not surface SymbolTable indexers as
    Python `__getitem__` — `lt[name]` raises `TypeError: unindexable
    object`. The C# `this[string]` indexer compiles to a `get_Item`
    method that pythonnet does expose by name.
    """
    lt = tr.GetObject(db.LayerTableId, OpenMode.ForRead)
    if lt.Has(name):
        return lt.get_Item(name)

    if linetype != "Continuous":
        ensure_linetype(db, linetype)

    lt.UpgradeOpen()
    rec = LayerTableRecord()
    rec.Name = name
    rec.Color = Color.FromColorIndex(ColorMethod.ByAci, color)
    if linetype != "Continuous":
        ltt = tr.GetObject(db.LinetypeTableId, OpenMode.ForRead)
        rec.LinetypeObjectId = ltt.get_Item(linetype)
    oid = lt.Add(rec)
    tr.AddNewlyCreatedDBObject(rec, True)
    return oid


def ensure_linetype(db, name: str):
    """Load `name` from acad.lin if not already present in the linetype table."""
    db.LoadLineTypeFile(name, "acad.lin")
