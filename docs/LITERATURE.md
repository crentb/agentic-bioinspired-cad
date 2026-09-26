# Literature foundation

This document distills the published science behind the three single-material architecture
families implemented in `abcad`: helicoidal (Bouligand) laminates, woven lattices, and
enamel-decussation rod lattices. It also records one cautionary two-material study whose
toughness numbers must not be transferred. Page, figure, table, and reference numbers refer to
the cited sources; quantities are reproduced as published. Numbered citations in square brackets
point to the reference list at the end; "[1, ref. 156]" means reference 156 inside source [1].

**Design constraint used throughout.** Every part is printed in **one material**. All mechanical
function must come from geometry and topology (fiber entanglement, rotating weak planes, crack
deflection), never from a hard/soft modulus contrast. Mechanisms that require a stiffness contrast
are identified below and excluded from the design rules.

---

## 1. Helicoidal (Bouligand) architectures — Ning et al. [1]

Natural exemplars reviewed in [1]: the shrimp and mantis-shrimp dactyl club, lobster claw, crab
shell, scorpion pincer, beetle cuticle, and fish scale (*Arapaima*, carp). "Bouligand" denotes the
twisted-plywood arrangement first described by Bouligand in crustacean cuticle.

### 1.1 Parameterization (p. 2; Fig. 16, p. 14)

| Symbol | Name (synonyms) | Definition | Relation |
|---|---|---|---|
| p | Pitch (periodicity, spacing) | Through-thickness distance for one **180° (π)** rotation of the fiber director | — |
| d | Ply thickness (inter-ply spacing) | Thickness of one unidirectional ply | — |
| n | Plies per pitch | — | n = p/d |
| γ ≡ θ | Pitch angle (rotation or twist angle) | Angle between adjacent plies | θ = π/n (constant pitch) |

Conventions: one pitch is a rotation of π (180°), not 2π, because the director is a headless axial
vector (a ply at θ is identical to a ply at θ + 180°). Published studies stack from one pitch
(180°) up to many (360°, 540°, 720°, 1080°, 1440°, 3240°).

**Generative recipe (constant pitch).** Choose Δθ, so n = 180°/Δθ; for m pitches the stack has
N = m·n plies. Ply k has orientation θ_k = k·Δθ (mod 180°) and occupies z ∈ [k·d, (k+1)·d]. The
continuous director field is θ(z) = θ₀ + (π/p)·z.

**Grading.** Natural helicoids are graded: the pitch angle typically increases from the impact
surface inward (dactyl club ≈ 1.6° → 6.2°). The resulting design rule [1, ref. 33] is a small
angle at the loading surface and a large angle in the interior.

### 1.2 Rotation-progression variants

| Variant | Inter-ply rule | Reported effect |
|---|---|---|
| Linear / constant | Δθ_k = Δθ | Baseline and most studied; outperforms quasi-isotropic (QI) and cross-ply layups out of plane and under impact. |
| Nonlinear / variable | Δθ_k monotonic (often increasing inward) | Fewer damaged plies; damaged-ply count decreases as the angle increases; redirects cracks [1, ref. 93]. |
| Sine angle | Δθ_k sinusoidal in k [1, ref. 217] | More tortuous crack path. |
| Exponential | Δθ_k = Δθ₀·r^k [1, ref. 217] | Higher crack tortuosity. |
| Fibonacci | Increments follow the Fibonacci series; realized aramid layup (0/10/10/20/30/50/80/130/210/340/190/170/360/170/170/340)ₛ | For tough fibers, helicoids minimize damage and preserve residual strength rather than absorb energy [1, ref. 147]. |
| Sinusoidal geometry | Plies laid on a wavy (sine) surface, herringbone-like | +28.4 % flexural strength and +36.9 % modulus over a plain helicoid (basalt/cyanate); best modeled impact response. |
| Herringbone–Bouligand | Alternating ± twist sense (chevron) | Delays delamination onset, contains damage, mitigates stress waves. |
| Double-twisted (double helicoid) | Two interleaved helicoids, each ply twisted; coelacanth-inspired; modeled pitch set 30/15/10/5° [1, ref. 65] | Tougher than a single helicoid in phase-field models [1, ref. 52]; specific energy absorption +122.5 % over a single helicoid (carbon fiber, Charpy). The toughest variant reported. |
| Twisted helicoidal | Adds an out-of-plane lamella tilt ∅_k (scorpion pincer) [1, ref. 8] | Additional stiffness and toughness at the cost of flexibility; modified ABD matrices (Eqs. 8–10, p. 39). |

