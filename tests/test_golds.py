"""
tests/test_golds.py — gold / invariant tests over BANKED instrument evidence.

QMS traceability (ABCAD-QMS-002): each test enforces a named acceptance criterion against the curated
evidence records in results/ (see results/README.md) — no solves, no Blender, sub-second. The one test
that needs a large binary artifact (an STL) is marked ``slow`` and skips cleanly when the artifact is
absent; point ABCAD_ARTIFACTS_DIR at a directory holding ``woven_fea_small.stl`` to run it.

Run:  python -m pytest tests/test_golds.py            (fast subset: -m "not slow")
"""

from __future__ import annotations

import csv
import glob
import json
import os
import tempfile

import pytest

E_MAT = 3000.0  # material modulus [MPa] used by the TM-3 baseline protocol


@pytest.fixture(scope="module")
def damage_jsons(results_dir):
    """The 2026-07-05 TM-3 baseline records (one damage_tolerance.json per ranked part)."""
    return sorted(glob.glob(str(results_dir / "damage_tolerance/baseline/*/damage_tolerance.json")))


def test_damage_evidence_present(damage_jsons):
    """The 2026-07-05 QMS baseline ranked 8 parts; their records must exist."""
    assert len(damage_jsons) >= 8, f"only {len(damage_jsons)} damage records found"


def test_tm3_v1_material_bound(damage_jsons):
    """TM3-V1: no banked E_eff may exceed the material modulus (2% numerical headroom)."""
    for f in damage_jsons:
        d = json.load(open(f))
        assert 0 < d["intact_E_eff_MPa"] <= E_MAT * 1.02, f"{f}: E_eff over material bound"
        for s in d["samples"]:
            assert 0 < s["E_eff_MPa"] <= E_MAT * 1.02, f"{f} rep {s['replicate']}"


def test_tm3_retention_and_dose_ranges(damage_jsons):
    """Retentions in (0, 1.05]; doses small and physical (< 20% member material)."""
    for f in damage_jsons:
        d = json.load(open(f))
        for s in d["samples"]:
            assert 0.0 < s["retention"] <= 1.05, f"{f}: retention {s['retention']}"
            assert 0.0 <= s["removed_rod_frac"] < 0.20, f"{f}: dose {s['removed_rod_frac']}"


def test_zero_point_control_at_floor(results_dir):
    """QMS-002 §3.4 zero-point rule: the solid in-plane control sits at its own floor."""
    f = results_dir / "damage_tolerance/baseline/h_solid_inplane/damage_tolerance.json"
    d = json.load(open(f))
    # per-replicate margin = retention - proportional-loss floor (1 - dose)
    margins = [s["retention"] - (1.0 - s["removed_rod_frac"]) for s in d["samples"]]
    worst = min(margins)
    assert abs(worst) < 0.02, f"solid control off floor: worst margin {worst:+.4f}"


def test_smooth_release_candidate_certified(results_dir):
    """TM-2 gold: the release-candidate print file's banked audit says PRINT + watertight."""
    rows = list(csv.DictReader(open(results_dir / "print_audit/smooth/print_audit.csv")))
    row = next(r for r in rows if "x20_smooth" in r["file"])
    assert row["watertight"] == "True", "release candidate not watertight in banked audit"
    assert row["verdict_fdm"] == "PRINT", f"release candidate verdict {row['verdict_fdm']}"
    assert float(row["lost_frac_d0.8"]) <= 0.01, "thin-feature loss above 1% at 0.8 mm"


@pytest.mark.slow
def test_normalize_to_target_size(artifacts_dir):
    """Target-size normalization rescales an STL deterministically to a target max dimension."""
    pv = pytest.importorskip("pyvista")  # fdm_variants needs pyvista (conda cad_env)
    src = artifacts_dir / "woven_fea_small.stl"
    if not src.is_file():
        pytest.skip(f"large artifact not available: {src} (set ABCAD_ARTIFACTS_DIR)")
    from abcad.printing import fdm_variants as fv

    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tf:
        rec = fv.normalize_to_target_size(str(src), 42.0, tf.name)
        b = pv.read(tf.name).bounds
        mx = max(b[1] - b[0], b[3] - b[2], b[5] - b[4])
        os.unlink(tf.name)
    assert abs(mx - 42.0) < 0.02, f"normalized max dim {mx} != 42"
    assert abs(rec["new_max_mm"] - 42.0) < 0.02


