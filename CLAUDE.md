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
- pythonnet 3 does **not** reliably disambiguate same-arity .NET method overloads when one accepts `ObjectId` and another accepts `string` for the same positional slot. Empirically observed with `Alignment.Create(CivilDocument, PolylineOptions, string, …)`: passing real `ObjectId` values still dispatched to the all-strings overload, which then failed C3D's name-based label-set lookup. Pin the desired overload explicitly via `Method.Overloads[T1, T2, …]`. Example for the ObjectId-typed `Alignment.Create`:
  ```python
  from System import String
  from Autodesk.AutoCAD.DatabaseServices import ObjectId
  from Autodesk.Civil.ApplicationServices import CivilDocument
  from Autodesk.Civil.DatabaseServices import Alignment, PolylineOptions

  create_objid = Alignment.Create.Overloads[
      CivilDocument, PolylineOptions, String,
      ObjectId, ObjectId, ObjectId, ObjectId,
  ]
  alignment_id = create_objid(civ_doc, options, name,
                              ObjectId.Null, layer_id, style_id, label_set_id)
  ```
  This is the canonical handling for any same-arity ObjectId-vs-string overload pair.

## Key Architecture Decisions

- AutoCAD 3D solids, not "smart" Civil 3D objects (Civil 3D has no native bridge API class)
- ~20 unnumbered component-level layers (e.g., `BRIDGE-GIRDER`, `BRIDGE-PIER-COL`); per-element identity stored as xdata
- Below-grade elements split at EG surface elevation: above-grade on standard layer, below-grade on `-BELOW` layer with DASHED linetype
- Footings are exclusively below grade and do not need splitting
- Re-run behavior (two-mode workflow): **skeleton elements** (sample lines, edge/CL reference polylines, future top-of-deck surfaces) are **preserved** across runs — designers can move/edit them and the tool reads positions back. **Solid geometry** (deck, girders, haunches, substructure) is **regenerated each run** from current params + skeleton positions. Idempotency uses xdata tags or sample-line group / alignment names for find-or-create.

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

**Phase 1: Single-Span Straight Bridge** — model a complete single-span steel girder bridge on a straight alignment. See `scope.md` Phase 1 section for the full deliverables list.

### Done (Phase 1, pure-math + skeleton)
- AISC W-shape lookup table (`data/aisc_w_shapes.json`, 266 W10–W44 shapes; sourced from steelpy, Apache-2.0; spot-check task in `MANUAL-TASKS.md`)
- Pure-math elevation chain (`src/elevation.py`) — top of deck → girder flange → bottom of girder → bearing seat → top of cap → top of column → top of footing
- Phase 1 params schema (`src/phase1_params.py`) — global, supports, spans, superstructures, with exactly-one-of edge-spacing rule and station-varying `crown_offset` / `deck_cl_offset_from_alignment` profiles
- End-to-end compute orchestrator (`src/phase1_compute.py`) — skew correction, deck-CL offset shift, per-girder per-bearing-line elevations, formatted text report
- Sample-line skeleton at supports (`src/skeleton.py`) — `BRIDGE-SUPPORTS` group, idempotent across runs
- Edge-of-deck + bridge-CL reference polylines (`src/bridge_lines.py`) — `BRIDGE-NOPLOT` layer (locked + non-plotting), skewed bearing endpoint geometry, anchored at support stations
- Pure-math I-shape profile builder (`src/girder_geometry.py`) — closed 12-vertex AISC W-shape outline in profile-local feet
- 117 macOS unit tests covering the pure-logic layer
- C3D-side build orchestrator (`src/phase1_build.py`) and Dynamo node body (`src/phase1_node.py`) verified end-to-end on a real `D-E` alignment with 10° skew

### Code written, awaiting C3D verification
**Girder swept solids** (`src/girders.py`). I-shape `Region` from AISC dims via `girder_geometry.i_shape_profile_vertices_ft`, profile pre-oriented in a vertical plane perpendicular to the in-plan girder direction (web plumb), swept along a 3D `Line` path from `(start_x, start_y, top_of_flange_z)` to `(end_x, end_y, top_of_flange_z)` via `Solid3d.CreateSweptSolid` with `Align=NoAlignment` + `Bank=False` so the cross-section orientation is preserved through graded paths. `BRIDGE-GIRDER` layer (red), xdata `{element, span_id, girder_index, girder_shape, id}`. Re-run regenerates solids (purges every `BRIDGE-GIRDER` entity first); skeleton elements on other layers are untouched.

Wired into `phase1_build.py` after `bridge_lines.ensure_phase1_bridge_lines`. Needs the Civil-3D-side verification documented in `MANUAL-TASKS.md` ("Phase 1 girder solids").

### Next up
Haunches (parallelogram cross-section sitting on top flange), then deck solid lofted between cross-section profiles at the bearing lines.

### Phase 0 (complete, 2026-05-06)
Foundation & proof-of-concept verified — see `MANUAL-TASKS.md` for the verification record. The Phase 0 pipeline (JSON params → 3 `Solid3d` boxes on `BRIDGE-*` layers with xdata) is the baseline Phase 1 builds on.
