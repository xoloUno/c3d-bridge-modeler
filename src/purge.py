"""Re-run contract: delete every ModelSpace entity on a `BRIDGE-*` layer.

Civil-3D-only. Implements the policy in scope.md:419-426 — re-running the
graph wipes prior bridge geometry before regenerating.
"""
from __future__ import annotations

import clr

clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.DatabaseServices import (  # noqa: E402
    BlockTable,
    BlockTableRecord,
    OpenMode,
)


_PREFIX = "BRIDGE-"


def purge_bridge_objects(tr, db) -> int:
    """Erase all ModelSpace entities whose layer starts with `BRIDGE-`.
    Returns the count erased.
    """
    bt = tr.GetObject(db.BlockTableId, OpenMode.ForRead)
    btr = tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForWrite)
    count = 0
    for oid in btr:
        ent = tr.GetObject(oid, OpenMode.ForRead)
        layer = getattr(ent, "Layer", None)
        if layer and layer.startswith(_PREFIX):
            ent.UpgradeOpen()
            ent.Erase()
            count += 1
    return count
