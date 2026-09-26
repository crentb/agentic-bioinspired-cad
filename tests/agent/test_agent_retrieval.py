"""
U-03 / U-04: code-exemplar and reference-render retrieval (abcad.agent.retrieval).

Exact cosine ranking with deterministic ties, k clamping, the exact context-block format, corpus
loading rules, and image-path resolution that never consults the working directory.
"""

from __future__ import annotations

import json
import os

import pytest
from agent_fakes import FakeEmbedder

from abcad import resources
from abcad.agent.retrieval import (
    Exemplar,
    ExemplarIndex,
    ReferenceGallery,
    format_exemplars,
    resolve_reference_path,
)


def write_jsonl(path, records, *, extra_lines=()):
    """Write records as JSON Lines, followed by any raw extra lines."""
    lines = [json.dumps(r) for r in records] + list(extra_lines)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


TEXT_RECORDS = [
    {
        "instruction": "bouligand helical plywood stack",
        "code": "import bpy\n# plies",
        "category": "helical",
    },
    {
        "instruction": "woven cubic lattice of helical fibers",
        "code": "import bpy\n# weave",
        "category": "woven",
    },
    {"instruction": "gyroid sheet network", "code": "import bpy\n# gyroid"},
]


# --------------------------------------------------------------------------------------------------
# U-03: exemplar index
# --------------------------------------------------------------------------------------------------
def test_ranking_by_cosine(tmp_path):
    corpus = write_jsonl(tmp_path / "text.jsonl", TEXT_RECORDS)
    index = ExemplarIndex.from_corpora([str(corpus)], FakeEmbedder())
    assert index.enabled and index.size == 3
    results = index.search("woven lattice fibers", k=3)
    assert results[0].category == "woven"
    assert [r.rank for r in results] == [0, 1, 2]
    assert results[0].score >= results[1].score >= results[2].score


def test_ties_resolve_to_corpus_order(tmp_path):
    first = write_jsonl(
        tmp_path / "a.jsonl", [{"instruction": "same", "code": "x", "category": "A"}]
    )
    second = write_jsonl(
        tmp_path / "b.jsonl", [{"instruction": "same", "code": "x", "category": "B"}]
    )
    index = ExemplarIndex.from_corpora([str(first), str(second)], FakeEmbedder())
    results = index.search("same x", k=2)
    assert [r.category for r in results] == ["A", "B"]
    assert results[0].score == pytest.approx(results[1].score)


def test_k_is_clamped(tmp_path):
    corpus = write_jsonl(tmp_path / "text.jsonl", TEXT_RECORDS)
    index = ExemplarIndex.from_corpora([str(corpus)], FakeEmbedder())
    assert len(index.search("anything", k=5)) == 3
    assert index.search("anything", k=0) == []


def test_record_defaults_and_source_basename(tmp_path):
    corpus = write_jsonl(tmp_path / "my_corpus.jsonl", TEXT_RECORDS)
    index = ExemplarIndex.from_corpora([str(corpus)], FakeEmbedder())
    gyroid = index.search("gyroid sheet network", k=1)[0]
    assert gyroid.source == "my_corpus.jsonl"
    assert gyroid.category == "unknown"


def test_context_block_exact_format():
    exemplars = [
        Exemplar(0, 0.9, "text.jsonl", "woven", "a woven lattice", "import bpy\nw = 1"),
        Exemplar(1, 0.5, "extra.jsonl", "helical", "a helicoid", "import bpy\nh = 2"),
    ]
    expected = (
        "Source: text.jsonl\nInstruction: a woven lattice\nCategory: woven\nCode:\nimport bpy\nw = 1\n"
        "\n---\n"
        "Source: extra.jsonl\nInstruction: a helicoid\nCategory: helical\nCode:\nimport bpy\nh = 2\n"
    )
    assert format_exemplars(exemplars) == expected
    assert format_exemplars([]) == ""


def test_context_block_matches_search(tmp_path):
    corpus = write_jsonl(tmp_path / "text.jsonl", TEXT_RECORDS)
    index = ExemplarIndex.from_corpora([str(corpus)], FakeEmbedder())
    assert index.context_block("woven", 2) == format_exemplars(index.search("woven", 2))


def test_disabled_or_empty_index_gives_empty_context(tmp_path):
    corpus = write_jsonl(tmp_path / "text.jsonl", TEXT_RECORDS)
    embedder = FakeEmbedder()
    disabled = ExemplarIndex.from_corpora([str(corpus)], embedder, enabled=False)
    assert not disabled.enabled and disabled.context_block("woven", 2) == ""
    assert embedder.calls == []  # a disabled index never embeds anything
    empty = ExemplarIndex.from_corpora([str(write_jsonl(tmp_path / "e.jsonl", []))], embedder)
    assert not empty.enabled and empty.context_block("woven", 2) == ""