### 1.3 Reported values

- **Natural pitch angles:** carp scale 36° (5 orientations); *Scarabaei* beetle 22–28°; figeater
  beetle 12–18°; dactyl-club gradient ≈ 1.6° → 6.2°. Pitch lengths: figeater beetle ≈ 220 nm;
  dactyl club ≈ 75 µm. Ply thickness 2–50 µm; exo- plus endocuticle thickness < 2 mm.
- **Pitch angles used in bio-inspired studies (Table 3):** 2.5, 3.75, 5, 5.625, 6, 6.43, 7.5, 7.8,
  9, 9.1, 9.47, 10, 11.25, 12, 13.3, 15, 16.3/16.36/16.4, 18, 20, 22.5, 24, 25, 25.7, 30, 36, 45°.
- **The "optimal pitch" is contested:** 2.5° (diffused sub-critical delamination; impact
  performance rises as pitch falls over 2.5/5/10/20/45°) [1, ref. 156]; 9.1° (best load bearing
  among 6/9.1/12/25.7°) [1, ref. 139]; ≈ 5–10° (below this range matrix splitting degrades
  performance) [1, ref. 165]; 12° (maximum energy absorption) [1, ref. 152]; 25.7° (impact, carbon
  fiber) [1, ref. 34]; ≤ 10° (numerical, most favorable stress distribution) [1, ref. 135].
- **Performance deltas:** helicoids ≈ 8 % above cross-ply and ≈ 15 % above QI layups in impact
  [1, ref. 163]; residual compressive strength up to +60 % over QI [1, ref. 143]; double helicoid
  specific energy absorption +122.5 %.
- **Generator defaults derived from these values:** Δθ = 7.8–10° (n ≈ 18–23) as the robust
  choice; 2.5–5° for maximum twisting and damage spreading; 15–36° for large-amplitude,
  easy-to-print coupons. Ply thickness d ≈ the printed layer height (0.1–0.3 mm) and p = n·d.
  Graded stacks use a small γ at the loading face and a large γ inside. The double helicoid is the
  choice for maximum toughness.

### 1.4 Additive manufacturing and single-material realization (pp. 26, 31)

Continuous-fiber helicoids are mostly produced by autoclave, hot press, vacuum-assisted resin
transfer molding, or hand layup; discontinuous-fiber helicoids are "typically additively
manufactured". Methods that encode the fiber orientation:

| Additive method | How the orientation is encoded | Material | Desktop |
|---|---|---|---|
| PolyJet multi-material | Stiff/soft per-layer pattern rotated by Δθ | Hard + soft photopolymer | Laboratory |
| FDM, short carbon fiber | Shear flow aligns short fibers along the toolpath; raster rotated Δθ per layer | Short-fiber filament | Yes |
| FDM, liquid-crystal polymer (LCP) | Nozzle aligns LCP domains along the toolpath | Single LCP filament | Yes |
| FDM, continuous fiber | Continuous Kevlar or glass tow on a programmed path (e.g. 16.3° pitch, Fig. 35) | Tow + thermoplastic | Yes |
| 3D magnetic printing | Field orients platelets or fibers per layer, then DLP cure | Filler + resin | Specialized |
| SLM / SEBM metal | Printed Ti-6Al-4V helicoidal scaffold (15°) | Metal | No |
| Colloidal / cellulose-nanocrystal self-assembly | Field or evaporation sets the pitch | Nanocrystal films | Laboratory |

**Single-material evidence.** [1] (p. 31, ref. 203) reports that "even one type of material can be
used": 3D-printed PLA helicoidal composites with pitch angles from 5° to 45° improve out-of-plane
and impact performance. Single-material printed steel-fiber concrete helicoids at 15° and 30°
(Fig. 33) and short-carbon-fiber PEEK (finite-element study) are also reported.

Single-material encoding options:

1. per-layer raster (toolpath) direction = θ_k, so that bead anisotropy acts as the "fiber";
2. modeled geometric weak planes — grooves, ridges, voids, or discrete fibers rotating by Δθ (the
   route implemented in [`abcad/generators/helicoidal.py`](../abcad/generators/helicoidal.py));
3. printed tows, which are effectively a second material and are therefore excluded.

### 1.5 Geometric toughening mechanisms that survive a single material

