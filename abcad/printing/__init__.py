"""
abcad.printing — single-material print certification and print-file preparation.

MODULES
    print_audit        TM-2 printability audit: watertight/manifold re-check, overhang fraction,
                       EDT wall-thickness and clearance ladders, enclosed voids, per-process verdict
                       (FDM / resin) with concrete fixes; writes CSV + Markdown reports.
    fdm_variants       uniformly scaled (and optionally grip-plated) FDM variants of an STL, plus
                       deterministic target-size normalization used by the agent's print gate.
    remesh_watertight  voxel remesh of open-tube lattices into a watertight, smooth print mesh.

INPUTS / OUTPUTS
    Each tool reads STLs and writes under ``./out`` by default (override with ABCAD_OUT). All three
    need pyvista (+ scipy / vtk) — the conda ``cad_env`` provides them. Import-light: nothing is
    imported here. See docs/PRINTING.md.
"""
