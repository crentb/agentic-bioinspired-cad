"""
helicoidal.py — Parametric single-material Bouligand / helicoidal laminate generator (Blender ``bpy``).

PROJECT
    agentic-bioinspired-cad (design notes: docs/GENERATORS.md, "Helicoidal / Bouligand"). The
    helicoidal / Bouligand laminate family is built so that the toughening behaviour comes purely
    from GEOMETRY and prints in a SINGLE material.

WHAT IT PRODUCES
    A stack of ``num_plies`` thin plies along +Z. Ply ``k`` is rotated about the central (Z) axis by a
    cumulative angle ``theta_k`` whose progression (constant / graded / exponential / Fibonacci /
    double-twist / herringbone / noise) is selectable. Each ply is either a solid plate or a row of
    rectangular / cylindrical fibres. Between plies we MODEL the weak plane that gives the Bouligand its
    damage tolerance (interface = ``groove`` notch | ``airgap`` | ``solid``). Output is one (or many) Blender
    MESH object(s); optionally exported to STL for slicing/printing.

WHY SINGLE-MATERIAL WORKS (physics, one material, no hard/soft contrast)
    The locally weakest plane rotates by ``delta_theta`` per ply, so the minimum-energy fracture surface is a
    continuously TWISTING helicoid rather than a flat plane (Ning 2024; Suksangpanya Eq. 2:
    Y = -Z*tan(X*dphi/dX), dphi/dX ∝ Δθ/d = π/p). Twisting costs extra surface area and forces mixed-mode
    loading → higher work-of-fracture. Strength scales with 1/pitch (finer Δθ) and the printed material's own
    bead anisotropy. We realise the weak plane as MODELED geometry (the locked design decision): a shallow
    groove cut along the director at each interface, or the inter-fibre gaps of the fibre styles.

UNITS
    Blender units are treated as MILLIMETRES. ``ply_thickness`` should equal the intended print layer height.

USAGE (inside Blender, headless)
    blender -b -P abcad/generators/helicoidal.py -- \
        --progression constant --delta 10 --plies 36 --ply_thickness 0.2 --plate_size 40 \
        --interface groove --export_stl --stl_path out/bouligand_constant.stl
    (Arguments after the ``--`` separator are parsed here; with none, sensible PLA-coupon defaults are used.)
    Smoke-test the pipeline first with ``--interface solid`` (no Boolean ops), then switch to ``groove``.
    Blender's exporter does not create directories, so create the STL's folder first.

INPUTS / OUTPUTS
    Inputs: the ``Params`` fields (CLI flags after ``--``). Outputs: MESH objects in the current Blender
    scene, a one-line build summary on stdout, and (with ``--export_stl``) an STL at ``--stl_path``.

TESTABILITY (no Blender required for the math)
    The geometry MATH (rotation laws, layout, derived pitch/height, fibre layout) lives in pure-Python
    functions and ``bpy`` is imported under a guard, so this module can be imported WITHOUT Blender for unit
    testing (see tests/test_helicoidal_logic.py and tests/test_helicoidal_build_mock.py). The produced
    geometry itself must be verified on a machine with Blender 4.2+ (e.g. with the 3D-Print Toolbox).
    This file must stay runnable as a standalone Blender script, so it imports nothing from ``abcad``.
"""

from __future__ import annotations

import math
import random
import sys
from dataclasses import dataclass, fields

# --------------------------------------------------------------------------------------------------
# Guarded Blender import.
# ``bpy``/``mathutils`` only exist inside Blender. Importing them lazily/guarded lets this file be
# imported on a machine without Blender so the pure-Python geometry math can be unit-tested.
# --------------------------------------------------------------------------------------------------
try:
    import bpy  # type: ignore
    import mathutils  # type: ignore  # noqa: F401  (kept for future vector math; harmless if unused)

    _HAVE_BPY = True
except Exception:  # pragma: no cover - exercised only outside Blender
    bpy = None  # type: ignore
    mathutils = None  # type: ignore
    _HAVE_BPY = False


