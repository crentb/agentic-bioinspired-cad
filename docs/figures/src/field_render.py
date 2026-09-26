"""
field_render.py -- the house style for the documentation's 3D renders and field plots.

Purpose
    One visual language for every render in docs/figures, taken from the woven builder's own
    preview render (abcad/generators/woven/build.py, render_png): bone material #c2b39a,
    smooth shading, specular 0.3, a white ground. Scalar fields (stress, phase-field damage)
    share one sequential ramp that starts at a light bone tone and darkens through terracotta
    to oxblood, so "more load" or "more damage" always reads as the material darkening; the
    ramp decreases monotonically in lightness, so it stays ordered in grayscale print.

    make_figures.py imports this module; it holds no figure layouts of its own.

Contents
    BONE, BONE_RED, ...          material color and the field ramp
    read_exodus(path, step)      one time step of a MOOSE Exodus file (undeformed coordinates)
    render_mesh(...)             off-screen PyVista render in the house lighting, content-cropped
    crop_to_content(img)         trim a white-ground image to its content plus a margin
    triangulation(grid, field)   2D nodal field -> matplotlib triangulation (Gouraud shading)
    crack_path(grid)             crack centerline y(x) from the phase-field damage
    path_drift(...), path_tortuosity(...)   crack-path metrics (tip drift, path length / span)
    edge_drift(grid)             far-edge drift measure of FRACTURE.md's reproducibility note
    thin_material_map(stl, d, v) the print gate's thin-material flag painted on the surface
    save_gif(frames, path, fps)  adaptive-palette GIF without dithering (flat colors, small file)

Dependencies
    numpy, matplotlib, Pillow; pyvista (with VTK's Exodus reader) for Exodus input and 3D renders,
    imported lazily so the chart-only figures do not need it.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.tri as mtri
import numpy as np
from matplotlib.colors import LinearSegmentedColormap, ListedColormap
from PIL import Image

# =============================================================================
# 1. Colors
# =============================================================================
BONE = "#c2b39a"  # the builder's material color: every geometry render uses it
EDGE = "#5f5a52"  # warm gray for body outlines on field renders
OUTLINE = "#8f8a80"  # hairline specimen outline on 2D field plots
# Field ramp: light bone (0) -> sand -> tan -> terracotta -> brick -> oxblood (max). Lightness
# falls monotonically along the ramp, so the scale reads in grayscale and for color-blind viewers.
BONE_RED = LinearSegmentedColormap.from_list(
    "bone_red", ["#ece5da", "#dccbb0", "#cfa27a", "#c0674a", "#a53f2a", "#7a2419"]
)
THIN = "#9c3a26"  # brick red: material the print gate flags as too thin to form
# Two-tone map for binary flags on geometry: 0 = bone (fine), 1 = brick (flagged).
BONE_THIN = ListedColormap([BONE, THIN])


# =============================================================================
# 2. Exodus input
# =============================================================================
def read_exodus(path: Path | str, step: int = -1):
    """
    Return one time step of a MOOSE Exodus file as a single pyvista UnstructuredGrid.

    VTK's Exodus reader defaults to ApplyDisplacements=ON and groups MOOSE's disp_x/y/z into a
    malformed `disp_` vector that it adds to the coordinates at read time (offsets of ~1e2 model
    units). It is switched off so every render shows the undeformed specimen, which is what the
    figures compare. `step` indexes the stored time steps (-1 = last).
    """
    import pyvista as pv

    reader = pv.get_reader(str(path))
    try:
        reader.reader.SetApplyDisplacements(False)
    except AttributeError:  # a reader without the switch has nothing to disable
        pass
    n = reader.number_time_points
    reader.set_active_time_point(step % n if n else 0)
    return reader.read().combine()


def exodus_steps(path: Path | str) -> int:
    """Number of stored time steps in an Exodus file."""
    import pyvista as pv

    return int(pv.get_reader(str(path)).number_time_points)


# =============================================================================
# 3. Raster helpers
# =============================================================================
def crop_to_content(img: Image.Image, margin: int = 24, threshold: int = 250) -> Image.Image:
    """Trim a white-ground render to its non-white content plus `margin` pixels on every side."""
    gray = np.asarray(img.convert("L"))
    ys, xs = np.where(gray < threshold)
    if xs.size == 0:
        return img
    box = (
        max(int(xs.min()) - margin, 0),
        max(int(ys.min()) - margin, 0),
        min(int(xs.max()) + 1 + margin, img.width),
        min(int(ys.max()) + 1 + margin, img.height),
    )
    return img.crop(box)


def render_mesh(
    mesh,
    *,
    scalars: np.ndarray | None = None,
    clim: tuple[float, float] | None = None,
    cmap=None,
    color: str = BONE,
    outline: bool = False,
    camera=None,
    zoom: float = 1.3,
    size: tuple[int, int] = (1600, 1200),
    smooth: bool = True,
    opacity: float = 1.0,
    crop: bool = True,
    extra=None,
) -> Image.Image:
    """
    Render one mesh off-screen in the house lighting and return the content-cropped image.

    Parameters
        mesh      any pyvista dataset (STL surface, hexahedral grid, ...)
        scalars   optional per-cell or per-point field; drawn over `clim` with `cmap`
        cmap      colormap for `scalars` (default BONE_RED; BONE_THIN for binary flags)
        color     solid material color when no field is given (default: bone)
        outline   draw sharp feature edges in warm gray, so separate bodies stay distinct when
                  they share a color (e.g. unloaded fibers crossing each other)
        camera    a pyvista camera position (list of 3 tuples or a named view); default "iso"
        zoom      camera zoom after reset_camera (framing only)
        size      render window [px]; renders are supersampled (SSAA) and then cropped
        smooth    Gouraud shading (curved surfaces) vs flat faces (hexahedral elements)
        opacity   material opacity (a translucent solid shows what grows inside it)
        crop      trim to content; animation frames pass False so all frames match in size
        extra     optional callback(plotter) for additional actors (e.g. a crack surface)
    """
    import pyvista as pv

    pl = pv.Plotter(off_screen=True, window_size=list(size))
    pl.set_background("white")
    kwargs = dict(
        smooth_shading=smooth, specular=0.3, specular_power=20, ambient=0.14, opacity=opacity
    )
    if scalars is None:
        pl.add_mesh(mesh, color=color, **kwargs)
    else:
        pl.add_mesh(
            mesh,
            scalars=scalars,
            cmap=cmap if cmap is not None else BONE_RED,
            clim=clim,
            show_scalar_bar=False,
            **kwargs,
        )
    if outline:
        edges = mesh.extract_surface().extract_feature_edges(
            feature_angle=30, boundary_edges=False, non_manifold_edges=False, manifold_edges=False
        )
        pl.add_mesh(edges, color=EDGE, line_width=2.2)
    if extra is not None:
        extra(pl)
    pl.camera_position = camera if camera is not None else "iso"
    pl.reset_camera()
    pl.camera.zoom(zoom)
    pl.enable_anti_aliasing("ssaa")
    img = Image.fromarray(pl.screenshot(return_img=True))
    pl.close()
    return crop_to_content(img) if crop else img


# =============================================================================
# 4. 2D phase-field crack fields
# =============================================================================
def triangulation(grid, field: str = "c") -> tuple[mtri.Triangulation, np.ndarray]:
    """
    Split a 2D quadrilateral mesh into triangles (two per quad) and return a matplotlib
    triangulation with the nodal `field`, so it can be Gouraud-shaded exactly at the nodes.
    """
    tri = grid.triangulate()
    faces = tri.cells.reshape(-1, 4)[:, 1:]
    t = mtri.Triangulation(tri.points[:, 0], tri.points[:, 1], faces)
    return t, np.asarray(tri.point_data[field], dtype=float)


def crack_path(grid, field: str = "c", threshold: float = 0.9) -> np.ndarray:
    """
    Crack centerline of a 2D phase-field result as an (n, 2) array of (x, y) points.

    Method: the mesh is structured, so nodes fall on vertical columns of equal x. In each
    column the node of maximum damage is taken as the crack position, and the column counts as
    cracked only when that maximum reaches `threshold` (0.9: fully developed crack, not the
    diffuse process zone ahead of it). Columns are returned in increasing x.
    """
    pts = np.asarray(grid.points)[:, :2]
    c = np.asarray(grid.point_data[field], dtype=float)
    xs = np.unique(np.round(pts[:, 0], 9))
    path = []
    for x in xs:
        col = np.isclose(pts[:, 0], x, atol=1e-9)
        k = int(np.argmax(np.where(col, c, -np.inf)))
        if c[k] >= threshold:
            path.append((pts[k, 0], pts[k, 1]))
    return np.asarray(path, dtype=float).reshape(-1, 2)


def path_drift(path: np.ndarray, y_start: float, height: float) -> float:
    """Vertical offset of the crack's far end from its starting height, as a fraction of height."""
    return float((path[-1, 1] - y_start) / height) if len(path) else float("nan")


