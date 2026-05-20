"""Phase 1 orchestrator: bridge the pure-math layer to the live Civil 3D drawing.

This is the entry point called by the Dynamo Python node (see
`src/phase1_node.py` for the node body).

Pipeline:
    JSON params  ──▶ phase1_params.load()
                                 │
       AISC table ──▶ aisc.load()│
                                 ▼
    C3D alignment + profile  ──▶ profile_elevation_at lookup
                                 ▼
                  phase1_compute.compute()
                                 ├─▶ skeleton.ensure_support_sample_lines()
                                 │         (BRIDGE-SUPPORTS sample line group)
                                 ├─▶ deck_polygon.ensure_deck_plan_polygon()
                                 │         (closed polyline on BRIDGE-2D-DECK,
                                 │          single source of truth for deck
                                 │          plan footprint; designer-editable,
                                 │          preserved across runs)
                                 ├─▶ girders.ensure_phase1_girders()
                                 │         (steel girder swept solids on
                                 │          BRIDGE-GIRDER; regenerated each run)
                                 ├─▶ haunches.ensure_phase1_haunches()
                                 │         (haunch trapezoid swept solids on
                                 │          BRIDGE-DECK-HAUNCH; regenerated)
                                 ├─▶ decks.ensure_phase1_decks(polygon_vertices)
                                 │         (deck slab built by extruding the
                                 │          BRIDGE-2D-DECK polygon, then
                                 │          intersecting with the fat-deck
                                 │          sweep; regenerated each run)
                                 ▼
                  format_text_report(...)
                                 ▼
                  Watch node summary string

Skeleton elements (sample lines, deck plan polygon) are created on
first run and preserved on subsequent runs — designers can grip-edit
them between runs and the tool reads positions back. Solid geometry
(girders, haunches, deck) is regenerated from params + the live
skeleton each run.

NOTE: `bridge_lines.ensure_phase1_bridge_lines()` (BRIDGE-NOPLOT EDGE-L,
EDGE-R, CL polylines) is no longer called — the BRIDGE-2D-DECK polygon
replaces all three. The `bridge_lines` module is retained in the repo
but unused by this orchestrator. Existing BRIDGE-NOPLOT polylines in
drawings are inert (locked layer, no longer managed).
"""
from __future__ import annotations

import traceback

import phase1_params
import phase1_compute
import aisc
import c3d_doc
import alignment as al
import skeleton
import deck_polygon
import decks
import girders
import haunches


def main(repo_root: str, params_path: str) -> str:
    """Phase 1 orchestrator wrapped in a single try/except.

    See `src/build.py:main` (Phase 0) for the rationale on returning
    error strings instead of letting exceptions propagate through
    pythonnet's IDisposable cleanup paths.
    """
    try:
        return _run(params_path)
    except Exception as exc:  # noqa: BLE001
        err = (
            f"ERROR: {type(exc).__name__}: {exc}\n"
            f"--- traceback ---\n{traceback.format_exc()}"
        )
        print("[phase1_build] FAILED:")
        for line in err.splitlines():
            print(f"[phase1_build] {line}")
        return err


