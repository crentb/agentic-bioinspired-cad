"""
abcad/printing/print_audit.py — single-material 3D-print readiness audit for the demonstrator STLs (TM-2).

PURPOSE
    Watertight/manifold verification alone does not decide whether a part PRINTS. This tool checks
    the things that do — minimum wall/strut thickness vs the process resolution, inter-fiber clearance
    (unintended fusion kills the woven compliance), overhang/support burden, build-volume fit, enclosed
    voids (trapped resin), and material volume. It grades every STL against FDM and/or resin limits and
    emits a per-part verdict with concrete fixes (supports / scale factor / redesign).

METHOD (pyvista + scipy only — both in cad_env; no new dependencies)
    Surface checks (exact, on the triangulation):
      - watertight (boundary-edge count == 0) and manifold (non-manifold-edge count == 0) re-check
      - bbox [mm], solid volume [mL] (+ resin-mass estimate), surface area, triangle count
      - overhang area fraction: faces whose world normal points steeper than 45 deg DOWN (the FDM rule),
        in the as-modeled orientation (+z up)
    Voxel checks (occupancy grid via the proven VTK image-stencil rasterizer `voxelize_stl` reused from
    abcad/fea/voxel_plate_mesh.py, then Euclidean distance transforms):
      - WALL THICKNESS by morphological opening: features are "formable at diameter d" if they survive
        erosion by d/2 followed by dilation by d/2 (both done as EDT thresholds, distances in mm). The
        lost-material fraction at each d in THICKNESS_LADDER is the fraction of the part thinner than d.
      - CLEARANCE / fusion risk: the same idea on the VOID phase — local channel width = 2 x EDT of the
        void; the fraction of near-structure void narrower than g in GAP_LADDER estimates where separate
        fibers will fuse into one (bead spread on FDM, cure bleed on resin).
      - ENCLOSED VOIDS: void components not connected to the outside = trapped uncured resin (needs
        drain holes) — counted via scipy.ndimage.label.
    Voxel size auto-picks as max(0.12 mm, max_bbox_dim / 320) so grids stay <= ~33M voxels (~0.7 GB peak
    with the float64 EDTs — memory-light class); the achieved resolution is reported per part, and any
    thickness/clearance statement is only trusted down to ~2 voxels.

PROCESS LIMITS (cross-referenced with abcad/agent/manufacturability.py PROCESS_LIMITS and the printability
    table in docs/PRINTING.md — keep the three in sync if a printer is named):
      FDM (0.4 mm nozzle): min feature 0.8 mm, overhang gate 15% area, bed 220 x 220 x 250 mm
      Resin (SLA/DLP):     min feature 0.3 mm, overhangs handled by supports, vat 145 x 145 x 175 mm

CAVEATS (stated in the report too)
    - Self-intersection is NOT tested: woven fibers intentionally interpenetrate/weld at nodes, and both
      slicer classes union overlapping shells; the voxel occupancy already reflects the printed solid.
    - Orientation is as-modeled (+z up). Overhang numbers change if the part is printed tilted.
    - min_feature is a GEOMETRY statement; material/printer tuning can shift real-world limits.

USAGE (cad_env)
    "$ABCAD_CAD_PYTHON" -m abcad.printing.print_audit                      # audit $ABCAD_OUT/*.stl
    "$ABCAD_CAD_PYTHON" -m abcad.printing.print_audit --stl out/dt.stl --voxel 0.1
    Options: --process both|fdm|resin   --out out/print_audit   --voxel 0 (auto)

OUTPUTS
    <out>/print_audit.csv        one row per part x metrics   (default <out> = $ABCAD_OUT/print_audit)
    <out>/print_audit_report.md  per-part sections + fleet verdict table + methodology
    stdout: compact per-part progress + final verdict table.
"""

from __future__ import annotations

import argparse
import csv
import glob as globlib
import os
import sys
from datetime import datetime
from typing import Any

import numpy as np

