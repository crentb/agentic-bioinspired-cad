# Print-readiness audit — 2026-07-03 10:05

Processes graded: fdm, resin. Limits: FDM min feature 0.8 mm / overhang 15% / bed (220.0, 220.0, 250.0) mm; resin min feature 0.3 mm / vat (145.0, 145.0, 175.0) mm.

| part | bbox [mm] | vol [mL] | overhang | min formable Ø [mm] | fdm verdict | resin verdict |
|---|---|---|---|---|---|---|
| dt.stl | 57x57x8 | 13.869 | 45% | 0.3 | SCALE/REDESIGN | PRINT w/ fixes |
| h_solid.stl | 56x56x7 | 12.672 | 45% | 0.3 | SCALE/REDESIGN | PRINT |
| woven_bcc.stl | 86x86x86 | 3.74 | 15% | 0.3 | SCALE/REDESIGN | PRINT |
| woven_cubic.stl | 96x96x96 | 5.123 | 13% | 0.3 | SCALE/REDESIGN | PRINT |
| woven_cubic_blender.stl | 96x96x96 | 5.246 | 13% | 0.3 | SCALE/REDESIGN | PRINT |
| woven_diamond.stl | 86x86x86 | 6.491 | 15% | 0.3 | SCALE/REDESIGN | PRINT |
| woven_fea_small.stl | 29x29x29 | 3.893 | 14% | 0.3 | SCALE/REDESIGN | PRINT w/ fixes |
| woven_fea_test.stl | 37x37x37 | 4.993 | 14% | 0.3 | SCALE/REDESIGN | PRINT |
| woven_octahedron.stl | 91x92x92 | 5.655 | 15% | 0.3 | SCALE/REDESIGN | PRINT |
| ws.stl | 91x91x91 | 8.248 | 13% | 0.3 | SCALE/REDESIGN | PRINT |

## Per-part detail

### dt.stl

- bbox (56.57, 56.57, 8.02) mm, volume 13.869 mL (~15.3 g resin), 960 tris, watertight=True, manifold=True
- overhang(>45°, as-modeled) = 45.5%
- voxel 0.177 mm (grid 325x325x51); thinnest formable Ø = 0.3 mm; lost-material fractions {0.3: 0.0, 0.5: 0.1797, 0.8: 0.2335, 1.2: 0.307}
- near-structure narrow-gap fractions {0.3: 0.0, 0.5: 0.2742, 0.8: 0.3968}; enclosed voids: 6 (0.0 mL)
- **fdm → SCALE/REDESIGN** — issues: 23% of material thinner than 0.8 mm; overhang area 45% > 15% — fixes: scale up x0.4 (features formable at 0.3 mm) or thicken fibers; add breakaway supports or reorient (or print on resin); note: 40% of inter-fiber gaps < ~0.8 mm — expect local fiber fusion
- **resin → PRINT w/ fixes** — issues: 6 enclosed void(s), 0.0 mL trapped resin — fixes: add drain holes or reorient so voids vent

### h_solid.stl

- bbox (56.35, 56.35, 7.22) mm, volume 12.672 mL (~13.9 g resin), 432 tris, watertight=True, manifold=True
- overhang(>45°, as-modeled) = 45.3%
- voxel 0.176 mm (grid 326x326x47); thinnest formable Ø = 0.3 mm; lost-material fractions {0.3: 0.0, 0.5: 0.0744, 0.8: 0.158, 1.2: 0.207}
- near-structure narrow-gap fractions {0.3: 0.0, 0.5: 0.2599, 0.8: 0.4215}; enclosed voids: 0 (0.0 mL)
- **fdm → SCALE/REDESIGN** — issues: 16% of material thinner than 0.8 mm; overhang area 45% > 15% — fixes: scale up x0.4 (features formable at 0.3 mm) or thicken fibers; add breakaway supports or reorient (or print on resin); note: 42% of inter-fiber gaps < ~0.8 mm — expect local fiber fusion
- **resin → PRINT**

