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

from finrobot.engine.data.interface import ProviderError, is_rate_limit_error
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.data.providers.adanos_provider import AlignmentToken
from finrobot.engine.data.ticker import validate_ticker
from finrobot.engine.data.types import DataType
from finrobot.ratelimit import enforce_live_data_limit
from finrobot.warning_text import humanize_warnings as _humanize_warnings

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
    reason: Literal["unconfigured", "provider_error", "rate_limited"] | None = Field(
        default=None,
        description=(
            "Why `available` is False, so the UI never mislabels a transient hiccup "
            "as a missing API key:\n"
            "  • 'unconfigured' — no Adanos key registered → show the 'add key' CTA.\n"
            "  • 'rate_limited' — upstream throttled us (HTTP 429); transient and "
            "self-healing → show a soft 'rate-limited, auto-retrying' notice, NOT a "
            "red outage error (and NEVER a fabricated '5xx': the call never reached "
            "a 5xx, it was throttled).\n"
            "  • 'provider_error' — key IS configured but the call genuinely failed "
            "(non-429 outage) → show a retry affordance, NOT the config CTA.\n"
            "  • None — the snapshot is available (or success)."
        ),
    )
    coverage: str | None = Field(
        default=None, description="N/3 platforms returned data, e.g. '2/3'"
    )
    bullish_pct: float | None = None
    bearish_pct: float | None = None
    average_buzz: float | None = None
    source_alignment: AlignmentToken | None = Field(
        default=None,
        description=(
            "How consistently the platforms agree with each other (direction is "
            "in bullish_pct/bearish_pct, not here): 'aligned' (spread ≤10pp) / "
            "'partial_divergence' (≤20pp) / 'split' (>20pp) / 'single_source' "
            "(only one platform has a view, nothing to cross-check) / 'no_data'."
        ),
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
    enforce_live_data_limit(request)
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
        reason: Literal["rate_limited", "provider_error"] = (
            "rate_limited" if is_rate_limit_error(exc) else "provider_error"
        )
        return SentimentSnapshot(
            ticker=ticker,
            days=days,
            available=False,
            reason=reason,
            warnings=_humanize_warnings([f"adanos 调用失败 — {exc}"]),
        )

    # DataLayer doesn't re-raise on total provider failure: when every Adanos
    # platform fails (e.g. all-429) and no cache exists, it returns a no-data
    # sentinel DataResult (data={"error": ...}, provider="none"). That's a
    # transient failure, not a missing key — never available=True with a null
    # coverage and never the "configure Adanos" CTA. Classify throttle (429,
    # self-healing) vs genuine outage so the UI shows the right state: the old
    # generic 'provider_error' made the card fabricate "Upstream returned 5xx"
    # for what was actually a rate-limit. A stale-cache fallback (real numbers +
    # retry warning) carries no "error" key and flows through to _to_snapshot as
    # the graceful degrade.
    if isinstance(result.data, dict) and result.data.get("error"):
        logger.info("sentiment unavailable for %s: %s", ticker, result.data["error"])
        return SentimentSnapshot(
            ticker=ticker,
            days=days,
            available=False,
            reason=_sentiment_failure_reason(data_layer),
            warnings=_humanize_warnings(
                list(result.warnings) or [f"adanos 调用失败 — {result.data['error']}"]
            ),
        )

    # A stale-cache fallback can carry ZERO usable signal: every platform 429'd,
    # so the DataLayer grafted an old snapshot whose coverage is 0/N with no
    # source data. That is NOT an "available" snapshot — it is a degraded state
    # wearing cached scaffolding. Rendering it available=True both contradicts the
    # 0/N coverage AND trails the cached provider diagnostics into the card. Route
    # it to the same soft reason states as a hard failure so the UI shows the
    # clean rate-limited / retry affordance. A FRESH empty result (untracked
    # ticker, genuine "no buzz") has from_stale_cache=False and flows through
    # below as a legitimate available 0/N state.
    if result.from_stale_cache and not _has_usable_sentiment(result.data):
        logger.info("sentiment stale fallback has no usable signal for %s", ticker)
        return SentimentSnapshot(
            ticker=ticker,
            days=days,
            available=False,
            reason=_sentiment_failure_reason(data_layer),
            warnings=_humanize_warnings(list(result.warnings)),
        )

    return _to_snapshot(ticker, days, result.data, _humanize_warnings(list(result.warnings)))


def _sentiment_failure_reason(
    data_layer: DataLayer,
) -> Literal["rate_limited", "provider_error"]:
    """Classify a sentiment no-data result: upstream rate-limit (429, transient →
    UI can auto-retry) vs a genuine provider failure.

    DataLayer collapses the typed ``RateLimitedProviderError`` into a generic
    no-data sentinel, so the 429-ness is gone by the time we get here — but the
    circuit breaker recorded it (``record_failure(rate_limited=…)``). Read it back
    off ``provider_status()`` for the sentiment-capable provider(s). Worst case
    (a concurrent success resets the flag) we fall back to 'provider_error', which
    is still an honest retry state — never a fabricated 5xx.
    """
    sentiment_providers = {
        p.name
        for p in data_layer._providers  # noqa: SLF001 — only sane way to introspect caps
        if DataType.SENTIMENT in p.capabilities()
    }
    for name, _available, state in data_layer.provider_status():
        if name in sentiment_providers and state.last_rate_limited:
            return "rate_limited"
    return "provider_error"


def _has_usable_sentiment(raw: Any) -> bool:
    """True when a snapshot dict carries an actual sentiment signal — at least one
    platform with data, or a finite aggregate bullish reading. A stale-cache graft
    with 0/N coverage and no source data is NOT usable (degraded); a fresh 0/N
    "no buzz" answer is distinguished by the caller via ``from_stale_cache``."""
    if not isinstance(raw, dict):
        return False
    sources = raw.get("sources")
    if isinstance(sources, list) and any(
        isinstance(s, dict) and s.get("has_data") for s in sources
    ):
        return True
    return _coerce_finite_float(raw.get("bullish_avg")) is not None


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