# Reuse the proven STL rasterizer (VTK polydata->image stencil) from the FEA bridge.
# Normal case: package import. Standalone case (this file executed by a conda interpreter where abcad
# is not installed): import the sibling module from abcad/fea/ by putting that directory on sys.path.
try:
    from abcad.fea.voxel_plate_mesh import voxelize_stl
except ModuleNotFoundError as _e:
    if not (_e.name or "").startswith("abcad"):
        raise  # a real third-party dependency is missing; do not mask it
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fea")
    )
    from voxel_plate_mesh import voxelize_stl  # type: ignore  # noqa: E402

# Output root: ./out under the working directory unless ABCAD_OUT points elsewhere.
_OUT_ROOT = os.environ.get("ABCAD_OUT", "out")

# --- gradable process limits [mm / area-fraction]; see module docstring for provenance -------------
PROCESS_LIMITS: dict[str, dict[str, Any]] = {
    "fdm": {"min_feature_mm": 0.8, "overhang_area_frac": 0.15, "build_mm": (220.0, 220.0, 250.0)},
    "resin": {"min_feature_mm": 0.3, "overhang_area_frac": None, "build_mm": (145.0, 145.0, 175.0)},
}
THICKNESS_LADDER = [0.3, 0.5, 0.8, 1.2]  # feature diameters d [mm] tested by morphological opening
GAP_LADDER = [0.3, 0.5, 0.8]  # channel widths g [mm] tested on the void phase
LOST_FRAC_PASS = 0.01  # <=1% of material thinner than the limit counts as formable
RESIN_DENSITY_G_PER_ML = 1.10  # typical photopolymer, for the material estimate


def surface_checks(stl_path: str) -> dict:
    """Exact checks on the triangulated surface: watertight/manifold, bbox, volume, overhang fraction."""
    import pyvista as pv

    surf = pv.read(stl_path).triangulate()
    b = surf.bounds
    bbox = (b[1] - b[0], b[3] - b[2], b[5] - b[4])

    # watertight = zero boundary edges; manifold = zero non-manifold edges (same test as the TM-1 report)
    n_boundary = surf.extract_feature_edges(
        boundary_edges=True, non_manifold_edges=False, feature_edges=False, manifold_edges=False
    ).n_cells
    n_nonmanifold = surf.extract_feature_edges(
        boundary_edges=False, non_manifold_edges=True, feature_edges=False, manifold_edges=False
    ).n_cells

    # overhang area fraction, as-modeled orientation: face normal z < -cos(45 deg) = steeper than 45 down.
    # Faces whose centers lie within 0.5 mm of z_min REST ON THE BED — they are first-layer contact, not
    # overhang (without this a flat-bottomed laminate reads ~50% "overhang" from its own underside).
    mesh = surf.compute_normals(cell_normals=True, point_normals=False, auto_orient_normals=True)
    normals = np.asarray(mesh.cell_data["Normals"])
    areas = np.asarray(
        mesh.compute_cell_sizes(length=False, area=True, volume=False).cell_data["Area"]
    )
    centers_z = np.asarray(mesh.cell_centers().points)[:, 2]
    total_area = float(areas.sum())
    down = (normals[:, 2] < -np.cos(np.radians(45.0))) & (centers_z > b[4] + 0.5)
    overhang_frac = float(areas[down].sum() / total_area) if total_area else 0.0

    return {
        "n_faces": int(surf.n_cells),
        "watertight": n_boundary == 0,
        "manifold": n_nonmanifold == 0,
        "bbox_mm": tuple(round(v, 2) for v in bbox),
        "volume_ml": round(float(surf.volume) / 1000.0, 3),  # mm^3 -> mL
        "resin_mass_g": round(float(surf.volume) / 1000.0 * RESIN_DENSITY_G_PER_ML, 1),
        "area_mm2": round(float(surf.area), 1),
        "overhang_area_frac": round(overhang_frac, 4),
    }


