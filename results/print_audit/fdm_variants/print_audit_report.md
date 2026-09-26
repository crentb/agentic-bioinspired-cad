# Print-readiness audit — 2026-07-03 10:10

Processes graded: fdm, resin. Limits: FDM min feature 0.8 mm / overhang 15% / bed (220.0, 220.0, 250.0) mm; resin min feature 0.3 mm / vat (145.0, 145.0, 175.0) mm.

| part | bbox [mm] | vol [mL] | overhang | min formable Ø [mm] | fdm verdict | resin verdict |
|---|---|---|---|---|---|---|
| woven_fea_small_x15.stl | 44x44x44 | 13.138 | 14% | 0.3 | PRINT | PRINT w/ fixes |
| woven_fea_small_x20.stl | 58x58x58 | 31.142 | 14% | 0.3 | PRINT | PRINT w/ fixes |
| woven_fea_small_x20_plated.stl | 58x58x63 | 58.278 | 17% | 0.3 | PRINT w/ fixes | PRINT w/ fixes |

## Per-part detail

### woven_fea_small_x15.stl

- bbox (43.68, 43.68, 43.66) mm, volume 13.138 mL (~14.5 g resin), 27072 tris, watertight=True, manifold=True
- overhang(>45°, as-modeled) = 14.2%
- voxel 0.137 mm (grid 325x325x325); thinnest formable Ø = 0.3 mm; lost-material fractions {0.3: 0.0016, 0.5: 0.0043, 0.8: 0.0099, 1.2: 0.0145}
- near-structure narrow-gap fractions {0.3: 0.0439, 0.5: 0.0823, 0.8: 0.1366}; enclosed voids: 877 (0.005 mL)
- **fdm → PRINT** — fixes: note: 14% of inter-fiber gaps < ~0.8 mm — expect local fiber fusion
- **resin → PRINT w/ fixes** — issues: 877 enclosed void(s), 0.005 mL trapped resin — fixes: add drain holes or reorient so voids vent

### woven_fea_small_x20.stl

- bbox (58.24, 58.24, 58.22) mm, volume 31.142 mL (~34.3 g resin), 27072 tris, watertight=True, manifold=True
- overhang(>45°, as-modeled) = 14.2%
- voxel 0.182 mm (grid 325x325x325); thinnest formable Ø = 0.3 mm; lost-material fractions {0.3: 0.0, 0.5: 0.0016, 0.8: 0.005, 1.2: 0.0088}
- near-structure narrow-gap fractions {0.3: 0.0, 0.5: 0.0559, 0.8: 0.1141}; enclosed voids: 877 (0.012 mL)
- **fdm → PRINT** — fixes: note: 11% of inter-fiber gaps < ~0.8 mm — expect local fiber fusion
- **resin → PRINT w/ fixes** — issues: 877 enclosed void(s), 0.012 mL trapped resin — fixes: add drain holes or reorient so voids vent

### woven_fea_small_x20_plated.stl

- bbox (58.24, 58.24, 63.02) mm, volume 58.278 mL (~64.1 g resin), 27096 tris, watertight=True, manifold=True
- overhang(>45°, as-modeled) = 16.7%
- voxel 0.197 mm (grid 301x301x325); thinnest formable Ø = 0.3 mm; lost-material fractions {0.3: 0.0, 0.5: 0.0017, 0.8: 0.005, 1.2: 0.0089}
- near-structure narrow-gap fractions {0.3: 0.0, 0.5: 0.0841, 0.8: 0.1701}; enclosed voids: 821 (0.131 mL)
- **fdm → PRINT w/ fixes** — issues: overhang area 17% > 15% — fixes: add breakaway supports or reorient (or print on resin); note: 17% of inter-fiber gaps < ~0.8 mm — expect local fiber fusion
- **resin → PRINT w/ fixes** — issues: 821 enclosed void(s), 0.131 mL trapped resin — fixes: add drain holes or reorient so voids vent

## Method & caveats

- Wall thickness via morphological opening on a VTK image-stencil occupancy grid (erode+dilate by d/2 as EDT thresholds); a feature 'forms at d' if <=1% material is lost.
- Clearance = 2xEDT of the void, restricted to void within 3 mm of the structure.
- Self-intersection NOT tested (woven fibers intentionally weld; slicers union shells).
- Orientation as-modeled (+z up); overhang numbers move if printed tilted.
- Thickness statements are trustworthy down to ~2 voxels at the reported voxel size.