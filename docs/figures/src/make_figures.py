#!/usr/bin/env python3
"""
make_figures.py -- regenerate the documentation figure set in docs/figures/.

Purpose
    Every figure in docs/ is rebuilt by this one script, from two kinds of input:

    1. Evidence records (JSON / CSV) written by the instruments of the pipeline:
       the phase-field fracture sweeps, the damage-tolerance screen, the print
       audit, and the agentic-loop run manifests. These drive the data charts,
       so every plotted number can be traced back to a record.
    2. Simulation outputs and geometry (MOOSE Exodus files, STLs, loop run folders),
       rendered here in one house style (field_render.py): the woven builder's own
       render look (bone material on white) for geometry, and one bone-to-oxblood
       ramp for stress and damage fields.
    3. Existing raster renders of generated parts (pyvista renders of STLs), composed
       into labeled multi-panel figures; titles that carry numbers are re-drawn from
       the records rather than copied from pixels.

    All charts share one visual system: a white surface, one sans-serif face,
    hairline solid gridlines, recessive axes, and categorical colors assigned in
    a fixed, colorblind-validated order (blue, orange, aqua), with gray reserved
    for context series. Each chart has a legend when it shows two or more series
    and uses direct labels sparingly.

Inputs (repo-relative defaults; override on the command line)
    --records  evidence records: results/ (curated copies) or the raw out/ tree
    --renders  existing renders and loop run folders: $ABCAD_OUT or out/
    --sims     simulation outputs and geometry: $ABCAD_OUT/figure_sims

    SIMULATION INPUTS (--sims; produce them with the commands shown)
        woven_diamond.stl            `just woven diamond` (README hero)
        wcell3_intact_pre.e, wcell3_dmg_pre.e
                                     the 3 x 3 woven-cell deck, intact and cut
                                     (`just deck-woven-cell 3 -1 0.05`, `... 3 0 0.05`)
        D_a{0,30,60,90}.e            tm6_stageD.i at each rod angle (euler_angle_1)
        boul_d{10,15,20,30}.e        tm6_make_bouligand_deck <pitch> 6, then solved
        vid_a{45,0}.e, vid_a{45,0}.csv   tm6_video.i at 45 and 0 deg
        D3d_long.e                   tm6_stageD_3d.i with Executioner/end_time=0.02
        twist3d_long.e               tm6_3d_twist_example.i with Executioner/end_time=0.006
    RENDER INPUTS (--renders)
        woven_{cubic,bcc,diamond,octahedron}.png, bouligand_d30_w.png,
        enamel_linear_x4.png, enamel_linear_x4_smooth.png,
        woven_fea_small_x20_smooth.png, woven_fea_small_plated.png,
        woven_fea_tension_stress.png   pyvista renders from the generators, the
                                       remesher and the FEA driver
        agent_runs/<run>/              a loop run folder: the critic's renders and
                                       the approved and auto-scaled STLs

Outputs
    PNG figures (kept <= 1.5 MB each) and GIF animations (<= 3 MB each) in
    --out. A figure whose inputs are missing is skipped with a message; the
    script exits non-zero only if a figure that was attempted fails.

Usage
    python docs/figures/src/make_figures.py                       # all figures
    python docs/figures/src/make_figures.py --records results --renders out
    python docs/figures/src/make_figures.py --only fracture_results

Dependencies
    numpy, matplotlib (>= 3.6, for per-glyph font fallback), Pillow.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")  # headless: figures are written to files, never shown
# House style for renders and field plots (sibling module; Python puts the script's own
# directory on sys.path, so this import works however the script is launched).
import field_render as fr  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from PIL import Image  # noqa: E402

# =============================================================================
# 1. Visual system
#    One surface, one sans face, a small set of ink tokens, and categorical
#    slots in a fixed order. Slots 1-3 were checked with a colorblind-safety
#    validator: all pairs clear a CVD delta-E of 9 (OKLab x 100) and the
#    normal-vision floor of 15. Aqua sits below 3:1 contrast on the surface,
#    so every aqua series also carries a legend entry and a direct label.
# =============================================================================
SURFACE = "#ffffff"  # chart surface (also the figure background): the white ground of the renders
INK = "#0b0b0b"  # primary text: titles, direct labels
INK_2 = "#52514e"  # secondary text: axis labels, legend text
MUTED = "#898781"  # tertiary text and de-emphasized reference series
GRID = "#e1e0d9"  # hairline gridlines, one step off the surface
AXIS = "#c3c2b7"  # axis spines and baselines
BLUE = "#2a78d6"  # categorical slot 1
ORANGE = "#eb6834"  # categorical slot 2
AQUA = "#1baf7a"  # categorical slot 3
BLUE_LIGHT = "#86b6ef"  # ordinal step lighter than BLUE (same hue), for "before"
CONTEXT = "#c3c2b7"  # gray for context series that are not the story

MAX_PNG_BYTES = 1_500_000  # size budget per PNG figure
MAX_GIF_BYTES = 3_000_000  # size budget per animation

plt.rcParams.update(
    {
        # Typeface: Helvetica where installed, then Arial, then the bundled DejaVu
        # Sans. Listing the families directly (not the generic "sans-serif") turns
        # on matplotlib's per-glyph fallback, so arrows and Greek letters missing
        # from Helvetica are drawn from the next family instead of as boxes.
        "font.family": ["Helvetica", "Arial", "DejaVu Sans"],
        "font.size": 10,
        "axes.titlesize": 11,
        "axes.titleweight": "bold",
        "axes.titlecolor": INK,
        "axes.titlelocation": "left",
        "axes.labelsize": 10,
        "axes.labelcolor": INK_2,
        "axes.edgecolor": AXIS,
        "axes.linewidth": 0.8,
        "axes.facecolor": SURFACE,
        "axes.grid": True,
        "axes.axisbelow": True,  # gridlines stay behind the data
        "grid.color": GRID,
        "grid.linewidth": 0.6,  # hairline
        "grid.linestyle": "-",  # solid, never dashed
        "xtick.color": INK_2,
        "ytick.color": INK_2,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "xtick.major.size": 0,  # tick marks off: gridlines carry the scale
        "ytick.major.size": 0,
        "legend.frameon": False,
        "legend.fontsize": 9,
        "legend.labelcolor": INK_2,
        "figure.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "axes.unicode_minus": True,  # a true minus sign in tick labels
    }
)

LINE_W = 1.8  # data lines [pt]; about 2 px at typical README display width
CONTEXT_W = 1.1  # context (gray) lines [pt]
MARKER_S = 6.5  # marker diameter [pt]
RING_W = 1.3  # surface-colored ring around markers [pt], keeps overlaps legible


def style_axes(ax) -> None:
    """Hide the top and right spines; the remaining two stay hairline and gray."""
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def panel_title(ax, letter: str, text: str) -> None:
    """Left-aligned panel title of the form '(a) Text' in primary ink."""
    ax.set_title(f"({letter}) {text}", pad=8)


# =============================================================================
# 2. Locating inputs
#    Records and renders are found by file name anywhere below their root, so
#    the script works whether the records sit in results/ (curated copies) or
#    in the raw instrument output tree.
# =============================================================================
class Finder:
    """Recursive, cached file-name index below one root directory."""

    def __init__(self, root: Path, suffixes: tuple[str, ...]):
        self.root = Path(root)
        self.suffixes = suffixes
        self._index: dict[str, list[Path]] | None = None

    def _build(self) -> dict[str, list[Path]]:
        index: dict[str, list[Path]] = {}
        if self.root.is_dir():
            # os.walk with followlinks=True so a staging directory of symlinks
            # behaves like the real tree.
            for dirpath, _dirnames, filenames in os.walk(self.root, followlinks=True):
                for name in filenames:
                    if name.lower().endswith(self.suffixes):
                        index.setdefault(name, []).append(Path(dirpath) / name)
        for paths in index.values():
            paths.sort()
        return index

    @property
    def index(self) -> dict[str, list[Path]]:
        if self._index is None:
            self._index = self._build()
        return self._index

    def all(self, name: str) -> list[Path]:
        """Every file with this exact name (possibly empty)."""
        return list(self.index.get(name, []))

    def one(self, name: str, hint: str | None = None) -> Path:
        """
        Exactly one file with this name. `hint` disambiguates by requiring the
        substring in the path (for example a run-folder name). Raises
        FileNotFoundError when absent and ValueError when ambiguous.
        """
        paths = self.all(name)
        if hint is not None:
            paths = [p for p in paths if hint in str(p)]
        if not paths:
            raise FileNotFoundError(
                f"{name}" + (f" (hint {hint!r})" if hint else "") + f" not found below {self.root}"
            )
        if len(paths) > 1:
            raise ValueError(
                f"{name} is ambiguous below {self.root}: " + ", ".join(str(p) for p in paths[:4])
            )
        return paths[0]


def read_csv_columns(path: Path) -> dict[str, np.ndarray]:
    """Read a numeric CSV into {column: float array}."""
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    return {k: np.array([float(r[k]) for r in rows]) for k in rows[0]}


def monotone(x: np.ndarray, *ys: np.ndarray) -> tuple[np.ndarray, ...]:
    """
    Keep only rows where x strictly increases. MOOSE repeats a time step after a
    failed solve; the repeated rows would otherwise double-count area in the
    work integrals (the same de-duplication the fracture analysis scripts use).
    """
    keep = np.concatenate([[True], np.diff(x) > 1e-12])
    return (x[keep],) + tuple(y[keep] for y in ys)


# =============================================================================
# 3. Output helpers
# =============================================================================
def save_png(fig, path: Path, dpi: int = 200) -> None:
    """
    Save a figure as PNG and enforce the size budget. If the file is too large
    (photographic render composites), it is re-encoded with an adaptive
    256-color palette, which is visually lossless for these renders; if still
    too large it is downscaled in steps of 15 %.
    """
    # Keep the figure's own background: the charts use the chart surface, the
    # render composites use white so the white-background renders sit seamlessly.
    fig.savefig(path, dpi=dpi, facecolor=fig.get_facecolor())
    plt.close(fig)
    img = Image.open(path)
    if path.stat().st_size > MAX_PNG_BYTES:
        img.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT).save(
            path, optimize=True
        )
    while path.stat().st_size > MAX_PNG_BYTES:
        img = Image.open(path).convert("RGB")
        w, h = img.size
        img = img.resize((int(w * 0.85), int(h * 0.85)), Image.LANCZOS)
        img.quantize(colors=256, method=Image.Quantize.MEDIANCUT).save(path, optimize=True)
    size_kb = path.stat().st_size / 1024
    print(
        f"  wrote {path.name}  ({Image.open(path).size[0]}x{Image.open(path).size[1]} px, "
        f"{size_kb:.0f} KB)"
    )


def content_box(
    img: Image.Image, bg_tol: int = 12, ignore: list[tuple] | None = None, margin: int = 16
) -> tuple[int, int, int, int]:
    """
    Bounding box (left, top, right, bottom) of everything that differs from the
    background color, taken as the top-left pixel. `ignore` lists boxes whose
    content should not extend the crop (e.g. the orientation triad that pyvista
    draws in a corner). A margin in pixels is added on every side.
    """
    arr = np.asarray(img.convert("RGB")).astype(int)
    bg = arr[0, 0]
    diff = np.abs(arr - bg).sum(axis=2) > bg_tol
    for x0, y0, x1, y1 in ignore or []:
        diff[y0:y1, x0:x1] = False
    ys, xs = np.nonzero(diff)
    h, w = diff.shape
    return (
        max(int(xs.min()) - margin, 0),
        max(int(ys.min()) - margin, 0),
        min(int(xs.max()) + margin, w),
        min(int(ys.max()) + margin, h),
    )


def pyvista_crop(src) -> Image.Image:
    """
    Load a pyvista render (a path or an already-loaded image) and crop it to the
    object. The axes triad sits in the lower-left corner (about 15 % of the
    width and 20 % of the height) and is excluded from the crop box.
    """
    img = src.convert("RGB") if isinstance(src, Image.Image) else Image.open(src).convert("RGB")
    w, h = img.size
    triad = (0, int(h * 0.80), int(w * 0.17), h)
    return img.crop(content_box(img, ignore=[triad]))


def show_image(ax, img: Image.Image) -> None:
    """Draw a raster image in an axes with no ticks, grid, or frame."""
    ax.imshow(np.asarray(img))
    ax.set_axis_off()


def uniform_tiles(imgs: list[Image.Image], fill=(255, 255, 255)) -> list[Image.Image]:
    """
    Pad every image (centered, with `fill`) to the largest height/width ratio in
    the set. Axes that keep the image aspect then all have the same shape, so
    panel titles line up across a row instead of floating at different heights.
    """
    ratio = max(im.size[1] / im.size[0] for im in imgs)
    out = []
    for im in imgs:
        w, h = im.size
        tw, th = (w, round(w * ratio)) if h / w < ratio else (round(h / ratio), h)
        canvas = Image.new("RGB", (max(tw, w), max(th, h)), fill)
        canvas.paste(im, ((canvas.size[0] - w) // 2, (canvas.size[1] - h) // 2))
        out.append(canvas)
    return out


def render_figure(nrows: int, ncols: int, figsize: tuple[float, float]):
    """Figure and axes for a render composite, on white to match the renders."""
    fig, axes = plt.subplots(nrows, ncols, figsize=figsize, facecolor="white")
    return fig, axes


def split_colorbar(img: Image.Image) -> tuple[Image.Image, Image.Image]:
    """
    Separate a pyvista render into the object and its horizontal colorbar.
    The colorbar gradient is the band of strongly saturated rows in the bottom
    quarter of the image; everything above its tick labels (40 px) is the object.
    Returns (object image, gradient strip). The strip is later redrawn with
    matplotlib tick labels, because pyvista overprints the bar title on the
    middle tick label.
    """
    a = np.asarray(img.convert("RGB")).astype(int)
    h, w, _ = a.shape
    sat = a.max(axis=2) - a.min(axis=2)  # 0 for grays, high for colors
    rows = [y for y in range(int(h * 0.75), h) if (sat[y] > 60).sum() > 0.3 * w]
    if not rows:
        raise ValueError("no colorbar band found")
    y0, y1 = min(rows), max(rows)
    cols = np.where((sat[y0 : y1 + 1] > 60).any(axis=0))[0]
    strip = img.crop((int(cols.min()) + 2, y0 + 2, int(cols.max()) - 1, y1 - 1))
    body = img.crop((0, 0, w, y0 - 40))
    return body, strip


# =============================================================================
# 4. Data charts
# =============================================================================
ANGLES = [0, 15, 30, 45, 60, 75, 90]  # crack-versus-rod orientation sweep [deg]


def fig_fracture_results(rec: Finder, out: Path) -> None:
    """
    Four-panel fracture summary (FRACTURE.md, Figure 1).

    (a) Load-displacement of the notched half model at every orientation:
        45 deg and the axis-aligned 0/90 deg in color, the rest as context.
        A hairline marks the common-displacement window (end of the shortest
        run), which is where the source work-to-common-displacement metric stops.
    (b) Orientation ratios to the 0 deg value: initial stiffness (gray
        reference), peak load, energy absorbed up to peak load, and J at crack
        initiation. The comparison shows that the peak-load gain tracks the
        stiffer rotated material while the energy to peak does not grow.
    (c) Crack tortuosity through the ply architecture versus pitch, with the
        10-30 deg/ply range of reported optima (LITERATURE.md §1.6) shaded.
    (d) Fused versus weak-interface woven idealization: reaction versus applied
        displacement.
    All phase-field quantities are in model units (relative comparisons).
    """
    # ---- load the orientation sweep (displacement, reaction) per angle -------
    curves = {}
    for a in ANGLES:
        c = read_csv_columns(rec.one(f"tm6_a{a}.csv"))
        d, r = monotone(c["top_disp"], np.abs(c["reaction_y"]))
        curves[a] = (d, r)
    d_common = min(d.max() for d, _ in curves.values())  # shortest run ends here

    # Per-angle scalar measures, each computed from the same curves:
    #   k0      initial secant stiffness (first nonzero step), reaction/displacement
    #   peak    maximum reaction (strength of the notched specimen)
    #   e_peak  energy absorbed up to the peak load, trapezoidal integral of R dd
    k0 = {a: curves[a][1][1] / curves[a][0][1] for a in ANGLES}
    peak = {a: curves[a][1].max() for a in ANGLES}
    e_peak = {}
    for a in ANGLES:
        d, r = curves[a]
        i = int(np.argmax(r))
        e_peak[a] = float(np.trapezoid(r[: i + 1], d[: i + 1]))
    j_rec = json.load(open(rec.one("tm6_jintegral_result.json")))
    j_init = dict(zip(j_rec["angles_deg"], j_rec["J_at_initiation"]))

    fig, axes = plt.subplots(2, 2, figsize=(11.0, 8.4))
    fig.subplots_adjust(left=0.07, right=0.98, top=0.95, bottom=0.08, hspace=0.42, wspace=0.22)

    # ---- (a) load-displacement curves ----------------------------------------
    ax = axes[0, 0]
    style_axes(ax)
    for a in (15, 30, 60, 75):  # context: gray, thin, behind
        d, r = curves[a]
        ax.plot(
            d * 1e3,
            r,
            color=CONTEXT,
            lw=CONTEXT_W,
            zorder=2,
            label="15°, 30°, 60°, 75°" if a == 15 else None,
        )
    d, r = curves[0]  # 0 and 90 deg coincide exactly
    ax.plot(d * 1e3, r, color=ORANGE, lw=LINE_W, zorder=3, label="0° and 90°")
    d, r = curves[45]
    ax.plot(d * 1e3, r, color=BLUE, lw=LINE_W, zorder=4, label="45°")
    ax.axvline(d_common * 1e3, color=INK_2, lw=0.8, zorder=1)
    ax.annotate(
        "end of shortest run\n(common-displacement window)",
        xy=(d_common * 1e3, 0.035),
        xytext=(d_common * 1e3 - 0.08, 0.035),
        ha="right",
        va="bottom",
        fontsize=8.5,
        color=INK_2,
    )
    ax.set_xlabel("Applied displacement (×10⁻³, model units)")
    ax.set_ylabel("Reaction force (model units)")
    ax.set_xlim(0, 3.3)
    ax.set_ylim(0, 0.34)
    ax.legend(loc="upper left", handlelength=1.6)
    panel_title(ax, "a", "Notched specimen, crack-versus-rod angle")

    # ---- (b) orientation ratios to 0 deg --------------------------------------
    ax = axes[0, 1]
    style_axes(ax)
    ax.axhline(1.0, color=AXIS, lw=0.8, zorder=1)  # the 0-deg reference level
    series = [
        # (label, values, color, line width, z-order)
        ("Initial stiffness", k0, MUTED, CONTEXT_W + 0.3, 2),
        ("Peak load", peak, BLUE, LINE_W, 4),
        ("Energy to peak load", e_peak, ORANGE, LINE_W, 3),
        ("J at crack initiation", j_init, AQUA, LINE_W, 3),
    ]
    for label, vals, color, lw, z in series:
        y = np.array([vals[a] / vals[0] for a in ANGLES])
        ax.plot(
            ANGLES,
            y,
            color=color,
            lw=lw,
            zorder=z,
            label=label,
            marker="o",
            ms=MARKER_S if color != MUTED else MARKER_S - 1.5,
            mec=SURFACE,
            mew=RING_W,
        )
        # Direct label at 45 deg, where the four measures separate most.
        y45 = vals[45] / vals[0]
        ax.annotate(
            f"{y45:.2f}×",
            xy=(45, y45),
            xytext=(7, 0),
            textcoords="offset points",
            ha="left",
            va="center",
            fontsize=8.5,
            color=INK,
        )
    ax.set_xticks(ANGLES)
    ax.set_xticklabels([f"{a}°" for a in ANGLES])
    ax.set_xlabel("Angle between rod direction and crack plane")
    ax.set_ylabel("Ratio to the 0° value")
    ax.set_ylim(0.8, 1.95)
    ax.legend(loc="upper right", handlelength=1.6)
    panel_title(ax, "b", "What the orientation changes")

    # ---- (c) Bouligand tortuosity versus pitch --------------------------------
    ax = axes[1, 0]
    style_axes(ax)
    boul = json.load(open(rec.one("tm6_bouligand_result.json")))
    pitches = sorted(int(k) for k in boul)
    tort = [boul[str(p)]["tortuosity"] for p in pitches]
    ax.axvspan(10, 30, color=AXIS, alpha=0.25, lw=0, zorder=0)  # reported-optima band wash
    ax.text(
        20.0,  # centered on the 10-30 deg/ply band
        1.955,
        "reported optima, printed Bouligand",
        ha="center",
        va="top",
        fontsize=8.5,
        color=INK_2,
    )
    ax.plot(
        pitches,
        tort,
        color=BLUE,
        lw=LINE_W,
        marker="o",
        ms=MARKER_S,
        mec=SURFACE,
        mew=RING_W,
        zorder=3,
    )
    i_max = int(np.argmax(tort))
    ax.annotate(
        f"{tort[i_max]:.2f}",
        xy=(pitches[i_max], tort[i_max]),
        xytext=(0, 8),
        textcoords="offset points",
        ha="center",
        va="bottom",
        fontsize=8.5,
        color=INK,
    )
    ax.set_xticks(pitches)
    ax.set_xticklabels([f"{p}°" for p in pitches])
    ax.set_xlim(7, 33)
    ax.set_ylim(1.0, 2.0)
    ax.set_xlabel("Ply pitch Δθ (per ply)")
    ax.set_ylabel("Crack tortuosity (path length / span)")
    panel_title(ax, "c", "Crack tortuosity through the ply stack")

    # ---- (d) fused versus weak-interface woven idealization -------------------
    ax = axes[1, 1]
    style_axes(ax)
    for name, label, color, z in (
        ("wfrac2_fused.csv", "Fused: uniform Gc", BLUE, 4),
        ("wfrac2_nonfused.csv", "Weak interfaces: Gc / 10", ORANGE, 3),
    ):
        c = read_csv_columns(rec.one(name))
        d, r = monotone(c["applied_disp"], np.abs(c["reaction"]))
        ax.plot(d * 1e3, r, color=color, lw=LINE_W, zorder=z, label=label)
        i = int(np.argmax(r))
        ax.plot(
            d[i] * 1e3, r[i], "o", color=color, ms=MARKER_S, mec=SURFACE, mew=RING_W, zorder=z + 1
        )
        ax.annotate(
            f"peak {r[i]:.3f}",
            xy=(d[i] * 1e3, r[i]),
            xytext=(8, 4),
            textcoords="offset points",
            ha="left",
            va="bottom",
            fontsize=8.5,
            color=INK,
        )
    ax.set_xlabel("Applied displacement (×10⁻³, model units)")
    ax.set_ylabel("Reaction force (model units)")
    ax.set_xlim(0, 20.5)
    ax.set_ylim(0, 0.52)
    ax.legend(loc="upper right", handlelength=1.6)
    panel_title(ax, "d", "Woven idealizations: fused versus weak interfaces")

    save_png(fig, out / "fracture_results.png")


# Display names for damage-tolerance parts (record directory name -> label).
DT_LABELS = {
    "h_solid_inplane": "Helicoidal plate, in-plane (control)",
    "dt_inplane": "Double-twist laminate, in-plane",
    "dt": "Double-twist laminate, through-thickness",
    "bouligand_d10_w": "Bouligand coupon, 10°/ply",
    "bouligand_d15_w": "Bouligand coupon, 15°/ply",
    "bouligand_d20_w": "Bouligand coupon, 20°/ply",
    "bouligand_d30_w": "Bouligand coupon, 30°/ply",
    "enamel_sigmoid": "Enamel ×4, sigmoid twist",
    "enamel_linear": "Enamel ×4, linear twist",
    "enamel_accelerating": "Enamel ×4, accelerating twist",
    "woven_fea_small": "Woven cube, fused crossings",
}


def load_damage_records(rec: Finder) -> dict[str, dict[float, float]]:
    """
    Collect TM-3 floor margins from every damage_tolerance.json below the
    records root: {part: {voxel_mm: margin}}. The part name is the record's
    parent directory; the voxel size comes from the record itself, so records
    from different resolutions never mix. Margin m = min R - (1 - mean dose),
    the ranking quantity defined in ABCAD-QMS-002.
    """
    margins: dict[str, dict[float, float]] = {}
    for path in rec.all("damage_tolerance.json"):
        d = json.load(open(path))
        part = path.parent.name
        if part not in DT_LABELS:
            continue
        voxel = float(d["mesh_recipe"]["voxel_mm"])
        m = d["min_retention"] - (1.0 - d["flaw_model"]["mean_dose"])
        # Near-solid plates ran at 1.25 mm inside the 1.0 mm protocol; both belong
        # to the coarse "proxy" family, the 0.5 mm runs to the resolved family.
        family = 0.5 if voxel <= 0.5 else 1.0
        margins.setdefault(part, {})[family] = m
    return margins


def fig_damage_tolerance(rec: Finder, out: Path) -> None:
    """
    Dumbbell chart of the TM-3 floor margin per architecture (FEA.md, Figure 2):
    light marker = 1.0 mm proxy voxels, dark marker = 0.5 mm resolved voxels,
    joined by a gray connector. Rows are ordered by the resolved margin (best at
    the top); parts measured at only one resolution show a single marker.
    """
    margins = load_damage_records(rec)
    if not margins:
        raise FileNotFoundError("no damage_tolerance.json records found")

    def sort_key(part: str) -> float:
        vals = margins[part]
        return vals.get(0.5, vals.get(1.0))

    parts = sorted(margins, key=sort_key)  # worst first -> bottom row
    fig, ax = plt.subplots(figsize=(9.6, 5.8))
    fig.subplots_adjust(left=0.33, right=0.97, top=0.90, bottom=0.12)
    style_axes(ax)
    ax.grid(axis="y", visible=False)  # rows need no horizontal grid
    ax.axvline(0.0, color=INK_2, lw=0.9, zorder=1)  # proportional-loss floor
    for y, part in enumerate(parts):
        vals = margins[part]
        if 1.0 in vals and 0.5 in vals:
            ax.plot(
                [vals[1.0], vals[0.5]], [y, y], color=AXIS, lw=2.2, zorder=2, solid_capstyle="round"
            )
        if 1.0 in vals:
            ax.plot(
                vals[1.0],
                y,
                "o",
                color=BLUE_LIGHT,
                ms=MARKER_S + 1,
                mec=SURFACE,
                mew=RING_W,
                zorder=3,
            )
        if 0.5 in vals:
            ax.plot(
                vals[0.5], y, "o", color=BLUE, ms=MARKER_S + 1, mec=SURFACE, mew=RING_W, zorder=4
            )
    # Direct labels only for the one architecture the story is about.
    woven = margins.get("woven_fea_small", {})
    y_w = parts.index("woven_fea_small") if "woven_fea_small" in parts else None
    for fam in (1.0, 0.5):
        if y_w is not None and fam in woven:
            ax.annotate(
                f"{woven[fam]:+.3f}".replace("-", "−"),
                xy=(woven[fam], y_w),
                xytext=(0, 9),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=8.5,
                color=INK,
            )
    ax.set_yticks(range(len(parts)))
    ax.set_yticklabels([DT_LABELS[p] for p in parts], color=INK_2)
    ax.set_xlabel("Floor margin m = min R − (1 − f)   (0 = proportional loss)")
    ax.set_xlim(-0.12, 0.012)
    ax.set_ylim(-0.7, len(parts) - 0.3)
    ax.text(0.003, len(parts) - 0.55, "floor", fontsize=8.5, color=INK_2, ha="left", va="center")
    # Legend built from proxy artists so that it lists exactly the two resolutions.
    from matplotlib.lines import Line2D

    handles = [
        Line2D(
            [],
            [],
            ls="",
            marker="o",
            ms=MARKER_S + 1,
            color=BLUE_LIGHT,
            mec=SURFACE,
            mew=RING_W,
            label="1.0 mm voxels (proxy)",
        ),
        Line2D(
            [],
            [],
            ls="",
            marker="o",
            ms=MARKER_S + 1,
            color=BLUE,
            mec=SURFACE,
            mew=RING_W,
            label="0.5 mm voxels (resolved)",
        ),
    ]
    ax.legend(
        handles=handles, loc="lower left", bbox_to_anchor=(0.0, 1.0), ncol=2, borderaxespad=0.3
    )
    save_png(fig, out / "damage_tolerance_ranking.png")


# Display names for print-audit parts (STL file name -> label, and whether the
# part is a repaired variant: scaled or remeshed for FDM).
PA_LABELS = {
    "woven_bcc.stl": ("Woven BCC, 2×2×2", False),
    "woven_diamond.stl": ("Woven diamond, 2×2×2", False),
    "woven_octahedron.stl": ("Woven octahedron, 2×2×2", False),
    "woven_cubic.stl": ("Woven cubic, numpy-stl sweep", False),
    "woven_cubic_blender.stl": ("Woven cubic, Blender sweep", False),
    "dt.stl": ("Double-twist laminate", False),
    "enamel_linear_x4.stl": ("Enamel ×4, as swept", False),
    "h_solid.stl": ("Helicoidal laminate plate", False),
    "ws.stl": ("Woven cubic, Tier 2", False),
    "bouligand_d20_w.stl": ("Bouligand coupon, 20°/ply", False),
    "bouligand_d15_w.stl": ("Bouligand coupon, 15°/ply", False),
    "bouligand_d10_w.stl": ("Bouligand coupon, 10°/ply", False),
    "bouligand_d30_w.stl": ("Bouligand coupon, 30°/ply", False),
    "woven_fea_small.stl": ("Woven specimen, 29 mm", False),
    "woven_fea_test.stl": ("Woven specimen, 37 mm", False),
    "woven_fea_small_x15.stl": ("Woven specimen ×1.5", True),
    "woven_fea_small_x20.stl": ("Woven specimen ×2.0", True),
    "woven_fea_small_x20_plated.stl": ("Woven specimen ×2.0, plated", True),
    "woven_fea_small_x20_smooth.stl": ("Woven specimen ×2.0, remeshed", True),
}


def fig_print_audit(rec: Finder, out: Path) -> None:
    """
    Dot plot of the fraction of material thinner than the 0.8 mm FDM strand
    limit, per part, on a logarithmic axis (PRINTING.md, Figure 1). A dot plot
    rather than bars: a log axis has no zero baseline for a bar to grow from.
    Gray = as-designed parts; blue = uniformly scaled or remeshed variants.
    The 1 % line is the TM-2 pass criterion.
    """
    rows: dict[str, float] = {}
    for path in rec.all("print_audit.csv"):
        with open(path, newline="") as fh:
            for r in csv.DictReader(fh):
                if r["file"] in PA_LABELS and r.get("lost_frac_d0.8"):
                    rows[r["file"]] = float(r["lost_frac_d0.8"])
    if not rows:
        raise FileNotFoundError("no print_audit.csv records found")
    parts = sorted(rows, key=lambda f: rows[f])  # smallest loss at the bottom
    fig, ax = plt.subplots(figsize=(9.6, 6.8))
    fig.subplots_adjust(left=0.30, right=0.95, top=0.90, bottom=0.10)
    style_axes(ax)
    ax.grid(axis="y", visible=False)
    ax.set_xscale("log")
    ax.axvline(0.01, color=INK_2, lw=0.9, zorder=1)  # the 1 % pass criterion
    for y, f in enumerate(parts):
        label, repaired = PA_LABELS[f]
        color = BLUE if repaired else MUTED
        ax.plot([1e-3, rows[f]], [y, y], color=GRID, lw=1.0, zorder=1)  # guide line
        ax.plot(rows[f], y, "o", color=color, ms=MARKER_S + 1, mec=SURFACE, mew=RING_W, zorder=3)
        if repaired:  # label the repaired variants, the parts the story is about
            ax.annotate(
                f"{100 * rows[f]:.2f} %",
                xy=(rows[f], y),
                xytext=(8, 0),
                textcoords="offset points",
                ha="left",
                va="center",
                fontsize=8.5,
                color=INK,
            )
    ax.set_yticks(range(len(parts)))
    ax.set_yticklabels([PA_LABELS[f][0] for f in parts], color=INK_2)
    ax.tick_params(which="minor", length=0)  # no minor tick marks on the log axis
    ax.set_xlim(1e-3, 1.0)
    ax.set_xticks([1e-3, 1e-2, 1e-1, 1.0])
    ax.set_xticklabels(["0.1 %", "1 %", "10 %", "100 %"])
    ax.set_xlabel("Material thinner than the 0.8 mm FDM strand limit (log scale)")
    ax.text(
        0.0105, len(parts) - 0.2, "pass ≤ 1 %", fontsize=8.5, color=INK_2, ha="left", va="center"
    )
    from matplotlib.lines import Line2D

    handles = [
        Line2D(
            [],
            [],
            ls="",
            marker="o",
            ms=MARKER_S + 1,
            color=MUTED,
            mec=SURFACE,
            mew=RING_W,
            label="As designed",
        ),
        Line2D(
            [],
            [],
            ls="",
            marker="o",
            ms=MARKER_S + 1,
            color=BLUE,
            mec=SURFACE,
            mew=RING_W,
            label="Scaled or remeshed for FDM",
        ),
    ]
    ax.legend(
        handles=handles, loc="lower left", bbox_to_anchor=(0.0, 1.0), ncol=2, borderaxespad=0.3
    )
    ax.set_ylim(-0.7, len(parts) - 0.1)
    save_png(fig, out / "print_audit_thin_features.png")


# =============================================================================
# 5. Raster composites
# =============================================================================
def compose_row(
    tiles: list[tuple[Image.Image, str, str]],
    nrows: int,
    ncols: int,
    figsize: tuple[float, float],
    path: Path,
    top: float,
    hspace: float = 0.10,
    dpi: int = 170,
):
    """
    Lay out cropped renders on a white figure with '(a) title' labels. Tiles are
    padded to one common aspect ratio first (uniform_tiles), so every panel has
    the same shape and the titles of a row sit at the same height.
    """
    imgs = uniform_tiles([img for img, _, _ in tiles])
    fig, axes = render_figure(nrows, ncols, figsize)
    fig.subplots_adjust(left=0.01, right=0.99, top=top, bottom=0.01, hspace=hspace, wspace=0.03)
    for ax, img, (_, letter, text) in zip(np.ravel(axes), imgs, tiles):
        show_image(ax, img)
        panel_title(ax, letter, text)
    save_png(fig, path, dpi=dpi)


def fig_woven_topologies(ren: Finder, out: Path) -> None:
    """2 x 2 panel of Tier-1 woven lattices (GENERATORS.md, Figure 2)."""
    spec = [
        ("woven_cubic.png", "a", "Cubic, n = 4 fibers per beam"),
        ("woven_bcc.png", "b", "BCC, n = 3"),
        ("woven_diamond.png", "c", "Diamond, n = 3"),
        ("woven_octahedron.png", "d", "Octahedron, n = 3"),
    ]
    tiles = [(pyvista_crop(ren.one(name)), letter, text) for name, letter, text in spec]
    compose_row(tiles, 2, 2, (9.0, 8.9), out / "woven_topologies.png", top=0.955, hspace=0.09)


def fig_generator_families(ren: Finder, out: Path) -> None:
    """One member of each generator family, side by side (GENERATORS.md, Figure 1)."""
    spec = [
        ("bouligand_d30_w.png", "a", "Helicoidal: Bouligand coupon, 30°/ply"),
        ("woven_cubic.png", "b", "Woven: cubic lattice, Tier 1"),
        ("enamel_linear_x4.png", "c", "Enamel: decussated rod lattice"),
    ]
    tiles = [(pyvista_crop(ren.one(name)), letter, text) for name, letter, text in spec]
    compose_row(tiles, 1, 3, (12.6, 4.75), out / "generator_families.png", top=0.91)


def fig_certified_print_meshes(ren: Finder, out: Path) -> None:
    """Watertight print meshes: woven release candidate and enamel (PRINTING.md, Figure 2)."""
    spec = [
        ("woven_fea_small_x20_smooth.png", "a", "Woven specimen ×2.0, remeshed (FDM PRINT)"),
        ("enamel_linear_x4_smooth.png", "b", "Enamel ×4, watertight remesh"),
    ]
    tiles = [(pyvista_crop(ren.one(name)), letter, text) for name, letter, text in spec]
    compose_row(tiles, 1, 2, (10.4, 5.0), out / "certified_print_meshes.png", top=0.91)


# Stress range of the rendered von Mises field [MPa]. Read from the element
# results of the same solve when that (large, optional) record is available;
# otherwise the documented extremes of that solve are used: 34,974 elements,
# minimum 0.000393 MPa, maximum 66.746 MPa, mean 4.465 MPa at 1 % strain.
VM_RANGE_FALLBACK = (0.000393, 66.746)


def von_mises_range(rec: Finder | None) -> tuple[float, float]:
    """(min, max) von Mises stress of the rendered tension solve [MPa]."""
    if rec is not None:
        try:
            cols = read_csv_columns(
                rec.one("element_results_tension.csv", hint=os.sep + "fea_tension" + os.sep)
            )
            return float(cols["von_mises_MPa"].min()), float(cols["von_mises_MPa"].max())
        except (FileNotFoundError, ValueError, KeyError):
            pass
    return VM_RANGE_FALLBACK


def fig_fea_plated_specimen(rec: Finder, ren: Finder, out: Path) -> None:
    """
    Plated voxel-hex specimen and its von Mises field (FEA.md, Figure 1). The
    stress render's own colorbar is replaced: its gradient strip is cut out and
    redrawn under panel (b) with clean tick labels, because the renderer printed
    the bar title over the middle tick label.
    """
    plated = pyvista_crop(ren.one("woven_fea_small_plated.png"))
    body, strip = split_colorbar(Image.open(ren.one("woven_fea_tension_stress.png")))
    body = pyvista_crop(body)
    plated, body = uniform_tiles([plated, body])
    vmin, vmax = von_mises_range(rec)

    fig = plt.figure(figsize=(9.6, 6.2), facecolor="white")
    ax_a = fig.add_axes([0.01, 0.13, 0.48, 0.79])
    ax_b = fig.add_axes([0.51, 0.13, 0.48, 0.79])
    ax_cb = fig.add_axes([0.60, 0.075, 0.30, 0.03])  # the redrawn colorbar
    for ax, img, letter, text in (
        (ax_a, plated, "a", "Plated voxel-hex mesh, 0.6 mm voxels"),
        (ax_b, body, "b", "von Mises stress at 1 % strain"),
    ):
        show_image(ax, img)
        panel_title(ax, letter, text)
    # The strip spans vmin (left) to vmax (right) linearly, as rendered.
    ax_cb.imshow(np.asarray(strip), extent=(vmin, vmax, 0, 1), aspect="auto")
    ax_cb.set_yticks([])
    ax_cb.grid(False)
    # Round ticks inside the range; the left end (vmin is a few 1e-4 MPa) reads as 0,
    # and the maximum is written beside the bar rather than as a crowded last tick.
    ticks = [vmin] + [t for t in (20, 40, 60) if vmin < t < vmax]
    ax_cb.set_xticks(ticks)
    ax_cb.set_xticklabels(["0"] + [f"{t:g}" for t in ticks[1:]])
    ax_cb.text(
        1.03,
        0.5,
        f"max {vmax:.1f}",
        transform=ax_cb.transAxes,
        ha="left",
        va="center",
        fontsize=9,
        color=INK_2,
    )
    ax_cb.set_xlabel("von Mises stress [MPa]", labelpad=3)
    for side in ax_cb.spines:
        ax_cb.spines[side].set_visible(False)
    save_png(fig, out / "fea_plated_specimen.png", dpi=170)


def select_loop_run(rec: Finder) -> tuple[Path, dict]:
    """
    The live loop run to illustrate: the first certified run whose critic rejected a design and
    approved a refined one (the full repair -> critique -> refine -> gate path), otherwise the
    first certified run. Returns (manifest path, manifest).
    """
    certified = []
    for path in sorted(rec.all("run_manifest.json")):
        m = json.load(open(path))
        if m.get("terminal_reason") == "certified":
            certified.append((path, m))
    if not certified:
        raise FileNotFoundError("no certified loop run among the run manifests")
    refined = [(p, m) for p, m in certified if (m.get("iteration_count") or 0) >= 1]
    return (refined or certified)[0]


def _tile_16x9(img: Image.Image) -> Image.Image:
    """Pad an image with white to 16:9, the aspect of the loop's own Blender renders."""
    w, h = img.size
    tw, th = (w, round(w * 9 / 16)) if h / w < 9 / 16 else (round(h * 16 / 9), h)
    canvas = Image.new("RGB", (tw, th), "white")
    canvas.paste(img, ((tw - w) // 2, (th - h) // 2))
    return canvas


def fig_agent_loop(rec: Finder, ren: Finder, out: Path) -> None:
    """
    One certified live run of the design loop (README; WORKFLOWS.md, Figure 1). Top: the
    loop's own Blender renders that the vision critic judged (a rejected design and the
    approved refinement when the run refined, else the approved repair). Bottom: the print
    gate's thin-material map on the approved geometry (brick = thinner than the 0.8 mm FDM
    strand) and on the certified, uniformly auto-scaled part. The maps are recomputed with the
    audit's own measure and must match the thin fraction the gate recorded; the caption
    numbers are read from the run manifest.
    """
    import pyvista as pv

    mpath, m = select_loop_run(rec)
    run = mpath.parent.name
    run_dir = ren.one("render_fix_run_2.png", hint=run).parent  # artifacts sit beside the renders
    deep = m["manufacturability"]["deep_audit"]
    variant = deep["autoscaled_variant"]
    vlm = m["vlm_analysis"]
    k = int(m.get("iteration_count") or 0)

    first = "Repaired script: rejected, partial match" if k else "Repaired script: approved"
    top = [(Image.open(run_dir / "render_fix_run_2.png").convert("RGB"), first)]
    if k:
        top.append(
            (
                Image.open(run_dir / f"render_design_iter_{k}.png").convert("RGB"),
                f"Refined design (iteration {k}): approved",
            )
        )

    # Thin-material maps: the approved geometry at the audit's recorded voxel size, then the
    # scaled variant at the audit's automatic voxel rule, max(0.12, largest extent / 320) [mm].
    lost_rec = float(deep["lost_frac_at_d"]["0.8"])
    mesh, flag, lost = fr.thin_material_map(run_dir / Path(deep["stl"]).name, 0.8, deep["voxel_mm"])
    if abs(lost - lost_rec) > 0.005:
        raise ValueError(f"thin map {lost:.4f} disagrees with the gate's record {lost_rec:.4f}")
    gate_img = fr.render_mesh(mesh, scalars=flag, clim=(0, 1), cmap=fr.BONE_THIN, zoom=1.0)
    scaled_path = run_dir / Path(variant["stl"]).name
    extent = float(np.ptp(np.asarray(pv.read(scaled_path).points), axis=0).max())
    smesh, sflag, slost = fr.thin_material_map(scaled_path, 0.8, max(0.12, extent / 320.0))
    cert_img = fr.render_mesh(smesh, scalars=sflag, clim=(0, 1), cmap=fr.BONE_THIN, zoom=1.0)
    bottom = [
        (gate_img, f"Print gate: {100 * lost_rec:.1f} % thinner than 0.8 mm"),
        (
            cert_img,
            f"Certified: ×{variant['scale']:g} ({extent:.0f} mm), {variant['verdict']}, "
            f"{100 * slost:.1f} % thin",
        ),
    ]

    ncols = max(len(top), len(bottom))
    fig, axes = render_figure(2, ncols, (5.4 * ncols, 6.9))
    fig.subplots_adjust(left=0.01, right=0.99, top=0.93, bottom=0.08, hspace=0.18, wspace=0.03)
    letters = iter("abcd")
    for row, tiles in enumerate((top, bottom)):
        for col in range(ncols):
            ax = axes[row][col]
            if col >= len(tiles):
                ax.set_axis_off()
                continue
            img, text = tiles[col]
            show_image(ax, _tile_16x9(img))
            panel_title(ax, next(letters), text)
    summary = (
        f"Repair: {m['fix_attempts_used']} fix attempts.   Critic: match {vlm['match_quality']}, "
        f"{vlm['physical_stability']}.   Print gate: uniform auto-scale ×{variant['scale']:g} → "
        f"{variant['verdict']} (certified strand {variant['max_formable_d_mm']:g} mm).   "
        "Brick marks material thinner than 0.8 mm."
    )
    fig.text(0.5, 0.025, summary, ha="center", va="center", fontsize=9.5, color=INK_2)
    save_png(fig, out / "agent_loop_convergence.png", dpi=170)


DAMAGE_LABEL = "Phase-field damage c   (0 intact, 1 fully cracked)"
ANIM_FPS = 12.0  # animation frame rate [frames/s]


def damage_panel(ax, grid, *, mirror: bool = False) -> None:
    """
    Draw the nodal damage field of a 2D phase-field run on the bone-to-oxblood ramp (Gouraud
    shading, exact at the nodes) inside a hairline specimen outline. `mirror` reflects a
    half model about its crack plane (y = 0) so the full specimen is shown.
    """
    t, c = fr.triangulation(grid, "c")
    c = c.clip(0.0, 1.0)
    style = dict(shading="gouraud", cmap=fr.BONE_RED, vmin=0.0, vmax=1.0, rasterized=True)
    ax.tripcolor(t, c, **style)
    x0, x1, y0, y1 = grid.bounds[:4]
    if mirror:
        ax.tripcolor(matplotlib.tri.Triangulation(t.x, -t.y, t.triangles), c, **style)
        y0 = -y1
    ax.plot([x0, x1, x1, x0, x0], [y0, y0, y1, y1, y0], color=fr.OUTLINE, lw=0.8)
    ax.set_xlim(x0 - 0.01 * (x1 - x0), x1 + 0.01 * (x1 - x0))
    ax.set_ylim(y0 - 0.01 * (y1 - y0), y1 + 0.01 * (y1 - y0))
    ax.set_aspect("equal")
    ax.set_axis_off()


def damage_colorbar(fig, rect: list[float]) -> None:
    """Horizontal colorbar for the damage ramp, frameless, in the secondary ink."""
    cax = fig.add_axes(rect)
    cb = fig.colorbar(
        plt.cm.ScalarMappable(matplotlib.colors.Normalize(0.0, 1.0), fr.BONE_RED),
        cax=cax,
        orientation="horizontal",
    )
    cb.outline.set_visible(False)
    cb.set_label(DAMAGE_LABEL, color=INK_2)
    cb.ax.tick_params(colors=INK_2, length=0)


def fig_crack_deflection(rec: Finder, sim: Finder, out: Path) -> None:
    """
    Final damage field of the full-model crack at 0/30/60/90 deg rod orientation (FRACTURE.md,
    Figure 2), rendered from the tm6_stageD.i runs D_a{angle}.e; panel titles carry the crack
    drift from the record.
    """
    drift = json.load(open(rec.one("tm6_stageD_result.json")))["deflection_drift_by_angle_deg"]
    fig = plt.figure(figsize=(12.8, 4.1), facecolor="white")
    for k, a in enumerate((0, 30, 60, 90)):
        ax = fig.add_axes([0.012 + 0.2475 * k, 0.22, 0.228, 0.66])
        damage_panel(ax, fr.read_exodus(sim.one(f"D_a{a}.e")))
        # '+g' keeps the record's precision (e.g. +0.005, -0.47); typographic minus sign.
        ax.set_title(f"{a}°  ·  drift {drift[str(a)]:+g}".replace("-", "−"), loc="center", pad=6)
    damage_colorbar(fig, [0.35, 0.1, 0.3, 0.035])
    save_png(fig, out / "crack_deflection_orientation.png", dpi=170)


def fig_bouligand_paths(rec: Finder, sim: Finder, out: Path) -> None:
    """
    Final damage field through the four Bouligand pitches (FRACTURE.md, Figure 3), rendered
    from the generated six-strip decks boul_d{pitch}.e. Ply-strip boundaries are dotted and
    each ply is labeled with its rod angle (the notch region is 0°); titles carry the tortuosity
    from the record.
    """
    boul = json.load(open(rec.one("tm6_bouligand_result.json")))
    fig = plt.figure(figsize=(13.6, 3.0), facecolor="white")
    for k, p in enumerate((10, 15, 20, 30)):
        ax = fig.add_axes([0.008 + 0.248 * k, 0.26, 0.236, 0.56])
        grid = fr.read_exodus(sim.one(f"boul_d{p}.e"))
        damage_panel(ax, grid)
        # Strip extents from the element blocks (one block per ply strip, left to right).
        centers = grid.cell_centers().points[:, 0]
        block = np.asarray(grid.cell_data["ObjectId"])
        spans = sorted(
            (centers[block == b].min(), centers[block == b].max()) for b in np.unique(block)
        )
        y0, y1 = grid.bounds[2:4]
        for j, (lo, hi) in enumerate(spans):
            if j:  # dotted boundary between strip j-1 and strip j
                edge = 0.5 * (spans[j - 1][1] + lo)
                ax.plot([edge, edge], [y0, y1], color=fr.OUTLINE, lw=0.7, ls=(0, (1, 2)))
            # Block 0 is the notch region (0 deg material); block k >= 1 is ply k at (k - 1) * pitch.
            ax.text(
                0.5 * (lo + hi),
                y1 + 0.03 * (y1 - y0),
                "notch" if j == 0 else f"{(j - 1) * p}°",
                ha="center",
                va="bottom",
                fontsize=7.5,
                color=INK_2,
            )
        ax.set_title(
            f"Δθ = {p}°/ply  ·  tortuosity {boul[str(p)]['tortuosity']:.2f}", loc="center", pad=16
        )
    damage_colorbar(fig, [0.35, 0.12, 0.3, 0.05])
    save_png(fig, out / "bouligand_crack_paths.png", dpi=170)


def fig_twist_slices(sim: Finder, out: Path) -> None:
    """
    Crack path y(x) of the 3D rotating-plywood block (FRACTURE.md, Figure 4), sliced at the
    mid-depth of each of its six ply slabs (ply angle k·30°), rendered from twist3d_long.e (the
    example deck run to end time 0.006, `Executioner/end_time=0.006`; at the shipped 0.004 the
    crack has barely advanced and has not yet snapped through the stack). The
    path in each slice is the column-wise damage maximum where the crack is fully developed
    (field_render.crack_path); depths are colored from light to dark through the stack.
    """
    grid = fr.read_exodus(sim.one("twist3d_long.e"))
    z0, z1 = grid.bounds[4:6]
    n_slabs = 6
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    fig.subplots_adjust(left=0.1, right=0.72, top=0.95, bottom=0.13)
    style_axes(ax)
    shades = fr.BONE_RED(np.linspace(0.38, 1.0, n_slabs))
    for k in range(n_slabs):
        z = z0 + (k + 0.5) * (z1 - z0) / n_slabs  # mid-depth of slab k
        path = fr.crack_path(grid.slice(normal="z", origin=(0.0, 0.0, z)), threshold=0.9)
        if len(path) >= 2:
            ax.plot(
                path[:, 0],
                path[:, 1],
                color=shades[k],
                lw=LINE_W,
                label=f"z = {z:.2f}  (ply {30 * k}°)",
            )
    ax.axhline(0.5, color=MUTED, lw=CONTEXT_W, ls=(0, (2, 2)), label="notch plane")
    ax.set_xlabel("x, along the crack (model units)")
    ax.set_ylabel("Crack position y (model units)")
    ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), title="Depth (ply angle)")
    save_png(fig, out / "crack_twist_through_thickness.png")


