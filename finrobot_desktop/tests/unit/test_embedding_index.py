"""Tests for the embedding-based RAG index and factory function."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from finagent.engine.compute.rag import BM25Index, Chunk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunks() -> list[Chunk]:
    return [
        Chunk(text="Apple reported record revenue", source="10-K", chunk_index=0, char_start=0),
        Chunk(text="Operating expenses increased by 5%", source="10-K", chunk_index=1, char_start=30),
        Chunk(text="Net income rose to 25 billion", source="10-K", chunk_index=2, char_start=65),
    ]


# ---------------------------------------------------------------------------
# Fallback behaviour (sentence-transformers NOT installed)
# ---------------------------------------------------------------------------

class TestCreateIndexFallback:
    """Verify factory falls back to BM25Index when sentence-transformers is absent."""

    def test_fallback_to_bm25(self) -> None:
        from finagent.engine.rag.embedding_index import create_index

        # In this test environment sentence-transformers is NOT installed,
        # so _HAS_SENTENCE_TRANSFORMERS is False and we get BM25.
        chunks = _make_chunks()
        index = create_index(chunks)
        assert isinstance(index, BM25Index)

    def test_bm25_fallback_returns_results(self) -> None:
        from finagent.engine.rag.embedding_index import create_index

        chunks = _make_chunks()
        index = create_index(chunks)
        results = index.search("revenue")
        assert len(results) >= 1
        assert results[0][0].text == "Apple reported record revenue"

    def test_embedding_index_import_error_when_unavailable(self) -> None:
        from finagent.engine.rag.embedding_index import EmbeddingIndex

        with pytest.raises(ImportError, match="sentence-transformers"):
            EmbeddingIndex(_make_chunks())


# ---------------------------------------------------------------------------
# Mocked sentence-transformers — test EmbeddingIndex logic
# ---------------------------------------------------------------------------

class TestEmbeddingIndexMocked:
    """Test EmbeddingIndex with a mocked SentenceTransformer model."""

    def _patch_and_build(self, chunks: list[Chunk]) -> "EmbeddingIndex":  # type: ignore[name-defined]  # noqa: F821
        """Build an EmbeddingIndex with mocked encoder."""
        import finagent.engine.rag.embedding_index as mod

        # Create a mock model that returns deterministic embeddings
        mock_model = MagicMock()

        dim = 4
        # Map chunk texts to fixed vectors for deterministic behaviour
        text_to_vec = {
            "Apple reported record revenue": np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
            "Operating expenses increased by 5%": np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32),
            "Net income rose to 25 billion": np.array([0.5, 0.0, 0.5, 0.0], dtype=np.float32),
        }

        def fake_encode(
            texts: list[str],
            convert_to_numpy: bool = True,
            show_progress_bar: bool = False,
        ) -> np.ndarray:
            vecs = []
            for t in texts:
                if t in text_to_vec:
                    vecs.append(text_to_vec[t])
                else:
                    # Query vector — make it close to first chunk
                    vecs.append(np.array([0.9, 0.1, 0.0, 0.0], dtype=np.float32))
            return np.array(vecs, dtype=np.float32)

        mock_model.encode = fake_encode

        # Temporarily enable the flag and mock SentenceTransformer constructor
        original_flag = mod._HAS_SENTENCE_TRANSFORMERS
        mod._HAS_SENTENCE_TRANSFORMERS = True
        mock_st_cls = MagicMock(return_value=mock_model)

        with patch.object(mod, "SentenceTransformer", mock_st_cls, create=True):
            idx = mod.EmbeddingIndex.__new__(mod.EmbeddingIndex)
            # Manually replicate __init__ logic with our mock
            idx._chunks = chunks
            idx._model = mock_model

            if chunks:
                texts = [c.text for c in chunks]
                emb = mock_model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
                norms = np.linalg.norm(emb, axis=1, keepdims=True)
                norms = np.where(norms == 0, 1.0, norms)
                idx._embeddings = emb / norms
            else:
                idx._embeddings = np.empty((0, dim), dtype=np.float32)

        mod._HAS_SENTENCE_TRANSFORMERS = original_flag
        return idx

    def test_search_returns_sorted_results(self) -> None:
        chunks = _make_chunks()
        idx = self._patch_and_build(chunks)

        results = idx.search("Apple revenue report", top_k=3)
        assert len(results) >= 1
        # The query vector [0.9, 0.1, 0, 0] is closest to chunk 0 [1, 0, 0, 0]
        assert results[0][0].text == "Apple reported record revenue"

        # Verify descending order of scores
        scores = [s for _, s in results]
        assert scores == sorted(scores, reverse=True)

    def test_search_empty_index(self) -> None:
        idx = self._patch_and_build([])
        results = idx.search("anything")
        assert results == []

    def test_search_top_k_limits_results(self) -> None:
        chunks = _make_chunks()
        idx = self._patch_and_build(chunks)

        results = idx.search("query", top_k=1)
        assert len(results) <= 1

    def test_search_scores_are_floats(self) -> None:
        chunks = _make_chunks()
        idx = self._patch_and_build(chunks)

        results = idx.search("revenue", top_k=3)
        for _, score in results:
            assert isinstance(score, float)

    def test_search_result_type(self) -> None:
        chunks = _make_chunks()
        idx = self._patch_and_build(chunks)

        results = idx.search("revenue", top_k=3)
        for chunk, score in results:
            assert isinstance(chunk, Chunk)
            assert isinstance(score, float)


# ---------------------------------------------------------------------------
# Factory with mocked availability
# ---------------------------------------------------------------------------

class TestCreateIndexWithEmbedding:
    """Verify factory selects EmbeddingIndex when sentence-transformers is available."""

    def test_creates_embedding_index_when_available(self) -> None:
        import finagent.engine.rag.embedding_index as mod

        original_flag = mod._HAS_SENTENCE_TRANSFORMERS
        mod._HAS_SENTENCE_TRANSFORMERS = True

        mock_model = MagicMock()
        mock_model.encode = MagicMock(
            return_value=np.array([[1.0, 0.0]], dtype=np.float32)
        )

        with patch.object(mod, "SentenceTransformer", MagicMock(return_value=mock_model), create=True):
            index = mod.create_index(_make_chunks())
            assert isinstance(index, mod.EmbeddingIndex)

        mod._HAS_SENTENCE_TRANSFORMERS = original_flag