def test_invalid_line_and_missing_corpus_are_skipped_with_warnings(tmp_path, caplog):
    corpus = write_jsonl(
        tmp_path / "text.jsonl", TEXT_RECORDS[:1], extra_lines=["{not json", "[1, 2]"]
    )
    missing = tmp_path / "missing.jsonl"
    index = ExemplarIndex.from_corpora([str(corpus), str(missing)], FakeEmbedder())
    assert index.size == 1
    assert "text.jsonl" in caplog.text and "invalid JSON" in caplog.text
    assert "missing.jsonl" in caplog.text


def test_shipped_text_corpus_loads():
    index = ExemplarIndex.from_corpora([str(resources.text_corpus_path())], FakeEmbedder())
    assert index.size == 3
    assert {r.category for r in index.search("lattice", 3)} >= {"woven"}


# --------------------------------------------------------------------------------------------------
# Reference gallery
# --------------------------------------------------------------------------------------------------
def test_missing_primary_image_corpus_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        ReferenceGallery.from_corpora([str(tmp_path / "absent.jsonl")], FakeEmbedder())


def test_missing_extra_image_corpus_warns(tmp_path, caplog):
    gallery = ReferenceGallery.from_corpora(
        [str(resources.vlm_corpus_path()), str(tmp_path / "absent.jsonl")], FakeEmbedder()
    )
    assert gallery.size == 2
    assert "absent.jsonl" in caplog.text


def test_shipped_gallery_resolves_through_resources():
    gallery = ReferenceGallery.from_corpora([str(resources.vlm_corpus_path())], FakeEmbedder())
    results = gallery.search("a woven cubic lattice metamaterial", k=2)
    assert len(results) == 2 and all(r.exists for r in results)
    assert {os.path.basename(r.path) for r in results} == {
        "woven_cubic_lattice.png",
        "bouligand_rotating_ply.png",
    }
    for result in results:
        rel = "renders/" + os.path.basename(result.path)
        assert result.path == str(resources.resolve_corpus_path(rel))
    assert results[0].category == "woven"


def test_one_embedder_is_shared_by_both_indexes(make_settings):
    from abcad.agent.runner import build_components

    embedder = FakeEmbedder()
    components = build_components(make_settings(), embedder=embedder)
    assert components.embedder is embedder
    embedded = [text for call in embedder.calls for text in call]
    assert any("woven cubic lattice metamaterial" in text for text in embedded)  # exemplar docs
    assert any(text.startswith("Bouligand structure") for text in embedded)  # gallery captions


# --------------------------------------------------------------------------------------------------
# U-04: reference-path resolution
# --------------------------------------------------------------------------------------------------
@pytest.fixture
def corpus_dir(tmp_path, monkeypatch):
    """A corpus directory with renders/x.png; the working directory is elsewhere and poisoned."""
    root = tmp_path / "corpus"
    (root / "renders").mkdir(parents=True)
    (root / "renders" / "x.png").write_bytes(b"png")
    decoy = tmp_path / "cwd"
    (decoy / "renders").mkdir(parents=True)
    (decoy / "renders" / "y.png").write_bytes(b"decoy")  # only reachable through the cwd
    monkeypatch.chdir(decoy)
    return root


def test_primary_rule_relative_and_leading_slash(corpus_dir):
    corpus = str(corpus_dir / "vlm.jsonl")
    expected = str(corpus_dir / "renders" / "x.png")
    assert resolve_reference_path("renders/x.png", corpus) == (expected, True)
    assert resolve_reference_path("/renders/x.png", corpus) == (expected, True)


def test_legacy_prefix_and_bare_basename_fallbacks(corpus_dir):
    corpus = str(corpus_dir / "vlm.jsonl")
    expected = str(corpus_dir / "renders" / "x.png")
    assert resolve_reference_path("/RAG/renders/x.png", corpus) == (expected, True)
    assert resolve_reference_path("x.png", corpus) == (expected, True)


def test_image_root_fallback(corpus_dir, tmp_path):
    root = tmp_path / "images"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "z.png").write_bytes(b"png")
    corpus = str(corpus_dir / "vlm.jsonl")
    assert resolve_reference_path("sub/z.png", corpus, image_root=str(root)) == (
        str(root / "sub" / "z.png"),
        True,
    )


def test_working_directory_is_never_consulted_and_misses_warn_once(corpus_dir, caplog):
    corpus = write_jsonl(corpus_dir / "vlm.jsonl", [{"caption": "decoy", "path": "renders/y.png"}])
    path, exists = resolve_reference_path("renders/y.png", str(corpus))
    assert not exists and path == str(corpus_dir / "renders" / "y.png")
    caplog.clear()
    gallery = ReferenceGallery.from_corpora([str(corpus)], FakeEmbedder())
    [result] = gallery.search("decoy", 1)
    assert result.exists is False
    assert caplog.text.count("reference image not found") == 1
