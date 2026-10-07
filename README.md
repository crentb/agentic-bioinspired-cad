# agentic-bioinspired-cad

A fully local agentic loop that turns a natural-language design prompt into a certified, single-material, 3D-printable bioinspired architecture, with printability, finite-element, and phase-field fracture verification.

[![CI](https://github.com/crentb/agentic-bioinspired-cad/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/crentb/agentic-bioinspired-cad/actions/workflows/ci.yml)
[![CodeQL](https://github.com/crentb/agentic-bioinspired-cad/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/crentb/agentic-bioinspired-cad/actions/workflows/codeql.yml)
[![Python](https://img.shields.io/badge/python-3.10--3.14-blue)](https://github.com/crentb/agentic-bioinspired-cad/blob/main/pyproject.toml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/crentb/agentic-bioinspired-cad/blob/main/LICENSE)

<p align="center">
  <img src="https://raw.githubusercontent.com/crentb/agentic-bioinspired-cad/main/docs/figures/readme_hero.png" width="620" alt="A woven diamond lattice built by the woven generator: bundles of helical fibers wound along every strut and entangled at the nodes, rendered as a single printable material">
</p>

Architected materials can be damage tolerant through geometry alone: helicoidal (Bouligand) laminates twist a crack through their plies, woven lattices distribute load along entangled fibers, and the decussating rods of tooth enamel deflect cracks. This repository makes those architectures designable and printable **from a single material**. Parametric generators build them directly; an agentic loop builds them from a sentence of text; and a set of verification instruments checks that the result can be printed, how it carries load, and how it fractures.

![Pipeline overview: a design prompt passes through a code emitter, a headless Blender build and render, a vision critic with repair and refine agents, and a print gate to a certified STL; three generator families supply exemplars, and four verification instruments (print audit, voxel-hex FEA, damage tolerance, phase-field fracture) check the part before it is printed](https://raw.githubusercontent.com/crentb/agentic-bioinspired-cad/main/docs/figures/pipeline_overview.png)

The loop runs on one 16 GB Apple-silicon machine with no cloud services. A fine-tuned code emitter writes Blender Python in an isolated process; headless Blender builds and renders it and reports mesh statistics; a local vision-language critic returns a schema-constrained verdict against retrieved reference renders; local repair and refine agents fix the code; and a manufacturability gate certifies an STL for FDM or resin printing, auto-scaling the design when its features are too thin. Every run writes a manifest.

## Results

Every number below comes from a text evidence record in [`results/`](https://github.com/crentb/agentic-bioinspired-cad/tree/main/results), and the gold tests re-verify the recorded values.

| Question | Result | Evidence |
|---|---|---|
| Does the loop converge hands-free? | Yes, in a live validation on the target machine. From a recorded emit that fails to execute, every one of five runs repaired the script within three attempts and ended with a certified print file: the print gate found 13–18 % of the material thinner than 0.8 mm and a uniform ×1.6 auto-scale certified the part PRINT for FDM, in 5 to 8 minutes per run. The runs held with the models offline, and at a 58 mm target size, and a full run from the text prompt alone certified the woven lattice in about 5 minutes. | [validation record](https://github.com/crentb/agentic-bioinspired-cad/blob/main/results/agent_runs/validation_2026-09-26/E2E_REPORT.md) |
| Can the designs be printed? | All 10 demonstrator parts are watertight and print in resin (2 with minor fixes); none prints in FDM as designed, which is what the certified scaled variants are for. The release-candidate woven part passes FDM with 0.17 % of the material thinner than 0.8 mm and no enclosed voids. | [fleet](https://github.com/crentb/agentic-bioinspired-cad/tree/main/results/print_audit/fleet), [release candidate](https://github.com/crentb/agentic-bioinspired-cad/tree/main/results/print_audit/smooth) |
| How flaw tolerant are the architectures? (TM-3) | At 0.5 mm voxels the solid control sits on the proportional-loss floor (margin −0.0002), the laminates and enamel lattices lose 0.0055 to 0.0111 beyond it, and the fused woven lattice is the outlier at −0.046. | [TM-3 records](https://github.com/crentb/agentic-bioinspired-cad/tree/main/results/damage_tolerance/voxel_0p5_amg) |
| Is the finite-strain solver right? | A validation block recovers 102.7 % of the solid modulus, and the woven lattice gives 93.1 MPa at 0.5 % strain against the 91.8 MPa linear reference on the same mesh (+1.4 %). | [FEA records](https://github.com/crentb/agentic-bioinspired-cad/tree/main/results/fea_tension) |
| Are the fracture simulations validated? (TM-6) | The uniaxial gate recovers E = 3000.00 MPa, and the J-integral reproduces the closed-form K benchmark within 4.5 %. | [fracture records](https://github.com/crentb/agentic-bioinspired-cad/tree/main/results/fracture) |
| Does rod orientation steer the crack? | Yes. The crack shows no net drift at 0° and 90° and drifts −0.47 and +0.48 at 30° and 60°; through Bouligand coupons it changes direction at every ply (tortuosity 1.5 to 1.8 as traced in July 2026; where it peaks depends on how the diffuse crack path is traced). | [fracture records](https://github.com/crentb/agentic-bioinspired-cad/tree/main/results/fracture) |
| Do frictional crossings make a woven cell redundant? | No. After one fiber is cut, stiffness retention is exactly the geometric (N−1)/N: 0.500 for a 2×2 cell and 0.667 for a 3×3 cell. | [woven-cell records](https://github.com/crentb/agentic-bioinspired-cad/tree/main/results/woven_cell) |
| Do weak interfaces toughen a woven idealization? | No. At equal initial stiffness the weak-interface specimen reaches 0.32× the fused peak load and 0.10× its total work. | [woven-cell records](https://github.com/crentb/agentic-bioinspired-cad/tree/main/results/woven_cell) |

![Fracture results: (a) load-displacement curves by rod angle, (b) ratios to the aligned specimen, (c) crack tortuosity versus ply pitch, (d) fused versus weak-interface woven idealizations](https://raw.githubusercontent.com/crentb/agentic-bioinspired-cad/main/docs/figures/fracture_results.png)

The orientation sweep needs a precise reading. The 45° specimen is 1.81× stiffer than the aligned one and reaches 1.32× its peak load, but absorbs the same energy up to peak (0.98×), and J at crack initiation rises by only 7 %. The runs stop before the crack propagates, so this sweep resolves stiffness and strength anisotropy, not crack-twisting toughening. The full analysis is in [docs/FRACTURE.md](https://github.com/crentb/agentic-bioinspired-cad/blob/main/docs/FRACTURE.md).

## Generator families

![Generator families: (a) a Bouligand coupon at 30 degrees per ply, (b) a Tier-1 woven cubic lattice, (c) an enamel decussation rod lattice](https://raw.githubusercontent.com/crentb/agentic-bioinspired-cad/main/docs/figures/generator_families.png)

| Family | Module | What it builds |
|---|---|---|
| Helicoidal / Bouligand | `abcad.generators.helicoidal` | Ply stacks with seven rotation laws (constant, graded, exponential, Fibonacci, double twist, herringbone, noise), plate or fiber plies, and modeled weak-plane interfaces (groove, air gap, solid) |
| Woven lattice | `abcad.generators.woven` | Tier 1: exact woven lattices (cubic, BCC, octahedron, diamond, tetrakaidecahedron) from the vendored woven-lattice engine, with fiber-clearance checks, functional grading, and a Blender-free watertight path. Tier 2: a compact form the code emitter can write |
| Enamel decussation | `abcad.generators.enamel` | Hexagonal rod rings twisted by linear, accelerating, or sigmoid laws, after the decussating rods of tooth enamel |

Parameters, units, and physical meaning for every family are in [docs/GENERATORS.md](https://github.com/crentb/agentic-bioinspired-cad/blob/main/docs/GENERATORS.md).

## How the loop works

![One certified live run: the critic rejects the repaired lattice and approves the refined one; the print gate marks the material thinner than 0.8 mm; the ×1.6 auto-scaled part is certified PRINT](https://raw.githubusercontent.com/crentb/agentic-bioinspired-cad/main/docs/figures/agent_loop_convergence.png)

The loop is split into two phases so that it fits in 16 GB of unified memory:

- **Phase 1 (code emitter).** A child process loads a Llama-3.2-3B-Instruct base model with a code-emitting LoRA adapter on the Metal backend, retrieves the closest exemplar scripts, writes one Blender script, and exits, which returns all of its memory to the operating system.
- **Phase 2 (render, critique, repair).** The parent process holds no model weights. It runs the script in headless Blender, which exports an STL, renders it, and prints a structured `MESH_STATS` line. A local vision-language model judges the render against retrieved reference renders and must answer in a fixed JSON schema. A local code model repairs scripts that fail and refines designs the critic rejects, with stall guards. After the first approval, the manufacturability gate audits wall thickness, clearance, overhang, and enclosed voids once, auto-scaling if needed; a certified artifact ends the run.

The state machine, the verdict schema, the Blender protocol, the configuration variables, and the operating rules are documented in [docs/AGENT.md](https://github.com/crentb/agentic-bioinspired-cad/blob/main/docs/AGENT.md).

## Installation

From source, for development:

```bash
git clone https://github.com/crentb/agentic-bioinspired-cad.git
cd agentic-bioinspired-cad
python -m pip install -e ".[dev]"                  # core + pinned dev tools (pytest, ruff, black, mypy, pre-commit)
python -m pip install -e ".[mesh,fea,agent]"       # mesh tools, FEA drivers, and the design loop
```

The default install and CI exercise the pure-Python logic: generator geometry, the manufacturability gate, the loop's control flow (with test doubles), and the evidence-record checks. The full stack also uses these host-side engines, which the package drives by subprocess:

| Engine | Used by | Configure with |
|---|---|---|
| Blender 4.2 or newer, headless | helicoidal and woven builds, loop renders | `ABCAD_BLENDER` (else `blender` on `PATH`, else the macOS application bundle) |
| conda `cad_env` ([env/cad_env.lock.yml](https://github.com/crentb/agentic-bioinspired-cad/blob/main/env/cad_env.lock.yml)) | CadQuery, mesh tools, print audit, damage tolerance, the loop | `ABCAD_CAD_PYTHON` |
| conda `sfepy_env` ([env/sfepy_env.lock.yml](https://github.com/crentb/agentic-bioinspired-cad/blob/main/env/sfepy_env.lock.yml)) | linear and finite-strain FEA solves | `ABCAD_SFEPY_PYTHON` |
| MOOSE (combined module) | phase-field fracture decks | `ABCAD_MOOSE_EXEC` |
| Ollama | the critic and the repair and refine agents | `ABCAD_LLM_BASE_URL` (loopback only unless `ABCAD_ALLOW_REMOTE_LLM=1`) |

### Models

| Role | Model | Obtained from |
|---|---|---|
| Code emitter (Phase 1) | `meta-llama/Llama-3.2-3B-Instruct` with the Bioinspired3D LoRA adapter of Luu and Buehler, [`rachelkluu/Bioinspired3D`](https://huggingface.co/rachelkluu/Bioinspired3D) | Hugging Face (the base model is gated: accept its license, then `hf auth login`) |
| Render critic | `qwen3-vl:8b` | `ollama pull qwen3-vl:8b` |
| Repair and refine | `qwen2.5-coder:7b` | `ollama pull qwen2.5-coder:7b` |
| Retrieval embeddings | `BAAI/bge-small-en-v1.5` | Hugging Face |

Model weights are downloaded by the user and remain under their own licenses. The three Hugging Face models default to the commits the validation runs used (base model `0cb88a4`, adapter `4753927`, embedder `5c38ec7`), so a later upload cannot change what a default run loads; override them with `ABCAD_BASE_REVISION`, `ABCAD_LORA_REVISION` and `ABCAD_EMBED_REVISION`. The critic needs an 8k context, so start Ollama with:

```bash
OLLAMA_CONTEXT_LENGTH=8192 OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_NUM_PARALLEL=1 OLLAMA_KEEP_ALIVE=2m ollama serve
```

## Quick start

Build a structure directly:

```bash
# Woven cubic lattice, Blender-free: centerlines -> watertight tube sweep -> render
abcad-woven --stage all_np --topology cubic --cells 2 2 2 --unitcell 40 --reff_over_L 0.111 \
    --nrev 1.0 --fiber_radius 0.4 --stl out/woven_cubic.stl --png out/woven_cubic.png

# Double-twist Bouligand laminate with modeled weak-plane grooves (headless Blender)
blender -b -P abcad/generators/helicoidal.py -- --progression double_twist --delta_a 10 --delta_b 5 \
    --plies 40 --interface groove --export_stl --stl_path out/double_twist.stl

# Enamel decussation lattice with a sigmoid twist law
abcad-enamel --twist_type sigmoid --scale 4 --stl out/enamel_sigmoid.stl
```

Run the design loop:

```bash
abcad-agent "a woven cubic lattice metamaterial"                        # full two-phase run
abcad-agent --use-code saved_script.py "a woven cubic lattice metamaterial"   # Phase 2 only, on a saved script
```

Verify a part:

```bash
abcad-print-audit --stl out/woven_cubic.stl --process fdm          # TM-2 printability verdict
abcad-damage-tolerance --stl out/woven_cubic.stl --voxel 1.0       # TM-3 flaw-seeded stiffness retention
abcad-voxel-mesh --stl out/woven_cubic.stl --voxel 0.6 --msh out/woven_cubic.msh
"$ABCAD_SFEPY_PYTHON" -m abcad.fea.run_tension_finite --msh out/woven_cubic.msh --max-strain 0.01 --nsteps 2
```

Every tool writes under `./out` (override with `ABCAD_OUT`). The [justfile](https://github.com/crentb/agentic-bioinspired-cad/blob/main/justfile) wraps each workflow, including the MOOSE fracture decks (`just --list`).

## Repository layout

```text
abcad/
  agent/          the design loop: settings, code emitter, retrieval, Blender runner, critic,
                  repair and refine, manufacturability gate, routing, run manifest, CLI
  generators/     helicoidal / Bouligand, woven (Tier 1 and Tier 2), enamel decussation
  printing/       TM-2 print audit, certified FDM variants, watertight remeshing
  fea/            plated voxel-hex meshing, linear and finite-strain tension, TM-3 damage tolerance
  fracture/       MOOSE phase-field fracture and J-integral decks, generators, analysis, rendering (TM-6)
  dataset/        prompt vocabulary for the generator families
  reporting/      static HTML mission-control dashboard
  data/           retrieval corpora, reference renders, exemplar scripts (package data)
  _vendor/        third-party woven-lattice engine, carried verbatim (MIT)
results/          text evidence records behind every documented number
docs/             design documents, figures, schematic, controlled QMS documents
env/              conda lockfiles for the CAD and FEA environments
tests/            fast suite; host-stack tests are marked slow
```

## Documentation

| Document | Contents |
|---|---|
| [AGENT.md](https://github.com/crentb/agentic-bioinspired-cad/blob/main/docs/AGENT.md) | The design loop: phases and memory model, state machine, verdict schema, Blender protocol, configuration, operating rules |
| [GENERATORS.md](https://github.com/crentb/agentic-bioinspired-cad/blob/main/docs/GENERATORS.md) | The three generator families: parameters with units and meaning, rotation and twist laws, commands |
| [WORKFLOWS.md](https://github.com/crentb/agentic-bioinspired-cad/blob/main/docs/WORKFLOWS.md) | Build-to-print runbook for each structure, material and slicer profiles, acceptance checklist |
| [PRINTING.md](https://github.com/crentb/agentic-bioinspired-cad/blob/main/docs/PRINTING.md) | TM-2 print audit, FDM and resin verdicts, auto-scaling, remeshing, certified print files |
| [FEA.md](https://github.com/crentb/agentic-bioinspired-cad/blob/main/docs/FEA.md) | Plated voxel-hex meshing, linear and finite-strain tension, the AMG solver, TM-3 method and rankings |
| [FRACTURE.md](https://github.com/crentb/agentic-bioinspired-cad/blob/main/docs/FRACTURE.md) | TM-6 MOOSE instrument: validation ladder, orientation, J-integral, deflection, Bouligand, 3D, and woven-cell results |
| [LITERATURE.md](https://github.com/crentb/agentic-bioinspired-cad/blob/main/docs/LITERATURE.md) | Scientific basis: Bouligand, woven, and enamel architectures; single-material design rules |
| [PERF.md](https://github.com/crentb/agentic-bioinspired-cad/blob/main/docs/PERF.md) | Resource envelope on a 16 GB machine: solver, instrument, and loop timings |
| [ABCAD-SOP-001](https://github.com/crentb/agentic-bioinspired-cad/blob/main/docs/qms/ABCAD-SOP-001_loop_operation.pdf) | Controlled standard operating procedure for the loop |
| [ABCAD-QMS-002](https://github.com/crentb/agentic-bioinspired-cad/blob/main/docs/qms/ABCAD-QMS-002_definitions_and_tests.pdf) | Controlled definitions and test methods TM-1 to TM-6 |
| [pipeline_schematic.pdf](https://github.com/crentb/agentic-bioinspired-cad/blob/main/docs/pipeline_schematic.pdf) | One-page end-to-end schematic |

## Testing and CI/CD

```bash
pytest -m "not slow"    # fast suite (what CI runs)
pytest                  # everything, including the host-stack tests (Blender, conda environments)
```

Every push and pull request runs one gate, defined in [ci.yml](https://github.com/crentb/agentic-bioinspired-cad/blob/main/.github/workflows/ci.yml):

- **Quality:** ruff, black, mypy (advisory), and pytest with coverage on Python 3.10 to 3.14; `CITATION.cff` validation.
- **Packaging:** the sdist and wheel are built, checked with twine, and the wheel is installed into a clean environment and imported.
- **Security (blocking):** gitleaks secret detection over the full history, bandit static analysis at medium severity and above, and pip-audit against known vulnerabilities.
- **Container:** the image is built, scanned with trivy (blocking on fixable critical and high findings), runs the test suite, and ships an SPDX software bill of materials signed keylessly with cosign.

CodeQL analyzes the Python code and the workflows themselves, pull requests pass a dependency review, and the OpenSSF Scorecard rates the repository's supply-chain posture. Every action is pinned to a full commit SHA, workflow tokens are least-privilege, and the whole gate re-runs weekly on `main` ([scheduled-scan.yml](https://github.com/crentb/agentic-bioinspired-cad/blob/main/.github/workflows/scheduled-scan.yml)). A version tag re-runs the gate on the tagged commit before [release.yml](https://github.com/crentb/agentic-bioinspired-cad/blob/main/.github/workflows/release.yml) publishes to PyPI through Trusted Publishing (no stored tokens), pushes a scanned, cosign-signed image with SLSA build provenance to the GitHub Container Registry, and creates the GitHub Release. The loop executes model-generated code inside Blender; the threat model and vulnerability reporting are in [SECURITY.md](https://github.com/crentb/agentic-bioinspired-cad/blob/main/SECURITY.md).

## Citation

Please cite the software. GitHub's "Cite this repository" button reads [CITATION.cff](https://github.com/crentb/agentic-bioinspired-cad/blob/main/CITATION.cff).

```bibtex
@software{renteria_agentic_bioinspired_cad,
  author  = {Renteria, Cameron B.},
  title   = {agentic-bioinspired-cad},
  version = {0.1.0},
  year    = {2026},
  url     = {https://github.com/crentb/agentic-bioinspired-cad}
}
```

## Acknowledgments

The design loop builds on Bioinspired123D by Rachel K. Luu and Markus J. Buehler: its code emitter is their Bioinspired3D LoRA adapter, and its emit, render, critique and repair design follows their system (R. K. Luu and M. J. Buehler, "Bioinspired123D: generative 3D modeling system for bioinspired structures", *AI for Science* 2, 025004 (2026), [doi:10.1088/3050-287X/ae61d1](https://doi.org/10.1088/3050-287X/ae61d1); [code](https://github.com/lamm-mit/Bioinspired123D)). No code from that repository is included here. The woven-lattice engine is Molly Carton's [woven-lattice](https://github.com/mollyacarton/woven-lattice), vendored verbatim under the MIT License, and three fracture decks are adapted from [MOOSE](https://github.com/idaholab/moose) test inputs and stay under LGPL-2.1. Please cite the Bioinspired123D paper alongside this software when you use the design loop.

## License

Apache-2.0, except the vendored woven-lattice engine (MIT) and the three MOOSE-derived fracture decks (LGPL-2.1). See [LICENSE](https://github.com/crentb/agentic-bioinspired-cad/blob/main/LICENSE) and [NOTICE](https://github.com/crentb/agentic-bioinspired-cad/blob/main/NOTICE).

## Bioinspired123D

**Generative 3D Modeling System for Bioinspired Structures**

**Authors:** Rachel K. Luu, Markus J. Buehler (2026)\
**Corresponding author:** mbuehler@mit.edu