1. **Crack twisting (the central mechanism).** The weak plane rotates by Δθ per ply, so the
   minimum-energy fracture surface is a twisting helicoid. Its geometry (Eq. 2, after Suksangpanya
   and co-workers) is Y = −Z·tan(X·dφ/dX), with X the twist axis, φ the relative twist, and
   dφ/dX ∝ Δθ/d = π/p: a smaller pitch twists faster and yields a longer, larger-area crack path.
   The strain-energy release rate rises with the anisotropy ratio E₂₂/E₁₁ [1, ref. 227]; for a
   single printed material this is the bead or raster anisotropy.
2. **Crack deflection** along the rotating planes lengthens the crack path; credited in
   single-material printed concrete and ceramic helicoids.
3. **Spiralling (twisting) delamination.** Cracks arrested at interfaces divert into a spiral front
   (micro-CT, Fig. 38), spreading damage over a large area and raising residual strength over QI
   and cross-ply layups. Penetration versus delamination is governed by an interfacial
   energy-release-rate criterion [1, ref. 173].
4. **Diffuse, progressive failure.** A small pitch spreads sub-critical damage, so the helicoid
   fails progressively where a QI layup fails catastrophically.

### 1.6 Printed Bouligand structures: pitch studies

Recent studies of printed Bouligand structures find that the optimal pitch depends on the material
and the load case. Single and double Bouligand layups both improve the fracture and flexural
behavior of printed strain-hardening cementitious composites [7]. In direct-ink-written alumina, a
helix angle of 10° per ply gave the highest fracture toughness of the Bouligand series
(1.45 MPa·m^1/2, 39 % above the 0° layup); with microscale flake reinforcement the combined
toughening peaked at 20° per ply, and interfacial engineering co-determined the gain [8]. In
stereolithographically printed porous Bouligand polymer plates, tensile modulus and strength both
peak at a 30° pitch angle [9]. This repository therefore treats **10–30° per ply** as the target
band for damage tolerance; the generator default of 10° per ply sits at its fracture-toughness end.

---

## 2. Woven metamaterials — Carton et al. [3]

### 2.1 Thesis

Most mechanical metamaterials (truss, shell, plate) target stiffness and strength. Woven lattices
are three-dimensional networks of **entangled fibers** joined by constant-curvature junctions
rather than monolithic nodes. They open the compliant and stretchable regime: reduced stress
concentrations permit large deformation (stretch λ > 2) even with stiff, brittle constituents, and
frictional sliding plus evolving entanglement dissipate energy. Earlier woven work was limited to
octahedron and diamond tessellations; [3] contributes a general graph-based framework for arbitrary
three-dimensional topologies, functional grading, and heterogeneity.

### 2.2 Released software (vendored in this repository)

The geometry engine was released as pure Python under the MIT license [4] and is vendored
verbatim in [`abcad/_vendor/woven_lattice/`](../abcad/_vendor/woven_lattice/) (commit
`8583837e712b01e161f93c0f360c3a2318d51191`).

- Dependencies at release: Python ≥ 3.9 with `scipy==1.13.1`, `matplotlib==3.4.3`,
  `numpy==1.22.4`, `numpy-stl==3.1.1`. No Blender and no CAD kernel. Two files:
  `lattice_main.py` (a short parameter script) and `makeunitcell_func1.py` (the 1469-line core).
- Outputs: a combined centerline CSV, one centerline CSV per fiber (plus `beams.csv` for the
  optional straight cores), a swept-tube triangle mesh `woven_mesh.stl`, and an interactive
  matplotlib plot. **The output is centerlines plus an STL, not a boundary representation.**
- Shipped demonstration: a 3 × 2 × 1 diamond lattice, unit cell 60, fiber radius 1, strut
  (bundle) radius R_eff = 2, 3/4 revolutions per strut, `doubleNetwork=True`; runs in under 30 s.

### 2.3 Construction algorithm

Line numbers refer to the vendored `makeunitcell_func1.py`. Orchestration: `wovenLattice()` →
`makeLattice()` (tessellate) → `class Node` / `wovenUnitCell()` (node tangents) →
`makeRotatedHelices()` (beams) → `wovenJoint()` (node connectors) → `sortStrands()` (stitching) →
`save_piped_stl()` (mesh).

1. **Parent lattice to graph** (`makeLattice`, lines 641–709). A unit cell is a dictionary of
   vertices and edges (`baseLatticeBars`, integer index pairs) tessellated over
   `cellNum = [nx, ny, nz]` by translations along the cubic vectors 2L·{x, y, z}; shared nodes and
   bars are de-duplicated. The internal half-side is L = unitCell/2. Each bar carries
   (R_eff, n_rev) through the callback `strutParams(position, L)` (`class Bar`, lines 1070–1074).
