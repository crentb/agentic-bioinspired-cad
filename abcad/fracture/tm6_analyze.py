"""
tm6_analyze.py — TM-6 orientation sweep: peak load and relative work vs rod angle, from the CSVs.

Per angle: peak reaction (strength) and work = integral reaction d(top_disp) up to a COMMON
displacement across all angles (the shortest run's end, so every angle is integrated over the
same window).

INTERPRETATION CAVEAT
    In the archived sweep that common window closes BEFORE the aligned (0°/90°) specimens reach
    their peak load, and every run stops a few percent past its peak with no crack propagation.
    The work ratio therefore tracks initial stiffness (1.81x at 45°), not toughness: the energy
    absorbed up to peak load is essentially angle-independent (0.98x at 45°). Initiation
    toughness is measured by the J-integral deck (tm6_jintegral.i). See docs/FRACTURE.md.

INPUTS
    tm6_a{0,15,30,45,60,75,90}.csv — MOOSE postprocessor CSVs (columns top_disp, reaction_y,
    crack_c) from the tm6_twist.i angle sweep, read from CSV_DIR (default: the working directory).
    The banked sweep lives in results/fracture/orientation_sweep/.
OUTPUTS
    stdout: the per-angle table and the angles of maximum work-to-common-displacement and of
    maximum peak load, with their max/min ratios.

USAGE
    python -m abcad.fracture.tm6_analyze [CSV_DIR]
"""

from __future__ import annotations

import csv
import os
import sys

import numpy as np

# Trapezoidal integration: numpy >= 2 names it `trapezoid`; numpy 1.x only has `trapz` (same maths).
# getattr (not np.trapz) for the 1.x name: numpy >= 2.4 removed `trapz` and its type stubs.
_trapezoid = getattr(np, "trapezoid", None) or getattr(np, "trapz")

# Rod/crack angles of the orientation sweep [deg] (0 and 90 = axis-aligned, 45 = maximally off-axis).
ANGLES = [0, 15, 30, 45, 60, 75, 90]


def load(a, csv_dir="."):
    """Return (displacement, |reaction|, crack_c) arrays for angle ``a``, retry rows removed."""
    rows = list(csv.DictReader(open(os.path.join(csv_dir, f"tm6_a{a}.csv"))))
    d = np.array([float(r["top_disp"]) for r in rows])
    R = np.array([abs(float(r["reaction_y"])) for r in rows])
    c = np.array([float(r["crack_c"]) for r in rows])
    # dedupe repeated-time (failed-retry) rows: keep max disp reached
    keep = np.concatenate([[True], np.diff(d) > 1e-12])
    return d[keep], R[keep], c[keep]


def analyze(csv_dir=".", angles=ANGLES):
    """Compute the toughness table for every angle.

    Returns (d_common, rows) where d_common is the shared displacement window [mm] and each row is
    (angle_deg, peak_load, disp_at_peak, work_to_common_disp, final_crack_c). Work is the area under
    the reaction-displacement curve up to d_common (relative work of fracture).
    """
    data = {a: load(a, csv_dir) for a in angles}
    d_common = min(d.max() for d, _, _ in data.values())  # common displacement window
    rows_out = []
    for a in angles:
        d, R, c = data[a]
        pk = R.max()
        dpk = d[R.argmax()]
        m = d <= d_common + 1e-12
        work = float(_trapezoid(R[m], d[m]))  # relative work of fracture
        rows_out.append((a, pk, dpk, work, c[-1]))
    return d_common, rows_out


def main(argv=None):
    """CLI entry point: print the per-angle table and the toughness / strength peaks."""
    argv = sys.argv[1:] if argv is None else list(argv)
    csv_dir = argv[0] if argv else "."
    d_common, rows_out = analyze(csv_dir)

    print(f"common displacement window: 0 .. {d_common:.5f} mm")
    print(
        f"{'angle':>6} {'peak_load':>10} {'d@peak':>9} {'work_to_common':>15} {'final_crack':>12}"
    )
    for a, pk, dpk, work, c_last in rows_out:
        print(f"{a:6d} {pk:10.4f} {dpk:9.5f} {work:15.6e} {c_last:12.4f}")

    angles = [r[0] for r in rows_out]
    works = [r[3] for r in rows_out]
    peaks = [r[1] for r in rows_out]
    best_w = angles[int(np.argmax(works))]
    best_p = angles[int(np.argmax(peaks))]
    # "Work" here is stiffness-weighted (see the module docstring), so it is labelled as what it is.
    print(
        f"\nmax work-to-common-displacement at {best_w} deg "
        f"({max(works)/min(works):.2f}x the minimum; stiffness-weighted, see docs/FRACTURE.md)"
    )
    print(f"strongest (max peak) at {best_p} deg ({max(peaks)/min(peaks):.2f}x the weakest)")


if __name__ == "__main__":
    main()
