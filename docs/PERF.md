# Performance and resource envelope

The whole pipeline — language models, Blender, the SfePy finite-element chain, and MOOSE — runs on
one workstation: an Apple-silicon macOS host with **16 GB of unified memory**. Memory, not compute,
is the binding constraint, so every heavy step runs under a watchdog that samples swap usage and
child-process memory every 2 s and terminates the step before the host runs out of memory (system
protection section of [ABCAD-SOP-001](qms/ABCAD-SOP-001_loop_operation.pdf)). This page records the measured
timings and memory peaks that set the operating limits. Numbers are from that host; expect
variation elsewhere.

## 1. Linear finite-element solves: direct versus algebraic multigrid

| Mesh | Hexahedra (nodes) | Solver | Wall time | Memory | Outcome |
|---|---|---|---|---|---|
| Woven specimen, 0.8 mm voxels | 17,685 (28,565) | direct (SciPy) | ≈ 1 min | ≈ 1.65 GB resident | reference envelope |
| Woven specimen, finer mesh (nonlinear solve) | ≈ 35,000 | direct (SciPy) | > 39 min | — | terminated by the watchdog |
| Woven specimen, 0.5 mm voxels (`woven_v05.msh`) | 63,334 (93,767) | AMG (pyamg, smoothed aggregation + CG) | **60 s** | swap peak 2,523 MB | completed; lineage-exact |

With the direct solver the practical band was 15–20 thousand hexahedra, which forced 1.0–1.25 mm
voxels and left 0.2 mm plies and grooves sub-voxel. Setting `ABCAD_FEA_SOLVER=amg` moves the
envelope past 100 thousand hexahedra: the 0.5 mm re-ranking of ten architectures used intact meshes
of 61,006–133,788 hexahedra, each with three damaged replicates, at a swap peak of at most 1.86 GB.
The AMG path reproduced the direct solver to four to five significant figures before any number was
accepted (82.698 versus 82.70 MPa and 941.179 versus 941.2 MPa; [FEA.md §4](FEA.md)).

## 2. Instrument timings

| Instrument | Case | Time | Memory |
|---|---|---|---|
| Damage tolerance (TM-3), 1.0 mm protocol | 29 mm woven specimen: intact solve + 3 damaged replicates (8,262 intact hexahedra) | ≈ 3.5 min total | swap unchanged |
| Print audit (TM-2) | automatic voxel size keeps grids at ≤ ≈ 33 million voxels | — | ≈ 0.7 GB peak (design bound with float64 distance transforms) |
| MOOSE 2D phase-field crack (TM-6) | single-edge-notched specimen, one orientation, run to failure | 32–48 s per run | swap peak 1.5 GB |
| MOOSE 3D phase-field crack | 30 × 30 × 15 hexahedra (≈ 50,000 degrees of freedom), through-thickness crack | — | 1.47 GB peak |
| MOOSE 3D twisting crack | 36 × 26 × 18 hexahedra, six rotating ply slabs | ≈ 4 min per time step during propagation | ≤ ≈ 2.8 GB |
| MOOSE contact, non-fused woven cell | 2 × 2 and 3 × 3 cells with frictional crossings | — | swap peak 754 MB |
| MOOSE build | `solid_mechanics` application (`make -j4`, conda-provided libMesh/PETSc); `combined` application | `combined`: 12 min | swap peak 1,873 MB (`solid_mechanics` build) |

A smooth, quasi-static propagation of the 3D twisting crack is out of reach at about four minutes
per step on this host; it is a job for a parallel (MPI) run.

## 3. Agentic loop

A certified run from the live validation of 2026-09-26 (`results/agent_runs/2026-09-26_12-16-16`),
on the prompt "a woven cubic lattice metamaterial" and starting from a recorded emit that fails to
execute, has the following timeline (from the run's event log):

| Elapsed | Event |
|---|---|
| 0:00 | Saved code injected; the first headless Blender run fails with an API error |
| 0:04 | Code-fixer attempt 1; the run still fails with the same error |
| 0:56 | Code-fixer attempt 2 reproduces a refuted script; the stall guard raises the temperature to 0.5 |
| 1:44 | Code-fixer attempt 3; the run succeeds (2.6 s in Blender) |
| 4:05 | Critic: partial, stable (rejected); code-designer iteration 1 |
| 5:39 | Iteration 1 runs (3.5 s in Blender) |
| 7:27 | Critic: good, stable (approved) |
| 8:11 | Print gate: 17.9 % of material thinner than 0.8 mm; the auto-scaled ×1.6 variant is re-audited as PRINT; certified, manifest written |

End to end the run took 8.2 minutes and grew swap by 433 MB. Across the five validation runs that
reached Phase 2, a run took 4.9 to 8.2 minutes and swap grew by at most 433 MB, against a 5,120 MB
abort threshold ([validation record](../results/agent_runs/validation_2026-09-26/E2E_REPORT.md)).

**Model memory.** The two-phase design keeps large models from co-residing: the code emitter
(Llama-3.2-3B-Instruct with a LoRA adapter, float16 on the Apple GPU, about 8–9 GB) runs in a child
process that exits before the critic and repair models load. The repair model (`qwen2.5-coder:7b`,
4.7 GB) and the vision critic (`qwen3-vl:8b`, 6.1 GB) are served by Ollama with one model loaded
at a time, one request in parallel, a two-minute keep-alive, and an 8,192-token context — the
critic prompt is about 3.5 thousand tokens, and at the 4,096-token default the verdict is
truncated. Because a model can outlive a run for its keep-alive, the runner asks the daemon to
unload every resident model before Phase 1; without that, a run started right after another
loads the emitter next to the critic, which drove the validation host deep into swap.
