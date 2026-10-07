# Paper Plan — Journal Article on the One-Click Bridge Modeler

Working notes for authoring a peer-reviewed article about this project. Living
document — update as the plan firms up.

## 1. Target venue & framing

- **Primary target:** *Automation in Construction* (Elsevier, Q1, ISSN 0926-5805).
  Rewards AEC **application** novelty — a forward parametric BrIM workflow with
  grip-editable round-tripping fits its scope.
- **Backup / alternative venues:** *Computer-Aided Civil and Infrastructure
  Engineering*, *Advanced Engineering Informatics*, *Computer-Aided Design*
  (CAD wants geometric-algorithm novelty specifically — higher bar on the
  geometry contribution, less on the application).
- **Framing rule:** Do **not** pitch "we built a bridge tool." Pitch the
  *method* — tangent-constrained arc-polygon derivation for tapered/curved/skewed
  decks + a sketch-drives-solid parametric regeneration model that preserves
  designer grip-edits across runs. The tool is the vehicle; the geometry +
  workflow methodology is the contribution.

## 2. Core contribution (the novelty claim)

Candidate contributions, strongest first:

1. **Tangent-constrained arc-polygon derivation** (`src/deck_plan.py`) — the
   5-way gated derivation of a closed arc-bulge deck polygon for tapered curved
   bridges, where arcs are constrained to the *preceding edge direction* (not the
   alignment tangent — they differ by the taper angle) and bulges are computed
   against the **skewed bearing chords** the polyline actually draws.
2. **Sketch-drives-solid parametric regeneration** — Inventor-style editable
   skeleton (`BRIDGE-2D-DECK` polygon) + `schema_version` self-heal: designer
   grip-edits are read back and preserved across regenerations; the algorithm
   only erases/rebuilds when the schema version is bumped.
3. **Constant-section sweep + boolean-intersect deck** — preserves design
   cross-slope exactly (avoids loft-twist artifact), with quantified residuals
   (~0.008% haunch slope artifact; cross-slope error bounded by `slope·(1−cosθ)`).

The delta statement (one paragraph) and a related-work matrix (§3, task 6)
must make 1–3 defensible against the prior art in §8.

## 3. Task list — closing the evaluation & positioning gaps

### Workstream A — Benchmark & evaluation dataset
- [ ] **A1.** Define a benchmark bridge set spanning the parameter space:
  straight / single-arc / tapered-on-curve / curve↔tangent-transition /
  multi-span viaduct; each at 0°, ±10°, asymmetric skews; constant vs. tapering
  width; constant vs. shifting deck CL.
- [ ] **A2.** Build a measurement harness that auto-extracts per generated solid:
  deck depth, perpendicular width at N stations, cross-slope at each bearing
  line, haunch-top-vs-deck-soffit coincidence, plan-corner-vs-polygon-vertex
  deviation → CSV of measured-vs-expected with error magnitudes. (Scripts the
  checks currently done by hand in C3D.)
- [ ] **A3.** Record generation time per bridge and per stage (compute /
  skeleton / girders / deck / haunches) across the benchmark set.
- [ ] **A4.** Repeatable regeneration/round-trip test: grip-edit polygon
  vertices → re-run → assert edits preserved AND solid follows. Measured, not a
  one-off manual check.
- [ ] **A5.** Quantify the known geometric residuals (0.008% haunch artifact,
  `slope·(1−cosθ)` cross-slope bound) across the full benchmark to show they
  stay within tolerance over the whole range.

### Workstream B — Productivity / validation study (from Gemini's suggestion)
- [ ] **B1.** Controlled time study: model representative bridges the traditional
  manual way vs. with the tool; log wall-clock time per task. Record n, who did
  the manual modeling, software versions, and conditions so it isn't dismissed
  as anecdotal.
- [ ] **B2.** Design-change responsiveness: shift an alignment (e.g. 10 ft) and
  measure tool rebuild time vs. estimated manual rework. This is a strong,
  AiC-flavored metric — but state assumptions explicitly.
- [ ] **B3.** Accuracy comparison: tool output vs. a manually-built reference
  model, reporting geometric deviations.

### Workstream C — Comparison against prior art / baselines
- [ ] **C1.** Identify the closest baselines (OpenBridge Modeler, Allplan
  Bridge, Dynamo box-deck approaches, IFC 4.3 `IfcSectionedSolidHorizontal`
  sweeps) and state, per baseline, what each does/doesn't do that we do.
- [ ] **C2.** Explicitly contrast our boolean-intersect-with-editable-polygon
  deck against the IFC-native "sweep section along alignment" primitive
  (`IfcSectionedSolidHorizontal`) — why ours exists (exact cross-slope +
  editable footprint).

### Workstream D — Literature review & positioning
- [ ] **D1.** Build the related-work matrix: prior tools as rows; columns =
  curved-alignment support, tapered+skewed decks, sketch-driven editability,
  round-trip grip-edit preservation, output type. Empty cells = contribution.
