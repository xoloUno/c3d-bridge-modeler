# Phase 2 — Scope

Phase 1 (single-span straight bridge with skewed abutments and
fanning/tapering deck) is largely working. This document captures
the next set of capabilities that Erik flagged as common in real
projects and outlines the implementation approach for each.

## Curved horizontal alignment

The most-requested Phase 2 capability. Real bridges often sit on
horizontal curves; the existing Phase 1 sweep+intersect approach
needs targeted changes (not a rewrite) to handle curves.

### What changes in the geometry

For a straight horizontal alignment, the deck is constructed by:
1. Sweeping an alignment-perpendicular cross-section along a 3D
   path (alignment XY + profile Z), with `Align=NoAlignment` and
   `Bank=False` so the cross-section stays in a fixed world
   orientation throughout.
2. Trimming the resulting "fat deck" with a 4-corner polygon
   extruded vertically.

For a curved horizontal alignment:

#### 1. Sweep path becomes a 3D curve

The existing path-sampling helper (`_build_path_3d_points` in
`decks.py`) already samples alignment XY at N evenly-spaced
stations and emits a `Polyline3d`. For a straight alignment it
produces a straight 3D polyline; for a curved alignment it produces
a polyline that approximates the curve. The denser the sampling,
the smoother the curve approximation.

Phase 1 uses `_PATH_SAMPLE_COUNT = 21` (every ~4 ft on a typical
~80 ft bridge). For tight horizontal curves, may need to bump to
50–100 samples. Likely also worth making the count
station-spacing-driven rather than fixed count: e.g., 1 sample per
foot of station with a minimum of 21.

#### 2. Cross-section orientation rotates with the path tangent

This is the central change. Phase 1's `Align=NoAlignment` keeps the
profile in its world orientation throughout the sweep. For a curved
path that's wrong everywhere except the start.

Switch to `Align=SweepOptionsAlignOption.AlignSweepEntityToPath`.
This makes AutoCAD auto-rotate the profile so its plane stays
perpendicular to the path tangent at every point. With `Bank=False`
the web/walls of the cross-section stay plumb regardless of horizontal
curvature; only the tangent direction changes.

We may need to test `Bank=False` vs leaving the bank option at the
default (`True`) on curved paths. With Bank=False, the cross-section
stays plumb; with Bank=True, it tilts with the curvature, which
would simulate super-elevation banking but isn't typically what
modeling code should generate (the engineer specifies super-elevation
in the params; let it drive the geometry rather than letting the loft
algorithm guess).

#### 3. Trim-polygon edges become curves, not straight lines

Currently the deck plan polygon has 4 straight segments between
corners. For curved alignments, the deck's left/right edges follow
the curve at constant perpendicular offset — these are themselves
curves (arcs offset from arcs, or splines offset from spirals). The
skewed bearing lines at the supports remain straight.

`Region.CreateFromCurves` accepts mixed curves and lines, so the
trim polygon construction can be generalized: build the trim region
from a closed curve set that includes:
  - Left deck-edge curve (offset of the alignment curve)
  - End-bearing line (straight, skewed)
  - Right deck-edge curve (offset of the alignment curve)
  - Start-bearing line (straight, skewed)

For Phase 1 with straight alignment, these all degenerate to
straight lines and the existing 4-corner polygon code works. For
Phase 2 we need to plug in the curved edges.

#### 4. Super-elevation transitions: sweep → loft

If the cross-slope varies with station (typical: normal crown
−2% / −2% on tangent, super-elevated +6% / +6% on the curve,
gradual transitions on the spirals at curve entry/exit), the
cross-section is no longer constant along the sweep. `CreateSweptSolid`
can't handle that.

Two options:
  - **Loft through multiple cross-sections** sampled at key
    super-elevation transition points (BC, EC, PC, PT, mid-curve)
    plus the start and end bearings. This works for any super-
    elevation profile but requires sampling logic that knows the
    super-elevation table.
  - **Defer super-elevation** to Phase 3 and assume constant
    cross-slope throughout Phase 2.

Recommend: defer super-elevation. Phase 2 covers tangent +
curve geometry with a single cross-slope per side, which is
sufficient for many real bridges and a useful incremental step.

#### 5. Tapering deck width on a curve

Already handled by the existing trim-polygon approach: the deck
edges curves are offset from the alignment by varying amounts
(`perpendicular_deck_width / 2 + deck_cl_offset` at each station).
For tapering, those offsets change linearly along the alignment.

When the deck edges are constructed as Civil 3D
sub-alignments / offsets-of-alignment objects, the tapering is a
property of how they're constructed in the drawing. The tool reads
the resulting curves from the drawing as part of the trim polygon.

### Decisions deferred

- **Where do the curved deck-edge polylines live?**
  Two options:
    a. Generate them at run-time from the alignment + params (same
       as Phase 1, but with `point_on_skewed_bearing` replaced by a
       curve-offset operation).
    b. Pre-author them as Civil 3D sub-alignments at template
       generation time; tool reads them from the drawing each run.
  Option (b) fits the two-mode workflow better (designers can edit
  the curves, tool reads them). Option (a) avoids the manual setup
  step but doesn't give the designer override capability.

- **How to handle non-tangent abutments on curves.** A bridge
  whose abutments sit on curve vs. spiral vs. tangent portions of
  the alignment have different geometric implications for the deck
  edge tangency at the bearing line. Probably worth a dedicated
  follow-up after the baseline curved-deck slice lands.

- **Girder layout on curves.** For Phase 2, girders are still
  modeled as straight 3D solids between bearings. For tight curves,
  real girders are either curved (rolled into a horizontal arc) or
  chord-and-fillet (straight segments with angle breaks at field
  splices). Defer to Phase 3.

### Effort estimate

~2 focused sessions:
- Session 1: curved sweep path + `AlignSweepEntityToPath` cross-
  section orientation; trim polygon with curve edges. Verify on a
  test bridge with constant cross-slope.
- Session 2: tapering verification, edge cases (abutment on
  spiral, deck CL offset on curves), updated MANUAL-TASKS entries.

Super-elevation is a Phase 3 add-on, not in this scope.

## Other Phase 2 candidates

These are mentioned for completeness; not in priority order. Each
deserves its own scope expansion before implementation.

### Substructure
- Pier caps, columns (above/below grade with `-BELOW` linetype),
  abutment stems / backwalls / wingwalls. Layers listed in
  `templates/README.md`. Cap-to-girder geometric tie-in via the
  bearing seat elevations already computed (`GirderAtBearing.
  bearing_seat`).

### Multi-span bridges
- Multiple `Span` entries linking shared piers. Schema already
  supports multiple spans; compute orchestrator handles the loop;
  the build orchestrators just iterate.

### Plate girders
- Custom-width built-up sections (vs. AISC rolled W-shapes). Schema
  has the `PLATE_GIRDER` enum value placeheld; need to add a plate-
  girder dim block and route through `girder_geometry` /
  `_girder_depth_ft` / `_flange_width_ft`.

### IFC export
- `templates/README.md` already documents the `BRIDGE_IFC` Property
  Set Definition. Once Phase 1 + 2 geometry is solid, the tool can
  attach the PropSet to each solid at creation time using the
  per-element `IfcEntity` / `PredefinedType` values listed in that
  README.
