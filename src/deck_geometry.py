"""Pure-math helpers for deck slab cross-section geometry.

The deck slab is bounded above by `top_of_deck` (which follows the
alignment profile + cross-slope) and below by a parallel surface
`deck_depth` lower. The slab's left and right edges are VERTICAL,
spanning between top and bottom surfaces.

Cross-section shape
-------------------
At any bearing line the cross-section is one of:

* **Parallelogram (4 vertices)** — when the deck top is a single
  linear segment across the width. This is the case for:
    - Super-elevated decks (e.g. `slope_left = -2%`, `slope_right = +2%`)
      where the two cross-slope sides combine into a single continuous
      plane.
    - Decks that don't straddle the crown (both edges on the same
      side of `crown_offset`).
  Shape: top-left → top-right → bottom-right → bottom-left.

* **Hexagon (6 vertices)** — when the deck straddles the crown AND
  the two cross-slopes have the same sign (typical crowned roadway:
  `slope_left = slope_right = -2%`, producing a tent-shaped peak at
  the crown). Shape:
    top-left → top-crown → top-right →
      bottom-right → bottom-crown → bottom-left.

The kink condition is `slope_left * slope_right > 0` AND
`deck_left_perp < crown_offset < deck_right_perp`.

Coordinate convention
---------------------
The cross-section lives in a 2D plane with axes `(u, v)` where:
  - `u` is along the bearing line (signed: more negative = alignment-
    left direction).
  - `v` is vertical world Z.

`u = 0` corresponds to the alignment-bearing crossing point. The
Civil-3D-side caller transforms each `(u, v)` vertex into world 3D
using `alignment.point_on_skewed_bearing` for XY and `v` directly for
Z. This means `u` is **perpendicular offset from alignment** — not
along-bearing distance — because that's what `point_on_skewed_bearing`
consumes. See module docstring of `alignment.py` for the bearing
helper.

(Why perpendicular-offset instead of along-bearing? It matches the
existing skewed-bearing math used by sample lines, edge polylines,
girders, and haunches. Same helper, same units, no double-
transformation.)

Pure-logic module: must not import anything from the Civil 3D API
(`clr`, `Autodesk.*`). Importable on macOS for unit testing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


Vertex = Tuple[float, float]  # (perp_offset, z)


@dataclass(frozen=True)
class DeckCrossSection:
    """Closed polygon for the deck cross-section in (perp_offset, z) coords.

    `vertices` traces the outline in order:
      - top edge from left to right (2 vertices, or 3 with crown kink)
      - bottom edge from right to left (2 vertices, or 3 with crown kink)

    The polygon is closed implicitly: the last vertex connects back to
    the first.
    """
    vertices: Tuple[Vertex, ...]
    has_crown_kink: bool

    @property
    def is_parallelogram(self) -> bool:
        return not self.has_crown_kink


def deck_cross_section(
    *,
    deck_left_perp: float,
    deck_right_perp: float,
    deck_top_left_z: float,
    deck_top_right_z: float,
    deck_depth: float,
    crown_perp: Optional[float] = None,
    deck_top_crown_z: Optional[float] = None,
) -> DeckCrossSection:
    """Build the deck cross-section polygon.

    If `crown_perp` and `deck_top_crown_z` are both provided AND
    `deck_left_perp < crown_perp < deck_right_perp`, the result is a
    6-vertex hexagon with a kink at the crown. Otherwise it's a
    4-vertex parallelogram.

    The caller is responsible for the crown-kink detection logic
    (whether `slope_left * slope_right > 0` etc.) — this builder just
    consumes the deck-top elevations and decides shape based on the
    presence of `crown_perp` / `deck_top_crown_z`.
    """
    if deck_left_perp >= deck_right_perp:
        raise ValueError(
            f"deck_left_perp ({deck_left_perp}) must be < deck_right_perp "
            f"({deck_right_perp})"
        )
    if deck_depth <= 0.0:
        raise ValueError(f"deck_depth must be > 0; got {deck_depth}")

    has_crown_kink = (
        crown_perp is not None
        and deck_top_crown_z is not None
        and deck_left_perp < crown_perp < deck_right_perp
    )

    if has_crown_kink:
        vertices = (
            (deck_left_perp, deck_top_left_z),                       # 0
            (crown_perp, deck_top_crown_z),                          # 1
            (deck_right_perp, deck_top_right_z),                     # 2
            (deck_right_perp, deck_top_right_z - deck_depth),        # 3
            (crown_perp, deck_top_crown_z - deck_depth),             # 4
            (deck_left_perp, deck_top_left_z - deck_depth),          # 5
        )
    else:
        vertices = (
            (deck_left_perp, deck_top_left_z),                       # 0
            (deck_right_perp, deck_top_right_z),                     # 1
            (deck_right_perp, deck_top_right_z - deck_depth),        # 2
            (deck_left_perp, deck_top_left_z - deck_depth),          # 3
        )

    return DeckCrossSection(vertices=vertices, has_crown_kink=has_crown_kink)


def crown_kink_present(
    *,
    slope_left_pct: float,
    slope_right_pct: float,
    deck_left_perp: float,
    deck_right_perp: float,
    crown_perp: float,
) -> bool:
    """Decide whether the deck cross-section needs a crown-vertex kink.

    Two conditions must hold:
      1. The crown is strictly between the deck edges
         (`deck_left_perp < crown_perp < deck_right_perp`).
      2. The two cross-slopes have the same sign (`slope_left × slope_right
         > 0`). When they have opposite signs (super-elevated case), the
         elevation chain produces a single continuous plane across the
         crown — no kink.

    A slope of exactly zero is treated as "no kink contribution from
    that side"; the function returns False if either slope is zero
    (continuous top edge regardless of crown position).
    """
    if not (deck_left_perp < crown_perp < deck_right_perp):
        return False
    return slope_left_pct * slope_right_pct > 0.0
