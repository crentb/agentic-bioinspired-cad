"""
abcad.agent.blender_harness — the script Blender runs for every candidate: execute, measure, render.

PURPOSE
    Executed by headless Blender as ``blender -b --python blender_harness.py -- <job.json>``. It
    runs one candidate script, then turns whatever the script built into evidence the loop can
    judge: a deterministic studio render, geometry statistics and an STL export. Results are
    reported on stdout through a line protocol that ``blender.py`` parses:

        ABCAD_BLENDER: <version>          Blender version string
        ABCAD_OBJECTS: <n>                number of objects after the candidate ran
        MESH_STATS: {"bbox_mm": [x, y, z], "overhang_area_frac": f}
        Render saved at <path>
        STL_PATH: <absolute path>         only when the export produced a file
        STL_EXPORT_FAILED: <message>      informational; the export is non-fatal
        ABCAD_EXEC: OK                    success marker (success is decided by this line)
        ABCAD_EXEC: FAIL <exception>      failure marker; the traceback goes to stderr

STUDIO SETUP (why each step exists)
    * gray material ramp: distinct neutral shades separate touching objects without implying a
      material the part will not have;
    * mid-gray world (0.2): ambient fill plus a clean silhouette for dark, thin struts;
    * world-space bounds: camera and light are placed from the true extent (a local-coordinate
      box mis-sized scaled lattices in earlier renders);
    * key light above the part with energy proportional to diag^2 (inverse-square falloff) so
      large lattices do not render dark;
    * three-quarter camera at 1.8 x diag, far clip >= 12 x diag, aimed at the center.

RESTRICTIONS
    Runs inside Blender's embedded Python: it imports nothing from ``abcad``, and ``bpy`` /
    ``mathutils`` are imported inside ``main`` only. The pure helpers below implement the placement
    and statistics formulas and are unit-tested without Blender.

SECURITY
    The candidate is model-generated code. It is executed here, inside the Blender subprocess the
    loop starts with a timeout and its own process group, and never inside the loop's own process.
"""

from __future__ import annotations

import json
import math
import os
import random
import sys
import traceback
from collections.abc import Iterable, Sequence
from typing import Any

Vec3 = tuple[float, float, float]

# ---- stdout protocol markers (parsed by abcad.agent.blender) ------------------------------------
MARK_BLENDER = "ABCAD_BLENDER: "
MARK_OBJECTS = "ABCAD_OBJECTS: "
MARK_MESH_STATS = "MESH_STATS: "
MARK_STL_PATH = "STL_PATH: "
MARK_STL_FAILED = "STL_EXPORT_FAILED: "
MARK_EXEC_OK = "ABCAD_EXEC: OK"
MARK_EXEC_FAIL = "ABCAD_EXEC: FAIL "

# ---- studio constants ---------------------------------------------------------------------------
WORLD_GRAY = (0.2, 0.2, 0.2, 1.0)  # RGBA world background (ambient fill + silhouette)
CAMERA_DIRECTION = (1.0, -1.0, 0.6)  # three-quarter view, normalized in camera_placement()
CAMERA_DISTANCE_FACTOR = 1.8  # camera distance = 1.8 x bounding-box diagonal
OVERHANG_COS_LIMIT = -0.7071  # face normals below this z-cosine point > 45 degrees downward


# ==================================================================================================
# Pure helpers (no bpy): the formulas behind the studio setup and the statistics
# ==================================================================================================
def bbox_diagonal(bmin: Sequence[float], bmax: Sequence[float]) -> float:
    """Euclidean length of the bounding-box diagonal, floored at 1.0 (so tiny parts stay framed)."""
    length = math.sqrt(sum((hi - lo) ** 2 for lo, hi in zip(bmin, bmax)))
    return max(length, 1.0)


def camera_placement(center: Sequence[float], diag: float) -> tuple[Vec3, float]:
    """Camera location and far clip for a part of the given center and diagonal.

    The camera sits along the unit direction of (1, -1, 0.6) at distance 1.8 x diag from the
    center; ``clip_end = max(1000, 12 x diag)`` keeps large parts inside the view frustum.

    Returns:
        ``(location, clip_end)``.
    """
    norm = math.sqrt(sum(c * c for c in CAMERA_DIRECTION))
    distance = CAMERA_DISTANCE_FACTOR * diag
    location = tuple(c + (d / norm) * distance for c, d in zip(center, CAMERA_DIRECTION))
    return (location[0], location[1], location[2]), max(1000.0, 12.0 * diag)


