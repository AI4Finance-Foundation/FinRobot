"""Earnings call transcript models.

FMP provides full earnings call transcripts via
``/earning_call_transcript/{ticker}?quarter={q}&year={y}``.
These models structure that data for display and downstream analysis.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class EarningsCallTranscript(BaseModel):
    """A single quarter's earnings call transcript."""

    ticker: str
    quarter: int = Field(ge=1, le=4)
    year: int
    date: datetime | None = None
    content: str
    summary: str | None = None  # LLM-generated summary, filled later


class EarningsCallList(BaseModel):
    """Collection of transcripts for a ticker, ordered most-recent first."""

    ticker: str
    transcripts: list[EarningsCallTranscript]
