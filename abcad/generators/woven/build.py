"""
abcad/generators/woven/build.py — Woven metamaterial lattice generator: adapter + driver (Tier 1).

WHAT THIS IS
    A thin, well-tested wrapper around the VENDORED, validated woven-lattice geometry engine
    (abcad/_vendor/woven_lattice/makeunitcell_func1.py — Carton/Portela, MIT; see the README there). The
    engine turns a parent beam lattice into continuous woven fiber CENTERLINES (entangled helical bundles +
    chiral node connectors). We add: a Blender curve+bevel SWEEP (replacing the engine's STL mesher), a
    fiber-interpenetration (clearance) check, single-material print scaling, and a CLI. All adaptations of
    the vendored engine live in this file; the engine itself is never edited.

WHY TWO STAGES (the key design choice)
    The engine needs scipy (+ matplotlib at import); Blender's bundled Python usually has neither. So we split:
      • stage "centerlines": run the engine (needs numpy+scipy) → save fiber paths to a .npz.   [run in a venv / cad_env]
      • stage "sweep":       read the .npz (needs only numpy) → Blender tubes → STL.             [run in Blender]
      • stage "all":         both in one process (only if scipy AND bpy live in the same interpreter).
    This keeps Blender free of scipy/matplotlib. A tiny matplotlib stub (below) also lets the engine import
    without matplotlib at all — so centerline generation needs only numpy + scipy.

USAGE
    # 1) centerlines (any Python with numpy + scipy):
    python abcad/generators/woven/build.py --stage centerlines --topology cubic --cells 2 2 2 \
        --unitcell 40 --reff_over_L 0.111 --nrev 1.0 --fiber_radius 0.4 --out out/woven_cubic.npz
    # 2) sweep to STL (inside Blender):
    blender -b -P abcad/generators/woven/build.py -- --stage sweep --centerlines out/woven_cubic.npz \
        --stl out/woven_cubic.stl

    # 3) Blender-FREE end-to-end (conda `cad_env`: numpy+scipy+numpy-stl+matplotlib+pyvista):
    #    generate centerlines -> numpy-stl tube sweep -> watertight check -> PNG render, in ONE process.
    #    This reuses the vendored engine's own STL mesher (save_piped_stl) instead of Blender, so the
    #    whole woven family can be produced/inspected on a machine without Blender.
    python abcad/generators/woven/build.py --stage all_np --topology cubic --cells 2 2 2 \
        --unitcell 40 --reff_over_L 0.111 --nrev 1.0 --fiber_radius 0.4 \
        --stl out/woven_cubic.stl --png out/woven_cubic.png
    (With abcad installed, ``python -m abcad.generators.woven.build ...`` is equivalent.)

PARAMETERS (see docs/LITERATURE.md and docs/GENERATORS.md)
    topology     cubic (n=4) | bcc | octahedron | diamond (n=3) | tetrakai | (experimental: cuBCC, tetracubic…)
    unitcell U   full unit-cell side [mm]; the engine is called with L = U/2 (its half-side convention)
    reff_over_L  effective bundle radius as a fraction of U → strutRadius = reff_over_L * U
    nrev         helix revolutions per beam (e.g. 0.75, 1.0, 1.333=4/3)
    fiber_radius individual filament radius [mm] for the swept tube (≥ printer min feature; ≤ clearance/2)

INPUTS / OUTPUTS
    Inputs: CLI flags (or a Params instance). Outputs: a centerline .npz (stage centerlines), an STL
    (sweep stages), an optional PNG render (numpy stages), and a one-line summary on stdout.

INTERPRETERS
    Runs as a standalone file in Blender's Python and in conda envs where ``abcad`` is not installed, so
    ``bpy`` and the vendored engine are imported under guards (see _load_engine).
"""

from __future__ import annotations

import math
import os
import sys
import types
from dataclasses import dataclass, fields

import numpy as np

# Directory of this file; used to locate the vendored engine when ``abcad`` is not importable.
_HERE = os.path.dirname(os.path.abspath(__file__))
# abcad/generators/woven/ -> abcad/_vendor/woven_lattice/ (fixed layout inside the package).
_VENDOR_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", "_vendor", "woven_lattice"))


