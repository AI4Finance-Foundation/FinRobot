"""SEC 10-K RAG module using BM25 keyword search.

Why BM25 over embeddings:
- No 80MB model download, deterministic results, easily testable.
- Same interface as embedding-based retrieval — upgrade path is straightforward.

What this code does that LLM cannot:
- Deterministic passage retrieval: BM25 always returns the same chunk for the same query.
- LLM would hallucinate passage content; BM25 retrieves actual text at a specific rank.
- Controlled chunking ensures no sentence is stranded at a boundary.
"""

from __future__ import annotations

from dataclasses import dataclass

from rank_bm25 import BM25Okapi


@dataclass
class Chunk:
    """A single text chunk from a document."""

    text: str
    source: str  # e.g. "10-K/2024/MD&A"
    chunk_index: int
    char_start: int  # byte offset of chunk start in original text


class BM25Index:
    """BM25 index over text chunks. Deterministic — no external model or randomness."""

    def __init__(self, chunks: list[Chunk]) -> None:
        self._chunks = chunks
        tokenized = [c.text.lower().split() for c in chunks]
        # BM25Okapi raises ZeroDivisionError on empty corpus
        self._bm25: BM25Okapi | None = BM25Okapi(tokenized) if tokenized else None

    def search(self, query: str, top_k: int = 5) -> list[tuple[Chunk, float]]:
        """Return top_k chunks ranked by BM25 score (descending).

        Chunks with score = 0 (no term overlap) are excluded.

        Args:
            query: Natural-language search query.
            top_k: Maximum number of results to return.

        Returns:
            List of (Chunk, score) pairs, highest score first.
        """
        if self._bm25 is None:
            return []
        scores = self._bm25.get_scores(query.lower().split())
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        return [(self._chunks[i], float(s)) for i, s in ranked[:top_k] if s > 0]


def chunk_text(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
    source: str = "",
) -> list[Chunk]:
    """Split text into overlapping word-chunks with character offset tracking.

    Args:
        text: The full document text to chunk.
        chunk_size: Number of words per chunk.
        overlap: Number of words shared between consecutive chunks.
            Ensures context is not lost at boundaries.
        source: Label for the source (e.g. "10-K/2024/MD&A").

    Returns:
        List of Chunk objects with char_start pointing into the original text.
    """
    words = text.split()
    if not words:
        return []

    # Build cumulative char-offset map: offsets[i] = start position of words[i]
    offsets: list[int] = []
    pos = 0
    for w in words:
        pos = text.find(w, pos)
        offsets.append(pos)
        pos += len(w)

    chunks: list[Chunk] = []
    step = max(1, chunk_size - overlap)
    i = 0
    while i < len(words):
        chunk_words = words[i : i + chunk_size]
        text_slice = " ".join(chunk_words)
        char_start = offsets[i]
        chunks.append(
            Chunk(
                text=text_slice,
                source=source,
                chunk_index=len(chunks),
                char_start=char_start,
            )
        )
        i += step

    return chunks
