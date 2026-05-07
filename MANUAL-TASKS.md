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

### AISC W-shape table spot-check
- [ ] Open `data/aisc_w_shapes.json` and verify a sample of shape
      dimensions against AISC Steel Construction Manual (v15 or v16).
      Suggested sample (covers light, medium, and heavy bridge girder
      sizes): W14X22, W18X35, W24X62, W30X90, W36X150, W40X167, W44X230.
      Check `d`, `bf`, `tf`, `tw`, and `lb_per_ft` for each. Values
      should be in inches (decimal) and lb/ft. Report any discrepancies
      so we can correct the source data.

### Phase 1 build verification — elevation report (no geometry yet)
- [ ] Copy `test/params.phase1.example.json` to
      `test/params.phase1.local.json` and edit it with real alignment,
      profile, EG, FG names from your reference drawing's data
      shortcuts. Adjust `begin_station`, `end_station`, `supports[].station`,
      and `supports[].bearing_offsets` to match the project. Confirm at
      least one `superstructures[].girder_shape` is a real AISC W-shape
      (e.g. W36X150) so AISC validation passes.
- [ ] In Dynamo for Civil 3D, build `src/phase1_bridge.dyn`:
      - `Directory Path` input → repo root
      - `File Path` input → `test/params.phase1.local.json`
      - Python Script node; paste contents of `src/phase1_node.py`;
        wire `IN[0]` ← repo root, `IN[1]` ← params path
      - `Watch` node on the Python node's output
      - Save the graph as `src/phase1_bridge.dyn`
      - Python node engine MUST be set to CPython 3 (PythonNet 3)
- [ ] Open the reference Civil 3D drawing with data shortcuts attached
- [ ] Run the graph; `Watch` node displays the elevation report
      starting with `== SPAN-1 (... → ...) ==` and listing per-girder
      `top_deck`, `top_flg`, `bot_grdr`, `brg_seat` at start and end
      bearings
- [ ] Cross-check one girder's elevations against a manual calculation
      (e.g. interior girder G2 at the start bearing): `top_of_deck =
      profile_elev + deck_profile_offset + cross_slope/100 *
      |girder_offset - crown_offset|`. Match within 0.01 ft.
- [ ] Confirm no `BRIDGE-*` layers or geometry are created — this
      slice is read-only and informational

