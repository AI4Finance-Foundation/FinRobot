"""RAG-based Q&A over SEC 10-K filings.

What this code does that raw LLM cannot: retrieves specific passages from
real SEC filings using BM25 ranking, then grounds the LLM answer in actual
regulatory disclosures rather than parametric memory. The LLM receives
exact text chunks with source labels ([Item 1A - Risk Factors], etc.)
so it can cite specific sections.
"""

from __future__ import annotations

import logging

from pydantic_ai import Agent

from finagent.config import FinAgentSettings
from finagent.engine.data.layer import DataLayer
from finagent.engine.data.types import DataType

logger = logging.getLogger(__name__)

_QA_SYSTEM_PROMPT = (
    "You are a senior financial analyst answering questions about SEC filings. "
    "Base your answer ONLY on the provided document excerpts. "
    "Cite the source section (e.g. [Item 1A]) for each key claim. "
    "If the excerpts do not contain enough information, say so explicitly. "
    "Be precise and factual."
)


async def run_qa(
    data_layer: DataLayer,
    settings: FinAgentSettings,
    ticker: str,
    question: str,
    top_k: int = 5,
) -> str:
    """Fetch 10-K, retrieve relevant chunks via BM25, answer the question.

    Returns the LLM answer with source citations.
    Raises ValueError if no 10-K data or chunks are available.
    """
    # 1. Fetch RAG index from SEC provider
    result = await data_layer.fetch(DataType.RAG_10K, ticker)
    rag_index = result.data.get("rag_index")

    if rag_index is None:
        raise ValueError(
            f"No 10-K RAG index available for {ticker}. "
            "Ensure SEC EDGAR is accessible and the company has filed a 10-K."
        )

    chunk_count = result.data.get("chunk_count", 0)
    if chunk_count == 0:
        raise ValueError(
            f"10-K filing for {ticker} was fetched but no sections could be extracted."
        )

    # 2. Search for relevant chunks
    chunks_with_scores = rag_index.search(question, top_k=top_k)

    if not chunks_with_scores:
        return (
            f"No relevant passages found in {ticker}'s 10-K filing for your question. "
            "Try rephrasing with different keywords."
        )

    # 3. Build context from retrieved chunks
    context_parts: list[str] = []
    for i, (chunk, score) in enumerate(chunks_with_scores, 1):
        source_label = chunk.source or f"Chunk {chunk.chunk_index}"
        context_parts.append(
            f"[Excerpt {i}] (Source: {source_label}, Relevance: {score:.2f})\n"
            f"{chunk.text}"
        )
    context = "\n\n---\n\n".join(context_parts)

    # 4. Build prompt and call LLM
    prompt = (
        f"## Question about {ticker.upper()}'s 10-K filing\n\n"
        f"**Question:** {question}\n\n"
        f"## Relevant Excerpts from 10-K\n\n{context}\n\n"
        f"## Instructions\n"
        f"Answer the question using ONLY the excerpts above. "
        f"Cite specific sections. If information is insufficient, state that clearly."
    )

    agent: Agent[None, str] = Agent(
        settings.create_model(),
        instructions=_QA_SYSTEM_PROMPT,
    )
    llm_result = await agent.run(prompt)
    return llm_result.output
