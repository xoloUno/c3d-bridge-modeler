"""AutoCAD layer and linetype helpers. Civil-3D-only."""
from __future__ import annotations

import clr

clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.Colors import Color, ColorMethod  # noqa: E402
from Autodesk.AutoCAD.DatabaseServices import (  # noqa: E402
    LayerTableRecord,
    OpenMode,
)


def ensure_layer(
    tr,
    db,
    name: str,
    color: int = 7,
    linetype: str = "Continuous",
    plottable: bool = True,
    locked: bool = False,
):
    """Idempotent: create the layer if missing, otherwise return the existing id.

    On the FIRST call that creates the layer, all attributes are set. On
    subsequent calls (layer already exists), only `plottable` and `locked`
    are reconciled if they differ from the requested values — color and
    linetype are left alone, since the user may have customized them.

    Uses `lt.get_Item(name)` rather than `lt[name]` because pythonnet 3
    (Civil 3D 2024 Dynamo) does not surface SymbolTable indexers as
    Python `__getitem__` — `lt[name]` raises `TypeError: unindexable
    object`. The C# `this[string]` indexer compiles to a `get_Item`
    method that pythonnet does expose by name.
    """
    lt = tr.GetObject(db.LayerTableId, OpenMode.ForRead)
    if lt.Has(name):
        existing_id = lt.get_Item(name)
        rec = tr.GetObject(existing_id, OpenMode.ForRead)
        # Only upgrade-and-write when something actually needs to change,
        # to avoid unnecessary write-locking on re-runs.
        needs_plot_change = bool(rec.IsPlottable) != bool(plottable)
        needs_lock_change = bool(rec.IsLocked) != bool(locked)
        if needs_plot_change or needs_lock_change:
            rec.UpgradeOpen()
            if needs_plot_change:
                rec.IsPlottable = plottable
            if needs_lock_change:
                rec.IsLocked = locked
        return existing_id

    if linetype != "Continuous":
        ensure_linetype(db, linetype)

    lt.UpgradeOpen()
    rec = LayerTableRecord()
    rec.Name = name
    rec.Color = Color.FromColorIndex(ColorMethod.ByAci, color)
    if linetype != "Continuous":
        ltt = tr.GetObject(db.LinetypeTableId, OpenMode.ForRead)
        rec.LinetypeObjectId = ltt.get_Item(linetype)
    rec.IsPlottable = plottable
    rec.IsLocked = locked
    oid = lt.Add(rec)
    tr.AddNewlyCreatedDBObject(rec, True)
    return oid


def ensure_linetype(db, name: str):
    """Load `name` from acad.lin if not already present in the linetype table."""
    db.LoadLineTypeFile(name, "acad.lin")
