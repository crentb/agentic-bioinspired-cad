"""
abcad.agent.retrieval — code-exemplar and reference-render retrieval over small JSONL corpora.

PURPOSE
    Grounds three models in known-good examples:
      * the Phase-1 code emitter, the repairer and the refiner receive a "context block" of the
        most similar code exemplars (``ExemplarIndex``);
      * the render critic receives the most similar reference renders (``ReferenceGallery``).
    Search is exact inner product over L2-normalized embeddings (= cosine similarity). With a few
    records a brute-force matrix product is exact and trivially fast, so no vector library is
    needed, and ``k`` is clamped to the corpus size so an invalid index is never dereferenced.

CORPUS FORMATS (JSON Lines, UTF-8, a leading byte-order mark is tolerated, blank lines ignored)
    text corpus    {"instruction": str, "code": str, "category": str}; other fields are ignored
    image corpus   {"caption": str, "path": str, "category": str?, "subcategory": str?}; ``path``
                   is relative to the directory of the JSONL file that holds the record

INPUTS / OUTPUTS
    Corpus paths come from AgentSettings (the shipped corpora are located through
    abcad.resources). The embedder is injected (``Embedder`` protocol) so tests run without model
    weights; ``SentenceEmbedder`` is the production implementation and imports
    sentence-transformers only on first use. One embedder instance is shared by both indexes.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from abcad import resources

LOGGER = logging.getLogger("abcad.agent")


# --------------------------------------------------------------------------------------------------
# Embedders
# --------------------------------------------------------------------------------------------------
class Embedder(Protocol):
    """Anything that maps texts to an ``(n, d)`` float32 array with L2-normalized rows."""

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        """Embed ``texts``; row i is the unit-length embedding of ``texts[i]``."""
        ...


class SentenceEmbedder:
    """sentence-transformers embedder, loaded lazily on the first ``encode`` call.

    Args:
        model_id: Hugging Face model id (``BAAI/bge-small-en-v1.5`` by default, 384-dimensional).
        revision: model revision (branch, tag or commit hash) for reproducibility.
        device: torch device string; ``cpu`` keeps the Metal allocator out of the Phase-2 parent.
    """

    def __init__(self, model_id: str, revision: str, device: str) -> None:
        self.model_id = model_id
        self.revision = revision
        self.device = device
        self._model: Any = None

    def _load(self) -> Any:
        """Import sentence-transformers and load the model (first call only)."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # heavy: lazy by design

            LOGGER.info(
                "loading embedder %s (revision %s) on %s", self.model_id, self.revision, self.device
            )
            self._model = SentenceTransformer(
                self.model_id, revision=self.revision, device=self.device
            )
        return self._model

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        """Embed ``texts`` with normalized embeddings, returned as float32."""
        items = list(texts)
        if not items:
            return np.zeros((0, 0), dtype=np.float32)
        vectors = self._load().encode(
            items, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
        )
        return np.asarray(vectors, dtype=np.float32)


def _unit_rows(matrix: np.ndarray) -> np.ndarray:
    """Re-normalize rows to unit length (defensive; zero rows stay zero instead of NaN)."""
    matrix = np.asarray(matrix, dtype=np.float32)
    if matrix.ndim != 2:
        raise ValueError(f"embedder returned an array of shape {matrix.shape}, expected (n, d)")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms > 0)


def _ranked(matrix: np.ndarray | None, query_vector: np.ndarray, k: int) -> list[tuple[int, float]]:
    """Exact top-k by inner product: descending score, ties to the earlier record.

    ``k`` is clamped to ``[0, n]``; a stable sort on the negated scores keeps corpus order among
    equal scores, which makes rankings deterministic.
    """
    if matrix is None or matrix.shape[0] == 0:
        return []
    k = max(0, min(int(k), matrix.shape[0]))
    if k == 0:
        return []
    scores = matrix @ query_vector
    order = np.argsort(-scores, kind="stable")[:k]
    return [(int(i), float(scores[i])) for i in order]


# --------------------------------------------------------------------------------------------------
# JSON Lines reading
# --------------------------------------------------------------------------------------------------
def _read_jsonl(path: str) -> Iterator[dict[str, Any]]:
    """Yield the JSON objects of a JSONL file; invalid lines are skipped with a warning.

    ``utf-8-sig`` tolerates a leading byte-order mark. Blank lines are ignored.
    """
    with open(path, encoding="utf-8-sig") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                LOGGER.warning("skipping invalid JSON in %s line %d: %s", path, number, exc.msg)
                continue
            if not isinstance(record, dict):
                LOGGER.warning("skipping non-object record in %s line %d", path, number)
                continue
            yield record


def _text_field(record: dict[str, Any], key: str, default: str) -> str:
    """String field with a default for missing or null values."""
    value = record.get(key)
    return default if value is None else str(value)


