# Bridge Template Drawing

This directory holds the starter Civil 3D template drawing that ships
with the One-Click Bridge Modeler. The `template_dwg` field in
`Phase1Params` (see `test/params.phase1.example.json`) points at a
project-customized copy of this template; the geometry-generation
slices load it at the start of a Create-Bridge run to pull layer,
style, and IFC Property Set definitions into the active drawing.

## Authoring status

`bridge_template.dwg` is **authored manually in Civil 3D 2024 on
Windows** — see the "Bridge template DWG" entry under "Phase 1
verification" in [`MANUAL-TASKS.md`](../MANUAL-TASKS.md). The DWG is
not generated from code (a valid C3D template requires C3D-side AEC
dictionary objects, sample line styles, and PropSet definitions that
cannot be authored from macOS or from Python). This README is the
source of truth for what the manually-authored DWG must contain.

## Per-project workflow

1. The tool ships `templates/bridge_template.dwg` with the layers,
   linetypes, skeleton styles, and IFC Property Set Definitions
   listed below pre-built.
2. The project lead copies it to the project working directory
   (e.g. `Z:/ProjectX/Bridge/BRG01-template.dwg`) and customizes per
   DOT — typically swapping ACI colors, extending PropSets with
   DOT-specific fields, or adding standard block definitions.
3. Each bridge's params JSON sets `template_dwg` to the project
   copy's path. Multiple bridges in one project can share a single
   template or each can point at its own copy.
4. The tool only reads from the template; it never writes back. No
   round-trip risk on the shipped file.

## Layer Structure

All bridge geometry lives on component-level layers (no per-element
numbering — element identity lives on each solid as xdata or IFC
PropSet values). Below-grade column / stem / wingwall portions and
all footings use linetype `DASHED`; everything else is `Continuous`.
Colors are AutoCAD Color Index (ACI) starting recommendations — DOTs
typically override them per their CAD standards.

### Skeleton layers (reference geometry)

| Layer | Color | Linetype | Notes |
|---|---|---|---|
| `BRIDGE-SKELETON-SUPPORT` | 6 (magenta) | Continuous | Sample lines at support stations |
| `BRIDGE-SKELETON-GIRDER`  | 4 (cyan)    | Continuous | Girder sub-alignments + profiles |
| `BRIDGE-SKELETON-EDGE`    | 5 (blue)    | Continuous | Edge-of-deck sub-alignments |
| `BRIDGE-DECK-SURFACE`     | 8 (gray)    | Continuous | Top-of-deck TIN surface (frozen by default) |

### Solid layers — superstructure (Phase 1)

| Layer | Color | Linetype | Notes |
|---|---|---|---|
| `BRIDGE-DECK`         | 7 (white/black) | Continuous | Deck slab solid(s) |
| `BRIDGE-DECK-TOPPING` | 8 (gray)        | Continuous | Topping pavement (optional) |
| `BRIDGE-DECK-HAUNCH`  | 51              | Continuous | Haunch solids |
| `BRIDGE-GIRDER`       | 1 (red)         | Continuous | Girder solids (steel or precast) |
| `BRIDGE-DIAPH-END`    | 30              | Continuous | End diaphragms (Phase 2+) |
| `BRIDGE-DIAPH-INT`    | 30              | Continuous | Intermediate diaphragms (Phase 2+) |
| `BRIDGE-BEARING`      | 6 (magenta)     | Continuous | Bearing devices (Phase 1b+) |
| `BRIDGE-PEDESTAL`     | 35              | Continuous | Bearing pedestals on pier cap |

### Solid layers — substructure (Phase 1b+)

| Layer | Color | Linetype | Notes |
|---|---|---|---|
| `BRIDGE-PIER-CAP`            | 2 (yellow) | Continuous | Pier / bent cap |
| `BRIDGE-PIER-COL`            | 3 (green)  | Continuous | Column above EG |
| `BRIDGE-PIER-COL-BELOW`      | 3 (green)  | DASHED     | Column below EG |
| `BRIDGE-PIER-FTG`            | 3 (green)  | DASHED     | Pier footing / pile cap (exclusively below grade) |
| `BRIDGE-PIER-PILE`           | 3 (green)  | DASHED     | Pier piles (Phase 4+) |
| `BRIDGE-ABUT-STEM`           | 40         | Continuous | Abutment stem above EG |
| `BRIDGE-ABUT-STEM-BELOW`     | 40         | DASHED     | Abutment stem below EG |
| `BRIDGE-ABUT-BACKWALL`       | 40         | Continuous | Abutment backwall |
| `BRIDGE-ABUT-WINGWALL`       | 41         | Continuous | Wingwall above EG |
| `BRIDGE-ABUT-WINGWALL-BELOW` | 41         | DASHED     | Wingwall below EG |
| `BRIDGE-ABUT-FTG`            | 40         | DASHED     | Abutment footing (exclusively below grade) |
| `BRIDGE-ABUT-PILE`           | 40         | DASHED     | Abutment piles (Phase 4+) |

