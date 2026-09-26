"""
abcad.data — runtime data shipped inside the package (travels with the wheel).

CONTENTS
    rag/text_corpus.jsonl    text retrieval corpus (instruction / code / category)
    rag/vlm_corpus.jsonl     vision retrieval corpus; image ``path`` values are relative to the
                             directory of this JSONL file (e.g. "renders/woven_cubic_lattice.png")
    rag/renders/*.png        reference renders for the vision corpus
    exemplars/*.py           exemplar Blender base scripts (templates with {placeholders}; data, not
                             importable modules)

Locate these files through :mod:`abcad.resources` (``rag_dir()``, ``exemplars_dir()``, ...), which
resolves them relative to the installed package via importlib.resources — never via the working
directory. This package intentionally contains no code.
"""
