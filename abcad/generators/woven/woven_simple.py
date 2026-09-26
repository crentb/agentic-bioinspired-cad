"""
woven_simple.py — Compact, self-contained woven-lattice generator (Tier 2).

PURPOSE
    A dependency-free (Python ``math`` + guarded ``bpy``, NO scipy/matplotlib) woven-lattice generator that the
    fine-tuned model can learn to EMIT as a single self-contained Blender script — unlike the exact vendored
    engine (abcad/_vendor/woven_lattice + build.py), which needs scipy and therefore runs as a separate
    two-stage tool. Use this for LLM generation / retrieval; use the Tier-1 vendored engine when you need the
    paper-exact nodes.

FIDELITY TRADEOFF (read this)
    This is a SIMPLIFIED woven model: each lattice beam is rendered as a bundle of ``n_fibers`` helices winding
    around the beam axis, and bundles of beams sharing a node simply meet in the node neighbourhood. It captures
    the essential woven character (entangled helical bundles, single material, geometry-only compliance) and is
    printable, but it does NOT reproduce the exact chiral-twist, tangent-continuous node connectors of the
    Carton/Portela engine (those require the spherical-dual + geodesic construction in the vendored core). For
    publication-grade geometry, use Tier-1 (build.py). See docs/LITERATURE.md.

UNITS / USAGE
    Blender units = millimetres. Inside Blender:
        blender -b -P abcad/generators/woven/woven_simple.py -- --topology cubic --cells 2 2 2 --unitcell 40 \
            --reff_over_L 0.12 --nrev 1.0 --fiber_radius 0.5 --export_stl --stl_path out/woven_simple.stl
    The helix/lattice math is pure Python and importable without Blender for unit testing
    (tests/test_woven_simple.py). This file must stay runnable as a standalone Blender script, so it
    imports nothing from ``abcad``.

INPUTS / OUTPUTS
    Inputs: the ``Params`` fields (CLI flags). Outputs: joined tube MESH objects in the Blender scene, a
    one-line clearance summary on stdout, and (with ``--export_stl``) an STL at ``--stl_path``.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, fields

# Guarded Blender import: the math below must import without Blender for the unit tests.
try:
    import bpy  # type: ignore

    _HAVE_BPY = True
except Exception:  # pragma: no cover
    bpy = None  # type: ignore
    _HAVE_BPY = False


# ------------------------------- tiny vector helpers (3-tuples) -----------------------------------
# Plain-tuple vector algebra keeps this module dependency-free (no numpy inside Blender needed).
def _sub(a, b):
    """a - b."""
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    """a + b."""
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a, s):
    """s * a."""
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    """a · b."""
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    """a × b."""
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a):
    """|a| (Euclidean length)."""
    return math.sqrt(_dot(a, a))


def _normalize(a):
    """a / |a|, or the zero vector for a (near-)zero input (avoids division by zero)."""
    n = _norm(a)
    return (a[0] / n, a[1] / n, a[2] / n) if n > 1e-12 else (0.0, 0.0, 0.0)


# ----------------------------------------- parameters ---------------------------------------------
@dataclass
class Params:
    """Tier-2 woven inputs; lengths in millimetres."""

    topology: str = "cubic"  # cubic (n_fibers→4) | bcc (n_fibers→3)
    cells: tuple = (2, 2, 2)  # [nx, ny, nz]
    unitcell: float = 40.0  # full cell side U [mm]
    reff_over_L: float = 0.12  # bundle radius R_eff as a fraction of U
    nrev: float = 1.0  # helix revolutions per beam
    n_fibers: int = 0  # fibers per beam; 0 → auto (cubic→4, bcc→3)
    pts_per_rev: int = 24  # centerline sample density
    fiber_radius: float = 0.5  # swept-tube radius [mm] (filament Ø = 2*fiber_radius)
    bevel_resolution: int = 6  # Blender bevel smoothness (cross-section segments)
    export_stl: bool = False  # export an STL after sweeping
    stl_path: str = "woven_simple.stl"  # relative to the working directory Blender was started in

    def resolved_n_fibers(self) -> int:
        """Fibers per beam: the explicit value, else the lattice connectivity (cubic 4, bcc 3)."""
        if self.n_fibers > 0:
            return self.n_fibers
        return 4 if self.topology == "cubic" else 3

    def validate(self) -> None:
        """Reject unsupported topologies and non-physical sizes."""
        if self.topology not in ("cubic", "bcc"):
            raise ValueError(
                "woven_simple supports topology in {cubic, bcc}; use Tier-1 build.py for others"
            )
        if any(c < 1 for c in self.cells):
            raise ValueError("cells must be >= 1")
        if self.unitcell <= 0 or self.reff_over_L <= 0 or self.fiber_radius <= 0:
            raise ValueError("unitcell, reff_over_L, fiber_radius must be > 0")


# ------------------------------------- lattice (nodes + edges) ------------------------------------
def lattice_nodes_edges(P: Params):
    """Return (nodes, edges): node coordinates [mm] and integer index pairs, tessellated and de-duplicated."""
    U = P.unitcell
    h = U / 2.0
    # Unit-cell corners (relative to the cell centre) and the cell's internal edges.
    corners = [
        (-h, -h, -h),
        (h, -h, -h),
        (-h, h, -h),
        (-h, -h, h),
        (h, h, -h),
        (h, -h, h),
        (-h, h, h),
        (h, h, h),
    ]
    if P.topology == "cubic":
        local_pts = corners
        # 12 cube edges (indices into ``corners``).
        local_edges = [
            (0, 1),
            (0, 2),
            (0, 3),
            (1, 4),
            (1, 5),
            (2, 4),
            (2, 6),
            (3, 5),
            (3, 6),
            (4, 7),
            (5, 7),
            (6, 7),
        ]
    else:  # bcc: 8 corners + body centre; 8 corner→centre struts
        local_pts = corners + [(0.0, 0.0, 0.0)]
        local_edges = [(i, 8) for i in range(8)]

    nodes: list[tuple[float, float, float]] = []  # unique node coordinates (rounded) [mm]
    index_of: dict[tuple[float, float, float], int] = {}  # node coordinate -> index in nodes

    def node_index(p):
        key = (round(p[0], 4), round(p[1], 4), round(p[2], 4))  # dedupe shared nodes across cells
        if key not in index_of:
            index_of[key] = len(nodes)
            nodes.append(key)
        return index_of[key]

    # Tessellate: every cell contributes its local edges; shared nodes/edges collapse via the index.
    edges = set()
    nx, ny, nz = P.cells
    for ci in range(nx):
        for cj in range(ny):
            for ck in range(nz):
                centre = (ci * U, cj * U, ck * U)
                gidx = [node_index(_add(centre, lp)) for lp in local_pts]
                for a, b in local_edges:
                    e = (gidx[a], gidx[b])
                    edges.add((min(e), max(e)))  # undirected edge, canonical order
    return [tuple(map(float, n)) for n in nodes], sorted(edges)


# ------------------------------------- helix bundle along a beam ----------------------------------
def helix_bundle(A, B, r_eff: float, n_rev: float, n_fibers: int, pts_per_rev: int):
    """Return a list of ``n_fibers`` centerline polylines (each a list of (x,y,z)) winding around A→B."""
    axis = _normalize(_sub(B, A))
    # Build a stable frame perpendicular to the axis.
    ref = (0.0, 0.0, 1.0) if abs(axis[2]) < 0.9 else (1.0, 0.0, 0.0)
    u = _normalize(_cross(ref, axis))
    v = _cross(axis, u)  # already unit (axis ⟂ u, both unit)
    N = max(8, int(pts_per_rev * max(n_rev, 1.0))) + 1  # samples along the beam
    fibers = []
    for f in range(n_fibers):
        phase = 2.0 * math.pi * f / n_fibers  # fibers evenly spaced in phase around the bundle
        poly = []
        for s in range(N):
            t = s / (N - 1)
            centre = _add(A, _scale(_sub(B, A), t))
            ang = 2.0 * math.pi * n_rev * t + phase
            off = _add(_scale(u, r_eff * math.cos(ang)), _scale(v, r_eff * math.sin(ang)))
            poly.append(_add(centre, off))
        fibers.append(poly)
    return fibers


def generate_centerlines(P: Params):
    """All fiber centerlines for the whole tessellated lattice (n_fibers per beam × number of beams)."""
    P.validate()
    nodes, edges = lattice_nodes_edges(P)
    r_eff = P.reff_over_L * P.unitcell  # absolute bundle radius [mm]
    nf = P.resolved_n_fibers()
    out = []
    for i, j in edges:
        out.extend(helix_bundle(nodes[i], nodes[j], r_eff, P.nrev, nf, P.pts_per_rev))
    return out


def clearance(paths, fiber_radius: float, sample: int = 40) -> dict:
    """
    numpy-free min center-distance between DISTINCT fibers (subsampled).

    NOTE (Tier-2 model): fibers of different beams intentionally MEET at shared nodes (that join is what makes
    the lattice one connected, printable solid), so the global min distance is ~0 by design. This metric is
    therefore a coarse over-thickening guard, not the strict ≥1-Ø fabricability gate of the Tier-1 engine
    (which produces continuous, non-duplicated strands). For the strict check, use
    abcad/generators/woven/build.py.
    """

    def sub(p):
        # Subsample to at most ``sample`` points per fiber so the all-pairs loop stays tractable.
        if len(p) <= sample:
            return p
        step = len(p) / sample
        return [p[int(k * step)] for k in range(sample)]

    sp = [sub(p) for p in paths]
    min_d = float("inf")
    for a in range(len(sp)):
        for b in range(a + 1, len(sp)):
            for pa in sp[a]:
                for pb in sp[b]:
                    d = _norm(_sub(pa, pb))
                    if d < min_d:
                        min_d = d
    return {
        "min_center_dist": min_d,
        "max_printable_fiber_radius": min_d / 2.0,
        "interpenetrates": fiber_radius > min_d / 2.0,
    }


# ------------------------------------- Blender sweep (requires bpy) -------------------------------
def sweep(paths, fiber_radius: float, bevel_resolution: int = 6):
    """Sweep every centerline into a capped bevel tube, convert to mesh and join into one object."""
    if not _HAVE_BPY:
        raise RuntimeError(
            "sweep() needs Blender's bpy. Run: blender -b -P abcad/generators/woven/woven_simple.py -- ..."
        )
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    objs = []
    for i, pts in enumerate(paths):
        cu = bpy.data.curves.new(f"wf_{i}", "CURVE")
        cu.dimensions = "3D"
        sp = cu.splines.new("POLY")
        sp.points.add(len(pts) - 1)  # a new POLY spline already holds one point
        for k, (x, y, z) in enumerate(pts):
            sp.points[k].co = (x, y, z, 1.0)  # (x, y, z, w) homogeneous
        cu.bevel_depth = fiber_radius
        cu.bevel_resolution = bevel_resolution
        cu.use_fill_caps = True  # cap tube ends so boundary fibers close -> watertight STL
        o = bpy.data.objects.new(f"wf_{i}", cu)
        bpy.context.collection.objects.link(o)
        objs.append(o)
    # Curves -> mesh, then join all tubes into a single object.
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
    return bpy.context.object


def export_stl(path: str) -> None:
    """Export the scene's meshes to STL (Blender 4.2 operator, legacy fallback)."""
    bpy.ops.object.select_all(action="SELECT")
    try:
        bpy.ops.wm.stl_export(filepath=path, export_selected_objects=True)
    except Exception:
        bpy.ops.export_mesh.stl(filepath=path, use_selection=True)


