# Manual Tasks (Civil 3D side)

These steps require Civil 3D 2024 on Windows and cannot be performed
from the macOS dev environment. Check items off as they are verified.

## Phase 0 verification — VERIFIED 2026-05-06

All checks below were completed end-to-end on a fresh Civil 3D 2024
drawing with data shortcuts attached to alignment `D-E` and profile
`D-E PGL`. Per-quirk findings discovered during this verification are
captured in `CLAUDE.md` ("PythonNet 3 quirks worth knowing").

### Setup
- [x] On Windows, copy the schema example to a local-only config:
      `cp test/params.phase0.json test/params.local.json`. Edit
      `test/params.local.json` with the actual alignment, profile,
      and EG surface names from your reference drawing's data
      shortcuts; adjust station range and pier stations to match.
      `test/params.local.json` is gitignored so `git pull` will never
      conflict with these edits.
- [x] In Dynamo for Civil 3D, build `src/phase0_bridge.dyn`:
      - `Directory Path` (or `File Path` set to a folder) input → repo
        root
      - `File Path` input → `test/params.local.json` (NOT
        `params.phase0.json` — that's the committed schema example)
      - Python Script node; paste contents of `src/phase0_node.py`;
        wire `IN[0]` ← repo root, `IN[1]` ← params path
      - `Watch` node on the Python node's output
      - Save the graph as `src/phase0_bridge.dyn`
      - Python node engine MUST be set to CPython 3 (PythonNet 3), not
        IronPython 2.7

### Run + first-pass checks
- [x] Open the reference Civil 3D drawing with data shortcuts attached
- [x] Open `src/phase0_bridge.dyn` and run the graph
- [x] Watch node summary reports
      `Created 1 deck + 2 piers on BRIDGE-* layers`
- [x] `BRIDGE-DECK` and `BRIDGE-PIER-COL` layers exist in the layer
      table (refresh / unfilter the Layer Properties Manager if they
      don't appear at first — they're in the database regardless)
- [x] ModelSpace contains exactly 3 solids (1 deck box, 2 pier boxes)
      on those layers
- [x] `XDLIST` on each solid shows `BRIDGE_MODELER` xdata with the
      expected JSON payload (`{"phase":0,"element":"DECK","id":...}`
      etc.)

### Display + xref
- [x] In a viewport, set visual style to **Hidden** — the bridge
      wireframe renders correctly with hidden-line removal
- [x] In a separate sheet drawing, xref the bridge drawing; set the
      sheet viewport to **Hidden** visual style — confirm the xref
      displays as expected. Note: in plan view the deck correctly
      occludes the piers below it (Hidden does hidden-line removal);
      a "Foundation Plan" sheet that shows piers as dashed in plan is
      a Phase 4 (drawing production aids) concern.

### Re-run contract
- [x] Edit `test/params.phase0.json` (or simply re-run after a prior
      run); console reports `[build] step: purged 3` (the prior
      solids), then creates 3 new ones
- [x] Watch node summary on the second run reports
      `Erased 3 prior BRIDGE-* objects. Created 1 deck + 2 piers...`

## Phase 1 verification

### Bridge template DWG

The geometry-generation slices load `templates/bridge_template.dwg`
to pull layer / linetype / skeleton-style / IFC PropSet definitions
into the active drawing. The DWG must be authored manually — a valid
C3D template requires AEC dictionary objects, sample line styles,
and Property Set Definitions that can't be authored from macOS or
from Python. `templates/README.md` is the source of truth for the
contents listed below.

- [ ] On Windows, open Civil 3D 2024 and start a new DWG from a
      clean Civil 3D template (e.g. `_AutoCAD Civil 3D (Imperial)
      NCS.dwt`).
- [ ] Add every `BRIDGE-*` layer in `templates/README.md` ("Layer
      Structure"), with the listed ACI color and linetype.
      `Continuous` is loaded by default; load `DASHED` from
      `acad.lin` once via `-LINETYPE → Load → DASHED → acad.lin` so
      it lives in the template's linetype table.
- [ ] Define the skeleton element styles named in
      `templates/README.md` ("Skeleton element styles"): a sample
      line style for `BRIDGE-SKELETON-SUPPORT`, an alignment style
      for `BRIDGE-SKELETON-GIRDER` / `-EDGE`, and a profile style
      for the per-girder profiles. Suggested names match the
      README so the tool can reference them by string.
- [ ] Define the `BRIDGE_IFC` Property Set Definition per
      `templates/README.md` ("IFC Property Set Definitions"):
      applies to `AcDbSolid3d`; four manual text fields
      (`IfcEntity`, `PredefinedType`, `BridgeName`, `ElementId`).
      Use **Manage → CAD Standards → Configure → Property Set
      Definitions** or the `PROPERTYSETDEFINE` command.
- [ ] `SAVEAS` to `templates/bridge_template.dwg` in the repo (DWG
      2018 format is fine — Civil 3D 2024 reads it natively).
- [ ] Spot-check persistence: close the DWG, re-open it in a fresh
      Civil 3D session, and confirm (a) all `BRIDGE-*` layers are
      present with the expected colors and linetypes, (b) the three
      skeleton styles appear under their respective Settings nodes,
      and (c) `PROPERTYSETDEFINE` lists `BRIDGE_IFC` with the four
      fields.

### AISC W-shape table spot-check — VERIFIED 2026-05-18
- [x] Open `data/aisc_w_shapes.json` and verify a sample of shape
      dimensions against AISC Steel Construction Manual (v15 or v16).
      Suggested sample (covers light, medium, and heavy bridge girder
      sizes): W14X22, W18X35, W24X62, W30X90, W36X150, W40X167, W44X230.
      Check `d`, `bf`, `tf`, `tw`, and `lb_per_ft` for each. Values
      should be in inches (decimal) and lb/ft. Report any discrepancies
      so we can correct the source data.

### Phase 1 build verification — elevation report (no geometry yet) — VERIFIED
- [x] Copy `test/params.phase1.example.json` to
      `test/params.phase1.local.json` and edit it with real alignment,
      profile, EG, FG names from your reference drawing's data
      shortcuts. Adjust `begin_station`, `end_station`, `supports[].station`,
      and `supports[].bearing_offsets` to match the project. Confirm at
      least one `superstructures[].girder_shape` is a real AISC W-shape
      (e.g. W36X150) so AISC validation passes.
- [x] In Dynamo for Civil 3D, build `src/phase1_bridge.dyn`:
      - `Directory Path` input → repo root
      - `File Path` input → `test/params.phase1.local.json`
      - Python Script node; paste contents of `src/phase1_node.py`;
        wire `IN[0]` ← repo root, `IN[1]` ← params path
      - `Watch` node on the Python node's output
      - Save the graph as `src/phase1_bridge.dyn`
      - Python node engine MUST be set to CPython 3 (PythonNet 3)
- [x] Open the reference Civil 3D drawing with data shortcuts attached
- [x] Run the graph; `Watch` node displays the elevation report
      starting with `== SPAN-1 (... → ...) ==` and listing per-girder
      `top_deck`, `top_flg`, `bot_grdr`, `brg_seat` at start and end
      bearings
- [x] Cross-check one girder's elevations against a manual calculation
      (e.g. interior girder G2 at the start bearing): `top_of_deck =
      profile_elev + deck_profile_offset + cross_slope/100 *
      |girder_offset - crown_offset|`. Match within 0.01 ft.
- [x] Confirm no `BRIDGE-*` layers or geometry are created — this
      slice is read-only and informational

### Phase 1 schema migration (skew + station-varying offsets) — VERIFIED
- [x] Update `test/params.phase1.local.json` to the new schema:
      - Add `perpendicular_deck_width_start` and `perpendicular_deck_width_end`
        (the engineer's intended perpendicular deck width).
      - Set EXACTLY ONE of (`left_edge_to_G1_*`, `Gn_to_right_edge_*`) per
        side; the other must be `null` (will be derived from
        `perpendicular_deck_width / cos(skew)` and the spacings).
      - Add `deck_cl_offset_from_alignment` (scalar, e.g. `0.0`, or array
        of `{station, value}` for station-varying).
      - Confirm `crown_offset` is scalar OR array form (it now accepts
        both).
- [x] Re-run the graph; for skewed supports, the elevation-report numbers
      will shift slightly vs. the previous run because spacings are now
      correctly interpreted as along-bearing measurements (perpendicular
      offsets are derived via `× cos(skew)`).
- [x] Sample-line lengths now equal `perpendicular_deck_width / cos(skew)`
      + 2 ft overhang. For the 22 ft perpendicular deck at 10° skew, sample
      line should be ~24.34 ft (was 24.0 ft when spacings were treated as
      perpendicular).

### Phase 1 sample-line skeleton verification — VERIFIED
- [x] Bump the reload trigger in the Python node body (already at v2
      in committed `src/phase1_node.py`) and rerun the graph
- [x] Watch node summary first line reads
      `Skeleton: created N sample line(s), preserved 0 existing`
      where N matches the number of supports in your local params
- [x] In Civil 3D, `LIST` or Properties panel shows a Sample Line
      Group named `BRIDGE-SUPPORTS` parented to your bridge alignment
- [x] Each sample line is named after its `support_id` (e.g. `ABUT-A`,
      `ABUT-B`); positions match support stations on the alignment
- [x] Sample lines are skewed by `support.skew_angle` from
      perpendicular (verify visually if non-zero skew; otherwise the
      lines are square to the alignment)
- [x] Sample line length = deck width + 2 ft (1 ft overhang on each
      side); for a 22 ft deck the sample lines are 24 ft total
- [x] Re-run the graph: summary now reads
      `Skeleton: created 0 sample line(s), preserved N existing` —
      confirms the skeleton is preserved across runs (designer edits
      will not be overwritten)
- [x] Optional: manually move one sample line in C3D (drag a station
      grip), rerun, confirm the moved line is preserved in place

### Phase 1 sample-line asymmetric extension for offset deck CL — VERIFIED 2026-05-07
- [x] In `test/params.phase1.local.json`, set
      `deck_cl_offset_from_alignment` to a non-zero scalar (e.g.
      `5.0`).
- [x] In Civil 3D, manually delete the existing `BRIDGE-SUPPORTS`
      sample lines (and the `BRIDGE-EDGE-L`/`-R`/`-CL` polylines so
      they regenerate at the shifted positions). The find-by-name
      logic preserves existing sample lines across runs, so the
      manual delete is required to pick up the new asymmetric
      formula.
- [x] Bump the reload trigger in the Python node and re-run the graph.
- [x] Each sample line now extends asymmetrically from the alignment
      crossing: more reach on the deck-far side (right of alignment
      for `+5` ft offset), less on the alignment-near side. The
      sample line endpoints land flush with the deck edges
      (+ 1 ft overhang each side); the alignment-crossing station
      grip remains at the alignment intersection.
- [x] Visually confirm the sample line endpoints coincide with the
      `BRIDGE-EDGE-L` and `BRIDGE-EDGE-R` polylines (offset by the
      1 ft along-bearing overhang) at each support.

### Phase 1 edge-of-deck and bridge-CL polyline verification — VERIFIED
- [x] Bump the reload trigger (committed file is at v10) and rerun
      the graph
- [x] Watch node now contains an additional summary line:
      `Bridge lines: created N (BRIDGE-EDGE-L, BRIDGE-EDGE-R, ...),
      preserved 0 (—)` on first run
- [x] A new layer `BRIDGE-NOPLOT` is added to the Layer Properties
      Manager, with **Plot = No** and **Lock = Yes** (magenta color
      by default — adjust in your project template if desired)
- [x] In ModelSpace, two AutoCAD Polylines exist on `BRIDGE-NOPLOT`:
      one along the left edge of deck, one along the right edge.
      They span bearing-line-to-bearing-line and are snappable for
      DIMLINEAR / DIMRADIUS / DIMANGULAR.
- [x] If your local params have `deck_cl_offset_from_alignment` set
      to a non-zero scalar or array form, a third polyline
      `BRIDGE-CL` is created along the deck centerline. With the
      constant `0.0` default, no `BRIDGE-CL` polyline is created
      (the roadway alignment already runs along the deck CL).
- [x] `XDLIST` on one of the bridge polylines shows
      `BRIDGE_MODELER` xdata with payload like
      `{"bridge_line":"BRIDGE-EDGE-L"}` — that's the tag the tool
      uses for idempotent find-or-create on subsequent runs.
- [x] Re-run the graph: summary now shows
      `Bridge lines: created 0 (—), preserved N (...)` — polylines
      are preserved across runs.
- [x] Confirm the layer's Lock attribute prevents accidental edits:
      try to MOVE one of the polylines via standard AutoCAD
      commands; AutoCAD should refuse with "1 was on a locked
      layer".
- [x] Optional: edit `deck_cl_offset_from_alignment` to a non-zero
      value, delete the existing `BRIDGE-EDGE-L`/`-R` polylines so
      they get recreated at the shifted positions, re-run, confirm
      a `BRIDGE-CL` polyline now appears between the two edges.

### Phase 1 girder swept-solid verification — VERIFIED 2026-05-18 (core)
First 3D output of the bridge model. The graph creates one
`Solid3d` per girder, swept along a 3D path from the start bearing to
the end bearing. The cross-section is the AISC I-shape; the web stays
plumb on graded paths because `SweepOptions.Align = NoAlignment` keeps
the pre-oriented profile fixed in world space throughout the sweep.
Solids regenerate every run (no preservation, unlike skeleton
elements) — `purged` in the summary counts entities deleted before
the rebuild.

- [x] Bump the reload trigger in `src/phase1_node.py` and rerun the
      graph.
- [x] Watch node summary now includes a third line:
      `Girders: built N (SPAN-1.G1, SPAN-1.G2, ...); purged M prior
      entities` — `N` matches the `girder_count` from your local
      params, and `M = 0` on the first run after this slice lands
      (any subsequent run shows `M = N`).
- [x] A new layer `BRIDGE-GIRDER` is present in the Layer Properties
      Manager (red by default — adjust in your project template if
      desired).
- [x] In ModelSpace, `N` `Solid3d` entities exist on `BRIDGE-GIRDER`.
      Use `QSELECT` filtered by Object = `3D Solid` and Layer =
      `BRIDGE-GIRDER`.
- [x] **Plan view** (top): each girder runs from its start bearing
      point to its end bearing point on the same in-plan path as
      the sample-line endpoint at each support.
- [x] **Front elevation** (look perpendicular to alignment): girders
      appear as parallelograms — top and bottom edges parallel,
      sloped to match the profile grade; verticals on the left and
      right ends. The top edge of each girder is at the
      `top_of_girder_flange` elevation from the elevation report.
- [x] **Section cut** perpendicular to a girder at midspan (use
      `SECTIONPLANE` then `LIVESECTION`): the cross-section is the
      AISC I-shape with web vertical (plumb), top flange wider than
      web, no twist or banking.
- [x] Cross-section dimensions match the W-shape: top flange width =
      `bf_in / 12` ft (e.g. W36X150: 1.000 ft), depth = `d_in / 12`
      ft (W36X150: 2.992 ft). Measure with `DIST` between flange
      tips, between top of top flange and bottom of bottom flange.
      _(Confirmed 2026-05-18: W36X150 depth = 2.9917 ft.)_

Remaining low-risk checks (file later if regressions appear):
- [ ] `XDLIST` on one girder shows `BRIDGE_MODELER` xdata with payload
      like `{"element":"girder","span_id":"SPAN-1","girder_index":2,
      "girder_shape":"W36X150","id":"SPAN-1.G2"}`.
- [ ] Re-run the graph (no params changes). Summary shows
      `Girders: built N (...); purged N prior entities` —
      confirms the regenerate-each-run policy. Visual result is
      identical to the prior run.
- [ ] **Hidden visual style** (`VSCURRENT → Hidden`): girders render
      with hidden lines suppressed; no Z-fighting or missing faces.
- [ ] Change `superstructures[0].girder_shape` to a different size
      (e.g. W24X62), bump the reload trigger, rerun. Girders rebuild
      with the new cross-section dimensions at the same positions.

### Phase 1 haunch swept-solid verification — VERIFIED 2026-05-18 (core)
The haunch is the concrete pad between the girder top flange and the
deck underside. Phase 1 baseline: 4-vertex trapezoid (flat bottom on
flange, sloped top matching deck-bottom cross-slope), swept with the
same orientation strategy as girders. `BRIDGE-DECK-HAUNCH` layer
(color 51 by default). The hexagonal-with-chamfers variant from the
project memory is deferred to a later slice — visual diff is small at
typical haunch_depth values (~1").

- [x] Bump the reload trigger in `src/phase1_node.py` and rerun the
      graph.
- [x] Watch node summary now includes a fourth line:
      `Haunches: built N (SPAN-1.G1.HAUNCH, SPAN-1.G2.HAUNCH, ...);
      purged M prior entities` — `N` matches `girder_count`.
- [x] The elevation report has two new rightmost columns `hnch_L` and
      `hnch_R` — the haunch height at each flange tip. _(Confirmed on
      D-E alignment with super-elevated deck: ±0.01 ft delta around
      haunch_depth = 0.25, consistent across all 4 girders.)_
- [x] Layer `BRIDGE-DECK-HAUNCH` is present (color 51 by default).
- [x] `N` `Solid3d` entities exist on `BRIDGE-DECK-HAUNCH`, each
      sitting on top of its girder with bottom at the girder top
      flange and top tucked under the deck soffit.
- [x] Haunch tops slope in the same direction as the deck soffit —
      caught a profile-mirror bug (commit 128162f) plus a stale-module
      cache bug (commit 2e69aae) before this verification passed.

Remaining low-risk checks (file later if regressions appear):
- [ ] **Section cut** at midspan perpendicular to a girder: above the
      girder's I-shape, a trapezoid of width `bf` and height ≈
      `haunch_depth` is visible. Its top edge slopes — slightly tilted
      to match the deck cross-slope.
- [ ] Cross-section width at the bottom = top flange width (e.g.
      W36X150 → 1.000 ft). Measure with `DIST` between bottom corners
      of the haunch trapezoid.
- [ ] `XDLIST` on one haunch shows `BRIDGE_MODELER` xdata with payload
      like `{"element":"haunch","span_id":"SPAN-1","girder_index":2,
      "id":"SPAN-1.G2.HAUNCH"}`.
- [ ] Re-run the graph (no params changes). Summary shows
      `Haunches: built N (...); purged N prior entities`.

### Phase 1 deck slab verification
The deck is a `Solid3d` lofted between two cross-sections — one at each
bearing line. Each cross-section is a parallelogram (super-elevated /
non-crown-straddling) or hexagon (crown-straddling, same-sign cross-
slopes). For fanning decks (width changes start → end), the loft handles
the geometry correctly. `BRIDGE-DECK` layer (color 7 by default).

**Reminder:** if `src/phase1_node.py` changed structurally (it did, for
this slice — `_OWN_MODULES` added `decks` and `deck_geometry`), paste
the FULL body from `src/phase1_node.py` into your Dynamo Python node.
Just bumping the trigger inline won't pick up the new module purge list.

- [ ] Update the .dyn's Python node body from `src/phase1_node.py`
      (v20). Re-run the graph.
- [ ] Watch node summary now includes a fifth line:
      `Decks: built N (SPAN-1.DECK, ...); purged M prior entities` —
      `N` matches the number of spans (1 for Phase 1).
- [ ] Layer `BRIDGE-DECK` is present (color 7 by default).
- [ ] A `Solid3d` exists on `BRIDGE-DECK` spanning the bridge length.
- [ ] **Plan view**: the deck slab covers the full bridge footprint
      from start-bearing left edge through end-bearing right edge —
      coincident with the `BRIDGE-EDGE-L` / `BRIDGE-EDGE-R` polylines.
- [ ] **Front elevation** (perpendicular to alignment): the deck top
      slopes with the profile + cross-slope, parallel to the girder
      top-flange tilt. Deck thickness = `deck_depth` (e.g. 0.667 ft
      for the committed example).
- [ ] **Section cut** at midspan: deck cross-section shows the
      expected shape — parallelogram for super-elevated decks like
      Erik's D-E test, or peaked hexagon for crowned roadways.
- [ ] The deck soffit (bottom face) touches the top of each haunch
      cleanly — no Z-fight or gap.
- [ ] `XDLIST` on the deck shows `BRIDGE_MODELER` xdata with payload
      like `{"element":"deck","span_id":"SPAN-1","id":"SPAN-1.DECK"}`.
- [ ] Re-run the graph (no params changes). Summary shows
      `Decks: built N (...); purged N prior entities` — regenerate
      contract holds.

## From session: 2026-05-19 — haunch boolean-trim refactor + Phase 2 scope

The haunch model was rewritten from a trapezoidal swept solid to a
**rectangular over-tall box + boolean-subtract by the deck**. The change
forces the haunch top to coincide with the deck soffit exactly (vs. the
~0.09% slope artifact the trapezoidal sweep had in alignment-perpendicular
sections under fanning skewed bridges). Reload trigger is at v25.

- [ ] On Windows, `git pull` and update the .dyn's Python node body to
      v25 (no `_OWN_MODULES` changes since v23, so bumping the trigger
      inline is fine if you prefer that).
- [ ] Re-run the graph against `test/params.phase1.local.json` (the
      D-E asymmetric-skew test). Watch node summary should still show
      `Haunches: built 4 (...); purged 4 prior entities` with no
      errors.
- [ ] In 3D view: haunches should still appear on top of girders,
      with the same overall geometry as v24. Visual diff against v24
      should be small — only the top surfaces change.
- [ ] **Section cut perpendicular to the alignment** near each end of
      the bridge. Slope between the two visible top corners of one
      haunch should read **2.0%** (or within ~0.008% — the projection
      residue from the small fan angle). This is the test that
      previously gave 2.09% / 1.9% and is the main thing the refactor
      is supposed to fix.
- [ ] Confirm no gap or Z-fight between the haunch tops and the deck
      soffit. The haunch top should now lie on the deck soffit
      surface for every (X, Y) in the haunch's plan footprint.

If the v25 verification surfaces anything unexpected, the prior
implementation lives at git tag-or-commit `242082f` (commit before
the haunch refactor).

## Operational notes for future runs

- **`CTRL-S` the DWG** immediately after a successful Dynamo run.
  Civil 3D's interaction with Dynamo-created database objects has been
  observed to be undo-fragile (a `CTRL-Z` against a bridge solid can
  crash Civil 3D). Rely on the re-run contract — re-running purges
  prior `BRIDGE-*` objects and regenerates — instead of `CTRL-Z`.
- After `git pull`, bump the `vN` number in the Python node's
  `print("[node] reload trigger vN")` line and click Run. Dynamo
  caches by node-body content, so a no-op text change is required to
  force the node to re-execute and pick up `.py` edits.