def voxel_checks(stl_path: str, bbox_mm: tuple, voxel_mm: float = 0.0) -> dict:
    """EDT-based wall-thickness / clearance / enclosed-void analysis on an occupancy grid."""
    from scipy import ndimage

    # auto voxel: fine enough for the 0.3 mm resin limit when the part allows, capped for memory
    max_dim = max(bbox_mm)
    v = voxel_mm if voxel_mm > 0 else max(0.12, max_dim / 320.0)
    occ, _origin, v = voxelize_stl(stl_path, v)
    solid_n = int(occ.sum())
    if solid_n == 0:
        return {"voxel_mm": round(v, 3), "error": "voxelization produced an empty grid"}

    out = {
        "voxel_mm": round(v, 3),
        "grid": "x".join(str(s) for s in occ.shape),
        "solid_frac_of_bbox": round(solid_n / occ.size, 4),
    }

    # --- wall thickness by morphological opening (erode d/2 then dilate d/2, via EDT thresholds) ---
    # EDT(solid) = distance [mm] from each solid voxel to the nearest air voxel = local inscribed radius.
    edt_solid = ndimage.distance_transform_edt(occ, sampling=v)
    out["max_inscribed_diam_mm"] = round(2.0 * float(edt_solid.max()), 2)  # thickest section
    lost = {}
    for d in THICKNESS_LADDER:
        core = edt_solid >= d / 2.0  # erosion: what survives removing a d/2 shell
        if core.any():
            # dilation of the core by d/2 = all voxels within d/2 of the core (EDT of the complement)
            regrown = ndimage.distance_transform_edt(~core, sampling=v) <= d / 2.0
            lost[d] = round(1.0 - float((regrown & occ).sum()) / solid_n, 4)
        else:
            lost[d] = 1.0  # nothing survives: whole part thinner than d
        del core
    out["lost_frac_at_d"] = lost
    # LARGEST ladder diameter the part still forms at with <=1% loss — the certified formable size.
    # (lost_frac is monotone increasing in d, so the smallest passing rung is trivially the ladder
    # floor and carries no information; scale advice needs the largest. Bug found by the gate unit
    # test 2026-07-03: the old min() produced inverted "scale up x0.4" advice.)
    formable = [d for d in THICKNESS_LADDER if lost[d] <= LOST_FRAC_PASS]
    out["max_formable_d_mm"] = max(formable) if formable else None
    del edt_solid

    # --- void phase: enclosed voids (trapped resin) + inter-fiber clearance / fusion risk ---
    void = ~occ
    labels, n_comp = ndimage.label(void)
    border = np.zeros_like(void)
    border[0, :, :] = border[-1, :, :] = True
    border[:, 0, :] = border[:, -1, :] = True
    border[:, :, 0] = border[:, :, -1] = True
    outside_ids = np.unique(labels[border & void])  # void components reaching the grid border
    enclosed_mask = void & ~np.isin(labels, outside_ids)
    out["enclosed_void_count"] = (
        int(len(np.unique(labels[enclosed_mask]))) if enclosed_mask.any() else 0
    )
    out["enclosed_void_ml"] = round(float(enclosed_mask.sum()) * (v**3) / 1000.0, 3)
    del labels, border, enclosed_mask

    # local channel width = 2 x EDT(void). Restrict the fusion statistic to NEAR-STRUCTURE void
    # (within 3 mm of solid) so the open air around the part doesn't dilute the fractions.
    edt_void = ndimage.distance_transform_edt(void, sampling=v)
    near = void & (edt_void <= 3.0)
    near_n = int(near.sum())
    gaps = {}
    for g in GAP_LADDER:
        gaps[g] = round(float((near & (edt_void < g / 2.0)).sum()) / near_n, 4) if near_n else 0.0
    out["narrow_gap_frac_at_g"] = gaps  # fraction of nearby void narrower than g
    del edt_void, near, void, occ
    return out