### woven_bcc.stl

- bbox (86.42, 86.42, 86.41) mm, volume 3.74 mL (~4.1 g resin), 154368 tris, watertight=True, manifold=True
- overhang(>45°, as-modeled) = 15.4%
- voxel 0.27 mm (grid 325x325x325); thinnest formable Ø = 0.3 mm; lost-material fractions {0.3: 0.0, 0.5: 0.0, 0.8: 0.9819, 1.2: 1.0}
- near-structure narrow-gap fractions {0.3: 0.0, 0.5: 0.0, 0.8: 0.0395}; enclosed voids: 0 (0.0 mL)
- **fdm → SCALE/REDESIGN** — issues: 98% of material thinner than 0.8 mm; overhang area 15% > 15% — fixes: scale up x0.4 (features formable at 0.3 mm) or thicken fibers; add breakaway supports or reorient (or print on resin)
- **resin → PRINT**

### woven_cubic.stl

- bbox (96.04, 96.04, 96.04) mm, volume 5.123 mL (~5.6 g resin), 193536 tris, watertight=True, manifold=True
- overhang(>45°, as-modeled) = 12.7%
- voxel 0.3 mm (grid 326x326x326); thinnest formable Ø = 0.3 mm; lost-material fractions {0.3: 0.0, 0.5: 0.0, 0.8: 0.2985, 1.2: 1.0}
- near-structure narrow-gap fractions {0.3: 0.0, 0.5: 0.0, 0.8: 0.0262}; enclosed voids: 0 (0.0 mL)
- **fdm → SCALE/REDESIGN** — issues: 30% of material thinner than 0.8 mm — fixes: scale up x0.4 (features formable at 0.3 mm) or thicken fibers
- **resin → PRINT**

### woven_cubic_blender.stl

- bbox (96.04, 96.04, 96.04) mm, volume 5.246 mL (~5.8 g resin), 257760 tris, watertight=True, manifold=True
- overhang(>45°, as-modeled) = 13.2%
- voxel 0.3 mm (grid 326x326x326); thinnest formable Ø = 0.3 mm; lost-material fractions {0.3: 0.0, 0.5: 0.0, 0.8: 0.2749, 1.2: 1.0}
- near-structure narrow-gap fractions {0.3: 0.0, 0.5: 0.0, 0.8: 0.0264}; enclosed voids: 0 (0.0 mL)
- **fdm → SCALE/REDESIGN** — issues: 27% of material thinner than 0.8 mm — fixes: scale up x0.4 (features formable at 0.3 mm) or thicken fibers
- **resin → PRINT**

### woven_diamond.stl

- bbox (86.25, 86.25, 86.25) mm, volume 6.491 mL (~7.1 g resin), 295776 tris, watertight=True, manifold=True
- overhang(>45°, as-modeled) = 15.2%
- voxel 0.27 mm (grid 325x325x325); thinnest formable Ø = 0.3 mm; lost-material fractions {0.3: 0.0, 0.5: 0.0, 0.8: 0.9504, 1.2: 1.0}
- near-structure narrow-gap fractions {0.3: 0.0, 0.5: 0.0, 0.8: 0.0593}; enclosed voids: 0 (0.0 mL)
- **fdm → SCALE/REDESIGN** — issues: 95% of material thinner than 0.8 mm; overhang area 15% > 15% — fixes: scale up x0.4 (features formable at 0.3 mm) or thicken fibers; add breakaway supports or reorient (or print on resin); note: 6% of inter-fiber gaps < ~0.8 mm — expect local fiber fusion
- **resin → PRINT**

### woven_fea_small.stl

