"""
tm6_fracture_compare.py — compare fused vs non-fused woven fracture (crack path + work of fracture).

Inputs are the two runs from tm6_make_woven_fracture_deck.py. Produces:
  1) <out>_crack.png  — final damage field c (top-down) for each mode, side by side. Fused crack runs
     straight through; the hypothesis tested is that a non-fused crack deflects onto the weak
     interfaces (in the archived run both cracks branch symmetrically; see docs/FRACTURE.md).
  2) <out>_curve.png  — reaction_x vs applied_disp for both, with the work to a common displacement
     (area under the curve up to the shorter run's end) annotated.
And prints peak load + work-to-common-displacement for each mode and their ratio. Because the
window ends where the weaker specimen's run ends, the ratio understates a strength penalty; also
compare peak loads and energy to peak (the archived runs: 0.32x peak, 0.16x energy to peak).

INPUTS
    <fused.e> <fused.csv> <nonfused.e> <nonfused.csv> — MOOSE Exodus + postprocessor CSV of each run
    (CSV columns applied_disp, reaction, crack_c).
OUTPUTS
    <out_prefix>_crack.png, <out_prefix>_curve.png, and the comparison table on stdout.

Usage: python -m abcad.fracture.tm6_fracture_compare <fused.e> <fused.csv> <nonfused.e> <nonfused.csv> <out_prefix>
Needs pyvista + matplotlib (conda cad_env).
"""

from __future__ import annotations

import csv
import sys

import matplotlib
import numpy as np
import pyvista as pv

matplotlib.use("Agg")  # headless backend: file output only (must precede the pyplot import)
import matplotlib.pyplot as plt

# Trapezoidal integration: numpy >= 2 names it `trapezoid`; numpy 1.x only has `trapz` (same maths).
# getattr (not np.trapz) for the 1.x name: numpy >= 2.4 removed `trapz` and its type stubs.
_trapezoid = getattr(np, "trapezoid", None) or getattr(np, "trapz")


def load_csv(path):
    """Return (disp, reaction, crack_c), de-duplicating failed-retry rows (repeated/decreasing disp)."""
    rows = list(csv.DictReader(open(path)))
    d = np.array([float(r["applied_disp"]) for r in rows])
    R = np.array([abs(float(r["reaction"])) for r in rows])
    c = np.array([float(r["crack_c"]) for r in rows])
    keep = np.concatenate([[True], np.diff(d) > 1e-12])  # monotone-increasing disp only
    return d[keep], R[keep], c[keep]


def open_undeformed(exo):
    """Exodus reader with ApplyDisplacements OFF (VTK else bakes MOOSE's bogus grouped disp into coords)."""
    r = pv.get_reader(exo)
    try:
        r.reader.SetApplyDisplacements(False)
    except Exception:
        pass  # reader without that switch: nothing to disable
    return r


def crack_panel(plotter, exo, title):
    """Draw the final-step damage field c of one run into the current subplot (top-down view)."""
    r = open_undeformed(exo)
    r.set_active_time_point(len(r.time_values) - 1)
    g = r.read().combine()
    c = g.point_data["c"] if "c" in g.point_data else g.cell_data.get("c")
    plotter.add_mesh(
        g,
        scalars=c,
        cmap="inferno",
        clim=(0, 1),
        show_edges=False,
        scalar_bar_args={"title": "damage c", "n_labels": 3, "fmt": "%.1f"},
    )
    plotter.add_text(title, position="upper_left", font_size=13, color="white")
    plotter.view_xy()
    plotter.camera.zoom(1.3)


def main(argv=None):
    """CLI entry point: render both crack paths, plot both curves, print the work ratio."""
    argv = sys.argv[1:] if argv is None else list(argv)
    fused_e, fused_csv, nf_e, nf_csv, out = argv[0:5]
    pv.OFF_SCREEN = True

    # --- 1) crack-path panels ---
    p = pv.Plotter(off_screen=True, shape=(1, 2), window_size=[1400, 720])
    p.background_color = "black"
    p.subplot(0, 0)
    crack_panel(p, fused_e, "FUSED (uniform Gc) -> straight crack")
    p.subplot(0, 1)
    crack_panel(p, nf_e, "NON-FUSED (weak interfaces) -> deflected crack")
    p.screenshot(out + "_crack.png")
    p.close()
    print("wrote", out + "_crack.png")

    # --- 2) reaction-displacement curves + work of fracture ---
    df, Rf, cf = load_csv(fused_csv)
    dn, Rn, cn = load_csv(nf_csv)
    d_common = min(df.max(), dn.max())  # fair common displacement window

    def work(d, R):
        # area under the reaction-displacement curve up to the common window (relative work)
        m = d <= d_common + 1e-12
        return float(_trapezoid(R[m], d[m]))

    Wf, Wn = work(df, Rf), work(dn, Rn)
    pkf, pkn = Rf.max(), Rn.max()

    plt.figure(figsize=(7, 5))
    plt.plot(df, Rf, "-o", ms=3, color="#d1495b", label=f"fused  (peak {pkf:.3f}, W={Wf:.3e})")
    plt.plot(dn, Rn, "-o", ms=3, color="#2e86ab", label=f"non-fused (peak {pkn:.3f}, W={Wn:.3e})")
    plt.axvline(d_common, ls="--", lw=0.8, color="gray", label=f"common disp {d_common:.4f}")
    plt.xlabel("applied displacement")
    plt.ylabel("reaction_x")
    plt.title(f"Woven fracture: work to common displacement, non-fused/fused = {Wn/Wf:.2f}x")
    plt.legend(fontsize=8)
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(out + "_curve.png", dpi=130)
    plt.close()
    print("wrote", out + "_curve.png")

    # --- 3) comparison table ---
    print(f"\n{'mode':>10} {'peak_load':>10} {'work_to_common':>16} {'final_crack_c':>14}")
    print(f"{'fused':>10} {pkf:10.4f} {Wf:16.6e} {cf[-1]:14.4f}")
    print(f"{'nonfused':>10} {pkn:10.4f} {Wn:16.6e} {cn[-1]:14.4f}")
    print(
        f"\nwork ratio (non-fused / fused) = {Wn/Wf:.2f}x  ·  common disp window = {d_common:.5f}"
    )


if __name__ == "__main__":
    main()
