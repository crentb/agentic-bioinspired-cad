"""
abcad/printing/fdm_variants.py — make FDM-printable scaled (and optionally plated) variants of an STL.

PURPOSE
    The print audit (abcad/printing/print_audit.py) showed the as-designed lattices have fibers below the
    FDM 0.4 mm nozzle's ~0.8 mm minimum-strand rule. UNIFORM SCALING is the preferred fix for validated
    specimens: it preserves the architecture exactly, so any FEA on the original (E_eff/E is a
    scale-invariant ratio in linear elasticity) still describes the scaled print — unlike parametric
    regeneration, which changes relative density and would need a re-run.

WHAT IT MAKES (for each --scales entry k)
    <name>_x<k>.stl        the input uniformly scaled by k about (bbox center x/y, z_min) — the part
                           stays centered and bed-seated.
    <name>_x<k>_plated.stl (only with --plate) the scaled lattice PLUS top/bottom grip plates as
                           overlapping closed boxes, mirroring the FEA plating convention of
                           abcad/fea/voxel_plate_mesh.add_plates: each plate's inner face sits
                           `overlap` INSIDE the fiber stubs (bonded grip), outer face extends
                           (plate - overlap) beyond the part. Slicers union overlapping shells within
                           one object, so this prints as a single bonded tension specimen.
    --plate/--overlap are given AT x1 SCALE [mm] and are scaled by k with the part, keeping the plated
    geometry similar to the FEA-plated mesh at every scale.

VALIDATION
    Always re-certify the outputs with the audit tool before printing:
        "$ABCAD_CAD_PYTHON" -m abcad.printing.print_audit --stl out/print/<variant>.stl
    (2026-07-03 reference result: woven_fea_small x1.5 = FDM PRINT marginal, x2.0 = FDM PRINT clean,
     x2.0 plated = FDM PRINT with supports under the top plate.)

USAGE (cad_env)
    "$ABCAD_CAD_PYTHON" -m abcad.printing.fdm_variants \
        --stl out/woven_fea_small.stl --scales 1.5,2.0 --plate 2.0 --overlap 0.8 --out out/print

INPUTS / OUTPUTS
    Input: one STL. Outputs: scaled (+ plated) STLs under --out (default ``$ABCAD_OUT/print``, i.e.
    ``./out/print``) and one size line per file on stdout. ``normalize_to_target_size`` is also used as
    a library call by the agent's manufacturability gate.
"""

from __future__ import annotations

import argparse
import os

import pyvista as pv

# Output root: ./out under the working directory unless ABCAD_OUT points elsewhere.
_OUT_ROOT = os.environ.get("ABCAD_OUT", "out")


def scaled_about_base(mesh: pv.PolyData, k: float) -> pv.PolyData:
    """Uniformly scale by k about (bbox-center x, bbox-center y, z_min): centered, still bed-seated."""
    b = mesh.bounds
    cx, cy = (b[0] + b[1]) / 2.0, (b[2] + b[3]) / 2.0
    m = mesh.copy()
    pts = m.points.copy()
    pts[:, 0] = (pts[:, 0] - cx) * k + cx
    pts[:, 1] = (pts[:, 1] - cy) * k + cy
    pts[:, 2] = (pts[:, 2] - b[4]) * k + b[4]  # z scales about the bed plane, so z_min is unchanged
    m.points = pts
    return m


