"""
abcad.resources — locate the runtime data that ships INSIDE the package (works from a wheel).

PURPOSE
    Runtime data (retrieval corpora, reference renders, exemplar scripts, MOOSE reference decks)
    lives inside the ``abcad`` package so that a plain ``pip install`` carries it along. Code must
    never find that data through the current working directory or a repository-relative path;
    it asks this module instead, which resolves every location through ``importlib.resources``
    (the standard, packaging-aware mechanism) relative to the installed package itself.

LAYOUT (inside the package)
    abcad/data/rag/text_corpus.jsonl     text retrieval corpus (instruction / code / category)
    abcad/data/rag/vlm_corpus.jsonl      vision retrieval corpus; each ``path`` is RELATIVE to the
                                         JSONL file's own directory (e.g. "renders/x.png")
    abcad/data/rag/renders/*.png         reference renders referenced by the vision corpus
    abcad/data/exemplars/*.py            exemplar Blender scripts (templates with {placeholders})
    abcad/fracture/decks/*.i             MOOSE reference input decks

INPUTS / OUTPUTS
    Pure lookups: every function returns a ``pathlib.Path``; nothing is read or written here.

WHY pathlib.Path (not a Traversable)
    Downstream consumers (MOOSE, Blender, pyvista, plain ``open``) need real filesystem paths.
    ``importlib.resources.files`` returns a ``pathlib.Path`` whenever the package is installed as
    ordinary files — a wheel unpacked into site-packages, an editable install, or a source
    checkout — which covers every supported installation. A zip-imported package would yield a
    ``zipfile.Path`` instead; that case is rejected with a clear error rather than handing a
    non-filesystem object to tools that cannot use it.
"""

from __future__ import annotations

import pathlib
from importlib import resources

# --------------------------------------------------------------------------------------------------
# Package anchors: the dotted packages whose directories hold the data. They are regular packages
# (each has an __init__.py), which is what importlib.resources.files() needs to anchor a lookup.
# --------------------------------------------------------------------------------------------------
_DATA_PACKAGE = "abcad.data"  # retrieval corpora, renders, exemplar scripts
_FRACTURE_PACKAGE = "abcad.fracture"  # MOOSE reference decks live in its decks/ subdirectory


def _package_path(package: str, *parts: str) -> pathlib.Path:
    """Return the filesystem path of ``parts`` inside ``package``.

    ``parts`` are joined one component at a time because ``Traversable.joinpath`` only accepts a
    single argument on some Python versions (3.10 / 3.11). Raises RuntimeError when the package is
    not backed by real files (see the module docstring, "WHY pathlib.Path").
    """
    target = resources.files(package)
    for part in parts:
        target = target / part
    if not isinstance(target, pathlib.Path):
        raise RuntimeError(
            f"{package} is not installed as regular files (got {type(target).__name__}); "
            "install abcad from a wheel or a source checkout so its data has filesystem paths."
        )
    return target


# --------------------------------------------------------------------------------------------------
# Retrieval data (text + vision corpora and their renders)
# --------------------------------------------------------------------------------------------------
def data_dir() -> pathlib.Path:
    """Root of the shipped runtime data: ``abcad/data``."""
    return _package_path(_DATA_PACKAGE)


def rag_dir() -> pathlib.Path:
    """Directory holding both retrieval corpora and the ``renders/`` image folder."""
    return _package_path(_DATA_PACKAGE, "rag")


def text_corpus_path() -> pathlib.Path:
    """Text retrieval corpus (JSON Lines; keys ``instruction``, ``code``, ``category``)."""
    return rag_dir() / "text_corpus.jsonl"


def vlm_corpus_path() -> pathlib.Path:
    """Vision retrieval corpus (JSON Lines; keys ``category``, ``subcategory``, ``caption``, ``path``)."""
    return rag_dir() / "vlm_corpus.jsonl"


def renders_dir() -> pathlib.Path:
    """Reference renders referenced by the vision corpus."""
    return rag_dir() / "renders"


def resolve_corpus_path(relative: str) -> pathlib.Path:
    """Resolve a ``path`` field from a retrieval corpus to an absolute file path.

    Corpus paths are stored RELATIVE to the directory of the JSONL file that contains them (for
    example ``"renders/woven_cubic_lattice.png"``), so they stay valid wherever the package is
    installed. A leading slash is tolerated and stripped for robustness against older entries.
    """
    return (rag_dir() / relative.lstrip("/")).resolve()


# --------------------------------------------------------------------------------------------------
# Exemplar scripts and fracture decks
# --------------------------------------------------------------------------------------------------
def exemplars_dir() -> pathlib.Path:
    """Exemplar Blender base scripts (templates whose ``{name}`` placeholders are filled by callers)."""
    return _package_path(_DATA_PACKAGE, "exemplars")


def decks_dir() -> pathlib.Path:
    """MOOSE reference input decks (``*.i``) shipped with the fracture instruments."""
    return _package_path(_FRACTURE_PACKAGE, "decks")


def deck_path(name: str) -> pathlib.Path:
    """Path of one shipped MOOSE deck; ``name`` may omit the ``.i`` suffix.

    Raises FileNotFoundError (listing the available decks) when the deck does not exist, so a
    typo fails loudly instead of MOOSE reporting an unreadable input later.
    """
    filename = name if name.endswith(".i") else f"{name}.i"
    path = decks_dir() / filename
    if not path.is_file():
        available = ", ".join(sorted(p.name for p in decks_dir().glob("*.i")))
        raise FileNotFoundError(f"no MOOSE deck {filename!r}; available: {available}")
    return path