def _frame(fig) -> Image.Image:
    """Rasterize a matplotlib figure to an RGB image (one animation frame) and close it."""
    fig.canvas.draw()
    img = Image.fromarray(np.asarray(fig.canvas.buffer_rgba())).convert("RGB")
    plt.close(fig)
    return img


def _frame_steps(n: int, count: int) -> list[int]:
    """`count` time-step indices spread evenly over n stored steps, always ending on the last."""
    return sorted(set(np.linspace(0, n - 1, min(n, count)).round().astype(int).tolist()))


def _progress_steps(columns: list[np.ndarray], count: int) -> list[int]:
    """
    `count` step indices spaced evenly along the run's progress: the cumulative arc length of the
    normalized columns (e.g. displacement, force, mean damage). A crack that crosses the specimen
    within a few percent of the loading still gets most of the frames.
    """
    norm = [(c - c.min()) / (np.ptp(c) or 1.0) for c in columns]
    arc = np.concatenate([[0.0], np.cumsum(np.sqrt(sum(np.diff(c) ** 2 for c in norm)))])
    targets = np.linspace(0.0, arc[-1], count)
    return sorted(set(int(np.searchsorted(arc, t)) for t in targets) | {len(arc) - 1})


def gif_crack_propagation(sim: Finder, angle: int, path: Path) -> None:
    """
    Crack growth in the notched specimen at one rod angle (tm6_video.i run vid_a{angle}): left,
    the damage field of the half model mirrored about its crack plane, with the notch (a free
    boundary in this model, x < 0.5) drawn in; right, the load-displacement curve with the
    current state marked. Frames follow the run's progress, so the crack's advance is filmed.
    """
    import pyvista as pv

    exo = sim.one(f"vid_a{angle}.e")
    c = read_csv_columns(sim.one(f"vid_a{angle}.csv"))
    disp, force = np.asarray(c["top_disp"]), np.abs(np.asarray(c["reaction_y"]))
    times = np.asarray(c["time"])
    reader = pv.get_reader(str(exo))
    steps = _progress_steps([disp, force, np.asarray(c["crack_c"])], 72)
    frames = []
    for k in steps:
        i = int(np.argmin(np.abs(np.asarray(reader.time_values) - times[k])))  # Exodus step
        fig = plt.figure(figsize=(10.0, 4.2), facecolor="white")
        ax_f = fig.add_axes([0.03, 0.12, 0.38, 0.72])
        damage_panel(ax_f, fr.read_exodus(exo, i), mirror=True)
        ax_f.plot([0.0, 0.5], [0.0, 0.0], color=INK, lw=2.4, solid_capstyle="butt")  # the notch
        ax_f.text(0.25, 0.035, "notch", ha="center", va="bottom", fontsize=8.5, color=INK_2)
        cax = fig.add_axes([0.425, 0.2, 0.012, 0.56])
        cb = fig.colorbar(
            plt.cm.ScalarMappable(matplotlib.colors.Normalize(0.0, 1.0), fr.BONE_RED), cax=cax
        )
        cb.outline.set_visible(False)
        cb.ax.tick_params(labelsize=8, colors=INK_2, length=0)
        cb.set_label("damage c", fontsize=8.5, color=INK_2)
        ax_c = fig.add_axes([0.56, 0.2, 0.41, 0.62])
        style_axes(ax_c)
        ax_c.plot(disp * 1e3, force, color=BLUE, lw=LINE_W)
        ax_c.plot(
            disp[k] * 1e3,
            force[k],
            "o",
            color=fr.BONE_RED(1.0),
            ms=MARKER_S + 1,
            mec=SURFACE,
            mew=RING_W,
        )
        ax_c.set_xlabel("Applied displacement (×10⁻³, model units)")
        ax_c.set_ylabel("Reaction force (model units)")
        fig.suptitle(
            f"Crack growth with rods at {angle}° to the crack plane", x=0.03, ha="left", fontsize=11
        )
        frames.append(_frame(fig))
    frames += [frames[-1]] * int(1.5 * ANIM_FPS)  # hold the final state for 1.5 s
    fr.save_gif(frames, path, fps=ANIM_FPS)
    print(f"  wrote {path.name}  ({len(frames)} frames, {path.stat().st_size / 1024:.0f} KB)")


