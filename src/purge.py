"""Re-run contract: delete every ModelSpace entity on a `BRIDGE-*` layer.

Civil-3D-only. Implements the policy in scope.md:419-426 — re-running the
graph wipes prior bridge geometry before regenerating.
"""
from __future__ import annotations

import clr

clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.DatabaseServices import (  # noqa: E402
    OpenMode,
    SymbolUtilityServices,
)


_PREFIX = "BRIDGE-"


def purge_bridge_objects(tr, db) -> int:
    """Erase all ModelSpace entities whose layer starts with `BRIDGE-`.
    Returns the count erased.

    Uses `SymbolUtilityServices.GetBlockModelSpaceId(db)` rather than
    indexing the BlockTable, because pythonnet on this Civil 3D / Dynamo
    runtime does not surface the C# `BlockTable.this[string]` indexer as
    Python `__getitem__` — `bt[BlockTableRecord.ModelSpace]` raises
    `TypeError: unindexable object`.
    """
    ms_id = SymbolUtilityServices.GetBlockModelSpaceId(db)
    btr = tr.GetObject(ms_id, OpenMode.ForWrite)
    count = 0
    for oid in btr:
        ent = tr.GetObject(oid, OpenMode.ForRead)
        layer = getattr(ent, "Layer", None)
        if layer and layer.startswith(_PREFIX):
            ent.UpgradeOpen()
            ent.Erase()
            count += 1
    return count