2. **Spherical node graph as the spherical dual** (`findNeighbors`, lines 184–204, using
   `scipy.spatial.ConvexHull`). Unit vectors to the neighbors are hulled on the sphere to decide
   which beam pairs interweave. **Invariant: node-graph degree = n = fibers per beam.** The dual of
   the cube is the octahedron, so n = 4 for the cubic lattice; BCC, octahedron and diamond give
   n = 3.
3. **Helix base circles on the node sphere** (`findCenterTangent`, lines 272–297; overlap test
   `checkHelixOverlap`, lines 299–308; growth in `wovenUnitCell`, lines 365–376). Each beam defines
   a small circle of radius R_eff where its centerline pierces a node sphere of radius r (initially
   r = L/10). The spherical arc radius is ρ = arcsin(R_eff/r). Circles may not overlap: for all
   adjacent i, j the intrinsic distance must exceed ρ_i + ρ_j, and r grows until this holds, so a
   node fits its largest local R_eff.
4. **Effective woven beam = bundle of n helices** (`makeRotatedHelices`, lines 424–560;
   `makeBaseHelix`, lines 312–327). The free helix length is
   H = |AB| − √(r_A² − R_eff²) − √(r_B² − R_eff²) (lines 533–534). The base helix for k = 0…N is
   x = R_eff·cos(kθ/N), y = R_eff·sin(kθ/N), z = z₀ + k·H/N, with total angle θ = 2π·(adjusted
   revolutions) and z₀ = √(r_A² − R_eff²). Pitch = H/θ (line 549) and helix angle
   α = atan2(H, 2π·n_rev·R_eff) (line 575). The n fibers are the base helix rotated into n slots so
   each lands on its node's tangent point (`anglesOfStrands`, lines 548–559), oriented with
   `rotationMatrixVectorToVector` (lines 163–181). The sample count is floor(pathLength/sampling)
   with pathLength = √((2π·n_rev·R_eff)² + H²) (lines 540–542). The chirality has the same sign
   everywhere, so fibers never cross.
5. **Chiral-twist node connector** (`wovenJoint`, lines 566–624). The angular path is a
   great-circle geodesic (`scipy.spatial.geometric_slerp`, line 616) between tangent points found
   by right-spherical-triangle trigonometry (`rightSphericalTriangle`, lines 239–266:
   B = arccos(tan ρ / tan(arc)), A = arcsin(sin ρ / sin(arc))), so each fiber leaves its helix
   tangentially (G¹ continuity). The radial profile is a cubic Bézier/Hermite curve
   (`scipy.interpolate.BPoly.from_derivatives`, line 618) whose end slopes equal the helix angles
   α₁ and α₂; it dips inward and returns, matching the pitch at both ends.
6. **Stitching continuous fibers** (`sortStrands`, lines 714–762). The walk node → beam → node
   concatenates helix and connector segments into single curves. The fiber-matching shift is
   (wholerevs, shift) = divmod(n_rev·n, n) (line 471); for example n_rev = 4/3 gives (1, 1) and
   n_rev = 5/3 gives (1, 2). This integer shift sets the global weave pattern and lets cells with
   different n_rev mate (Supplementary S2, Fig. S5). Rings close through `closePath`
   (lines 1104–1106).
7. **Sweep to a solid** (`save_piped_stl`, lines 883–939). A parallel-transport (twist-minimizing)
   frame is built along each centerline, a `pts`-sided circle of radius `rad` is placed at every
   sample, the tube is triangulated with `matplotlib.tri.Triangulation` and capped, and all tubes
   are written to one STL with numpy-stl. `eccentricity` flattens the circle into an ellipse.
8. **Optional double network** (`doubleNetwork=True`, lines 1421–1453). A straight monolithic beam
   is also emitted along each edge as a concentric core, giving two interpenetrating networks
   (woven shell plus straight core). This thickens struts, aids printability, and reduces
   compliance.

### 2.4 Parameters