def test_live_validation_certified_runs(results_dir):
    """TM-4 gold: the live validation of 2026-09-26 (results/agent_runs/validation_2026-09-26).

    Every acceptance check passes (E2E-4 on its repeat, which is recorded beside the first
    attempt), no chat request was truncated, every Phase-2-only run on the recorded failing emit
    ended certified through a single gate pass with the full chain in its manifest, and both full
    two-phase runs released the resident critic before Phase 1 and ended with a truthful manifest.
    """
    root = results_dir / "agent_runs"
    summary = json.load(open(root / "validation_2026-09-26/e2e_summary.json"))
    for check in ("E2E-1", "E2E-2", "E2E-3", "E2E-4", "E2E-5", "E2E-6", "E2E-7"):
        assert summary[check]["pass"], check
    assert summary["E2E-4_first_attempt"]["pass"] is False  # kept on record, not overwritten
    assert summary["daemon"]["truncated_nonzero"] == 0
    manifests = [json.load(open(p)) for p in sorted(root.glob("2026-09-26_*/run_manifest.json"))]
    assert len(manifests) == 8
    for m in manifests:
        if m["entry"]["origin"] != "use-code":
            continue
        assert m["terminal_reason"] == "certified"
        assert m["approved"] is True and m["ever_approved"] is True
        assert m["counters"]["gate_runs"] == 1
        assert m["fix_attempts_used"] <= 3
        assert m["manufacturability"]["deep_audit"]["autoscaled_variant"]["verdict"] == "PRINT"
        assert m["certification"]["status"] == "autoscaled_print"
    full = [m for m in manifests if m["entry"]["origin"] == "lora"]
    assert [m["terminal_reason"] for m in full] == ["certified", "approved_gated"]
    for run in summary["E2E-4"]["runs"]:
        assert run["released_models"] and run["phase1_before_phase2"]
    assert summary["E2E-4"]["orphaned_emitters_after"] == 0


def test_tm6_orientation_sweep_reproducible(results_dir):
    """TM-6 gold: re-analyzing the banked orientation sweep reproduces the banked record.

    The recorded "work" is the area to a common displacement, a stiffness-weighted quantity in this
    sweep (see docs/FRACTURE.md); the test pins reproducibility of the record, not its reading.
    """
    from abcad.fracture import tm6_analyze

    rec = json.load(open(results_dir / "fracture/tm6_result.json"))
    d_common, rows = tm6_analyze.analyze(str(results_dir / "fracture/orientation_sweep"))
    assert [r[0] for r in rows] == rec["angles_deg"]
    works = [r[3] for r in rows]
    for got, want in zip(works, rec["work_of_fracture"]):
        assert got == pytest.approx(
            want, rel=1e-12
        ), "work to common displacement drifted from the record"
    for got, want in zip([r[1] for r in rows], rec["peak_load"]):
        assert got == pytest.approx(want, rel=1e-12), "peak load drifted from the record"
    assert max(works) / min(works) == pytest.approx(rec["work_ratio_max_min"], rel=1e-12)
    assert rows[works.index(max(works))][0] == rec["peak_angle_deg"] == 45


def test_moose_validation_gate(results_dir):
    """TM-6 Stage A gate: MOOSE recovers E = 3000 MPa on the solid bar (stress / strain)."""
    rows = list(csv.DictReader(open(results_dir / "fracture/validate_uniaxial_out.csv")))
    last = rows[-1]
    e_eff = float(last["avg_stress_zz"]) / float(last["avg_strain_zz"])
    assert e_eff == pytest.approx(E_MAT, rel=1e-6), f"MOOSE E_eff {e_eff} != {E_MAT}"


def test_finite_strain_validation_record(results_dir):
    """FEA gold (SOP-001 acceptance rule): the finite-strain solver recovers the block modulus within
    5 %, the lattice small-strain modulus agrees with the linear reference on the same mesh within a
    few percent, every validation step converged, and the oversized-step diagnostic is flagged."""
    base = results_dir / "fea_tension/finite_strain_validation"
    rec = json.load(open(base / "record.json"))

    def rows(name):
        return list(csv.DictReader(open(base / name)))

    # Block: E_eff from the first loaded step (nominal stress / strain) within 5 % of E.
    blk = rows(rec["block_validation"]["csv"])
    e_blk = float(blk[1]["nominal_stress_MPa"]) / float(blk[1]["strain"])
    assert e_blk == pytest.approx(E_MAT, rel=0.05), f"block E_eff {e_blk:.1f} not within 5 % of E"
    assert all(
        r["newton_converged"] == "1" for r in blk
    ), "block validation has an unconverged step"

    # Lattice: small-strain E_eff agrees with the linear solve on the same mesh (within 5 %).
    lat = rows(rec["lattice_validation"]["csv"])
    e_lat = float(lat[1]["nominal_stress_MPa"]) / float(lat[1]["strain"])
    e_lin = json.load(open(results_dir / "fea_tension/woven_fea_tiny_linear/e_eff.json"))[
        "E_eff_MPa"
    ]
    assert e_lat == pytest.approx(e_lin, rel=0.05), f"lattice {e_lat:.2f} vs linear {e_lin:.2f} MPa"
    assert all(
        r["newton_converged"] == "1" for r in lat
    ), "lattice validation has an unconverged step"

    # The single oversized step is the documented counter-example: it must be marked unconverged.
    bad = rows(rec["step_size_limitation"]["csv"])
    assert bad[1]["newton_converged"] == "0", "the oversized-step diagnostic should be unconverged"
