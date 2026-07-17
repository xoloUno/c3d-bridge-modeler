"""Reference body for the Dynamo Python node in `bridge_wizard.dyn`.

This file is the canonical, version-controlled source for what goes inside
the .dyn's Python node. The committed graph `src/bridge_wizard.dyn` embeds
this body (docstring stripped, CRLF line endings) and is the Dynamo
Player-ready tool UI: the Directory/File inputs are marked "Is Input" and
the report Watch node "Is Output". When editing this file, re-embed the
body in the graph — either paste it into the Python node in Dynamo, or
regenerate the `Code` field so the two stay byte-identical. (The graph was
fabricated from the known-good `phase0_bridge.dyn` serialization rather
than authored in Dynamo — see MANUAL-TASKS.md for its verification
checklist; if Dynamo rewrites the file on save, commit Dynamo's version.)

Dynamo node inputs (in order):
    IN[0]: repo root path  (Directory Path node pointed at this repository)
    IN[1]: params JSON path (File Path node pointed at e.g.
           test/params.phase1.example.json or test/params.phase1.local.json)

Dynamo node output:
    OUT: build summary + elevation report string from `phase1_build.main`,
         wired to a Watch node (the Player output). The run creates the
         skeleton (sample lines, deck plan polygon) and regenerates the
         solids (girders, haunches, deck slab).
"""
import sys
import os

# Reload trigger — bump this number after `git pull` to force Dynamo to
# treat the node as dirty and re-execute (Dynamo caches by node-body
# content, so a no-op text change is enough). This is the only edit you
# typically need to make to the node body itself; everything else lives
# in the imported `src/*.py` files and is reloaded via the sys.modules
# purge below.
print("[phase1_node] reload trigger v28")

repo_root = IN[0]                                               # noqa: F821
params_path = IN[1]                                             # noqa: F821

src_path = os.path.join(repo_root, "src")

# Defensive: sys.path persists across Dynamo graph runs. If the user
# previously pointed `repo_root` at a different clone (e.g. an old
# OneDrive-backed working copy), THAT path is still in sys.path and
# can shadow our new clone for some imports. Strip any stale
# c3d-bridge-modeler entries before inserting the current one.
sys.path[:] = [p for p in sys.path if "c3d-bridge-modeler" not in p]
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
    "bridge_lines",
    "deck_polygon",
    "deck_plan",
    "girders",
    "girder_geometry",
    "haunches",
    "haunch_geometry",
    "decks",
    "deck_geometry",
    "layers",
    "xdata",
    "c3d_doc",
    "alignment",
)
for _name in _OWN_MODULES:
    if _name in sys.modules:
        del sys.modules[_name]

import phase1_build
OUT = phase1_build.main(repo_root, params_path)                 # noqa: F821
