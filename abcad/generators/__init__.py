"""
abcad.generators — parametric, single-material, 3D-printable structure generators.

PURPOSE
    Each generator turns a small set of physically meaningful parameters (mm / degrees) into a
    printable geometry whose damage tolerance comes from ARCHITECTURE alone (no hard/soft material
    contrast). See docs/GENERATORS.md for the design notes and build runbooks.

MODULES
    helicoidal        Bouligand / helicoidal laminates (rotation laws, weak-plane interfaces).
                      Runs inside Blender (``blender -b -P abcad/generators/helicoidal.py -- ...``);
                      its geometry math is pure Python and unit-tested without Blender.
    woven.build       woven metamaterial lattices on the vendored woven-lattice engine: fiber
                      centerlines (numpy + scipy), then a Blender bevel sweep or a Blender-free
                      numpy-stl sweep with a watertight report and a pyvista render.
    woven.woven_simple  compact, dependency-free woven generator the language model can emit as a
                      single self-contained Blender script (simplified node model).
    enamel            decussated enamel-rod ("rotating plywood") lattices, swept to STL with the
                      woven numpy-stl tube mesher (conda ``cad_env``).

INPUTS / OUTPUTS
    Import-light: nothing is imported here. Each module documents its own CLI, inputs and outputs.
"""
