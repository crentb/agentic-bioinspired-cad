# Print-readiness audit — 2026-07-05 14:18

Processes graded: fdm. Limits: FDM min feature 0.8 mm / overhang 15% / bed (220.0, 220.0, 250.0) mm; resin min feature 0.3 mm / vat (145.0, 145.0, 175.0) mm.

| part | bbox [mm] | vol [mL] | overhang | max certified Ø [mm] | fdm verdict |
|---|---|---|---|---|---|
| bouligand_d10_w.stl | 36x36x23 | 9.09 | 22% | 0.3 | SCALE/REDESIGN |
| bouligand_d15_w.stl | 36x36x23 | 9.09 | 22% | 0.3 | SCALE/REDESIGN |
| bouligand_d20_w.stl | 36x36x23 | 9.09 | 22% | 0.3 | SCALE/REDESIGN |
| bouligand_d30_w.stl | 35x35x23 | 9.09 | 22% | 0.3 | SCALE/REDESIGN |

## Per-part detail

### bouligand_d10_w.stl

- bbox (35.6, 36.37, 22.8) mm, volume 9.09 mL (~10.0 g resin), 13888 tris, watertight=True, manifold=True
- overhang(>45°, as-modeled) = 22.4%
- voxel 0.12 mm (grid 302x309x196); max certified formable Ø = 0.3 mm; lost-material fractions {0.3: 0.0036, 0.5: 0.012, 0.8: 0.0261, 1.2: 0.0329}
- near-structure narrow-gap fractions {0.3: 0.1169, 0.5: 0.2237, 0.8: 0.3645}; enclosed voids: 2955 (0.008 mL)
- **fdm → SCALE/REDESIGN** — issues: 3% of material thinner than 0.8 mm; overhang area 22% > 15% — fixes: scale up x2.7 (features certified at 0.3 mm vs the 0.8 mm limit) or thicken fibers; add breakaway supports or reorient (or print on resin); note: 36% of inter-fiber gaps < ~0.8 mm — expect local fiber fusion

### bouligand_d15_w.stl

- bbox (35.64, 36.49, 22.8) mm, volume 9.09 mL (~10.0 g resin), 13888 tris, watertight=True, manifold=True
- overhang(>45°, as-modeled) = 22.4%
- voxel 0.12 mm (grid 302x310x196); max certified formable Ø = 0.3 mm; lost-material fractions {0.3: 0.0043, 0.5: 0.0142, 0.8: 0.0289, 1.2: 0.037}
- near-structure narrow-gap fractions {0.3: 0.105, 0.5: 0.1996, 0.8: 0.3297}; enclosed voids: 1620 (0.003 mL)
- **fdm → SCALE/REDESIGN** — issues: 3% of material thinner than 0.8 mm; overhang area 22% > 15% — fixes: scale up x2.7 (features certified at 0.3 mm vs the 0.8 mm limit) or thicken fibers; add breakaway supports or reorient (or print on resin); note: 33% of inter-fiber gaps < ~0.8 mm — expect local fiber fusion

### bouligand_d20_w.stl

- bbox (36.37, 36.32, 22.8) mm, volume 9.09 mL (~10.0 g resin), 13888 tris, watertight=True, manifold=True
- overhang(>45°, as-modeled) = 22.4%
- voxel 0.12 mm (grid 309x308x196); max certified formable Ø = 0.3 mm; lost-material fractions {0.3: 0.0042, 0.5: 0.0142, 0.8: 0.0296, 1.2: 0.0399}
- near-structure narrow-gap fractions {0.3: 0.0998, 0.5: 0.19, 0.8: 0.3185}; enclosed voids: 1291 (0.003 mL)
- **fdm → SCALE/REDESIGN** — issues: 3% of material thinner than 0.8 mm; overhang area 22% > 15% — fixes: scale up x2.7 (features certified at 0.3 mm vs the 0.8 mm limit) or thicken fibers; add breakaway supports or reorient (or print on resin); note: 32% of inter-fiber gaps < ~0.8 mm — expect local fiber fusion

### bouligand_d30_w.stl

- bbox (35.32, 35.32, 22.8) mm, volume 9.09 mL (~10.0 g resin), 13888 tris, watertight=True, manifold=True
- overhang(>45°, as-modeled) = 22.4%
- voxel 0.12 mm (grid 300x300x196); max certified formable Ø = 0.3 mm; lost-material fractions {0.3: 0.0036, 0.5: 0.0135, 0.8: 0.0257, 1.2: 0.034}
- near-structure narrow-gap fractions {0.3: 0.1048, 0.5: 0.2006, 0.8: 0.3362}; enclosed voids: 696 (0.005 mL)
- **fdm → SCALE/REDESIGN** — issues: 3% of material thinner than 0.8 mm; overhang area 22% > 15% — fixes: scale up x2.7 (features certified at 0.3 mm vs the 0.8 mm limit) or thicken fibers; add breakaway supports or reorient (or print on resin); note: 34% of inter-fiber gaps < ~0.8 mm — expect local fiber fusion

## Method & caveats

- Wall thickness via morphological opening on a VTK image-stencil occupancy grid (erode+dilate by d/2 as EDT thresholds); a feature 'forms at d' if <=1% material is lost.
- Clearance = 2xEDT of the void, restricted to void within 3 mm of the structure.
- Self-intersection NOT tested (woven fibers intentionally weld; slicers union shells).
- Orientation as-modeled (+z up); overhang numbers move if printed tilted.
- Thickness statements are trustworthy down to ~2 voxels at the reported voxel size.