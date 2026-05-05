# Manual Tasks (Civil 3D side)

These steps require Civil 3D 2026+ on Windows and cannot be performed from
the macOS dev environment. Check items off as they are verified.

## Phase 0 verification

### Setup
- [ ] On Windows, edit `test/params.phase0.json` to use the actual alignment,
      profile, and EG surface names from your reference drawing's data
      shortcuts. Do not commit those edits if your team doesn't share names.
- [ ] In Dynamo for Civil 3D, build `src/phase0_bridge.dyn`:
      - Add a `File Path` input node pointed at the repo root
      - Add a `File Path` input node pointed at `test/params.phase0.json`
      - Add a Python node; paste the contents of `src/phase0_node.py` into
        it; wire `IN[0]` to the repo-root path and `IN[1]` to the params
        path
      - Add a `Watch` node on the Python node's output
      - Save the graph as `src/phase0_bridge.dyn`

### Run + first-pass checks
- [ ] Open the reference Civil 3D drawing with data shortcuts attached
- [ ] Open `src/phase0_bridge.dyn` and run the graph
- [ ] Watch node summary reports `Created 1 deck + 2 piers on BRIDGE-* layers`
- [ ] `BRIDGE-DECK` and `BRIDGE-PIER-COL` layers exist in the layer table
- [ ] ModelSpace contains exactly 3 solids (1 deck box, 2 pier boxes) on
      those layers
- [ ] `XDLIST` on each solid shows `BRIDGE_MODELER` xdata with the expected
      JSON payload (`element`, `id`)

### Display + xref
- [ ] In a viewport, set visual style to **Hidden** — the bridge wireframe
      renders correctly with hidden-line removal
- [ ] In a separate sheet drawing, xref the bridge drawing; set the sheet
      viewport to **Hidden** visual style — confirm the xref displays as
      expected (no missing edges, correct layer visibility)

### Re-run contract
- [ ] Edit `test/params.phase0.json` (e.g., shift a pier station 5 ft);
      re-run the graph
- [ ] Confirm the prior 3 solids were erased and 3 new solids reflect the
      updated parameters
- [ ] Confirm the Watch node summary reports `Erased 3 prior BRIDGE-*
      objects` on the second run
