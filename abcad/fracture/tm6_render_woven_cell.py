"""
tm6_render_woven_cell.py — visualize a non-fused woven CELL MOOSE run (contact/sliding).

Reads the Exodus output of `tm6_make_woven_cell_deck.py` and renders the loaded cell so the
damage-tolerance behaviour is legible: warp fibers (bottom layer, pulled along +x) and weft fibers
(top layer, pressed down), warped by the displacement field (exaggerated) and colored by axial
stress `stress_xx`. In the DAMAGED cell one warp fiber's pulled grip is freed ("cut"); if the
frictional crossings shed load to it, it carries stress — if not, it stays dark (drops out).

Three modes:
  single  : one Exodus -> one PNG (final step).            tm6_render_woven_cell.py single <exo.e> <out.png> [title]
  compare : intact + damaged side-by-side (final step).    tm6_render_woven_cell.py compare <intact.e> <damaged.e> <out.png>
  video   : one Exodus -> mp4 across load steps (orbit).   tm6_render_woven_cell.py video  <exo.e> <out_prefix> [title]

INPUTS   the mode and its arguments above (Exodus files from the woven-cell deck).
OUTPUTS  the PNG / mp4 named on the command line (video mode also keeps <out_prefix>_frames/).
Units: mm / MPa (PLA). Displacement warp factor is cosmetic (default 20x) so 0.02 mm reads at cell scale.
Usage: python -m abcad.fracture.tm6_render_woven_cell <single|compare|video> ...
Needs pyvista (conda cad_env) and, for video, ffmpeg on PATH.
"""

from __future__ import annotations

import os
import subprocess
import sys

import numpy as np
import pyvista as pv

pv.OFF_SCREEN = True
WARP = 20.0  # displacement exaggeration factor (0.02 mm pull -> visible at ~mm cell scale)


def _open(exo):
    """Open an Exodus reader with ApplyDisplacements OFF.

    vtkExodusIIReader defaults ApplyDisplacements=ON and mis-groups MOOSE's disp_x/y/z into a bogus
    `disp_` vector (~1e2 mm), which it then bakes into the point coordinates at read time — blowing the
    bounds up to ~300 mm and flinging the camera away. Disabling it returns the true undeformed mesh.
    """
    r = pv.get_reader(exo)
    try:
        r.reader.SetApplyDisplacements(False)
    except Exception:
        pass  # reader without that switch: nothing to disable
    return r


def _disp(g):
    """Displacement vector (N,3). MOOSE groups disp_x/y/z into a single vector field named 'disp_'."""
    d = np.asarray(g.point_data["disp_"])
    if d.ndim == 1:  # single component -> pad to 3D
        d = np.column_stack([d, np.zeros_like(d), np.zeros_like(d)])
    if d.shape[1] < 3:
        d = np.column_stack([d, np.zeros((d.shape[0], 3 - d.shape[1]))])
    return d


def _field(mesh):
    """Return (scalar array, name) to color by: axial stress_xx (cell) if present, else axial disp."""
    if "stress_xx" in mesh.cell_data:
        return np.asarray(mesh.cell_data["stress_xx"]), "stress_xx (MPa)"
    return _disp(mesh)[:, 0], "disp_x (mm)"


def _load_step(reader, i):
    """Read timestep i, return a single combined UnstructuredGrid.

    The applied displacement is only ~0.02 mm (invisible even exaggerated), and VTK's exodus reader
    mis-groups MOOSE's disp_x/y/z into a garbage `disp_` vector (values ~1e2 mm), so we render the
    UNDEFORMED cell and let the clean `stress_xx` field carry the load story. If a sane displacement is
    ever present we exaggerate it; otherwise we skip warping.
    """
    reader.set_active_time_point(i)
    g = reader.read().combine()
    try:
        d = _disp(g)
        # sane (mm) displacement -> exaggerate it; otherwise leave the cell undeformed
        if np.isfinite(d).all() and np.abs(d).max() < 5.0:
            g.points = g.points + WARP * d
    except Exception:
        pass  # no usable displacement field: render the undeformed cell
    return g


def _add_cell(plotter, g, clim=None):
    """Add the warped cell colored by the chosen field; return the clim used (for shared color scale)."""
    scal, name = _field(g)
    g2 = g.copy()
    # attach the scalars on cells or points, whichever length they match
    if scal.shape[0] == g2.n_cells:
        g2.cell_data["c"] = scal
    else:
        g2.point_data["c"] = scal
    if clim is None:
        lo, hi = float(np.nanmin(scal)), float(np.nanmax(scal))
        if hi - lo < 1e-9:
            hi = lo + 1e-9  # avoid a zero-width color range on a uniform field
        clim = (lo, hi)
    plotter.add_mesh(
        g2,
        scalars="c",
        cmap="turbo",
        clim=clim,
        show_edges=True,
        edge_color="gray",
        line_width=0.3,
        scalar_bar_args={"title": name, "n_labels": 3, "fmt": "%.1f"},
    )
    return clim


