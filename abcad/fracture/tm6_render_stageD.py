"""
tm6_render_stageD.py — video of the full-model (Stage D) phase-field crack in an oriented rod field.

Renders the damage field c of a 2D Stage-D run (tm6_stageD.i: internal seeded crack, no symmetry
plane, so the crack is FREE to deflect) on the displacement-warped mesh at every timestep, with the
initial notch and the pulled edge annotated, then stitches an mp4 + gif with ffmpeg. The title
states the rod angle so a sweep of runs (e.g. 0/30/60/90 deg) reads side by side.

INPUTS   <exodus.e> <out_prefix> <angle_deg>   (Exodus of a 2D quad-mesh run; angle for the title)
OUTPUTS  <out_prefix>_frames/f####.png, <out_prefix>.mp4, <out_prefix>.gif
Usage: python -m abcad.fracture.tm6_render_stageD <exodus.e> <out_prefix> <angle_deg>
Needs pyvista + matplotlib (conda cad_env) and ffmpeg on PATH.
"""

from __future__ import annotations

import os
import subprocess
import sys

import matplotlib
import numpy as np
import pyvista as pv

matplotlib.use("Agg")  # headless backend: file output only (must precede the pyplot import)
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.tri import Triangulation

# damage colormap: intact material -> light steel; crack -> crimson (reads as "breaking")
DMG = LinearSegmentedColormap.from_list(
    "d", ["#cdd7e0", "#cdd7e0", "#e8a37a", "#c0392b", "#7d1a12"]
)
WARP = 5  # displacement exaggeration factor for the warped mesh (cosmetic)


def main(argv=None):
    """CLI entry point: one annotated frame per timestep, then mp4 (20 fps) + gif."""
    argv = sys.argv[1:] if argv is None else list(argv)
    exo, out_prefix, angle = argv[0], argv[1], argv[2]
    r = pv.get_reader(exo)
    n = len(r.time_values)
    fd = out_prefix + "_frames"
    os.makedirs(fd, exist_ok=True)

    # Static triangulation from the first read: each quad cell (VTK layout [4, n0, n1, n2, n3]) is
    # split into two triangles so matplotlib can shade it; the topology does not change over time.
    g0 = r.read().combine()
    cells = g0.cells.reshape(-1, 5)[:, 1:]
    tris = np.vstack([cells[:, [0, 1, 2]], cells[:, [0, 2, 3]]])

    for i in range(n):
        r.set_active_time_point(i)
        g = r.read().combine()
        c = g.point_data["c"]
        dx = g.point_data.get("disp_x", np.zeros(g.n_points))
        dy = g.point_data.get("disp_y", np.zeros(g.n_points))
        x = g.points[:, 0] + dx * WARP
        y = g.points[:, 1] + dy * WARP
        fig, ax = plt.subplots(figsize=(6.2, 6.4))
        ax.tripcolor(Triangulation(x, y, tris), c, cmap=DMG, vmin=0, vmax=1, shading="gouraud")
        # annotations: the seeded notch (left half of y=0.5) and the pulled top edge
        ax.plot([0, 0.5], [0.5, 0.5], "k:", lw=1, alpha=0.5)
        ax.text(0.2, 0.53, "initial notch", fontsize=8, color="#555")
        for xa in np.linspace(0.15, 0.85, 5):
            ax.annotate(
                "",
                xy=(xa, 1.06),
                xytext=(xa, 0.99),
                arrowprops=dict(arrowstyle="-|>", color="#2c3e50", lw=1.4),
            )
        ax.text(0.5, 1.10, "pulled up", ha="center", fontsize=10, color="#2c3e50", weight="bold")
        ax.set_aspect("equal")
        ax.set_xlim(-0.05, 1.05)
        ax.set_ylim(-0.08, 1.2)
        ax.axis("off")
        ax.set_title(
            f"Full-model crack in a {angle}° rod field — free to deflect\nstep {i+1}/{n}",
            fontsize=11,
        )
        fig.savefig(os.path.join(fd, f"f{i:04d}.png"), dpi=105, bbox_inches="tight")
        plt.close(fig)

    # encode: mp4 at 20 fps (even-height scaling for yuv420p), then a lighter gif from the mp4
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            "20",
            "-i",
            os.path.join(fd, "f%04d.png"),
            "-pix_fmt",
            "yuv420p",
            "-vf",
            "scale=760:-2",
            out_prefix + ".mp4",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            out_prefix + ".mp4",
            "-vf",
            "fps=12,scale=520:-1",
            out_prefix + ".gif",
        ],
        check=True,
        capture_output=True,
    )
    print(f"wrote {out_prefix}.mp4 ({os.path.getsize(out_prefix+'.mp4')//1024} KB)")


if __name__ == "__main__":
    main()
