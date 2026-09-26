# Live end-to-end validation of `abcad.agent` (2026-09-26)

This record documents the live validation of the design loop on its target host, against the
acceptance procedure of the loop convergence test (TM-4, ABCAD-QMS-002). The machine-readable
verdicts are in [`e2e_summary.json`](e2e_summary.json), each step's watchdog summary is in
[`watchdog/`](watchdog/), the retrieval check's output is in [`retrieval.log`](retrieval.log), and
the manifest of every run that reached Phase 2 sits beside this folder in
`results/agent_runs/<run>/run_manifest.json`.

## Setup

| Item | Value |
|---|---|
| Host | Apple-silicon Mac, 16 GB unified memory |
| Geometry | Blender 5.1.2, headless |
| Chat models | Ollama 0.30.7, a dedicated daemon with `OLLAMA_CONTEXT_LENGTH=8192`, `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_KEEP_ALIVE=2m`; critic `qwen3-vl:8b`, repair and refine `qwen2.5-coder:7b` |
| Pinned snapshots | base `0cb88a4f764b7a12671c53f0838cd831a0843b95`, adapter `47539274e56c7b38d052bfe6334a2868029a26b8`, embedder `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` |
| Gate | deep print audit required (`ABCAD_REQUIRE_DEEP_AUDIT=1`) |
| Guard | every heavy step under a watchdog: stop the step if swap grows by more than 5,120 MB (4,096 MB for Phase-1-only steps) or it runs longer than 45 min |
| Regression fixture | `tests/agent/fixtures/woven_failing_emit.py`, a recorded emit that stops with `'Object' object has no attribute 'splines'` |

## Verdicts

| Check | Result |
|---|---|
| E2E-1 Phase-1 emit | **Pass.** 1,857 characters that parse as Python and start with `import bpy`; no Ollama model resident during the emit; 123 s; swap +418 MB |
| E2E-2 Smoke | **Pass.** The printed excerpt is the model's completion (Blender code), not the prompt; 121 s |
| E2E-3 Regression convergence, 3 runs | **Pass.** All three runs certified (below) |
| E2E-4 Full two-phase runs | **Pass on the repeat** (below). The first attempt failed from memory co-residency and orphaned emitter processes; both causes were fixed and the repeat recreated the failing situation on purpose |
| E2E-5 Target size 58 mm | **Pass.** The approved part was normalized from 90.6 to 58.0 mm (×0.640); the sized STL was audited (all material thinner than 0.8 mm at that size) and auto-scaled ×2.7 to PRINT; 317 s |
| E2E-6 Retrieval grounding | **Pass.** Each query ranks its own reference first: woven render 0.934, Bouligand render 0.842, woven code exemplar 0.808 |
| E2E-7 Offline sovereignty | **Pass.** With `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` the run certified as the online runs did; all 108 sampled sockets of its process tree were loopback |

Across all 28 chat requests the daemon truncated none; the largest context was 4,757 tokens.

## Regression runs (E2E-3) and the two variants (E2E-5, E2E-7)

| Run | Critic verdicts | Thin at 0.8 mm | Auto-scale | Result | Time | Swap growth |
|---|---|---|---|---|---|---|
| `2026-09-26_12-04-16` | good, stable (approve) | 13.4 % | ×1.6 → PRINT | certified | 376 s | +56 MB |
| `2026-09-26_12-10-52` | good, stable (approve) | 13.4 % | ×1.6 → PRINT | certified | 304 s | +0 MB |
| `2026-09-26_12-16-16` | partial, stable (reject); after one refine: good, stable (approve) | 17.9 % | ×1.6 → PRINT | certified | 492 s | +433 MB |
| `2026-09-26_12-24-48` (58 mm) | good, stable (approve) | 100 % at 58 mm | ×2.7 → PRINT | certified | 317 s | +391 MB |
| `2026-09-26_12-30-26` (offline) | good, stable (approve) | 13.4 % | ×1.6 → PRINT | certified | 291 s | +0 MB |