### Phase 1 schema migration (skew + station-varying offsets)
- [ ] Update `test/params.phase1.local.json` to the new schema:
      - Add `perpendicular_deck_width_start` and `perpendicular_deck_width_end`
        (the engineer's intended perpendicular deck width).
      - Set EXACTLY ONE of (`left_edge_to_G1_*`, `Gn_to_right_edge_*`) per
        side; the other must be `null` (will be derived from
        `perpendicular_deck_width / cos(skew)` and the spacings).
      - Add `deck_cl_offset_from_alignment` (scalar, e.g. `0.0`, or array
        of `{station, value}` for station-varying).
      - Confirm `crown_offset` is scalar OR array form (it now accepts
        both).
- [ ] Re-run the graph; for skewed supports, the elevation-report numbers
      will shift slightly vs. the previous run because spacings are now
      correctly interpreted as along-bearing measurements (perpendicular
      offsets are derived via `× cos(skew)`).
- [ ] Sample-line lengths now equal `perpendicular_deck_width / cos(skew)`
      + 2 ft overhang. For the 22 ft perpendicular deck at 10° skew, sample
      line should be ~24.34 ft (was 24.0 ft when spacings were treated as
      perpendicular).

### Phase 1 sample-line skeleton verification
- [ ] Bump the reload trigger in the Python node body (already at v2
      in committed `src/phase1_node.py`) and rerun the graph
- [ ] Watch node summary first line reads
      `Skeleton: created N sample line(s), preserved 0 existing`
      where N matches the number of supports in your local params
- [ ] In Civil 3D, `LIST` or Properties panel shows a Sample Line
      Group named `BRIDGE-SUPPORTS` parented to your bridge alignment
- [ ] Each sample line is named after its `support_id` (e.g. `ABUT-A`,
      `ABUT-B`); positions match support stations on the alignment
- [ ] Sample lines are skewed by `support.skew_angle` from
      perpendicular (verify visually if non-zero skew; otherwise the
      lines are square to the alignment)
- [ ] Sample line length = deck width + 2 ft (1 ft overhang on each
      side); for a 22 ft deck the sample lines are 24 ft total
- [ ] Re-run the graph: summary now reads
      `Skeleton: created 0 sample line(s), preserved N existing` —
      confirms the skeleton is preserved across runs (designer edits
      will not be overwritten)
- [ ] Optional: manually move one sample line in C3D (drag a station
      grip), rerun, confirm the moved line is preserved in place

### Phase 1 sample-line asymmetric extension for offset deck CL
- [ ] In `test/params.phase1.local.json`, set
      `deck_cl_offset_from_alignment` to a non-zero scalar (e.g.
      `5.0`).
- [ ] In Civil 3D, manually delete the existing `BRIDGE-SUPPORTS`
      sample lines (and the `BRIDGE-EDGE-L`/`-R`/`-CL` polylines so
      they regenerate at the shifted positions). The find-by-name
      logic preserves existing sample lines across runs, so the
      manual delete is required to pick up the new asymmetric
      formula.
- [ ] Bump the reload trigger in the Python node and re-run the graph.
- [ ] Each sample line now extends asymmetrically from the alignment
      crossing: more reach on the deck-far side (right of alignment
      for `+5` ft offset), less on the alignment-near side. The
      sample line endpoints land flush with the deck edges
      (+ 1 ft overhang each side); the alignment-crossing station
      grip remains at the alignment intersection.
- [ ] Visually confirm the sample line endpoints coincide with the
      `BRIDGE-EDGE-L` and `BRIDGE-EDGE-R` polylines (offset by the
      1 ft along-bearing overhang) at each support.

### Phase 1 edge-of-deck and bridge-CL polyline verification
- [ ] Bump the reload trigger (committed file is at v10) and rerun
      the graph
- [ ] Watch node now contains an additional summary line:
      `Bridge lines: created N (BRIDGE-EDGE-L, BRIDGE-EDGE-R, ...),
      preserved 0 (—)` on first run
- [ ] A new layer `BRIDGE-NOPLOT` is added to the Layer Properties
      Manager, with **Plot = No** and **Lock = Yes** (magenta color
      by default — adjust in your project template if desired)
- [ ] In ModelSpace, two AutoCAD Polylines exist on `BRIDGE-NOPLOT`:
      one along the left edge of deck, one along the right edge.
      They span bearing-line-to-bearing-line and are snappable for
      DIMLINEAR / DIMRADIUS / DIMANGULAR.
- [ ] If your local params have `deck_cl_offset_from_alignment` set
      to a non-zero scalar or array form, a third polyline
      `BRIDGE-CL` is created along the deck centerline. With the
      constant `0.0` default, no `BRIDGE-CL` polyline is created
      (the roadway alignment already runs along the deck CL).
- [ ] `XDLIST` on one of the bridge polylines shows
      `BRIDGE_MODELER` xdata with payload like
      `{"bridge_line":"BRIDGE-EDGE-L"}` — that's the tag the tool
      uses for idempotent find-or-create on subsequent runs.
- [ ] Re-run the graph: summary now shows
      `Bridge lines: created 0 (—), preserved N (...)` — polylines
      are preserved across runs.
- [ ] Confirm the layer's Lock attribute prevents accidental edits:
      try to MOVE one of the polylines via standard AutoCAD
      commands; AutoCAD should refuse with "1 was on a locked
      layer".
- [ ] Optional: edit `deck_cl_offset_from_alignment` to a non-zero
      value, delete the existing `BRIDGE-EDGE-L`/`-R` polylines so
      they get recreated at the shifted positions, re-run, confirm
      a `BRIDGE-CL` polyline now appears between the two edges.

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