# --------------------------------------------------------------------------------------------------
# matplotlib stub: the vendored engine does ``import matplotlib.pyplot as plt`` at top level but only uses
# it in plotting helpers we never call. Provide a stub so the engine imports without matplotlib installed.
# (Installed before the engine is imported, inside _load_engine().)
# --------------------------------------------------------------------------------------------------
def _install_matplotlib_stub() -> None:
    """Register empty ``matplotlib`` / ``matplotlib.pyplot`` modules if the real ones are missing."""
    try:
        import matplotlib.pyplot  # noqa: F401  (real matplotlib present — use it)

        return
    except Exception:
        mpl = types.ModuleType("matplotlib")
        plt = types.ModuleType("matplotlib.pyplot")
        mpl.pyplot = plt  # type: ignore[attr-defined]
        sys.modules.setdefault("matplotlib", mpl)
        sys.modules.setdefault("matplotlib.pyplot", plt)


def _load_engine():
    """Import the vendored woven engine (numpy+scipy). Raises a clear error if scipy is missing.

    Resolution order:
      1. the package import ``abcad._vendor.woven_lattice.makeunitcell_func1`` (abcad installed, or the
         repository root on sys.path, e.g. via ``python -m``);
      2. standalone fallback: when THIS file runs inside an interpreter where ``abcad`` itself is not
         importable (Blender's Python, a bare conda env), put the vendored directory on sys.path and import
         the module by its own name. The layout is fixed inside the package, so the relative path is safe.
    A missing third-party dependency (e.g. scipy) is NOT treated as "abcad missing": it propagates to the
    RuntimeError below so the user sees the real cause.
    """
    _install_matplotlib_stub()
    try:
        try:
            from abcad._vendor.woven_lattice import makeunitcell_func1 as muc
        except ModuleNotFoundError as e:
            if not (e.name or "").startswith("abcad"):
                raise  # a real dependency of the engine is missing -> report it below
            sys.path.insert(0, _VENDOR_DIR)  # standalone execution: abcad is not importable here
            import makeunitcell_func1 as muc  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Could not import the vendored woven engine (needs numpy + scipy). "
            f"Underlying error: {e}"
        )
    return muc


# Guarded Blender import (only needed for the sweep stage).
try:
    import bpy  # type: ignore

    _HAVE_BPY = True
except Exception:  # pragma: no cover - exercised outside Blender
    bpy = None  # type: ignore
    _HAVE_BPY = False


