"""Embedding-based RAG index using sentence-transformers.

Falls back to BM25Index when sentence-transformers is not installed,
ensuring the system works out-of-the-box without heavy ML dependencies.

**What this code does that raw LLM cannot**:
- Deterministic cosine-similarity retrieval over pre-computed dense vectors.
- LLM cannot search its own context window by semantic similarity; this module
  encodes chunks once and answers arbitrary queries in O(n) dot-product time
  with reproducible, ranked results.
- The factory function ``create_index`` auto-selects the best available backend,
  giving callers a single call-site that transparently upgrades from keyword
  search (BM25) to semantic search (embeddings) when the optional dependency
  is present.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

from finagent.engine.compute.rag import BM25Index, Chunk

if TYPE_CHECKING:
    from numpy.typing import NDArray

logger = logging.getLogger(__name__)

_HAS_SENTENCE_TRANSFORMERS = False
try:
    from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

    _HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    pass

# Cache loaded models to avoid reloading ~90MB weights on each call.
_model_cache: dict[str, SentenceTransformer] = {}


def _get_model(model_name: str) -> SentenceTransformer:
    if model_name not in _model_cache:
        _model_cache[model_name] = SentenceTransformer(model_name)
    return _model_cache[model_name]


class EmbeddingIndex:
    """Dense-vector index over text chunks using sentence-transformers.

    Same ``search`` interface as :class:`BM25Index` — callers can swap freely.

    Args:
        chunks: Pre-chunked text segments to index.
        model_name: HuggingFace model identifier for sentence-transformers.

    Raises:
        ImportError: If sentence-transformers is not installed.
    """

    def __init__(
        self,
        chunks: list[Chunk],
        model_name: str = "all-MiniLM-L6-v2",
    ) -> None:
        if not _HAS_SENTENCE_TRANSFORMERS:
            raise ImportError(
                "sentence-transformers is required for EmbeddingIndex. "
                "Install it with: pip install 'finagent[rag]'"
            )
        self._chunks = chunks
        self._model: SentenceTransformer = _get_model(model_name)

        if chunks:
            texts = [c.text for c in chunks]
            # encode returns ndarray of shape (n, dim)
            self._embeddings: NDArray[np.float32] = self._model.encode(
                texts, convert_to_numpy=True, show_progress_bar=False
            )
            # Normalise for cosine similarity via dot product
            norms = np.linalg.norm(self._embeddings, axis=1, keepdims=True)
            # Avoid division by zero for degenerate empty-text chunks
            norms = np.where(norms == 0, 1.0, norms)
            self._embeddings = self._embeddings / norms
        else:
            self._embeddings = np.empty((0, 0), dtype=np.float32)

    def search(self, query: str, top_k: int = 5) -> list[tuple[Chunk, float]]:
        """Return top_k chunks ranked by cosine similarity (descending).

        Only chunks with positive similarity are returned.

        Args:
            query: Natural-language search query.
            top_k: Maximum number of results to return.

        Returns:
            List of ``(Chunk, score)`` pairs, highest similarity first.
        """
        if len(self._chunks) == 0:
            return []

        query_vec: NDArray[np.float32] = self._model.encode(
            [query], convert_to_numpy=True, show_progress_bar=False
        )
        query_norm = np.linalg.norm(query_vec)
        if query_norm > 0:
            query_vec = query_vec / query_norm

        # Cosine similarity = dot product of normalised vectors
        scores: NDArray[np.float32] = (self._embeddings @ query_vec.T).flatten()

        # Rank descending
        ranked_indices = np.argsort(scores)[::-1][:top_k]

        return [
            (self._chunks[int(i)], float(scores[i]))
            for i in ranked_indices
            if scores[i] > 0
        ]


def create_index(chunks: list[Chunk]) -> BM25Index | EmbeddingIndex:
    """Create the best available search index over *chunks*.

    Uses :class:`EmbeddingIndex` when ``sentence-transformers`` is installed,
    otherwise falls back to :class:`BM25Index`.

    Args:
        chunks: Pre-chunked text segments to index.

    Returns:
        An index object with a ``search(query, top_k)`` method.
    """
    if _HAS_SENTENCE_TRANSFORMERS:
        logger.info("sentence-transformers available — using EmbeddingIndex")
        return EmbeddingIndex(chunks)
    logger.info("sentence-transformers not installed — falling back to BM25Index")
    return BM25Index(chunks)
