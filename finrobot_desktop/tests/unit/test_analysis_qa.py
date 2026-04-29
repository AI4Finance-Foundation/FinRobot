"""Tests for RAG Q&A runner.

Verifies chunk retrieval, prompt construction, and error handling
without hitting real SEC EDGAR or LLM APIs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from finagent.engine.analysis.qa import run_qa
from finagent.engine.data.interface import DataResult


@dataclass
class FakeChunk:
    text: str
    source: str
    chunk_index: int
    char_start: int


class FakeIndex:
    """Minimal BM25Index stand-in for testing."""

    def __init__(self, chunks: list[FakeChunk], scores: list[float] | None = None):
        self._chunks = chunks
        self._scores = scores or [1.0] * len(chunks)

    def search(self, query: str, top_k: int = 5) -> list[tuple[FakeChunk, float]]:
        return list(zip(self._chunks, self._scores))[:top_k]


def _make_data_layer(
    rag_index: FakeIndex | None = None,
    chunk_count: int = 10,
) -> MagicMock:
    data: dict = {}
    if rag_index is not None:
        data["rag_index"] = rag_index
        data["chunk_count"] = chunk_count
    else:
        data["chunk_count"] = 0

    result = DataResult(
        data=data,
        provider="sec_edgar",
        ticker="AAPL",
        data_type="10k_rag",
        timestamp=datetime.now(tz=timezone.utc),
    )
    layer = MagicMock()
    layer.fetch = AsyncMock(return_value=result)
    return layer


def _make_settings() -> MagicMock:
    settings = MagicMock()
    settings.create_model.return_value = "test"
    return settings


class TestRunQA:
    @pytest.mark.asyncio
    async def test_no_rag_index_raises(self) -> None:
        layer = _make_data_layer(rag_index=None, chunk_count=0)
        # Data has no rag_index key
        layer.fetch = AsyncMock(
            return_value=DataResult(
                data={"chunk_count": 0},
                provider="sec_edgar",
                ticker="AAPL",
                data_type="10k_rag",
                timestamp=datetime.now(tz=timezone.utc),
            )
        )
        with pytest.raises(ValueError, match="No 10-K RAG index"):
            await run_qa(layer, _make_settings(), "AAPL", "What are the risks?")

    @pytest.mark.asyncio
    async def test_empty_chunks_raises(self) -> None:
        layer = _make_data_layer(rag_index=FakeIndex([]), chunk_count=0)
        # rag_index exists but chunk_count is 0
        layer.fetch = AsyncMock(
            return_value=DataResult(
                data={"rag_index": FakeIndex([]), "chunk_count": 0},
                provider="sec_edgar",
                ticker="AAPL",
                data_type="10k_rag",
                timestamp=datetime.now(tz=timezone.utc),
            )
        )
        with pytest.raises(ValueError, match="no sections could be extracted"):
            await run_qa(layer, _make_settings(), "AAPL", "Revenue?")

    @pytest.mark.asyncio
    async def test_no_matching_chunks_returns_message(self) -> None:
        """If BM25 returns no matches, return a helpful message (not LLM call)."""
        empty_index = FakeIndex([])  # search returns []
        layer = _make_data_layer(rag_index=empty_index, chunk_count=10)
        result = await run_qa(layer, _make_settings(), "AAPL", "zzz_gibberish?")
        assert "No relevant passages" in result

    @pytest.mark.asyncio
    async def test_successful_qa_calls_llm(self, monkeypatch) -> None:
        """With valid chunks, the runner should call the LLM and return its output."""
        chunks = [
            FakeChunk(
                text="Risk factors include regulatory changes.",
                source="[Item 1A - Risk Factors]",
                chunk_index=0,
                char_start=0,
            ),
            FakeChunk(
                text="Revenue grew 8% driven by services.",
                source="[Item 7 - MD&A]",
                chunk_index=5,
                char_start=500,
            ),
        ]
        index = FakeIndex(chunks, scores=[3.5, 2.1])
        layer = _make_data_layer(rag_index=index, chunk_count=50)

        # Mock the Agent to avoid real LLM calls
        mock_agent_instance = MagicMock()
        mock_run_result = MagicMock()
        mock_run_result.output = "Based on [Item 1A], regulatory risk is the primary concern."
        mock_agent_instance.run = AsyncMock(return_value=mock_run_result)

        mock_agent_cls = MagicMock(return_value=mock_agent_instance)
        monkeypatch.setattr("finagent.engine.analysis.qa.Agent", mock_agent_cls)

        result = await run_qa(layer, _make_settings(), "AAPL", "What are the risks?")
        assert "regulatory risk" in result
        # Verify the prompt sent to LLM contains our chunks
        call_args = mock_agent_instance.run.call_args[0][0]
        assert "Risk factors include regulatory changes" in call_args
        assert "[Item 1A - Risk Factors]" in call_args
        assert "AAPL" in call_args
