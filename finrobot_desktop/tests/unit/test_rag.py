"""Tests for BM25 RAG compute module."""

from finrobot.engine.primitives.rag import Chunk, BM25Index, chunk_text


class TestChunkText:
    def test_chunk_count_1000_words(self):
        """1000 words, chunk=100, overlap=10, step=90 → ceil((1000-100)/90)+1 ≈ 11-12 chunks."""
        text = " ".join(["word"] * 1000)
        chunks = chunk_text(text, chunk_size=100, overlap=10)
        assert len(chunks) >= 10

    def test_chunk_size_correct(self):
        """Each chunk except possibly the last has exactly chunk_size words."""
        text = " ".join([f"w{i}" for i in range(200)])
        chunks = chunk_text(text, chunk_size=50, overlap=10)
        for c in chunks[:-1]:
            assert len(c.text.split()) == 50

    def test_chunk_overlap_content(self):
        """Last 10 words of chunk[0] appear at start of chunk[1]."""
        text = " ".join([f"w{i}" for i in range(200)])
        chunks = chunk_text(text, chunk_size=50, overlap=10)
        end_words = chunks[0].text.split()[-10:]
        start_words = chunks[1].text.split()[:10]
        assert end_words == start_words

    def test_char_start_monotone(self):
        """char_start of consecutive chunks must be non-decreasing."""
        text = " ".join([f"word{i}" for i in range(300)])
        chunks = chunk_text(text, chunk_size=50, overlap=10)
        starts = [c.char_start for c in chunks]
        assert all(starts[i] <= starts[i + 1] for i in range(len(starts) - 1))

    def test_char_start_first_chunk_is_zero(self):
        text = "hello world foo bar"
        chunks = chunk_text(text, chunk_size=10, overlap=0)
        assert chunks[0].char_start == 0

    def test_source_label_propagated(self):
        text = " ".join(["x"] * 100)
        chunks = chunk_text(text, source="10-K/2024/MD&A")
        assert all(c.source == "10-K/2024/MD&A" for c in chunks)

    def test_empty_text_returns_empty(self):
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_chunk_index_sequential(self):
        text = " ".join(["w"] * 200)
        chunks = chunk_text(text, chunk_size=50, overlap=10)
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


class TestBM25Index:
    def test_retrieves_relevant_chunk(self):
        """Chunk containing 'liquidity risk' must rank #1 for that query."""
        chunks = [
            Chunk(
                text="The company faces market risk from interest rates.",
                source="risk",
                chunk_index=0,
                char_start=0,
            ),
            Chunk(
                text="Liquidity risk arises from inability to meet obligations.",
                source="risk",
                chunk_index=1,
                char_start=0,
            ),
            Chunk(
                text="Revenue increased 12% year over year.",
                source="ops",
                chunk_index=2,
                char_start=0,
            ),
        ]
        index = BM25Index(chunks)
        results = index.search("liquidity risk")
        assert results[0][0].chunk_index == 1

    def test_empty_for_zero_score_query(self):
        """A query with no matching terms returns an empty list."""
        chunks = [Chunk(text="hello world foo", source="", chunk_index=0, char_start=0)]
        index = BM25Index(chunks)
        results = index.search("xyzzy quantum entanglement")
        assert results == []

    def test_top_k_limits_results(self):
        chunks = [
            Chunk(
                text=f"revenue cash profit loss ebitda concept{i}",
                source="",
                chunk_index=i,
                char_start=0,
            )
            for i in range(10)
        ]
        index = BM25Index(chunks)
        results = index.search("revenue", top_k=3)
        assert len(results) <= 3

    def test_scores_descending(self):
        """Results are returned in descending score order."""
        chunks = [
            Chunk(
                text="revenue revenue revenue highly relevant",
                source="",
                chunk_index=0,
                char_start=0,
            ),
            Chunk(text="revenue mentioned once here", source="", chunk_index=1, char_start=0),
            Chunk(text="something else entirely different", source="", chunk_index=2, char_start=0),
        ]
        index = BM25Index(chunks)
        results = index.search("revenue")
        scores = [score for _, score in results]
        assert scores == sorted(scores, reverse=True)

    def test_relevant_chunk_ranked_higher(self):
        """Chunk with more query terms must outscore an unrelated chunk.

        Needs 3+ chunks: BM25Okapi IDF = log((N-df+0.5)/(df+0.5)).
        With N=2, df=1: IDF = log(1)=0 → all scores 0. With N=3, df=1: IDF>0.
        """
        chunks = [
            Chunk(
                text="ebitda margin expansion organic growth profitability",
                source="",
                chunk_index=0,
                char_start=0,
            ),
            Chunk(
                text="legal proceedings litigation settlement court",
                source="",
                chunk_index=1,
                char_start=0,
            ),
            Chunk(
                text="tax expense deferred liabilities income statement",
                source="",
                chunk_index=2,
                char_start=0,
            ),
        ]
        index = BM25Index(chunks)
        results = index.search("ebitda growth margin")
        assert len(results) >= 1
        assert results[0][0].chunk_index == 0
