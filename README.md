# One-Click Bridge Modeler for Civil 3D

A Dynamo-based parametric bridge modeler that generates 3D AutoCAD solids directly in Civil 3D from alignment, profile, surface, and tabular inputs.

## Status

**Work in progress.** See [docs/scope.md](docs/scope.md) for the full project scope and development plan.

## Problem

Autodesk has no native bridge modeling tool for Civil 3D. The current multi-product workflow (InfraWorks → Inventor → Civil 3D) produces models that must be exploded into 2D linework for drawing production — destroying the link between 3D model and 2D deliverables.

## Approach

- Read Civil 3D alignments, profiles, and surfaces via data shortcuts
- Generate bridge geometry as AutoCAD 3D solids on a disciplined layer structure
- Enable a single-source-of-truth xref workflow where sheets reference the bridge drawing directly
- Parametric: change inputs, re-run, solids regenerate

## Requirements

- Autodesk Civil 3D 2024+
- Dynamo for Civil 3D (ships with Civil 3D)

## License

[MIT](LICENSE)
