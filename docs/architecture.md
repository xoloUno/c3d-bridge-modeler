# Bridge Modeler Architecture

How the pipeline works, end to end. Last updated after Phase 2
close-out (curved alignments + polygon-driven deck, commit `ed56232`,
2026-05-20).

## The Big Idea

You write a JSON file describing your bridge (girder type, spacing, supports, skew angles, etc.). You open a Civil 3D drawing with alignment data shortcuts attached. You run a Dynamo graph. The tool reads the JSON, queries the alignment/profile for positions and elevations, computes everything about the bridge geometry, and creates AutoCAD 3D solids in the drawing.

## Two-Mode Workflow

The tool creates two categories of objects with different re-run behavior:

```
+------------------------------------------------------+
|  SKELETON (preserved across runs)                    |
|  - Sample lines at supports + bearing offsets        |
|  - Deck plan polygon (BRIDGE-2D-DECK)                |
|                                                      |
|  Designer can grip-edit these between runs.           |
|  Tool reads positions/shapes back on next run.       |
|  Idempotent: find-by-xdata, create only if absent.   |
|  Self-heal: stale entities with old schema_version   |
|  are erased and regenerated automatically.            |
+------------------------------------------------------+
|  SOLIDS (regenerated each run)                       |
|  - Girders (swept I-shape on BRIDGE-GIRDER)          |
|  - Haunches (box - deck boolean on BRIDGE-DECK-HAUNCH|
|  - Deck slab (sweep + polygon trim on BRIDGE-DECK)   |
|  - Piers, abutments, footings (future)               |
|                                                      |
|  Purged per-layer and rebuilt from current params     |
|  + the live skeleton each run.                       |
+------------------------------------------------------+
```

The deck plan polygon is the main skeleton element: an editable
AutoCAD polyline (with arc bulges for curved alignments) that defines
the deck footprint. The deck solid is built FROM this polygon. If a
designer grip-edits a polygon vertex, the deck solid follows on the
next run -- Inventor-style "sketch drives solid."

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
            +-------+-------+----+----+-------+-------+
            v       v       v    v    v       v       v
          params  AISC   C3D  compute skel.  solids  report
          load    table  align        +poly   gen
```

### (1) The Dynamo Node -- `src/phase1_node.py`

The code you paste into the Dynamo Python Script node. It does three things:

1. **Cleans the Python path** (lines 41-42) -- strips stale repo paths from `sys.path` so you don't accidentally run old code from a different clone.
2. **Purges cached modules** (lines 47-72) -- Dynamo caches Python modules across runs; this forces fresh imports every time. The purge list covers all `src/` modules.
3. **Calls the orchestrator** (line 75) -- `phase1_build.main(repo_root, params_path)`.

The **reload trigger** on line 29 is a hack: Dynamo only re-executes a Python node if the body text changed, so bumping the number after a `git pull` forces re-execution.

### (2) The Orchestrator -- `src/phase1_build.py`

Everything happens inside a document lock + transaction (lines 101-203):

```python
with c3d_doc.locked_document():          # required or AutoCAD throws eLockViolation
    with c3d_doc.transaction() as tr:     # if tr.Commit() isn't called, everything aborts
        # ... all work happens here ...
        tr.Commit()                       # line 203
