"""
test_helicoidal_logic.py — Pure-Python unit tests for the helicoidal generator's geometry MATH.

These tests exercise everything that does NOT require Blender (rotation laws, layout, derived geometry),
so the logic can be validated on a machine without ``bpy``. The Blender build itself is verified
separately on a machine with Blender 4.2+ (the build control flow is covered against a mock ``bpy`` in
test_helicoidal_build_mock.py).

Run:  python -m pytest tests/test_helicoidal_logic.py   (fast suite; standard library only)
"""

from __future__ import annotations

import math

import pytest

from abcad.generators import helicoidal as H


def approx(seq_a, seq_b, tol=1e-6):
    """True iff two float sequences match elementwise within ``tol``."""
    return len(seq_a) == len(seq_b) and all(
        math.isclose(a, b, abs_tol=tol) for a, b in zip(seq_a, seq_b)
    )


# --------------------------------------------------------------------------------------------------
# Rotation laws — compare cumulative theta_k against hand-computed expected sequences.
# --------------------------------------------------------------------------------------------------
def test_constant():
    P = H.Params(progression="constant", delta_theta=10.0, num_plies=5)
    assert approx(H.cumulative_theta_sequence(P), [0, 10, 20, 30, 40]), "constant Θ_k = k·Δθ"


def test_graded():
    # Increment ramps linearly 2°→10° across the 4 steps of a 5-ply stack.
    P = H.Params(progression="graded", delta_min=2.0, delta_max=10.0, num_plies=5)
    assert approx(
        H.cumulative_theta_sequence(P), [0.0, 2.0, 6.6666667, 14.0, 24.0]
    ), "graded cumulative"


def test_exponential():
    P = H.Params(progression="exponential", delta_theta=10.0, ratio=1.1, num_plies=4)
    assert approx(H.cumulative_theta_sequence(P), [0.0, 10.0, 21.0, 33.1]), "exponential cumulative"


def test_fibonacci():
    P = H.Params(progression="fibonacci", delta_theta=10.0, num_plies=6)
    assert approx(H.cumulative_theta_sequence(P), [0, 10, 20, 40, 70, 120]), "fibonacci cumulative"


def test_herringbone():
    # Twist sign flips every 2 plies → chevron.
    P = H.Params(progression="herringbone", delta_theta=10.0, flip_every=2, num_plies=6)
    assert approx(H.cumulative_theta_sequence(P), [0, 10, 20, 10, 0, 10]), "herringbone cumulative"


def test_double_twist():
    P = H.Params(
        progression="double_twist", delta_a=10.0, delta_b=5.0, double_twist_offset=90.0, num_plies=6
    )
    assert approx(
        H.cumulative_theta_sequence(P), [0, 90, 10, 95, 20, 100]
    ), "double_twist interleaved"


def test_noise_determinism():
    P1 = H.Params(progression="noise", delta_theta=10.0, noise_sigma=3.0, seed=42, num_plies=20)
    P2 = H.Params(progression="noise", delta_theta=10.0, noise_sigma=3.0, seed=42, num_plies=20)
    P3 = H.Params(progression="noise", delta_theta=10.0, noise_sigma=3.0, seed=7, num_plies=20)
    s1, s2, s3 = (H.cumulative_theta_sequence(p) for p in (P1, P2, P3))
    assert approx(s1, s2), "noise is deterministic for a fixed seed"
    assert not approx(s1, s3), "noise differs across seeds"
    # Each ply stays within Δθ ± σ of the constant-pitch reference.
    ref = [k * 10.0 for k in range(20)]
    assert all(abs(a - b) <= 3.0 + 1e-9 for a, b in zip(s1, ref)), "noise bounded by ±σ"


@pytest.mark.parametrize(
    "prog",
    ["constant", "graded", "exponential", "fibonacci", "herringbone", "double_twist", "noise"],
)
def test_edge_single_ply(prog):
    P = H.Params(progression=prog, num_plies=1)
    seq = H.cumulative_theta_sequence(P)
    assert approx(seq, [0.0]), f"N=1 yields [0.0] ({prog})"


# --------------------------------------------------------------------------------------------------
# Derived geometry & fibre layout.
# --------------------------------------------------------------------------------------------------
def test_derived_geometry():
    P = H.Params(
        progression="constant", delta_theta=10.0, num_plies=36, ply_thickness=0.2, plate_size=40.0
    )
    d = H.derived_geometry(P)
    assert math.isclose(d["plies_per_180deg"], 18.0), "plies_per_180deg = 180/Δθ"
    assert math.isclose(d["pitch_mm"], 18.0 * 0.2), "pitch = n·d"
    assert math.isclose(d["total_height_mm"], 36 * 0.2), "total_height = N·d (solid)"
    assert math.isclose(d["total_sweep_deg"], 35 * 10.0), "total_sweep = (N-1)·Δθ"


def test_airgap_height():
    # With an air gap the stack is taller by N·gap.
    P = H.Params(
        progression="constant", num_plies=10, ply_thickness=0.2, interface="airgap", gap=0.1
    )
    d = H.derived_geometry(P)
    assert math.isclose(d["total_height_mm"], 10 * (0.2 + 0.1)), "airgap height = N·(d+gap)"


def test_fiber_centers():
    P = H.Params(plate_size=40.0, fiber_diameter=1.0, fiber_gap=0.4)  # spacing 1.4 → 28 fibres
    c = H.fiber_centers(P)
    assert len(c) == 28, "fibre count = floor(W/spacing)"
    assert min(c) >= -20.0 and max(c) <= 20.0, "fibres fit inside the footprint"
    assert abs((min(c) + max(c)) / 2.0) < 1.0, "fibre row is centred"


@pytest.mark.parametrize(
    "P",
    [
        H.Params(num_plies=0),
        H.Params(progression="constant", delta_theta=0.0),
        H.Params(interface="welded"),
        H.Params(fiber_style="ribbons"),
        H.Params(progression="spiral"),
    ],
)
def test_validate_rejects_bad_input(P):
    with pytest.raises(ValueError):
        P.validate()


def test_bpy_guarded():
    # The module must import without Blender (so these tests can run at all) and report bpy absence.
    assert H._HAVE_BPY is False or H._HAVE_BPY is True, "module imported without bpy"
    if not H._HAVE_BPY:
        # bpy-dependent calls raise a clear error when Blender is absent
        with pytest.raises(RuntimeError):
            H.clear_scene()
