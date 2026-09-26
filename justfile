# =====================================================================================
# justfile — agentic-bioinspired-cad task runner
#
# Encodes the operating-procedure incantations (ABCAD-SOP-001) so they cannot be
# mistyped. Memory rules still apply: one heavy step at a time, and run heavy steps
# (meshing, solves, renders) under a swap watchdog on a 16 GB machine.
#
# List recipes:            just --list
# Run from the repository root (just does this automatically), so `python -m abcad...`
# finds the package even where it is not pip-installed.
#
# Interpreters and tools are resolved from environment variables; nothing below is a
# machine-specific path. Each default reproduces the standard conda / MOOSE layout:
#   ABCAD_CAD_PYTHON    Python of the conda CAD env (pyvista, vtk, numpy-stl, meshio, cadquery)
#                       default: <conda base>/envs/cad_env/bin/python, where <conda base> is
#                       derived from $CONDA_EXE (<base>/bin/conda, set by `conda init`);
#                       falls back to `python` on PATH.
#   ABCAD_SFEPY_PYTHON  Python of the conda SfePy env; default <conda base>/envs/sfepy_env/bin/python.
#   ABCAD_BLENDER       Blender executable; default `blender` on PATH (on macOS without a
#                       `blender` shim, point it at the app bundle's Contents/MacOS/Blender).
#   ABCAD_MOOSE_EXEC    MOOSE application; default $HOME/projects/moose/modules/combined/combined-opt
#                       (MOOSE's documented clone location), else `combined-opt` on PATH.
#   ABCAD_MOOSE_ENV     conda env that provides MOOSE's runtime libraries; default `moose`.
#   ABCAD_OUT           output root for every tool; default ./out (never the package directory).
# =====================================================================================

# --- interpreter / tool resolution (see the header for the defaults' rationale) ---------
# Shell snippet: print <conda base>/envs/<env>/bin/python if it exists, else "python".
CAD := env_var_or_default("ABCAD_CAD_PYTHON", `p="${CONDA_EXE%/bin/conda}/envs/cad_env/bin/python"; if [ -n "${CONDA_EXE:-}" ] && [ -x "$p" ]; then echo "$p"; else echo python; fi`)
SFEPY := env_var_or_default("ABCAD_SFEPY_PYTHON", `p="${CONDA_EXE%/bin/conda}/envs/sfepy_env/bin/python"; if [ -n "${CONDA_EXE:-}" ] && [ -x "$p" ]; then echo "$p"; else echo python; fi`)
BLENDER := env_var_or_default("ABCAD_BLENDER", "blender")
MOOSE := env_var_or_default("ABCAD_MOOSE_EXEC", `p="$HOME/projects/moose/modules/combined/combined-opt"; if [ -x "$p" ]; then echo "$p"; else echo combined-opt; fi`)
MOOSE_ENV := env_var_or_default("ABCAD_MOOSE_ENV", "moose")
OUT := env_var_or_default("ABCAD_OUT", "out")

# Show the recipe list when `just` is run without arguments.
default:
    @just --list

# Print how every interpreter / tool resolved on this machine (debug the defaults above).
which:
    @echo "CAD       = {{CAD}}"
    @echo "SFEPY     = {{SFEPY}}"
    @echo "BLENDER   = {{BLENDER}}"
    @echo "MOOSE     = {{MOOSE}}  (conda env: {{MOOSE_ENV}})"
    @echo "OUT       = {{OUT}}"

# -------------------------------------------------------------------------------------
# Verification
# -------------------------------------------------------------------------------------

# Needs only numpy + scipy + pytest on the active `python` (CI runs exactly this).
# Fast, Blender-free verification: generator/critic/dataset suites + gold tests over results/.
verify:
    python -m pytest -q -m "not slow"

# Blender, sfepy and large-artifact tests skip cleanly when unavailable; needs pytest importable
# by the CAD interpreter. Point ABCAD_ARTIFACTS_DIR at a folder with woven_fea_small.stl to run
# the normalization gold test.
# Full suite under the CAD env, including the slow host-stack smoke tests.
verify-all:
    {{CAD}} -m pytest -q

# -------------------------------------------------------------------------------------
# Generators
# -------------------------------------------------------------------------------------