# ----------------------------------------------- CLI ----------------------------------------------
def parse_args(argv=None) -> Params:
    """Parse CLI flags into a Params (accepts Blender's ``--`` separator or plain ``sys.argv``)."""
    import argparse

    if argv is None:
        argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    p = argparse.ArgumentParser(
        description="Compact self-contained woven-lattice generator (Tier-2)."
    )
    p.add_argument("--topology", default=Params.topology, choices=["cubic", "bcc"])
    p.add_argument("--cells", type=int, nargs=3, default=list(Params.cells))
    p.add_argument("--unitcell", type=float, default=Params.unitcell)
    p.add_argument("--reff_over_L", type=float, default=Params.reff_over_L)
    p.add_argument("--nrev", type=float, default=Params.nrev)
    p.add_argument("--n_fibers", type=int, default=Params.n_fibers)
    p.add_argument("--pts_per_rev", type=int, default=Params.pts_per_rev)
    p.add_argument("--fiber_radius", type=float, default=Params.fiber_radius)
    p.add_argument("--bevel_resolution", type=int, default=Params.bevel_resolution)
    p.add_argument("--export_stl", action="store_true")
    p.add_argument("--stl_path", default=Params.stl_path)
    ns = p.parse_args(argv)
    valid = {f.name for f in fields(Params)}
    kw = {k: v for k, v in vars(ns).items() if k in valid}
    kw["cells"] = tuple(kw["cells"])  # argparse gives a list; Params stores a tuple
    return Params(**kw)


def main(argv=None) -> None:
    """CLI entry point: generate centerlines, report clearance, sweep in Blender, optionally export."""
    P = parse_args(argv)
    paths = generate_centerlines(P)
    cl = clearance(paths, P.fiber_radius)
    print(
        f"[woven_simple] {P.topology} {tuple(P.cells)}: {len(paths)} fibers; "
        f"min center-dist={cl['min_center_dist']:.3f} mm; interpenetrates={cl['interpenetrates']}"
    )
    sweep(paths, P.fiber_radius, P.bevel_resolution)
    if P.export_stl:
        export_stl(P.stl_path)
        print(f"[woven_simple] STL → {P.stl_path}")


if __name__ == "__main__":
    main()
