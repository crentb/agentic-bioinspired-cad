"""
abcad/generators/enamel.py — Decussated enamel-rod lattice generator (SINGLE MATERIAL).

PROJECT
    agentic-bioinspired-cad: the third damage-tolerance family alongside the woven lattices and the
    helicoidal / Bouligand laminates (design notes: docs/GENERATORS.md). Ported from the author's
    microCT-grounded enamel work; the cadquery original ``radial_enamel_lattice_continuous_twist.py``
    remains the golden reference (see docs/validation/enamel_goldens.md).

WHAT IT PRODUCES (the biology)
    Dental enamel's damage tolerance comes from DECUSSATION: enamel rods (prisms) are bundled
    and adjacent bundles CROSS between layers (Hunter-Schreger bands). A crack cannot run
    straight — it must repeatedly twist to follow the rotating rod direction, which multiplies
    the work of fracture (a rising, "J-shaped" R-curve). We model this as "rotating plywood":
      * rods packed on concentric HEXAGONAL rings (center rod; ring k has 6k rods at radius
        k*spacing) — the natural close packing of prisms;
      * each ring is twisted about the central axis by a per-ring angle over the specimen
        height. Adjacent rings twist by DIFFERENT, typically ALTERNATING-SIGN angles — that
        sign flip between neighbours IS the decussation (crossing) that deflects cracks;
      * the twist develops along the height by a selectable LAW (linear / accelerating /
        sigmoid) — THE damage-tolerance design lever: the twist profile, not just its
        magnitude, shapes the R-curve;
      * interrod BRIDGES (thin single-material struts) tie adjacent rods within a ring together
        at several heights, making the bundle a connected, printable, load-bearing solid.

WHY SINGLE MATERIAL (the hard constraint, honored)
    Real enamel has a soft protein interrod sheath; we DO NOT use a soft phase (the two-phase
    soft/stiff STEP models of the original microCT project are explicitly excluded). Here the rods
    AND the bridges are the SAME material — all toughness comes from GEOMETRY (crack twisting + the
    connected bridge network), never a modulus contrast. (The Jia & Wang two-material contrast
    numbers do not transfer — see docs/LITERATURE.md.)

HOW IT IS REALIZED (engineering choice, 2026-07-05)
    The architecture is swept into an STL via the VALIDATED woven numpy-stl tube mesher
    (abcad/generators/woven/build.py :: sweep_to_stl_numpy, vendored Portela save_piped_stl),
    NOT via OCCT/cadquery boolean unions. Rationale: memory safety comes first on a 16 GB
    workstation; the cadquery exports are 34-137 MB (too heavy for our voxelizer); boolean-unioning
    ~90 helical rods + hundreds of bridges is the fragile, RAM-hungry path. Tubes coexist as separate
    shells exactly like the woven family — the downstream voxelizer (print_audit /
    damage_tolerance) unions them implicitly. The cadquery original remains the golden for
    architecture validation; a high-fidelity cadquery STEP export can be added later if needed.

GEOMETRY MATH IS BLENDER/CAD-FREE + UNIT-TESTED
    hex_ring_positions / twist_angle / rod_centerline / bridge_segments are pure numpy and are
    exercised by tests/test_enamel_logic.py (house pattern: prove the math cheaply
    before spending RAM on a sweep).

USAGE (cad_env python — needs numpy-stl + matplotlib + pyvista, all present in cad_env)
    "$ABCAD_CAD_PYTHON" -m abcad.generators.enamel \
        --rings 5 --rod_diameter 0.5 --spacing 0.6 --thickness 5.0 \
        --twist_type linear --rotations 0,10,-20,30,-45,60 \
        --scale 4 --stl out/enamel_lattice.stl
    (or run the file directly: "$ABCAD_CAD_PYTHON" abcad/generators/enamel.py ...)
    (scale is uniform, applied to ALL lengths — the print/FEA sizing knob, exactly like the
    woven x2.0 lineage: build faithful, then scale so Ø rods clear the FDM limit / resolve in
    the voxel mesh. Native Ø0.5 mm rods are sub-nozzle and sub-voxel; scale 4 -> Ø2 mm.)

OUTPUTS
    <stl>            watertight-reportable STL (rods + bridges as coexisting tube shells);
                     default ``$ABCAD_OUT/enamel_lattice.stl`` (``./out`` when ABCAD_OUT is unset)
    <stl>.png        pyvista render (unless --no_render)
    stdout           rod/bridge counts, bbox, watertight report, R-curve info note
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import os
import sys
from dataclasses import dataclass

import numpy as np

# --------------------------------------------------------------------------------------------
# Reuse the woven family's VALIDATED watertight tube mesher + QC helpers (DRY).
# Normal case: import it from the installed package. Standalone case (this file executed by a
# conda interpreter where abcad is not installed): load the sibling woven/build.py by file path.
# The module is registered in sys.modules BEFORE execution because its @dataclass resolves
# annotations through sys.modules[cls.__module__].
# --------------------------------------------------------------------------------------------
try:
    from abcad.generators.woven import build as _wb
except ModuleNotFoundError as _e:
    if not (_e.name or "").startswith("abcad"):
        raise  # a real third-party dependency is missing; do not mask it
    _HERE = os.path.dirname(os.path.abspath(__file__))
    _WOVEN_BUILD = os.path.normpath(os.path.join(_HERE, "woven", "build.py"))
    _spec = importlib.util.spec_from_file_location("woven_build", _WOVEN_BUILD)
    if _spec is None or _spec.loader is None:  # the sibling file is missing or unreadable
        raise ImportError(f"cannot load the woven builder from {_WOVEN_BUILD}") from _e
    _wb = importlib.util.module_from_spec(_spec)
    sys.modules["woven_build"] = _wb
    _spec.loader.exec_module(_wb)
sweep_to_stl_numpy = _wb.sweep_to_stl_numpy  # (paths, radius, pts, eccentricity, stl_path)
watertight_report = _wb.watertight_report
render_png = _wb.render_png

# Output root: ./out under the working directory unless ABCAD_OUT points elsewhere.
_OUT_ROOT = os.environ.get("ABCAD_OUT", "out")


# ============================================================================================
# Parameters
# ============================================================================================
@dataclass
class Params:
    """Enamel-lattice inputs; lengths in millimetres at native enamel scale (before ``scale``)."""

    # --- lattice packing (mm; native enamel scale) ---
    rod_diameter: float = 0.5  # rod (prism) diameter [mm]
    center_spacing: float = 0.6  # center-to-center spacing of adjacent rods [mm]
    thickness: float = 5.0  # specimen height along the rod/twist axis (+Z) [mm]
    n_rings: int = 5  # concentric hex rings around the center rod

    # --- decussation twist (THE design lever) ---
    twist_type: str = "linear"  # linear | accelerating | sigmoid  (twist law θ(z))
    # per-ring TOTAL twist over the full height [deg], index = ring number (0 = center).
    # Alternating signs between neighbours = the crossing (decussation) that deflects cracks.
    ring_rotation: tuple = (0.0, 10.0, -20.0, 30.0, -45.0, 60.0)
    z_samples: int = 24  # points along each helical rod centerline (smoothness)

    # --- interrod bridges (single-material connectivity) ---
    bridges: bool = True  # tie adjacent same-ring rods with thin struts
    bridge_diameter: float = 0.25  # strut diameter [mm]
    n_bridge_layers: int = 8  # number of z-heights at which bridges are placed

    # --- sweep / fabrication ---
    pts: int = 10  # circumferential facets per tube cross-section
    scale: float = 1.0  # UNIFORM scale on all lengths (print/FEA sizing knob)

    # --- I/O ---
    stl_path: str = os.path.join(_OUT_ROOT, "enamel_lattice.stl")
    png_path: str = ""  # "" -> <stl_path>.png
    render: bool = True

    def validate(self) -> None:
        """Reject unknown twist laws and non-physical sizes."""
        if self.twist_type not in ("linear", "accelerating", "sigmoid"):
            raise ValueError(
                f"twist_type must be linear|accelerating|sigmoid, got {self.twist_type!r}"
            )
        if self.n_rings < 0:
            raise ValueError("n_rings must be >= 0")
        if self.rod_diameter <= 0 or self.center_spacing <= 0 or self.thickness <= 0:
            raise ValueError("rod_diameter, center_spacing, thickness must be > 0")
        if self.bridge_diameter >= self.rod_diameter:
            raise ValueError("bridge_diameter should be < rod_diameter (a thin strut)")
        if self.scale <= 0:
            raise ValueError("scale must be > 0")

    def ring_rot(self, ring: int) -> float:
        """Total twist [deg] for a ring; rings beyond the given tuple reuse the last value."""
        if not self.ring_rotation:
            return 0.0
        return (
            float(self.ring_rotation[ring])
            if ring < len(self.ring_rotation)
            else float(self.ring_rotation[-1])
        )


# ============================================================================================
# Geometry core — PURE numpy, no CAD backend (unit-tested Blender-free)
# ============================================================================================
def twist_angle(z: float, H: float, total_deg: float, kind: str) -> float:
    """
    Twist angle [rad] developed at height z for a rod whose TOTAL twist over height H is
    total_deg. `kind` is the damage-tolerance design lever:
      linear       θ(z) = (z/H)·Δθ                      constant angular velocity (baseline R-curve)
      accelerating θ(z) = (z/H)²·Δθ                     twist rate rises with crack depth (steeper R-curve)
      sigmoid      θ(z) = S(z/H)·Δθ, S = normalized     slow-fast-slow (gentler, more printable ends)
    """
    dtheta = math.radians(total_deg)
    u = z / H if H else 0.0  # normalized height in [0, 1]
    if kind == "linear":
        return u * dtheta
    if kind == "accelerating":
        return (u**2) * dtheta
    if kind == "sigmoid":
        k = 6.0  # steepness; endpoints normalized so S(0)=0, S(1)=1
        s = 1.0 / (1.0 + math.exp(-k * (u - 0.5)))
        s0 = 1.0 / (1.0 + math.exp(k * 0.5))  # raw logistic value at u = 0
        s1 = 1.0 / (1.0 + math.exp(-k * 0.5))  # raw logistic value at u = 1
        return ((s - s0) / (s1 - s0)) * dtheta
    raise ValueError(f"unknown twist kind {kind!r}")


def hex_ring_positions(n_rings: int, spacing: float):
    """
    Base (z=0) rod centers on concentric hexagonal rings — the enamel prism packing.
    Ring 0 = the single center rod; ring k has 6k rods evenly spaced at radius k·spacing.
    Returns a list of (x, y, ring, theta0) with theta0 the base azimuth [rad].
    """
    positions = [(0.0, 0.0, 0, 0.0)]  # center rod
    for k in range(1, n_rings + 1):
        radius = k * spacing
        n_rods = 6 * k
        for i in range(n_rods):
            theta = 2.0 * math.pi * i / n_rods
            positions.append((radius * math.cos(theta), radius * math.sin(theta), k, theta))
    return positions


def rod_centerline(
    theta0: float, radius: float, ring_rotation_deg: float, H: float, z_samples: int, kind: str
) -> np.ndarray:
    """
    Helical centerline of one rod as an (z_samples, 3) array. The rod stays at constant radius
    and sweeps in azimuth by twist_angle(z) — the rotating-plywood helix. The center rod
    (radius≈0) is a straight axial segment.
    """
    zs = np.linspace(0.0, H, z_samples)
    if radius < 1e-9:
        return np.column_stack([np.zeros_like(zs), np.zeros_like(zs), zs])
    thetas = theta0 + np.array([twist_angle(z, H, ring_rotation_deg, kind) for z in zs])
    return np.column_stack([radius * np.cos(thetas), radius * np.sin(thetas), zs])


def _rod_point_at(
    theta0: float, radius: float, ring_rotation_deg: float, z: float, H: float, kind: str
):
    """(x, y) of a rod centerline at height z (used to anchor bridges to moving rods)."""
    if radius < 1e-9:
        return 0.0, 0.0
    th = theta0 + twist_angle(z, H, ring_rotation_deg, kind)
    return radius * math.cos(th), radius * math.sin(th)


def bridge_segments(P: Params):
    """
    Interrod bridge centerlines: within each ring, connect ADJACENT rods (sorted by azimuth)
    at n_bridge_layers heights. Each bridge is anchored at the two rods' SURFACE points (offset
    radially outward by rod_R - bridge_R so the strut lands on the rod skin, not the axis), at
    the rods' twisted positions at that height. Returns a list of (P0, P1) endpoint tuples.
    """
    if not P.bridges or P.n_rings < 1:
        return []
    R = P.rod_diameter / 2.0
    rb = P.bridge_diameter / 2.0
    surf = R - rb  # radial offset onto the rod surface
    H = P.thickness
    segs = []
    for ring in range(1, P.n_rings + 1):
        radius = ring * P.center_spacing
        rot = P.ring_rot(ring)
        n_rods = 6 * ring
        base_thetas = sorted(2.0 * math.pi * i / n_rods for i in range(n_rods))
        for layer in range(1, P.n_bridge_layers + 1):
            z = (layer / (P.n_bridge_layers + 1)) * H  # interior heights, none at the faces
            for i in range(n_rods):
                t0 = base_thetas[i]
                t1 = base_thetas[(i + 1) % n_rods]  # wrap: last rod bridges back to the first
                x0, y0 = _rod_point_at(t0, radius, rot, z, H, P.twist_type)
                x1, y1 = _rod_point_at(t1, radius, rot, z, H, P.twist_type)
                a0 = math.atan2(y0, x0)
                a1 = math.atan2(y1, x1)
                p0 = (x0 + surf * math.cos(a0), y0 + surf * math.sin(a0), z)
                p1 = (x1 + surf * math.cos(a1), y1 + surf * math.sin(a1), z)
                segs.append((p0, p1))
    return segs


def build_centerlines(P: Params):
    """
    Assemble all rod centerlines and bridge centerlines (each densified to >=4 points so the
    tube spline is well-posed), applying the uniform scale. Returns (rod_paths, bridge_paths).
    """
    s = P.scale
    H = P.thickness * s
    rod_paths = []
    for x0, y0, ring, theta0 in hex_ring_positions(P.n_rings, P.center_spacing * s):
        radius = math.hypot(x0, y0)
        path = rod_centerline(theta0, radius, P.ring_rot(ring), H, P.z_samples, P.twist_type)
        rod_paths.append(path)
    bridge_paths = []
    for p0, p1 in bridge_segments(_scaled_for_bridges(P)):
        a = np.array(p0) * 1.0
        b = np.array(p1) * 1.0
        bridge_paths.append(np.linspace(a, b, 4))  # short strut -> 4-point centerline
    return rod_paths, bridge_paths


def _scaled_for_bridges(P: Params) -> Params:
    """Bridges computed in the SCALED frame so struts land on the scaled rod surfaces."""
    s = P.scale
    return Params(
        rod_diameter=P.rod_diameter * s,
        center_spacing=P.center_spacing * s,
        thickness=P.thickness * s,
        n_rings=P.n_rings,
        twist_type=P.twist_type,
        ring_rotation=P.ring_rotation,
        z_samples=P.z_samples,
        bridges=P.bridges,
        bridge_diameter=P.bridge_diameter * s,
        n_bridge_layers=P.n_bridge_layers,
    )


# ============================================================================================
# Build stage — sweep to a watertight STL via the woven numpy-stl mesher
# ============================================================================================
def build_stl(P: Params) -> dict:
    """
    Sweep rods (at rod radius) and bridges (at bridge radius) into tube shells and MERGE them
    into one STL. Two radii => two sweeps => concatenate triangles (the voxelizer unions the
    shells implicitly, as for the woven family). Returns the watertight report dict.
    """
    P.validate()
    from stl import mesh as stlmesh

    rod_paths, bridge_paths = build_centerlines(P)
    rod_r = (P.rod_diameter / 2.0) * P.scale  # swept rod radius in the scaled frame [mm]
    brg_r = (P.bridge_diameter / 2.0) * P.scale  # swept bridge radius in the scaled frame [mm]
    os.makedirs(os.path.dirname(os.path.abspath(P.stl_path)) or ".", exist_ok=True)

    # Two temporary STLs next to the target (one per tube radius), merged and then deleted.
    tmp_rods = P.stl_path + ".rods.tmp.stl"
    sweep_to_stl_numpy(rod_paths, rod_r, P.pts, 1.0, tmp_rods)
    parts = [stlmesh.Mesh.from_file(tmp_rods).data]

    if bridge_paths:
        tmp_brg = P.stl_path + ".bridges.tmp.stl"
        sweep_to_stl_numpy(bridge_paths, brg_r, P.pts, 1.0, tmp_brg)
        parts.append(stlmesh.Mesh.from_file(tmp_brg).data)
        os.remove(tmp_brg)
    os.remove(tmp_rods)

    combined = stlmesh.Mesh(np.concatenate(parts))
    combined.save(P.stl_path)

    rep = watertight_report(P.stl_path)
    rep["n_rods"] = len(rod_paths)
    rep["n_bridges"] = len(bridge_paths)
    print(
        f"[enamel] {P.twist_type} twist, {P.n_rings} rings, scale x{P.scale}: "
        f"{len(rod_paths)} rods + {len(bridge_paths)} bridges -> {P.stl_path}"
    )
    print(
        f"[enamel] {rep['n_tris']} tris; bbox_mm={rep['bbox_mm']}; "
        f"open_edges={rep['open_edges']}; watertight={rep['watertight']}"
    )

    if P.render:
        png = P.png_path or (os.path.splitext(P.stl_path)[0] + ".png")
        render_png(P.stl_path, png)
        print(f"[enamel] render -> {png}")
    return rep


# ============================================================================================
# CLI
# ============================================================================================
def parse_args(argv=None) -> Params:
    """Parse CLI flags into a Params (``--rotations`` is a comma-separated per-ring list)."""
    p = argparse.ArgumentParser(description="Decussated enamel-rod lattice (single material).")
    p.add_argument("--rings", type=int, default=Params.n_rings)
    p.add_argument("--rod_diameter", type=float, default=Params.rod_diameter)
    p.add_argument("--spacing", type=float, default=Params.center_spacing)
    p.add_argument("--thickness", type=float, default=Params.thickness)
    p.add_argument(
        "--twist_type",
        default=Params.twist_type,
        choices=["linear", "accelerating", "sigmoid"],
    )
    p.add_argument(
        "--rotations",
        default=",".join(str(x) for x in Params.ring_rotation),
        help="comma-separated per-ring total twist [deg], index 0 = center rod",
    )
    p.add_argument("--z_samples", type=int, default=Params.z_samples)
    p.add_argument("--no_bridges", dest="bridges", action="store_false")
    p.add_argument("--bridge_diameter", type=float, default=Params.bridge_diameter)
    p.add_argument("--bridge_layers", type=int, default=Params.n_bridge_layers)
    p.add_argument("--pts", type=int, default=Params.pts)
    p.add_argument("--scale", type=float, default=Params.scale)
    p.add_argument("--stl", dest="stl_path", default=Params.stl_path)
    p.add_argument("--png", dest="png_path", default=Params.png_path)
    p.add_argument("--no_render", dest="render", action="store_false")
    ns = p.parse_args(argv)
    rotations = (
        tuple(float(x) for x in ns.rotations.split(",")) if ns.rotations else Params.ring_rotation
    )
    return Params(
        rod_diameter=ns.rod_diameter,
        center_spacing=ns.spacing,
        thickness=ns.thickness,
        n_rings=ns.rings,
        twist_type=ns.twist_type,
        ring_rotation=rotations,
        z_samples=ns.z_samples,
        bridges=ns.bridges,
        bridge_diameter=ns.bridge_diameter,
        n_bridge_layers=ns.bridge_layers,
        pts=ns.pts,
        scale=ns.scale,
        stl_path=ns.stl_path,
        png_path=ns.png_path,
        render=ns.render,
    )


def main(argv=None) -> None:
    """CLI entry point: build the enamel lattice STL (and render) from command-line flags."""
    build_stl(parse_args(argv))


if __name__ == "__main__":
    main()
