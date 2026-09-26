"""
test_dataset_integration.py — Tests for the dataset / retrieval integration of the new families.

Verifies (no Blender, no langgraph, no model):
  • the vocabulary module routes every new base_id to a phrase, and ignores unknown ids;
  • the exemplar base scripts shipped in abcad/data/exemplars/ are valid Python after placeholder
    substitution;
  • the text retrieval corpus (abcad/data/rag/text_corpus.jsonl) loads, has the schema the retriever
    expects (instruction/code/category), and every embedded script parses;
  • the vision retrieval corpus (abcad/data/rag/vlm_corpus.jsonl) stores image paths RELATIVE to its
    own directory and every one of them resolves to a shipped render.
All data is located through abcad.resources (importlib.resources), exactly as runtime code does, so
these tests also prove the data is reachable from an installed package, not just from a checkout.

Run:  python -m pytest tests/test_dataset_integration.py   (fast suite; standard library only)
"""

from __future__ import annotations

import ast
import json
import pathlib
import random

from abcad import resources
from abcad.dataset import prompt_vocab as X


def test_vocabulary_routes_new_ids():
    random.seed(0)
    for bid in X.NEW_BASE_IDS:
        p = X.shape_phrase_x(bid)
        assert isinstance(p, str) and len(p) > 0, f"phrase for {bid}"
    assert isinstance(X.shape_phrase_x("woven_anything"), str), "woven_* generic id routes"
    assert X.shape_phrase_x("tubular_generic") is None, "unknown/original id returns None"


def test_supplementary_base_scripts_parse():
    # Placeholder values used only to make the templates concrete for parsing.
    subs = {
        "num_plies": 24,
        "delta_a": 10,
        "delta_b": 5,
        "delta_min": 3,
        "delta_max": 18,
        "rotation": 10,
    }
    d = resources.exemplars_dir()
    files = sorted(p for p in d.iterdir() if p.suffix == ".py")
    assert len(files) >= 2, "supplementary base scripts exist"
    for fn in files:
        src = fn.read_text(encoding="utf-8")
        for k, v in subs.items():
            src = src.replace("{" + k + "}", str(v))
        ast.parse(src)  # raises SyntaxError if malformed
        assert (
            src.strip().startswith("#") or "import bpy" in src
        ), f"{fn.name} parses after substitution"
        assert "select_all" in src and (
            "primitive_cube_add" in src or "curves.new" in src
        ), f"{fn.name} clears the scene + builds geometry"


def test_supplementary_rag_jsonl():
    path = resources.text_corpus_path()
    assert path.exists(), "supplementary RAG jsonl exists"
    n = 0
    cats = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)  # valid JSON per line
            assert all(
                k in e for k in ("instruction", "code", "category")
            ), "entry has instruction/code/category"
            ast.parse(e["code"])  # embedded script is valid Python
            assert "import bpy" in e["code"], "embedded code is a runnable bpy script"
            cats.add(e["category"])
            n += 1
    assert n >= 3, "RAG store has >= 3 entries"
    assert {"helical", "woven"} <= cats, "RAG store covers helical and woven"


def test_vlm_corpus_paths_resolve_relative_to_jsonl():
    path = resources.vlm_corpus_path()
    assert path.exists(), "vision corpus jsonl exists"
    renders = resources.renders_dir().resolve()
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            assert all(k in e for k in ("category", "subcategory", "caption", "path")), e
            assert not e["path"].startswith("/"), f"path must be relative: {e['path']}"
            img = resources.resolve_corpus_path(e["path"])
            assert img == (path.parent / e["path"]).resolve(), "resolves next to the JSONL file"
            assert img.is_file(), f"render shipped: {e['path']}"
            assert img.parent == renders, "renders live in the package's rag/renders directory"
            n += 1
    assert n >= 2, "vision corpus has entries"


def test_resource_accessors_point_inside_the_package():
    import abcad

    pkg = pathlib.Path(abcad.__file__).resolve().parent  # the imported package directory
    for p in (
        resources.data_dir(),
        resources.rag_dir(),
        resources.exemplars_dir(),
        resources.decks_dir(),
    ):
        assert p.is_dir(), p
        assert pkg in p.resolve().parents, f"{p} is not inside the installed package"
    assert resources.deck_path("validate_uniaxial").name == "validate_uniaxial.i"
