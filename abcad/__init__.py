"""
abcad — agentic bioinspired CAD: single-material, damage-tolerant architectures from prompt to print.

PURPOSE
    Top-level package of agentic-bioinspired-cad. It bundles the parametric structure generators,
    the FEA / fracture instruments that rank the generated architectures, the printability tools
    that certify them for fabrication, and the agentic LLM-to-CAD design loop that ties them
    together.

SUBPACKAGES
    abcad.generators   parametric generators: helicoidal / Bouligand laminates (Blender ``bpy``),
                       woven lattices (vendored geometry engine + Blender or numpy-stl sweep), and
                       decussated enamel-rod lattices (numpy-stl sweep).
    abcad.fea          STL -> plated voxel-hex meshing, linear and finite-strain tension (SfePy),
                       and the flaw-seeded damage-tolerance screen (TM-3).
    abcad.fracture     MOOSE phase-field / J-integral fracture decks, deck generators, analysis and
                       rendering scripts (TM-6); the reference decks ship in ``fracture/decks/``.
    abcad.printing     print-readiness audit (TM-2), FDM scaling / grip-plate variants, and the
                       watertight voxel remesher.
    abcad.agent        the agentic design loop (code emitter, retrieval, critic, repair and the
                       single-material manufacturability critic).
    abcad.dataset      prompt vocabulary for the new structural families.
    abcad.reporting    static HTML dashboard over the evidence records.
    abcad.data         runtime data shipped inside the wheel (retrieval corpora, reference renders,
                       exemplar scripts); locate it with :mod:`abcad.resources`.
    abcad._vendor      third-party code carried verbatim (see each directory's README).

FOREIGN INTERPRETERS
    Several modules also run as standalone files inside interpreters where this package is not
    installed (Blender's bundled Python, the conda ``cad_env`` / ``sfepy_env`` environments, the
    MOOSE environment). Those modules guard their optional imports and fall back to sibling-file
    imports, so importing ``abcad`` itself stays light: this file imports no subpackage.

INPUTS / OUTPUTS
    None at import time. Tools write under ``./out`` (override with the ``ABCAD_OUT`` environment
    variable) and never into the package directory.
"""

# Single source of truth for the package version (mirrored by the packaging metadata).
__version__ = "0.1.0"