- [ ] **D2.** Write the one-paragraph delta statement.
- [ ] **D3.** Snowball references from the three target AiC articles (you have
  full-text access via Stantec — see §6) plus the seed list in §8.

### Workstream E — Methods formalization (from Gemini's suggestion)
- [ ] **E1.** Write up the math cleanly: stationing, coordinate offsets, skew
  correction, perpendicular-offset edge sampling, arc-from-start-tangent and
  3-point-arc primitives. This is the "geometric logic" reviewers want stated
  abstractly, independent of the code.
- [ ] **E2.** "Challenges & workarounds" section — the PythonNet 3 / Civil 3D
  .NET API quirks already catalogued in `CLAUDE.md` (ref/out params, indexer
  dispatch, IDisposable `__exit__` misroute, overload disambiguation, enum
  stringification). This is genuinely useful, practitioner-facing content and a
  natural AiC section.
- [ ] **E3.** Data-flow figure: Civil 3D alignment/profile/surface → Dynamo
  nodes → Python compute → parametric solid generation → xdata/PropertySet
  mapping.

### Workstream F — Scope honesty & reproducibility
- [ ] **F1.** Re-scope the paper title/claim to the deck-geometry +
  parametric-regeneration contribution. Substructure / super-elevation / curved
  girders go in an explicit "Limitations & future work" section (reuse the
  deferral list in `CLAUDE.md`).
- [ ] **F2.** Write methodology-first so the paper never depends on a code
  release (see §5); keep code-release and benchmark-artifact release as
  additive, one-sentence decisions decoupled from the writing. Add a
  reproducibility statement consistent with whatever is ultimately released.

## 4. Proposed paper outline

1. Introduction — the BrIM gap; forward parametric modeling in Civil 3D.
2. Related work — parametric/algorithmic bridge modeling, IFC-Bridge / IFC 4.3,
   Dynamo-based AEC automation (the §3-D1 matrix).
3. System architecture — data flow (E3), platform (Dynamo/PythonNet/C3D .NET).
4. Method — deck-plan geometry (E1), sketch-drives-solid regeneration, deck/
   girder/haunch solid generation.
5. Implementation challenges & workarounds (E2).
6. Evaluation — benchmark set (A), accuracy + timing (A2/A3/A5), productivity
   study (B), comparison (C).
7. Limitations & future work (F1).
8. Conclusion.

## 5. IP / open-vs-closed strategy (Stantec)

**Guiding principle — methodology-first, written once.** Do not write two
papers, and do not write a paper that *depends* on releasing the source. From
day one, write the paper so it stands entirely on the **system architecture and
underlying logic** — input parameters (alignment/profile/surface), the geometric
translation logic (how the Python computes 3D coordinates, offsets, skew, arc
bulges), and the output (the parametric bridge model). Acceptance never requires
the Python files or the Dynamo graph.

This decouples the IP decision from the writing:
- If Stantec keeps the tool closed-source, the paper is already complete — it
  explains the science without giving away the proprietary product.
- If Stantec allows open-sourcing, you add **one sentence**: "The source code
  for this framework is available at [GitHub link]." No rewrite.

Case studies can be anonymized regardless ("a 3-span precast girder bridge on a
major North American highway project").

Honest caveats to weigh:
- A method-only paper *raises* the clarity bar — reviewers can't inspect the
  implementation, so §2's contribution and the §3 evaluation must be airtight
  and the methodology (E1) fully self-contained.
- *Automation in Construction* increasingly values reproducibility. Treat the
  **benchmark params + expected-output CSVs** as a *separately* releasable,
  citable artifact (the AISC table is already openly licensed) — independent of
  the core code decision, and additive in the same one-sentence way. This also
  keeps a future **dataset-paper** option open.

Action: get explicit sign-off from Stantec leadership on (a) publishing the
method (default-yes under this strategy), (b) the anonymization wording, and
(c) whether the code and/or the benchmark artifact may be released — but note
that none of these block starting to write.

## 6. Using Scopus AI + the Stantec eLibrary

You have two assets I don't: **Scopus AI** (discovery + summarization over
Scopus-indexed literature) and **full-text access** via the eLibrary. Suggested
workflow:

**Discovery (Scopus AI):**
- Run topic queries to seed the related-work section, e.g.:
  - "parametric bridge information modeling from alignments"
  - "IFC-Bridge parametric geometry exchange"
  - "Dynamo Civil 3D automated bridge modeling"
  - "procedural / generative solid geometry along alignment infrastructure"
- Ask gap-framing questions to sharpen the novelty statement, e.g. *"What are
  the open challenges in automated parametric bridge deck modeling on curved,
  skewed alignments?"* — then position contributions 1–3 (§2) against the gaps
  it surfaces.
- Use the concept-map / "expand" feature to find adjacent terminology you should
  be searching and citing.
