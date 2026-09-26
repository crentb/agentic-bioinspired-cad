# Print-readiness audit — 2026-07-05 16:22

Processes graded: fdm. Limits: FDM min feature 0.8 mm / overhang 15% / bed (220.0, 220.0, 250.0) mm; resin min feature 0.3 mm / vat (145.0, 145.0, 175.0) mm.

| part | bbox [mm] | vol [mL] | overhang | max certified Ø [mm] | fdm verdict |
|---|---|---|---|---|---|
| enamel_linear_x4.stl | 26x26x21 | 7.197 | 7% | None | SCALE/REDESIGN |

## Per-part detail

### enamel_linear_x4.stl

- bbox (25.95, 26.0, 21.06) mm, volume 7.197 mL (~7.9 g resin), 101280 tris, watertight=False, manifold=False
- overhang(>45°, as-modeled) = 6.9%
- voxel 0.12 mm (grid 222x222x181); max certified formable Ø = None mm; lost-material fractions {0.3: 0.0427, 0.5: 0.0973, 0.8: 0.1983, 1.2: 0.3175}
- near-structure narrow-gap fractions {0.3: 0.1978, 0.5: 0.3855, 0.8: 0.5979}; enclosed voids: 28 (0.0 mL)
- **fdm → SCALE/REDESIGN** — issues: mesh not watertight; 20% of material thinner than 0.8 mm — fixes: repair the mesh before slicing (open surface); features thinner than the whole test ladder — redesign/thicken; note: 60% of inter-fiber gaps < ~0.8 mm — expect local fiber fusion

## Method & caveats

- Wall thickness via morphological opening on a VTK image-stencil occupancy grid (erode+dilate by d/2 as EDT thresholds); a feature 'forms at d' if <=1% material is lost.
- Clearance = 2xEDT of the void, restricted to void within 3 mm of the structure.
- Self-intersection NOT tested (woven fibers intentionally weld; slicers union shells).
- Orientation as-modeled (+z up); overhang numbers move if printed tilted.
- Thickness statements are trustworthy down to ~2 voxels at the reported voxel size.