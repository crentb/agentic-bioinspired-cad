# Enamel family: golden reference geometry

The enamel decussation generator,
[`abcad/generators/enamel.py`](../../abcad/generators/enamel.py), is a port of the CadQuery
continuous-twist decussated-lattice generator of the author's micro-CT enamel work. That CadQuery
generator is the **golden reference** for the architecture; a version of it is published as
`geometry/lattice_cad.py` in the companion repository
[biomimetic-lattice-pipeline](https://github.com/crentb/biomimetic-lattice-pipeline). Its exported
solids (a unified STL of about 137 MB and a compound STEP of about 34 MB) serve as visual and
geometric validation targets. They are not tracked in this repository: they are too large to
vendor and too heavy for the voxel-based instruments.

## 1. What is ported

| Feature | Golden (CadQuery) | Port (`abcad`) |
|---|---|---|
| Packing | Concentric hexagonal rings around a center rod | Same: ring k holds 6k rods at radius k·spacing; N rings contain 1 + 3N(N + 1) rods |
| Decussation | Per-ring total rotation with alternating sign between neighbors | Same default profile, (0, +10, −20, +30, −45, +60)° for rings 0–5 |
| Twist laws | Linear, accelerating, sigmoid | Same three laws: u·Δθ, u²·Δθ, and a logistic S(u)·Δθ normalized to S(0) = 0, S(1) = 1 (u = z/H) |
| Interrod bridges | Struts between adjacent rods of a ring at several heights | Same, anchored on the rod surfaces at the rods' twisted positions; bridge diameter must be smaller than the rod diameter |
| Scale | Dimensions fixed in the exported models | Unit-scale defaults (rod Ø 0.5 mm, spacing 0.6 mm, height 5.0 mm) with a uniform `--scale`; ×4 gives Ø 2.0 mm rods, 2.4 mm spacing, 20 mm height |
| Solid realization | OCCT Boolean union into one solid | Rods and bridges swept as coexisting tube shells with the woven family's numpy-stl mesher; the voxel-based instruments union them implicitly |
| Material | Single phase (two-phase soft/stiff variants of the source project are excluded) | Single phase |

The change of solid realization is deliberate: unioning about a hundred helical rods and hundreds of
bridges in an OCCT kernel is slow and memory-hungry, and the resulting exports are far larger than
the voxelizers need. The port therefore validates the **architecture**, not the byte-level solid.

## 2. Port-fidelity checks

Blender- and CAD-free unit tests (`tests/`) assert the port against the CadQuery parameters:

- hexagonal ring counts: ring k holds exactly 6k rods, and N rings hold 1 + 3N(N + 1) rods
  (N = 0, 1, 3, 5);
- ring radius: every rod of ring k lies at radius k·spacing;
- twist-law end points: all three laws give zero twist at z = 0 and the full Δθ at z = H; at
  mid-height the accelerating law lags the linear one and the sigmoid equals half of Δθ;
- decussation: the default profile flips twist sign between neighboring rings at least three
  times;
- rod centerlines: `z_samples` points at constant radius, reaching the full twist at the top; the
  center rod is a straight axial segment;
- bridges: the count equals Σ 6k × `n_bridge_layers` (720 for the defaults), and none are produced
  when bridges are disabled.

A mesh-level comparison against the exported golden solid (for example a Hausdorff distance after
aligning both at ×4) has not been recorded.

## 3. Grounding in measured enamel

The golden generator belongs to a micro-CT pipeline that tracks individual enamel rods and reports
per-rod instantaneous angles and yaw/pitch statistics. Those measured angle distributions are the
intended source for grounding the ring rotations and the choice of twist law in measured tissue;
the default rotation profile above is the reference design, not a fit to a specimen.

## 4. Status of the ported family

| Test method | Result | Where |
|---|---|---|
| TM-1 / TM-2 print audit | ×4 linear lattice as swept: not watertight (open tube shells), 19.8 % of material thinner than 0.8 mm; watertight solid remesh produced (1,022,332 triangles), certification pending | [PRINTING.md §5.4](../PRINTING.md) |
| TM-3 damage tolerance (0.5 mm) | E_eff ≈ 1096–1121 MPa; floor margin −0.0098 (sigmoid), −0.0109 (linear), −0.0111 (accelerating): ranks with the solid controls; the twist law makes no TM-3 difference | [FEA.md §5](../FEA.md) |
| TM-6 fracture | Not yet run on enamel geometry; the orientation, deflection, and ply-twist studies establish the mechanism the twist law is meant to shape | [FRACTURE.md](../FRACTURE.md) |