# Example: just helicoidal --progression double_twist --plies 40 --export_stl --stl_path out/dt.stl
# Helicoidal / Bouligand laminate in headless Blender (args are passed after Blender's `--`).
helicoidal *ARGS:
    mkdir -p {{OUT}}
    {{BLENDER}} -b -P abcad/generators/helicoidal.py -- {{ARGS}}

# Tier-1 woven lattice, Blender-free: centerlines -> numpy-stl sweep -> watertight report -> PNG.
woven TOPOLOGY="cubic" STL=(OUT + "/woven_cubic.stl") *ARGS="":
    {{CAD}} -m abcad.generators.woven.build --stage all_np --topology {{TOPOLOGY}} --stl {{STL}} {{ARGS}}

# Tier-2 compact woven lattice in headless Blender (the language-model-emittable variant).
woven-simple *ARGS:
    mkdir -p {{OUT}}
    {{BLENDER}} -b -P abcad/generators/woven/woven_simple.py -- {{ARGS}}

# Decussated enamel-rod lattice (numpy-stl sweep). Example: just enamel --scale 4 --twist_type sigmoid
enamel *ARGS:
    {{CAD}} -m abcad.generators.enamel {{ARGS}}

# -------------------------------------------------------------------------------------
# FEA and the damage-tolerance screen (TM-3)
# -------------------------------------------------------------------------------------

# STL -> plated voxel-hex mesh (+ <msh>.json sidecar with A0 / H0) for the SfePy drivers.
mesh STL MSH VOXEL="0.6":
    {{CAD}} -m abcad.fea.voxel_plate_mesh --stl {{STL}} --voxel {{VOXEL}} --msh {{MSH}}

# The solve runs via `conda run` in sfepy_env and needs the biomimetic-lattice-pipeline run
# context (installed package, or ABCAD_BIOMIMETIC_PIPELINE). ABCAD_FEA_SOLVER=amg for big meshes.
# Linear small-strain tension of a plated mesh -> e_eff.json.
tension MSH:
    {{SFEPY}} -u abcad/fea/run_tension.py --msh {{MSH}}

# Finite-strain (neo-Hookean, total-Lagrangian) tension curve of a plated mesh.
tension-finite MSH *ARGS:
    {{SFEPY}} -u -m abcad.fea.run_tension_finite --msh {{MSH}} {{ARGS}}

# Damage-tolerance screen, TM-3 baseline protocol (voxel 1.25 for near-solid plates).
rank STL VOXEL="1.0":
    {{CAD}} -u -m abcad.fea.damage_tolerance --stl {{STL}} --voxel {{VOXEL}} --samples 3 --nflaws 3 --flaw-radius-mm 1.5

# -------------------------------------------------------------------------------------
# Printing (TM-2)
# -------------------------------------------------------------------------------------

# Printability audit, TM-2 (PROCESS: fdm | resin | both).
audit STL PROCESS="fdm":
    {{CAD}} -m abcad.printing.print_audit --stl {{STL}} --process {{PROCESS}}

# Uniformly scaled (and optionally plated) FDM variants of an STL -> $ABCAD_OUT/print/.
fdm-variants STL SCALES="1.5,2.0" *ARGS="":
    {{CAD}} -m abcad.printing.fdm_variants --stl {{STL}} --scales {{SCALES}} {{ARGS}}

# Voxel remesh of an open-tube lattice into a watertight, smooth print mesh.
remesh STL OUTSTL VOXEL="0.2":
    {{CAD}} -m abcad.printing.remesh_watertight --stl {{STL}} --out {{OUTSTL}} --voxel {{VOXEL}}

# -------------------------------------------------------------------------------------
# Fracture instruments (TM-6, MOOSE)
# -------------------------------------------------------------------------------------

# The deck is COPIED into $ABCAD_OUT/fracture first because MOOSE writes its outputs next to
# the input file, and nothing may be written into the package directory. Run
# `just fracture validate_uniaxial` first: it is the mandatory validation gate (E_eff must come
# back as 3000 MPa). Extra ARGS are MOOSE command-line overrides (e.g. Outputs/file_base=x).
# Run a shipped MOOSE deck (abcad/fracture/decks/<DECK>.i) in $ABCAD_OUT/fracture.
fracture DECK="validate_uniaxial" *ARGS="":
    mkdir -p {{OUT}}/fracture
    cp abcad/fracture/decks/{{DECK}}.i {{OUT}}/fracture/{{DECK}}.i
    cd {{OUT}}/fracture && conda run --no-capture-output -n {{MOOSE_ENV}} {{MOOSE}} -i {{DECK}}.i {{ARGS}}