def gif_crack_deflection(sim: Finder, angle: int, path: Path) -> None:
    """Growth of the full-model crack in a rod field at `angle` (tm6_stageD.i run D_a{angle})."""
    exo = sim.one(f"D_a{angle}.e")
    frames = []
    for i in range(fr.exodus_steps(exo)):  # the adaptive run stores few steps: use them all
        fig = plt.figure(figsize=(4.6, 5.0), facecolor="white")
        ax = fig.add_axes([0.04, 0.2, 0.92, 0.7])
        damage_panel(ax, fr.read_exodus(exo, i))
        ax.set_title(f"Crack deflection, rods at {angle}°", loc="center", pad=8)
        damage_colorbar(fig, [0.12, 0.1, 0.76, 0.035])
        frames.append(_frame(fig))
    fps = 5.0  # slower than the long animations: each frame is a whole adaptive step
    fr.save_gif(frames + [frames[-1]] * int(2 * fps), path, fps=fps)  # hold the result for 2 s
    print(f"  wrote {path.name}  ({len(frames)} frames, {path.stat().st_size / 1024:.0f} KB)")


def gif_crack_3d(sim: Finder, path: Path, run: str = "D3d_long.e") -> None:
    """
    A 3D phase-field crack forming through the thickness (tm6_stageD_3d.i run to end time 0.02,
    `Executioner/end_time=0.02`, as D3d_long; the shipped 0.006 stops before propagation): the crack
    surface (damage isosurface c = 0.5) in oxblood inside a translucent bone block. The run stores
    few adaptive steps, so each step is shown for several frames while the camera orbits
    continuously (50 deg over the clip), and the final state is held before the loop restarts.
    """
    exo = sim.one(run)
    n_steps = fr.exodus_steps(exo)
    per_step = max(1, round(48 / n_steps))  # frames per stored step
    total = n_steps * per_step
    frames = []
    for i in range(n_steps):
        grid = fr.read_exodus(exo, i)
        surface = grid.contour([0.5], scalars="c")
        cx, cy, cz = grid.center

        def actors(pl, surface=surface, grid=grid):
            pl.add_mesh(grid.outline(), color=fr.OUTLINE, line_width=1.5)
            if surface.n_points:
                pl.add_mesh(surface, color=fr.BONE_RED(0.92), smooth_shading=True, specular=0.3)

        for j in range(per_step):
            # from -115 to -65 deg: the camera stays on the -y side, facing the x-z crack plane
            azim = np.deg2rad(-115 + 50 * (i * per_step + j) / max(total - 1, 1))
            camera = [
                (cx + 2.6 * np.cos(azim), cy + 2.6 * np.sin(azim), cz + 1.6),
                (cx, cy, cz),
                (0, 0, 1),
            ]
            frames.append(
                fr.render_mesh(
                    grid.extract_surface(),
                    color=fr.BONE,
                    camera=camera,
                    zoom=1.0,
                    size=(900, 760),
                    extra=actors,
                    opacity=0.18,
                    crop=False,
                )
            )
    frames += [frames[-1]] * int(1.5 * ANIM_FPS)  # hold the final state for 1.5 s
    fr.save_gif(frames, path, fps=ANIM_FPS)
    print(f"  wrote {path.name}  ({len(frames)} frames, {path.stat().st_size / 1024:.0f} KB)")