| Symbol | Engine name | Meaning | Range in [3] | Desktop-print target |
|---|---|---|---|---|
| L | `unitCell` (halved internally) | Unit-cell side | 60 µm (120 µm for the tetrakaidecahedron) | 30–60 mm |
| R_eff | `strutRadius` / `barRadius` | Bundle radius; sets compliance and node size | 2–6 µm, i.e. R_eff/L ≈ 1/30–1/10 (simulations 1/30–1/5) | R_eff/L ≈ 1/10–1/8 |
| R_eff/L | — | Dimensionless design knob | 1/30 → 1/5; fabricable ≈ 1/30–1/10 | 1/10–1/8 |
| R_eff/R′_eff | — | Directional ratio (in-cell anisotropy) | varied | — |
| n_rev | `strutRevolutions` / `barRevolutions` | Helix turns per beam | n = 3: 4/3–7/3 (simulations to 10/3); n = 4: 4/4–6/4 (simulations to 12/4) | low end |
| n | node degree | Fibers per beam | 3 (BCC, octahedron, diamond, tetrakaidecahedron), 4 (cubic) | same |
| fiber radius | `rad` | Filament cross-section | 1 µm (Ø 2 µm ≈ L/60) | 0.3–0.5 mm (Ø 0.6–1.0 mm) |
| pitch | H/θ | Derived | — | — |
| α | atan2(H, 2π·n_rev·R_eff) | Helix angle (Bézier end slopes) | derived | — |
| chirality | global sign | Constant lattice-wide | single | single |
| r | `sphereRadius` | Node sphere; starts at L/10 and grows automatically | derived | — |
| sampling | `sampling` | Centerline point spacing | 2 (demonstration) | tune |
| ρ̄ | — | Relative density | 1–5 % | similar |

### 2.5 Topologies, grading, and heterogeneity

- **Parent lattices in [3]** (n = node degree): cubic (n = 4, dual octahedron), BCC (n = 3),
  octahedron (n = 3, dual BCC), diamond cubic (n = 3), and tetrakaidecahedron (Kelvin cell, mixed
  3 and 4). The released code also contains experimental cuBCC, tetracubic, arrow, octet, and
  octahedron-to-BCC dual topologies (lines 1166–1198). Adding a topology is one
  `Lattice(name, vecs, vertices, edges)` entry.
- **Functional grading** through `strutParams(position, L) → (R_eff, n_rev)` per beam:
  - Fig. 1b: cubic lattice with R_eff/L graded 1/5 → 1/12 vertically and n_rev 2/n → 12/n.
  - Fig. 5a: text cells (n_rev = 2/3, R_eff/L = 1/10, compliant) against a background (7/3, 1/12)
    and a boundary (7/3, 1/15, stiffest), so that the letters are revealed by strain.
  - Fig. 5b: a sinusoidal programmable failure path via a stepwise-linear R_eff gradient to 1/20;
    Supplementary Fig. S16 ramps R_eff from −4 to −2 across the width.
  - Stochastic n_rev produces a randomly entangled but ordered network.
- Dissimilar neighbors mate automatically (the node resizes and the divmod shift adapts), so no
  manual CAD repair is needed.

### 2.6 Fabrication and validated performance

- **Process:** two-photon lithography (Nanoscribe GT2), microscale only. L = 60 µm with fiber
  Ø 2 µm; tetrakaidecahedron L = 120 µm. Printing at 25 mW and 10 mm/s with 0.2 µm hatch and
  slice; development in PGMEA and IPA, critical-point drying, 10 nm Au coating for SEM.
- **Material:** IP-Dip2 acrylate photoresist, **a single material everywhere**. All tunability is
  geometric: stiffness varies by more than 10×, anisotropy E_max/E_min exceeds 20, and stretch
  reaches λ = 4, all with one material.
- **Supports:** a sacrificial thin simple-cubic scaffold (fiber radius 4× smaller) printed
  simultaneously and removed by O₂ plasma ashing (15 min, 100 W; Supplementary S5) — the analogue
  of breakaway supports in FDM or resin printing.
- **Testing:** in-situ uniaxial tension in the SEM (Alemnis nanoindenter with a microgripper) at a
  strain rate of 5 × 10⁻² s⁻¹ on 2 × 2 × 2 tessellations (some 4 × 4 × 4 cyclic tests and one
  10 × 2 × 5 failure-path specimen). Stiffness 40 → 160 kPa (BCC, R_eff 6 → 2 µm); **all woven
  lattices reach λ ≥ 2 and up to 4**, whereas monolithic counterparts fail below 1.5; cyclic
  loading 10× to 15 % strain. Relative density 1–5 %.
- **Modeling:** Timoshenko B31 beam elements (ABAQUS/Explicit, Coulomb friction μ = 0.5, element
  deletion at a maximum strain of 0.0377), about four orders of magnitude faster than C3D10
  tetrahedra (125.7 h → 1.5 min). Homogenization in nTop and ABAQUS; Gmsh meshes at 0.25× the
  fiber radius.

### 2.7 Desktop-print feasibility (millimetre scale, single material)

