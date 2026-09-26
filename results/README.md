# results/ — curated evidence records

Small, text-only records (JSON / CSV / Markdown / one solver log) that back the documented numbers
of agentic-bioinspired-cad. Each record was written by one of the package's instruments during the
original runs and is archived here unchanged, except that absolute paths were rewritten to
repository-relative ones (the `out/...` paths inside the records name the working output directory
of the original run; the geometry, meshes and solver fields they point to are binary artifacts and
are **not** archived). Terminal colour codes were stripped from the one log file. No number was
altered.

The test-method codes (TM-1 … TM-6) are defined in the quality documents under `docs/qms/`. The
fast gold tests in `tests/test_golds.py` read these records directly.

| Directory | Instrument (producer) | Certifies |
|---|---|---|
| `damage_tolerance/baseline/` | TM-3, `abcad/fea/damage_tolerance.py` | 2026-07-05 baseline damage-tolerance ranking (8 parts) |
| `damage_tolerance/voxel_0p5_amg/` | TM-3 at 0.5 mm voxels with `ABCAD_FEA_SOLVER=amg` | ranking of record (10 parts, incl. enamel) |
| `fracture/` | TM-6, MOOSE decks in `abcad/fracture/decks/` + `abcad/fracture/*.py` | validation gate, toughness vs orientation, J-integral, Bouligand crack twisting |
| `woven_cell/` | TM-6 contact / failure decks (`tm6_make_woven_cell_deck.py`, `tm6_make_woven_fracture_deck.py`) | non-fused woven retention and fracture comparison |
| `print_audit/` | TM-2, `abcad/printing/print_audit.py` | print certification of the demonstrator fleet and the release candidate |
| `fea_tension/` | `abcad/fea/run_tension.py` via `abcad/fea/fea_runner_amg.py` | linear small-strain tensile moduli of the woven FEA specimen |
| `agent_runs/` | TM-4, the agentic design loop | the live validation of 2026-09-26: five run manifests and the validation record |

## damage_tolerance/ — flaw-seeded stiffness retention (TM-3)

One directory per part. Each holds:

- `damage_tolerance.json` — the QMS record: STL path, mesh recipe (voxel / plate / overlap),
  flaw model (replicates, flaws per replicate, flaw radius, pinned seed), intact `E_eff`, and per
  replicate the flaw dose `removed_rod_frac` (f), damaged `E_eff` and retention `R = E_damaged /
  E_intact`, plus mean and min retention;
- `report.md` — the human-readable table written alongside;
- `fea_intact/e_eff.json`, `fea_damaged_<k>/e_eff.json` — the per-solve summaries written by
  `run_tension.py` (reaction force [N], footprint `A0` [mm²], height `H0` [mm], applied strain,
  `E_eff` [MPa]), one per mesh variant.

Ranking quantity: floor margin `m = min R − (1 − mean f)`. `m ≈ 0` means continuum-proportional
stiffness loss; negative means load-path sensitivity.

**`baseline/`** — voxel 1.0 mm (1.25 mm for the near-solid plates `dt`, `dt_inplane`,
`h_solid_inplane`), plates 2.0 mm / overlap 0.8 mm, 3 replicates × 3 flaws of radius 1.5 mm, seed
20260703, material E = 3000 MPa, ν = 0.40. Margins: `h_solid_inplane` (solid control) +0.001 — the
instrument zero-point; `dt_inplane` −0.003; `dt` −0.005; Bouligand coupons 10° / 15° / 20° / 30°
−0.009 / −0.014 / −0.017 / −0.021; fused woven cube `woven_fea_small` −0.108 (intact E_eff 82.698 MPa).

**`voxel_0p5_amg/`** — the same protocol at 0.5 mm voxels (larger meshes, solved with the pyamg
solver path of `fea_runner_amg.py`); adds the three enamel twist laws. Fused woven margin −0.046;
all other parts between −0.011 and 0.000. This set is what `abcad/reporting/mission_control.py`
ranks.

## fracture/ — MOOSE fracture instruments (TM-6)

| File | Producer | Content |
|---|---|---|
| `validate_uniaxial_out.csv` | `decks/validate_uniaxial.i` | validation gate: solid bar, strain 0.01 → stress 29.999999998146 MPa, i.e. E = 3000 MPa recovered |
| `validate_uniaxial_run.log` | MOOSE console output of that run | MOOSE build (git a628b5c0), mesh, converged Newton solve |
| `tm6_benchmark_K.csv` | `decks/tm6_benchmark_K.i` | J-integral (4 rings) + top reaction for the closed-form K benchmark |
| `orientation_sweep/tm6_a{0..90}.csv` | `decks/tm6_twist.i` swept over `euler_angle_1` | top displacement, reaction, mean damage `crack_c` and average σ_yy histories per rod angle |
| `tm6_result.json` | `abcad/fracture/tm6_analyze.py` over `orientation_sweep/` | peak load and area under the load–displacement curve to a common displacement (2.357e-3, the shortest run) vs angle; max/min ratio 1.6655 at 45°. That window closes before the 0°/90° peaks (3.05e-3) and every run stops 4–6 % past its peak with no crack propagation, so the ratio tracks initial stiffness (1.81× at 45°), not toughness: energy absorbed to peak is 0.98× at 45°. See docs/FRACTURE.md |
| `jintegral_sweep/tm6j_a{0..90}.csv` | `decks/tm6_jintegral.i` swept over `euler_angle_1` | J (3 rings) vs displacement per angle |
| `tm6_jintegral_result.json` | J-integral sweep summary | J at initiation vs angle; peak at 45°, Jc ratio 1.173; benchmark error 4.5 % |
| `tm6_bouligand_result.json` | `tm6_make_bouligand_deck.py` runs at 10/15/20/30°/ply | crack tortuosity (peak 1.824 at 15°/ply), twist amplitude, work |
| `tm6_stageD_result.json` | `decks/tm6_stageD.i` swept over angle | full-model crack deflection drift by rod angle (0/90 straight, 30/60 opposite) |