Every run met the per-run criteria: the fixture's first execution fails with the `splines` error
and is repaired within the three-attempt budget (three attempts in every run); the gate runs
exactly once; `approved` and `ever_approved` are both true in every certified manifest; the
certified artifact exists; and the repaired fixture measures 90.6 × 90.6 × 90.597 mm with an
overhang fraction of 0.1392. The third run exercised the whole path: the critic rejected the
repaired lattice ("lacks explicit helical fiber winding on cube edges"), the refine agent added
wound fibers along the edges, and the critic approved the result. Its refined geometry is thinner
in places (17.9 % below 0.8 mm), and the same ×1.6 scale certifies it.

## E2E-4: first attempt, causes, and fixes

Both full runs were stopped by the watchdog during Phase 1: the woven run after 179 s at +5,175 MB
of swap, and the default-prompt run 27 s after it started, at +5,475 MB. The loop logic was not
reached. Two causes compounded:

1. **Co-residency.** The woven run started 20 s after the offline run, while the daemon still held
   the critic (6.0 GB) for its two-minute keep-alive; the emitter's weights (about 8 GB) finished
   loading at 12:36:03 and the critic unloaded at 12:36:27. The two-phase design assumes no chat
   model is resident when Phase 1 starts, and nothing enforced it.
2. **Orphaned emitters.** The watchdog stopped each run's process group, but the Phase-1 child runs
   in its own session, outside that group. Both children survived with the emitter resident, so the
   second run started with 9.6 GB of swap in use.

Fixes, with unit tests (`tests/agent/test_agent_chat.py`, `tests/agent/test_agent_phase_one.py`):

- Before Phase 1 the runner asks a local Ollama daemon to unload every resident model
  (`abcad.agent.chat.release_resident_models`: `GET /api/ps`, then a request with
  `keep_alive: 0` per model; best effort for any other server). A run started inside an earlier
  run's keep-alive no longer loads the emitter next to the critic.
- While the parent waits on the Phase-1 child, SIGTERM and SIGHUP become an exit (status 128 +
  signal), and every abnormal end of the wait, including Ctrl-C, kills the child's process group
  first.
- The validation watchdog now stops the whole process tree, including children in their own
  session.

### Repeat with the fixes (13:07–13:22)

The repeat recreated the failing situation on purpose: a Phase-2-only warm-up run
(`2026-09-26_13-07-04`, certified) left the critic resident in the daemon ("about a minute" of
keep-alive left), and the first full run started 20 s later.

| Run | Before Phase 1 | Phase 1 | Outcome | Time | Swap growth |
|---|---|---|---|---|---|
| `2026-09-26_13-13-06`, woven prompt | released `qwen3-vl:8b` | 1,857 characters in 137 s | the emitted script ran without repair; approved (good, stable); 13 % thinner than 0.8 mm, ×1.6 → PRINT; **certified** | 306 s | +0 MB |
| `2026-09-26_13-18-33`, default Bouligand prompt | released `qwen3-vl:8b` | 1,077 characters in 74 s | approved (good, stable), gated, refined once, approved again; **approved_gated** (below) | 208 s | +615 MB |

Both runs released the resident critic before loading the emitter, finished Phase 1 before any
Phase-2 step, record `entry.origin = "lora"`, and ended through a router decision with a truthful
manifest; no emitter process survived. The Bouligand emit came out 2.83 × 2.83 × 2.0 mm, because
the emitter works in Blender units: 4.7 % of the material is thinner than the smallest audited
feature (0.3 mm) and the overhang area is 34 %, so the gate had no formable size to scale from
and correctly declined to certify it. A target size (`ABCAD_TARGET_SIZE_MM`, exercised by E2E-5)
normalizes such a part before the audit. The warm-up grew swap by 4,018 MB, within the 5,120 MB
threshold, while the host was also rendering documentation figures.