The geometry is scale-free: the dimensionless quantities R_eff/L, n_rev, and fiber Ø/L are kept
and the absolute size is refit to the printer resolution. Resin (SLA/DLP) printing is preferred;
FDM is marginal.

1. **Scale up about 100–500×.** A 2 µm fiber maps to a desktop resin minimum feature of about
   0.2–0.5 mm, or a 0.4 mm FDM nozzle (≥ 0.8 mm for robust unsupported strands). Keeping fiber
   Ø/L ≈ 1/60–1/30 gives **fiber Ø 0.6–1.0 mm and L = 30–60 mm** (centimetre-scale cells).
2. **Raise R_eff/L (≈ 1/10–1/8) and keep n_rev low.** A small R_eff or a large n_rev shrinks the
   inter-fiber gap; fibers then fuse and the woven compliance is lost. Keep at least one fiber
   diameter of clearance.
3. **Mind the XY accuracy.** The gap must exceed the positional error plus the bead width; resin
   printing is far better than FDM here.

Helices have a continuously varying overhang, and near-horizontal arcs exceed the 45° FDM rule, so
supports are unavoidable (a breakaway lattice, or a thin sacrificial scaffold as in [3]). Tight
nodes (high n_rev, small R_eff) should be checked for self-intersection, the part should be
oriented to minimize the worst overhang, and the double network can be used to thicken struts.
The single-material property is fully preserved.

### 2.8 Sweep options