# ==================================================================================================
# Parameters
# ==================================================================================================
@dataclass
class Params:
    """All woven-generator inputs; units are millimetres unless stated otherwise."""

    # --- lattice ---
    # topology: cubic | bcc | octahedron | diamond | tetrakai | cuBCC | tetracubic | …
    topology: str = "cubic"
    cells: tuple = (2, 2, 2)  # number of unit cells [nx, ny, nz]
    unitcell: float = 40.0  # full unit-cell side U [mm] (engine uses L = U/2)
    sampling: float = 2.0  # approx. spacing between centerline sample points (engine units)
    double_network: bool = False  # also lay a straight monolithic core down each beam (concentric)
    # clip to the unit-cell boundary (bad for edge-aligned beams: cubic/tetrakai)
    trim: bool = False

    # --- woven strut params ---
    # R_eff / U  (≈1/9; fabricable band ≈ 1/30..1/10, use 1/10..1/8 for FDM)
    reff_over_L: float = 0.111
    nrev: float = 1.0  # helix revolutions per beam

    # --- optional linear functional grading of R_eff along an axis ---
    grade: str = "none"  # none | linear
    grade_axis: int = 2  # 0=x, 1=y, 2=z
    reff_bot: float = 0.111  # reff_over_L at the low end of grade_axis
    reff_top: float = 0.111  # reff_over_L at the high end of grade_axis

    # --- sweep / fabrication ---
    fiber_radius: float = 0.4  # swept-tube radius [mm] (filament Ø = 2*fiber_radius)
    bevel_resolution: int = 6  # Blender bevel smoothness (cross-section segments ≈ 4*(res+1))
    eccentricity: float = 1.0  # >1 flattens the circular cross-section to an ellipse

    # --- I/O (relative paths resolve against the working directory) ---
    stage: str = "centerlines"  # centerlines | sweep | all | sweep_np | all_np
    centerlines_path: str = "woven_centerlines.npz"
    stl_path: str = "woven.stl"
    quiet: bool = True  # suppress the engine's verbose stdout

    # --- Blender-free (numpy-stl) sweep + render: the cad_env path ---
    pts: int = 12  # circumferential facets per tube cross-section (numpy-sweep smoothness)
    png_path: str = ""  # optional render output; "" -> <stl_path>.png
    render: bool = True  # auto-render a PNG after a numpy-stl sweep (stages sweep_np / all_np)

    def validate(self) -> None:
        """Reject malformed parameters early with an actionable message."""
        if self.topology not in (
            "cubic",
            "bcc",
            "octahedron",
            "diamond",
            "tetrakai",
            "cuBCC",
            "tetracubic",
            "arrow",
            "octet",
        ):
            raise ValueError(f"unknown topology: {self.topology!r}")
        if any(c < 1 for c in self.cells):
            raise ValueError("cells must be >= 1 in each dimension")
        if self.unitcell <= 0 or self.reff_over_L <= 0 or self.fiber_radius <= 0:
            raise ValueError("unitcell, reff_over_L, fiber_radius must be > 0")
        if self.stage not in ("centerlines", "sweep", "all", "sweep_np", "all_np"):
            raise ValueError("stage must be one of: centerlines, sweep, all, sweep_np, all_np")


# ==================================================================================================
# strutParams factory (the engine's per-beam callback: (strutPosition, L) -> (R_eff_abs, revolutions))
# ==================================================================================================
def make_strut_params(P: Params):
    """
    Build the per-beam callback the engine expects. R_eff is ABSOLUTE (engine units); we map our
    dimensionless reff_over_L to absolute via R_eff = reff_over_L * unitcell. Optional linear grading
    interpolates reff_over_L along ``grade_axis`` across the lattice extent.
    """
    U = P.unitcell
    # Approximate lattice half-extent along each axis (cells of size U, centered on origin).
    half_extent = [max(1e-9, P.cells[a] * U / 2.0) for a in range(3)]

    def strut_params(strut_position, L):  # signature required by the engine
        if P.grade == "linear":
            a = P.grade_axis
            # Map position along grade_axis to frac∈[0,1]; engine positions are in half-side (L) units,
            # so scale by L to compare against our mm half_extent.
            pos = float(strut_position[a]) * L
            frac = min(1.0, max(0.0, (pos + half_extent[a]) / (2.0 * half_extent[a])))
            reff_over_L = P.reff_bot + (P.reff_top - P.reff_bot) * frac
        else:
            reff_over_L = P.reff_over_L
        return (float(reff_over_L * U), float(P.nrev))

    return strut_params


# ==================================================================================================
# Stage 1 — centerlines (numpy + scipy; NO Blender)
# ==================================================================================================
def run_centerlines(P: Params) -> list:
    """Run the vendored engine and return a list of Nx3 float arrays (one per continuous fiber)."""
    P.validate()
    muc = _load_engine()
    strut_params = make_strut_params(P)

    import contextlib

    # The engine prints progress chatter; route it to /dev/null unless --verbose was given.
    sink = open(os.devnull, "w") if P.quiet else sys.stdout
    try:
        with contextlib.redirect_stdout(sink):
            curves = muc.wovenLattice(
                P.topology,
                P.unitcell / 2.0,
                strut_params,
                P.sampling,
                list(P.cells),
                doubleNetwork=P.double_network,
                trim=P.trim,
                defectPoints=[],
            )
    finally:
        if P.quiet:
            sink.close()

    # Keep only real polylines (>= 2 points); the engine can emit empty/degenerate curve holders.
    paths = [
        np.asarray(c.path, dtype=float)
        for c in curves
        if getattr(c, "path", None) is not None and len(c.path) >= 2
    ]
    if not paths:
        raise RuntimeError("engine returned no centerlines — check topology/params")
    return paths


