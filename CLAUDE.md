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

**Phase 2: Curved Horizontal Alignment** — extend the Phase 1 superstructure to work on curved (arc / spiral) horizontal alignments. See `docs/phase2-scope.md` for the detailed scope. Super-elevation and curved girders are deferred to Phase 3; girders remain straight chords between bearings.

### Done (Phase 1, pure-math + skeleton)
- AISC W-shape lookup table (`data/aisc_w_shapes.json`, 266 W10–W44 shapes; sourced from steelpy, Apache-2.0; spot-check task in `MANUAL-TASKS.md`)
- Pure-math elevation chain (`src/elevation.py`) — top of deck → girder flange → bottom of girder → bearing seat → top of cap → top of column → top of footing
- Phase 1 params schema (`src/phase1_params.py`) — global, supports, spans, superstructures, with exactly-one-of edge-spacing rule and station-varying `crown_offset` / `deck_cl_offset_from_alignment` profiles
- End-to-end compute orchestrator (`src/phase1_compute.py`) — skew correction, deck-CL offset shift, per-girder per-bearing-line elevations, formatted text report
- Sample-line skeleton at supports (`src/skeleton.py`) — `BRIDGE-SUPPORTS` group, idempotent across runs
- Edge-of-deck + bridge-CL reference polylines (`src/bridge_lines.py`) — `BRIDGE-NOPLOT` layer (locked + non-plotting), skewed bearing endpoint geometry, anchored at support stations
- Pure-math I-shape profile builder (`src/girder_geometry.py`) — closed 12-vertex AISC W-shape outline in profile-local feet
- Girder swept solids (`src/girders.py`) — I-shape `Region` pre-oriented in a vertical plane perpendicular to the in-plan girder direction (web plumb), swept along a 3D `Line` from start to end bearing via `Solid3d.CreateSweptSolid` with `Align=NoAlignment` + `Bank=False`. `BRIDGE-GIRDER` layer (red), xdata `{element, span_id, girder_index, girder_shape, id}`. Re-run regenerates (purges every `BRIDGE-GIRDER` entity first); skeleton on other layers untouched. Verified 2026-05-18 on `D-E` alignment with 10° / -10° skew, 4 × W36X150 girders, depth-measured 2.9917 ft against AISC 35.9 in. Profile elevation sampled at each girder's actual world station (`bearing_station + perp_offset × tan(skew)`) so girder-to-girder slope in alignment-perpendicular sections equals design cross-slope exactly (verified 2.0% on 2026-05-19, commit 242082f).
- Pure-math haunch profile builder (`src/haunch_geometry.py`) — closed 4-vertex trapezoid; kept for reference but the rectangular-box approach below doesn't use it
- Pure-math deck cross-section vertex builder (`src/deck_geometry.py`) — 4-vertex parallelogram (super-elevated / non-crown-straddling) or 6-vertex hex (crown-straddling with same-sign cross-slopes); crown-kink detection helper
- Phase 1 compute extended with per-bearing-line `DeckCrossSection` (top vertex list + bearing station + skew + deck_depth) and per-girder `haunch_h_left_ft` / `haunch_h_right_ft` (kept on `GirderAtBearing` for the elevation report; the haunch solid construction no longer needs them after the boolean-trim refactor)
- Deck slab (`src/decks.py`) via sweep + boolean intersect — alignment-perpendicular fat cross-section swept along the alignment 3D path (`Align=NoAlignment`, `Bank=False`, profile-Z-aware path sampling), then intersected with a vertical extrusion of the 4-corner deck plan polygon. Layer `BRIDGE-DECK` (color 7), xdata `{element, span_id, id}`. This approach preserves design cross-slope exactly (no loft twist artifact); the skewed plan footprint is preserved by the trim. Verified 2026-05-19 on `D-E` alignment under ±10° asymmetric skew with fanning width 22→25 ft — 2.0% cross-slope read at both ends, slabs flush with deck-edge polylines. `decks.build_fat_deck_cutter` is exported for reuse by `haunches`.
- Haunch solids (`src/haunches.py`) via rectangular box + boolean subtract — `bf × (haunch_depth + 0.5·deck_depth)` rectangular swept prism along the girder path, then boolean-subtract a `build_fat_deck_cutter` deck volume from it. The haunch top coincides with the deck soffit by construction; layer `BRIDGE-DECK-HAUNCH` (color 51), xdata `{element, span_id, girder_index, id}`. This replaces the earlier trapezoidal-sweep approach which had a ~0.09% slope artifact in alignment-perpendicular sections from oblique-cut effects on fanning girders; the new approach drops that to ~0.008% (just the projection of `bf` onto alignment-perpendicular under the fan angle, geometrically unavoidable without breaking girder-flange alignment). Verified 2026-05-19 on Windows (v25, commit 97f6c9e) — haunch tops coincide with deck soffit exactly.
- 162 macOS unit tests covering the pure-logic layer
- C3D-side build orchestrator (`src/phase1_build.py`) and Dynamo node body (`src/phase1_node.py`) verified end-to-end on a real `D-E` alignment with ±10° asymmetric skew, fanning deck width (22→25 ft), -5% longitudinal grade, and `bearing_offsets: [1.5]` / `[-1.5]`. After the F2 fix (PR #14, commit `d368f4d`), deck slab plan corners coincide with the `BRIDGE-NOPLOT` edge polyline endpoints exactly — verified 2026-05-19 on Windows. Phase 1 superstructure (skeleton + girders + haunches + deck) is functional and dimensionally correct.
- Bridge-line schema self-heal (PR #15, commit `7c65501`) — `BRIDGE-EDGE-L/R/BRIDGE-CL` polylines carry a `schema_version` stamp in xdata. When the polyline-generation algorithm changes, bump `_SCHEMA_VERSION` in `src/bridge_lines.py`; the next run erases unstamped/mismatched polylines (force-opening through the layer lock) and regenerates them. Designer edits within the same schema_version stay preserved.

### Done (Phase 2, curved horizontal alignment)
- Curved deck sweep (`src/decks.py`) — two changes: (1) density-driven path sampling (~1 sample/ft, min 21, via `_path_sample_count()`) so the `Polyline3d` sweep path closely approximates curved alignments; (2) trim polygon generalized from 4-corner to many-vertex (`_deck_plan_polygon_xy`) where left/right deck edges are sampled along the alignment curve at perpendicular offset (~1 pt per 5 ft), connected by straight bearing-line segments at supports. For straight alignments this degenerates to the Phase 1 behaviour (collinear intermediate points). Sweep option stays `NoAlignment` — `AlignSweepEntityToPath` was tried but it repositions the cross-section (shifts the fat deck), causing a regression on straight bridges. With `NoAlignment` the `Polyline3d` path still bends with the curve; the cross-slope orientation error is bounded at `slope × (1 − cos θ)` and negligible for typical geometries. `build_fat_deck_cutter` (used by `haunches.py`) inherits these changes automatically.
- Arc-segment edge polylines (`src/bridge_lines.py`) — intermediate vertices at ~10 ft spacing with arc bulges computed from alignment-curve midpoint sampling (sagitta / half-chord = `tan(θ/4)`). Each polyline segment is a true arc that matches the alignment curvature at perpendicular offset, so `DIMRADIUS` reports the correct edge radius. On straight alignments all midpoints are collinear → bulge = 0 → straight segments. Schema version `v6-arc-edge`; stale polylines self-heal on first post-update run.
- Girders (`src/girders.py`) — **unchanged**; girders remain straight chords between bearings per Phase 2 scope. Curved/chorded girders are Phase 3.
- Haunches (`src/haunches.py`) — **unchanged**; the deck cutter now follows the curve automatically.
- Pure-math layer — **unchanged**; all 162 macOS tests still pass.
- Windows verification (2026-05-20): curved-alignment test bridge built successfully (D-E alignment, 4 × W36X150, 47 ft span). Straight-alignment regression clean — deck edges coincide with `BRIDGE-NOPLOT` polylines. See `MANUAL-TASKS.md` "Phase 2 curved horizontal alignment" for remaining visual checks.

### Known deferrals (gated at params parse time)
- **`follow_superelevation: true`** — alignment-superelevation tracking is not implemented; setting `true` raises `Phase1ParamsError` rather than silently rendering a non-superelevated deck.
- **Station-varying `crown_offset` / `deck_cl_offset_from_alignment`** — deck solid construction is a constant-section sweep, so multi-point profiles (or two endpoints with differing values) raise `Phase1ParamsError`. Reference polylines support the variation, but the slab geometry doesn't yet — lifting this is on the Phase 2 deck-sweep work.
- **`template_dwg`** — the path is parsed and validated but no template-loader runs yet. Layers and xdata are created ad-hoc; IFC PropertySets aren't written. See MANUAL-TASKS.md "Bridge template DWG".
- **Per-layer purge** (`BRIDGE-GIRDER`, `BRIDGE-DECK`, `BRIDGE-DECK-HAUNCH`) erases every entity on the layer, not just xdata-tagged tool output. Acceptable for single-bridge drawings; multi-bridge support needs xdata-filtered, bridge-id-scoped purging.

### Next up
Phase 3 candidates (see `docs/phase2-scope.md` § "Other Phase 2 candidates" for details):
- **Super-elevation** (station-varying cross-slope) — requires loft through multiple cross-sections instead of constant-section sweep.
- **Curved/chorded girders** — for tight curves, real girders are curved (rolled arcs) or chorded (straight segments with field splices).
- **Substructure** — pier caps, columns, abutments, footings. Layers listed in `templates/README.md`. Cap-to-girder tie-in via bearing-seat elevations already computed.
- **Multi-span** — multiple `Span` entries linking shared piers; schema and compute orchestrator already support the loop.
- **Plate girders** — custom-width built-up sections vs. AISC rolled W-shapes.

### Phase 0 (complete, 2026-05-06)
Foundation & proof-of-concept verified — see `MANUAL-TASKS.md` for the verification record. The Phase 0 pipeline (JSON params → 3 `Solid3d` boxes on `BRIDGE-*` layers with xdata) is the baseline Phase 1 builds on.
