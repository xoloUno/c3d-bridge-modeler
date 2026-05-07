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
