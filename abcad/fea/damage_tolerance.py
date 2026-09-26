"""
abcad/fea/damage_tolerance.py — flaw-seeded stiffness-retention test: THE damage-tolerance metric (TM-3).

MISSION CONTEXT (2026-07-03)
    The project goal is DAMAGE-TOLERANT single-material printable architectures. Printability is
    gated (abcad/printing/print_audit.py); this tool adds the mission metric itself: how much effective
    stiffness a lattice RETAINS when material goes missing — modeling print defects, service damage, or
    deliberate strut removal. Field practice probes exactly this with missing-strut/flaw studies (e.g.
    "Breaking better: how imperfections increase fracture resistance in architected lattices",
    arXiv:2504.08873; Portela's woven/double-network work shows entangled architectures keep load paths as
    members fail), and 2026 agentic-design systems close their loops with FEA feedback (arXiv:2605.19717,
    2605.17448). This tool is that closure for our loop, built ENTIRELY from validated house pieces.

WHAT IT DOES (composition of trusted tools — no new physics)
    STL --voxelize_stl--> occupancy --keep_largest--> rod grid --add_plates--> plated grid
        --[per replicate: carve N spherical flaws in the ROD region (plates protected), re-clean]-->
        intact.msh + damaged_k.msh (+ A0/H0 sidecars, identical nominal geometry)
        --subprocess: run_tension.py (linear, TRUSTED reference physics) per mesh-->
        E_eff per variant --> retention R_k = E_damaged/E_intact --> mean/min retention = the score.

    Linear small-strain is the right first metric: it is the validated reference (91.8 MPa lineage), it
    is scale-invariant, and stiffness retention under flaws is the standard first-order damage-tolerance
    screen. (Strength/toughness retention needs the finite-strain path — see TODO.)

INTERPRETATION
    removed_rod_frac f is the flaw dose (fraction of member material carved). A hypothetical
    "every-strut-counts-equally" lattice loses stiffness at least proportionally (R <= 1 - f); redundant,
    entangled architectures hold R well above that line, brittle load-path architectures fall below it.
    We report R alongside (1 - f) so the margin is explicit. min-retention across replicates is the
    headline score (worst sampled flaw placement).

USAGE (cad_env python — meshing needs pyvista/vtk; the solves subprocess into run_tension.py which
    conda-runs sfepy_env internally):
      "$ABCAD_CAD_PYTHON" -m abcad.fea.damage_tolerance \
          --stl out/woven_fea_small.stl --voxel 1.0 --samples 3 --nflaws 3 --flaw-radius-mm 1.5
    Defaults reproduce the validated fast-proxy meshing recipe (voxel 1.0 / plate 2.0 / overlap 0.8:
    ~8k hex, ~1 GB-class solves). MEMORY: serial subprocess solves; run under a swap watchdog for big meshes.

INTERPRETERS
    The per-mesh solves run abcad/fea/run_tension.py as a standalone file under the SfePy-side Python:
    $ABCAD_SFEPY_PYTHON if set, else the ``sfepy_env`` conda env next to the running interpreter's env (or
    under the conda base found via $CONDA_EXE), else the running interpreter itself. Environment variables
    (ABCAD_FEA_SOLVER, ABCAD_BIOMIMETIC_PIPELINE, ...) are inherited by the subprocess.

OUTPUTS
    <out>/damage_tolerance.json   config + per-variant E_eff + retention summary (the QMS record)
    <out>/report.md               human-readable mini-report
    <out>/*.msh(.json)            the intact + damaged meshes (kept for inspection/re-solve)
    Default <out> = $ABCAD_OUT/damage_tolerance/<stl stem> (``./out/...`` when ABCAD_OUT is unset).

TODO (next rungs)
    - strength/energy retention via the finite-strain solver (run_tension_finite.py) at larger strain;
    - graded flaw-dose sweeps (retention curve R(f) instead of a single dose);
    - wire as an optional post-approval loop stage (ABCAD_DAMAGE_CHECK=1) once runtimes are budgeted.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

import numpy as np

# House interpreters / sibling tools (same conventions as run_tension.py / print_audit.py).
_HERE = os.path.dirname(os.path.abspath(__file__))
try:
    from abcad.fea.voxel_plate_mesh import (
        add_plates,
        keep_largest_component,
        occupancy_to_hex_msh,
        voxelize_stl,
    )
except ModuleNotFoundError as _e:
    if not (_e.name or "").startswith("abcad"):
        raise  # a real third-party dependency is missing; do not mask it
    # Standalone execution (this file run directly by a conda interpreter without abcad installed):
    # import the sibling module from this directory.
    sys.path.insert(0, _HERE)
    from voxel_plate_mesh import (  # type: ignore  # noqa: E402
        add_plates,
        keep_largest_component,
        occupancy_to_hex_msh,
        voxelize_stl,
    )

# The linear tension driver is always launched as a standalone FILE in the SfePy-side interpreter
# (which need not have abcad installed); it resolves its own imports.
RUN_TENSION = os.path.join(_HERE, "run_tension.py")

# Output root: ./out under the working directory unless ABCAD_OUT points elsewhere.
_OUT_ROOT = os.environ.get("ABCAD_OUT", "out")


def _default_sfepy_python() -> str:
    """Interpreter used for the per-mesh solves (see "INTERPRETERS" in the module docstring).

    Order: $ABCAD_SFEPY_PYTHON; the conda env named ``sfepy_env`` beside the env that runs this file
    (<base>/envs/<env>/bin/python -> <base>/envs/sfepy_env/bin/python); the same env under the conda
    base derived from $CONDA_EXE (<base>/bin/conda); finally the current interpreter.
    """
    explicit = os.environ.get("ABCAD_SFEPY_PYTHON")
    if explicit:
        return explicit
    candidates = []
    prefix = os.path.abspath(sys.prefix)  # e.g. <base>/envs/cad_env
    if os.path.basename(os.path.dirname(prefix)) == "envs":
        candidates.append(os.path.join(os.path.dirname(prefix), "sfepy_env", "bin", "python"))
    conda_exe = os.environ.get("CONDA_EXE")  # e.g. <base>/bin/conda when conda is initialized
    if conda_exe:
        base = os.path.dirname(os.path.dirname(os.path.abspath(conda_exe)))
        candidates.append(os.path.join(base, "envs", "sfepy_env", "bin", "python"))
    for cand in candidates:
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return sys.executable


SFEPY_PY = _default_sfepy_python()


def carve_flaws(
    plated: np.ndarray,
    is_plate: np.ndarray,
    voxel_mm: float,
    nflaws: int,
    flaw_radius_mm: float,
    rng: np.random.Generator,
) -> tuple:
    """Carve `nflaws` spherical voids (radius in mm) at random ROD-material sites; plates are immune.

    Flaw centers are drawn from solid rod voxels at least one flaw-radius away (in z) from the plate
    inner faces, so the grip bond itself is never the thing we test. Returns (damaged_grid,
    removed_rod_frac) where the fraction is relative to the ROD (member) volume — the flaw dose f.
    """
    rod = plated & ~is_plate
    rod_n = int(rod.sum())
    r_vox = max(int(round(flaw_radius_mm / voxel_mm)), 1)  # flaw radius in voxels (>= 1)

    # z-band of allowed centers: strictly between the plates, one flaw-radius clear of each inner face.
    # The two slabs are the first and last contiguous True runs of plate-occupied z-columns.
    run = np.where(is_plate.any(axis=(0, 1)))[0]
    breaks = np.where(np.diff(run) != 1)[0]
    # bot_top = top z-index of the bottom slab; top_bot = bottom z-index of the top slab
    bot_top = int(run[breaks[0]]) if len(breaks) else int(run[-1])
    top_bot = int(run[breaks[0] + 1]) if len(breaks) else int(run[0])
    lo, hi = bot_top + r_vox + 1, top_bot - r_vox - 1

    candidates = np.argwhere(rod[:, :, lo : hi + 1]) if hi >= lo else np.empty((0, 3), dtype=int)
    if len(candidates) == 0:
        raise RuntimeError(
            "no valid flaw sites between the plates (part too short vs flaw radius?)"
        )
    candidates[:, 2] += lo  # back to full-grid z indices

    damaged = plated.copy()
    X, Y, Z = np.ogrid[: plated.shape[0], : plated.shape[1], : plated.shape[2]]
    for c in candidates[rng.choice(len(candidates), size=nflaws, replace=False)]:
        sphere = (X - c[0]) ** 2 + (Y - c[1]) ** 2 + (Z - c[2]) ** 2 <= r_vox**2
        damaged &= ~(sphere & ~is_plate)  # carve members only; plates immune
    removed_rod_frac = 1.0 - float((damaged & ~is_plate).sum()) / rod_n
    return damaged, removed_rod_frac


def write_variant(
    occ: np.ndarray, voxel_mm: float, origin: tuple, msh_path: str, A0: float, H0: float
) -> dict:
    """Write a hex mesh + the A0/H0 sidecar (identical nominal geometry across variants)."""
    n_hex, n_nodes, gshape = occupancy_to_hex_msh(occ, voxel_mm, origin, msh_path)
    sidecar = {
        "n_hex": int(n_hex),
        "n_nodes": int(n_nodes),
        "voxel_mm": voxel_mm,
        "footprint_area_mm2": float(A0),
        "height_mm": float(H0),
        "grid": [int(g) for g in gshape],
    }
    with open(msh_path + ".json", "w") as fh:
        json.dump(sidecar, fh, indent=2)
    return sidecar


def solve_e_eff(msh_path: str, iter_dir: str, E: float, nu: float, strain: float) -> float:
    """Run the TRUSTED linear tension solve (run_tension.py) on a mesh; return E_eff [MPa]."""
    cmd = [
        SFEPY_PY,
        RUN_TENSION,
        "--msh",
        msh_path,
        "--iter_dir",
        iter_dir,
        "--E",
        str(E),
        "--nu",
        str(nu),
        "--strain",
        str(strain),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    with open(os.path.join(iter_dir, "e_eff.json")) as fh:
        return float(json.load(fh)["E_eff_MPa"])


def main(argv=None):
    """CLI entry point: intact + flaw-seeded replicate solves -> retention record + report."""
    ap = argparse.ArgumentParser(
        description="Flaw-seeded stiffness-retention (damage tolerance) of an STL lattice."
    )
    ap.add_argument("--stl", required=True)
    ap.add_argument(
        "--voxel", type=float, default=1.0, help="voxel size [mm] (1.0 = fast validated proxy)"
    )
    ap.add_argument("--plate", type=float, default=2.0)
    ap.add_argument("--overlap", type=float, default=0.8)
    ap.add_argument("--samples", type=int, default=3, help="independent damaged replicates")
    ap.add_argument("--nflaws", type=int, default=3, help="spherical flaws per replicate")
    ap.add_argument("--flaw-radius-mm", dest="flaw_r", type=float, default=1.5)
    ap.add_argument("--seed", type=int, default=20260703)
    ap.add_argument("--E", type=float, default=3000.0)
    ap.add_argument("--nu", type=float, default=0.40)
    ap.add_argument("--strain", type=float, default=0.01)
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)

    stem = os.path.splitext(os.path.basename(a.stl))[0]
    out = a.out or os.path.join(_OUT_ROOT, "damage_tolerance", stem)
    os.makedirs(out, exist_ok=True)

    # --- base grids (identical recipe to voxel_plate_mesh.build_plated_hex_mesh) ---
    print(f"[dt] voxelizing {a.stl} @ {a.voxel} mm ...", flush=True)
    occ, origin, v = voxelize_stl(a.stl, a.voxel)
    rod, kept = keep_largest_component(occ)
    # TM3-V2 (QMS-002): if keep-largest pruned a large fraction of the voxelized part, the
    # structure is DISCONNECTED at this voxel pitch (e.g. tangent contacts violating the
    # >=0.4 mm interpenetration weld rule, 2026-07-05 pitch-sweep round 1) — any solve on
    # the remnant is meaningless. Refuse loudly instead of producing a number.
    if kept < 0.70:
        raise RuntimeError(
            f"TM3-V2 INVALID: keep-largest retained only {kept:.2f} of voxelized material "
            f"(< 0.70) — part disconnected at voxel={v} mm. Check the >=0.4 mm "
            f"interpenetration weld rule (QMS-002 TM-5) or reduce voxel pitch."
        )
    plated, is_plate, origin2, meta = add_plates(rod, v, a.plate, a.overlap, origin)
    fib = np.argwhere(rod)
    # nominal footprint A0 = rod bounding box in x, y (inclusive voxel counts, hence +1) [mm^2]
    A0 = ((np.ptp(fib[:, 0]) + 1) * v) * ((np.ptp(fib[:, 1]) + 1) * v)
    H0 = plated.shape[2] * v  # plated specimen height [mm]
    print(
        f"[dt] grid={plated.shape} rod_kept={kept:.3f} A0={A0:.1f} mm^2 H0={H0:.1f} mm", flush=True
    )

    # --- intact reference ---
    m0 = os.path.join(out, "intact.msh")
    sc0 = write_variant(plated, v, origin2, m0, A0, H0)
    print(f"[dt] intact: {sc0['n_hex']} hex — solving ...", flush=True)
    E0 = solve_e_eff(m0, os.path.join(out, "fea_intact"), a.E, a.nu, a.strain)
    print(f"[dt] intact E_eff = {E0:.2f} MPa", flush=True)
    # TM3-V1 (QMS-002): a structural E_eff cannot exceed the material modulus (2% numerical
    # headroom). The 84 GPa reading on a degenerate remnant (2026-07-05) motivated this gate:
    # violations mean broken specimen/normalization — the run is INVALID, never a data point.
    if E0 > a.E * 1.02:
        raise RuntimeError(
            f"TM3-V1 INVALID: intact E_eff={E0:.1f} MPa exceeds material E={a.E:.0f} MPa — "
            f"degenerate specimen or broken A0/H0 normalization; no retention reported."
        )

    # --- damaged replicates ---
    samples = []
    for s in range(a.samples):
        rng = np.random.default_rng(a.seed + s)  # pinned seed per replicate (reproducible flaws)
        damaged, f = carve_flaws(plated, is_plate, v, a.nflaws, a.flaw_r, rng)
        cleaned, kept_d = keep_largest_component(damaged)
        mk = os.path.join(out, f"damaged_{s}.msh")
        sck = write_variant(cleaned, v, origin2, mk, A0, H0)
        Ek = solve_e_eff(mk, os.path.join(out, f"fea_damaged_{s}"), a.E, a.nu, a.strain)
        R = Ek / E0  # stiffness retention of this replicate
        samples.append(
            {
                "replicate": s,
                "seed": a.seed + s,
                "nflaws": a.nflaws,
                "flaw_radius_mm": a.flaw_r,
                "removed_rod_frac": round(f, 4),
                "kept_frac_after_damage": round(kept_d, 4),
                "n_hex": sck["n_hex"],
                "E_eff_MPa": round(Ek, 3),
                "retention": round(R, 4),
            }
        )
        print(
            f"[dt] damaged[{s}]: dose f={f:.3f}  E_eff={Ek:.2f} MPa  retention={R:.3f} "
            f"(proportional-loss floor {1 - f:.3f})",
            flush=True,
        )

    # --- summary record (the QMS evidence) ---
    rets = [s["retention"] for s in samples]
    doses = [s["removed_rod_frac"] for s in samples]
    summary = {
        "stl": os.path.abspath(a.stl),
        "mesh_recipe": {"voxel_mm": v, "plate_mm": a.plate, "overlap_mm": a.overlap},
        "flaw_model": {
            "samples": a.samples,
            "nflaws": a.nflaws,
            "flaw_radius_mm": a.flaw_r,
            "seed": a.seed,
            "mean_dose": round(float(np.mean(doses)), 4),
        },
        "intact_E_eff_MPa": round(E0, 3),
        "samples": samples,
        "mean_retention": round(float(np.mean(rets)), 4),
        "min_retention": round(float(np.min(rets)), 4),
        "note": "retention vs (1 - dose): above = redundant/damage-tolerant load paths, "
        "below = brittle load-path architecture. Linear small-strain stiffness metric.",
    }
    with open(os.path.join(out, "damage_tolerance.json"), "w") as fh:
        json.dump(summary, fh, indent=2)

    # --- human-readable mini-report ---
    md = [
        f"# Damage tolerance — {stem}",
        "",
        f"Intact E_eff = **{E0:.2f} MPa** (voxel {v} mm, {sc0['n_hex']} hex).",
        f"Flaw model: {a.samples} replicates x {a.nflaws} spherical flaws r={a.flaw_r} mm "
        f"(mean dose {np.mean(doses):.1%} of member material).",
        "",
        "| replicate | dose f | E_eff [MPa] | retention R | 1 - f |",
        "|---|---|---|---|---|",
    ]
    md += [
        f"| {s['replicate']} | {s['removed_rod_frac']:.3f} | {s['E_eff_MPa']} | "
        f"**{s['retention']:.3f}** | {1 - s['removed_rod_frac']:.3f} |"
        for s in samples
    ]
    md += [
        "",
        f"**Score: min retention = {summary['min_retention']:.3f}, "
        f"mean = {summary['mean_retention']:.3f}.** R above (1 - f) means the architecture "
        "carries load around flaws (redundant/entangled paths).",
    ]
    with open(os.path.join(out, "report.md"), "w") as fh:
        fh.write("\n".join(md))
    print(
        f"[dt] score: min retention = {summary['min_retention']:.3f} "
        f"(mean {summary['mean_retention']:.3f})  ->  {out}/damage_tolerance.json",
        flush=True,
    )


if __name__ == "__main__":
    main()