# ==================================================================================================
# Parameters
# ==================================================================================================
@dataclass
class Params:
    """All generator inputs. Defaults build a constant-pitch 10°/36-ply PLA coupon (≈40×40×7.5 mm)."""

    # --- rotation law (degrees) ---------------------------------------------------------------
    # progression: constant | graded | exponential | fibonacci | double_twist | herringbone | noise
    progression: str = "constant"
    delta_theta: float = 10.0  # base inter-ply rotation increment Δθ [deg]
    delta_min: float = 3.0  # graded: increment at the base (impact face) [deg]
    delta_max: float = 18.0  # graded: increment at the top (interior) [deg]
    ratio: float = 1.10  # exponential: per-step growth r (incrementⱼ = Δθ·r^(j-1))
    flip_every: int = 6  # herringbone: flip twist sign every N plies (chevron)
    delta_a: float = 10.0  # double_twist: increment of interleaved helicoid A (even plies) [deg]
    delta_b: float = 5.0  # double_twist: increment of interleaved helicoid B (odd plies) [deg]
    double_twist_offset: float = 90.0  # double_twist: starting angular offset between A and B [deg]
    noise_sigma: float = 0.0  # noise: ± uniform jitter added to each ply's angle [deg]
    seed: int = 0  # RNG seed (determinism for the noise progression)

    # --- stack geometry (millimetres) ---------------------------------------------------------
    num_plies: int = 36  # total number of plies N
    ply_thickness: float = 0.2  # d: lamina thickness — set equal to the print layer height [mm]
    plate_size: float = 40.0  # W: square in-plane footprint side [mm]
    # solid/groove: vertical overlap between consecutive plies so the stack fuses into one connected
    # solid for single-piece printing [mm]
    bond_overlap: float = 0.02

    # --- single-material weak-plane interface -------------------------------------------------
    interface: str = "groove"  # groove | airgap | solid
    gap: float = 0.0  # airgap: vertical air gap between plies [mm] (weak plane)
    groove_frac: float = 0.10  # groove: notch depth as a fraction of the plate HALF-width
    groove_width: float = 0.6  # groove: slot width [mm] (≈ one FDM nozzle)
    # airgap: radius of the central connector spine that holds the plies together [mm]
    spine_radius: float = 1.5

    # --- fibre style --------------------------------------------------------------------------
    fiber_style: str = "plate"  # plate | rect_fibers | cyl_fibers
    fiber_diameter: float = 1.0  # fibre Ø for fibre styles [mm] (≥ nozzle Ø for FDM)
    # gap between adjacent fibres [mm] (this gap is the weak plane for fibre styles)
    fiber_gap: float = 0.4

    # --- output -------------------------------------------------------------------------------
    join_mesh: bool = True  # join all plies into a single MESH object
    export_stl: bool = False  # export an STL after building
    stl_path: str = "helicoidal.stl"  # relative to the working directory Blender was started in

    def validate(self) -> None:
        """Cheap sanity checks with actionable messages (run before building)."""
        if self.num_plies < 1:
            raise ValueError("num_plies must be >= 1")
        if self.delta_theta <= 0 and self.progression in (
            "constant",
            "exponential",
            "herringbone",
            "noise",
        ):
            raise ValueError("delta_theta must be > 0 for this progression")
        if self.ply_thickness <= 0 or self.plate_size <= 0:
            raise ValueError("ply_thickness and plate_size must be > 0")
        if self.interface not in ("groove", "airgap", "solid"):
            raise ValueError("interface must be one of: groove, airgap, solid")
        if self.fiber_style not in ("plate", "rect_fibers", "cyl_fibers"):
            raise ValueError("fiber_style must be one of: plate, rect_fibers, cyl_fibers")
        if self.progression not in (
            "constant",
            "graded",
            "exponential",
            "fibonacci",
            "double_twist",
            "herringbone",
            "noise",
        ):
            raise ValueError(f"unknown progression: {self.progression!r}")


