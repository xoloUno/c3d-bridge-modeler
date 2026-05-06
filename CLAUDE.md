# CLAUDE.md

## Project Overview

One-Click Bridge Modeler — a Dynamo for Civil 3D tool that generates parametric 3D bridge models as AutoCAD solids from alignment, profile, surface, and tabular inputs.

## Detailed Scope

See `docs/scope.md` for the full project scope, parameter definitions, phased development plan, and technical implementation notes.

## Tech Stack

- **Platform:** Dynamo for Civil 3D 2024 (Dynamo Core 2.x)
- **Language:** CPython 3.x via PythonNet 3 inside Dynamo Python nodes
- **API:** Civil 3D .NET API accessed through Python for .NET (`clr` / `pythonnet`)
- **Output:** AutoCAD `Solid3d` objects on named `BRIDGE-*` layers with xdata metadata
- **Parameter format:** JSON files (one per bridge)

### PythonNet 3 quirks worth knowing (verified empirically in C3D 2024 Dynamo)

- `clr.Reference[T]()` (the pythonnet-2.x pattern for `ref`/`out` parameters) does **not** exist. For .NET methods with `ref`/`out` doubles, pass `0.0` placeholders for those slots; pythonnet returns the modified values as part of a tuple alongside the void/return slot — see `src/alignment.py:point_at_station` for the canonical handling.
- C# indexers (`SymbolTable.this[string]`) do **not** surface as Python `__getitem__`. Use the underlying `get_Item(name)` method instead — `lt[name]` raises `TypeError: unindexable object`. For `BlockTable` specifically, `SymbolUtilityServices.GetBlockModelSpaceId(db)` skips the indexing entirely.
- `with doc.LockDocument():` and `with tr:` (raw `Transaction`) misroute Python's `__exit__(exc_type, exc_val, tb)` to .NET's `OnExit(int)` during exception unwinding, raising a masking `TypeError`. Wrap IDisposable lifetimes in `@contextmanager` helpers that explicitly call `Dispose()` in a `finally` block — see `src/c3d_doc.py` (`locked_document`, `transaction`).
- A document write lock IS required around any `OpenMode.ForWrite` `tr.GetObject()` call from a Python node; without it AutoCAD raises `eLockViolation`. The lock acquired around an unrelated edit can leak in and let a script "succeed" on a warm drawing — always lock explicitly.

## Key Architecture Decisions

- AutoCAD 3D solids, not "smart" Civil 3D objects (Civil 3D has no native bridge API class)
- ~20 unnumbered component-level layers (e.g., `BRIDGE-GIRDER`, `BRIDGE-PIER-COL`); per-element identity stored as xdata
- Below-grade elements split at EG surface elevation: above-grade on standard layer, below-grade on `-BELOW` layer with DASHED linetype
- Footings are exclusively below grade and do not need splitting
- Re-run behavior: delete all `BRIDGE-*` layer objects, regenerate from parameters

## File Structure

```
docs/scope.md          Full project scope and development plan
src/                   Dynamo graphs (.dyn) and Python scripts (.py)
data/                  AISC shape tables, parameter templates
test/                  Test parameter files and expected outputs
```

## Development Notes

- Target Dynamo Player compatibility so non-Dynamo users can run the tool
- Python scripts should use `clr.AddReference` for Civil 3D and AutoCAD .NET assemblies
- All geometry is generated in Civil 3D world coordinates by querying alignments for station/offset/elevation
- AISC W-shape dimensions stored as embedded JSON lookup table
- Parameter input via JSON files loaded by Python nodes

## Current Phase

Phase 0: Foundation & Proof of Concept — prove the core pipeline works (read alignment via data shortcuts, generate simple solids, verify xref and Hidden visual style display in viewports).