def make_gifs(sim: Finder, out: Path) -> None:
    """The four crack animations linked from FRACTURE.md, rendered from their Exodus runs."""
    gif_crack_propagation(sim, 45, out / "crack_propagation_45deg.gif")
    gif_crack_propagation(sim, 0, out / "crack_propagation_0deg.gif")
    gif_crack_deflection(sim, 60, out / "crack_deflection_60deg.gif")
    try:  # needs the long 3D run to have completed (FRACTURE.md §6); keep the file otherwise
        gif_crack_3d(sim, out / "crack_3d_formation.gif")
    except FileNotFoundError as exc:
        print(f"  kept crack_3d_formation.gif: {exc}")


def fig_woven_cell(rec: Finder, sim: Finder, out: Path) -> None:
    """
    The 3 x 3 non-fused woven cell, intact and with one warp fiber cut at its pulled grip
    (FRACTURE.md, Figure 5), rendered from the woven-cell deck's two Exodus results at the
    final load step. Both panels share one camera and one stress scale (0 to the larger of the
    two maxima). Fibers are outlined so the cut, unloaded warp stays distinct from the unloaded
    wefts that cross it. The retention in panel (b) is the ratio of the recorded pull forces.
    """
    intact = fr.read_exodus(sim.one("wcell3_intact_pre.e"))
    damaged = fr.read_exodus(sim.one("wcell3_dmg_pre.e"))
    # Axial stress per element; the -0.000 minimum is solver round-off, clipped to 0.
    fields = [np.asarray(g.cell_data["stress_xx"]).clip(min=0.0) for g in (intact, damaged)]
    clim = (0.0, float(max(f.max() for f in fields)))
    cx, cy, cz = intact.center  # both runs share the mesh, hence the view
    camera = [(cx - 16, cy - 30, cz + 20), (cx, cy, cz), (0, 0, 1)]  # from -y, -x, above
    imgs = uniform_tiles(
        [
            fr.render_mesh(
                g, scalars=f, clim=clim, outline=True, camera=camera, zoom=1.25, smooth=False
            )  # hexahedral fibers: flat faces read as square rods
            for g, f in zip((intact, damaged), fields)
        ]
    )
    force = {
        k: read_csv_columns(rec.one(f"wcell3_{k}_pre.csv"))["pull_force"][-1]
        for k in ("intact", "dmg")
    }
    retention = force["dmg"] / force["intact"]

    fig = plt.figure(figsize=(11.0, 5.0), facecolor="white")
    axes = [fig.add_axes([0.01, 0.17, 0.48, 0.72]), fig.add_axes([0.51, 0.17, 0.48, 0.72])]
    subtitles = (
        "all three warp fibers pulled along x",
        f"the cut fiber drops out: retention {retention:.3f} = (N − 1)/N",
    )
    for ax, img, (letter, text), sub in zip(
        axes,
        imgs,
        (("a", "Intact 3 × 3 cell"), ("b", "One warp fiber cut at its pulled grip")),
        subtitles,
    ):
        show_image(ax, img)
        ax.set_title(f"({letter}) {text}", pad=24)  # room for the subtitle line under it
        ax.text(0.0, 1.015, sub, transform=ax.transAxes, fontsize=9, color=INK_2, va="bottom")
    cax = fig.add_axes([0.33, 0.09, 0.34, 0.032])
    cb = fig.colorbar(
        plt.cm.ScalarMappable(matplotlib.colors.Normalize(*clim), fr.BONE_RED),
        cax=cax,
        orientation="horizontal",
    )
    cb.outline.set_visible(False)
    cb.set_label("Axial stress σ$_{xx}$ (MPa)", color=INK_2)
    cb.ax.tick_params(colors=INK_2, length=0)
    save_png(fig, out / "woven_cell_contact_stress.png", dpi=200)