def _run(params_path: str) -> str:
    print(f"[phase1_build] loading params from {params_path}")
    params = phase1_params.load(params_path)

    print("[phase1_build] loading AISC W-shape table")
    aisc_table = aisc.load()

    aisc_errors = phase1_params.validate_against_aisc(params, aisc_table)
    if aisc_errors:
        return "ERROR: AISC validation failed:\n  " + "\n  ".join(aisc_errors)

    skeleton_summary = ""
    polygon_summary = ""
    girder_summary = ""
    haunch_summary = ""
    deck_summary = ""
    with c3d_doc.locked_document():
        with c3d_doc.transaction() as tr:
            print(f"[phase1_build] resolving alignment {params.alignment_name!r}")
            alignment_obj = al.find_alignment(tr, params.alignment_name)
            print(f"[phase1_build] resolving profile {params.profile_name!r}")
            profile_obj = al.find_profile(tr, alignment_obj, params.profile_name)

            def profile_at(station: float) -> float:
                return al.elevation_at_station(profile_obj, station)

            print("[phase1_build] running compute()")
            result = phase1_compute.compute(params, aisc_table, profile_at)

            print("[phase1_build] ensuring sample-line skeleton at supports")
            sk = skeleton.ensure_support_sample_lines(
                tr=tr,
                alignment_obj=alignment_obj,
                supports=params.supports,
                deck_widths_by_support_id=skeleton.deck_widths_by_support_id(result),
                deck_cl_offsets_by_support_id=skeleton.deck_cl_offsets_by_support_id(
                    params, result
                ),
            )
            skeleton_summary = (
                f"Skeleton: created {len(sk['created'])} sample line(s), "
                f"preserved {len(sk['preserved'])} existing"
            )
            print(f"[phase1_build] {skeleton_summary}")

            db = c3d_doc.active_db()
            print("[phase1_build] ensuring deck plan polygon (BRIDGE-2D-DECK)")
            dp_res = deck_polygon.ensure_deck_plan_polygon(
                tr=tr,
                db=db,
                alignment_obj=alignment_obj,
                params=params,
                compute_result=result,
            )
            polygon_vertices = dp_res["vertices"]
            dp_regen_names = [name for name, _oid, _ver in dp_res.get("regenerated", [])]
            polygon_summary = (
                f"Deck polygon: created {len(dp_res['created'])} "
                f"({', '.join(name for name, _ in dp_res['created']) or '—'}), "
                f"preserved {len(dp_res['preserved'])} "
                f"({', '.join(name for name, _ in dp_res['preserved']) or '—'}), "
                f"regenerated {len(dp_regen_names)} "
                f"({', '.join(dp_regen_names) or '—'}), "
                f"vertices={len(polygon_vertices)}"
            )
            print(f"[phase1_build] {polygon_summary}")

            print("[phase1_build] regenerating girder solids")
            gd = girders.ensure_phase1_girders(
                tr=tr,
                db=db,
                alignment_obj=alignment_obj,
                params=params,
                compute_result=result,
                aisc_table=aisc_table,
            )
            girder_summary = (
                f"Girders: built {len(gd['created'])} "
                f"({', '.join(name for name, _ in gd['created']) or '—'}); "
                f"purged {gd['purged']} prior entit{'y' if gd['purged'] == 1 else 'ies'}"
            )
            print(f"[phase1_build] {girder_summary}")

            print("[phase1_build] regenerating haunch solids")
            hn = haunches.ensure_phase1_haunches(
                tr=tr,
                db=db,
                alignment_obj=alignment_obj,
                params=params,
                compute_result=result,
                aisc_table=aisc_table,
                profile_elevation_at=profile_at,
            )
            haunch_summary = (
                f"Haunches: built {len(hn['created'])} "
                f"({', '.join(name for name, _ in hn['created']) or '—'}); "
                f"purged {hn['purged']} prior entit{'y' if hn['purged'] == 1 else 'ies'}"
            )
            print(f"[phase1_build] {haunch_summary}")

            print("[phase1_build] regenerating deck slabs (from polygon)")
            dk = decks.ensure_phase1_decks(
                tr=tr,
                db=db,
                alignment_obj=alignment_obj,
                params=params,
                compute_result=result,
                aisc_table=aisc_table,
                profile_elevation_at=profile_at,
                polygon_vertices=polygon_vertices,
            )
            deck_summary = (
                f"Decks: built {len(dk['created'])} "
                f"({', '.join(name for name, _ in dk['created']) or '—'}); "
                f"purged {dk['purged']} prior entit{'y' if dk['purged'] == 1 else 'ies'}"
            )
            print(f"[phase1_build] {deck_summary}")

            tr.Commit()

    report = phase1_compute.format_text_report(result)
    # Mirror to console so the full table is copyable from the Background
    # Preview Console — Watch node display can be hard to select from.
    print("[phase1_build] elevation report:")
    for line in report.splitlines():
        print(f"[phase1_build] {line}")
    return (
        f"{skeleton_summary}\n{polygon_summary}\n"
        f"{girder_summary}\n{haunch_summary}\n{deck_summary}\n\n{report}"
    )
