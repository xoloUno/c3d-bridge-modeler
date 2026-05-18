# Bridge Modeler Architecture

How the Phase 1 pipeline works, end to end.

## The Big Idea

You write a JSON file describing your bridge (girder type, spacing, supports, skew angles, etc.). You open a Civil 3D drawing with alignment data shortcuts attached. You run a Dynamo graph. The tool reads the JSON, queries the alignment/profile for positions and elevations, computes everything about the bridge geometry, and creates AutoCAD objects in the drawing.

## Two-Mode Workflow

The tool creates two categories of objects with different re-run behavior:

```
+-----------------------------------------------------+
|  SKELETON (preserved across runs)                    |
|  - Sample lines at supports                          |
|  - Edge-of-deck polylines                            |
|  - Bridge-CL polyline (if deck CL != alignment)     |
|                                                      |
|  Designer can move these between runs.               |
|  Tool reads positions back on next run.              |
|  Idempotent: find-by-name, create only if absent.    |
+------------------------------------------------------+
|  SOLIDS (regenerated each run)                       |
|  - Girders, haunches, deck (future)                  |
|  - Piers, abutments, footings (Phase 1b)             |
|                                                      |
|  Purged and rebuilt from current params + skeleton.   |
|  No user edits expected on these.                    |
+------------------------------------------------------+
```

Defined in `CLAUDE.md` under "Key Architecture Decisions" and detailed in `scope.md`.

## The Pipeline, Step by Step

What happens when you hit Run in Dynamo:

```
                          +----------------+
                          |  Dynamo Graph  |
                          |  phase1_       |
                          |  bridge.dyn    |
                          +-------+--------+
                                  |
                     IN[0]=repo_root  IN[1]=params_path
                                  |
                     +------------v--------------+
                     |   phase1_node.py          |
               (1)   |   (Dynamo Python node)    |
                     |   Purges stale modules,   |
                     |   calls phase1_build      |
                     +------------+--------------+
                                  |
                     +------------v--------------+
                     |   phase1_build.py         |
               (2)   |   (orchestrator)          |
                     |   Ties everything         |
                     |   together inside a       |
                     |   doc lock + transaction  |
                     +------------+--------------+
                                  |
            +---------+-----------+-----------+----------+
            v         v           v           v          v
       +---------+ +--------+ +--------+ +--------+ +--------+
  (3)  | params  | | AISC   | | C3D    | |compute | |skeleton|
       | load +  | | table  | | align- | |(pure   | |+ bridge|
       |validate | | load   | | ment + | | math)  | | lines  |
       |         | |        | |profile | |        | |        |
       +---------+ +--------+ +--------+ +--------+ +--------+
```

### (1) The Dynamo Node -- `src/phase1_node.py`

The code you paste into the Dynamo Python Script node. Three jobs:

1. **Cleans the Python path** (lines 41-43) -- strips stale repo paths from `sys.path` so you can't accidentally run old code from a different clone.
2. **Purges cached modules** (lines 47-64) -- Dynamo caches Python modules across runs; this forces fresh imports every time.
3. **Calls the orchestrator** (line 67) -- `phase1_build.main(repo_root, params_path)`.

The **reload trigger** on line 29 (`print("[phase1_node] reload trigger v14")`) is a hack around Dynamo's caching -- Dynamo only re-executes a Python node if the node body text changed, so bumping `v14` to `v15` after a `git pull` forces a re-run.

### (2) The Orchestrator -- `src/phase1_build.py`

The conductor. Everything happens inside a document lock + transaction (lines 77-123):

```python
with c3d_doc.locked_document():          # required or AutoCAD throws eLockViolation
    with c3d_doc.transaction() as tr:     # if tr.Commit() isn't called, everything aborts
        # ... all work happens here ...
        tr.Commit()                       # line 123
```

Why `locked_document()` instead of `with doc.LockDocument()`? Because pythonnet 3 mis-routes Python's `__exit__` to .NET's `OnExit(int)` during exception unwinding. Documented in `src/c3d_doc.py` lines 59-78.

Inside the transaction, the sequence is:

1. **Load params** -- `phase1_params.load()` (line 66)
2. **Load AISC table** -- `aisc.load()` (line 69)
3. **Validate** girder shapes exist in the AISC table (lines 71-73)
4. **Find alignment + profile** in the drawing (lines 80-82)
5. **Run compute** -- `phase1_compute.compute()` (line 88) -- pure math, produces structured elevation data
6. **Create skeleton** -- sample lines (lines 91-99) + bridge polylines (lines 108-114)
7. **Commit** the transaction (line 123)
8. **Format text report** for the Watch node (line 125)

### (3) The Building Blocks

Each module has a clear responsibility. Dependency graph:

```
  phase1_node.py
       |
       v
  phase1_build.py  (C3D orchestrator)
       |
       +-- phase1_params.py  <-- station_profile.py
       |        (pure math)          (pure math)
       |
       +-- aisc.py  <-- data/aisc_w_shapes.json
       |   (pure math)
       |
       +-- phase1_compute.py  <-- elevation.py, units.py
       |        (pure math)        (pure math)
       |
       +-- skeleton.py           \
       +-- bridge_lines.py       |
       +-- alignment.py          | C3D-only (geometry creation)
       +-- c3d_doc.py            |
       +-- layers.py             |
       +-- xdata.py              |
       +-- solids.py             |
       +-- purge.py              /
```

The split between **pure math** and **C3D-only** is deliberate. Every pure-math module has this comment at the top:

> Pure-logic module: must not import anything from the Civil 3D API
> (`clr`, `Autodesk.*`). Importable on macOS for unit testing.

That's why we can run 101 unit tests on macOS -- the entire elevation chain, parameter validation, AISC lookup, skew correction, and station-varying interpolation all run without Civil 3D.

## What Each Module Does

### `src/phase1_params.py` -- Parameter Loading

Loads the JSON, validates it, returns frozen dataclasses:

- `Support` -- station, skew angle, support type, bearing offsets
- `Span` -- links two supports by ID
- `Superstructure` -- girder type/shape/count, spacings, deck dimensions, haunch depth
- `Phase1Params` -- the top-level container

The **edge-spacing rule** (docstring lines 30-36): specify exactly ONE of `left_edge_to_G1` or `Gn_to_right_edge` per side; the other is derived so that spacings + edges = total bearing line distance. This keeps skewed bridges geometrically consistent.

### `src/station_profile.py` -- Station-Varying Parameters

Handles parameters that can be constant OR vary along the alignment. `crown_offset` and `deck_cl_offset_from_alignment` both use this. The JSON accepts either form:

```json
"crown_offset": 0.0

"crown_offset": [{"station": 100, "value": 0},
                  {"station": 200, "value": 2.5}]
```

Both parse into a `StationProfile` with an `.at(station)` method that linearly interpolates (lines 41-62).

### `src/aisc.py` -- Steel Shape Lookup

Loads `data/aisc_w_shapes.json` (266 W-shapes from W10 to W44). Each shape is a `WShape` dataclass with the dimensions that matter for geometry: `d_in` (depth), `bf_in` (flange width), `tf_in` (flange thickness), `tw_in` (web thickness). All stored in inches -- converted to feet at the geometry boundary via `src/units.py`.

### `src/elevation.py` -- The Vertical Chain

Two key functions:

**`top_of_deck_at_offset()`** (lines 44-59) -- given a profile elevation, crown position, cross slopes, and a girder's offset from alignment, computes the deck top elevation at that girder:

```
deck_top = profile_elev + deck_profile_offset
         + (cross_slope% / 100) * |distance_from_crown|
```

**`superstructure_elevations()`** (lines 62-78) -- chains downward from a known deck top:

```
top_of_deck
  - deck_depth
  - haunch_depth
= top_of_girder_flange
  - girder_depth          (from AISC table, d_in converted to feet)
= bottom_of_girder
  - bearing_device_height
= bearing_seat
```

### `src/phase1_compute.py` -- Pure-Math Orchestrator