def save_centerlines(paths: list, P: Params, out_path: str) -> None:
    """Persist centerlines + the params needed by the sweep stage to a .npz."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    arrs = {f"c{i}": p for i, p in enumerate(paths)}  # one array per fiber (ragged lengths)
    np.savez(
        out_path,
        n=len(paths),
        fiber_radius=P.fiber_radius,
        bevel_resolution=P.bevel_resolution,
        eccentricity=P.eccentricity,
        unitcell=P.unitcell,
        topology=P.topology,
        **arrs,
    )


def load_centerlines(path: str):
    """Load centerlines + metadata from a .npz produced by save_centerlines()."""
    d = np.load(path, allow_pickle=False)
    n = int(d["n"])
    paths = [d[f"c{i}"] for i in range(n)]
    meta = {
        "fiber_radius": float(d["fiber_radius"]),
        "bevel_resolution": int(d["bevel_resolution"]),
        "eccentricity": float(d["eccentricity"]),
        "unitcell": float(d["unitcell"]),
        "topology": str(d["topology"]),
    }
    return paths, meta


def clearance(paths: list, fiber_radius: float, max_pts_per_curve: int = 80) -> dict:
    """
    Fabricability/self-intersection diagnostic. Distinct fibers in a woven lattice are MEANT to be close
    (entanglement) but their solid tubes must not interpenetrate: min center-distance between DIFFERENT
    fibers must be >= 2*fiber_radius. Returns the min center distance, the implied max printable fiber
    radius, and whether the chosen radius interpenetrates.
    """
    from scipy.spatial.distance import cdist  # scipy present in the centerlines stage

    def sub(p):
        # Evenly subsample long polylines so the O(n^2) pairwise check stays cheap.
        if len(p) <= max_pts_per_curve:
            return p
        idx = np.linspace(0, len(p) - 1, max_pts_per_curve).astype(int)
        return p[idx]

    sp = [sub(np.asarray(p, dtype=float)) for p in paths]
    min_d = math.inf
    for i in range(len(sp)):
        for j in range(i + 1, len(sp)):
            d = cdist(sp[i], sp[j]).min()
            if d < min_d:
                min_d = d
    return {
        "min_center_dist": float(min_d),
        "max_printable_fiber_radius": float(min_d / 2.0),
        "chosen_fiber_radius": float(fiber_radius),
        "interpenetrates": bool(fiber_radius > min_d / 2.0),
    }


# ==================================================================================================
# Stage 2 — sweep centerlines into Blender tubes (requires bpy; numpy only otherwise)
# ==================================================================================================
def _require_bpy() -> None:
    """Fail with a runnable hint when the Blender sweep is requested outside Blender."""
    if not _HAVE_BPY:
        raise RuntimeError(
            "The sweep stage needs Blender's bpy. Run inside Blender:\n"
            "  blender -b -P abcad/generators/woven/build.py -- --stage sweep "
            "--centerlines <file.npz> --stl <out.stl>"
        )


def _make_ellipse_bevel(fiber_radius: float, eccentricity: float):
    """Bevel object for an elliptical cross-section (only created when eccentricity != 1)."""
    bpy.ops.curve.primitive_bezier_circle_add(radius=fiber_radius)
    ell = bpy.context.object
    ell.scale[1] = 1.0 / eccentricity
    return ell


def sweep_centerlines(
    paths: list, fiber_radius: float, bevel_resolution: int = 6, eccentricity: float = 1.0
):
    """Create one beveled Blender curve per centerline (twist-minimized tube), join into one mesh."""
    _require_bpy()
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    ellipse = _make_ellipse_bevel(fiber_radius, eccentricity) if eccentricity != 1.0 else None
    objs = []
    for i, pts in enumerate(paths):
        pts = np.asarray(pts, dtype=float)
        cu = bpy.data.curves.new(f"fiber_{i}", "CURVE")
        cu.dimensions = "3D"
        sp = cu.splines.new("POLY")
        sp.points.add(len(pts) - 1)  # one point exists by default
        for k, (x, y, z) in enumerate(pts):
            sp.points[k].co = (float(x), float(y), float(z), 1.0)  # (x, y, z, w) homogeneous
        if ellipse is not None:
            cu.bevel_mode = "OBJECT"
            cu.bevel_object = ellipse
        else:
            cu.bevel_depth = fiber_radius  # circular tube of radius=fiber_radius
            cu.bevel_resolution = bevel_resolution
        # Cap the swept tube's ends: boundary fibers terminate mid-air, so without
        # caps each tube leaves two open vertex rings and the STL fails the
        # watertight gate (watertight_report: 2304 open edges on a 2x2x2 cubic).
        # The vendored numpy mesher (save_piped_stl) caps ends -- match it here.
        cu.use_fill_caps = True
        obj = bpy.data.objects.new(f"fiber_{i}", cu)
        bpy.context.collection.objects.link(obj)
        objs.append(obj)

    # Convert curves → mesh so the validator counts them, then join into one object.
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.convert(target="MESH")
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    if ellipse is not None:
        try:
            bpy.data.objects.remove(ellipse, do_unlink=True)
        except Exception:
            pass  # the bevel helper may already be consumed by the join; nothing to clean up
    return bpy.context.object


def export_stl(path: str) -> None:
    """Export the scene's meshes to STL (Blender 4.2 operator, legacy fallback)."""
    bpy.ops.object.select_all(action="SELECT")
    try:
        bpy.ops.wm.stl_export(filepath=path, export_selected_objects=True)  # Blender 4.2+
    except Exception:
        bpy.ops.export_mesh.stl(filepath=path, use_selection=True)  # legacy fallback