# Generate a Bouligand-coupon crack-twisting deck (pitch in deg/ply, number of plies).
deck-bouligand PITCH="30" PLIES="6":
    mkdir -p {{OUT}}/fracture
    {{CAD}} -m abcad.fracture.tm6_make_bouligand_deck {{PITCH}} {{PLIES}} {{OUT}}/fracture/bouligand_d{{PITCH}}_n{{PLIES}}.i

# Generate the 3D twisting-crack deck (pitch in deg/ply, number of ply slabs).
deck-3d-twist PITCH="30" SLABS="6":
    mkdir -p {{OUT}}/fracture
    {{CAD}} -m abcad.fracture.tm6_make_3d_twist_deck {{PITCH}} {{SLABS}} {{OUT}}/fracture/twist3d_p{{PITCH}}_n{{SLABS}}.i

# Generate the 3D J-integral deck (pitch in deg/ply, number of ply slabs).
deck-3d-jintegral PITCH="30" SLABS="5":
    mkdir -p {{OUT}}/fracture
    {{CAD}} -m abcad.fracture.tm6_make_3d_jintegral_deck {{PITCH}} {{SLABS}} {{OUT}}/fracture/jint3d_p{{PITCH}}_n{{SLABS}}.i

# Generate a non-fused woven-cell contact deck (N x N grid, cut warp index or -1, preload mm).
deck-woven-cell N="2" CUT="-1" PRELOAD="0.0":
    mkdir -p {{OUT}}/fracture
    {{CAD}} -m abcad.fracture.tm6_make_woven_cell_deck {{N}} {{OUT}}/fracture/wcell{{N}}_cut{{CUT}}_pre{{PRELOAD}}.i {{CUT}} {{PRELOAD}}

# Generate the woven fracture deck (MODE: fused | nonfused).
deck-woven-fracture MODE="nonfused" *ARGS="":
    mkdir -p {{OUT}}/fracture
    {{CAD}} -m abcad.fracture.tm6_make_woven_fracture_deck {{MODE}} {{OUT}}/fracture/wfrac_{{MODE}}.i {{ARGS}}

# Work of fracture vs rod angle from a tm6_a<angle>.csv sweep (default: the banked sweep).
tm6-analyze DIR="results/fracture/orientation_sweep":
    {{CAD}} -m abcad.fracture.tm6_analyze {{DIR}}

# -------------------------------------------------------------------------------------
# Reporting
# -------------------------------------------------------------------------------------

# Regenerate the static HTML mission-control dashboard from the records under $ABCAD_OUT.
report:
    {{CAD}} -m abcad.reporting.mission_control

# -------------------------------------------------------------------------------------
# TODO (lead): agent-loop and operations recipes — wire these to the abcad.agent entry
# points once they land. The source recipes were:
#   daemon       Ollama daemon capped and at the MANDATORY 8k context (ABCAD-QMS-002 §3.5):
#                OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_NUM_PARALLEL=1 OLLAMA_KEEP_ALIVE=2m
#                OLLAMA_CONTEXT_LENGTH=8192 <ollama> serve   (executable via an ABCAD_* variable)
#   loop         full agentic run: Phase 1 LoRA emit -> Phase 2 render/critic/repair loop
#                (PROMPT="a woven cubic lattice metamaterial")
#   loop-repair  Phase-2-only repair run on saved Blender code (the TM-4 convergence-run form)
#                (CODE="$ABCAD_OUT/agent_tmp/woven.py", PROMPT=...)
#   emit         Phase-1-only LoRA emit (no Ollama/Blender) to inspect what the model writes
#                (OUT="$ABCAD_OUT/agent_tmp/emit.py", PROMPT=...)
#   qms          rebuild the controlled QMS PDFs in docs/qms (ABCAD-SOP-001, ABCAD-QMS-002) with
#                latexmk, then `latexmk -c`
#   status       machine + repo health: `sysctl vm.swapusage`, `ollama ps`, `git status -sb`
# -------------------------------------------------------------------------------------