Steps 1–6 of the engine are pure numpy/scipy and are reused unchanged. Step 7 (the tube sweep) is
provided twice in [`abcad/generators/woven/build.py`](../abcad/generators/woven/build.py): a
Blender curve with `bevel_depth` = fiber radius (Blender's curve tilt supplies the same
twist-minimizing frame as the engine's parallel transport), and the engine's own numpy-stl mesher,
which runs without Blender. The `strutParams(position, L)` callback is the grading hook.

---

## 3. Enamel decussation

Dental enamel owes its damage tolerance to **decussation**. Enamel rods (prisms) are bundled, and
adjacent bundles cross one another between layers (Hunter–Schreger bands). A crack cannot run
straight through such a structure: it must repeatedly twist to follow the changing rod direction,
which multiplies the work of fracture and produces a rising ("J-shaped") resistance curve.

The enamel family in `abcad` models this as a **rotating plywood of rods**:

- rods are packed on concentric hexagonal rings (one center rod; ring k holds 6k rods at radius
  k·spacing), the natural close packing of prisms;
- each ring is twisted about the central axis by its own total angle over the specimen height, and
  adjacent rings twist by different, typically alternating-sign angles — the sign flip between
  neighbors is the decussation (crossing) that deflects cracks;
- the twist develops along the height according to a selectable law (linear, accelerating, or
  sigmoid); the twist profile, not only its magnitude, is the design lever for the resistance
  curve;
- thin interrod bridges of the same material tie adjacent rods of a ring together at several
  heights, making the bundle a connected, printable, load-bearing solid.

Real enamel has a soft protein sheath between rods. That second phase is deliberately **not**
modeled: rods and bridges are one material, so every toughening contribution is geometric (crack
twisting and the connected bridge network) and none relies on a modulus contrast. The rotating
plywood is the same geometric principle behind the helicoidal crack twisting of Section 1.5 and
behind the best-performing architecture of Section 4, realized here with discrete rods instead of
plies. The reference geometry is the micro-CT-grounded CadQuery lattice of the author's enamel
work [5, 6]; its port is documented in [validation/enamel_goldens.md](validation/enamel_goldens.md).

---

## 4. Printed biomimetic composites — Jia and Wang [2] (cautionary reference)

> **This is a two-material PolyJet study.** Its 5–17× toughness gains come primarily from a 390×
> modulus contrast between two printed photopolymers, not from geometry alone. All "×" values
> below are contrast-inflated upper bounds that do **not** transfer to single-material printing.
> Adopt the architectures, not the numbers.

### 4.1 Architectures (Fig. 1, §2.1): 2D microstructures extruded as compact-tension prisms

| Architecture | Biological model | Geometry | Notes |
|---|---|---|---|
| Brick-and-mortar | Nacre | Bricks of aspect ratio r, length a, mortar t; with or without mineral bridges (1.25 %, 2.5 %) and interfacial micro-asperity | 4 sub-designs |
| Cross-lamellar | Conch | Crossed laminas a, b, c plus interface t | — |
| Branch-lamellar | Conch | Laminas a, b plus t | Authors' variant |
| Concentric hexagon | Bone osteon | N nested hexagonal rings, spacing a, wall t; outer ring hard | — |
| Rotating plywood (Bouligand) | Dactyl club, scales, teeth | Laminas at constant rotation per ply plus interface t | Pitch angle in Table S1 (supplement) |

The soft-phase volume fraction is 0.25 for all designs (0.50 for the hexagon). Feature sizes are
about one order of magnitude below the specimen size (45 × 40 × 8 mm).

### 4.2 Process and material

- PolyJet material jetting (Stratasys Objet Connex260) with two photopolymers: **VeroWhite**
  (E = 1.56 GPa, ν = 0.33, G_IC = 0.95 kJ/m², strength ≈ 46.6 MPa) and **TangoPlus** (E = 4 MPa,
  ν = 0.4, G_IC = 0.20 kJ/m²), so **E_hard/E_soft = 390**, matched to nacre. Resolution 30 µm (Z)
  and 600 DPI ≈ 43 µm (XY). There are no fibers or fillers; "composite" means two bulk polymers.
- **The one single-material-relevant finding (§3.1):** PolyJet droplets are elliptical with the
  long axis along the print direction. Orienting the print path parallel or perpendicular to an
  interface sets low or high interfacial asperity, so **print direction encodes a
  surface-roughness (interlock) feature without changing the material**. Higher asperity improves
  stiffness, strength, and work of fracture.

### 4.3 Results (Table 2; baseline = homogeneous hard phase)

| Structure | Maximum force per mass (N/g) | Work per mass (N·mm/g) | × hard phase |
|---|---|---|---|
| Hard phase | 16.39 | 4.25 | 1× |
| Soft phase | 0.22 | 3.29 | — |
| **Rotating plywood (Bouligand)** | 14.53 | **75.37** | **16.7× (highest)** |
| Concentric hexagon | 11.54 | 68.41 | 15.1× |
| Brick-and-mortar (optimized) | **16.78 (strongest)** | 65.01 | 14.3× |
| Cross-lamellar | 7.31 | 37.96 | 7.9× |
| Branch-lamellar | 13.08 | 28.36 | 5.7× |

The rotating plywood shows a "J"-shaped resistance curve (R ∝ Δa): a larger critical G_c and
tolerance of longer cracks, i.e. the best **crack arrest** (impact). The other designs show
"G"-shaped curves (the process zone saturates): a higher critical stress, i.e. the best
**resistance to initiation**. The concentric hexagon shows stepped force histories from periodic
fracture and arrest of the hard layers, with deflection when G_h/G_s > (3a + t)/2a (≈ 1.5–2; 5.1
here). The optimized brick-and-mortar reaches 15× the hard phase and 7× the original design
(asperity plus bridges), with ≤ 60 % of the energy dissipated during post-peak propagation.

### 4.4 Mechanism split (§4.3): the decision table for a single material

- **Require a modulus contrast (not transferable):** crack-penetration arrest at a stiffness jump
  (J_tip/J_far < 1 toward the stiffer phase; vanishes when E₁ = E₂); stepped toughening in the
  concentric hexagon (needs G_h/G_s); brick-and-mortar strength and shear lag; crack bridging
  (needs an intact stiff ligament; a factor of 2.91).
- **Geometric (partly transferable):** crack deflection and twisting along weak interfaces
  (surface ratio S_d/S₁ = 1/cos θ; mode mixity raises R/R₁ and lowers G(θ)/G₁); the twisting in the
  rotating plywood — the 16.7× architecture — is geometric in origin (compare the twisting-crack
  analyses of Bouligand structures by Suksangpanya and co-workers); interfacial asperity and
  interlock, which are material-agnostic. For the lamellar branch the experiment gives
  J_lam/J_int = 5.38 (deflection 2.16× combined with bridging 2.91×).

### 4.5 Single-material transferability (engineering inference)

The target architecture needs **engineered weak interfaces**, because deflection, twisting, and
tortuosity all require guided cracks. Single-material routes are: (1) per-layer raster rotation,
creating inter-bead weak planes that form a rotating-plywood field (the closest analogue of the
16.7× architecture, and consistent with the print-direction finding of §3.1); (2) weak interlayer
bonding or designed gaps as the surrogate for a toughness contrast; (3) explicit modeled voids or
grooves for resin, which is otherwise nearly isotropic. Small pitch angles (≈ 7–25°, many plies)
maximize twist toughening; the exact value used in [2] is in its Table S1. For a desktop coupon of
about 40 mm, unit cells should be ≳ 2–4 mm and laminas ≥ 2–3 beads (≥ 0.8–1.2 mm); with 0.1 mm
layers and Δθ = 18°, one 180° rotation spans about 10 layers, or about 1 mm, which is feasible.
The concentric hexagon relies on contrast and is avoided.

---

## 5. Cross-paper synthesis: single-material design rules

1. **One material means function from architecture.** Lost: modulus-contrast mechanisms
   (penetration arrest, bridging, stepped toughening). Kept: topology (woven entanglement) and
   weak-plane geometry (helicoidal and decussated crack twisting and deflection).
2. **Woven lattices are the clearest single-material demonstration** (one photoresist; compliance
   and toughness entirely geometric) [3]. The released generator is reused; R_eff/L, n_rev,
   topology, and grading are tuned, and at least one fiber diameter of inter-fiber clearance is
   enforced.
3. **Helicoidal laminates are validated in single materials** (PLA at 5–45°, concrete at 15° and
   30°) [1]. Toughening scales with 1/pitch and with the bead anisotropy E₂₂/E₁₁. The route
   implemented here uses modeled rotated plies with controlled gaps or grooves; per-layer raster
   rotation is an optional addition for anisotropy. The double twist is the toughest reported
   variant.
4. **Expectation management.** Single-material prints recover only a fraction of multi-material
   toughness (the 16.7× of [2] is contrast-inflated), but the qualitative mechanisms persist and
   are tunable through pitch and raster.
5. **Recommended starting designs:** helicoidal Δθ = 7.8–10° (PLA, modeled gaps) as the robust,
   strength-leaning default and 10–30° per ply where damage tolerance is the target (§1.6); the
   30/15/10/5° double twist; woven cubic, BCC, and diamond lattices at R_eff/L = 1/10–1/8 with low
   n_rev and L = 30–60 mm (resin or TPU); enamel rod lattices scaled so that rods clear the process
   minimum feature.

How these rules are exercised in this repository: the generators are specified in
[GENERATORS.md](GENERATORS.md); printability is certified as described in
[PRINTING.md](PRINTING.md); stiffness and flaw tolerance are measured with the voxel-hex
finite-element instruments in [FEA.md](FEA.md); and crack twisting and deflection — the mechanisms
of Sections 1.5, 3, and 4.4 that a linear stiffness screen cannot resolve — are simulated with the
phase-field fracture instrument in [FRACTURE.md](FRACTURE.md).

---

## References

1. H. Ning, C. Monroe, S. Gibbons, B. Gaskey, P. Flater. A review of helicoidal composites: From
   natural to bio-inspired damage tolerant materials. *International Materials Reviews* 69(3–4),
   181–228 (2024). doi:10.1177/09506608241252498
2. Z. Jia, L. Wang. 3D printing of biomimetic composites with improved fracture toughness.
   *Acta Materialia* 173, 61–73 (2019). doi:10.1016/j.actamat.2019.04.052
3. M. Carton, J. U. Surjadi, B. F. G. Aymon, L. Xu, C. M. Portela. Design framework for
   programmable three-dimensional woven metamaterials. *Nature Communications* 17, 1581 (2026).
   doi:10.1038/s41467-026-68298-3. Preprint: arXiv:2507.14130 (2025).
4. M. Carton. woven-lattice (software, MIT License), <https://github.com/mollyacarton/woven-lattice>,
   commit 8583837e712b01e161f93c0f360c3a2318d51191.
5. C. B. Renteria, J. R. Grimm, A. Yunker, D. Y. Parkinson, D. D. Arola. Translating helically
   decussated enamel into damage-tolerant bioinspired lattices. *Matter* (in preparation).
6. C. B. Renteria. biomimetic-lattice-pipeline (software),
   <https://github.com/crentb/biomimetic-lattice-pipeline>.
7. G. Du, Y. Qian. Enhancing the fracture and flexural behavior of 3D printed strain-hardening
   cementitious composites with nature-inspired single and double Bouligand structures.
   *Construction and Building Materials* 465, 140145 (2025). doi:10.1016/j.conbuildmat.2025.140145
8. Z. Wang, D. Duan, L. Yang, X. Bai, Z. Jiao, C. Wu, J. Zhao, Z. Zhang. Synergistic strengthening
   and toughening of 3D-printed bioinspired alumina composites with a multi-scale Bouligand
   structure. *Biomimetics* 11(4), 252 (2026). doi:10.3390/biomimetics11040252
9. P. S. Patil, E. D. McCarthy, P. Alam. Tensile properties of 3D-printed porous Bouligand
   structured polymer plates. *Macromolecular Materials and Engineering* (2026).
   doi:10.1002/mame.70218
