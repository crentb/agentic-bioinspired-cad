"""
abcad/printing/remesh_watertight.py — turn an open-tube lattice STL into a WATERTIGHT print mesh.

Generalized from the woven-smooth recipe (2026-07-05). Open-tube swept lattices (woven, enamel)
are not watertight — the rod ends leave boundary edges, and coarse tessellation shows facets.
This tool remeshes the part AS SOLID GEOMETRY, guaranteeing a watertight, manifold, smooth
surface by construction:
    fine image-stencil voxelization (house voxelize_stl)
    -> Gaussian smoothing of the occupancy FIELD (kills the voxel staircase before contouring)
    -> marching-cubes isosurface at 0.5
    -> windowed-sinc (Taubin) smoothing (volume-preserving polish)
    -> topology-preserving quadric decimation to a slicer-friendly triangle budget.
Geometry is preserved to within ~half a voxel; the surface is manifold + watertight by
construction (isosurface of a padded binary field). Certification (print_audit) is separate.

INPUTS
    --stl PATH     input (possibly open-tube) STL
    --voxel MM     rasterization pitch; >= 4 voxels across the thinnest feature
    --sigma VOX    Gaussian sigma in voxels; --reduce FRAC decimation fraction; --no_render
OUTPUTS
    --out PATH     the watertight STL (+ <out>.png render unless --no_render); stdout reports the
                   triangle count, watertightness and the bbox drift vs the source (asserted < 3 voxels).

Usage:
  "$ABCAD_CAD_PYTHON" -m abcad.printing.remesh_watertight \
      --stl out/enamel/enamel_linear_x4.stl --voxel 0.2 --out out/print/enamel_linear_x4_smooth.stl
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys

import numpy as np


def _load(name, rel):
    """Load a sibling source file by path (standalone fallback when abcad is not importable)."""
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(name, os.path.join(here, rel))
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m  # @dataclass in the module resolves via sys.modules
    spec.loader.exec_module(m)
    return m


def _helpers():
    """Return (voxel_plate_mesh, woven build) modules: package imports, else load by file path.

    The file-path branch keeps this tool runnable as a standalone file in a conda env where abcad is
    not installed; the relative paths follow the fixed package layout (abcad/printing -> abcad/fea,
    abcad/generators/woven).
    """
    try:
        from abcad.fea import voxel_plate_mesh as vpm
        from abcad.generators.woven import build as wb
    except ModuleNotFoundError as e:
        if not (e.name or "").startswith("abcad"):
            raise  # a real third-party dependency is missing; do not mask it
        vpm = _load("vpm", os.path.join("..", "fea", "voxel_plate_mesh.py"))
        wb = _load("wbuild", os.path.join("..", "generators", "woven", "build.py"))
    return vpm, wb


def main(argv=None):
    """CLI entry point: voxelize -> smooth field -> contour -> polish -> decimate -> verify."""
    ap = argparse.ArgumentParser(description="Remesh an open-tube lattice STL to watertight.")
    ap.add_argument("--stl", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--voxel",
        type=float,
        default=0.2,
        help="rasterization pitch [mm]; >=4 voxels across the thinnest feature",
    )
    ap.add_argument(
        "--sigma", type=float, default=0.9, help="Gaussian sigma [voxels] to round the staircase"
    )
    ap.add_argument(
        "--reduce", type=float, default=0.6, help="decimation fraction (0.6 = drop 60%%)"
    )
    ap.add_argument("--no_render", dest="render", action="store_false")
    a = ap.parse_args(argv)

    vpm, wb = _helpers()  # house image-stencil voxelizer + watertight_report / render_png
    import pyvista as pv
    from scipy.ndimage import gaussian_filter

    # 1) fine solid rasterization (robust on multiply-connected lattices)
    occ, origin, _ = vpm.voxelize_stl(a.stl, a.voxel)
    print(f"[remesh] occupancy {occ.shape} @ {a.voxel} mm, solid fraction {occ.mean():.4f}")

    # 2) pad an air margin (guarantees a closed isosurface) + smooth the occupancy field
    field = gaussian_filter(np.pad(occ.astype(np.float32), 2), sigma=a.sigma)
    pad_origin = tuple(o - 2 * a.voxel for o in origin)  # the 2-voxel pad shifts the grid origin

    # 3) marching cubes at 0.5
    img = pv.ImageData(dimensions=field.shape, spacing=(a.voxel,) * 3, origin=pad_origin)
    img.point_data["v"] = field.ravel(order="F")  # VTK point order is x-fastest (Fortran order)
    surf = img.contour([0.5], scalars="v")
    print(f"[remesh] isosurface {surf.n_cells} tris")

    # 4) volume-preserving polish
    surf = surf.smooth_taubin(n_iter=60, pass_band=0.05, normalize_coordinates=True)
    surf_clean = surf.clean().triangulate()

    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)

    # 5) topology-preserving decimation to a slicer-friendly budget. On DENSE lattices (enamel:
    # near-touching fibers) decimation can pinch thin bridges into non-manifold edges; the
    # marching-cubes isosurface is watertight by construction, so fall back to it if decimation
    # breaks manifoldness — a bigger file that still slices cleanly.
    dec = surf.decimate_pro(a.reduce, preserve_topology=True).clean().triangulate()
    dec.save(a.out)
    rep = wb.watertight_report(a.out)
    if not rep["watertight"]:
        print(
            f"[remesh] decimation left {rep['nonmanifold_edges']} non-manifold / "
            f"{rep['open_edges']} open edges — falling back to the undecimated isosurface"
        )
        surf_clean.save(a.out)
        rep = wb.watertight_report(a.out)
    print(
        f"[remesh] {a.out}: {rep['n_tris']} tris, watertight={rep['watertight']}, "
        f"nonmanifold={rep['nonmanifold_edges']}, bbox_mm={rep['bbox_mm']}"
    )

    # fidelity: bbox must match the source within a few voxels
    src_b = pv.read(a.stl).bounds
    db = max(abs(np.array(rep["bbox_mm"]) - np.array(src_b)))
    print(f"[remesh] bbox delta vs source {db:.3f} mm (allow < {3*a.voxel:.2f})")
    assert rep["watertight"], "remesh not watertight"
    assert db < 3 * a.voxel, "bbox moved too far — voxel/contour mismatch"

    if a.render:
        png = os.path.splitext(a.out)[0] + ".png"
        wb.render_png(a.out, png)
        print(f"[remesh] render -> {png}")


if __name__ == "__main__":
    main()