# ==================================================================================================
# Pure-Python geometry math (NO bpy — unit-testable without Blender)
# ==================================================================================================
def cumulative_theta_sequence(P: Params) -> list[float]:
    """
    Cumulative orientation theta_k [deg] of every ply (k = 0..N-1), with theta_0 = 0.

    Returned angles are NOT reduced mod 180; the raw cumulative twist is what we apply to the geometry
    (e.g. a 4-pitch stack genuinely sweeps 720°). The mod-180 equivalence of the director is purely a
    physical interpretation and does not affect the rotation transform.
    """
    N = P.num_plies
    prog = P.progression

    if prog == "constant":
        # Δθ fixed every step → theta_k = k·Δθ.
        return [k * P.delta_theta for k in range(N)]

    if prog == "graded":
        # Increment grows linearly from delta_min (first step) to delta_max (last step). Mirrors the
        # dactyl-club gradient: small angle near the impact face, larger angle toward the interior.
        thetas = [0.0]
        for k in range(1, N):
            frac = (k - 1) / (N - 2) if N > 2 else 0.0
            inc = P.delta_min + (P.delta_max - P.delta_min) * frac
            thetas.append(thetas[-1] + inc)
        return thetas

    if prog == "exponential":
        # incrementⱼ = Δθ · r^(j-1) → tortuous, accelerating twist.
        thetas = [0.0]
        for k in range(1, N):
            inc = P.delta_theta * (P.ratio ** (k - 1))
            thetas.append(thetas[-1] + inc)
        return thetas

    if prog == "fibonacci":
        # Increments follow a Fibonacci series scaled so the first increment == delta_theta.
        fib = [1, 1]
        while len(fib) < max(2, N):
            fib.append(fib[-1] + fib[-2])
        thetas = [0.0]
        for k in range(1, N):
            inc = P.delta_theta * (fib[k - 1] / fib[0])
            thetas.append(thetas[-1] + inc)
        return thetas

    if prog == "herringbone":
        # Chevron Bouligand: the twist sense flips every ``flip_every`` plies.
        thetas = [0.0]
        for k in range(1, N):
            sign = 1 if ((k - 1) // max(1, P.flip_every)) % 2 == 0 else -1
            thetas.append(thetas[-1] + sign * P.delta_theta)
        return thetas

    if prog == "double_twist":
        # Two interleaved helicoids (coelacanth-inspired, the literature's best-toughness variant):
        # even plies belong to helicoid A (step delta_a); odd plies to helicoid B (step delta_b) offset
        # by ``double_twist_offset``.
        out = []
        for k in range(N):
            if k % 2 == 0:
                out.append((k // 2) * P.delta_a)
            else:
                out.append((k // 2) * P.delta_b + P.double_twist_offset)
        return out

    if prog == "noise":
        # Constant pitch + per-ply uniform jitter (biological irregularity). Seeded for determinism.
        rng = random.Random(P.seed)
        return [k * P.delta_theta + rng.uniform(-P.noise_sigma, P.noise_sigma) for k in range(N)]

    raise ValueError(f"unknown progression: {prog!r}")


def fiber_centers(P: Params) -> list[float]:
    """Y-offsets of the fibre centrelines across the plate width (for the fibre styles), symmetric about 0."""
    spacing = P.fiber_diameter + P.fiber_gap  # centre-to-centre pitch of the fibre row [mm]
    n = max(1, int(P.plate_size // spacing))  # how many fibres fit across the footprint
    total = n * spacing
    # First centre: half a fibre in from the left edge, shifted so the row is centred on 0.
    start = -P.plate_size / 2 + P.fiber_diameter / 2 + (P.plate_size - total) / 2
    return [start + i * spacing for i in range(n)]


def derived_geometry(P: Params) -> dict:
    """Human-readable derived quantities (for logging, QC, and the build summary)."""
    thetas = cumulative_theta_sequence(P)
    # Plies per 180° (one full director revolution) under a constant-pitch interpretation.
    n_per_pitch = (180.0 / P.delta_theta) if P.delta_theta > 0 else float("inf")
    step = P.ply_thickness + (P.gap if P.interface == "airgap" else 0.0)  # z advance per ply [mm]
    total_height = P.num_plies * step
    return {
        "plies": P.num_plies,
        "plies_per_180deg": n_per_pitch,
        "pitch_mm": n_per_pitch * P.ply_thickness,
        "total_height_mm": total_height,
        "total_sweep_deg": (thetas[-1] - thetas[0]) if thetas else 0.0,
        "footprint_mm": (P.plate_size, P.plate_size),
        "interface": P.interface,
        "fiber_style": P.fiber_style,
    }


# ==================================================================================================
# Blender build (requires bpy)
# ==================================================================================================
def _require_bpy() -> None:
    """Fail with a runnable hint when a Blender-only function is called outside Blender."""
    if not _HAVE_BPY:
        raise RuntimeError(
            "This function needs Blender's bpy. Run inside Blender, e.g.:\n"
            "  blender -b -P abcad/generators/helicoidal.py -- --progression constant --plies 36"
        )


def clear_scene() -> None:
    """Delete everything so the script is self-contained (the base-script convention)."""
    _require_bpy()
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def _add_box(size_xyz, location):
    """Add a unit cube and set its bounding-box dimensions; bake the scale into the mesh."""
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.object
    obj.dimensions = size_xyz
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return obj


def _cut_groove(P: Params, plate, z_top: float) -> None:
    """
    Cut a shallow slot along the director (X at θ=0) into the TOP face of ``plate`` using a Boolean
    DIFFERENCE modifier. The plate is still axis-aligned here, so after the caller rotates the plate by
    θ_k the groove rotates with it → the weak plane ends up along the director. Modelled weak plane.
    """
    depth = P.groove_frac * (P.plate_size / 2.0)
    # Cutter: long along X (the director), thin along Y, straddling the top face so it removes ``depth``.
    cutter = _add_box(
        (P.plate_size * 1.5, P.groove_width, depth * 2.0),
        (0.0, 0.0, z_top),
    )
    mod = plate.modifiers.new(name="groove", type="BOOLEAN")
    mod.operation = "DIFFERENCE"
    mod.object = cutter
    bpy.context.view_layer.objects.active = plate
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(cutter, do_unlink=True)


def _make_ply_plate(P: Params, z_bottom: float, theta_deg: float):
    """A solid square plate ply (default style). Optionally grooved, then rotated by θ_k about the Z axis."""
    overlap = P.bond_overlap if P.interface in ("solid", "groove") else 0.0
    height = P.ply_thickness + overlap  # slight overlap fuses neighbours for printing
    z_center = z_bottom + P.ply_thickness / 2.0
    plate = _add_box((P.plate_size, P.plate_size, height), (0.0, 0.0, z_center))
    if P.interface == "groove":
        _cut_groove(P, plate, z_top=z_center + height / 2.0)
    # Rotate about the object's own origin, which sits on the central Z axis → twist about the stack axis.
    plate.rotation_euler = (0.0, 0.0, math.radians(theta_deg))
    bpy.context.view_layer.objects.active = plate
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
    return plate


def _make_ply_fibers(P: Params, z_bottom: float, theta_deg: float, shape: str):
    """
    A ply made of parallel fibres (rect or cyl) along X, spread along Y. The inter-fibre gaps are the
    modelled weak planes. Fibres are joined, the origin is moved to the central axis, then the ply is
    rotated by θ_k so the fibre direction = the director.
    """
    z_center = z_bottom + P.ply_thickness / 2.0
    objs = []
    for y in fiber_centers(P):
        if shape == "rect_fibers":
            o = _add_box((P.plate_size, P.fiber_diameter, P.ply_thickness), (0.0, y, z_center))
        else:  # cyl_fibers — a rod along X (rotate the default +Z cylinder 90° about Y)
            bpy.ops.mesh.primitive_cylinder_add(
                radius=P.fiber_diameter / 2.0,
                depth=P.plate_size,
                location=(0.0, y, z_center),
                rotation=(0.0, math.radians(90.0), 0.0),
            )
            o = bpy.context.object
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
        objs.append(o)

    # Join the fibres of this ply into one object.
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    ply = bpy.context.object

    # Move the origin onto the central axis at this height, then rotate the whole ply about it.
    bpy.context.scene.cursor.location = (0.0, 0.0, z_center)
    bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
    ply.rotation_euler = (0.0, 0.0, math.radians(theta_deg))
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
    bpy.context.scene.cursor.location = (0.0, 0.0, 0.0)
    return ply


def _make_spine(P: Params, total_height: float):
    """Central cylindrical spine that holds airgap-separated plies together for single-piece printing."""
    bpy.ops.mesh.primitive_cylinder_add(
        radius=P.spine_radius, depth=total_height, location=(0.0, 0.0, total_height / 2.0)
    )
    return bpy.context.object


def _join_all(objs) -> None:
    """Join a list of mesh objects into one."""
    objs = [o for o in objs if o is not None]
    if not objs:
        return
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()


def _export_stl(path: str) -> None:
    """Export the (selected) meshes to STL, handling both the Blender 4.2 and legacy operators."""
    bpy.ops.object.select_all(action="SELECT")
    try:
        bpy.ops.wm.stl_export(filepath=path, export_selected_objects=True)  # Blender 4.2+
    except Exception:
        bpy.ops.export_mesh.stl(filepath=path, use_selection=True)  # legacy fallback


def build(P: Params):
    """Build the helicoidal laminate in the current Blender scene and return the list of created objects."""
    _require_bpy()
    P.validate()
    random.seed(P.seed)
    clear_scene()

    thetas = cumulative_theta_sequence(P)
    step = P.ply_thickness + (P.gap if P.interface == "airgap" else 0.0)  # z advance per ply [mm]

    # --- one ply per layer, each rotated by its cumulative angle ---
    plies = []
    for k in range(P.num_plies):
        z_bottom = k * step
        if P.fiber_style == "plate":
            plies.append(_make_ply_plate(P, z_bottom, thetas[k]))
        else:
            plies.append(_make_ply_fibers(P, z_bottom, thetas[k], P.fiber_style))

    # --- airgap stacks need a connector spine to print as one piece ---
    extras = []
    if P.interface == "airgap":
        extras.append(_make_spine(P, total_height=P.num_plies * step))

    all_objs = plies + extras
    if P.join_mesh:
        _join_all(all_objs)

    info = derived_geometry(P)
    print(
        "[helicoidal] built:",
        {k: (round(v, 3) if isinstance(v, float) else v) for k, v in info.items()},
    )
    return all_objs


# ==================================================================================================
# CLI (arguments after the Blender ``--`` separator)
# ==================================================================================================
def parse_args(argv=None) -> Params:
    """Parse CLI args into a Params. Booleans are flags; everything else maps by name to a Params field."""
    import argparse

    if argv is None:
        # Blender passes script args after a literal "--"; take everything past it. Without a "--"
        # (e.g. `blender -b -P helicoidal.py`) Blender's own flags are in sys.argv, so use defaults.
        argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []

    p = argparse.ArgumentParser(
        description="Single-material Bouligand/helicoidal generator (Blender bpy)."
    )
    p.add_argument("--progression", default=Params.progression)
    p.add_argument("--delta", dest="delta_theta", type=float, default=Params.delta_theta)
    p.add_argument("--delta_min", type=float, default=Params.delta_min)
    p.add_argument("--delta_max", type=float, default=Params.delta_max)
    p.add_argument("--ratio", type=float, default=Params.ratio)
    p.add_argument("--flip_every", type=int, default=Params.flip_every)
    p.add_argument("--delta_a", type=float, default=Params.delta_a)
    p.add_argument("--delta_b", type=float, default=Params.delta_b)
    p.add_argument("--double_twist_offset", type=float, default=Params.double_twist_offset)
    p.add_argument("--noise_sigma", type=float, default=Params.noise_sigma)
    p.add_argument("--seed", type=int, default=Params.seed)
    p.add_argument("--plies", dest="num_plies", type=int, default=Params.num_plies)
    p.add_argument("--ply_thickness", type=float, default=Params.ply_thickness)
    p.add_argument("--plate_size", type=float, default=Params.plate_size)
    p.add_argument("--bond_overlap", type=float, default=Params.bond_overlap)
    p.add_argument("--interface", default=Params.interface)
    p.add_argument("--gap", type=float, default=Params.gap)
    p.add_argument("--groove_frac", type=float, default=Params.groove_frac)
    p.add_argument("--groove_width", type=float, default=Params.groove_width)
    p.add_argument("--spine_radius", type=float, default=Params.spine_radius)
    p.add_argument("--fiber_style", default=Params.fiber_style)
    p.add_argument("--fiber_diameter", type=float, default=Params.fiber_diameter)
    p.add_argument("--fiber_gap", type=float, default=Params.fiber_gap)
    p.add_argument("--no_join", dest="join_mesh", action="store_false")
    p.add_argument("--export_stl", action="store_true")
    p.add_argument("--stl_path", default=Params.stl_path)
    ns = p.parse_args(argv)

    # Keep only names that are Params fields (argparse dests match field names by construction).
    valid = {f.name for f in fields(Params)}
    return Params(**{k: v for k, v in vars(ns).items() if k in valid})


def main(argv=None) -> None:
    """CLI entry point: parse args, build the laminate in the open Blender scene, optionally export."""
    P = parse_args(argv)
    build(P)
    if P.export_stl:
        _export_stl(P.stl_path)
        print(f"[helicoidal] exported STL → {P.stl_path}")


if __name__ == "__main__":
    # Runs both when executed by Blender (``blender -P ...``) and as a script if bpy is importable.
    main()
