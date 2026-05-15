"""RAG Q&A endpoint for SEC 10-K filings."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.requests import Request

from finagent.engine.data.interface import ProviderError

router = APIRouter(prefix="/api/ask", tags=["ask"])

logger = logging.getLogger(__name__)


class AskRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=10)
    question: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)


class Citation(BaseModel):
    source: str
    text: str
    relevance: float


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    chunk_count: int


@router.post("", response_model=AskResponse)
async def ask_question(request: Request, body: AskRequest) -> AskResponse:
    """Ask a question about a company's 10-K filing using BM25 RAG.

    Fetches the latest 10-K from SEC EDGAR, retrieves relevant passages
    via BM25 keyword search, and generates an LLM answer with source citations.
    """
    from finagent.engine.data.types import DataType

    deps = request.app.state.deps
    data_layer = deps.data_layer
    settings = deps.settings

    # Fetch RAG index
    try:
        result = await data_layer.fetch(DataType.RAG_10K, body.ticker.upper())
    except (ValueError, ProviderError) as e:
        raise HTTPException(
            status_code=404,
            detail=f"Could not fetch 10-K data for {body.ticker.upper()}: {e}",
        ) from e

    rag_index = result.data.get("rag_index")
    chunk_count = result.data.get("chunk_count", 0)

    if rag_index is None or chunk_count == 0:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No 10-K content available for {body.ticker.upper()}. "
                "Ensure the company has filed a 10-K with SEC EDGAR."
            ),
        )

    # Search for relevant chunks
    chunks_with_scores = rag_index.search(body.question, top_k=body.top_k)

    if not chunks_with_scores:
        return AskResponse(
            answer=(
                f"No relevant passages found in {body.ticker.upper()}'s 10-K filing "
                "for your question. Try rephrasing with different keywords."
            ),
            citations=[],
            chunk_count=chunk_count,
        )

    # Build citations
    citations: list[Citation] = []
    context_parts: list[str] = []
    for i, (chunk, score) in enumerate(chunks_with_scores, 1):
        source_label = chunk.source or f"Chunk {chunk.chunk_index}"
        citations.append(
            Citation(
                source=source_label,
                text=chunk.text[:500],  # Truncate for response size
                relevance=round(score, 3),
            )
        )
        context_parts.append(
            f"[Excerpt {i}] (Source: {source_label}, Relevance: {score:.2f})\n{chunk.text}"
        )

    context = "\n\n---\n\n".join(context_parts)

    # Generate LLM answer
    try:
        from pydantic_ai import Agent

        prompt = (
            f"## Question about {body.ticker.upper()}'s 10-K filing\n\n"
            f"**Question:** {body.question}\n\n"
            f"## Relevant Excerpts from 10-K\n\n{context}\n\n"
            f"## Instructions\n"
            f"Answer the question using ONLY the excerpts above. "
            f"Cite specific sections (e.g. [Item 1A]). "
            f"If information is insufficient, state that clearly."
        )

        agent: Agent[None, str] = Agent(
            settings.create_model(),
            instructions=(
                "You are a senior financial analyst answering questions about SEC filings. "
                "Base your answer ONLY on the provided document excerpts. "
                "Cite the source section for each key claim. "
                "If the excerpts do not contain enough information, say so explicitly. "
                "Be precise and factual."
            ),
        )
        llm_result = await agent.run(prompt)
        answer = llm_result.output
    except (ValueError, RuntimeError) as e:
        logger.warning("LLM call failed for ask endpoint: %s", e)
        answer = (
            "Could not generate an AI answer at this time. "
            "The relevant excerpts are shown below in the citations."
        )

    return AskResponse(
        answer=answer,
        citations=citations,
        chunk_count=chunk_count,
    )
