# Tests

Pure-logic tests run on macOS; Civil-3D-API modules (`c3d_doc.py`,
`alignment.py`, `layers.py`, `solids.py`, `xdata.py`, `purge.py`) cannot be
imported off Windows and are not covered here. They are exercised manually
via the checklist in `MANUAL-TASKS.md`.

## Run

```
pip install pytest
pytest test/
```

## Files

- `test_params.py` — covers `src/params.py` parsing and validation.
- `params.phase0.json` — sample parameter file used by both the unit tests
  and the Dynamo graph. The committed alignment/profile/surface names are
  placeholders — edit them locally to match your reference Civil 3D
  drawing's data-shortcut names before running `phase0_bridge.dyn`. Do not
  commit those edits unless your team standardizes on the same names.
