"""Phase 1 orchestrator: bridge the pure-math layer to the live Civil 3D drawing.

This is the entry point called by the Dynamo Python node (see
`src/phase1_node.py` for the node body).

For this slice the orchestrator stops at the elevation-table report —
no geometry is generated yet. That keeps the Phase 1 pure-math layer
testable end-to-end against real C3D alignment + profile data, before
sample lines, sub-alignments, and swept solids start landing in
follow-up slices.

Pipeline:
    JSON params  ──▶ phase1_params.load()
                                 │
       AISC table ──▶ aisc.load()│
                                 ▼
    C3D alignment + profile  ──▶ profile_elevation_at lookup
                                 ▼
                  phase1_compute.compute()
                                 ▼
                  format_text_report(...)
                                 ▼
                  Watch node summary string
"""
from __future__ import annotations

import traceback

import phase1_params
import phase1_compute
import aisc
import c3d_doc
import alignment as al


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

            tr.Commit()  # read-only, but commit + dispose is the canonical pattern

    report = phase1_compute.format_text_report(result)
    # Mirror to console so the full table is copyable from the Background
    # Preview Console — Watch node display can be hard to select from.
    print("[phase1_build] elevation report:")
    for line in report.splitlines():
        print(f"[phase1_build] {line}")
    return report
