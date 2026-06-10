"""Retail sentiment endpoint (v5 §6.12 散户情绪 section).

Thin wrapper over the adanos provider — the heavy lifting (concurrent
Reddit / X.com / Polymarket fetch + per-source aggregation) already lives
in `AdanosProvider._fetch_sentiment`. This route normalises the payload
into a UI-friendly shape and degrades cleanly when the Adanos API key
isn't configured (spec §6.X.5 cold-start rule: empty state with a CTA
to settings).
"""

from __future__ import annotations

import logging
import math
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.requests import Request

from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.data.ticker import validate_ticker
from finrobot.engine.data.types import DataType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sentiment", tags=["sentiment"])


class SentimentSource(BaseModel):
    """One platform's contribution to the aggregate sentiment view."""

    platform: str = Field(description="Reddit / X.com / Polymarket")
    has_data: bool
    bullish_pct: float | None = None
    activity_label: str = Field(description="'Mentions' / 'Trades'")
    activity_value: int | None = None


class SentimentSnapshot(BaseModel):
    """``GET /api/sentiment/{ticker}`` payload (v5 §6.12)."""

    ticker: str
    days: int
    available: bool = Field(
        description=(
            "False when the Adanos provider isn't configured (no API key) or all "
            "platform requests failed — UI shows '未配置 Adanos · [跳设置 →]'."
        )
    )
    reason: Literal["unconfigured", "provider_error"] | None = Field(
        default=None,
        description=(
            "Why `available` is False, so the UI never mislabels a transient hiccup "
            "as a missing API key:\n"
            "  • 'unconfigured' — no Adanos key registered → show the 'add key' CTA.\n"
            "  • 'provider_error' — key IS configured but the call failed → show a "
            "retry affordance, NOT the config CTA.\n"
            "  • None — the snapshot is available (or success)."
        ),
    )
    coverage: str | None = Field(
        default=None, description="N/3 platforms returned data, e.g. '2/3'"
    )
    bullish_pct: float | None = None
    bearish_pct: float | None = None
    average_buzz: float | None = None
    source_alignment: str | None = Field(
        default=None,
        description="'aligned' / 'split' / 'no_data' — how consistently the sources agree.",
    )
    sources: list[SentimentSource] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@router.get("/{ticker}", response_model=SentimentSnapshot)
async def get_sentiment(
    ticker: str,
    request: Request,
    days: int = Query(7, ge=1, le=30),
) -> SentimentSnapshot:
    """Aggregate Reddit / X.com / Polymarket sentiment for one ticker.

    Falls back to ``available=False`` when the Adanos provider isn't loaded
    (typically because the API key is missing) — the UI hides the section
    and shows a "configure Adanos" link, per the v5 cold-start rules.
    """
    data_layer = _data_layer(request)
    try:
        ticker = validate_ticker(ticker.lstrip("$"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if data_layer is None or not _has_sentiment_provider(data_layer):
        return SentimentSnapshot(
            ticker=ticker,
            days=days,
            available=False,
            reason="unconfigured",
            warnings=["adanos provider 未配置 — 在设置中填入 API key 后即可解锁散户情绪"],
        )

    try:
        result = await data_layer.fetch(DataType.SENTIMENT, ticker, days_back=days)
    except (ProviderError, ValueError, KeyError) as exc:
        logger.info("sentiment fetch failed for %s: %s", ticker, exc)
        return SentimentSnapshot(
            ticker=ticker,
            days=days,
            available=False,
            reason="provider_error",
            warnings=[f"adanos 调用失败 — {exc}"],
        )

    return _to_snapshot(ticker, days, result.data, list(result.warnings))


def _data_layer(request: Request) -> DataLayer | None:
    deps = getattr(request.app.state, "deps", None)
    return getattr(deps, "data_layer", None) if deps is not None else None


def _has_sentiment_provider(data_layer: DataLayer) -> bool:
    """Adanos isn't always loaded — only when the API key is configured."""
    for provider in data_layer._providers:  # noqa: SLF001 — only sane way to introspect
        if DataType.SENTIMENT in provider.capabilities():
            return True
    return False


def _to_snapshot(
    ticker: str, days: int, raw: dict[str, Any], warnings: list[str]
) -> SentimentSnapshot:
    bullish = _coerce_finite_float(raw.get("bullish_avg"))
    bearish = (100.0 - bullish) if bullish is not None else None
    sources_raw_value = raw.get("sources")
    sources_raw: list[Any] = sources_raw_value if isinstance(sources_raw_value, list) else []
    sources = [_source(item) for item in sources_raw]
    return SentimentSnapshot(
        ticker=ticker,
        days=days,
        available=True,
        coverage=raw.get("coverage"),
        bullish_pct=bullish,
        bearish_pct=bearish,
        average_buzz=_coerce_finite_float(raw.get("average_buzz")),
        source_alignment=raw.get("source_alignment"),
        sources=sources,
        warnings=warnings,
    )


def _source(item: Any) -> SentimentSource:
    if not isinstance(item, dict):
        return SentimentSource(platform="unknown", has_data=False, activity_label="Mentions")
    activity_value = item.get("activity_value")
    return SentimentSource(
        platform=str(item.get("platform") or item.get("label") or "unknown"),
        has_data=bool(item.get("has_data", False)),
        bullish_pct=_coerce_finite_float(item.get("bullish_pct")),
        activity_label=str(item.get("activity_label") or "Mentions"),
        activity_value=_coerce_activity_value(activity_value),
    )


def _coerce_finite_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        value = float(v)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _coerce_activity_value(v: Any) -> int | None:
    value = _coerce_finite_float(v)
    if value is None or value < 0:
        return None
    return int(value)
