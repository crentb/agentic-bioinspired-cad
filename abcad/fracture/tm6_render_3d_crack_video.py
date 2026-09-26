"""
tm6_render_3d_crack_video.py — video of a 3D phase-field crack forming.

Reads a MOOSE Exodus file; for each timestep renders the crack SURFACE (isosurface of the
damage field c = 0.5) inside the specimen outline, with the camera slowly orbiting so the 3D
shape reads. The crack grows across the frames. ffmpeg stitches an mp4 + gif.

INPUTS   <exodus.e> <out_prefix>   (Exodus from a 3D deck such as tm6_3d_twist_example.i)
OUTPUTS  <out_prefix>_frames/f####.png, <out_prefix>.mp4, <out_prefix>.gif
Usage: python -m abcad.fracture.tm6_render_3d_crack_video <exodus.e> <out_prefix>
Needs pyvista (conda cad_env) and ffmpeg on PATH.
"""

from __future__ import annotations

import os
import subprocess
import sys

import numpy as np
import pyvista as pv


def main(argv=None):
    """CLI entry point: render one orbiting frame per timestep, then encode mp4 + gif."""
    argv = sys.argv[1:] if argv is None else list(argv)
    exo, out_prefix = argv[0], argv[1]
    pv.OFF_SCREEN = True
    r = pv.get_reader(exo)
    n = len(r.time_values)
    fd = out_prefix + "_frames"
    os.makedirs(fd, exist_ok=True)
    print(f"{n} timesteps")

    # specimen bounds (from step 0)
    r.set_active_time_point(0)
    b0 = np.asarray(r.read().combine().points)
    bounds = (
        b0[:, 0].min(),
        b0[:, 0].max(),
        b0[:, 1].min(),
        b0[:, 1].max(),
        b0[:, 2].min(),
        b0[:, 2].max(),
    )
    ctr = ((bounds[0] + bounds[1]) / 2, (bounds[2] + bounds[3]) / 2, (bounds[4] + bounds[5]) / 2)

    for i in range(n):
        r.set_active_time_point(i)
        g = r.read().combine()
        c = np.asarray(g.point_data["c"])
        p = pv.Plotter(off_screen=True, window_size=[900, 760])
        p.add_mesh(pv.Box(bounds=bounds), style="wireframe", color="gray", opacity=0.5)
        # crack surface = isosurface c=0.5; fall back to cracked-node points if the contour is empty
        try:
            surf = g.contour([0.5], scalars="c")
        except Exception:
            surf = None
        if surf is not None and surf.n_points > 20:
            surf["z"] = surf.points[:, 2]  # color the crack surface by depth so its twist reads
            p.add_mesh(surf, scalars="z", cmap="turbo", smooth_shading=True, show_scalar_bar=False)
        else:
            crk = np.asarray(g.points)[c > 0.5]
            if len(crk):
                cloud = pv.PolyData(crk)
                cloud["z"] = crk[:, 2]
                p.add_mesh(
                    cloud,
                    scalars="z",
                    cmap="turbo",
                    point_size=6,
                    render_points_as_spheres=True,
                    show_scalar_bar=False,
                )
        p.background_color = "white"
        p.add_text(
            f"3D crack forming  ·  step {i+1}/{n}",
            position="upper_left",
            font_size=12,
            color="black",
        )
        # slow orbit: azimuth advances a little each frame so the 3D shape reads
        az = np.radians(35 + i * 1.2)
        p.camera_position = [
            (ctr[0] + 2.4 * np.cos(az), ctr[1] - 2.4 * np.sin(az), ctr[2] + 1.6),
            ctr,
            (0, 0, 1),
        ]
        p.screenshot(os.path.join(fd, f"f{i:04d}.png"))
        p.close()

    # encode: mp4 at 10 fps (even-height scaling for yuv420p), then a lighter gif from the mp4
    mp4 = out_prefix + ".mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            "10",
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
    subprocess.run(
        ["ffmpeg", "-y", "-i", mp4, "-vf", "fps=8,scale=560:-1", out_prefix + ".gif"],
        check=True,
        capture_output=True,
    )
    print(f"wrote {mp4} ({os.path.getsize(mp4)//1024} KB)")


if __name__ == "__main__":
    main()