- bbox (29.12, 29.12, 29.11) mm, volume 3.893 mL (~4.3 g resin), 27072 tris, watertight=True, manifold=True
- overhang(>45°, as-modeled) = 14.1%
- voxel 0.12 mm (grid 248x248x248); thinnest formable Ø = 0.3 mm; lost-material fractions {0.3: 0.0026, 0.5: 0.0082, 0.8: 0.017, 1.2: 0.016}
- near-structure narrow-gap fractions {0.3: 0.042, 0.5: 0.0862, 0.8: 0.1583}; enclosed voids: 728 (0.002 mL)
- **fdm → SCALE/REDESIGN** — issues: 2% of material thinner than 0.8 mm — fixes: scale up x0.4 (features formable at 0.3 mm) or thicken fibers; note: 16% of inter-fiber gaps < ~0.8 mm — expect local fiber fusion
- **resin → PRINT w/ fixes** — issues: 728 enclosed void(s), 0.002 mL trapped resin — fixes: add drain holes or reorient so voids vent

### woven_fea_test.stl

- bbox (37.37, 37.37, 37.37) mm, volume 4.993 mL (~5.5 g resin), 33408 tris, watertight=True, manifold=True
- overhang(>45°, as-modeled) = 14.2%
- voxel 0.12 mm (grid 317x317x317); thinnest formable Ø = 0.3 mm; lost-material fractions {0.3: 0.0026, 0.5: 0.0079, 0.8: 0.0153, 1.2: 0.0136}
- near-structure narrow-gap fractions {0.3: 0.0323, 0.5: 0.0712, 0.8: 0.1441}; enclosed voids: 0 (0.0 mL)
- **fdm → SCALE/REDESIGN** — issues: 2% of material thinner than 0.8 mm — fixes: scale up x0.4 (features formable at 0.3 mm) or thicken fibers; note: 14% of inter-fiber gaps < ~0.8 mm — expect local fiber fusion
- **resin → PRINT**

### woven_octahedron.stl

- bbox (91.44, 91.95, 91.95) mm, volume 5.655 mL (~6.2 g resin), 150912 tris, watertight=True, manifold=True
- overhang(>45°, as-modeled) = 14.5%
- voxel 0.287 mm (grid 324x325x325); thinnest formable Ø = 0.3 mm; lost-material fractions {0.3: 0.0, 0.5: 0.0, 0.8: 0.4024, 1.2: 1.0}
- near-structure narrow-gap fractions {0.3: 0.0, 0.5: 0.0, 0.8: 0.0352}; enclosed voids: 0 (0.0 mL)
- **fdm → SCALE/REDESIGN** — issues: 40% of material thinner than 0.8 mm — fixes: scale up x0.4 (features formable at 0.3 mm) or thicken fibers
- **resin → PRINT**

### ws.stl

- bbox (90.6, 90.6, 90.6) mm, volume 8.248 mL (~9.1 g resin), 171936 tris, watertight=True, manifold=True
- overhang(>45°, as-modeled) = 13.2%
- voxel 0.283 mm (grid 325x325x325); thinnest formable Ø = 0.3 mm; lost-material fractions {0.3: 0.0, 0.5: 0.0, 0.8: 0.1281, 1.2: 1.0}
- near-structure narrow-gap fractions {0.3: 0.0, 0.5: 0.0, 0.8: 0.0323}; enclosed voids: 0 (0.0 mL)
- **fdm → SCALE/REDESIGN** — issues: 13% of material thinner than 0.8 mm — fixes: scale up x0.4 (features formable at 0.3 mm) or thicken fibers
- **resin → PRINT**

## Method & caveats

- Wall thickness via morphological opening on a VTK image-stencil occupancy grid (erode+dilate by d/2 as EDT thresholds); a feature 'forms at d' if <=1% material is lost.
- Clearance = 2xEDT of the void, restricted to void within 3 mm of the structure.
- Self-intersection NOT tested (woven fibers intentionally weld; slicers union shells).
- Orientation as-modeled (+z up); overhang numbers move if printed tilted.
- Thickness statements are trustworthy down to ~2 voxels at the reported voxel size.