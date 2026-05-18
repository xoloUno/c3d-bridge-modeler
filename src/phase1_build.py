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
                                 ├─▶ bridge_lines.ensure_phase1_bridge_lines()
                                 │         (BRIDGE-EDGE-L, BRIDGE-EDGE-R, and
                                 │          BRIDGE-CL when deck CL ≠ alignment;
                                 │          polylines on BRIDGE-NOPLOT layer)
                                 ├─▶ girders.ensure_phase1_girders()
                                 │         (steel girder swept solids on
                                 │          BRIDGE-GIRDER; regenerated each run)
                                 ▼
                  format_text_report(...)
                                 ▼
                  Watch node summary string

Skeleton elements (sample lines, sub-alignments, edge / CL polylines)
are created on first run and preserved on subsequent runs — designers
can move them between runs and the tool reads positions back. Solid
geometry (girders so far; deck + haunches + substructure to follow) is
regenerated from JSON each run.
"""
from __future__ import annotations

import traceback

import phase1_params
import phase1_compute
import aisc
import c3d_doc
import alignment as al
import skeleton
import bridge_lines
import girders


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
    sub_alignment_summary = ""
    girder_summary = ""
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
            print("[phase1_build] ensuring edge-of-deck and bridge-CL polylines")
            bl = bridge_lines.ensure_phase1_bridge_lines(
                tr=tr,
                db=db,
                alignment_obj=alignment_obj,
                params=params,
                compute_result=result,
            )
            sub_alignment_summary = (
                f"Bridge lines: created {len(bl['created'])} "
                f"({', '.join(name for name, _ in bl['created']) or '—'}), "
                f"preserved {len(bl['preserved'])} "
                f"({', '.join(name for name, _ in bl['preserved']) or '—'})"
            )
            print(f"[phase1_build] {sub_alignment_summary}")

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

            tr.Commit()

    report = phase1_compute.format_text_report(result)
    # Mirror to console so the full table is copyable from the Background
    # Preview Console — Watch node display can be hard to select from.
    print("[phase1_build] elevation report:")
    for line in report.splitlines():
        print(f"[phase1_build] {line}")
    return (
        f"{skeleton_summary}\n{sub_alignment_summary}\n{girder_summary}\n\n{report}"
    )