def grade(process: str, s: dict, vx: dict) -> dict:
    """Combine the measurements into a per-process verdict + concrete recommendations."""
    lim = PROCESS_LIMITS[process]
    issues, recs = [], []

    # Watertightness BLOCKS (open surfaces break slicing and the voxel stencil). Non-manifold edges
    # on a watertight mesh do NOT block: Blender curve-bevel miters fold locally at sharp poly corners
    # (observed on loop-exported woven fibers, 2026-07-03) and both slicer classes + the image-stencil
    # voxelizer handle them via union semantics — flag as a note instead.
    if not s["watertight"]:
        issues.append("mesh not watertight")
        recs.append("repair the mesh before slicing (open surface)")
    elif not s["manifold"]:
        recs.append(
            "note: non-manifold edges present (bevel miter folds) — slicers union these; "
            "verify the slice preview at fiber crossings"
        )

    # build volume: list every axis that exceeds the printer's envelope
    over = [f"{a:.0f}>{b:.0f}" for a, b in zip(s["bbox_mm"], lim["build_mm"]) if a > b]
    if over:
        issues.append(f"exceeds build volume ({', '.join(over)} mm)")
        recs.append("scale down or split to fit the build volume")

    # thin features: the part must be formable at the process minimum with <=1% material loss
    d_lim = lim["min_feature_mm"]
    lost_at_lim = None
    if "lost_frac_at_d" in vx:
        ladder_d = min((d for d in THICKNESS_LADDER if d >= d_lim), default=None)
        lost_at_lim = vx["lost_frac_at_d"].get(ladder_d) if ladder_d else None
        if lost_at_lim is not None and lost_at_lim > LOST_FRAC_PASS:
            issues.append(f"{lost_at_lim:.0%} of material thinner than {d_lim} mm")
            mf = vx.get("max_formable_d_mm")
            if mf:
                # uniform scale-up factor: features certified at mf must reach the process limit
                recs.append(
                    f"scale up x{d_lim / mf:.1f} (features certified at {mf} mm vs the "
                    f"{d_lim} mm limit) or thicken fibers"
                )
            else:
                recs.append("features thinner than the whole test ladder — redesign/thicken")

    if (
        lim["overhang_area_frac"] is not None
        and s["overhang_area_frac"] > lim["overhang_area_frac"]
    ):
        issues.append(
            f"overhang area {s['overhang_area_frac']:.0%} > {lim['overhang_area_frac']:.0%}"
        )
        recs.append("add breakaway supports or reorient (or print on resin)")

    if process == "resin" and vx.get("enclosed_void_count", 0) > 0:
        issues.append(
            f"{vx['enclosed_void_count']} enclosed void(s), {vx['enclosed_void_ml']} mL trapped resin"
        )
        recs.append("add drain holes or reorient so voids vent")

    # fusion warning (advisory, not gating): nearby channels narrower than the feature size will bridge
    g_frac = vx.get("narrow_gap_frac_at_g", {}).get(
        min((g for g in GAP_LADDER if g >= d_lim), default=GAP_LADDER[-1])
    )
    if g_frac and g_frac > 0.05:
        recs.append(
            f"note: {g_frac:.0%} of inter-fiber gaps < ~{d_lim} mm — expect local fiber fusion"
        )

    verdict = (
        "PRINT"
        if not issues
        else (
            "PRINT w/ fixes"
            if not any("thinner" in i or "redesign" in r for i in issues for r in recs)
            else "SCALE/REDESIGN"
        )
    )
    # simple tighter rule: thin-feature failures dominate the verdict
    if lost_at_lim is not None and lost_at_lim > LOST_FRAC_PASS:
        verdict = "SCALE/REDESIGN"
    elif issues:
        verdict = "PRINT w/ fixes"
    return {"process": process, "verdict": verdict, "issues": issues, "recommendations": recs}