# ==================================================================================================
# Stage 2' — Blender-FREE sweep + render (cad_env path: numpy-stl + pyvista, NO bpy)
#
# The vendored engine ships its OWN watertight STL mesher (save_piped_stl): it sweeps a circular tube
# of radius=fiber_radius along each centerline using a twist-minimized parallel-transport frame — the
# same idea as the Blender bevel sweep, but pure numpy + numpy-stl. We reuse it so the entire woven
# family can be generated AND visually QC'd on a machine without Blender (only numpy/scipy/numpy-stl/
# matplotlib/pyvista, all present in `cad_env`). Watertightness — the TM-1 mesh-integrity gate — is then
# verified with pyvista (vtk), mirroring Blender's 3D-Print-Toolbox manifold check.
# ==================================================================================================
def sweep_to_stl_numpy(
    paths: list,
    fiber_radius: float,
    pts: int = 12,
    eccentricity: float = 1.0,
    stl_path: str = "woven.stl",
):
    """
    Sweep fiber centerlines into a solid, watertight STL WITHOUT Blender, via the vendored
    save_piped_stl (numpy-stl). Returns the numpy-stl Mesh (also written to ``stl_path``).

    paths        : list of Nx3 float arrays (one per continuous fiber) from run/load_centerlines.
    fiber_radius : swept-tube radius [mm] (filament Ø = 2*fiber_radius).
    pts          : circumferential facets per cross-section — tube smoothness. 12 ≈ smooth & light;
                   raise for a finer print mesh, lower for a quick preview.
    eccentricity : >1 flattens the circular section to an ellipse (1.0 = circular).
    """
    # Friendly dependency guard (cad_env has these; Blender's bundled Python typically does not).
    try:
        import stl  # numpy-stl  # noqa: F401
        from matplotlib import tri  # noqa: F401  (save_piped_stl triangulates the tube grid)
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "The Blender-free sweep needs numpy-stl + matplotlib. In cad_env:\n"
            '  "$ABCAD_CAD_PYTHON" -m pip install numpy-stl matplotlib\n'
            f"Underlying import error: {e}"
        )
    muc = _load_engine()  # the vendor module also exposes save_piped_stl

    # save_piped_stl reads each element's `.path`; wrap our raw Nx3 arrays in a minimal holder.
    class _Curve:
        __slots__ = ("path",)

        def __init__(self, p):
            self.path = np.asarray(p, dtype=float)

    curves = [_Curve(p) for p in paths]
    os.makedirs(os.path.dirname(os.path.abspath(stl_path)), exist_ok=True)
    return muc.save_piped_stl(
        curves, fiber_radius, pts, filename=stl_path, eccentricity=eccentricity
    )


