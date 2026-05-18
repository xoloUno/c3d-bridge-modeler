"""Unit tests for src/girder_geometry.py.

Run with `pytest test/` from the repo root.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import aisc  # noqa: E402
import girder_geometry as gg  # noqa: E402
import units  # noqa: E402


@pytest.fixture(scope="module")
def table():
    return aisc.load()


# ----------------------------------------------------------------------
# Basic shape contract
# ----------------------------------------------------------------------

def test_returns_twelve_vertices(table):
    verts = gg.i_shape_profile_vertices_ft(aisc.get(table, "W14X22"))
    assert len(verts) == 12


def test_vertices_are_2tuples_of_floats(table):
    verts = gg.i_shape_profile_vertices_ft(aisc.get(table, "W14X22"))
    for v in verts:
        assert isinstance(v, tuple)
        assert len(v) == 2
        assert isinstance(v[0], float)
        assert isinstance(v[1], float)


def test_first_and_last_vertices_differ(table):
    # Outline is open-ended; the closing segment from V11 back to V0 is
    # implicit (caller marks the polyline closed). V11 and V0 must NOT
    # coincide, or the closing segment would be zero-length.
    verts = gg.i_shape_profile_vertices_ft(aisc.get(table, "W14X22"))
    assert verts[0] != verts[-1]


# ----------------------------------------------------------------------
# Top of top flange is at v = 0 (lines up with top_of_girder_flange elev)
# ----------------------------------------------------------------------

def test_top_edge_sits_at_v_zero(table):
    verts = gg.i_shape_profile_vertices_ft(aisc.get(table, "W14X22"))
    # V0 and V1 are the two top-of-top-flange corners
    assert verts[0][1] == 0.0
    assert verts[1][1] == 0.0


def test_bottom_edge_sits_at_minus_d_ft(table):
    shape = aisc.get(table, "W14X22")
    verts = gg.i_shape_profile_vertices_ft(shape)
    d_ft = units.in_to_ft(shape.d_in)
    # V6 and V7 are the two bottom-of-bottom-flange corners
    assert verts[6][1] == pytest.approx(-d_ft)
    assert verts[7][1] == pytest.approx(-d_ft)


# ----------------------------------------------------------------------
# Left-right symmetry — W-shapes are doubly-symmetric
# ----------------------------------------------------------------------

def test_outline_is_left_right_symmetric(table):
    """For every vertex at u, there is a corresponding vertex at -u with
    the same v. We check by sorting by v then |u|."""
    verts = gg.i_shape_profile_vertices_ft(aisc.get(table, "W36X150"))
    # Bucket vertices by v
    by_v: dict[float, list[float]] = {}
    for u, v in verts:
        by_v.setdefault(round(v, 9), []).append(u)
    for v_value, us in by_v.items():
        us_sorted = sorted(us)
        # Every level should have a left/right pair (or a pair of pairs
        # at the web/flange step). Sum of all u-values at a given v
        # should be zero up to float precision.
        assert sum(us_sorted) == pytest.approx(0.0, abs=1e-12)


# ----------------------------------------------------------------------
# Flange width and web thickness honored
# ----------------------------------------------------------------------

def test_flange_width_matches_bf(table):
    shape = aisc.get(table, "W36X150")
    verts = gg.i_shape_profile_vertices_ft(shape)
    bf_ft = units.in_to_ft(shape.bf_in)
    us = sorted(u for u, _ in verts)
    assert us[0] == pytest.approx(-bf_ft / 2.0)
    assert us[-1] == pytest.approx(+bf_ft / 2.0)


def test_web_thickness_matches_tw(table):
    shape = aisc.get(table, "W36X150")
    verts = gg.i_shape_profile_vertices_ft(shape)
    tw_ft = units.in_to_ft(shape.tw_in)
    # Web-side vertices are those at u = ±tw/2 (4 of them: V3, V4, V9, V10)
    web_us = sorted(set(round(u, 9) for u, _ in verts if abs(u) < units.in_to_ft(shape.bf_in) / 2.0 - 1e-9))
    assert len(web_us) == 2
    assert web_us[0] == pytest.approx(-tw_ft / 2.0)
    assert web_us[1] == pytest.approx(+tw_ft / 2.0)


def test_flange_thickness_matches_tf(table):
    shape = aisc.get(table, "W36X150")
    verts = gg.i_shape_profile_vertices_ft(shape)
    tf_ft = units.in_to_ft(shape.tf_in)
    d_ft = units.in_to_ft(shape.d_in)
    # Top flange occupies v in [-tf, 0]; bottom flange v in [-d, -(d-tf)]
    vs = sorted(set(round(v, 9) for _, v in verts))
    # Four distinct v-levels: 0, -tf, -(d-tf), -d
    assert len(vs) == 4
    assert vs[0] == pytest.approx(-d_ft)
    assert vs[1] == pytest.approx(-(d_ft - tf_ft))
    assert vs[2] == pytest.approx(-tf_ft)
    assert vs[3] == pytest.approx(0.0)


# ----------------------------------------------------------------------
# Units: returned in feet, NOT inches
# ----------------------------------------------------------------------

def test_values_are_feet_not_inches(table):
    """W14X22 has d=13.7 in. In feet that's ~1.14; in inches that's 13.7.
    A common mistake is to return inches directly — this guards against
    that by asserting a feet-scale value."""
    shape = aisc.get(table, "W14X22")
    verts = gg.i_shape_profile_vertices_ft(shape)
    d_in = shape.d_in  # 13.7
    d_ft = units.in_to_ft(d_in)  # ~1.14
    # Bottom edge should be near -1.14, not near -13.7
    v_bottom = min(v for _, v in verts)
    assert v_bottom == pytest.approx(-d_ft)
    assert v_bottom > -d_in  # i.e. less negative than -13.7


# ----------------------------------------------------------------------
# Vertex sequence integrity — outline traces a valid I shape without
# crossing itself. Walking the 12 segments must not self-intersect.
# ----------------------------------------------------------------------

def test_outline_does_not_self_intersect(table):
    """Walk the 12 closing-segment polygon and confirm no two
    non-adjacent edges cross. Catches a future refactor that scrambles
    vertex order."""
    verts = gg.i_shape_profile_vertices_ft(aisc.get(table, "W24X62"))
    n = len(verts)
    edges = [(verts[i], verts[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue  # adjacent (closing) edges share V0
            assert not _segments_cross(edges[i], edges[j]), (
                f"edges {i} ({edges[i]}) and {j} ({edges[j]}) intersect"
            )


def _segments_cross(seg_a, seg_b) -> bool:
    """Strict intersection test (no shared endpoints, no collinear overlap)."""
    (p1, p2), (p3, p4) = seg_a, seg_b
    d1 = _orient(p3, p4, p1)
    d2 = _orient(p3, p4, p2)
    d3 = _orient(p1, p2, p3)
    d4 = _orient(p1, p2, p4)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and (
        (d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)
    ):
        return True
    return False


def _orient(a, b, c) -> float:
    """Cross product of (b-a) × (c-a). Sign indicates left/right turn."""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


# ----------------------------------------------------------------------
# Spot checks on real AISC dims (table sourced from steelpy)
# ----------------------------------------------------------------------

def test_w14x22_dims(table):
    shape = aisc.get(table, "W14X22")
    verts = gg.i_shape_profile_vertices_ft(shape)
    d_ft = 13.7 / 12.0
    bf_ft = 5.0 / 12.0
    assert min(v for _, v in verts) == pytest.approx(-d_ft, abs=1e-9)
    assert max(u for u, _ in verts) == pytest.approx(bf_ft / 2.0, abs=1e-9)


def test_w36x150_dims(table):
    shape = aisc.get(table, "W36X150")
    verts = gg.i_shape_profile_vertices_ft(shape)
    d_ft = 35.9 / 12.0
    bf_ft = 12.0 / 12.0
    assert min(v for _, v in verts) == pytest.approx(-d_ft, abs=1e-9)
    assert max(u for u, _ in verts) == pytest.approx(bf_ft / 2.0, abs=1e-9)


# ----------------------------------------------------------------------
# Degenerate / pathological shape inputs raise rather than silently
# producing a broken polyline
# ----------------------------------------------------------------------

def test_zero_dimension_raises():
    bad = aisc.WShape(
        designation="BAD0", lb_per_ft=10.0, area_in2=1.0,
        d_in=0.0, bf_in=5.0, tw_in=0.2, tf_in=0.3,
    )
    with pytest.raises(ValueError):
        gg.i_shape_profile_vertices_ft(bad)


def test_flanges_overlap_raises():
    """2*tf >= d would put the two flanges into / through each other."""
    bad = aisc.WShape(
        designation="BAD1", lb_per_ft=10.0, area_in2=1.0,
        d_in=1.0, bf_in=5.0, tw_in=0.2, tf_in=0.6,
    )
    with pytest.raises(ValueError):
        gg.i_shape_profile_vertices_ft(bad)


def test_web_wider_than_flange_raises():
    bad = aisc.WShape(
        designation="BAD2", lb_per_ft=10.0, area_in2=1.0,
        d_in=10.0, bf_in=2.0, tw_in=3.0, tf_in=0.5,
    )
    with pytest.raises(ValueError):
        gg.i_shape_profile_vertices_ft(bad)