def audit_one(stl_path: str, processes: list, voxel_mm: float) -> dict:
    """Run the surface + voxel checks on one STL and grade it for every requested process."""
    name = os.path.basename(stl_path)
    print(f"\n=== {name} ===", flush=True)
    s = surface_checks(stl_path)
    print(
        f"  bbox={s['bbox_mm']} mm  vol={s['volume_ml']} mL  overhang={s['overhang_area_frac']:.1%}  "
        f"watertight={s['watertight']}",
        flush=True,
    )
    vx = voxel_checks(stl_path, s["bbox_mm"], voxel_mm)
    if "error" not in vx:
        print(
            f"  voxel={vx['voxel_mm']} mm grid={vx['grid']}  max_formable_d={vx['max_formable_d_mm']} mm  "
            f"lost@ladder={vx['lost_frac_at_d']}  enclosed_voids={vx['enclosed_void_count']}",
            flush=True,
        )
    grades = [grade(p, s, vx) for p in processes]
    for g in grades:
        print(
            f"  [{g['process']:5s}] {g['verdict']}: {'; '.join(g['issues']) or 'no blocking issues'}",
            flush=True,
        )
    return {"file": name, "surface": s, "voxel": vx, "grades": grades}


def write_reports(results: list, out_dir: str, processes: list) -> None:
    """Write the fleet CSV (one row per part) and the Markdown report into ``out_dir``."""
    os.makedirs(out_dir, exist_ok=True)
    # --- CSV: one row per part, flat columns ---
    csv_path = os.path.join(out_dir, "print_audit.csv")
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        head = [
            "file",
            "bbox_x_mm",
            "bbox_y_mm",
            "bbox_z_mm",
            "volume_ml",
            "resin_mass_g",
            "watertight",
            "manifold",
            "overhang_area_frac",
            "voxel_mm",
            "max_formable_d_mm",
            "max_inscribed_diam_mm",
            "enclosed_void_count",
            "enclosed_void_ml",
        ]
        head += [f"lost_frac_d{d}" for d in THICKNESS_LADDER] + [
            f"gap_frac_g{g}" for g in GAP_LADDER
        ]
        head += [f"verdict_{p}" for p in processes]
        w.writerow(head)
        for r in results:
            s, vx = r["surface"], r["voxel"]
            row = [
                r["file"],
                *s["bbox_mm"],
                s["volume_ml"],
                s["resin_mass_g"],
                s["watertight"],
                s["manifold"],
                s["overhang_area_frac"],
                vx.get("voxel_mm"),
                vx.get("max_formable_d_mm"),
                vx.get("max_inscribed_diam_mm"),
                vx.get("enclosed_void_count"),
                vx.get("enclosed_void_ml"),
            ]
            row += [vx.get("lost_frac_at_d", {}).get(d) for d in THICKNESS_LADDER]
            row += [vx.get("narrow_gap_frac_at_g", {}).get(g) for g in GAP_LADDER]
            row += [
                next((g["verdict"] for g in r["grades"] if g["process"] == p), "")
                for p in processes
            ]
            w.writerow(row)

    # --- Markdown report ---
    md = [
        f"# Print-readiness audit — {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"Processes graded: {', '.join(processes)}. Limits: "
        f"FDM min feature {PROCESS_LIMITS['fdm']['min_feature_mm']} mm / overhang "
        f"{PROCESS_LIMITS['fdm']['overhang_area_frac']:.0%} / bed {PROCESS_LIMITS['fdm']['build_mm']} mm; "
        f"resin min feature {PROCESS_LIMITS['resin']['min_feature_mm']} mm / vat "
        f"{PROCESS_LIMITS['resin']['build_mm']} mm.",
        "",
        "| part | bbox [mm] | vol [mL] | overhang | max certified Ø [mm] | "
        + " | ".join(f"{p} verdict" for p in processes)
        + " |",
        "|---|---|---|---|---|" + "---|" * len(processes),
    ]
    for r in results:
        s, vx = r["surface"], r["voxel"]
        verd = [
            next((g["verdict"] for g in r["grades"] if g["process"] == p), "") for p in processes
        ]
        md.append(
            f"| {r['file']} | {s['bbox_mm'][0]:.0f}x{s['bbox_mm'][1]:.0f}x{s['bbox_mm'][2]:.0f} | "
            f"{s['volume_ml']} | {s['overhang_area_frac']:.0%} | {vx.get('max_formable_d_mm', '?')} | "
            + " | ".join(verd)
            + " |"
        )
    md += ["", "## Per-part detail", ""]
    for r in results:
        s, vx = r["surface"], r["voxel"]
        md += [
            f"### {r['file']}",
            "",
            f"- bbox {s['bbox_mm']} mm, volume {s['volume_ml']} mL (~{s['resin_mass_g']} g resin), "
            f"{s['n_faces']} tris, watertight={s['watertight']}, manifold={s['manifold']}",
            f"- overhang(>45°, as-modeled) = {s['overhang_area_frac']:.1%}",
            f"- voxel {vx.get('voxel_mm')} mm (grid {vx.get('grid')}); max certified formable Ø = "
            f"{vx.get('max_formable_d_mm')} mm; lost-material fractions {vx.get('lost_frac_at_d')}",
            f"- near-structure narrow-gap fractions {vx.get('narrow_gap_frac_at_g')}; enclosed voids: "
            f"{vx.get('enclosed_void_count')} ({vx.get('enclosed_void_ml')} mL)",
        ]
        for g in r["grades"]:
            md.append(
                f"- **{g['process']} → {g['verdict']}**"
                + (f" — issues: {'; '.join(g['issues'])}" if g["issues"] else "")
                + (f" — fixes: {'; '.join(g['recommendations'])}" if g["recommendations"] else "")
            )
        md.append("")
    md += [
        "## Method & caveats",
        "",
        "- Wall thickness via morphological opening on a VTK image-stencil occupancy grid "
        "(erode+dilate by d/2 as EDT thresholds); a feature 'forms at d' if <=1% material is lost.",
        "- Clearance = 2xEDT of the void, restricted to void within 3 mm of the structure.",
        "- Self-intersection NOT tested (woven fibers intentionally weld; slicers union shells).",
        "- Orientation as-modeled (+z up); overhang numbers move if printed tilted.",
        "- Thickness statements are trustworthy down to ~2 voxels at the reported voxel size.",
    ]
    md_path = os.path.join(out_dir, "print_audit_report.md")
    with open(md_path, "w") as fh:
        fh.write("\n".join(md))
    print(f"\n[audit] wrote {csv_path}\n[audit] wrote {md_path}", flush=True)


