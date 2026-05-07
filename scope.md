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

Civil 3D has no native `Bridge` API class. The "Bridges" node in Prospector only receives imported InfraWorks models — you cannot author bridge objects natively. Therefore the tool generates **AutoCAD `Solid3d` objects** organized on a disciplined layer structure, augmented by Civil 3D-native reference geometry (sample lines, alignments, profiles, surfaces).

The "intelligence" lives in the Dynamo script and its parameter inputs — not in the geometry itself. To update the bridge, the user changes inputs and/or moves skeleton geometry and re-runs the script. Solids are deleted and regenerated; skeleton elements are read or updated.

### Skeleton Architecture (Inspired by OpenBridge Modeler)

The tool creates a **skeleton** of C3D-native reference geometry before generating solids. This skeleton is visible, verifiable, snappable, and editable by the designer.

**Support Lines** are **C3D Sample Lines** placed at each pier/abutment station on the bridge alignment. They serve dual purpose: (1) defining the bridge skeleton for solid generation, and (2) providing section cut locations for drawing production. Sample lines can be perpendicular or skewed.

**Bearing Lines** are parallel to their respective support line, offset along the alignment direction. A support can have multiple bearing lines:
- Intermediate piers: one bearing line on each side of the support line (e.g., ±1.0' from pier CL)
- Abutments: one or two rows of bearings on the abutment seat
- A bearing line can overlap (coincide with) its support line

Girder span length is measured **bearing-line-to-bearing-line**, not support-line-to-support-line.

**Girder Sub-Alignments** are C3D Alignment + Profile pairs created by the tool for each girder. The horizontal alignment defines the girder's plan path (straight line for tangent bridges, arc for curved). The profile defines the top-of-flange elevation along the girder's length (computed from the deck bottom minus haunch depth via the elevation chain). These sub-alignments serve three purposes:
1. **Sweep path** for generating girder and haunch Solid3d objects
2. **Dimensionable reference** — the alignment IS a true arc, so DIMRADIUS works for plan-view radius dimensioning
3. **Queryable path** — downstream code (bearing placement, diaphragm connection points) queries the alignment/profile for positions

**Edge-of-Deck Sub-Alignments** define the deck width envelope. Like girder sub-alignments, these are true C3D alignments that are dimensionable (DIMRADIUS works for edge-of-deck radius on flared bridges where the edge is not a simple alignment offset).

All skeleton elements are placed on `BRIDGE-SKELETON-*` layers and can be frozen for drawing production.

### Two-Mode Workflow (Create and Update)

```
INITIAL CREATION (from JSON params):
  JSON params ──▶ Dynamo "Create Bridge" ──▶ Sample Lines (skeleton)
                                            ──▶ Sub-Alignments + Profiles
                                            ──▶ Solid3d objects (bridge model)
                                            ──▶ Top-of-Deck Surface

UPDATE (after designer edits):
  Designer moves sample lines, adjusts skew, edits JSON specs
       ──▶ Dynamo "Update Bridge" ──▶ Reads current sample line positions
                                   ──▶ Reads JSON for component specs
                                   ──▶ Regenerates sub-alignments + solids
```

**Source of truth split:**
- **Sample lines in the drawing** are authoritative for support locations (station, skew). The designer can move them between runs.
- **JSON params** are authoritative for component specifications (girder type, dimensions, haunch depth, etc.).
- **Sub-alignments, solids, and surfaces** are derived — always regenerated from the skeleton + params.
- No automatic write-back from drawing to JSON. An explicit "Export Params" command captures current state if needed.

### Drawing & Xref Workflow

```
[Bridge Parameters JSON]
        │
        ▼
[Dynamo Script] ──reads──▶ [Civil 3D Data Shortcuts]
        │                    • Alignment(s)
        │                    • Profile(s)
        │                    • EG Surface
        │                    • FG Surface
        ▼
[Bridge Drawing] ◀── single source of truth
  ├─ Skeleton: Sample Lines, Sub-Alignments, Sub-Profiles
  ├─ Solids: 3D Solid3d objects on BRIDGE-* layers
  ├─ Surface: Top-of-Deck TIN surface
  └─ Metadata: xdata + IFC Property Sets on each solid
        │
        ├──xref──▶ [Plan Sheet]     (Top viewport, Hidden style)
        ├──xref──▶ [Elevation Sheet] (Front viewport, Hidden style)
        ├──xref──▶ [Section Sheets]  (Section viewports at sample lines)
        └──xref──▶ [Profile Sheet]   (Profile view along alignment)
```

### Top-of-Deck Surface

After generating the deck solid, the tool creates a C3D TIN surface (`BRG01-DECK-TOP`) from sampled points on the deck top face. This surface enables:
- Spot elevation annotations using standard C3D surface labels
- Surface measurement tools (elevation difference, slope arrows)
- Sharing with the roadway team for composite surface assembly and grading ties

Layer: `BRIDGE-DECK-SURFACE` (frozen by default to avoid visual clutter).

### IFC Classification

Each solid is tagged with IFC Property Sets at creation time, enabling correct classification on IFC 4.3 export without manual mapping:

| Element | IFC Entity | PredefinedType |
|---|---|---|
| Deck | `IfcSlab` | BASESLAB |
| Girder | `IfcBeam` | GIRDER |
| Haunch | `IfcBuildingElementProxy` | — |
| Pier Cap | `IfcBeam` | BEAM |
| Column | `IfcColumn` | COLUMN |
| Footing | `IfcFooting` | — |
| Abutment | `IfcAbutment` | — |

### Template Drawing

A template `.dwg` ships with the tool containing standard definitions:
- `BRIDGE-*` layer definitions with standard colors and linetypes
- Alignment/profile/sample line styles for skeleton elements
- Property Set Definitions for IFC classification
- Pre-built corridor assemblies for future deck/barrier corridor integration
- Standard block definitions for bearing devices, expansion joints, etc.

**Per-project workflow:** Copy the template to the project directory, customize as needed (swap barrier shapes, adjust layer colors per DOT standards), and point the tool to the project copy via the `template_dwg` JSON parameter. Multiple bridges in the same project can share one template or each can have its own.

### Layer Structure

All bridge objects are placed on component-level layers (unnumbered). Individual element identity (girder number, pier ID, span, etc.) is stored as **xdata tags** on each solid, queryable via selection filters or scripts when per-element isolation is needed. This keeps the layer list clean regardless of bridge size.

```
Skeleton layers (reference geometry):
BRIDGE-SKELETON-SUPPORT        Sample lines at support stations
BRIDGE-SKELETON-GIRDER         Girder sub-alignments and profiles
BRIDGE-SKELETON-EDGE           Edge-of-deck sub-alignments
BRIDGE-DECK-SURFACE            Top-of-deck TIN surface (frozen by default)

Solid layers (3D model):
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
| `template_dwg` | string | Path to project-specific template drawing (layer defs, styles, PropSet defs). Copied from tool's default template and customized per project. |

### Span Definition (per span)

Each span is defined between two support points (piers, abutments, or straddle bents).

| Parameter | Type | Description |
|---|---|---|
| `span_id` | string | Identifier (e.g., "SPAN-1") |
| `start_support_id` | string | Reference to pier/abutment at start of span |
| `end_support_id` | string | Reference to pier/abutment at end of span |

### Superstructure Definition (per span)

Girder spacings are defined at **bearing lines** (not support line stations). For a flared bridge, spacings differ at each end; the tool linearly interpolates positions between them to construct girder sub-alignments. Edge-of-deck spacings define the deck width envelope and create edge-of-deck sub-alignments.

| Parameter | Type | Description |
|---|---|---|
| `girder_type` | enum | `W_SHAPE`, `PLATE_GIRDER`, `BOX_GIRDER`, `PRECAST_PRESTRESSED` |
| `girder_shape` | string | AISC designation (e.g., "W36X150") or plate girder dimensions |
| `girder_count` | int | Number of girders in this span |
| `girder_spacing_mode` | enum | `EQUAL`, `CUSTOM` |
| `left_edge_to_G1_start` | float | Left edge of deck to first girder CL at start bearing line |
| `girder_spacings_start` | float[] | Array of girder-to-girder spacings at start bearing line (G1→G2, G2→G3, ...) |
| `Gn_to_right_edge_start` | float | Last girder CL to right edge of deck at start bearing line |
| `left_edge_to_G1_end` | float | Left edge of deck to first girder CL at end bearing line |
| `girder_spacings_end` | float[] | Array of girder-to-girder spacings at end bearing line |
| `Gn_to_right_edge_end` | float | Last girder CL to right edge of deck at end bearing line |
| `girder_geometry` | enum | `STRAIGHT` (Phase 1: chorded between bearing lines), `CURVED_RADIUS` (Phase 2+: constant radius per girder), `FOLLOW_ALIGNMENT` (Phase 2+: offset from alignment curve) |
| `girder_radius` | float[] | Per-girder radius (only if `CURVED_RADIUS`); null otherwise |
| `girder_spacings_mid` | float[] | Spacings at midspan or intermediate pier stations (required for `CURVED_RADIUS` and `FOLLOW_ALIGNMENT` modes; null for `STRAIGHT`) |
| `deck_depth` | float | Deck slab thickness |
| `haunch_depth` | float | Haunch depth at girder web CL (constant per span; actual depth varies across flange width due to cross-slope) |
| `haunch_width_mode` | enum | `MATCH_TOP_FLANGE`, `CUSTOM` |
| `haunch_width` | float | Custom haunch width (if not matching top flange) |
| `haunch_chamfer` | float | Chamfer size at top outer corners of haunch (0 = no chamfer; e.g., 0.083 = 1 inch). Chamfer flares outward as a concrete fillet for formwork release. Deferred to post-Phase 1. |
| `topping_depth` | float | Topping pavement depth (0 if none) |
| `end_diaphragm` | bool | Generate end diaphragms at supports |
| `intermediate_diaphragm_count` | int | Number of intermediate diaphragms (Phase 2+) |
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

Each support is defined independently, allowing mixed types. On initial creation, the tool creates C3D sample lines from these parameters. On subsequent runs, the tool reads current sample line positions from the drawing (the designer may have moved them).

| Parameter | Type | Description |
|---|---|---|
| `support_id` | string | Unique identifier (e.g., "PIER-1", "ABUT-A") |
| `support_type` | enum | `ABUTMENT_SEAT`, `ABUTMENT_INTEGRAL`, `PIER_SINGLE_COLUMN`, `PIER_MULTI_COLUMN`, `PIER_WALL`, `STRADDLE_BENT`, `NONE` (jump span) |
| `station` | float | Station on alignment (initial creation only; sample line position is authoritative after first run) |
| `skew_angle` | float | Skew angle at this support (degrees from perpendicular) |
| `offset` | float | Lateral offset from alignment (+ = right) |
| `bearing_offsets` | float[] | Bearing line offsets from support station along alignment (e.g., `[-1.0, 1.0]` for intermediate pier with bearing lines on each side of cap CL; `[0.0]` for single bearing line coincident with support) |

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

### Phase 1: Superstructure — Straight & Flared Steel Girder Bridge (Weeks 5–12)

**Goal:** Model a complete single-span steel girder superstructure on a straight alignment, with support for flared bridges (variable girder spacing) and skewed supports. Establish the skeleton architecture and two-mode workflow.

**Superstructure deliverables:**
- AISC W-shape lookup table (`data/aisc_w_shapes.json`, W10–W44 series) with depth, web thickness, flange width/thickness, weight per foot
- W-shape girder generation: swept I-shape cross-section (single closed polyline profile → Region → `CreateSweptSolid`) along girder sub-alignments with `Bank = false` (girders stay plumb on curves)
- Plate girder generation from custom dimensions (same sweep approach, user-specified flange/web dims)
- Deck solid with configurable width, depth, cross slope, crown offset — lofted between cross-section profiles at bearing lines
- Haunch solids per girder: parallelogram cross-section (bottom = horizontal on flange, top = sloped matching deck bottom). Width = top flange width (automatic from AISC lookup). Depth = user input at web CL; varies across flange due to cross-slope. Chamfered top corners deferred to later update.
- Deck skew: `Solid3d.Slice(Plane)` to trim deck ends at skew angles
- Top-of-deck C3D TIN surface from sampled deck top face points
- Different girder types per span (W-shape in short spans, plate girder in long)

**Skeleton deliverables:**
- Sample Line Group creation for bridge supports
- Sample Lines at each support station with skew angle
- Girder sub-alignments: C3D Alignment + Profile per girder, computed from bearing line spacings (linear interpolation of offsets for flared bridges)
- Edge-of-deck sub-alignments for deck width envelope and dimensionability
- Two-mode workflow: "Create Bridge" from JSON, "Update Bridge" reading sample line positions

**Infrastructure deliverables:**
- Elevation chain module (pure math, macOS-testable): top of deck → girder top → girder bottom → bearing seat → top of cap → top of column → top of footing, computed per girder per support
- Phase 1 parameter schema extending Phase 0
- IFC Property Set classification on each solid at creation time
- Template drawing import (layers, styles, PropSet definitions)

**Deferred from Phase 1:** substructure (piers, abutments, foundations — see Phase 1b), cross-frames/diaphragms, corridor integration for deck, haunch chamfer, camber, bearing devices/pedestals.

**Input method:** JSON parameter file + Dynamo Player (two input nodes: `repo_root`, `params_path`)

### Phase 1b: Substructure — Piers, Abutments, Foundations (Weeks 13–18)

**Goal:** Complete the single-span bridge with substructure elements positioned by the elevation chain.

**Deliverables:**
- Single-column or multi-column pier with concrete rectangular cap
- Seat-type abutment with backwall and optional wingwalls
- Foundation solids (drilled shaft or spread footing — simplest two types)
- Column split at EG surface for above/below-grade layer assignment (`Solid3d.Slice` at EG plane)
- Bearing devices and pedestals (simple rectangular blocks)
- Elevation table output (CSV/text; matches manual calculation within 0.01')

### Phase 2: Curved Geometry & Multi-Span (Weeks 19–28)

**Goal:** Add curved bridge support as a geometry-mode switch, and extend to multi-span bridges.

**Curved geometry deliverables:**
- `FOLLOW_ALIGNMENT` girder mode: each girder sub-alignment is a lateral offset from the main alignment (the alignment API handles the curve math)
- `CURVED_RADIUS` girder mode: independent constant radius per girder (for widening bridges with non-concentric girder radii)
- Girder spacings at midspan / intermediate pier stations (required control points for curved modes)
- Superelevation-following mode for deck cross slope (haunch profiles lofted between stations with varying cross-slope)

**Multi-span deliverables:**
- Multiple spans with intermediate pier stations and individual skew angles
- Per-pier substructure type selection (different pier types per support)
- Per-span girder type selection (already in schema from Phase 1)
- Straddle bent support type
- `NONE` support type for jump spans (girders/deck continue, no substructure)
- Independent begin/end skew angles
- Deck as continuous solid across multiple spans (option vs. per-span)

**Cross-frame / diaphragm deliverables (higher priority than camber):**
- End diaphragms at supports
- Intermediate diaphragms (evenly spaced per span)
- Simplified beam shapes between girder webs (connection plates/stiffeners deferred)

### Phase 3: Drawing Production & Corridor Integration (Weeks 29–36)

**Goal:** Automate drawing production and optionally integrate C3D corridor for deck/barriers.

**Drawing production deliverables (formerly Phase 4):**
- Elevation/dimension tables as Civil 3D table objects or AutoCAD tables
- Quantity summary: deck volume, girder weights (from AISC tables), concrete volumes per element
- Auto-generate viewport configurations for plan, elevation, typical section

**Corridor integration (optional, additive):**
- C3D corridor for deck slab as alternative to direct solid (assembly from template drawing)
- Barrier/parapet shapes in corridor assembly
- Corridor solid extraction + skew trimming
- Edge-of-deck sub-alignments as corridor width targets
- Topping pavement as separate solid (corridor shape or direct solid)

### Phase 4: Advanced Features & App Store Preparation (Weeks 37–48)

**Goal:** Polish for release and add high-value features.

**Deliverables:**
- Camber: input as ordinate offsets at tenth-points per girder; girder sweep path adjusted vertically
- Shared substructure references (e.g., straddle bent shared between two bridges on different alignments)
- Multiple alignment support per bridge drawing
- Wingwall geometry: straight and flared, tapered to grade
- Integral abutment type
- Precast prestressed girder type
- Cast-in-place box girder type (single-cell, multi-cell)
- Bearing device types (elastomeric, pot, disc) beyond simple rectangular blocks
- Barrier/parapet seat geometry on deck edges
- Export to IFC 4.3 for coordination (leveraging Property Sets already attached in Phase 1)
- Dynamo Player UI with grouped parameter panels
- Parametric cross-section editor: draw shape once, assign variable dimensions, edit via parameter table (inspired by OBM deck templates, Revit parametric families, Inventor parameter workflow)
- Documentation and tutorial
- Autodesk App Store submission (if converting to C# plugin)

### Future: Post-v1

- **Rebar/reinforcement generation** (top priority post-v1 per Erik)
- Deck drainage (scuppers, drain locations)
- Bridge barriers / railings / median barriers as standalone solids (in addition to corridor-based barriers from Phase 3)
- Expansion joint locations and modeling
- Camber diagram generation
- Integration with Autodesk Structural Bridge Design for analysis
- Bill of steel (detailed girder weight breakdown by piece)
- Erection sequence visualization
- Connection to Site Composer / visionOS viewer for spatial review
- FreeCAD investigation: explore as civil infrastructure CAD option for Mac/Linux

---

## Technical Implementation Notes

### AISC Shape Database

Embed a lookup table of standard W-shapes (W10–W44 series) with dimensions: depth, web thickness, flange width, flange thickness, weight per foot, moment of inertia, section modulus. Source: AISC Steel Construction Manual, 16th Edition (publicly available dimension tables). This avoids requiring the user to manually input dimensions for standard shapes.

Format: `data/aisc_w_shapes.json` — a dict keyed by designation (e.g., `"W36X150"`) with numeric fields. Loadable on macOS for unit testing (no C3D dependency).

### Units & Metric Support

**Source data is stored in AISC's native units (inches, lb/ft).** This keeps the JSON identical to AISC's published values, making manual spot-checks against the printed Manual trivial. The JSON declares its units explicitly via a top-level `"units"` field (e.g., `"imperial_inches"`).

**Civil 3D bridge drawings in the US are typically in decimal feet.** Conversion happens at the geometry boundary — `src/units.py` provides pure-logic helpers (`in_to_ft`, `ft_to_in`, etc.) that the geometry-generation layer calls just before constructing swept-solid profiles. This single conversion point prevents drift from repeated conversions and keeps the data file canonical.

**Metric (Canadian) projects** use CISC tables — same I-shape geometry, dimensioned in mm with weights in kg/m. Phase 1 ships Imperial only. The schema reserves a slot for a parallel `data/cisc_w_shapes_metric.json` and a corresponding `"drawing_units"` field on params. Full metric support is a Phase 4 deliverable; the design now ensures it's a no-breaking-change addition later.

**Plate girders** are project-specific welded sections, not standard shapes — they are parameterized directly in JSON (web/flange dimensions per girder) rather than looked up. The Phase 4 parametric cross-section editor will unify the input model for both rolled and plate sections.

### Skeleton Creation via Sample Line API

The tool creates skeleton geometry using Civil 3D's Sample Line API (`SampleLine`, `SampleLineGroup`):

1. **Create Sample Line Group** on the bridge alignment: `SampleLineGroup.Create(alignmentId, groupName)`
2. **Create Sample Lines** at each support station with skew angle. Sample line properties: station position, length (deck width + overhang), angle (perpendicular + skew offset)
3. **Read Sample Lines on update**: iterate `SampleLineGroup.GetSampleLineIds()`, read each line's current station/angle — the designer may have moved them between runs

Sample lines on `BRIDGE-SKELETON-SUPPORT` layer. The group doubles as the section-cut source for drawing production viewports.

### Sub-Alignment Creation

Girder and edge-of-deck sub-alignments are C3D Alignment + Profile pairs created programmatically:

**Horizontal alignment** via `Alignment.Create(db, name, siteId, layerId, styleId, labelStyleId)`:
- Phase 1 (straight): two-point tangent alignment (start and end bearing line positions)
- Phase 2 (curved): arc alignment matching girder radius, or offset from main alignment

**Vertical profile** via `Profile.CreateByLayout(name, alignmentId, layerId, styleId)`:
- Add PVIs at bearing line stations via `PVICollection.AddPVI(station, elevation)`
- Elevation at each PVI = deck top − deck depth − haunch depth (from elevation chain)
- For Phase 1 (straight grade): two PVIs produce a straight profile
- For Phase 2: PVIs at each support + midspan for vertical curve following

Sub-alignment naming convention: `BRG01-G1`, `BRG01-G2`, ..., `BRG01-EDGE-L`, `BRG01-EDGE-R`

Girder sub-alignment offsets at bearing lines are computed from the girder spacing arrays:
```
G1_offset = -(deck_half_width) + left_edge_to_G1
G2_offset = G1_offset + girder_spacings[0]
G3_offset = G2_offset + girder_spacings[1]
...
```

For flared bridges, start and end offsets differ. The alignment is a straight line between the two offset positions (Phase 1) or an arc (Phase 2).

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

The elevation chain module is **pure math with no C3D dependency** — it takes profile elevation, cross slope, and component dimensions as inputs and returns all computed elevations. This makes it testable on macOS and usable as a standalone calculation check.

### Coordinate System & Alignment Following

All geometry is generated in Civil 3D world coordinates by querying the alignment for:
- Point (X, Y) at a given station
- Direction (tangent bearing) at a given station
- Superelevation at a given station (if applicable)

Cross-sections are then constructed perpendicular to the alignment (adjusted by skew angle) and the 3D solids are built by lofting or extruding between cross-sections.

For curved girders, three modes are supported:

1. **`FOLLOW_ALIGNMENT` (recommended default for curved bridges):** Each girder centerline and each edge-of-deck line is generated by querying the alignment at a constant lateral offset. This is the same approach Civil 3D corridors and OpenBridge Modeler use — the alignment already encodes the horizontal curve geometry (arcs, spirals), so each girder path is simply `alignment.PointAtStationOffset(station, offset)` sampled at regular intervals and connected. This produces girders that are concentric with the alignment and with each other. The girder cross-section is swept along this path.

2. **`CURVED_RADIUS`:** Each girder has an independently specified constant radius (not necessarily concentric with the alignment or with each other). This handles the case where the bridge widens along a curve and girder spacing increases, producing unique non-concentric radii per girder. The girder centerline is generated as a circular arc between support points at the specified radius.

3. **`STRAIGHT`:** Girder is a straight chord between support points. Used for tangent spans or for spans where girders are chorded with angle breaks at piers.

### Swept Solid Approach (Girders and Haunches)

Girders and haunches are generated using `Solid3d.CreateSweptSolid()`:

**I-Shape profile construction (for W-shapes and plate girders):**
1. Build a single closed `Polyline` tracing the I-shape cross-section outline (top flange → web → bottom flange → back around)
2. Convert to `Region` via `Region.CreateFromCurves()`
3. Sweep along the girder sub-alignment path

**Sweep path:**
- Must be an `Arc` or `Spline` entity — `Polyline` paths fail in `CreateSweptSolid`
- For Phase 1 (straight): use a `Line` entity (straight sweep = extrusion along path)
- For Phase 2 (curved): convert sampled alignment points to a `Spline`, or use `Arc` for constant-radius curves

**Key parameter: `Bank = false`** — girders must stay plumb (vertical web) even on curved paths. Without this, the cross-section tilts to follow the path curvature.

**Result:** `CreateSweptSolid` produces truly curved NURBS solids (not faceted/chorded). The resulting surfaces are smooth B-spline faces that render correctly in Hidden visual style and measure correctly with DIMRADIUS on the sub-alignment (which IS a true arc).

**Haunch profile:**
```
Cross-section: parallelogram
  ┌─────────────┐  ← top: sloped to match deck bottom (follows cross-slope)
  │             │
  └─────────────┘  ← bottom: horizontal, resting on girder top flange

Width  = AISC top flange width (automatic from shape lookup)
Height = haunch_depth at web CL; varies across flange width due to cross-slope
```

Chamfered top corners (concrete fillets flaring outward for formwork release) are deferred past Phase 1. When implemented, the cross-section becomes a hexagon:
```
  ╱─────────────╲  ← chamfers flare OUTWARD (wider at top than flange)
  │             │
  └─────────────┘
```

### Top-of-Deck Surface Creation

After generating the deck solid:
1. Sample points on the deck top face at a grid (e.g., every 5' along alignment × every 2' across width)
2. Create a C3D TIN surface (`TinSurface.Create(db, name)`) from the sampled points
3. Place on `BRIDGE-DECK-SURFACE` layer (frozen by default)

The surface enables standard C3D workflows: spot elevation labels, surface slope arrows, elevation difference analysis vs. FG, and sharing with the roadway team for composite surface assembly.

### IFC Property Set Attachment

Each solid gets IFC classification at creation time by attaching AutoCAD Property Sets:

1. Property Set Definitions are pre-built in the template drawing (or created by the tool if missing)
2. After solid creation, attach the appropriate Property Set: `PropertyDataServices.AddPropertySet(solidId, propSetDefId)`
3. Set property values (IFC entity type, predefined type, bridge name, element ID)

This ensures correct IFC 4.3 classification on export without requiring the user to manually map objects. The template drawing ships with standard IFC PropSet definitions.

### Solid Generation Strategy

- **Deck:** Lofted solid between cross-section profiles at each bearing line and at intermediate points (for tapering/curving). Cross-section = wide thin rectangle with cross slope applied. Ends trimmed at skew angles via `Solid3d.Slice(Plane)`.
- **Girders:** `CreateSweptSolid` along girder sub-alignment path. Cross-section = I-shape (from AISC lookup or custom plate dims). `Bank = false`.
- **Haunches:** `CreateSweptSolid` matching girder path. Cross-section = parallelogram (bottom = horizontal on flange, top = sloped matching deck bottom). Width = top flange width.
- **Pier caps:** Extruded solid along the cap length (perpendicular to bridge, adjusted for skew). Cross-section = rectangle or tapered rectangle.
- **Columns:** Extruded solid (cylinder or prism) from top of footing to top of column.
- **Footings:** Simple box solid placed at the calculated elevation.
- **Piles:** Cylinders or prisms from bottom of pile cap to tip elevation, with optional batter angle.
- **Abutments:** Composed of multiple box solids (seat, backwall, wingwalls).

### Below-Grade Layer Split

For each column, abutment stem, and wingwall solid:
1. Query EG surface elevation at the element's (X, Y) location
2. If the solid spans above and below this elevation, split it into two solids using `Solid3d.Slice(Plane)` at the EG elevation
3. Place the above-grade portion on the standard layer
4. Place the below-grade portion on the `-BELOW` layer (DASHED linetype)

Footings (pier and abutment) are exclusively below grade and do not need splitting — they are placed directly on their respective `FTG` layers with DASHED linetype.

### Two-Mode Workflow Implementation

**Create Bridge mode** (first run):
1. Load JSON params
2. Lock document, open transaction
3. Import template drawing definitions (layers, styles, PropSets) if not already present
4. Find alignment + profile via data shortcuts
5. Create Sample Line Group + Sample Lines at support stations
6. Compute girder offsets at each bearing line from spacing arrays
7. Create girder sub-alignments + profiles (Alignment.Create, Profile.CreateByLayout, AddPVI)
8. Create edge-of-deck sub-alignments
9. Run elevation chain per girder per support
10. Generate all solids (deck, girders, haunches, substructure)
11. Create top-of-deck surface
12. Attach IFC Property Sets to each solid
13. Commit transaction

**Update Bridge mode** (subsequent runs):
1. Load JSON params (component specs may have changed)
2. Lock document, open transaction
3. Read existing Sample Line positions from drawing (station, angle for each support)
4. Delete all objects on `BRIDGE-*` solid layers (not skeleton layers)
5. Recompute girder offsets from current spacing params
6. Recreate or update girder/edge sub-alignments + profiles
7. Run elevation chain with current geometry
8. Regenerate all solids
9. Recreate top-of-deck surface
10. Attach IFC Property Sets
11. Commit transaction

The mode is determined automatically: if a Sample Line Group for this bridge already exists, it's an update; otherwise it's a create.

### Re-Run Safety

- Skeleton elements (sample lines, sub-alignments) are **preserved** across update runs — the designer's edits are retained
- Derived elements (solids, surface) are **deleted and regenerated** — always reflect current inputs
- Future optimization: tag each solid with xdata linking it to its parameter source, and only regenerate changed elements (Phase 4+)

---

## Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| Dynamo `Solid3d` creation is slow for complex bridges (50+ solids) | Script takes 30+ seconds to run | Acceptable for re-generation workflow; optimize with direct API calls in Python if needed |
| AutoCAD Hidden visual style doesn't handle complex occlusion well | Drawing production requires manual cleanup | Test early (Phase 0 — verified OK); fall back to layer-based dashed lines if needed |
| Civil 3D alignment API doesn't expose superelevation data in Dynamo | Can't automate superelevation-following mode | Query via Python `.NET` API directly; superelevation is available in `Alignment.GetSuperElevation()` |
| Curved girder swept solids are geometrically complex | Loft/sweep failures on tight radii | `FOLLOW_ALIGNMENT` mode is simplest (uses alignment API offsets); `CURVED_RADIUS` mode uses segmented straight approximation (chorded at small intervals) as fallback |
| `CreateSweptSolid` path type restrictions | Polyline paths fail; only Arc/Spline/Line accepted | Use Line for straight (Phase 1), Spline for curved (Phase 2); fallback = segmented extrusion |
| Sample Line API may not expose skew angle programmatically | Can't read designer's skew edits on update | Investigate `SampleLine` properties; fallback = compute skew from sample line endpoint geometry |
| Sub-alignment accumulation on repeated create runs | Drawing fills with orphaned alignments | Detect existing sub-alignments by naming convention, delete before recreating |
| Scope creep: "just one more parameter" per bridge type | Timeline balloons from 10 weeks to 10 months | Strict phase gates; Phase 1 = straight steel girder superstructure only |
| AISC shape data licensing | Can't distribute shape tables | AISC dimensions are published in publicly available resources; include a curated subset; allow user override |
| Dynamo version compatibility across Civil 3D versions | Script breaks on upgrade | Target Civil 3D 2024 (Dynamo 2.x); use CPython 3 / PythonNet 3 exclusively; avoid deprecated nodes; document PythonNet 3 quirks in CLAUDE.md so they don't get re-discovered |
| Template drawing becomes stale as tool evolves | Layer/style definitions drift from what the tool expects | Version-stamp the template; tool checks template version on load and warns if outdated |

---

## Success Criteria

### Phase 0 (Proof of Concept) — COMPLETE 2026-05-06
- [x] Dynamo script reads alignment and profile from data shortcuts
- [x] Generates 3D solid deck and two pier placeholders
- [x] Solids display correctly in Hidden visual style viewport
- [x] Xref workflow verified: bridge drawing xref'd into separate sheet drawing

### Phase 1 (Superstructure)
- [ ] Complete superstructure (deck, girders, haunches) generated from JSON params
- [ ] Sample line skeleton created at support stations with correct skew angles
- [ ] Girder sub-alignments created with correct offsets and elevations
- [ ] Edge-of-deck sub-alignments created and dimensionable (DIMRADIUS works)
- [ ] Top-of-deck C3D surface created with spot elevation labels working
- [ ] IFC Property Sets attached to all solids; IFC export classifies elements correctly
- [ ] Flared bridge (different spacing at each end) generates correctly with linearly interpolated girder positions
- [ ] Skewed deck ends generated correctly via Solid3d.Slice
- [ ] Two-mode workflow: Create from JSON, Update reading sample line positions
- [ ] Elevation chain output matches manual calculation within 0.01'
- [ ] Re-run preserves skeleton, regenerates solids
- [ ] Template drawing imports layers/styles/PropSets on first run

### Phase 1b (Substructure)
- [ ] Single-column and multi-column piers generated with correct dimensions
- [ ] Seat-type abutment with backwall and wingwalls
- [ ] Column split at EG surface, below-grade portions on DASHED layers
- [ ] Bearing devices and pedestals placed at correct elevation chain positions
- [ ] Digital Applications team member validates on a real project structure

### Phase 2 (Curved & Multi-Span)
- [ ] 3-span curved bridge with mixed pier types generated correctly
- [ ] `FOLLOW_ALIGNMENT` mode produces concentric curved girders
- [ ] Skewed supports produce correct geometry at each pier
- [ ] Cross-frames/diaphragms generated between girders

### Phase 3 (Drawing Production & Corridor)
- [ ] Elevation/quantity tables auto-generated
- [ ] Viewport configurations for plan, elevation, section views
- [ ] Corridor-based deck (optional path) functional with skew trimming

---

## Estimated Timeline

At 2–5 hours/week evening development time:

| Phase | Weeks | Cumulative Hours | Target |
|---|---|---|---|
| Phase 0 (POC) | 4 | 8–20 hrs | ~~Month 1~~ COMPLETE |
| Phase 1 (Superstructure) | 8 | 16–40 hrs | Months 2–4 |
| Phase 1b (Substructure) | 6 | 12–30 hrs | Months 4–6 |
| Phase 2 (Curved & Multi-Span) | 10 | 20–50 hrs | Months 6–9 |
| Phase 3 (Drawing Production) | 8 | 16–40 hrs | Months 9–12 |
| Phase 4 (Advanced & App Store) | 12 | 24–60 hrs | Months 12–16 |

**Phase 0 + 1 + 1b produce a usable tool for simple bridges.** This is the MVP — a single-span, straight, steel girder bridge with piers and abutments. If this is all you ever build, it still saves hours per bridge.

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
| Bridge skeleton | C3D Sample Lines at support stations | Dual purpose: modeling skeleton + section view cut locations. Editable by designer between runs. Inspired by OBM skeleton architecture |
| Girder paths | C3D sub-alignments (Alignment + Profile per girder) | True arcs are DIMRADIUS-dimensionable; queryable for downstream geometry (bearings, diaphragms); sweep paths for CreateSweptSolid |
| Deck approach (Phase 1) | Direct Solid3d (not corridor) | Corridor deferred to Phase 3 as optional/additive. Solid approach is simpler, fully controlled, skew-trimmable via Slice |
| Template drawing | Copy-to-project `.dwg` with standard definitions | Per-DOT customization without modifying the tool's shipped template; layers, styles, PropSet defs, assemblies all pre-built |
| IFC classification | Property Sets attached at solid creation time | Correct IFC 4.3 export without manual mapping; definitions stored in template drawing |
| Source of truth split | Sample lines = geometry; JSON = component specs | No auto-write-back from drawing to JSON; explicit "Export Params" command captures current state if needed |

---

## Open Questions

### Resolved

1. ~~**Parameter input format:**~~ → JSON as primary, with an Excel-to-JSON converter as a future convenience. *Decided: Phase 1 uses JSON files loaded by Python nodes.*

2. ~~**Bearing device modeling detail:**~~ → Simple rectangular blocks in Phase 1b, typed bearings (elastomeric, pot, disc) in Phase 4. *Decided.*

3. ~~**Deck edge geometry:**~~ → Vertical edge through Phase 3. Barrier seat profile in Phase 4 with barriers. *Decided.*

4. ~~**Cross-frame / diaphragm connection detail:**~~ → Simplified beam shapes between girders in Phase 2. Connection plates/stiffeners/gussets deferred. *Decided.*

5. ~~**Camber input:**~~ → Deferred past Phase 1. When implemented (Phase 4): table of ordinate offsets at tenth-points per girder. *Decided.*

### Open

6. **Naming convention for Autodesk App Store product:** The tool needs a name. Working suggestions: "BridgeForge", "CivilBridge", "OneSpan", "BridgeDirect". Pick something that won't conflict with existing trademarks.

7. **Sample Line API skew angle access:** Can `SampleLine` properties expose the skew angle programmatically for read-back on update runs? Needs empirical testing in C3D 2024. Fallback: compute skew from sample line endpoint geometry.

8. **Sub-alignment style management:** Should girder/edge sub-alignments use a minimal no-label style (to avoid visual clutter), or a custom style with girder-specific label formatting? The template drawing should define these styles, but the exact styling needs design input.

9. **Top-of-deck surface sampling density:** What grid spacing produces an adequate TIN surface for spot elevations without excessive point count? Candidate: 5' along alignment × 2' across width. Needs testing with real deck geometry.

10. **Multi-bridge coordination in one drawing:** When multiple bridges share a drawing (e.g., mainline + ramp), how are namespaces handled? Current naming convention (`BRG01-*`) supports this, but the JSON schema doesn't define a bridge ID prefix yet.