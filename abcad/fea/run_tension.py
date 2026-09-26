"""
abcad/fea/run_tension.py — uniaxial TENSION FEA of a plated voxel-hex lattice mesh, via SfePy.

PURPOSE
    Drive a small-strain uniaxial TENSION solve on a plated hex mesh (produced by voxel_plate_mesh.py) by
    REUSING the proven biomimetic-lattice-pipeline FEA stack, and report the reaction force + the effective
    tensile modulus E_eff of the lattice.

WHY TENSION (not compression)
    Woven metamaterials are the stretchable / entanglement regime (fiber straightening, stretch lambda up to
    4); the bonded loading plates provide the tensile grip. NOTE: the stock SfePy solver is LINEAR
    small-strain, so |E_eff| is the same in tension and compression here — this run reports the small-strain
    tensile modulus. The dramatic woven stiffening is large-deformation and needs the finite-strain /
    strain-controlled solve in abcad/fea/run_tension_finite.py.

REUSE (NOT re-implemented — the stock physics is the source of truth)
    abcad.fea.fea_runner_amg.run_one_iteration(mesh, E, nu, disp, load_mode="tension", element_type="hex")
    — derived from biomimetic_pipeline.fea.fea_runner (same author): copies the mesh in as
    compound_enamel_lattice.msh, writes the problem-definition (stock compression_test.py with the tension
    displacement sign-flip + the 8-node-hex element-volume / centroid kernel swap), runs
    `conda run -n sfepy_env sfepy-run`, and parses the global results. The stock problem picks the
    Top/Bottom load faces from the mesh z-extremes (our plates), fixes the bottom, and pulls the top up by
    COMPRESS_DISP_MM. We add only the F -> E_eff reduction. Set ABCAD_FEA_SOLVER=amg to swap the direct
    linear solver for pyamg (large meshes); results are otherwise identical.

INPUTS (CLI)
    --msh PATH        plated hex .msh; expects sidecar <msh>.json (footprint_area_mm2 + height_mm) from
                      voxel_plate_mesh.py.
    --E MPA           Young's modulus of the printed solid [MPa]   (default 3000 — photopolymer resin)
    --nu              Poisson ratio                                 (default 0.40)
    --strain          nominal tensile strain to apply              (default 0.01 = 1%); disp = strain * H0.
    --iter_dir DIR    FEA working directory                        (default <msh dir>/fea_tension)
    --biomimetic PATH optional biomimetic-lattice-pipeline location to put on sys.path: a legacy source
                      tree holding orchestration/ + fea/, or a checkout root holding biomimetic_pipeline/.
                      The environment variables ABCAD_BIOMIMETIC_PIPELINE (preferred) or
                      BIOMIMETIC_PIPELINE take precedence over the flag. With none of them set, the
                      installed biomimetic-lattice-pipeline package is used.

OUTPUTS
    Prints reaction force [N], nominal stress [MPa], applied strain, and E_eff [MPa] (+ % of the solid E).
    Writes the SfePy field dump / result CSVs into <iter_dir> and an e_eff.json summary.

NOTES
    Linear elasticity is scale-invariant, so E_eff does not depend on the applied strain magnitude; we keep
    it at 1% so the result is unambiguously the small-strain modulus. The solve itself runs in `sfepy_env`
    via `conda run`; this outer driver only needs the stdlib + the biomimetic run context on sys.path, so it
    also runs as a standalone file (abcad/fea/damage_tolerance.py launches it that way).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Directory of this file: the standalone fallback imports the sibling fea_runner_amg.py from here.
_HERE = os.path.dirname(os.path.abspath(__file__))


def _biomimetic_location(cli_value: str) -> str:
    """Resolve the optional biomimetic-lattice-pipeline location (environment first, then the flag)."""
    return (
        os.environ.get("ABCAD_BIOMIMETIC_PIPELINE")
        or os.environ.get("BIOMIMETIC_PIPELINE")
        or cli_value
    )


def _import_runner(bp: str):
    """Import run_one_iteration, first putting an explicit biomimetic location on sys.path if given.

    Package import first (abcad installed or the repository root on sys.path); otherwise this file is
    running standalone in an interpreter without abcad, so import the sibling module by name.
    """
    if bp:
        if not os.path.isdir(bp):
            raise SystemExit(
                f"biomimetic_pipeline not found at {bp!r} "
                f"(pass --biomimetic or set $ABCAD_BIOMIMETIC_PIPELINE)"
            )
        sys.path.insert(0, bp)
    try:
        try:
            # reuse the stock physics (tension + hex variants)
            from abcad.fea.fea_runner_amg import run_one_iteration
        except ModuleNotFoundError as e:
            if not (e.name or "").startswith("abcad"):
                raise
            sys.path.insert(0, _HERE)  # standalone execution: abcad is not importable here
            from fea_runner_amg import run_one_iteration  # type: ignore
    except Exception as e:  # pragma: no cover
        where = repr(bp) if bp else "the installed biomimetic-lattice-pipeline package"
        raise SystemExit(f"could not import the biomimetic FEA run context from {where}: {e}")
    return run_one_iteration


def main(argv=None) -> None:
    """CLI entry point: solve one plated mesh in tension and write e_eff.json."""
    # --- 1. CLI ------------------------------------------------------------
    ap = argparse.ArgumentParser(
        description="Uniaxial tension FEA of a plated voxel-hex mesh (SfePy)."
    )
    ap.add_argument("--msh", required=True, help="plated hex .msh (with sidecar <msh>.json)")
    ap.add_argument(
        "--E", type=float, default=3000.0, help="solid Young's modulus [MPa] (resin~3000)"
    )
    ap.add_argument("--nu", type=float, default=0.40, help="solid Poisson ratio (resin~0.40)")
    ap.add_argument(
        "--strain", type=float, default=0.01, help="nominal tensile strain (disp = strain*H0)"
    )
    ap.add_argument(
        "--iter_dir", default="", help="FEA working dir (default <msh dir>/fea_tension)"
    )
    ap.add_argument(
        "--biomimetic",
        default="",
        help="biomimetic-lattice-pipeline location (default: the installed package)",
    )
    a = ap.parse_args(argv)

    # --- 2. Locate + import the proven FEA runner ---------------------------
    run_one_iteration = _import_runner(_biomimetic_location(a.biomimetic))

    # --- 3. Geometry from the mesh sidecar (A0 footprint, H0 height) -------
    side_path = a.msh + ".json"
    if not os.path.exists(side_path):
        raise SystemExit(
            f"missing sidecar {side_path} — regenerate the mesh with voxel_plate_mesh.py"
        )
    side = json.load(open(side_path))
    A0 = float(side["footprint_area_mm2"])  # nominal cross-section [mm^2]
    H0 = float(side["height_mm"])  # specimen height [mm]
    disp = a.strain * H0  # applied top-face displacement [mm] (tension = upward)

    iter_dir = a.iter_dir or os.path.join(os.path.dirname(os.path.abspath(a.msh)), "fea_tension")
    print(
        f"[fea] TENSION  E={a.E} MPa  nu={a.nu}  strain={a.strain}  disp={disp:.4f} mm  "
        f"|  A0={A0:.1f} mm^2  H0={H0:.1f} mm  |  mesh={a.msh} ({side.get('n_hex','?')} hex)"
    )
    print(f"[fea] solving in sfepy_env (conda run) -> {iter_dir} ...")

    # --- 4. Run the solve (stock compression_test.py, tension + hex) ------
    res = run_one_iteration(
        mesh_source=a.msh,
        iter_dir=iter_dir,
        material_E_mpa=a.E,
        material_nu=a.nu,
        compress_disp_mm=disp,  # magnitude; load_mode="tension" applies it as +z (pull)
        load_mode="tension",
        element_type="hex",  # our mesh is voxel-hex -> swap the stock tet kernels
    )

    # --- 5. Reduce reaction force -> effective tensile modulus ------------
    F = abs(res.force_N)  # axial reaction force [N]
    nominal_stress = F / A0  # nominal (apparent) stress over the gross footprint [MPa]
    E_eff = nominal_stress / a.strain  # small-strain effective tensile modulus [MPa]

    print(
        f"[fea] reaction F = {F:.4f} N  |  nominal stress = {nominal_stress:.5f} MPa  "
        f"|  avg_sigma_zz = {res.avg_sigma_zz_mpa:.5f} MPa  |  avg_vM = {res.avg_von_mises_mpa:.5f} MPa"
    )
    print(
        f"[fea] EFFECTIVE TENSILE MODULUS  E_eff = {E_eff:.3f} MPa  "
        f"({E_eff / a.E * 100:.3f}% of the solid E = {a.E} MPa)"
    )

    # --- 6. Persist the summary record next to the solver outputs -----------
    summary = {
        "load_mode": "tension",
        "E_solid_MPa": a.E,
        "nu": a.nu,
        "strain": a.strain,
        "disp_mm": disp,
        "A0_mm2": A0,
        "H0_mm": H0,
        "reaction_force_N": F,
        "nominal_stress_MPa": nominal_stress,
        "avg_sigma_zz_MPa": res.avg_sigma_zz_mpa,
        "avg_von_mises_MPa": res.avg_von_mises_mpa,
        "E_eff_MPa": E_eff,
        "E_eff_fraction_of_solid": E_eff / a.E,
        "mesh": os.path.abspath(a.msh),
    }
    with open(os.path.join(iter_dir, "e_eff.json"), "w") as fh:
        json.dump(summary, fh, indent=2)
    print(f"[fea] wrote {os.path.join(iter_dir, 'e_eff.json')}")


if __name__ == "__main__":
    main()
