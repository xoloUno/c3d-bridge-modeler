"""Reference body for the Dynamo Python node in `phase0_bridge.dyn`.

This file is the canonical, version-controlled source for what goes inside
the .dyn's Python node. Copy its body into the Python node when building or
rebuilding the graph in Dynamo. The .dyn itself is created in Civil 3D
(see `MANUAL-TASKS.md`) — fabricating valid Dynamo JSON outside of Dynamo
is brittle across versions.

Dynamo node inputs (in order):
    IN[0]: repo root path  (File Path node pointed at this repository)
    IN[1]: params JSON path (File Path node pointed at e.g. test/params.phase0.json)

Dynamo node output:
    OUT: summary string from `build.main`, wired to a Watch node.
"""
import sys
import os

repo_root = IN[0]                                               # noqa: F821
params_path = IN[1]                                             # noqa: F821

src_path = os.path.join(repo_root, "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

# During dev we want every node run to pick up edits across the whole
# src/ tree. `importlib.reload(build)` only refreshes `build` itself —
# its already-imported dependencies (`purge`, `solids`, etc.) keep their
# stale module objects, and `build.purge` still references the old one.
# Drop every src/ module from sys.modules so the next import is fresh.
_OWN_MODULES = (
    "build", "params", "c3d_doc", "alignment",
    "layers", "solids", "xdata", "purge",
)
for _name in _OWN_MODULES:
    if _name in sys.modules:
        del sys.modules[_name]

import build
OUT = build.main(repo_root, params_path)                        # noqa: F821