def normalize_to_target_size(stl_path: str, target_max_mm: float, out_path: str) -> dict:
    """
    Target-size normalization: deterministically rescale an STL so its LARGEST bounding-box
    dimension equals `target_max_mm`, keeping it bed-seated (scale about bbox-center-xy / z_min).
    The LoRA emits arbitrary "mm" numbers (a lattice prompt gave a 96 mm part), and print viability
    depends on absolute size — this gives the loop a size knob before the deep gate. Returns a
    record (original/new max dim, scale factor) for the run manifest. Architecture is unchanged
    (uniform scale), so any scale-invariant FEA ratio still describes the normalized part.
    """
    m = pv.read(stl_path)
    b = m.bounds
    cur = max(b[1] - b[0], b[3] - b[2], b[5] - b[4])  # current largest bbox dimension [mm]
    k = float(target_max_mm) / cur if cur > 0 else 1.0  # degenerate (flat) input -> no scaling
    out = scaled_about_base(m, k)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    out.save(out_path)
    nb = out.bounds
    new_max = max(nb[1] - nb[0], nb[3] - nb[2], nb[5] - nb[4])
    return {
        "target_max_mm": float(target_max_mm),
        "orig_max_mm": round(cur, 3),
        "new_max_mm": round(new_max, 3),
        "scale": round(k, 4),
        "out": out_path,
    }


def add_grip_plates(mesh: pv.PolyData, plate_mm: float, overlap_mm: float) -> pv.PolyData:
    """Append top/bottom grip plates as separate closed shells overlapping the part by `overlap_mm`."""
    b = mesh.bounds
    # Bottom plate: from (plate - overlap) below the part up to `overlap` inside it (and mirrored on top).
    bot = pv.Box(
        bounds=(b[0], b[1], b[2], b[3], b[4] - (plate_mm - overlap_mm), b[4] + overlap_mm)
    ).triangulate()
    top = pv.Box(
        bounds=(b[0], b[1], b[2], b[3], b[5] - overlap_mm, b[5] + (plate_mm - overlap_mm))
    ).triangulate()
    return mesh.merge(bot).merge(top)


def main(argv=None):
    """CLI entry point: write one scaled (and optionally plated) STL per requested scale factor."""
    ap = argparse.ArgumentParser(description="Scaled (+plated) FDM-printable variants of an STL.")
    ap.add_argument("--stl", required=True, help="input STL")
    ap.add_argument("--scales", default="1.5,2.0", help="comma-separated uniform scale factors")
    ap.add_argument(
        "--plate",
        type=float,
        default=0.0,
        help="ALSO emit a plated variant; plate thickness [mm] at x1 scale (0 = no plates)",
    )
    ap.add_argument(
        "--overlap",
        type=float,
        default=0.8,
        help="plate-into-part bonded overlap [mm] at x1 scale (FEA convention: 0.8)",
    )
    ap.add_argument("--out", default=os.path.join(_OUT_ROOT, "print"))
    a = ap.parse_args(argv)

    os.makedirs(a.out, exist_ok=True)
    base = pv.read(a.stl).triangulate()
    stem = os.path.splitext(os.path.basename(a.stl))[0]

    for k in [float(s) for s in a.scales.split(",") if s.strip()]:
        tag = f"x{k:g}".replace(".", "")  # 1.5 -> x15, 2.0 -> x2 (compact, filesystem-safe)
        m = scaled_about_base(base, k)
        path = os.path.join(a.out, f"{stem}_{tag}.stl")
        m.save(path)
        mb = m.bounds
        print(
            f"[fdm_variants] {os.path.basename(path)}: "
            f"{mb[1]-mb[0]:.1f} x {mb[3]-mb[2]:.1f} x {mb[5]-mb[4]:.1f} mm",
            flush=True,
        )

        if a.plate > 0:
            # Plate thickness and bond overlap scale with the part (given at x1 scale).
            plated = add_grip_plates(m, plate_mm=a.plate * k, overlap_mm=a.overlap * k)
            ppath = os.path.join(a.out, f"{stem}_{tag}_plated.stl")
            plated.save(ppath)
            pb = plated.bounds
            print(
                f"[fdm_variants] {os.path.basename(ppath)}: "
                f"{pb[1]-pb[0]:.1f} x {pb[3]-pb[2]:.1f} x {pb[5]-pb[4]:.1f} mm "
                f"(plates {a.plate * k:.1f} mm, overlap {a.overlap * k:.1f} mm)",
                flush=True,
            )


if __name__ == "__main__":
    main()
