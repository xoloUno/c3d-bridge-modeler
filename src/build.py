"""Phase 0 orchestrator: load params, generate deck + piers, tag with xdata.

This is the entry point called by the Dynamo Python node (see
`src/phase0_node.py` for the node body).
"""
from __future__ import annotations

import traceback

import params
import c3d_doc
import alignment as al
import layers
import solids
import xdata
import purge


XDATA_APP = "BRIDGE_MODELER"

LAYER_DECK = "BRIDGE-DECK"
LAYER_PIER = "BRIDGE-PIER-COL"

_COLOR_DECK = 7
_COLOR_PIER = 4


def main(repo_root: str, params_path: str) -> str:
    """Phase 0 orchestrator wrapped in a single try/except.

    Any exception raised inside the transaction is caught, formatted, and
    returned as the function's result. Without this wrapper, exceptions
    propagate up through pythonnet's IDisposable cleanup paths (Transaction,
    DocumentLock) — those wrappers map the Python `__exit__(exc_type,
    exc_val, tb)` signature to `OnExit(int)` on the underlying .NET types,
    fail with a TypeError during unwinding, and mask the real error.

    Returning the error as a string lets the Watch node display it instead
    of dropping it on the floor.
    """
    try:
        return _run(params_path)
    except Exception as exc:  # noqa: BLE001
        err = (
            f"ERROR: {type(exc).__name__}: {exc}\n"
            f"--- traceback ---\n{traceback.format_exc()}"
        )
        # Mirror the error to the console so it's copyable from the
        # Background Preview Console; the Watch node display isn't
        # reliably text-selectable.
        print("[build] FAILED:")
        for line in err.splitlines():
            print(f"[build] {line}")
        return err


def _run(params_path: str) -> str:
    print("[build] step: load params")
    p = params.load(params_path)

    print("[build] step: get active database")
    db = c3d_doc.active_db()

    # An explicit document write lock IS required around any
    # `OpenMode.ForWrite` GetObject call from a Dynamo Python node;
    # without it AutoCAD raises `eLockViolation`. The earlier removal of
    # LockDocument was incorrect — happy-path runs only worked when the
    # drawing already had a warm lock from prior interactive editing.
    print("[build] step: lock document")
    with c3d_doc.locked_document():
        print("[build] step: start transaction")
        with c3d_doc.start_transaction() as tr:
            print("[build] step: purge BRIDGE-* objects")
            erased = purge.purge_bridge_objects(tr, db)
            print(f"[build] step: purged {erased}")

            print("[build] step: ensure deck layer")
            layers.ensure_layer(tr, db, LAYER_DECK, color=_COLOR_DECK)
            print("[build] step: ensure pier layer")
            layers.ensure_layer(tr, db, LAYER_PIER, color=_COLOR_PIER)
            print("[build] step: ensure regapp")
            xdata.ensure_regapp(tr, db, XDATA_APP)

            print(f"[build] step: find alignment '{p.alignment_name}'")
            alignment_obj = al.find_alignment(tr, p.alignment_name)
            print(f"[build] step: find profile '{p.profile_name}'")
            profile_obj = al.find_profile(tr, alignment_obj, p.profile_name)

            print("[build] step: create deck solid")
            deck_oid = _create_deck(tr, db, alignment_obj, profile_obj, p)
            print("[build] step: write deck xdata")
            xdata.write(tr, deck_oid, XDATA_APP, {
                "phase": 0, "element": "DECK", "id": "DECK-1",
            })

            for pier in p.piers:
                print(f"[build] step: create pier '{pier.id}'")
                pier_oid = _create_pier(tr, db, alignment_obj, profile_obj, pier, p)
                print(f"[build] step: write pier xdata '{pier.id}'")
                xdata.write(tr, pier_oid, XDATA_APP, {
                    "phase": 0, "element": "PIER", "id": pier.id,
                })

            print("[build] step: commit transaction")
            tr.Commit()
            print("[build] step: committed")

    return (
        f"Erased {erased} prior BRIDGE-* objects. "
        f"Created 1 deck + {len(p.piers)} piers on BRIDGE-* layers."
    )


def _create_deck(tr, db, alignment_obj, profile_obj, p):
    mid = (p.begin_station + p.end_station) / 2.0
    cx, cy = al.point_at_station(alignment_obj, mid, 0.0)
    bearing = al.direction_at_station(alignment_obj, mid)
    top_z = al.elevation_at_station(profile_obj, mid)
    cz = top_z - p.deck_depth / 2.0
    length = p.end_station - p.begin_station

    box = solids.create_box(
        center=(cx, cy, cz),
        length=length,
        width=p.deck_width,
        height=p.deck_depth,
        rotation_z_rad=bearing,
    )
    return solids.append_to_modelspace(tr, db, box, LAYER_DECK)


def _create_pier(tr, db, alignment_obj, profile_obj, pier, p):
    cx, cy = al.point_at_station(alignment_obj, pier.station, 0.0)
    bearing = al.direction_at_station(alignment_obj, pier.station)
    top_of_pier = al.elevation_at_station(profile_obj, pier.station) - p.deck_depth
    cz = top_of_pier - pier.height / 2.0

    box = solids.create_box(
        center=(cx, cy, cz),
        length=pier.length,
        width=pier.width,
        height=pier.height,
        rotation_z_rad=bearing,
    )
    return solids.append_to_modelspace(tr, db, box, LAYER_PIER)