`DASHED` is loaded from `acad.lin`. Load it explicitly in the
template (`-LINETYPE → Load → DASHED → acad.lin`) so the linetype
table travels with the DWG; otherwise re-runs that touch a fresh
drawing have to load it on the fly via `db.LoadLineTypeFile`.

## Skeleton element styles

The skeleton layers carry C3D-native objects, not just AutoCAD
entities. Each needs a named style so the tool can reference it when
creating geometry and so the skeleton renders cleanly without
overwhelming the bridge drawing.

- **Sample line style** — used on `BRIDGE-SKELETON-SUPPORT`. Minimal
  label (station + skew), tick marks at deck edges. Define under
  Settings → Sample Line → Sample Line Styles.
- **Alignment style (skeleton)** — used on `BRIDGE-SKELETON-GIRDER`
  and `BRIDGE-SKELETON-EDGE`. No PI / direction labels; thin
  polyline display so sub-alignments stay snappable but visually
  unobtrusive.
- **Profile style (skeleton)** — used by the per-girder profiles.
  Default is fine; the tool just needs a named style to pass to
  `Profile.CreateByLayout`.
- **Profile label set + view style** — only relevant if the user
  creates a profile view for a girder sub-alignment. Not exercised
  in Phase 1, so a default is acceptable.

Suggested style names (so future code can reference them by string):

- `Bridge Skeleton — Sample Line`
- `Bridge Skeleton — Alignment`
- `Bridge Skeleton — Profile`

## IFC Property Set Definitions

Each bridge solid is tagged with an AEC Property Set at creation
time so IFC 4.3 export classifies elements correctly without manual
mapping. Phase 1 uses a single PropSet definition with text fields
that the tool fills in per-instance — this avoids maintaining a
separate PropSet for every element type.

**PropSet name:** `BRIDGE_IFC`
**Applies to:** `AcDbSolid3d`
**Fields (all manual, text):**

| Field name       | Purpose                                       | Example values |
|---               |---                                            |---             |
| `IfcEntity`      | IFC 4.3 entity type                            | `IfcSlab`, `IfcBeam`, `IfcColumn`, `IfcFooting`, `IfcAbutment`, `IfcBuildingElementProxy` |
| `PredefinedType` | IFC predefined type (blank when not used)      | `BASESLAB`, `GIRDER`, `BEAM`, `COLUMN` |
| `BridgeName`     | Bridge identifier from params                  | `BRG01` |
| `ElementId`      | Per-element identifier                         | `SPAN-1.G2`, `PIER-1.COL-2`, `ABUT-A.WW-L` |

Per-element-type values that the tool sets when attaching the
PropSet (matches the IFC Classification table in `scope.md`):

| Element       | `IfcEntity`                  | `PredefinedType` |
|---            |---                           |---               |
| Deck          | `IfcSlab`                    | `BASESLAB`       |
| Girder        | `IfcBeam`                    | `GIRDER`         |
| Haunch        | `IfcBuildingElementProxy`    | _(blank)_        |
| Pier Cap      | `IfcBeam`                    | `BEAM`           |
| Column        | `IfcColumn`                  | `COLUMN`         |
| Footing       | `IfcFooting`                 | _(blank)_        |
| Abutment      | `IfcAbutment`                | _(blank)_        |

Author the PropSet Definition via Civil 3D 2024's
**Manage → CAD Standards → Configure → Property Set Definitions**
panel, or via the `PROPERTYSETDEFINE` command. The definition is
stored in the drawing as an `AecDbPropertySetDef` dictionary object
and travels with the template DWG.

If a particular DOT requires extra IFC fields (`Material`,
`StructuralUsage`, etc.), add them to the project copy of the
template — the tool will leave unfamiliar manual fields untouched.
