# c3d-bridge-modeler command profile (local escape hatch)

This repo is a kind-of-one — the only Dynamo-for-Civil-3D project, so no pack applies and there
is **no `command-profile.md`** (the pack layer) for it. The universal `/status` and `/wrapup`
skeletons load this file at runtime and fold its sections in. It carries this project's own
judgment: it's a `.dyn` graph plus PythonNet node scripts whose truth lives in Civil 3D 2026+ at
runtime on Windows — Claude Code can read, edit, and reason about the source from macOS, but
cannot execute the graph against Civil 3D. There is no build, no lint, and no test runner today.

## /status

Fold these into the briefing after the universal git steps:

- **Current phase.** Read the **`## Current Phase`** section of `CLAUDE.md` and quote the active
  phase as a `**Current phase:** <…>` headline line. (Phases are defined in the repo-root
  `scope.md` — Phase 0 → POC, Phase 1 → first parametric superstructure, etc.; `CLAUDE.md` tracks
  which one is in flight. The universal skeleton's own "Current State" read finds no such heading
  here and correctly skips — this section is what surfaces project state instead.)
- **Project layout.** Report which of `src/`, `data/`, `test/` already exist as a
  `**Project layout:** src/ <yes|missing> · data/ <yes|missing> · test/ <yes|missing>` line
  (`CLAUDE.md` documents these as the target layout). A missing directory is *expected* — note
  it without raising a flag.
- **Manual tasks (Civil-3D framing).** The universal step already lists unchecked
  `MANUAL-TASKS.md` items. Here the canonical manual-task category is **Civil-3D-side
  verification** — xref a bridge drawing into a sheet, confirm Hidden visual style display in a
  viewport, run the graph against real data shortcuts — none of which can be done from this macOS
  environment. Present pending items under a "Manual tasks pending (Civil 3D side)" heading.

**This command intentionally does NOT** (noted so the absence reads as deliberate, not drift):

- **No CI check.** There are no CI workflows in this repo — Dynamo graphs aren't unit-testable in
  the conventional sense and the Civil 3D runtime is Windows-only. (If a CI strategy is added
  later — e.g. linting the Python nodes' extracted source — wire it in then.)
- **No Dependabot check.** There is no package manifest to bump.
- It assumes neither `WORKLOG.md` nor `release-notes-draft.md` exists — this project hasn't
  reached a release/version cadence and may never need one in its current form (the deliverable
  is a Dynamo graph). The universal skeleton's "if present" guards already skip these.

## /wrapup

Slot these into the universal flow at the stage named — not in list order.

**Record mutations (stage 3 — before staging):**

- **Update `CLAUDE.md`** if the session advanced project state:
  - **`## Current Phase`** is the closest thing this project has to a "last completed / next up"
    field — update it when a phase milestone lands or the next session's focus shifts.
  - **`## File Structure`** — update if `src/`, `data/`, or `test/` gained real content.
  - **`## Key Architecture Decisions`** — touch only when an architectural choice was actually
    made or revised this session.
- **Update the repo-root `scope.md`** when the session changes the plan itself — a phase was
  completed, a parameter definition was revised, a deliverable was reframed. Routine
  implementation work that merely *follows* the plan does not need a `scope.md` edit. (The file
  is `scope.md` at the repo root, not `docs/scope.md`.)
- **Manual-task handoff.** If the session produced anything that needs Civil 3D 2026+ on a
  Windows workstation to verify (run the Dynamo graph, check xref display in a sheet, validate
  Hidden visual style in a viewport, inspect xdata via `LIST` on a generated solid), append the
  steps to `MANUAL-TASKS.md` rather than burying them in chat. Format:
  ```markdown
  ## From session: YYYY-MM-DD — <focus>

  - [ ] In Civil 3D, open <drawing>, run <graph>, verify <expected outcome>
  - [ ] Xref <bridge.dwg> into <sheet.dwg>, confirm Hidden style displays the bridge correctly
  ```

**Commit (stage 6):**

- Scopes that fit this project: `dynamo` (graph changes), `python` (node scripts), `params`
  (JSON parameter format), `data` (AISC tables), `docs`, `scope`, `claude` (`CLAUDE.md` / `.claude/`
  updates).
- **`.dyn` files are merge-hostile** — JSON under the hood, but large and diff-noisy. Keep
  graph-only commits separate from Python-script-only commits when feasible, so future blame and
  revert stay surgical. (A graph-side change and an unrelated docs polish should be two commits,
  not one.)

**Validation gates (stage 4):** none today — no build, no lint, no test runner. The universal
gate step finds no `test_command` and no pack, and correctly no-ops. If a lightweight Python lint
(`ruff`, `pyflakes`) or a graph-extraction script is added later, run it here before staging.

**Steps that no-op here:** no `[skip ci]` (no CI lanes), no release-notes draft, no
prose-humanizer pass, no version-file sync — the deliverable is a Dynamo graph verified manually
in Civil 3D, so this project's session record is its commit history plus `MANUAL-TASKS.md`.
