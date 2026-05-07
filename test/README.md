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
- `test_units.py` — covers `src/units.py` inch / foot / mm helpers.
- `test_aisc.py` — covers `src/aisc.py` W-shape table loading and lookup.
- `test_elevation.py` — covers `src/elevation.py` bridge elevation chain
  (top of deck → girder → bearing seat → cap → column → footing).
- `params.phase0.json` — committed schema example with placeholder
  alignment / profile / surface names. Used by the unit tests; do not
  edit. New contributors copy this file to create their local config
  (see below).
- `params.local.json` (gitignored) — your project's real config with
  actual data-shortcut names. Point your Dynamo `File Path` node at
  this file. `*.local.json` patterns are gitignored so a `git pull`
  will never overwrite or conflict with your real configuration.

## Setting up a local config

```
cp test/params.phase0.json test/params.local.json
# Edit params.local.json with your real alignment / profile / EG
# surface names, station range, pier stations, etc.
```

In Dynamo, point the params `File Path` node at
`test/params.local.json` instead of `params.phase0.json`. The
in-repo schema file stays untouched and the committed unit tests
keep loading the placeholder version cleanly.
