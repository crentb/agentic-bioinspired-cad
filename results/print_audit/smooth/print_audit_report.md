# Print-readiness audit — 2026-07-05 12:36

Processes graded: fdm. Limits: FDM min feature 0.8 mm / overhang 15% / bed (220.0, 220.0, 250.0) mm; resin min feature 0.3 mm / vat (145.0, 145.0, 175.0) mm.

| part | bbox [mm] | vol [mL] | overhang | max certified Ø [mm] | fdm verdict |
|---|---|---|---|---|---|
| woven_fea_small_x20_smooth.stl | 58x58x58 | 31.047 | 13% | 1.2 | PRINT |

## Per-part detail

### woven_fea_small_x20_smooth.stl

- bbox (57.69, 57.69, 57.7) mm, volume 31.047 mL (~34.2 g resin), 555622 tris, watertight=True, manifold=True
- overhang(>45°, as-modeled) = 13.4%
- voxel 0.18 mm (grid 325x325x326); max certified formable Ø = 1.2 mm; lost-material fractions {0.3: 0.0, 0.5: 0.0005, 0.8: 0.0017, 1.2: 0.0032}
- near-structure narrow-gap fractions {0.3: 0.0, 0.5: 0.0493, 0.8: 0.1058}; enclosed voids: 0 (0.0 mL)
- **fdm → PRINT** — fixes: note: 11% of inter-fiber gaps < ~0.8 mm — expect local fiber fusion

## Method & caveats

- Wall thickness via morphological opening on a VTK image-stencil occupancy grid (erode+dilate by d/2 as EDT thresholds); a feature 'forms at d' if <=1% material is lost.
- Clearance = 2xEDT of the void, restricted to void within 3 mm of the structure.
- Self-intersection NOT tested (woven fibers intentionally weld; slicers union shells).
- Orientation as-modeled (+z up); overhang numbers move if printed tilted.
- Thickness statements are trustworthy down to ~2 voxels at the reported voxel size.