```

Why `locked_document()` instead of `with doc.LockDocument()`? Because pythonnet 3 mis-routes Python's `__exit__` to .NET's `OnExit(int)` during exception unwinding. Documented in `src/c3d_doc.py` lines 59-78.

Inside the transaction, the sequence is:

1. **Load params** -- `phase1_params.load()` (line 87)
2. **Load AISC table** -- `aisc.load()` (line 90)
3. **Validate** girder shapes exist in the AISC table (lines 92-94)
4. **Find alignment + profile** in the drawing (lines 103-106)
5. **Run compute** -- `phase1_compute.compute()` (line 112) -- pure math, produces structured elevation data
6. **Create skeleton** -- sample lines at supports + bearing offsets (lines 115-123)
7. **Ensure deck plan polygon** -- `deck_polygon.ensure_deck_plan_polygon()` (lines 132-138) -- find-or-create the BRIDGE-2D-DECK polyline; read back vertices + bulges if it already exists
8. **Regenerate girder solids** -- `girders.ensure_phase1_girders()` (lines 153-160)
9. **Regenerate haunch solids** -- `haunches.ensure_phase1_haunches()` (lines 169-177)
10. **Regenerate deck solids** -- `decks.ensure_phase1_decks(polygon_vertices=...)` (lines 186-195) -- the deck solid is built FROM the polygon vertices read back in step 7
11. **Commit** the transaction (line 203)
12. **Format text report** for the Watch node (line 205)

Note that `bridge_lines.py` (the old BRIDGE-NOPLOT EDGE-L, EDGE-R, CL polylines) is no longer called by the orchestrator. The BRIDGE-2D-DECK polygon replaces all three. The module is retained in the repo but unused.

### (3) The Building Blocks

Dependency graph:

```
  phase1_node.py
       |
       v
  phase1_build.py  (C3D orchestrator)
       |
       |  --- pure-math layer (macOS-testable) --------
       |
       +-- phase1_params.py  <-- station_profile.py
       +-- aisc.py  <-- data/aisc_w_shapes.json
       +-- phase1_compute.py  <-- elevation.py, units.py
       +-- girder_geometry.py       (I-shape profile vertices)
       +-- haunch_geometry.py       (trapezoid profile vertices)
       +-- deck_geometry.py         (deck cross-section vertices)
       +-- deck_plan.py             (deck plan polygon derivation
       |                             with arc bulges + 5-way gating)
       |
       |  --- C3D-only layer (Windows / Civil 3D) -----
       |
       +-- skeleton.py              (sample lines at supports + bearings)
       +-- deck_polygon.py          (BRIDGE-2D-DECK polyline, editable)
       +-- girders.py               (swept I-shape solids)
       +-- haunches.py              (box - deck boolean solids)
       +-- decks.py                 (sweep + polygon-trim slab solids)
       +-- alignment.py             (alignment/profile queries +
       |                             entity walk for curvature detection)
       +-- c3d_doc.py               (doc lock + transaction)
       +-- layers.py, xdata.py      (layer + identity helpers)
       +-- purge.py                 (re-run cleanup, legacy)
       +-- bridge_lines.py          (DEPRECATED — replaced by deck_polygon)
```

The pure-math / C3D-only split is deliberate. Every pure-math module has this comment at the top:

> Pure-logic module: must not import anything from the Civil 3D API
> (`clr`, `Autodesk.*`). Importable on macOS for unit testing.

This is why 201 unit tests run on macOS -- elevation chain, parameter validation, AISC lookup, skew correction, cross-section geometry, deck plan polygon derivation, and station-varying interpolation all work without Civil 3D.

## What Each Module Does

### Pure-Math Layer

#### `src/phase1_params.py` -- Parameter Loading

Loads and validates the JSON, returns frozen dataclasses:

- `Support` -- station, skew angle, support type, bearing offsets
- `Span` -- links two supports by ID
- `Superstructure` -- girder type/shape/count, spacings, deck dimensions, haunch depth, cross slopes
- `Phase1Params` -- the top-level container

The **edge-spacing rule** (docstring lines 30-36): specify exactly ONE of `left_edge_to_G1` or `Gn_to_right_edge` per side; the other is derived so that spacings + edges = total bearing line distance. This keeps skewed bridges geometrically consistent.

**Shifting deck CL** -- `deck_cl_offset_from_alignment` now accepts 2-point profiles (start != end) as long as the deck cross-section has no crown kink at any bearing. The validator checks `deck_geometry.crown_kink_present()` at each (span, side) and rejects kink + shift combos with an explanatory error.

#### `src/station_profile.py` -- Station-Varying Parameters

Handles parameters that are constant or vary along the alignment. `crown_offset` and `deck_cl_offset_from_alignment` both use this. The JSON accepts either form:

```json
"crown_offset": 0.0

