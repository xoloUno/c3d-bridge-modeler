# Bridge Modeler for Civil 3D

Civil 3D doesn't have a bridge modeler. Bentley has OpenBridge Modeler; this is the Autodesk-side equivalent. Feed it alignment, profile, and bridge parameters; it generates 3D AutoCAD solids with an editable skeleton that designers can grip-edit between runs.

Dynamo graph + CPython 3 scripts calling the Civil 3D .NET API through PythonNet 3.

## Current State

**Phase 2 complete** (2026-05-20). Generates a steel girder superstructure -- girders, haunches, deck slab -- as AutoCAD `Solid3d` objects with xdata tags. Tested on a Civil 3D alignment with asymmetric skew, curved geometry, fanning width, longitudinal grade, and shifting deck CL.

Next: super-elevation, substructure (piers/abutments/footings), multi-span, curved/chorded girders. See [CLAUDE.md](CLAUDE.md) for the phase log.

## Problem

Without this, the workflow bounces through InfraWorks, Inventor, and back to Civil 3D. The resulting models have to be exploded into 2D linework for drawing production, breaking the link between 3D model and 2D deliverables.

## How It Works

Write a JSON file describing your bridge -- girder type, spacing, supports, skew angles, deck dimensions. Open a Civil 3D drawing with alignment data shortcuts and run the Dynamo graph. It reads the JSON, queries the alignment/profile for geometry, and places 3D solids in the drawing.

Two kinds of output:

- **Skeleton** (sample lines at supports, deck plan polygon) -- preserved across runs. Designers can grip-edit these; the tool reads positions back on the next run.
- **Solids** (girders, haunches, deck) -- purged and regenerated from current params + the live skeleton each run.

[docs/architecture.md](docs/architecture.md) walks through the pipeline, module dependencies, and geometry construction.

## What It Generates

| Element | Technique | Layer |
|---|---|---|
| Girders | Swept I-shape (AISC W-shapes) along 3D path, web plumb | `BRIDGE-GIRDER` |
| Deck slab | Constant-section sweep + boolean intersect with polygon trim | `BRIDGE-DECK` |
| Haunches | Rectangular box sweep - boolean subtract deck cutter | `BRIDGE-DECK-HAUNCH` |
| Deck plan polygon | Closed polyline with arc bulges, designer-editable | `BRIDGE-2D-DECK` |
| Sample lines | Civil 3D sample lines at supports + bearing offsets | `BRIDGE-SUPPORTS` group |

## Requirements

- Autodesk Civil 3D 2024+
- Dynamo for Civil 3D (ships with Civil 3D)
- Python node set to **CPython 3** (PythonNet 3 runtime)

## Repository Layout

```
src/                   Dynamo graph (.dyn) + Python scripts (.py)
data/                  AISC W-shape lookup table (266 shapes, W10-W44)
test/                  Unit tests (201, runnable on macOS) + example params
docs/                  Architecture guide, phase scopes
scope.md               Full project scope and development plan
templates/             Template drawing documentation
```

## Testing

Pure-math modules (no Civil 3D dependency, runnable on macOS) have unit tests:

```
cd test && python -m pytest       # 201 tests, ~2 seconds
```

Covers elevation chain, parameter validation, AISC lookup, skew correction, cross-section geometry, deck plan polygon derivation (all 5 gating cases), station-varying interpolation.

C3D-side modules are tested by running the Dynamo graph on Windows. See [MANUAL-TASKS.md](MANUAL-TASKS.md).

## Documentation

- **[docs/architecture.md](docs/architecture.md)** -- pipeline, diagrams, geometry construction
- **[scope.md](scope.md)** -- project scope, parameter definitions, development plan
- **[CLAUDE.md](CLAUDE.md)** -- development log, phase records, PythonNet 3 quirks

## License

[MIT](LICENSE)
