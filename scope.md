# One-Click Bridge Modeler for Civil 3D

## Project Scope & Development Plan

**Author:** Erik Jimenez / xolo.uno  
**Platform:** Dynamo for Civil 3D (Python nodes) → future C# plugin  
**Date:** May 2026  
**Status:** Scoping

---

## Problem Statement

Autodesk has no native bridge modeling tool for Civil 3D. The current Autodesk-recommended workflow requires five separate products (InfraWorks, Inventor, Civil 3D, Revit, Structural Bridge Design) to produce a single bridge model. In practice, the InfraWorks-based workflow produces 3D models that must be exploded into dumb linework for drawing production — destroying the link between 3D model and 2D deliverables, creating design drift risk, and adding manual rework at every design iteration.

The Civil 3D App Store has 827+ plugins and zero dedicated bridge modeling tools. SOFiSTiK's Bridge Modeler exists for Revit but not Civil 3D. Bentley's OpenBridge Modeler is the only real competitor, and it lives outside the Autodesk ecosystem entirely.

**Goal:** Build a Dynamo-based parametric bridge modeler that generates 3D AutoCAD solids directly in Civil 3D from alignment, profile, surface, and tabular inputs — enabling a single-source-of-truth workflow where sheets xref the bridge drawing and update automatically when the model is regenerated.

---

## Architecture

### Why AutoCAD 3D Solids (Not "Smart" Civil 3D Objects)

Civil 3D has no native `Bridge` API class. The "Bridges" node in Prospector only receives imported InfraWorks models — you cannot author bridge objects natively. Therefore the tool generates **AutoCAD `Solid3d` objects** organized on a disciplined layer structure.

The "intelligence" lives in the Dynamo script and its parameter inputs — not in the geometry itself. To update the bridge, the user changes inputs and re-runs the script. Solids are deleted and regenerated.

