# Non-fused woven CELL — damage-tolerance retention (TM-6 contact track)

> **Erratum (2026-09-25).** The numbers below are unchanged; two interpretations are corrected.
> (1) Orientation sweep: the 1.67× "work of fracture" at 45° is the area to a common displacement
> that closes before the 0°/90° specimens reach peak load, and no run propagates a crack, so the
> ratio tracks the 1.81× higher initial stiffness at 45°; energy absorbed to peak is 0.98×. It is
> not evidence of crack-twisting toughening. (2) Weak interfaces: the 0.55× work-to-common-displacement
> ratio understates the penalty; at equal initial stiffness the non-fused specimen reaches 0.32× the
> peak load, 0.16× the energy to peak and 0.10× the total work. See docs/FRACTURE.md.

**Question:** does a *non-fused* woven cell — separate fibers coupled only by frictional
crossings — shed the load of a severed fiber to its neighbours (graceful redundancy), unlike the *fused*
woven cube whose voxel-weld makes fibers monolithic (TM-3 floor-margin −0.046, the sole real outlier)?

**Model:** `abcad/fracture/tm6_make_woven_cell_deck.py`. N warp fibers along x (bottom layer,
gripped both ends, pulled 0.02 mm) + N weft fibers along y (top layer, pressed down `preload` mm to
engage friction), each a separate body, Coulomb penalty contact (μ=0.3) at every warp/weft crossing.
PLA (E=3500 MPa, ν=0.36), small strain, mm/MPa. NEWTON + superlu_dist + automatic_scaling, staged
loading (weft preload seats over t∈[0,0.25]; warp pull ramps over t∈[0.25,1.0]). Swap-guarded
(peak 754 MB — negligible). **Flaw = free one warp fiber's pulled grip** ("cut"): it carries no applied
tension but stays anchored at the left and can be dragged by weft friction.

## Result — retention lands EXACTLY on the geometric (N−1)/N

| cell | crossings | intact F (N) | damaged F (N) | retention | geometric (N−1)/N |
|---|---|---|---|---|---|
| 2×2 (cut 1 of 2) | 4 | 52.41 | 26.21 | **0.500** | 0.500 |
| 3×3 (cut 1 of 3) | 9 | 59.33 | 39.55 | **0.667** | 0.667 |

Sensitivity check (2×2): retention = 0.500 **whether or not** the crossings are frictionally preloaded
(no-preload damaged ≈ 26.2 N; preload 0.05 mm damaged = 26.2 N). The intact force is likewise
preload-independent (52.41 N either way) — in an intact cell all warps move together, so there is **no
relative slip** at the crossings and friction is inert.

## Interpretation — the frictional crossings give NO linear-stiffness redundancy

A cut fiber simply **drops out**: it carries ~0 axial stress and the remaining N−1 warps carry the same
per-fiber load as before. See `wcell2_compare.png` / `wcell3_compare.png` — the cut warp0 goes dark
(near-zero `stress_xx`) while its neighbours stay fully loaded. Friction cannot transfer a parallel
fiber's *axial* load to another parallel fiber in a flat plain-weave at small strain.

**This is the expected, project-consistent answer, not a failure.** It confirms — a third time, now with a
contact model — that non-fused woven damage tolerance is **not a linear-stiffness phenomenon** (TM-3 is
blind to it), the same lesson the enamel twist-law and Bouligand pitch-band delivered. The woven
toughening the literature reports (Carton/Surjadi/Aymon/Portela, *Nat. Commun.* 2026: entangled fibers,
frictional sliding, stretch up to 4, **programmable failure patterns**) lives in the **large-deformation /
fracture regime** — fiber straightening, entanglement locking, and sliding that blunts stress
concentrations. Capturing it requires a **failure simulation** (finite strain + contact to large stretch,
or contact + phase-field crack), not a small-strain stiffness screen. That is the next build.

## Files
- Decks (not archived; emitted by `abcad/fracture/tm6_make_woven_cell_deck.py`): `wcell{2,3}_{intact,dmg}_pre.i`
- Exodus (binary, not archived): `wcell{2,3}_{intact,dmg}_pre.e` · CSV (this directory): `wcell{2,3}_{intact,dmg}_pre.csv`
- Figures (not archived; re-render from the Exodus files): `wcell2_compare.png`, `wcell3_compare.png` · Video: `wcell2_dmg_video.mp4`
- Renderer: `abcad/fracture/tm6_render_woven_cell.py`

---

# FAILURE / FRACTURE simulation — where the woven toughening actually lives

Since the retention study showed the toughening is a fracture-regime effect, the failure track uses
phase-field fracture (`tm6_make_woven_fracture_deck.py`, built on the validated `tm6_stageD.i`: NEWTON +
VI bounded solver + IterationAdaptiveDT, PLANE_STRAIN, brittle AT2). Notched unit square, mode I. Two
idealizations of the non-fused architecture were tested against the fused (uniform) control, and paired
with the already-validated anisotropy route:

**(A) Weak-interface fracture — the CAUTIONARY result.** Non-fused = weak fracture-toughness interfaces
(Gc_low = Gc_high/10) representing delaminating/sliding crossings. Result: whether the interfaces are
transverse to the crack or parallel-and-offset (Cook–Gordon geometry), the crack exploits them as an
easy DELAMINATION path and fails EARLY:

| mode | peak load | work-to-common-disp | vs fused |
|---|---|---|---|
| fused (uniform Gc) | 0.458 | 1.19e-3 | 1.00× |
| non-fused (weak interfaces) | 0.145 | 6.60e-4 | **0.55×** |

**Weak interfaces alone do NOT toughen — they lower strength via delamination.** (Both cracks also
branch symmetrically under the isotropic snap-through — `wfrac2_crack.png` — because isotropy gives the
bifurcation no preferred direction.) This is a real materials-optimization lesson: non-fused toughening
is architecture-specific, not automatic.

**(B) Crack-deflection by ORIENTED anisotropy — the TOUGHENING result (validated, `results/fracture/`).** When the
architecture ORIENTS the material off-axis (the decussation / Bouligand / woven-ply lever), the crack is
forced to KINK toward the weak plane — deflection lengthens the path and dissipates more energy:

| rod angle | 0°/90° (aligned, straight crack) | 45° (max off-axis, deflected crack) |
|---|---|---|
| work of fracture | 2.69e-4 | **4.48e-4 (1.67×)** |
| peak load | 0.233 | 0.307 (1.32×) |

**Synthesis:** non-fused / woven damage tolerance = crack **DEFLECTION driven by oriented architecture**
(anisotropy, tortuosity), NOT weak interfaces or frictional sliding per se — those, misused, just
delaminate. To make weak interfaces toughen you must FORCE tortuosity (staggered nacre brick-wall) or
couple contact-friction to the crack (heavier future work). The validated toughening lever we already
have is ply orientation (peaks 45° / 1.67×; Bouligand pitch tortuosity peaks 15°/ply).

## Fracture files
- Generator: `abcad/fracture/tm6_make_woven_fracture_deck.py` (fused|nonfused) · compare:
  `abcad/fracture/tm6_fracture_compare.py`
- `wfrac2_crack.png` (crack paths), `wfrac2_curve.png` (reaction–disp + work), `wfrac2_fused.csv`,
  `wfrac2_nonfused.csv` · anisotropy evidence: `results/fracture/orientation_sweep/tm6_a{0..90}.csv`