# --------------------------------------------------------------------------------------------------
# Code-exemplar index
# --------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Exemplar:
    """One retrieved code exemplar.

    Attributes:
        rank: 0-based position in the result list.
        score: cosine similarity to the query.
        source: basename of the corpus file the record came from.
        category: design family (e.g. "helical", "woven"), "unknown" when absent.
        instruction: the natural-language description of the exemplar.
        code: the exemplar's Blender Python code.
    """

    rank: int
    score: float
    source: str
    category: str
    instruction: str
    code: str


def format_exemplars(exemplars: Sequence[Exemplar]) -> str:
    """Render the retrieval context block used by the emitter, repair and refine prompts.

    Each exemplar renders as ``"Source: <source>\\nInstruction: <instruction>\\nCategory:
    <category>\\nCode:\\n<code>\\n"`` and the blocks are joined with ``"\\n---\\n"``. The adapter
    was trained with this exact framing, so the format is an external interface.

    Args:
        exemplars: results in rank order.

    Returns:
        The context block; ``""`` for an empty list.
    """
    rendered = [
        "Source: "
        + e.source
        + "\nInstruction: "
        + e.instruction
        + "\nCategory: "
        + e.category
        + "\nCode:\n"
        + e.code
        + "\n"
        for e in exemplars
    ]
    return "\n---\n".join(rendered)


@dataclass(frozen=True)
class _TextRecord:
    """A loaded code exemplar before ranking."""

    source: str
    category: str
    instruction: str
    code: str


class ExemplarIndex:
    """Exact cosine search over the code-exemplar corpora.

    Build it with :meth:`from_corpora`. When retrieval is disabled or no record loads, the index
    is disabled and every context block is empty.

    Attributes:
        enabled: whether searches return anything.
        size: number of loaded records.
    """

    def __init__(
        self,
        records: Sequence[_TextRecord],
        matrix: np.ndarray | None,
        embedder: Embedder | None,
        *,
        enabled: bool,
    ) -> None:
        self._records = list(records)
        self._matrix = matrix
        self._embedder = embedder
        self.size = len(self._records)
        self.enabled = bool(enabled and self.size > 0)

    @classmethod
    def from_corpora(
        cls, paths: Sequence[str], embedder: Embedder, *, enabled: bool = True
    ) -> ExemplarIndex:
        """Load and embed the text corpora in the given order.

        Args:
            paths: corpus files; the configured order (then line order) breaks score ties.
            embedder: shared embedder instance.
            enabled: False skips loading entirely (retrieval switched off).

        Returns:
            The index. Missing files are skipped with a warning.
        """
        if not enabled:
            return cls([], None, embedder, enabled=False)
        records: list[_TextRecord] = []
        for path in paths:
            if not os.path.isfile(path):
                LOGGER.warning("code-exemplar corpus not found, skipped: %s", path)
                continue
            source = os.path.basename(path)
            for record in _read_jsonl(path):
                records.append(
                    _TextRecord(
                        source=source,
                        category=_text_field(record, "category", "unknown"),
                        instruction=_text_field(record, "instruction", ""),
                        code=_text_field(record, "code", ""),
                    )
                )
        if not records:
            LOGGER.warning("no code exemplars loaded; retrieval context disabled")
            return cls([], None, embedder, enabled=False)
        documents = [r.instruction + "\n" + r.code for r in records]
        matrix = _unit_rows(embedder.encode(documents))
        LOGGER.info("code-exemplar index: %d record(s) from %d file(s)", len(records), len(paths))
        return cls(records, matrix, embedder, enabled=True)

    def search(self, query: str, k: int) -> list[Exemplar]:
        """Return up to ``k`` exemplars ranked by cosine similarity to ``query``."""
        if not self.enabled or self._embedder is None:
            return []
        query_vector = _unit_rows(self._embedder.encode([query]))[0]
        results = []
        for rank, (index, score) in enumerate(_ranked(self._matrix, query_vector, k)):
            record = self._records[index]
            results.append(
                Exemplar(
                    rank=rank,
                    score=score,
                    source=record.source,
                    category=record.category,
                    instruction=record.instruction,
                    code=record.code,
                )
            )
        return results

    def context_block(self, query: str, k: int) -> str:
        """The formatted context block for ``query`` (``""`` when disabled or empty)."""
        if not self.enabled:
            return ""
        return format_exemplars(self.search(query, k))


# --------------------------------------------------------------------------------------------------
# Reference-render gallery
# --------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ReferenceImage:
    """One retrieved reference render.

    Attributes:
        rank: 0-based position in the result list.
        score: cosine similarity of the caption to the query.
        caption: text description of the render (the embedded text).
        path: resolved absolute image path.
        exists: whether that file existed when the corpus was loaded.
        category: design family, "" when absent.
        subcategory: finer family label, "" when absent.
    """

    rank: int
    score: float
    caption: str
    path: str
    exists: bool
    category: str
    subcategory: str