This is the same pattern used by every Dynamo-based Civil 3D automation today, including CivilConnection (Autodesk's own Civil 3D ↔ Revit bridge workflow package).

### Drawing & Xref Workflow

```
[Bridge Parameters]
        │
        ▼
[Dynamo Script] ──reads──▶ [Civil 3D Data Shortcuts]
        │                    • Alignment(s)
        │                    • Profile(s)
        │                    • EG Surface
        │                    • FG Surface
        ▼
[Bridge Drawing] ◀── single source of truth
  (3D Solids on layers)
        │
        ├──xref──▶ [Plan Sheet]     (Top viewport, Hidden style)
        ├──xref──▶ [Elevation Sheet] (Front viewport, Hidden style)
        ├──xref──▶ [Section Sheets]  (Section viewports per pier/midspan)
        └──xref──▶ [Profile Sheet]   (Profile view along alignment)
```

### Layer Structure

All bridge objects are placed on component-level layers (unnumbered). Individual element identity (girder number, pier ID, span, etc.) is stored as **xdata tags** on each solid, queryable via selection filters or scripts when per-element isolation is needed. This keeps the layer list clean regardless of bridge size.

```
BRIDGE-DECK                    Deck slab solid(s)
BRIDGE-DECK-TOPPING            Topping pavement solid(s)
BRIDGE-DECK-HAUNCH             Haunch solids
BRIDGE-GIRDER                  Girder solids
BRIDGE-DIAPH-END               End diaphragm solids
BRIDGE-DIAPH-INT               Intermediate diaphragm solids
BRIDGE-BEARING                 Bearing device solids
BRIDGE-PEDESTAL                Bearing pedestal solids
BRIDGE-PIER-CAP                Pier/bent cap solids
BRIDGE-PIER-COL                Column solids (above grade)
BRIDGE-PIER-COL-BELOW          Column portions below EG (DASHED linetype)
BRIDGE-PIER-FTG                Pier footing/pile cap solids (exclusively below grade)
BRIDGE-PIER-PILE               Pier piles
BRIDGE-ABUT-STEM               Abutment stem solids (above grade)
BRIDGE-ABUT-STEM-BELOW         Abutment stem portions below EG (DASHED)
BRIDGE-ABUT-BACKWALL           Abutment backwall solids
BRIDGE-ABUT-WINGWALL           Abutment wingwall solids (above grade)
BRIDGE-ABUT-WINGWALL-BELOW     Abutment wingwall portions below EG (DASHED)
BRIDGE-ABUT-FTG                Abutment footing solids (exclusively below grade)
BRIDGE-ABUT-PILE               Abutment piles
```

Each solid carries xdata with its identity metadata, e.g.:
```json
{"pier_id": "PIER-2", "column": 3, "span": "SPAN-1", "girder": 5}
```

This enables per-element selection when needed (phased erection drawings, section view isolation, quantity extraction by element) without inflating the layer list.

---

## Input Parameters

### Global Bridge Parameters

| Parameter | Type | Description |
|---|---|---|
| `alignment_name` | string | Name of Civil 3D alignment to reference via data shortcuts |
| `profile_name` | string | Name of vertical profile on that alignment |
| `eg_surface_name` | string | Existing Ground surface name |
| `fg_surface_name` | string | Finished Grade surface name |
| `begin_station` | float | Begin bridge station on alignment |
| `end_station` | float | End bridge station on alignment |
| `begin_skew_angle` | float | Skew angle at begin station (degrees from perpendicular, 0 = square) |
| `end_skew_angle` | float | Skew angle at end station (degrees from perpendicular) |
| `deck_cross_slope_left` | float | Cross slope left of crown (%, negative = downward) |
| `deck_cross_slope_right` | float | Cross slope right of crown (%) |
| `crown_offset` | float | Offset of crown from alignment (+ = right, 0 = centerline) |
| `deck_profile_offset` | float | Vertical offset from profile to top of deck (negative = below profile, accounts for pavement depth) |
| `follow_superelevation` | bool | If true, deck cross slope follows alignment superelevation |

### Span Definition (per span)

Each span is defined between two support points (piers, abutments, or straddle bents).

| Parameter | Type | Description |
|---|---|---|
| `span_id` | string | Identifier (e.g., "SPAN-1") |
| `start_support_id` | string | Reference to pier/abutment at start of span |
| `end_support_id` | string | Reference to pier/abutment at end of span |

### Superstructure Definition (per span)

| Parameter | Type | Description |
|---|---|---|
| `girder_type` | enum | `W_SHAPE`, `PLATE_GIRDER`, `BOX_GIRDER`, `PRECAST_PRESTRESSED` |
| `girder_shape` | string | AISC designation (e.g., "W36X150") or plate girder dimensions |
| `girder_count` | int | Number of girders in this span |
| `girder_spacing_mode` | enum | `EQUAL`, `CUSTOM` |
| `girder_spacing_at_start` | float[] | Array of spacings at start support CL bearings (from left edge of deck) |
| `girder_spacing_at_end` | float[] | Array of spacings at end support CL bearings |
| `girder_geometry` | enum | `STRAIGHT` (chorded between supports), `CURVED_RADIUS` (constant radius per girder), `FOLLOW_ALIGNMENT` (offset from alignment curve) |
| `girder_radius` | float[] | Per-girder radius (only if `CURVED_RADIUS`); null otherwise |
| `deck_width_at_start` | float | Total deck width at start of span |
| `deck_width_at_end` | float | Total deck width at end of span (allows tapering) |
| `deck_depth` | float | Deck slab thickness |
| `haunch_depth` | float | Haunch depth (constant per span) |
| `haunch_width_mode` | enum | `MATCH_TOP_FLANGE`, `CUSTOM` |
| `haunch_width` | float | Custom haunch width (if not matching top flange) |
| `topping_depth` | float | Topping pavement depth (0 if none) |
| `end_diaphragm` | bool | Generate end diaphragms at supports |
| `intermediate_diaphragm_count` | int | Number of intermediate diaphragms |
| `diaphragm_type` | enum | `W_SHAPE`, `PLATE`, `CHANNEL` |
| `diaphragm_shape` | string | Shape designation or dimensions |

### Plate Girder Definition (if `girder_type` = `PLATE_GIRDER`)

| Parameter | Type | Description |
|---|---|---|
| `web_depth` | float | Web plate depth |
| `web_thickness` | float | Web plate thickness |
| `top_flange_width` | float | Top flange width |
| `top_flange_thickness` | float | Top flange thickness |
| `bottom_flange_width` | float | Bottom flange width |
| `bottom_flange_thickness` | float | Bottom flange thickness |
| `web_depth_varies` | bool | Does web depth vary along span (haunched girder) |
| `web_depth_at_supports` | float | Web depth at supports (if varies) |
| `web_depth_at_midspan` | float | Web depth at midspan (if varies) |

### Support Definition (per pier / abutment / straddle bent)

Each support is defined independently, allowing mixed types.

| Parameter | Type | Description |
|---|---|---|
| `support_id` | string | Unique identifier (e.g., "PIER-1", "ABUT-A") |
| `support_type` | enum | `ABUTMENT_SEAT`, `ABUTMENT_INTEGRAL`, `PIER_SINGLE_COLUMN`, `PIER_MULTI_COLUMN`, `PIER_WALL`, `STRADDLE_BENT`, `NONE` (jump span) |
| `station` | float | Station on alignment |
| `skew_angle` | float | Skew angle at this support (degrees from perpendicular) |
| `offset` | float | Lateral offset from alignment (+ = right) |

### Pier Cap / Bent Cap Definition (per support)

| Parameter | Type | Description |
|---|---|---|
| `cap_type` | enum | `CONCRETE_RECT`, `CONCRETE_TAPERED`, `STEEL_BOX`, `STEEL_MULTI_BEAM`, `INTEGRAL` |
| `cap_width` | float | Cap width (perpendicular to bridge) |
| `cap_depth` | float | Cap depth |
| `cap_length` | float | Cap length (parallel to bridge / along skew) |
| `cap_extends_beyond_deck` | bool | Does cap extend beyond edge of deck (for straddle bents) |
| `bearing_seat_height` | float | Pedestal height on cap (default 6") |
| `bearing_device_height` | float | Bearing device height (default 6") |
| `cap_slope_follows_deck` | bool | If true, top of cap slopes to match deck cross slope |

### Column Definition (per support)

| Parameter | Type | Description |
|---|---|---|
| `column_count` | int | Number of columns |
| `column_spacing` | float[] | Spacing array (if multi-column) |
| `column_shape` | enum | `CIRCULAR`, `RECTANGULAR`, `OCTAGONAL` |
| `column_diameter` | float | Diameter (circular) or width (rectangular) |
| `column_depth` | float | Depth (rectangular only) |

Note: Column height is automatically calculated from:
`top_of_cap_elevation - top_of_footing_elevation`
where `top_of_cap` is derived from deck profile/cross slope minus superstructure depth, and `top_of_footing` is derived from FG surface minus `min_foundation_depth`.

### Foundation Definition (per column)

| Parameter | Type | Description |
|---|---|---|
| `foundation_type` | enum | `DRILLED_SHAFT`, `SPREAD_FOOTING`, `PILE_CAP_MICROPILE`, `PILE_CAP_DRIVEN`, `SPREAD_FOOTING_MICROPILE`, `SPREAD_FOOTING_DRIVEN` |
| `min_depth_below_fg` | float | Minimum depth of top of foundation below FG surface |
| `footing_length` | float | Footing plan dimension along bridge |
| `footing_width` | float | Footing plan dimension perpendicular to bridge |
| `footing_depth` | float | Footing thickness |
| `shaft_diameter` | float | Drilled shaft diameter (if applicable) |
| `shaft_tip_elevation` | float | Tip elevation (if known; otherwise placeholder) |
| `pile_rows` | int | Number of pile rows |
| `pile_per_row` | int | Number of piles per row |
| `pile_spacing` | float | Pile spacing |
| `pile_batter` | float | Batter angle (degrees from vertical, 0 = plumb) |
| `pile_batter_direction` | enum | `NONE`, `OUTWARD`, `INWARD`, `ALTERNATING` |

### Abutment-Specific Parameters (if support_type = ABUTMENT_*)

| Parameter | Type | Description |
|---|---|---|
| `backwall_height` | float | Backwall height above bearing seat |
| `backwall_thickness` | float | Backwall thickness |
| `wingwall_type` | enum | `NONE`, `STRAIGHT`, `FLARED` |
| `wingwall_length` | float | Wingwall length |
| `wingwall_height_mode` | enum | `CONSTANT`, `TAPERED_TO_GRADE` |
| `wingwall_thickness` | float | Wingwall thickness |

---

## Phased Development Plan

### Phase 0: Foundation & Proof of Concept (Weeks 1–4)

**Goal:** Prove the core pipeline works — read Civil 3D data, generate solids, display correctly in viewports.

**Deliverables:**
- Dynamo graph that reads a single alignment + profile via data shortcuts
- Generates a simple rectangular deck solid between two stations
- Generates two rectangular pier solids at specified stations
- Places solids on named layers
- Verify: Hidden visual style in viewport shows correct wireframe
- Verify: xref workflow works (bridge drawing xref'd into sheet)

**Why this first:** This validates the entire I/O pipeline before investing in geometric complexity. If xref display or Dynamo-to-Civil3D solid generation has issues, we discover them in week 1, not month 3.

### Phase 1: Single-Span Straight Bridge (Weeks 5–10)

**Goal:** Model a complete single-span bridge with steel girders on a straight alignment.

**Deliverables:**
- W-shape girder generation from AISC designation (lookup table for dimensions)
- Plate girder generation from custom dimensions
- Deck solid with configurable width, depth, cross slope, crown offset
- Haunch solids per girder
- Bearing devices and pedestals
- Single-column or multi-column pier with concrete cap
- Seat-type abutment with backwall and optional wingwalls
- Foundation solids (drilled shaft or spread footing — simplest two types)
- Column split at EG surface for above/below-grade layer assignment
- Elevation table output (top of footing, top of column, top of cap, bearing seat, top of deck)
- End diaphragms

**Input method:** Dynamo parameter panel (Dynamo Player-friendly for non-Dynamo users)

### Phase 2: Multi-Span & Skewed Bridges (Weeks 11–16)

**Goal:** Extend to multi-span bridges with varying pier types and skew angles.

**Deliverables:**
- Multi-span support: list of intermediate pier stations with individual skew angles
- Per-pier substructure type selection (different pier types per support)
- Straddle bent support type
- `NONE` support type for jump spans (girders/deck continue, no substructure)
- Steel box cap beam and multi-steel-beam cap
- Wall pier type
- Pile cap foundations with micropiles or driven piles
- Battered pile support
- Independent begin/end skew angles
- Intermediate diaphragms (evenly spaced per span)

### Phase 3: Curved & Variable-Width Bridges (Weeks 17–24)

**Goal:** Handle the geometric complexity of the current project type.

**Deliverables:**
- Three girder geometry modes:
  - `STRAIGHT`: chorded between supports (existing default)
  - `FOLLOW_ALIGNMENT`: each girder path is a lateral offset from the alignment curve (simplest curved mode — alignment already has the curve math; query station+offset for each girder)
  - `CURVED_RADIUS`: independent constant radius per girder (for cases where girders don't follow the alignment, e.g., variable spacing on a widening bridge)
- Variable deck width (taper) with interpolated girder spacing
- Custom (non-equal) girder spacing defined at each support
- Deck as continuous solid across multiple spans (option vs. per-span)
- Edge-of-deck paths: `FOLLOW_ALIGNMENT` mode (offset from alignment, like corridor) or independent radius
- Girder seat elevation calculation from deck cross slope → haunch → girder depth
- Superelevation-following mode for deck cross slope
- Topping pavement as separate solid

### Phase 4: Drawing Production Aids (Weeks 25–30)

**Goal:** Automate the drawing production workflow.

**Deliverables:**
- Auto-generate sample lines at each pier and at midspan for section views
- Elevation/dimension tables as Civil 3D table objects or AutoCAD tables:
  - Bearing seat elevations per girder per support
  - Top of footing / bottom of column elevations
  - Top of column / bottom of cap elevations
  - Top of cap at CL columns and at cap ends
  - Deck elevations at edges and CL
  - Girder camber table (if camber is input)
- Quantity summary: deck volume, girder weights (from AISC tables), concrete volumes per substructure element
- Auto-generate viewport configurations for plan, elevation, typical section

### Phase 5: Advanced Features & App Store Preparation (Weeks 31–40)

**Goal:** Polish for release and add high-value features.

**Deliverables:**
- Shared substructure references (e.g., straddle bent shared between two bridges on different alignments)
- Multiple alignment support per bridge drawing
- Wingwall geometry: straight and flared, tapered to grade
- Integral abutment type
- Precast prestressed girder type
- Cast-in-place box girder type (single-cell, multi-cell)
- Export to IFC for coordination
- Dynamo Player UI with grouped parameter panels
- Documentation and tutorial
- Autodesk App Store submission (if converting to C# plugin)

### Future: Post-v1

- **Rebar/reinforcement generation** (top priority post-v1 per Erik)
- Deck drainage (scuppers, drain locations)
- Bridge barriers / railings / median barriers
- Expansion joint locations and modeling
- Camber diagram generation
- Integration with Autodesk Structural Bridge Design for analysis
- Bill of steel (detailed girder weight breakdown by piece)
- Erection sequence visualization
- Connection to Site Composer / visionOS viewer for spatial review

---

## Technical Implementation Notes

### AISC Shape Database

Embed a lookup table of standard W-shapes (W10–W44 series) with dimensions: depth, web thickness, flange width, flange thickness, weight per foot, moment of inertia, section modulus. Source: AISC Steel Construction Manual, 16th Edition (publicly available dimension tables). This avoids requiring the user to manually input dimensions for standard shapes.

### Girder Seat Elevation Calculation

The critical geometric chain from top of deck down to top of footing:

```
Top of Deck (at girder CL) = Profile Elevation
                            + deck_profile_offset
                            + cross_slope × distance_from_crown

Top of Girder Top Flange  = Top of Deck
                            - deck_depth
                            - haunch_depth

Bottom of Girder           = Top of Girder Top Flange
                            - girder_depth

Bearing Seat Elevation     = Bottom of Girder
                            - bearing_device_height

Top of Cap                 = Bearing Seat Elevation
                            - bearing_seat_height (pedestal)

Top of Column              = Top of Cap
                            - cap_depth

Top of Footing             = max(
                                FG_surface_at_column - min_depth_below_fg,
                                specified_top_of_footing_elevation
                              )

Column Height              = Top of Column - Top of Footing
```

This chain is computed per girder per support, accounting for cross slope. If `cap_slope_follows_deck` is true, the cap top surface slopes and pedestals vary in height to provide level bearing seats.

### Coordinate System & Alignment Following

All geometry is generated in Civil 3D world coordinates by querying the alignment for:
- Point (X, Y) at a given station
- Direction (tangent bearing) at a given station
- Superelevation at a given station (if applicable)

Cross-sections are then constructed perpendicular to the alignment (adjusted by skew angle) and the 3D solids are built by lofting or extruding between cross-sections.

For curved girders, three modes are supported:

1. **`FOLLOW_ALIGNMENT` (recommended default for curved bridges):** Each girder centerline and each edge-of-deck line is generated by querying the alignment at a constant lateral offset. This is the same approach Civil 3D corridors and OpenBridge Modeler use — the alignment already encodes the horizontal curve geometry (arcs, spirals), so each girder path is simply `alignment.PointAtStationOffset(station, offset)` sampled at regular intervals and connected. This produces girders that are concentric with the alignment and with each other. The girder cross-section is swept along this path. This is the simplest curved mode to implement because you don't need to compute independent arc geometry — the alignment API does the work.

2. **`CURVED_RADIUS`:** Each girder has an independently specified constant radius (not necessarily concentric with the alignment or with each other). This handles the case Erik described where the bridge widens along a curve and girder spacing increases, producing unique non-concentric radii per girder. The girder centerline is generated as a circular arc between support points at the specified radius.

3. **`STRAIGHT`:** Girder is a straight chord between support points. Used for tangent spans or for spans where girders are chorded with angle breaks at piers.

### Solid Generation Strategy

- **Deck:** Lofted solid between cross-section profiles at each support and at intermediate points (for tapering/curving). Cross-section = a wide, thin rectangle with cross slope applied.
- **Girders:** Swept solid along the girder centerline path (straight line or arc). Cross-section = I-shape (from AISC lookup or custom plate dimensions).
- **Haunches:** Swept solid matching girder path. Cross-section = trapezoid (bottom = top flange width, top = haunch width, height = haunch depth).
- **Pier caps:** Extruded solid along the cap length (perpendicular to bridge, adjusted for skew). Cross-section = rectangle or tapered rectangle.
- **Columns:** Extruded solid (cylinder or prism) from top of footing to top of column.
- **Footings:** Simple box solid placed at the calculated elevation.
- **Piles:** Cylinders or prisms from bottom of pile cap to tip elevation, with optional batter angle.
- **Abutments:** Composed of multiple box solids (seat, backwall, wingwalls).

### Below-Grade Layer Split

For each column, abutment stem, and wingwall solid:
1. Query EG surface elevation at the element's (X, Y) location
2. If the solid spans above and below this elevation, split it into two solids using a boolean cut at the EG plane
3. Place the above-grade portion on the standard layer
4. Place the below-grade portion on the `-BELOW` layer (DASHED linetype)

Footings (pier and abutment) are exclusively below grade and do not need splitting — they are placed directly on their respective `FTG` layers with DASHED linetype.

### Re-Run / Update Behavior

When the user re-runs the Dynamo script:
1. Delete all objects on `BRIDGE-*` layers in the current drawing
2. Regenerate all solids from current parameter values
3. This ensures the model always reflects the latest inputs

Alternative (more advanced): tag each solid with an xdata key linking it to its parameter source, and only regenerate changed elements. This is a performance optimization for Phase 5+.

---

## Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| Dynamo `Solid3d` creation is slow for complex bridges (50+ solids) | Script takes 30+ seconds to run | Acceptable for re-generation workflow; optimize with direct API calls in Python if needed |
| AutoCAD Hidden visual style doesn't handle complex occlusion well | Drawing production requires manual cleanup | Test early (Phase 0); fall back to layer-based dashed lines if needed |
| Civil 3D alignment API doesn't expose superelevation data in Dynamo | Can't automate superelevation-following mode | Query via Python `.NET` API directly; superelevation is available in `Alignment.GetSuperElevation()` |
| Curved girder swept solids are geometrically complex | Loft/sweep failures on tight radii | `FOLLOW_ALIGNMENT` mode is simplest (uses alignment API offsets); `CURVED_RADIUS` mode uses segmented straight approximation (chorded at small intervals) as fallback |
| Scope creep: "just one more parameter" per bridge type | Timeline balloons from 10 weeks to 10 months | Strict phase gates; v1 = steel girder + simple substructure only |
| AISC shape data licensing | Can't distribute shape tables | AISC dimensions are published in publicly available resources; include a curated subset; allow user override |
| Dynamo version compatibility across Civil 3D versions | Script breaks on upgrade | Target Civil 3D 2024 (Dynamo 2.x); use CPython 3 / PythonNet 3 exclusively; avoid deprecated nodes; document PythonNet 3 quirks in CLAUDE.md so they don't get re-discovered |

---

## Success Criteria

### Phase 0 (Proof of Concept) — COMPLETE 2026-05-06
- [x] Dynamo script reads alignment and profile from data shortcuts
- [x] Generates 3D solid deck and two pier placeholders
- [x] Solids display correctly in Hidden visual style viewport
- [x] Xref workflow verified: bridge drawing xref'd into separate sheet drawing

### Phase 1 (Single-Span)
- [ ] Complete single-span steel girder bridge generated from parameters
- [ ] Elevation table output matches manual calculation within 0.01'
- [ ] Drawing production: plan, elevation, and section viewports show correct wireframe
- [ ] Re-run correctly deletes and regenerates all solids
- [ ] Digital Applications team member validates on a real project structure

### Phase 2 (Multi-Span)
- [ ] 3-span bridge with mixed pier types generated correctly
- [ ] Skewed supports produce correct geometry
- [ ] Straddle bent shared between two bridges (basic reference)

---

## Estimated Timeline

At 2–5 hours/week evening development time:

| Phase | Weeks | Cumulative Hours | Target |
|---|---|---|---|
| Phase 0 | 4 | 8–20 hrs | Month 1 |
| Phase 1 | 6 | 20–50 hrs | Months 2–3 |
| Phase 2 | 6 | 32–80 hrs | Months 3–5 |
| Phase 3 | 8 | 48–120 hrs | Months 5–8 |
| Phase 4 | 6 | 36–90 hrs | Months 8–10 |
| Phase 5 | 10 | 56–140 hrs | Months 10–14 |

**Phase 0 + 1 produce a usable tool for simple bridges.** This is the MVP — a single-span, straight, steel girder bridge on a non-skewed alignment. If this is all you ever build, it still saves hours per bridge.

---

## Technology Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Automation platform | Dynamo for Civil 3D (Python nodes) | Fastest to prototype; full access to Civil 3D .NET API via PythonNet3; Dynamo Player provides UI for non-developers; convert to C# plugin later for App Store |
| Geometry output | AutoCAD `Solid3d` objects | Civil 3D has no native bridge API class; solids support Hidden visual style, xref, viewport layer control |
| Parameter input (Phase 0–2) | Dynamo input nodes + Python dictionaries | Quick iteration; parameters can be JSON/CSV files loaded by the script |
| Parameter input (Phase 4+) | Dynamo Player panel or custom WPF dialog (C#) | Production-ready UI for bridge team members who don't use Dynamo |
| Python version | CPython 3.x via PythonNet 3 | Selected per-node in Dynamo (CPython 3, not IronPython 2.7); IronPython 2.7 is deprecated |
| Target Civil 3D version | 2024 (Dynamo Core 2.x) | Project requirement; pythonnet 3 quirks (`clr.Reference` removed, indexers not exposed as `__getitem__`) are documented in CLAUDE.md |
| Shape database | Embedded JSON lookup table | No external dependencies; user can extend with custom shapes |
| File format for parameters | JSON (one file per bridge) | Human-readable, version-control-friendly, editable outside Dynamo |
| Layer naming convention | `BRIDGE-{COMPONENT}` (unnumbered) + xdata per solid | Clean layer list (~20 layers regardless of bridge size); per-element identity stored as xdata for filtering/selection when needed |
| Below-grade display | Layer split at EG surface with DASHED linetype | More reliable than depending on Hidden visual style for surface occlusion |

---

## Open Questions

1. **Parameter input format:** Should bridge parameters be defined in a JSON file, an Excel spreadsheet, or directly in the Dynamo graph? JSON is cleanest for version control; Excel is most familiar to bridge engineers. Recommendation: support both — JSON as primary, with an Excel-to-JSON converter script.

2. **Bearing device modeling detail:** For v1, are bearings simple rectangular blocks, or do you need to distinguish elastomeric pads, pot bearings, disc bearings, etc.? Recommendation: simple block placeholder in v1, typed bearings in Phase 5.

3. **Deck edge geometry:** Are deck edges vertical (square edge) or do you need barrier/parapet seat geometry (e.g., a step at the edge for barrier placement)? Recommendation: vertical edge in v1, barrier seat profile in Phase 5 with barriers.

4. **Cross-frame / diaphragm connection detail:** Do diaphragms need connection plates, stiffeners, or gusset plates modeled, or are they simplified beam shapes between girders? Recommendation: simplified shapes in v1.

5. **Camber input:** When camber data is available, how is it provided — as a table of ordinate offsets at tenth-points along each girder, or as a parabolic formula? This affects how the girder sweep path is vertically adjusted.

6. **Naming convention for Autodesk App Store product:** The tool needs a name. Working suggestions: "BridgeForge", "CivilBridge", "OneSpan", "BridgeDirect". Pick something that won't conflict with existing trademarks.