def edge_drift(grid, field: str = "c", threshold: float = 0.5) -> float:
    """
    Crack drift measured on the far (right) edge: the damage-weighted mean height of the fully
    damaged material there (c >= threshold), minus mid-height, as a fraction of the height.
    Symmetric branching toward both far corners gives 0; a crack steered to one corner gives
    about +/-0.5.
    """
    pts = np.asarray(grid.points)[:, :2]
    c = np.asarray(grid.point_data[field], dtype=float)
    edge = np.isclose(pts[:, 0], pts[:, 0].max())
    w = np.where(c[edge] >= threshold, c[edge], 0.0)
    y0, y1 = pts[:, 1].min(), pts[:, 1].max()
    return float((w * pts[edge, 1]).sum() / w.sum() - 0.5 * (y0 + y1)) / float(y1 - y0)


def path_tortuosity(path: np.ndarray) -> float:
    """Crack path length divided by its horizontal span (1 = straight)."""
    if len(path) < 2:
        return float("nan")
    length = float(np.sum(np.hypot(np.diff(path[:, 0]), np.diff(path[:, 1]))))
    return length / float(path[-1, 0] - path[0, 0])


# =============================================================================
# 5. Print-gate thin-material map
# =============================================================================
def thin_material_map(stl_path: Path | str, d_mm: float, voxel_mm: float):
    """
    Flag where a part is thinner than `d_mm`, by the print audit's own measure, and return
    (surface mesh, per-vertex flag 0/1, lost volume fraction).

    Method (abcad.printing.print_audit.voxel_checks): voxelize the closed surface; material that
    does not survive a morphological opening with a ball of diameter d (erode by d/2 via the
    Euclidean distance transform, then dilate the surviving core by d/2) is thinner than d. A
    surface vertex is flagged when a thin voxel lies within one voxel of it. The returned lost
    fraction equals the audit's lost_frac_at_d[d] at the same voxel size, which cross-checks
    the map against the gate's recorded verdict.
    """
    import pyvista as pv
    from scipy import ndimage

    from abcad.fea.voxel_plate_mesh import voxelize_stl

    occ, origin, v = voxelize_stl(str(stl_path), voxel_mm)
    edt = ndimage.distance_transform_edt(occ, sampling=v)  # local inscribed radius [mm]
    core = edt >= d_mm / 2.0
    del edt
    regrown = ndimage.distance_transform_edt(~core, sampling=v) <= d_mm / 2.0
    thin = occ & ~regrown
    lost = float(thin.sum()) / float(occ.sum())
    near = ndimage.binary_dilation(thin, iterations=1)
    mesh = pv.read(str(stl_path))
    ijk = np.rint((np.asarray(mesh.points) - np.asarray(origin)) / v).astype(int)
    ijk = np.clip(ijk, 0, np.asarray(occ.shape) - 1)
    flag = near[ijk[:, 0], ijk[:, 1], ijk[:, 2]].astype(float)
    return mesh, flag, lost


# =============================================================================
# 6. Animation output
# =============================================================================
def save_gif(frames: list[Image.Image], path: Path, fps: float = 12.0, colors: int = 160) -> None:
    """
    Write frames as a looping GIF with one adaptive palette built from a sample of the frames
    and no dithering: flat fields and text stay clean (no speckle), and the file stays small.
    """
    rgb = [f.convert("RGB") for f in frames]
    sample_idx = np.linspace(0, len(rgb) - 1, min(len(rgb), 8)).astype(int)
    strip = Image.new("RGB", (rgb[0].width, rgb[0].height * len(sample_idx)), "white")
    for i, k in enumerate(sample_idx):
        strip.paste(rgb[k], (0, i * rgb[0].height))
    palette = strip.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    quantized = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in rgb]
    quantized[0].save(
        path,
        save_all=True,
        append_images=quantized[1:],
        duration=int(round(1000 / fps)),
        loop=0,
        optimize=True,
        disposal=1,
    )