`tm6_result.json` is reproducible from the archived sweep: `python -m abcad.fracture.tm6_analyze
results/fracture/orientation_sweep` (checked by `tests/test_golds.py`). The per-step J-integral
vector-postprocessor dumps of the sweep (one tiny CSV per ring and step) are not archived; the
per-angle files above carry the same J values over time.

## woven_cell/ — non-fused woven cell (TM-6 contact track)

`RESULTS.md` is the study write-up (model, tables, interpretation). CSVs are the MOOSE
postprocessor histories it cites: `wcell{2,3}_{intact,dmg}_pre.csv` (weft-preloaded runs) plus
`wcell2_intact.csv` and `wcell2_dmg_free.csv` (2×2 runs with a free, unpressed weft) for the
frictional-contact retention study — retention lands
on the geometric (N−1)/N (0.500 for 2×2, 0.667 for 3×3); `wfrac_fused.csv`, `wfrac2_fused.csv`,
`wfrac2_nonfused.csv` for the phase-field fused vs weak-interface comparison: equal initial
stiffness, but the weak-interface specimen reaches 0.32× the fused peak load, 0.16× its energy to
peak and 0.10× its total work (an earlier summary quoted 0.55×, which understated the penalty).

## print_audit/ — printability audit (TM-2)

Each subdirectory holds the audit's `print_audit.csv` (one row per part: bbox, volume, watertight /
manifold, overhang fraction, voxel size, lost-material fractions on the thickness ladder, gap
fractions, enclosed voids, verdict per process) and `print_audit_report.md`.

- `fleet/` — first audit of the demonstrator STLs (FDM + resin verdicts).
- `fdm_variants/` — the uniformly scaled `woven_fea_small` variants from
  `abcad/printing/fdm_variants.py` (x1.5, x2.0, x2.0 plated).
- `coupons/` — the Bouligand pitch coupons.
- `enamel/` — the scaled enamel lattice before remeshing.
- `smooth/` — the release candidate `woven_fea_small_x20_smooth.stl` (voxel remesh of the x2.0
  variant by `abcad/printing/remesh_watertight.py`): FDM verdict PRINT, watertight, 0.17 % of
  material below 0.8 mm.

## fea_tension/ — tension FEA (linear and finite strain)

`e_eff.json` (the `run_tension.py` summary), `global_results_tension.csv` and
`force_displacement_tension.csv` (the stock SfePy problem's outputs) and `mesh.json` (the
`voxel_plate_mesh.py` sidecar: voxel size, hex count, A0, H0) for three meshes of the same woven
specimen `woven_fea_small.stl`:

- `woven_fea_small_linear/` — voxel 0.6 mm, 34,974 hex, strain 0.01: E_eff 67.73 MPa.
- `woven_fea_tiny_linear/` — voxel 0.8 mm, 17,685 hex, strain 0.015: E_eff 91.80 MPa (the linear
  reference quoted in `abcad/fea/run_tension_finite.py` and `abcad/fea/fea_runner_amg.py`).
- `woven_v05_amg/` — voxel 0.5 mm, 63,334 hex, solved with `ABCAD_FEA_SOLVER=amg`: E_eff 47.69 MPa
  (matches the intact value of `damage_tolerance/voxel_0p5_amg/woven_fea_small`).

### fea_tension/finite_strain_validation/ — finite-strain solver validation

Produced by `abcad/fea/run_tension_finite.py` (SfePy 2025.4) on 2026-09-25; `record.json` holds
the commands, software versions, the mesh's SHA-256 and the derived values. Each CSV carries the
per-step Newton record (`newton_converged`, `newton_iters`, `newton_residual_N`).

- `block_tension_finite.csv` — 10 × 10 × 20 mm block, 6 steps to 10 % strain, every step
  converged: small-strain E_eff 3080.8 MPa = 102.7 % of E (the clamped-grip block's expected
  slight over-stiffness).
- `woven_fea_tiny_tension_finite.csv` — the 17,685-hex woven mesh, two 0.5 % steps, both
  converged (residual about 7 × 10⁻⁷ N): E_eff 93.11 MPa at 0.5 % strain versus the 91.80 MPa
  linear reference on the same mesh (+1.4 %), stiffening to a 95.7 MPa secant at 1 %.
- `woven_fea_tiny_single_large_step_nonconverged.csv` — the same mesh in ONE 1.67 % step: Newton
  exhausts its 12 iterations (residual 1.0 × 10⁵ N), so that row is not an equilibrium state. It
  documents why lattice runs use about 0.5 % strain per step.

## agent_runs/ — live validation of the design loop (TM-4)

`validation_2026-09-26/E2E_REPORT.md` records the live end-to-end validation of `abcad.agent` on
its target host: the setup, the verdict of every acceptance check, and the manifests of the five
runs that reached Phase 2 (`2026-09-26_*/run_manifest.json`), each ending with a certified print
file. `e2e_summary.json` holds the machine-readable verdicts and measured values, `watchdog/` the
wall time and swap growth of every step, and `retrieval.log` the grounding scores. Recorded paths
are relative to the repository root; the geometry and renders they name are regenerable run
output under `out/` and are not tracked.
