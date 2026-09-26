"""
tm6_render_v2.py — LEGIBLE crack-propagation video (annotated 2-panel).

Left  : the notched specimen, colored by damage (light steel = intact material, red = cracked),
        on the displacement-warped mesh, with the loading/BC/notch annotated so it is obvious
        what is being pulled and where the crack starts.
Right : the load-displacement curve (reaction vs applied displacement) with a moving marker,
        so each frame of cracking is tied to the mechanics (load climbs, then drops as the
        crack runs). Everything in matplotlib for full control. ffmpeg stitches the frames.

INPUTS   <exodus.e> <csv> <out_prefix> <angle_deg> [warp]   (Exodus + postprocessor CSV with
         columns top_disp / reaction_y of a tm6_twist.i-type run; warp = cosmetic factor, default 8)
OUTPUTS  <out_prefix>_frames/f####.png, <out_prefix>.mp4, <out_prefix>.gif
Usage: python -m abcad.fracture.tm6_render_v2 <exodus.e> <csv> <out_prefix> <angle_deg> [warp]
Needs pyvista + matplotlib (conda cad_env) and ffmpeg on PATH.
"""

from __future__ import annotations

import csv as csvmod
import os
import subprocess
import sys

import matplotlib
import numpy as np

matplotlib.use("Agg")  # headless backend: file output only (must precede the pyplot import)
import matplotlib.pyplot as plt
import pyvista as pv
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.tri import Triangulation

# damage colormap: intact material -> light steel; crack -> crimson (reads as "breaking")
DMG = LinearSegmentedColormap.from_list(
    "dmg", ["#cdd7e0", "#cdd7e0", "#e8a37a", "#c0392b", "#7d1a12"]
)


def main(argv=None):
    """CLI entry point: two-panel frames (damage field + load curve), then mp4 (22 fps) + gif."""
    argv = sys.argv[1:] if argv is None else list(argv)
    exo, csvp, out_prefix, angle = argv[0], argv[1], argv[2], argv[3]
    warp = float(argv[4]) if len(argv) > 4 else 8.0

    # load-displacement history from the CSV
    rows = list(csvmod.DictReader(open(csvp)))
    D = np.array([float(r["top_disp"]) for r in rows]) * 1e3  # um
    R = np.array([abs(float(r["reaction_y"])) for r in rows])
    # drop failed-retry rows (non-increasing displacement) from the plotted curve
    keep = np.concatenate([[True], np.diff(np.array([float(r["top_disp"]) for r in rows])) > 1e-12])

    reader = pv.get_reader(exo)
    times = reader.time_values
    n = len(times)
    frames_dir = out_prefix + "_frames"
    os.makedirs(frames_dir, exist_ok=True)

    # build the (static) mesh triangulation once from step 0; warp per frame
    def get_grid(i):
        reader.set_active_time_point(i)
        return reader.read().combine()

    g0 = get_grid(0)
    pts0 = g0.points[:, :2]
    # triangulate quad cells -> 2 triangles each (GeneratedMesh is quads)
    cells = g0.cells.reshape(-1, 5)[:, 1:]  # [n, 4] quad node ids (VTK: leading count=4)
    tris = np.vstack([cells[:, [0, 1, 2]], cells[:, [0, 2, 3]]])

    for i in range(n):
        g = get_grid(i)
        c = g.point_data["c"]
        dx = g.point_data.get("disp_x", np.zeros(g.n_points))
        dy = g.point_data.get("disp_y", np.zeros(g.n_points))
        x = g.points[:, 0] + dx * warp
        y = g.points[:, 1] + dy * warp
        tri = Triangulation(x, y, tris)

        fig, (axL, axR) = plt.subplots(
            1, 2, figsize=(12, 4.6), gridspec_kw={"width_ratios": [1.35, 1]}
        )
        # ---- left: specimen + damage ----
        tpc = axL.tripcolor(tri, c, cmap=DMG, vmin=0, vmax=1, shading="gouraud")
        axL.set_aspect("equal")
        axL.set_xlim(-0.05, 1.05)
        axL.set_ylim(-0.18, 0.78)
        axL.axis("off")
        # loading arrows (top, pulled up)
        for xa in np.linspace(0.1, 0.9, 5):
            axL.annotate(
                "",
                xy=(xa, 0.60),
                xytext=(xa, 0.52),
                arrowprops=dict(arrowstyle="-|>", color="#2c3e50", lw=1.6),
            )
        axL.text(0.5, 0.71, "pulled up", ha="center", fontsize=10, color="#2c3e50", weight="bold")
        # fixed support (bottom right half)
        axL.plot([0.5, 1.0], [-0.005, -0.005], color="#2c3e50", lw=3)
        for xf in np.linspace(0.55, 0.98, 8):
            axL.plot([xf, xf - 0.03], [-0.005, -0.05], color="#2c3e50", lw=1)
        axL.text(0.75, -0.11, "fixed", ha="center", fontsize=9, color="#2c3e50")
        # initial notch
        axL.annotate(
            "initial notch",
            xy=(0.5, 0.0),
            xytext=(0.12, -0.13),
            fontsize=9,
            color="#c0392b",
            arrowprops=dict(arrowstyle="->", color="#c0392b", lw=1.4),
        )
        cb = fig.colorbar(tpc, ax=axL, fraction=0.035, pad=0.02)
        cb.set_label("damage (0 = intact, 1 = cracked)")

        # ---- right: load-displacement with moving marker ----
        axR.plot(D[keep], R[keep], color="#7f8c8d", lw=1.5)
        j = min(i, len(D) - 1)  # frame index -> CSV row (the CSV may hold fewer rows than steps)
        axR.plot(D[j], R[j], "o", color="#c0392b", ms=9)
        axR.axvline(D[j], color="#c0392b", ls=":", lw=0.8, alpha=0.6)
        axR.set_xlabel("applied displacement [µm]")
        axR.set_ylabel("load (reaction force)")
        axR.set_title("Load–displacement (you are here ●)", fontsize=11)
        axR.grid(alpha=0.3)
        ipk = int(np.argmax(R[keep]))
        axR.annotate(
            "peak → crack runs",
            xy=(D[keep][ipk], R[keep][ipk]),
            xytext=(D[keep][ipk] * 0.3, R[keep][ipk] * 0.9),
            fontsize=8,
            color="#2c3e50",
            arrowprops=dict(arrowstyle="->", color="#2c3e50", lw=1),
        )

        fig.suptitle(
            f"TM-6 crack propagation  ·  rods at {angle}° to the crack  ·  warp ×{warp:.0f}  ·  step {i+1}/{n}",
            fontsize=12,
            weight="bold",
        )
        fig.tight_layout(rect=[0, 0, 1, 0.94])
        fig.savefig(os.path.join(frames_dir, f"f{i:04d}.png"), dpi=105)
        plt.close(fig)

    # encode: mp4 at 22 fps (even-height scaling for yuv420p), then a lighter gif from the mp4
    mp4 = out_prefix + ".mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            "22",
            "-i",
            os.path.join(frames_dir, "f%04d.png"),
            "-pix_fmt",
            "yuv420p",
            "-vf",
            "scale=1260:-2",
            mp4,
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-i", mp4, "-vf", "fps=12,scale=720:-1", out_prefix + ".gif"],
        check=True,
        capture_output=True,
    )
    print(f"wrote {mp4} ({os.path.getsize(mp4)//1024} KB)")


if __name__ == "__main__":
    main()