def main(argv=None):
    """CLI entry point: audit the given STLs (default: every STL directly under the output root)."""
    ap = argparse.ArgumentParser(description="Single-material 3D-print readiness audit for STLs.")
    ap.add_argument(
        "--stl",
        nargs="*",
        default=None,
        help="STL paths (default: $ABCAD_OUT/*.stl, i.e. out/*.stl)",
    )
    ap.add_argument("--process", default="both", choices=["both", "fdm", "resin"])
    ap.add_argument(
        "--voxel", type=float, default=0.0, help="voxel size mm (0 = auto, capped for memory)"
    )
    ap.add_argument("--out", default=os.path.join(_OUT_ROOT, "print_audit"))
    a = ap.parse_args(argv)

    stls = a.stl or sorted(globlib.glob(os.path.join(_OUT_ROOT, "*.stl")))
    processes = ["fdm", "resin"] if a.process == "both" else [a.process]
    print(f"[audit] {len(stls)} STL(s), processes={processes}", flush=True)

    results = [audit_one(p, processes, a.voxel) for p in stls]
    write_reports(results, a.out, processes)

    print("\n[audit] VERDICTS:", flush=True)
    for r in results:
        verd = ", ".join(f"{g['process']}={g['verdict']}" for g in r["grades"])
        print(f"  {r['file']:28s} {verd}", flush=True)


if __name__ == "__main__":
    main()
