"""
abcad._vendor.woven_lattice — the woven-lattice geometry engine, vendored verbatim (MIT).

``makeunitcell_func1.py`` is an unmodified copy of the upstream module (see README.md in this
directory for the repository URL, pinned commit and license). It converts a parent beam lattice
into continuous woven fiber centerlines. It is imported through
``abcad.generators.woven.build._load_engine``, which installs a matplotlib stub first so the engine
needs only numpy + scipy; do not import it directly unless matplotlib is available.
"""