def resolve_reference_path(
    raw_path: str, corpus_path: str, *, image_root: str | None = None
) -> tuple[str, bool]:
    """Resolve an image-corpus ``path`` field to an absolute file path.

    The working directory is never consulted. Let ``q`` be the path without leading "/" and
    ``corpus_dir`` the directory of the JSONL file. The primary rule is ``<corpus_dir>/q``; for
    the shipped corpus this is exactly ``abcad.resources.resolve_corpus_path(q)``. When that file
    does not exist, the fallbacks are tried in order and the first existing file wins:
    ``<image_root>/q`` (if configured), ``<corpus_dir>/`` + ``q`` without its first path component
    (legacy ``/RAG/renders/x.png`` entries), and ``<corpus_dir>/renders/<basename(q)>``.

    Args:
        raw_path: the record's ``path`` value.
        corpus_path: the JSONL file holding the record.
        image_root: optional extra base directory.

    Returns:
        ``(path, exists)``; when nothing exists the primary path is returned with ``False``.
    """
    relative = raw_path.lstrip("/")
    corpus_dir = os.path.dirname(os.path.abspath(corpus_path))
    if os.path.normcase(corpus_dir) == os.path.normcase(os.path.abspath(resources.rag_dir())):
        primary = str(resources.resolve_corpus_path(relative))  # shipped data: package-relative
    else:
        primary = os.path.abspath(os.path.join(corpus_dir, relative))
    if os.path.isfile(primary):
        return primary, True

    candidates: list[str] = []
    if image_root:
        candidates.append(os.path.join(image_root, relative))
    components = [c for c in relative.replace("\\", "/").split("/") if c]
    if len(components) > 1:
        candidates.append(os.path.join(corpus_dir, *components[1:]))
    if components:
        candidates.append(os.path.join(corpus_dir, "renders", components[-1]))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return os.path.abspath(candidate), True
    return primary, False


@dataclass(frozen=True)
class _ImageRecord:
    """A loaded reference render before ranking."""

    caption: str
    path: str
    exists: bool
    category: str
    subcategory: str


class ReferenceGallery:
    """Exact cosine search over reference-render captions.

    Build it with :meth:`from_corpora`. The first corpus is mandatory (the critic's grounding is
    not optional); extra corpora are best-effort.
    """

    def __init__(
        self, records: Sequence[_ImageRecord], matrix: np.ndarray | None, embedder: Embedder
    ) -> None:
        self._records = list(records)
        self._matrix = matrix
        self._embedder = embedder
        self.size = len(self._records)

    @classmethod
    def from_corpora(
        cls, paths: Sequence[str], embedder: Embedder, *, image_root: str | None = None
    ) -> ReferenceGallery:
        """Load the image corpora and embed their captions.

        Args:
            paths: corpus files; the first is the primary corpus.
            embedder: shared embedder instance.
            image_root: optional extra base directory for image paths.

        Returns:
            The gallery.

        Raises:
            FileNotFoundError: the primary corpus is missing (or no corpus was configured).
        """
        if not paths:
            raise FileNotFoundError("no reference-image corpus configured")
        primary = paths[0]
        if not os.path.isfile(primary):
            raise FileNotFoundError(f"primary reference-image corpus not found: {primary}")
        records: list[_ImageRecord] = []
        for position, path in enumerate(paths):
            if position > 0 and not os.path.isfile(path):
                LOGGER.warning("extra reference-image corpus not found, skipped: %s", path)
                continue
            for number, record in enumerate(_read_jsonl(path), start=1):
                caption, raw_path = record.get("caption"), record.get("path")
                if not isinstance(caption, str) or not isinstance(raw_path, str):
                    LOGGER.warning(
                        "skipping image record %d in %s: needs caption and path", number, path
                    )
                    continue
                resolved, exists = resolve_reference_path(raw_path, path, image_root=image_root)
                if not exists:
                    # Logged once, at load; the critic later filters these entries out.
                    LOGGER.warning("reference image not found for %r: %s", raw_path, resolved)
                records.append(
                    _ImageRecord(
                        caption=caption,
                        path=resolved,
                        exists=exists,
                        category=_text_field(record, "category", ""),
                        subcategory=_text_field(record, "subcategory", ""),
                    )
                )
        matrix = _unit_rows(embedder.encode([r.caption for r in records])) if records else None
        LOGGER.info("reference gallery: %d image(s) from %d file(s)", len(records), len(paths))
        return cls(records, matrix, embedder)

    def search(self, query: str, k: int) -> list[ReferenceImage]:
        """Return up to ``k`` reference renders ranked by caption similarity to ``query``."""
        if not self._records:
            return []
        query_vector = _unit_rows(self._embedder.encode([query]))[0]
        results = []
        for rank, (index, score) in enumerate(_ranked(self._matrix, query_vector, k)):
            record = self._records[index]
            results.append(
                ReferenceImage(
                    rank=rank,
                    score=score,
                    caption=record.caption,
                    path=record.path,
                    exists=record.exists,
                    category=record.category,
                    subcategory=record.subcategory,
                )
            )
        return results
