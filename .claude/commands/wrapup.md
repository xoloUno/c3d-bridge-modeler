End-of-session wrap-up for c3d-bridge-modeler — commit cleanly, push, leave the repo in good shape.

This is a Dynamo-for-Civil-3D project (Python inside Dynamo Python nodes,
`.dyn` graph files, JSON parameter inputs). It does not have a build pipeline
or unit-test suite — the truth lives in Civil 3D 2026+ at runtime, and most
verification happens manually on a Windows workstation. Wrap-up is therefore
lighter than for a typical app: focus on clean commits, accurate phase
tracking in `CLAUDE.md`, and a clear handoff for any Civil-3D-side
verification the next session needs.

Steps:

1. Run `git status` — review staged, unstaged, untracked files.
2. Show the user a concise summary of what changed this session.
3. **Stage selectively** — never `git add .` blindly. Group related changes
   into logical commits if multiple concerns were touched.
4. **Write conventional commit message(s):**
   - Format: `type(scope): short description`
   - Types: `feat`, `fix`, `docs`, `refactor`, `chore`
   - Scopes that fit this project: `dynamo` (graph changes), `python` (node
     scripts), `params` (JSON parameter format), `data` (AISC tables),
     `docs`, `scope`, `claude` (CLAUDE.md / .claude/ updates)
   - Append `Co-Authored-By: Claude <noreply@anthropic.com>`
5. **Update `CLAUDE.md`** if the session advanced the project state:
   - The `## Current Phase` section is the closest thing this project has to
     a "Last completed work / Next up" field. Update it when a phase milestone
     lands or when the next session's focus shifts.
   - Update `## File Structure` if `src/`, `data/`, or `test/` gained
     real content this session.
   - Touch `## Key Architecture Decisions` only when an architectural choice
     was actually made or revised this session.
6. **Update `scope.md`** when the session changes the plan itself — a phase
   was completed, a parameter definition was revised, a deliverable was
   reframed. Routine implementation work that follows the plan does not need
   a `scope.md` edit.
7. **Manual-task handoff.** If this session produced anything that requires
   Civil 3D 2026+ on a Windows workstation to verify (run the Dynamo graph,
   check xref display in a sheet, validate Hidden visual style in a viewport,
   inspect xdata via `LIST` on a generated solid), append the steps to
   `MANUAL-TASKS.md` rather than burying them in chat. Format:
   ```markdown
   ## From session: YYYY-MM-DD — <focus>

   - [ ] In Civil 3D, open <drawing>, run <graph>, verify <expected outcome>
   - [ ] Xref <bridge.dwg> into <sheet.dwg>, confirm Hidden style displays
         the bridge correctly
   ```
8. **Branch routing:**
   - On `main`: do **NOT** push directly. Create a feature branch
     (`feat/<slug>`, `fix/<slug>`, `docs/<slug>`, `chore/<slug>`) from HEAD,
     push it, and open a PR with `gh pr create`. Report the PR URL.
   - On a feature branch: push with `git push -u origin <branch>`. If no PR
     exists yet, offer to create one.
   - Exception: routine doc-only edits when the user has explicitly authorized
     direct push for the session. "Wrap up" alone in chat is not authorization
     to push to `main`.
9. Confirm to the user: what was committed, what branch, PR URL (if applicable),
   what's next on the manual-task side, and what the next session should focus
   on (which usually mirrors the updated `## Current Phase` in `CLAUDE.md`).

If there are no changes to commit, say so and skip to step 9.

## Notes

- Don't `git push --force` without explicit user request.
- For multi-file changes, prefer one commit per logical unit. A graph-side
  change and an unrelated docs polish should be two commits, not one.
- `.dyn` files are JSON under the hood but they're large and merge-hostile.
  Keep graph-only commits separate from Python-script-only commits when
  feasible — this makes future blame and revert surgical.
- This project has no build, no lint, no test runner today. If a lightweight
  Python lint (`ruff`, `pyflakes`) or a graph-extraction script is added later,
  update step 0 of this command to run it before staging.
