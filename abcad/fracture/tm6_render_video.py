"""
tm6_render_video.py — render the phase-field crack propagation to a video.

Reads a MOOSE Exodus file, renders the damage field c (0=intact -> 1=cracked) on the
displacement-warped mesh at every timestep, writes PNG frames, then stitches an mp4 with
ffmpeg. Shows the crack nucleating at the notch and sweeping across the specimen.

INPUTS   <exodus.e> <out_prefix> [warp_factor]   (2D run such as tm6_video.i; warp default 15)
OUTPUTS  <out_prefix>_frames/f####.png, <out_prefix>.mp4, <out_prefix>.gif
Usage: python -m abcad.fracture.tm6_render_video <exodus.e> <out_prefix> [warp_factor]
Needs pyvista (conda cad_env) and ffmpeg on PATH.
"""

from __future__ import annotations

import os
import subprocess
import sys

import numpy as np
import pyvista as pv


def main(argv=None):
    """CLI entry point: fixed color scale + camera across frames, then mp4 (24 fps) + gif."""
    argv = sys.argv[1:] if argv is None else list(argv)
    exo = argv[0]
    out_prefix = argv[1]
    warp = float(argv[2]) if len(argv) > 2 else 15.0

    pv.OFF_SCREEN = True
    frames_dir = out_prefix + "_frames"
    os.makedirs(frames_dir, exist_ok=True)

    reader = pv.get_reader(exo)
    times = reader.time_values
    print(f"{len(times)} timesteps in {exo}")

    # Fixed color scale + camera across all frames so the animation is stable.
    cmap = "inferno"
    n = len(times)
    cmax = None
    for i in range(n):
        reader.set_active_time_point(i)
        grid = reader.read().combine()
        if "c" in grid.point_data:
            m = float(np.nanmax(grid.point_data["c"]))
            cmax = m if cmax is None else max(cmax, m)
    cmax = max(cmax or 1.0, 0.5)  # never let a barely-damaged run saturate the colormap
    print(f"max damage c over run = {cmax:.3f}")

    cam = None
    for i in range(n):
        reader.set_active_time_point(i)
        grid = reader.read().combine()
        # warp by displacement (exaggerated) to show the crack opening
        if {"disp_x", "disp_y"}.issubset(grid.point_data.keys()):
            d = np.zeros((grid.n_points, 3))
            d[:, 0] = grid.point_data["disp_x"]
            d[:, 1] = grid.point_data["disp_y"]
            grid.point_data["warpvec"] = d * warp
            grid = grid.warp_by_vector("warpvec")
        p = pv.Plotter(off_screen=True, window_size=[1000, 620])
        p.add_mesh(
            grid,
            scalars="c",
            cmap=cmap,
            clim=[0, cmax],
            show_edges=False,
            scalar_bar_args={"title": "damage c", "vertical": True},
        )
        p.add_text(
            f"crack propagation  |  step {i+1}/{n}  |  disp {times[i]*1e3:.2f} um  (warp x{warp:.0f})",
            position="upper_left",
            font_size=10,
            color="white",
        )
        p.background_color = "black"
        p.enable_parallel_projection()
        p.view_xy()
        if cam is None:
            # first frame fixes the camera; later frames reuse it so the view does not jump
            p.reset_camera()
            p.camera.zoom(2.4)
            cam = p.camera_position
        else:
            p.camera_position = cam
        p.screenshot(os.path.join(frames_dir, f"f{i:04d}.png"))
        p.close()

    # encode: mp4 at 24 fps (even-height scaling for yuv420p), then a lighter gif from the mp4
    mp4 = out_prefix + ".mp4"
    cmd = [
        "ffmpeg",
        "-y",
        "-framerate",
        "24",
        "-i",
        os.path.join(frames_dir, "f%04d.png"),
        "-pix_fmt",
        "yuv420p",
        "-vf",
        "scale=1000:-2",
        mp4,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    gif = out_prefix + ".gif"
    subprocess.run(
        ["ffmpeg", "-y", "-i", mp4, "-vf", "fps=12,scale=560:-1", gif],
        check=True,
        capture_output=True,
    )
    print(
        f"wrote {mp4} ({os.path.getsize(mp4)//1024} KB) and {gif} ({os.path.getsize(gif)//1024} KB)"
    )


if __name__ == "__main__":
    main()