def watertight_report(stl_path: str) -> dict:
    """
    Manifold/watertight diagnostics for a finished STL via pyvista (vtk) — the TM-1 'watertight STL'
    gate, checkable without Blender. ``open_edges`` counts boundary edges belonging to a single triangle;
    ``nonmanifold_edges`` counts edges shared by >2 triangles. Both 0 => a closed, 2-manifold surface.
    """
    import pyvista as pv

    m = pv.read(stl_path)
    boundary = m.extract_feature_edges(
        boundary_edges=True, feature_edges=False, manifold_edges=False, non_manifold_edges=False
    )
    nonman = m.extract_feature_edges(
        boundary_edges=False, feature_edges=False, manifold_edges=False, non_manifold_edges=True
    )
    return {
        "n_points": int(m.n_points),
        "n_tris": int(m.n_cells),
        "open_edges": int(boundary.n_cells),
        "nonmanifold_edges": int(nonman.n_cells),
        "watertight": bool(boundary.n_cells == 0 and nonman.n_cells == 0),
        "bbox_mm": [round(float(b), 3) for b in m.bounds],  # [xmin,xmax,ymin,ymax,zmin,zmax]
    }


def render_png(
    stl_path: str, png_path: str, color: str = "#c2b39a", window=(1100, 900), cpos: str = "iso"
) -> str:
    """
    Off-screen PNG render of an STL via pyvista (no display required) — quick visual QC of a generated
    lattice without Blender. Returns ``png_path``.
    """
    try:
        import pyvista as pv
    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"Rendering needs pyvista (present in cad_env). Import error: {e}")
    m = pv.read(stl_path)
    p = pv.Plotter(off_screen=True, window_size=list(window))
    p.add_mesh(m, color=color, smooth_shading=True, specular=0.3)
    p.add_axes()
    p.camera_position = cpos
    os.makedirs(os.path.dirname(os.path.abspath(png_path)), exist_ok=True)
    p.screenshot(png_path)
    p.close()
    return png_path


