"""
abcad.fea — FEA bridge for single-material lattices (voxel-hex meshing + SfePy tension).

Turns a watertight lattice STL (e.g. the woven generators' output) into a plated voxel-hex mesh and
runs uniaxial tension/compression in SfePy, mirroring the voxel-hex route of the author's
biomimetic-lattice-pipeline package (``biomimetic_pipeline``). Blender-free; the geometry stage runs
in the conda ``cad_env``, the solves in ``sfepy_env``. See docs/FEA.md.

Modules:
  voxel_plate_mesh    — STL -> occupancy -> loading plates -> gmsh-2.2 hex .msh (+ render). [cad_env]
  run_tension         — drive the linear SfePy solve (via fea_runner_amg) + report E_eff.
  fea_runner_amg      — subprocess wrapper around the stock SfePy problem definition, derived from
                        biomimetic_pipeline.fea.fea_runner (same author) with an opt-in AMG solver.
  run_tension_finite  — finite-strain (neo-Hookean, total-Lagrangian) tension curve.   [sfepy_env]
  damage_tolerance    — flaw-seeded stiffness-retention screen (TM-3), the mission metric. [cad_env]

Several of these files also run as standalone scripts inside conda interpreters where ``abcad`` is
not installed; they fall back to sibling-file imports in that case. Nothing is imported here.
"""
