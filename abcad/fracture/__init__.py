"""
abcad.fracture — MOOSE fracture instruments (TM-6): crack twisting, J-integral, woven contact/failure.

PURPOSE
    The TM-3 stiffness screen cannot see crack-path mechanisms such as the crack twisting proposed
    for decussation / Bouligand architectures. This subpackage probes them with MOOSE phase-field
    fracture and J-integral decks, and turns the solver output into load, energy and J-integral
    measures, crack-path comparisons and videos. See docs/FRACTURE.md for what the runs resolve.

CONTENTS
    decks/                      MOOSE reference input decks (package data; locate them with
                                ``abcad.resources.decks_dir()`` / ``deck_path(name)``, never via the
                                working directory). Copy a deck into a run directory before solving,
                                because MOOSE writes its outputs next to the input file.
    tm6_make_*_deck.py          pure-Python deck generators (Bouligand strips, 3D twisting crack,
                                3D J-integral, non-fused woven cell with frictional contact, woven
                                fused vs non-fused fracture).
    tm6_analyze.py              work of fracture / peak load vs rod angle from the sweep CSVs.
    tm6_fracture_compare.py     fused vs non-fused woven fracture: crack-path panels + work ratio.
    tm6_render_*.py             off-screen pyvista / matplotlib renders and ffmpeg videos of the runs.

INTERPRETERS
    Deck generators and tm6_analyze need only the standard library / numpy. The renderers and the
    comparison need pyvista + matplotlib (conda ``cad_env``) and ``ffmpeg`` on PATH for videos. MOOSE
    itself runs via ``conda run -n moose "$ABCAD_MOOSE_EXEC" -i <deck>.i``. Nothing is imported here.
"""
