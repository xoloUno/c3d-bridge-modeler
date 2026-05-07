"""Reference body for the Dynamo Python node in `phase1_bridge.dyn`.

This file is the canonical, version-controlled source for what goes inside
the .dyn's Python node. Copy its body into the Python node when building or
rebuilding the graph in Dynamo. The .dyn itself is created in Civil 3D
(see `MANUAL-TASKS.md`) — fabricating valid Dynamo JSON outside of Dynamo
is brittle across versions.

Dynamo node inputs (in order):
    IN[0]: repo root path  (File Path node pointed at this repository)
    IN[1]: params JSON path (File Path node pointed at e.g.
           test/params.phase1.example.json or test/params.local.json)

Dynamo node output:
    OUT: elevation-report string from `phase1_build.main`, wired to a
         Watch node. For this slice the report is purely informational
         (no geometry is generated yet); follow-up slices will add
         sample lines, sub-alignments, and swept solids.
"""
import sys
import os

# Reload trigger — bump this number after `git pull` to force Dynamo to
# treat the node as dirty and re-execute (Dynamo caches by node-body
# content, so a no-op text change is enough). This is the only edit you
# typically need to make to the node body itself; everything else lives
# in the imported `src/*.py` files and is reloaded via the sys.modules
# purge below.
print("[phase1_node] reload trigger v8")

repo_root = IN[0]                                               # noqa: F821
params_path = IN[1]                                             # noqa: F821

src_path = os.path.join(repo_root, "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

# Drop every Phase 1 src/ module from sys.modules so the next import is
# fresh — `importlib.reload` only refreshes a single module, leaving its
# already-imported dependencies stale.
_OWN_MODULES = (
    "phase1_build",
    "phase1_compute",
    "phase1_params",
    "station_profile",
    "elevation",
    "units",
    "aisc",
    "skeleton",
    "sub_alignment",
    "layers",
    "c3d_doc",
    "alignment",
)
for _name in _OWN_MODULES:
    if _name in sys.modules:
        del sys.modules[_name]

import phase1_build
OUT = phase1_build.main(repo_root, params_path)                 # noqa: F821