def fig_readme_hero(sim: Finder, out: Path) -> None:
    """
    README hero image: the Tier-1 woven diamond lattice (`just woven diamond`) in the builder's
    own render style (bone, smooth shading, white ground, iso view), supersampled, without the
    axes triad, framed at about 4:3 and stored as a 256-color PNG (visually lossless here).
    """
    import pyvista as pv

    img = fr.render_mesh(pv.read(sim.one("woven_diamond.stl")), size=(2400, 1600), zoom=1.35)
    w, h = img.size
    height = int(h * 1.06)
    width = int(max(w * 1.04, height * 1.35))
    canvas = Image.new("RGB", (width, height), "white")
    canvas.paste(img, ((width - w) // 2, (height - h) // 2))
    canvas = canvas.resize((1800, round(1800 * height / width)), Image.LANCZOS)
    path = out / "readme_hero.png"
    canvas.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(
        path, optimize=True
    )
    print(
        f"  wrote {path.name}  ({canvas.size[0]}x{canvas.size[1]} px, "
        f"{path.stat().st_size / 1024:.0f} KB)"
    )


# =============================================================================
# 6. Driver
# =============================================================================
FIGURES = {
    # name: (function, the inputs it takes, in order): "rec" evidence records, "ren" existing
    # renders, "sim" simulation outputs and geometry (Exodus, STL) rendered here directly.
    "readme_hero": (fig_readme_hero, ("sim",)),
    "fracture_results": (fig_fracture_results, ("rec",)),
    "damage_tolerance_ranking": (fig_damage_tolerance, ("rec",)),
    "print_audit_thin_features": (fig_print_audit, ("rec",)),
    "woven_topologies": (fig_woven_topologies, ("ren",)),
    "generator_families": (fig_generator_families, ("ren",)),
    "certified_print_meshes": (fig_certified_print_meshes, ("ren",)),
    "fea_plated_specimen": (fig_fea_plated_specimen, ("rec", "ren")),
    "agent_loop_convergence": (fig_agent_loop, ("rec", "ren")),
    "crack_deflection_orientation": (fig_crack_deflection, ("rec", "sim")),
    "bouligand_crack_paths": (fig_bouligand_paths, ("rec", "sim")),
    "crack_twist_through_thickness": (fig_twist_slices, ("sim",)),
    "woven_cell_contact_stress": (fig_woven_cell, ("rec", "sim")),
    "gifs": (make_gifs, ("sim",)),
}


def main(argv: list[str] | None = None) -> int:
    default_records = "results" if Path("results").is_dir() else "out"
    ap = argparse.ArgumentParser(description="Regenerate the docs/figures set.")
    ap.add_argument(
        "--records",
        default=default_records,
        help="evidence-record root (default: results/ if present, else out/)",
    )
    ap.add_argument(
        "--renders",
        default=os.environ.get("ABCAD_OUT", "out"),
        help="render/animation root (default: $ABCAD_OUT or out/)",
    )
    ap.add_argument(
        "--sims",
        default=os.path.join(os.environ.get("ABCAD_OUT", "out"), "figure_sims"),
        help="simulation outputs and geometry root (default: $ABCAD_OUT/figure_sims)",
    )
    ap.add_argument("--out", default="docs/figures", help="output directory")
    ap.add_argument(
        "--only",
        action="append",
        choices=sorted(FIGURES),
        help="build only this figure (repeatable)",
    )
    a = ap.parse_args(argv)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rec = Finder(Path(a.records), (".json", ".csv", ".md"))
    ren = Finder(Path(a.renders), (".png", ".gif"))
    sim = Finder(Path(a.sims), (".e", ".stl", ".csv"))
    finders = {"rec": rec, "ren": ren, "sim": sim}
    print(f"records: {rec.root}   renders: {ren.root}   sims: {sim.root}   out: {out}")

    failures = 0
    for name in a.only or list(FIGURES):
        func, inputs = FIGURES[name]
        args = [finders[kind] for kind in inputs] + [out]
        print(f"[{name}]")
        try:
            func(*args)
        except FileNotFoundError as exc:  # missing inputs: skip, do not fail
            print(f"  skipped: {exc}")
        except Exception as exc:  # anything else is a real failure
            failures += 1
            print(f"  FAILED: {type(exc).__name__}: {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
