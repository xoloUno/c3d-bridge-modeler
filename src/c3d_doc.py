"""Civil 3D / AutoCAD active-document and transaction helpers.

Imports `clr` and Autodesk .NET assemblies. Will not import on a machine
without Civil 3D. Pure-logic code must not depend on this module.
"""
from __future__ import annotations

from contextlib import contextmanager

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


@contextmanager
def transaction():
    """Open a database transaction; dispose it on exit.

    Use:

        with c3d_doc.transaction() as tr:
            ...
            tr.Commit()

    Like `locked_document()`, this wraps the .NET IDisposable in a
    Python try/finally rather than relying on pythonnet's `with`
    integration, so an inner exception unwinds cleanly without
    pythonnet trying to map Python's `__exit__(exc_type, exc_val, tb)`
    onto `Transaction.OnExit(int)` — which masked our real errors for
    most of Phase 0 debugging.

    If `tr.Commit()` is not called, `Dispose()` aborts the transaction.
    """
    tr = active_db().TransactionManager.StartTransaction()
    try:
        yield tr
    finally:
        tr.Dispose()


@contextmanager
def locked_document():
    """Acquire a document write lock for the duration of the block.

    The active drawing must be locked for write before any
    `tr.GetObject(..., OpenMode.ForWrite)` call from a Dynamo Python
    node — without it AutoCAD raises `eLockViolation`.

    A bare `with doc.LockDocument():` would seem natural, but pythonnet
    3 mis-binds Python's `__exit__(exc_type, exc_val, tb)` to
    `DocumentLock.OnExit(int)`, whose signature mismatch raises a
    masking TypeError during exception unwinding (and may confuse the
    happy path on some pythonnet versions). Manage the lock with
    try/finally + explicit `Dispose()` instead.
    """
    lock = active_doc().LockDocument()
    try:
        yield lock
    finally:
        lock.Dispose()