def key_light(center: Sequence[float], max_z: float, diag: float) -> tuple[Vec3, float, float]:
    """Area key light placed one diagonal above the part's top.

    ``energy = max(800, 5 * diag^2)`` [W] grows with distance squared (inverse-square falloff),
    ``size = max(14, diag)`` [m, i.e. Blender units] keeps shadows soft.

    Returns:
        ``(location, energy, size)``.
    """
    location = (float(center[0]), float(center[1]), float(max_z) + diag)
    return location, max(800.0, 5.0 * diag * diag), max(14.0, diag)


def gray_ramp(n: int, seed: int = 0) -> list[Vec3]:
    """Deterministic gray shades for ``n`` mesh objects, lightest last.

    ``shade_i = i / max(1, n - 1)``, ``base_i = 0.2 + 0.6 * shade_i``, and one tint draw per
    object from ``uniform(-0.05, 0.05)`` of a generator seeded with ``seed`` gives the color
    ``(base + tint, base + tint / 2, base - tint)`` clamped to [0, 1]. The slight warm/cool tint
    separates neighbours of equal shade. (Non-cryptographic randomness: cosmetic only.)
    """
    generator = random.Random(seed)  # same sequence as seeding the global generator, isolated
    colors: list[Vec3] = []
    for i in range(n):
        base = 0.2 + 0.6 * (i / max(1, n - 1))
        tint = generator.uniform(-0.05, 0.05)
        colors.append(
            (
                min(1.0, max(0.0, base + tint)),
                min(1.0, max(0.0, base + tint / 2.0)),
                min(1.0, max(0.0, base - tint)),
            )
        )
    return colors


def overhang_fraction(faces: Iterable[tuple[float, Sequence[float]]]) -> float:
    """Area fraction of faces that point more than 45 degrees downward (the FDM overhang rule).

    Args:
        faces: ``(area, world_normal)`` pairs. A face counts as overhang when its normal has
            length > 1e-9 and ``n_z / |n| < -0.7071``. Zero-length normals count toward the
            total area only.

    Returns:
        ``round(overhang_area / total_area, 4)``, or 0.0 when the total area is zero.
    """
    total = 0.0
    overhang = 0.0
    for area, normal in faces:
        total += area
        length = math.sqrt(sum(c * c for c in normal))
        if length > 1e-9 and normal[2] / length < OVERHANG_COS_LIMIT:
            overhang += area
    return round(overhang / total, 4) if total > 0 else 0.0


def mesh_stats_payload(bmin: Sequence[float], bmax: Sequence[float], overhang: float) -> dict:
    """The MESH_STATS dictionary: bounding box in mm (1 Blender unit = 1 mm) and overhang."""
    return {
        "bbox_mm": [round(hi - lo, 3) for lo, hi in zip(bmin, bmax)],
        "overhang_area_frac": overhang,
    }


# ==================================================================================================
# Blender-side steps (called from main(); bpy is passed in, never imported at module level)
# ==================================================================================================
def _job_path(argv: Sequence[str]) -> str:
    """The job-file path: the first argument after Blender's ``--`` separator."""
    if "--" not in argv:
        raise RuntimeError("usage: blender -b --python blender_harness.py -- <job.json>")
    rest = list(argv)[list(argv).index("--") + 1 :]
    if not rest:
        raise RuntimeError("missing job file after '--'")
    return rest[0]


def _run_candidate(script_path: str) -> None:
    """Execute the candidate in a fresh global namespace, as if it were the main program.

    ``__name__ == "__main__"`` makes scripts that guard their body with a main check run, and the
    fresh namespace keeps the script's top-level names away from the harness's own.
    """
    with open(script_path, encoding="utf-8") as handle:
        source = handle.read()
    code = compile(source, script_path, "exec")
    namespace: dict[str, Any] = {"__name__": "__main__", "__file__": script_path}
    # Executing the candidate is this harness's sole purpose. It happens only here, inside the
    # Blender subprocess (own process group, hard timeout), never in the loop's own process.
    exec(code, namespace)  # nosec B102 - runs only inside the sandboxed Blender subprocess


