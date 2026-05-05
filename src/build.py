"""Phase 0 orchestrator: load params, generate deck + piers, tag with xdata.

This is the entry point called by the Dynamo Python node (see
`src/phase0_node.py` for the node body).
"""
from __future__ import annotations

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
    p = params.load(params_path)

    doc = c3d_doc.active_doc()
    db = c3d_doc.active_db()

    with doc.LockDocument():
        with c3d_doc.start_transaction() as tr:
            erased = purge.purge_bridge_objects(tr, db)
            layers.ensure_layer(tr, db, LAYER_DECK, color=_COLOR_DECK)
            layers.ensure_layer(tr, db, LAYER_PIER, color=_COLOR_PIER)
            xdata.ensure_regapp(tr, db, XDATA_APP)

            alignment_obj = al.find_alignment(tr, p.alignment_name)
            profile_obj = al.find_profile(tr, alignment_obj, p.profile_name)

            deck_oid = _create_deck(tr, db, alignment_obj, profile_obj, p)
            xdata.write(tr, deck_oid, XDATA_APP, {
                "phase": 0, "element": "DECK", "id": "DECK-1",
            })

            for pier in p.piers:
                pier_oid = _create_pier(tr, db, alignment_obj, profile_obj, pier, p)
                xdata.write(tr, pier_oid, XDATA_APP, {
                    "phase": 0, "element": "PIER", "id": pier.id,
                })

            tr.Commit()

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