"crown_offset": [{"station": 100, "value": 0},
                  {"station": 200, "value": 2.5}]
```

Both parse into a `StationProfile` with an `.at(station)` method that linearly interpolates (lines 41-62).

#### `src/aisc.py` -- Steel Shape Lookup

Loads `data/aisc_w_shapes.json` (266 W-shapes, W10 to W44). Each shape is a `WShape` dataclass with the dimensions needed for geometry: `d_in` (depth), `bf_in` (flange width), `tf_in` (flange thickness), `tw_in` (web thickness). Stored in inches, converted to feet at the geometry boundary via `src/units.py`. Spot-checked against AISC Steel Construction Manual v15/v16 on 2026-05-18.

#### `src/elevation.py` -- The Vertical Chain

Two functions:

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

#### `src/phase1_compute.py` -- Pure-Math Orchestrator

Takes params + AISC table + a profile-elevation callback, returns a `Phase1ComputeResult` with `ComputedSpan` objects. Each span contains:

- `GirderInSpan` objects, each with a `start` and `end` `GirderAtBearing`:

```python
@dataclass(frozen=True)
class GirderAtBearing:
    support_id: str
    bearing_station: float               # ft, on main alignment
    girder_offset: float                 # ft, perpendicular to alignment
    along_bearing_offset: float          # ft, along the bearing line
    top_of_deck: float
    top_of_girder_flange: float
    bottom_of_girder: float
    bearing_seat: float
    haunch_h_left_ft: float              # haunch height, alignment-left side
    haunch_h_right_ft: float             # haunch height, alignment-right side
```

- `DeckCrossSection` objects at each bearing line (top vertex list + bearing station + skew + deck_depth) -- consumed by `decks.py` and `haunches.py`.

The **skew correction math** (module docstring lines 19-35): girder spacings are measured along the bearing line (what's on the plans), but the alignment API and cross-slope math need perpendicular offsets. For a skewed support: `perpendicular_offset = along_bearing_offset * cos(skew)`.

#### `src/girder_geometry.py` -- I-Shape Profile Builder

Builds the closed 12-vertex outline of an AISC W-shape in profile-local `(u, v)` coordinates, in feet. The vertices trace the full I-shape: top flange, web, bottom flange.

```
    V0 --- V1               v = 0  (top of top flange)
    |       |               v = -tf
    V11    V2
        |
       web                  (x = +/-tw/2)
        |
    V10    V3
    |       |               v = -(d - tf)
    V9     V4
    |       |
    V8 --- V5               v = -d  (bottom of bottom flange)