def _camera(bounds):
    """Angled camera (from -y, slightly -x, above) looking at the cell centre, z up."""
    ctr = ((bounds[0] + bounds[1]) / 2, (bounds[2] + bounds[3]) / 2, (bounds[4] + bounds[5]) / 2)
    span = max(bounds[1] - bounds[0], bounds[3] - bounds[2]) + 6
    return [(ctr[0] - 0.15 * span, ctr[1] - span, ctr[2] + 0.7 * span), ctr, (0, 0, 1)]


def _frame(plotter, bounds):
    """Set an angled view direction, then reset_camera so the (small, mm-scale) cell fills the frame."""
    plotter.camera_position = _camera(bounds)
    plotter.reset_camera()
    plotter.camera.zoom(1.3)


def render_single(exo, out_png, title=""):
    """Final-step render of one run to ``out_png`` (optional title)."""
    r = _open(exo)
    g = _load_step(r, len(r.time_values) - 1)
    p = pv.Plotter(off_screen=True, window_size=[900, 760])
    p.background_color = "white"
    _add_cell(p, g)
    _frame(p, g.bounds)
    if title:
        p.add_text(title, position="upper_left", font_size=13, color="black")
    p.screenshot(out_png)
    p.close()
    print("wrote", out_png)


def render_compare(intact_e, damaged_e, out_png):
    """Side-by-side final-step renders of the intact and damaged runs on one shared color scale."""
    ri, rd = _open(intact_e), _open(damaged_e)
    gi = _load_step(ri, len(ri.time_values) - 1)
    gd = _load_step(rd, len(rd.time_values) - 1)
    # shared color scale across both panels so the "dropped-out" fiber reads as genuinely low stress
    si, _ = _field(gi)
    sd, _ = _field(gd)
    clim = (float(min(si.min(), sd.min())), float(max(si.max(), sd.max())))
    p = pv.Plotter(off_screen=True, shape=(1, 2), window_size=[1500, 720])
    p.background_color = "white"
    p.subplot(0, 0)
    _add_cell(p, gi, clim)
    _frame(p, gi.bounds)
    p.add_text("INTACT", position="upper_left", font_size=13, color="black")
    p.subplot(0, 1)
    _add_cell(p, gd, clim)
    _frame(p, gd.bounds)
    p.add_text("DAMAGED (warp0 grip cut)", position="upper_left", font_size=13, color="black")
    p.screenshot(out_png)
    p.close()
    print("wrote", out_png)


def render_video(exo, out_prefix, title=""):
    """Orbiting per-step frames on a fixed color scale, encoded to <out_prefix>.mp4 (6 fps)."""
    r = _open(exo)
    n = len(r.time_values)
    fd = out_prefix + "_frames"
    os.makedirs(fd, exist_ok=True)
    # fixed color scale from the final (most-loaded) step so color = load, not a per-frame rescale
    gL = _load_step(r, n - 1)
    sL, _ = _field(gL)
    clim = (float(sL.min()), float(sL.max()))
    for i in range(n):
        g = _load_step(r, i)
        p = pv.Plotter(off_screen=True, window_size=[900, 760])
        p.background_color = "white"
        _add_cell(p, g, clim)
        cam = _camera(g.bounds)
        az = np.radians(i * 3.0)  # slow orbit so the 3D layering reads
        ctr = cam[1]
        rad = np.hypot(cam[0][0] - ctr[0], cam[0][1] - ctr[1])
        p.camera_position = [
            (ctr[0] + rad * np.sin(az), ctr[1] - rad * np.cos(az), cam[0][2]),
            ctr,
            (0, 0, 1),
        ]
        if title:
            p.add_text(
                f"{title}  ·  step {i+1}/{n}", position="upper_left", font_size=12, color="black"
            )
        p.screenshot(os.path.join(fd, f"f{i:04d}.png"))
        p.close()
    mp4 = out_prefix + ".mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            "6",
            "-i",
            os.path.join(fd, "f%04d.png"),
            "-pix_fmt",
            "yuv420p",
            "-vf",
            "scale=760:-2",
            mp4,
        ],
        check=True,
        capture_output=True,
    )
    print("wrote", mp4)


def main(argv=None):
    """CLI entry point: dispatch to the single / compare / video renderer."""
    argv = sys.argv[1:] if argv is None else list(argv)
    mode = argv[0]
    if mode == "single":
        render_single(argv[1], argv[2], argv[3] if len(argv) > 3 else "")
    elif mode == "compare":
        render_compare(argv[1], argv[2], argv[3])
    elif mode == "video":
        render_video(argv[1], argv[2], argv[3] if len(argv) > 3 else "")
    else:
        sys.exit("mode must be single|compare|video")


if __name__ == "__main__":
    main()
