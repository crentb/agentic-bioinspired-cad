"""
abcad.generators.woven — woven metamaterial lattice generators (two fidelity tiers).

MODULES
    build          Tier 1, paper-exact: adapter + CLI around the vendored woven-lattice geometry
                   engine (abcad/_vendor/woven_lattice). Stages: ``centerlines`` (numpy + scipy),
                   ``sweep`` / ``all`` (Blender bevel sweep), ``sweep_np`` / ``all_np`` (Blender-free
                   numpy-stl sweep + watertight report + pyvista render).
    woven_simple   Tier 2, compact: math + guarded ``bpy`` only (no scipy), emittable by the language
                   model as one self-contained Blender script; simplified shared-node model.

INPUTS / OUTPUTS
    Import-light: nothing is imported here. See each module's docstring for its CLI.
"""
