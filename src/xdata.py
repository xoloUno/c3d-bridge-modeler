"""Xdata registration and serialization helpers. Civil-3D-only.

Phase 0 stores per-element identity as a JSON string under a single
RegApp (default: `BRIDGE_MODELER`). Querying with the `XDLIST` AutoCAD
command shows the JSON string verbatim.
"""
from __future__ import annotations

import json

import clr

clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.DatabaseServices import (  # noqa: E402
    DxfCode,
    OpenMode,
    RegAppTableRecord,
    ResultBuffer,
    TypedValue,
)


def ensure_regapp(tr, db, app_name: str):
    rat = tr.GetObject(db.RegAppTableId, OpenMode.ForRead)
    if rat.Has(app_name):
        return
    rat.UpgradeOpen()
    rec = RegAppTableRecord()
    rec.Name = app_name
    rat.Add(rec)
    tr.AddNewlyCreatedDBObject(rec, True)


def write(tr, object_id, app_name: str, data: dict):
    payload = json.dumps(data, separators=(",", ":"))
    rb = ResultBuffer()
    rb.Add(TypedValue(int(DxfCode.ExtendedDataRegAppName), app_name))
    rb.Add(TypedValue(int(DxfCode.ExtendedDataAsciiString), payload))
    ent = tr.GetObject(object_id, OpenMode.ForWrite)
    ent.XData = rb
