"""
test_enamel_logic.py — Blender/CAD-free unit tests for the enamel decussation geometry core.

House pattern: prove the generator MATH cheaply before spending RAM on a sweep.
Covers the parts that encode the biology: hex-ring packing counts, the three twist laws, the
decussation (alternating-sign twist between neighbouring rings), and bridge placement.

Run:  python -m pytest tests/test_enamel_logic.py   (fast suite; numpy only — the STL sweep
dependencies numpy-stl / pyvista are imported lazily and are not needed here)
"""

from __future__ import annotations

import math
from collections import Counter

import pytest

from abcad.generators import enamel as E


@pytest.mark.parametrize("N", [0, 1, 3, 5])
def test_hex_ring_counts(N):
    """Ring k holds 6k rods; total for N rings = 1 + 3N(N+1) (centered hexagonal number)."""
    pos = E.hex_ring_positions(N, 0.6)
    assert len(pos) == 1 + 3 * N * (N + 1), f"N={N}: got {len(pos)}"


def test_hex_ring_tally():
    """Ring index tally: ring k appears exactly 6k times (k>=1), the centre once."""
    pos = E.hex_ring_positions(5, 0.6)
    c = Counter(r for _, _, r, _ in pos)
    assert c[0] == 1
    for k in range(1, 6):
        assert c[k] == 6 * k, f"ring {k}: {c[k]}"


def test_ring_radius():
    """Ring k rods sit at radius k*spacing."""
    pos = E.hex_ring_positions(3, 0.6)
    for x, y, ring, _ in pos:
        assert abs(math.hypot(x, y) - ring * 0.6) < 1e-9


def test_twist_laws_endpoints():
    """All laws give 0 at z=0 and the full Δθ at z=H; only accelerating lags at the midpoint."""
    H, dth = 5.0, 60.0
    for kind in ("linear", "accelerating", "sigmoid"):
        assert abs(E.twist_angle(0.0, H, dth, kind)) < 1e-12
        assert abs(E.twist_angle(H, H, dth, kind) - math.radians(dth)) < 1e-9
    mid = {k: E.twist_angle(H / 2, H, dth, k) for k in ("linear", "accelerating", "sigmoid")}
    # accelerating (u^2) is below linear at the midpoint; sigmoid crosses linear at the middle
    assert mid["accelerating"] < mid["linear"]
    assert abs(mid["sigmoid"] - math.radians(dth) / 2) < 1e-6


def test_decussation_sign_flip():
    """The default profile alternates twist sign between neighbouring rings — the crossing."""
    P = E.Params()
    signs = [math.copysign(1, P.ring_rot(k)) for k in range(1, len(P.ring_rotation))]
    flips = sum(1 for a, b in zip(signs, signs[1:]) if a != b)
    assert flips >= 3, f"expected alternating decussation, got signs {signs}"


def test_rod_centerline_shape_and_twist():
    """Rod centerline has z_samples points, constant radius, and ends at the full twist."""
    P = E.Params()
    radius = 2 * P.center_spacing
    cl = E.rod_centerline(0.0, radius, 30.0, P.thickness, P.z_samples, "linear")
    assert cl.shape == (P.z_samples, 3)
    r = (cl[:, 0] ** 2 + cl[:, 1] ** 2) ** 0.5
    assert abs(r.max() - radius) < 1e-9 and abs(r.min() - radius) < 1e-9  # constant radius
    end_theta = math.atan2(cl[-1, 1], cl[-1, 0])
    assert abs(end_theta - math.radians(30.0)) < 1e-6  # full twist reached


def test_center_rod_is_axial():
    """The center rod (radius 0) is a straight axial segment, not a helix."""
    cl = E.rod_centerline(0.0, 0.0, 45.0, 5.0, 24, "accelerating")
    assert (abs(cl[:, 0]) < 1e-12).all() and (abs(cl[:, 1]) < 1e-12).all()


def test_bridge_count_and_scale():
    """Bridges = sum over rings of (6k rods) x n_layers; no_bridges -> none."""
    P = E.Params()
    segs = E.bridge_segments(P)
    expected = sum(6 * k for k in range(1, P.n_rings + 1)) * P.n_bridge_layers
    assert len(segs) == expected, f"{len(segs)} != {expected}"
    # no_bridges -> none
    assert E.bridge_segments(E.Params(bridges=False)) == []