- Use it to identify the most-cited papers and active authors in the space —
  these are citation targets and likely reviewers.

**Snowballing (Scopus + eLibrary):**
- Open the three AiC articles you sent (I was blocked by the paywall) and use
  Scopus's **"References"** (backward) and **"Cited by"** (forward) to snowball.
  Paste their reference lists back here and I'll help triage relevance.
- Pull full text from the eLibrary for everything in §8 and the snowball set.

**Caveats:**
- Scopus AI summarizes only Scopus-indexed content — it can miss very recent,
  preprint, or conference work (e.g. some Autodesk University / ISARC material).
- Always verify each Scopus AI citation against the full text before citing —
  treat it as a discovery aid, not a source of ground truth.

## 7. Notes on the Gemini response — what to use, what to temper

**Use it:**
- Generalized/agnostic framework over single-project (→ A1, F1).
- Formalize the math/geometry abstractly (→ E1).
- "Challenges & workarounds" section (→ E2) — we already have rich material in
  `CLAUDE.md`.
- Data-flow flowchart (→ E3).
- Validation by time + accuracy comparison (→ B1–B3).
- IP strategy: publish method, keep code; anonymize the case study (→ §5).
- Career/leadership framing is reasonable as an internal pitch for sign-off.

**Temper it:**
- The response is hype-y in places ("pure academic gold", "bulletproof"). AiC
  reviewers are skeptical of overselling — keep claims measured and evidenced.
- Don't frame the tool as "AI-driven efficiency." It's deterministic parametric
  geometry, not AI. Mislabeling it will hurt credibility.
- "OpenBridge-style" needs real differentiation (→ C1), not claimed parity.
- The time-savings study must be rigorous (n, conditions, who) or it reads as
  anecdote (→ B1 caveat).
- Closed-code vs. reproducibility is a genuine tension (→ §5) — Gemini presents
  closed-code as cost-free; it isn't, at this venue.

## 8. Literature & sources to check out

> Found via my own topic search — **not** from the three target articles'
> reference lists (those were paywalled to me). Verify each via the eLibrary /
> Scopus before citing. Roughly priority-ordered.

- **Review on parametric BIM & forward-design for bridge engineering** (Springer,
  *Discover Applied Sciences*, 2025) — best single anchor for related work; recent
  survey of exactly this space.
  https://link.springer.com/article/10.1007/s42452-025-06543-y
- **Borrmann et al., "The IFC-Bridge project — Extending the IFC standard…"** —
  foundational BrIM / IFC-Bridge positioning.
  https://www.semanticscholar.org/paper/The-IFC-Bridge-project-%E2%80%93-Extending-the-IFC-standard-Borrmann-Muhic/4a4f271bada2e0bbd567d019a4ec4ffb9b4aa679
- **"Integration of Parametric Geometry into IFC-Bridge"** — representing
  constraint/expression-driven parametric geometry in IFC-Bridge; close to the
  editable-sketch thesis.
  https://www.researchgate.net/publication/260762895_Integration_of_Parametric_Geometry_into_IFC-Bridge
- **IFC 4.3 infrastructure — `IfcAlignment`, `IfcSectionedSolidHorizontal`** —
  standards baseline to contrast the sweep-along-alignment approach against.
  https://wiki.osarch.org/index.php/IFC_-_Industry_Foundation_Classes/IFC_alignment
  · https://www.buildingsmart.org/standards/domains/infrastructure/ifc-bridge/
- **"Bridge damage: Detection, IFC-based semantic enrichment and visualization"**
  — confirmed *Automation in Construction* article; in-venue citation + xdata/
  semantic-tagging framing.
  https://www.sciencedirect.com/science/article/abs/pii/S0926580519306387
- **"Optimization of geometric parameters of arch bridges using visual
  programming FEM components and genetic algorithm"** — generative/algorithmic
  design in a visual-programming context.
  https://www.researchgate.net/publication/351514126_Optimization_of_geometric_parameters_of_arch_bridges_using_visual_programming_FEM_components_and_genetic_algorithm
- **"Development of parametric bridge BIM and PCD generation algorithms…"**
  (*Advances in Engineering Software*, 2024 — adjacent venue, not AiC) — closest
  "parametric bridge BIM generation algorithm" peer to differentiate against.
  https://www.sciencedirect.com/science/article/abs/pii/S0965997824000802
- **Scan2BrIM / point-cloud → IFC bridge reconstruction** — cite to delimit scope
  (reverse-engineering from scans vs. forward parametric design).
  https://ascelibrary.org/doi/10.1061/9780784482421.058

### To verify / track down with your access
- The three target AiC 2026 articles you sent (PIIs `S092658052600230X`,
  `S0926580526002360`, `S092658052600244X`) — open via eLibrary, capture title +
  abstract + reference list, and snowball.
- The Dynamo single-cell box-deck parametric paper (surfaced via an unverifiable
  `scirp.org` link) — confirm citation details before use.
