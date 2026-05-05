Quick session orientation for c3d-bridge-modeler — run at the start of every session.

This is a Dynamo-for-Civil-3D project authored in Python (PythonNet inside Dynamo
Python nodes). The deliverable is a `.dyn` graph plus supporting `.py` scripts —
not a build artifact. Most of the "running it" happens inside Civil 3D 2026+ on
Windows; Claude Code can read, edit, and reason about source, but cannot execute
the graph against Civil 3D from the macOS dev environment.

Steps:
1. Run `git branch --show-current` and `git status --short` — current branch +
   dirty state
2. Run `git log --oneline -5` — recent commits on the current branch
3. Run `git rev-list --left-right --count origin/main...HEAD 2>/dev/null` to
   show ahead/behind state vs. `origin/main`
4. Check open PRs: `gh pr list --state open --limit 10` (if `gh` is available)
5. Read the **`## Current Phase`** section of `CLAUDE.md` and quote the active
   phase. Phases are defined in `scope.md` (Phase 0 → POC, Phase 1 → first
   parametric pier, etc.) — `CLAUDE.md` tracks which one is in flight.
6. Surface project-structure progress: report which of `src/`, `data/`, `test/`
   already exist (`CLAUDE.md` documents these as the target layout). If a
   directory is missing, it's expected — note it without flagging.
7. If `MANUAL-TASKS.md` exists with unchecked items (`- [ ]`), list them and
   ask whether any have been completed. Civil-3D-side verification (xref a
   bridge drawing into a sheet, confirm Hidden visual style display in a
   viewport, run the graph against real data shortcuts) is the canonical
   manual-task category here — those steps cannot be performed from this
   environment.

Present as a concise briefing — not a wall of text:

```
## c3d-bridge-modeler Session Briefing

**Branch:** <branch> | **vs origin/main:** <N ahead, M behind>
**Current phase:** <quote from CLAUDE.md `## Current Phase`>
**Project layout:** src/ <yes|missing> · data/ <yes|missing> · test/ <yes|missing>

### Recent commits
<git log --oneline -5 output>

### Open PRs
- #<N> <title> — <branch>

### Manual tasks pending (Civil 3D side)
- [ ] <unchecked item from MANUAL-TASKS.md>
(or "None" if file is absent or fully checked)

### Flags
- ⚠️ <uncommitted changes, ahead-of-origin without push, anything unusual>
- ✓ Clean — no flags <if nothing to report>
```

After presenting, ask: "What would you like to work on?"

## Things this command intentionally does NOT do

- It does not check CI. There are no CI workflows in this repo yet — Dynamo
  graphs aren't unit-testable in the conventional sense, and the Civil 3D
  runtime is Windows-only. If a CI strategy is added later (e.g. linting the
  Python nodes' extracted source), update this command then.
- It does not check Dependabot. There's no package manifest yet.
- It does not assume `WORKLOG.md` or `release-notes-draft.md` exist —
  this project hasn't reached a release/version cadence and may never need
  one in its current form (the deliverable is a Dynamo graph).