def _apply_gray_materials(bpy: Any, mesh_objects: Sequence[Any]) -> None:
    """Give every mesh object its own node material with a shade from gray_ramp()."""
    for obj, (red, green, blue) in zip(mesh_objects, gray_ramp(len(mesh_objects), seed=0)):
        material = bpy.data.materials.new(name=f"ABCAD_Gray_{obj.name}")
        try:
            material.use_nodes = True  # deprecated (always on) in recent Blender releases
        except AttributeError:
            pass
        nodes = material.node_tree.nodes
        bsdf = next((node for node in nodes if node.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None:
            bsdf = nodes.new("ShaderNodeBsdfPrincipled")
            output = next((node for node in nodes if node.type == "OUTPUT_MATERIAL"), None)
            if output is None:
                output = nodes.new("ShaderNodeOutputMaterial")
            material.node_tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
        # Sockets differ between Blender versions; missing ones are skipped.
        for socket, value in (
            ("Base Color", (red, green, blue, 1.0)),
            ("Specular IOR Level", 0.25),
            ("Roughness", 0.4),
        ):
            if socket in bsdf.inputs:
                bsdf.inputs[socket].default_value = value
        if not obj.material_slots:
            obj.data.materials.append(material)
        obj.active_material = material


def _setup_world(bpy: Any, scene: Any) -> None:
    """Mid-gray world background linked to the world output (created when missing)."""
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        scene.world = world
    try:
        world.use_nodes = True
    except AttributeError:
        pass
    nodes = world.node_tree.nodes
    background = next((node for node in nodes if node.type == "BACKGROUND"), None)
    if background is None:
        background = nodes.new("ShaderNodeBackground")
    output = next((node for node in nodes if node.type == "OUTPUT_WORLD"), None)
    if output is None:
        output = nodes.new("ShaderNodeOutputWorld")
    world.node_tree.links.new(background.outputs["Background"], output.inputs["Surface"])
    background.inputs["Color"].default_value = WORLD_GRAY


def _world_bounds(mathutils: Any, mesh_objects: Sequence[Any]) -> tuple[Vec3, Vec3]:
    """Component-wise min / max of every mesh object's bounding-box corners in world space."""
    if not mesh_objects:
        return (-1.0, -1.0, -1.0), (1.0, 1.0, 1.0)
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for obj in mesh_objects:
        for corner in obj.bound_box:
            point = obj.matrix_world @ mathutils.Vector(corner)
            for axis in range(3):
                lo[axis] = min(lo[axis], point[axis])
                hi[axis] = max(hi[axis], point[axis])
    return (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])


def _faces_with_world_normals(mesh_objects: Sequence[Any]) -> Iterable[tuple[float, Vec3]]:
    """Yield (object-local polygon area, world-space normal) for every polygon of every mesh."""
    for obj in mesh_objects:
        rotation = obj.matrix_world.to_3x3()  # 3x3 part of the world matrix
        for polygon in obj.data.polygons:
            normal = rotation @ polygon.normal
            yield polygon.area, (normal[0], normal[1], normal[2])


def _setup_key_light(bpy: Any, scene: Any, center: Vec3, max_z: float, diag: float) -> None:
    """Replace every light with one area key light (see key_light())."""
    for obj in [o for o in bpy.data.objects if o.type == "LIGHT"]:
        bpy.data.objects.remove(obj, do_unlink=True)
    location, energy, size = key_light(center, max_z, diag)
    light_data = bpy.data.lights.new(name="ABCAD_KeyLight", type="AREA")
    light_data.energy = energy
    light_data.size = size
    light = bpy.data.objects.new(name="ABCAD_KeyLight", object_data=light_data)
    scene.collection.objects.link(light)
    light.location = location  # area lights emit along local -Z, i.e. straight down


def _setup_camera(bpy: Any, scene: Any, center: Vec3, diag: float) -> None:
    """Move (or add) the camera to the three-quarter view and aim it at the center."""
    location, clip_end = camera_placement(center, diag)
    camera = bpy.data.objects.get("Camera")
    if camera is None or camera.type != "CAMERA":
        camera = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    if scene.objects.get(camera.name) is None:
        scene.collection.objects.link(camera)
    camera.location = location
    camera.data.type = "PERSP"
    camera.data.clip_end = clip_end
    if not any(constraint.type == "TRACK_TO" for constraint in camera.constraints):
        target = bpy.data.objects.new("ABCAD_CameraTarget", None)  # an empty at the center
        target.location = center
        scene.collection.objects.link(target)
        constraint = camera.constraints.new(type="TRACK_TO")
        constraint.target = target
        constraint.track_axis = "TRACK_NEGATIVE_Z"
        constraint.up_axis = "UP_Y"
    scene.camera = camera


def _select_engine(bpy: Any, scene: Any) -> str:
    """Real-time engine id: BLENDER_EEVEE_NEXT where offered (4.2-era), else BLENDER_EEVEE (5.x)."""
    try:
        items = bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items
        offered = {item.identifier for item in items}
    except (AttributeError, KeyError):
        offered = set()
    engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in offered else "BLENDER_EEVEE"
    try:
        scene.render.engine = engine
    except TypeError:  # the enumeration did not list it after all
        engine = "BLENDER_EEVEE" if engine == "BLENDER_EEVEE_NEXT" else "BLENDER_EEVEE_NEXT"
        scene.render.engine = engine
    return engine


def _render(bpy: Any, scene: Any, job: dict[str, Any]) -> str:
    """Render a still PNG as the job file specifies; return its path."""
    _select_engine(bpy, scene)
    try:
        scene.eevee.taa_render_samples = int(job.get("samples", 64))  # anti-aliasing samples
    except AttributeError:
        pass
    width, height = job.get("resolution", [1280, 720])
    scene.render.resolution_x = int(width)
    scene.render.resolution_y = int(height)
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    output_dir = job["output_dir"]
    render_path = os.path.join(output_dir, job["render_filename"])
    os.makedirs(output_dir, exist_ok=True)
    scene.render.filepath = render_path
    bpy.ops.render.render(write_still=True)
    print(f"Render saved at {render_path}", flush=True)
    return render_path


def _export_stl(bpy: Any, stl_path: str) -> None:
    """Export all objects to binary STL (native exporter, then legacy); never fatal."""
    try:
        bpy.ops.wm.stl_export(filepath=stl_path)  # Blender 4.2+: all objects, modifiers applied
    except Exception as native_error:
        try:
            bpy.ops.export_mesh.stl(filepath=stl_path)  # legacy exporter (older releases)
        except Exception as legacy_error:
            print(f"{MARK_STL_FAILED}{native_error} / {legacy_error}", flush=True)
    if os.path.exists(stl_path):
        print(f"{MARK_STL_PATH}{os.path.abspath(stl_path)}", flush=True)


# ==================================================================================================
# Entry point
# ==================================================================================================
def main(argv: list[str]) -> None:
    """Run one job: execute the candidate, measure, render, export, and report on stdout.

    Args:
        argv: Blender's full argument vector; the job file follows ``--``.
    """
    import bpy  # Blender-only modules: imported here so the helpers import anywhere
    import mathutils

    print(f"{MARK_BLENDER}{bpy.app.version_string}", flush=True)
    try:
        # ---- job + candidate (steps 1-3) ----------------------------------------------------
        with open(_job_path(argv), encoding="utf-8") as handle:
            job = json.load(handle)
        _run_candidate(job["script_path"])

        # ---- step 4: something must exist -----------------------------------------------------
        scene = bpy.context.scene
        object_count = len(bpy.data.objects)
        print(f"{MARK_OBJECTS}{object_count}", flush=True)
        if object_count == 0:
            raise RuntimeError("no objects created")

        # ---- steps 5-6: materials and world ---------------------------------------------------
        mesh_objects = [obj for obj in bpy.data.objects if obj.type == "MESH"]
        _apply_gray_materials(bpy, mesh_objects)
        _setup_world(bpy, scene)

        # ---- steps 7-8: world-space bounds and MESH_STATS -------------------------------------
        bmin, bmax = _world_bounds(mathutils, mesh_objects)
        # World-space bounding-box center, as an explicit (x, y, z) triple [scene units].
        center = (
            (bmin[0] + bmax[0]) / 2.0,
            (bmin[1] + bmax[1]) / 2.0,
            (bmin[2] + bmax[2]) / 2.0,
        )
        diag = bbox_diagonal(bmin, bmax)
        overhang = overhang_fraction(_faces_with_world_normals(mesh_objects))
        print(MARK_MESH_STATS + json.dumps(mesh_stats_payload(bmin, bmax, overhang)), flush=True)

        # ---- steps 9-11: light, camera, render ------------------------------------------------
        _setup_key_light(bpy, scene, center, bmax[2], diag)
        _setup_camera(bpy, scene, center, diag)
        _render(bpy, scene, job)
    except Exception as error:
        # Step 14: the exception text goes to STDOUT (it becomes the repair model's error
        # message); the traceback goes to stderr so it does not pollute that excerpt.
        print(f"{MARK_EXEC_FAIL}{error}", flush=True)
        traceback.print_exc(file=sys.stderr)
        sys.stdout.flush()
        sys.stderr.flush()
        sys.exit(1)

    # ---- step 12: STL export (own non-fatal trap) ---------------------------------------------
    _export_stl(bpy, os.path.join(job["output_dir"], job["stl_filename"]))

    # ---- step 13: success marker --------------------------------------------------------------
    print(MARK_EXEC_OK, flush=True)


if __name__ == "__main__":
    main(sys.argv)