```

`v = 0` lines up with `top_of_girder_flange` from the elevation chain, so the C3D-side caller places the profile origin directly at the world anchor point without further offset.

#### `src/haunch_geometry.py` -- Haunch Profile Builder

Builds a closed 4-vertex trapezoid for the haunch cross-section. Width = girder flange width (`bf`). Height varies across the flange due to deck cross-slope (`h_left` vs `h_right`). Bottom at `v = 0` (sits on top of girder flange). Note: the actual solid construction in `haunches.py` uses a rectangular-box + boolean-subtract approach instead of sweeping this profile directly -- see the Haunch Solids section below.

#### `src/deck_geometry.py` -- Deck Cross-Section Builder

Builds the deck slab cross-section at a bearing line. Two possible shapes:

- **Parallelogram (4 vertices)** -- super-elevated decks, or decks where both edges fall on the same side of the crown.
- **Hexagon (6 vertices)** -- when the deck straddles the crown AND both cross-slopes have the same sign (typical crowned roadway with a tent-shaped peak).

Also exports `crown_kink_present()`, used by the params validator to gate the shifting-deck-CL + hexagonal-cross-section combination.

#### `src/deck_plan.py` -- Deck Plan Polygon Derivation (NEW in Phase 2.1)

The most complex pure-math module. Derives a closed CCW polygon for the deck footprint in XY, with arc bulges for curved segments.

The polygon traces: `start_left -> start_right -> (right edge) -> end_right -> end_left -> (left edge) -> start_left`.

Each edge segment is derived via **5-way gating** based on alignment geometry:

| Case | Logic |
|---|---|
| Constant offset, any alignment | Pure offset from alignment (concentric arcs on curves) |
| Tapering, all tangent/spiral | Linear-in-station taper (straight segments, bulge=0) |
| Tapering, wholly within a single arc | 3-point arc fit through start, midstation, end |
| Tapering, one tangent-to-curve transition | Walk from the tangent end; arc tangent-constrained to preceding edge direction |
| Tapering, viaduct (2+ transitions) | Linear-in-station vertices at every transition; ARC segments get arcs tangent to alignment |

Primitives: `arc_from_start_tangent_endpoint()` and `arc_through_three_points()`. The polygon uses **skewed bearing corners** as start/end points (not the un-skewed alignment-perpendicular endpoints) -- this matters for arcs on tapered curved bridges with skewed supports.

35 unit tests in `test/test_deck_plan.py` cover all five gating cases.

### C3D-Only Layer (Geometry Creation)

#### `src/skeleton.py` -- Sample Lines at Supports

Creates Civil 3D sample lines at each support station:

- Grouped under `BRIDGE-SUPPORTS` (line 42)
- Named by `support_id` (e.g., `ABUT-A`, `PIER-1`)
- Skewed to match `support.skew_angle`
- Length = deck width + 2 ft overhang (1 ft each side)
- **Idempotent**: if a sample line with that name already exists, it stays -- designers can drag it and the tool reads the new position

Also creates **bearing-line sample lines** at each `support.station + bearing_offsets[i]`, named `{support_id}.BRG` (or `.BRG.{i}` for multi-bearing supports). Skipped when `bearing_offset == 0` to avoid duplicating the support sample line.

#### `src/deck_polygon.py` -- Deck Plan Polygon Skeleton (NEW in Phase 2.1)

Connects the pure-math `deck_plan.py` to the C3D drawing. Creates or preserves a closed AutoCAD `Polyline` on `BRIDGE-2D-DECK` (color 142, light blue, **plottable and unlocked** so designers can see and grip-edit it).

Behaviors:
- **Find-or-create with self-heal**: tagged with xdata `{deck_polygon: "DECK-PLAN", schema_version: "v3-skewed-corner-bulges"}`. If the version matches, the existing polygon is kept (including grip-edits). If stale or missing, regenerated from `deck_plan.derive_deck_plan_polygon()`.
- **Read-back**: vertices and bulges are read via `GetPoint2dAt(i)` + `GetBulgeAt(i)` and returned to the orchestrator. The deck solid is built FROM these values, so grip-edits flow through to the 3D geometry.

#### `src/girders.py` -- Girder Swept Solids

For each girder in each span:

1. Looks up the AISC W-shape from `aisc.py` (e.g., W36X150)
2. Builds the 12-vertex I-shape profile via `girder_geometry.py`
3. Materializes it as an AutoCAD `Polyline` -> `Region`
4. **Pre-orients the region** in a vertical plane perpendicular to the girder's plan direction: profile X -> `cross_xy` (horizontal, 90 deg CCW from girder), profile Y -> world +Z. This keeps the web plumb.
5. Creates a 3D `Line` path from start to end bearing: `(x, y, top_of_flange)` at each end
6. Sweeps via `Solid3d.CreateSweptSolid` with `Align=NoAlignment` + `Bank=False`
7. Places on `BRIDGE-GIRDER` layer (red), with xdata `{element, span_id, girder_index, girder_shape, id}`

Profile elevation is sampled at each girder's actual world station (`bearing_station + perp_offset * tan(skew)`), not at the bearing station on the alignment. This makes the girder-to-girder slope in alignment-perpendicular sections match the design cross-slope exactly.

Girders remain **straight chords** between bearings. Curved/chorded girders are Phase 3.

Re-run purges every entity on `BRIDGE-GIRDER` and rebuilds from scratch.

#### `src/decks.py` -- Deck Slab Solids

Construction is **sweep + boolean intersect**:

1. Build a **fat deck**: sweep a wider-than-actual alignment-perpendicular cross-section along the alignment's 3D path. Path sampling is density-driven (~1 sample/ft, min 21) so the `Polyline3d` path tracks curved alignments closely. `Align=NoAlignment` + `Bank=False` keeps the cross-section perpendicular to alignment, preserving design cross-slope.
2. Build a **trim volume**: vertically extrude the **deck plan polygon** (read back from the BRIDGE-2D-DECK skeleton entity, with arc bulges) by a tall extent.
3. Boolean **intersect** the fat deck with the trim volume -> final deck with correct cross-slope AND correct plan footprint (including arcs on curved bridges).

`_fat_deck_envelope()` computes the sweep path + cross-section perp envelope from params + compute_result, widening automatically when the deck CL shifts laterally.

Layer `BRIDGE-DECK` (color 7/white), xdata `{element, span_id, id}`. Exports `build_fat_deck_cutter()` for reuse by haunches.

#### `src/haunches.py` -- Haunch Solids

Construction is **rectangular box + boolean subtract**:

1. For each girder, build an **over-tall rectangular prism**: `bf` wide (flange width), `haunch_depth + 0.5 * deck_depth` tall, swept along the same girder path with the same orientation as the girder solid.
2. Build a fat deck cutter (same as `decks.py` uses for the intersect).
3. **Boolean-subtract the deck** from the over-tall box. This removes everything above the deck soffit, leaving the haunch from top-of-flange up to deck soffit.

Layer `BRIDGE-DECK-HAUNCH` (color 51/yellow-brown), xdata `{element, span_id, girder_index, id}`.

#### `src/alignment.py` -- Alignment/Profile Queries

Civil 3D API wrapper. Main functions:

- `point_at_station(alignment, station, offset)` -> `(easting, northing)`
- `direction_at_station(alignment, station)` -> bearing in radians
- `elevation_at_station(profile, station)` -> Z
- `point_on_skewed_bearing(alignment, station, skew_deg, perp_offset)` -> `(x, y)` -- computes the XY of a point on a skewed bearing line at a given perpendicular offset from the alignment
- `alignment_entity_ranges(alignment, start_sta, end_sta)` -> list of `(entity_type, start_sta, end_sta, radius)` tuples -- **added in Phase 2.1**, walks `alignment_obj.Entities` and recurses into composites (e.g. `SpiralCurveSpiral`). Falls back to numerical curvature detection (sampling `direction_at_station`) if the entity walk fails, so the build never crashes on unsupported alignment shapes.

The entity walk surfaced two pythonnet quirks (documented in `CLAUDE.md`): `AlignmentSubEntity` uses `SubEntityType` (not `EntityType`), and `AlignmentSubEntityType` enum values may stringify as integers (`"257"` for Tangent, `"258"` for Curve, `"259"` for Spiral).

#### `src/xdata.py` -- Object Identity Tags

Every bridge object gets an xdata tag under the `BRIDGE_MODELER` RegApp. The payload is a JSON string:

```json
{"deck_polygon": "DECK-PLAN", "schema_version": "v3-skewed-corner-bulges"}
{"element": "GIRDER", "span_id": "SPAN-1", "girder_index": 1, "girder_shape": "W36X150"}
{"element": "DECK", "span_id": "SPAN-1"}
{"element": "HAUNCH", "span_id": "SPAN-1", "girder_index": 1}
```

Used for:

- **Re-run purging** -- per-layer purge erases everything on e.g. `BRIDGE-GIRDER`
- **Idempotent find-or-create** -- skeleton elements are found by name/xdata before creating new ones
- **Self-heal** -- deck_polygon and bridge_lines detect schema_version mismatches and regenerate
- **Selection filters** -- `XDLIST` shows the tags; scripts can filter by element type

#### `src/c3d_doc.py` -- Document/Transaction Helpers

Wraps the .NET `DocumentLock` and `Transaction` disposables in Python context managers with explicit `Dispose()` calls in `finally` blocks. Without this, pythonnet 3's `__exit__` mis-binding masks real errors (most of Phase 0 debugging was this).

#### `src/bridge_lines.py` -- DEPRECATED

Formerly created BRIDGE-NOPLOT EDGE-L, EDGE-R, CL polylines. Replaced by BRIDGE-2D-DECK polygon in Phase 2.1. Still in the repo but no longer imported. Existing BRIDGE-NOPLOT polylines in drawings are inert.

## Layer Strategy

~20 unnumbered component-level layers. Per-element identity lives in xdata, not the layer table:

```
BRIDGE-DECK              Deck solids (color 7 / white)
BRIDGE-GIRDER            Girder solids (color 1 / red)
BRIDGE-DECK-HAUNCH       Haunch solids (color 51 / yellow-brown)
BRIDGE-2D-DECK           Deck plan polygon (color 142 / light blue, UNLOCKED, plottable)
BRIDGE-NOPLOT            Legacy reference polylines (locked, non-plotting, DEPRECATED)
BRIDGE-PIER-COL          Pier columns (future)
BRIDGE-PIER-CAP          Pier caps (future)
BRIDGE-SKELETON-GIRDER   Girder sub-alignments (future)
BRIDGE-*-BELOW           Below-grade variants with DASHED linetype (future)
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
  |  Support(ABUT-B, sta=200, |              v
  |    skew=-10 deg)          |     aisc.load() -> {"W36X150": WShape(
  |  Span(SPAN-1, A->B)      |       d=35.9", bf=11.975", tf=1.128",
  |  Superstructure(W36X150,  |       tw=0.625", ...)}
  |    4 girders, ...)        |
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
  |       e. haunch_h_left, haunch_h_right       |
  |    5. DeckCrossSection at each bearing line  |
  |       (4 or 6 vertex polygon)                |
  |                                              |
  |  Result: Phase1ComputeResult                 |
  |    +- ComputedSpan                           |
  |        +- GirderInSpan(G1)                   |
  |        |   +- start: GirderAtBearing(...)    |
  |        |   +- end: GirderAtBearing(...)      |
  |        +- GirderInSpan(G2) ...               |
  |        +- DeckCrossSection(start_bearing)    |
  |        +- DeckCrossSection(end_bearing)      |
  +------------------+---------------------------+
                     |
     +--------+------+------+--------+--------+
     v        v      v      v        v        v
  +------+ +------+ +----+ +------+ +------+ +------+
  |skel. | |deck  | |gir-| |haun- | |decks | |text  |
  |.py   | |_poly-| |ders| |ches  | |.py   | |report|
  |      | |gon   | |.py | |.py   | |      | |      |
  |Sample| |.py   | |Swept| |Box - | |Sweep | |Watch |
  |lines | |      | |I-   | |deck  | |+ poly| |node  |
  |+brg  | |BRIDGE| |shape| |bool  | |trim  | |      |
  |lines | |-2D-  | |     | |      | |bool  | |      |
  |      | |DECK  | |     | |      | |      | |      |
  +------+ +--+---+ +----+ +------+ +--+---+ +------+
               |                        ^
               |   polygon_vertices     |
               +------------------------+
               (deck solid is built FROM
                the polygon read back)
```

## Test Architecture

All pure-math modules are testable on macOS. 201 tests across `test/`:

| Test file | What it covers |
|---|---|
| `test/test_elevation.py` | Vertical chain math, cross-slope, crown offset |
| `test/test_phase1_compute.py` | End-to-end compute with mocked profile elevation, deck cross-sections, haunch heights |
| `test/test_phase1_params.py` | JSON loading, validation, edge-spacing rule, bearing offsets, shifting-dcl gating |
| `test/test_station_profile.py` | Interpolation, scalar/array parsing |
| `test/test_aisc.py` | Shape lookup, normalization, missing-field errors |
| `test/test_girder_geometry.py` | I-shape vertex math, dimensions, edge cases |
| `test/test_haunch_geometry.py` | Trapezoid profile, symmetric/asymmetric heights |
| `test/test_deck_geometry.py` | Parallelogram and hexagon cross-sections, crown kink detection |
| `test/test_deck_plan.py` | Deck plan polygon derivation, all 5 gating cases, arc bulge math |
| `test/test_units.py` | in/ft/mm conversions |
| `test/test_params.py` | Phase 0 params (legacy) |

The C3D-side modules (`girders.py`, `haunches.py`, `decks.py`, `deck_polygon.py`, `skeleton.py`) can only be tested by running the Dynamo graph on Windows -- tracked in `MANUAL-TASKS.md`.

## Geometry Construction Techniques

### Why Sweep + Boolean Instead of Loft

Both deck and haunch solids use booleans rather than direct lofting.

**Deck**: an earlier version lofted between two skewed-bearing cross-sections. When the two supports had different skew angles (e.g., +10 deg and -10 deg), the loft introduced a twist artifact that distorted the alignment-perpendicular cross-slope. The sweep + intersect approach builds a straight-through prismatic deck (constant cross-slope everywhere) and then trims it to the plan footprint with a boolean.

**Haunches**: an earlier version swept a trapezoidal cross-section along the girder path. For fanning girders (on flared bridges), the oblique cut of an alignment-perpendicular section through the swept haunch picked up a ~0.09% slope artifact. The rectangular-box + boolean-subtract approach forces the haunch top to coincide with the deck soffit at every point by construction, dropping the artifact to ~0.008%.

### The Polygon-Driven Deck (Phase 2.1 Architecture)

Phase 2.1 fixed a problem: the deck solid's trim polygon and the BRIDGE-NOPLOT edge polylines were computed independently from the same params, so on tapered curved bridges the deck edges and the dimensioning polylines didn't match. Neither was right -- neither produced the tangent-constrained arcs you'd expect at curve-to-tangent transitions.

The fix is Inventor-style: **a single editable sketch entity drives the solid**.

```
  deck_plan.py (pure math)
       |
       | derives polygon with arc bulges
       | via 5-way gating on alignment geometry
       v
  deck_polygon.py (C3D)
       |
       | creates/preserves BRIDGE-2D-DECK polyline
       | reads back vertices + bulges (including grip-edits)
       v
  polygon_vertices  ------>  decks.py
                             builds trim volume from polygon
                             boolean intersects with fat-deck sweep
                             = final deck solid
```

The polygon is the single source of truth. If a designer grip-edits a vertex, the polygon is `preserved` and the deck solid follows on the next run.

### IDisposable Cleanup

AutoCAD .NET objects (`Polyline`, `Region`, `Line`, `Solid3d`, `DBObjectCollection`) are all IDisposable. Per the pythonnet 3 quirk documented in `CLAUDE.md`, `with` statements misroute `__exit__` during exception unwinding. All geometry modules use explicit `try / finally` with `.Dispose()` calls instead.

## Current State

Phase 2 is **COMPLETE** (2026-05-20). Verified on the D-E test alignment with:

- Straight and curved horizontal alignments
- Asymmetric skew (+10 deg / -10 deg)
- Fanning deck width (22 ft -> 25 ft perpendicular)
- -5% longitudinal grade
- 4 x W36X150 girders
- Bearing offsets (1.5 ft / -1.5 ft)
- Shifting deck CL (start=-9, end=-6)
- Polygon grip-edit roundtrip (preserved, deck follows)
- Arc rendering + DIMRADIUS on curved edges

**Phase 3 candidates** (see `docs/phase2-scope.md`):
- Super-elevation (station-varying cross-slope)
- In-place solid geometry swap (preserve ObjectIds across regenerate)
- Curved/chorded girders
- Substructure (pier caps, columns, abutments, footings)
- Multi-span bridges
- Plate girders
