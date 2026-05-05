"""Civil 3D / AutoCAD active-document and transaction helpers.

Imports `clr` and Autodesk .NET assemblies. Will not import on a machine
without Civil 3D 2026+. Pure-logic code must not depend on this module.
"""
from __future__ import annotations

import clr

clr.AddReference("acdbmgd")
clr.AddReference("acmgd")
clr.AddReference("AcCoreMgd")
clr.AddReference("AeccDbMgd")

from Autodesk.AutoCAD.ApplicationServices import Application  # noqa: E402
from Autodesk.Civil.ApplicationServices import CivilApplication  # noqa: E402


def active_doc():
    return Application.DocumentManager.MdiActiveDocument


def active_db():
    return active_doc().Database


def active_civil_doc():
    return CivilApplication.ActiveDocument


def start_transaction():
    """Return a new Transaction. Use with `with`:

        with c3d_doc.start_transaction() as tr:
            ...
            tr.Commit()
    """
    return active_db().TransactionManager.StartTransaction()