Takes params + AISC table + a profile-elevation callback, produces a `Phase1ComputeResult` containing `ComputedSpan` objects. Each span contains `GirderInSpan` objects, each with a `start` and `end` `GirderAtBearing`:

```python
@dataclass(frozen=True)
class GirderAtBearing:                    # lines 58-67
    support_id: str
    bearing_station: float               # ft, on main alignment
    girder_offset: float                 # ft, perpendicular to alignment
    along_bearing_offset: float          # ft, along the bearing line
    top_of_deck: float
    top_of_girder_flange: float
    bottom_of_girder: float
    bearing_seat: float
```

This is the data the geometry generators consume -- station + offset gives `(x, y)` via the alignment API, `top_of_girder_flange` gives `z`.

The **skew correction math** (module docstring lines 19-35): girder spacings are measured along the bearing line (what's on the plans), but the alignment API and cross-slope math need perpendicular offsets. For a skewed support: `perpendicular_offset = along_bearing_offset * cos(skew)`.

### `src/skeleton.py` -- Sample Lines at Supports

Creates Civil 3D Sample Lines at each support station:

- Grouped under `BRIDGE-SUPPORTS` (line 42)
- Named by `support_id` (e.g., `ABUT-A`, `PIER-1`)
- Skewed to match `support.skew_angle`
- Length = deck width + 2 ft overhang (1 ft each side)
- **Idempotent**: if a sample line with that name already exists, it is preserved -- designers can drag it and the tool respects the new position

### `src/bridge_lines.py` -- Deck Edge Polylines

Creates AutoCAD Polylines for deck edges:

- `BRIDGE-EDGE-L`, `BRIDGE-EDGE-R` -- left and right deck edges
- `BRIDGE-CL` -- deck centerline (only when deck CL != alignment)
- All on `BRIDGE-NOPLOT` layer -- **locked** (can't accidentally move) and **non-plotting** (won't clutter sheets)
- Endpoints land on the skewed bearing lines at support stations
- Tagged with xdata so the tool can find them on re-run

Why polylines instead of true C3D Alignments? Documented in the module header (lines 21-31): pythonnet 3 has trouble disambiguating `Alignment.Create` overloads. Polylines deliver the same dimensioning value without the API friction. Phase 2 can revisit if curved geometry needs station/offset queries.

### `src/xdata.py` -- Object Identity Tags

Every bridge object gets an xdata tag under the `BRIDGE_MODELER` RegApp. The payload is a JSON string:

```json
{"bridge_line": "BRIDGE-EDGE-L"}
{"element": "GIRDER", "span": "SPAN-1", "girder": 1}
```

This enables:

- **Re-run purging** -- `src/purge.py` erases everything on `BRIDGE-*` layers
- **Idempotent find-or-create** -- skeleton elements are found by name/xdata before deciding to create
- **Selection filters** -- `XDLIST` command shows the tags; scripts can filter by element type

### `src/c3d_doc.py` -- Document/Transaction Helpers

Wraps the .NET `DocumentLock` and `Transaction` disposables in Python context managers with explicit `Dispose()` calls in `finally` blocks. This avoids the pythonnet 3 `__exit__` mis-binding that masked real errors for most of Phase 0 debugging.

### `src/solids.py` -- Solid3d Creation

Phase 0 helper for creating axis-aligned boxes, rotating them, and appending to ModelSpace on a named layer. The girder solids slice will extend this with swept-solid support.

### `src/purge.py` -- Re-Run Cleanup

Erases all ModelSpace entities whose layer starts with `BRIDGE-`. Called at the start of each run so solids are regenerated fresh. Skeleton elements survive because they live on layers that the purge logic will need to exempt (or because skeleton creation is idempotent and runs after purge).

## Layer Strategy

~20 unnumbered component-level layers. Per-element identity lives in xdata, not the layer table:

```
BRIDGE-DECK              Deck solids
BRIDGE-GIRDER            Girder solids
BRIDGE-DECK-HAUNCH       Haunch solids
BRIDGE-PIER-COL          Pier columns
BRIDGE-PIER-CAP          Pier caps
BRIDGE-NOPLOT            Reference polylines (locked, non-plotting)
BRIDGE-SKELETON-GIRDER   Girder sub-alignments (future)
BRIDGE-*-BELOW           Below-grade variants with DASHED linetype
```

## Data Flow Through a Typical Run

```
 test/params.phase1.local.json
              |
              v
  +-- phase1_params.load() --+
  |                           |
  |  Support(ABUT-A, sta=100, |     data/aisc_w_shapes.json
  |    skew=10 deg)           |              |
  |  Support(ABUT-B, sta=200) |              v
  |  Span(SPAN-1, A->B)      |     aisc.load() -> {"W36X150": WShape(
  |  Superstructure(W36X150,  |       d=36.33", bf=11.98", tf=1.13",
  |    4 girders, ...)        |       tw=0.625", ...)}
  +----------+----------------+              |
             |                               |
             v                               v
  +-- phase1_compute.compute() -----------------+
  |                                              |
  |  For each span:                              |
  |    1. Resolve along-bearing girder offsets    |
  |       (perpendicular_deck_width / cos(skew)) |
  |    2. Derive missing edge spacing            |
  |    3. Compute deck-CL offset at each support |
  |    4. For each girder at each bearing:       |
  |       a. along_bearing_offset (signed)       |
  |       b. perpendicular offset (* cos(skew))  |
  |       c. top_of_deck (via elevation.py)      |
  |       d. Chain: deck -> flange -> girder     |
  |          bottom -> bearing seat              |
  |                                              |
  |  Result: Phase1ComputeResult                 |
  |    +- ComputedSpan                           |
  |        +- GirderInSpan(G1)                   |
  |            +- start: GirderAtBearing(         |
  |            |    sta=100, offset=-8.2,         |
  |            |    top_flg=98.42, bot=95.39)     |
  |            +- end: GirderAtBearing(           |
  |                 sta=200, offset=-8.2,         |
  |                 top_flg=97.31, bot=94.28)     |
  +------------------+---------------------------+
                     |
        +------------+------------+
        v            v            v
  +----------+ +----------+ +----------+
  | skeleton | | bridge   | | text     |
  | .py      | | _lines   | | report   |
  |          | | .py      | |          |
  | Sample   | | EDGE-L   | | Printed  |
  | lines at | | EDGE-R   | | to Watch |
  | supports | | (CL)     | | node     |
  +----------+ +----------+ +----------+
```

## Test Architecture

All pure-math modules are testable on macOS. The tests live in `test/`:

| Test file | What it covers |
|---|---|
| `test/test_elevation.py` | Vertical chain math, cross-slope, crown offset |
| `test/test_phase1_compute.py` | End-to-end compute with mocked profile elevation |
| `test/test_phase1_params.py` | JSON loading, validation, edge-spacing rule |
| `test/test_station_profile.py` | Interpolation, scalar/array parsing |
| `test/test_aisc.py` | Shape lookup, normalization, missing-field errors |
| `test/test_units.py` | in/ft/mm conversions |
| `test/test_params.py` | Phase 0 params (legacy) |

The C3D-side modules (`skeleton.py`, `bridge_lines.py`, `alignment.py`, `solids.py`) can only be tested by running the Dynamo graph on Windows -- tracked in `MANUAL-TASKS.md`.

## What's Next: Girder Solids

The compute result already has everything needed. The next slice will:

1. Take each `GirderInSpan` from the compute result
2. Convert `(station, perpendicular_offset)` to `(x, y)` via `alignment.point_at_station()`
3. Build a W-shape cross-section `Region` from AISC dims (`bf_in`, `d_in`, `tf_in`, `tw_in`)
4. Create a 3D line path between the start and end `(x, y, top_of_girder_flange)`
5. Call `Solid3d.CreateSweptSolid(region, path, sweepOptions)` with `Bank=False`
6. Place on `BRIDGE-GIRDER` layer with xdata

It plugs into `src/phase1_build.py` between line 121 (after bridge_lines) and line 123 (`tr.Commit()`).

After girders: haunches (parallelogram cross-section), then deck solid (lofted between cross-section profiles at bearing lines).