# ==================================================================================================
# CLI
# ==================================================================================================
def parse_args(argv=None) -> Params:
    """Parse CLI flags into a Params (accepts Blender's ``--`` separator or plain ``sys.argv``)."""
    import argparse

    if argv is None:
        # Inside Blender the script args follow a literal "--"; under plain Python use sys.argv[1:].
        argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]

    p = argparse.ArgumentParser(
        description="Woven metamaterial lattice generator: vendored core + Blender sweep, "
        "OR Blender-free numpy-stl sweep + pyvista render (stages *_np, for cad_env)."
    )
    p.add_argument(
        "--stage",
        default=Params.stage,
        choices=["centerlines", "sweep", "all", "sweep_np", "all_np"],
        help="all_np / sweep_np = Blender-free (numpy-stl + pyvista) path; no bpy required",
    )
    p.add_argument("--topology", default=Params.topology)
    p.add_argument("--cells", type=int, nargs=3, default=list(Params.cells))
    p.add_argument("--unitcell", type=float, default=Params.unitcell)
    p.add_argument("--sampling", type=float, default=Params.sampling)
    p.add_argument("--double_network", action="store_true")
    p.add_argument("--trim", action="store_true")
    p.add_argument("--reff_over_L", type=float, default=Params.reff_over_L)
    p.add_argument("--nrev", type=float, default=Params.nrev)
    p.add_argument("--grade", default=Params.grade, choices=["none", "linear"])
    p.add_argument("--grade_axis", type=int, default=Params.grade_axis)
    p.add_argument("--reff_bot", type=float, default=Params.reff_bot)
    p.add_argument("--reff_top", type=float, default=Params.reff_top)
    p.add_argument("--fiber_radius", type=float, default=Params.fiber_radius)
    p.add_argument("--bevel_resolution", type=int, default=Params.bevel_resolution)
    p.add_argument("--eccentricity", type=float, default=Params.eccentricity)
    # --out and --centerlines are aliases for the same .npz path (write in stage 1, read in stage 2).
    p.add_argument("--out", dest="centerlines_path", default=Params.centerlines_path)
    p.add_argument("--centerlines", dest="centerlines_path", default=Params.centerlines_path)
    p.add_argument("--stl", dest="stl_path", default=Params.stl_path)
    p.add_argument(
        "--pts",
        type=int,
        default=Params.pts,
        help="numpy sweep: circumferential facets per tube cross-section (smoothness)",
    )
    p.add_argument(
        "--png",
        dest="png_path",
        default=Params.png_path,
        help="render PNG for sweep_np/all_np; default <stl>.png",
    )
    p.add_argument(
        "--no_render",
        dest="render",
        action="store_false",
        help="skip the PNG render after a Blender-free (numpy-stl) sweep",
    )
    p.add_argument("--verbose", dest="quiet", action="store_false")
    ns = p.parse_args(argv)

    valid = {f.name for f in fields(Params)}
    kw = {k: v for k, v in vars(ns).items() if k in valid}
    kw["cells"] = tuple(kw["cells"])  # argparse gives a list; Params stores a tuple
    return Params(**kw)


def main(argv=None) -> None:
    """CLI entry point: run the requested stage(s) and print a one-line summary."""
    P = parse_args(argv)
    np_path = P.stage in ("sweep_np", "all_np")  # Blender-free (numpy-stl + pyvista) path

    # --- obtain centerlines: generate (centerlines/all/all_np) or load a .npz (sweep/sweep_np) ---
    if P.stage in ("centerlines", "all", "all_np"):
        paths = run_centerlines(P)
        cl = clearance(paths, P.fiber_radius)
        print(
            f"[woven] {P.topology} {tuple(P.cells)}: {len(paths)} fibers; "
            f"min center-dist={cl['min_center_dist']:.3f} mm; "
            f"max printable fiber radius={cl['max_printable_fiber_radius']:.3f} mm; "
            f"interpenetrates={cl['interpenetrates']}"
        )
        if P.stage == "centerlines":
            save_centerlines(paths, P, P.centerlines_path)
            print(
                f"[woven] centerlines → {P.centerlines_path}  "
                "(next: blender -P build.py -- --stage sweep ...)"
            )
            return
    else:  # stage in ("sweep", "sweep_np") → load saved centerlines + their sweep params
        paths, meta = load_centerlines(P.centerlines_path)
        P.fiber_radius = meta["fiber_radius"]
        P.bevel_resolution = meta["bevel_resolution"]
        P.eccentricity = meta["eccentricity"]

    # --- sweep to STL: Blender-free numpy-stl (sweep_np/all_np) or Blender bevel (sweep/all) ---
    if np_path:
        sweep_to_stl_numpy(paths, P.fiber_radius, P.pts, P.eccentricity, P.stl_path)
        rep = watertight_report(P.stl_path)
        print(
            f"[woven] (numpy) swept {len(paths)} fibers → STL {P.stl_path}  "
            f"[{rep['n_tris']} tris; open_edges={rep['open_edges']}; "
            f"nonmanifold={rep['nonmanifold_edges']}; watertight={rep['watertight']}]"
        )
        if P.render:
            png = P.png_path or (os.path.splitext(P.stl_path)[0] + ".png")
            render_png(P.stl_path, png)
            print(f"[woven] render → {png}")
    else:
        sweep_centerlines(paths, P.fiber_radius, P.bevel_resolution, P.eccentricity)
        export_stl(P.stl_path)
        print(f"[woven] swept {len(paths)} fibers → STL {P.stl_path}")


if __name__ == "__main__":
    main()
