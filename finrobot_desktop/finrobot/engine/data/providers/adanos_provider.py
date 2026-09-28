"""Adanos Finance retail sentiment provider.

Fetches retail sentiment data from Reddit, X.com, and Polymarket via the
Adanos Finance API (https://api.adanos.org). Three platform endpoints are
queried concurrently; partial failures degrade gracefully.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from statistics import mean
from typing import Any, Literal

import httpx

from finrobot.engine.data.interface import (
    DataProvider,
    DataResult,
    ProviderError,
    RateLimitedProviderError,
    is_rate_limit_error,
)
from finrobot.engine.data.types import DataType

logger = logging.getLogger(__name__)

# Cross-platform agreement tokens. The single source of truth for the whole
# chain: _compute_alignment output ⊆ this Literal ⊆ route schema ⊆ frontend
# ALIGNMENT_KEYS ⊆ i18n keys (workspace.market.sentimentAlignment.*).
AlignmentToken = Literal["aligned", "partial_divergence", "split", "single_source", "no_data"]

_BASE_URL = "https://api.adanos.org"
_TIMEOUT = 10.0
_MIN_INTERVAL = 0.5  # conservative; Adanos rate-limit policy not published

_PLATFORM_SPECS: tuple[dict[str, str], ...] = (
    {
        "key": "reddit",
        "label": "Reddit",
        "path": "/reddit/stocks/v1/compare",
        "activity_field": "mentions",
        "activity_label": "Mentions",
    },
    {
        "key": "x",
        "label": "X.com",
        "path": "/x/stocks/v1/compare",
        "activity_field": "mentions",
        "activity_label": "Mentions",
    },
    {
        "key": "polymarket",
        "label": "Polymarket",
        "path": "/polymarket/stocks/v1/compare",
        "activity_field": "trade_count",
        "activity_label": "Trades",
    },
)


class AdanosProvider(DataProvider):
    """DataProvider backed by Adanos Finance API.

    Provides retail sentiment snapshots aggregated across Reddit, X.com,
    and Polymarket. API key required — get one at https://adanos.org/
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._lock = asyncio.Lock()
        self._last_call: float = 0.0
        # Reuse one AsyncClient across the session to amortise TLS handshakes.
        self._client = httpx.AsyncClient(timeout=_TIMEOUT)

    @property
    def name(self) -> str:
        return "adanos"

    def capabilities(self) -> list[str | DataType]:
        return [DataType.SENTIMENT]

    async def fetch(self, ticker: str, data_type: str | DataType, **kwargs: Any) -> DataResult:
        if data_type != DataType.SENTIMENT:
            raise ProviderError(
                f"data_type '{data_type}' is not supported by Adanos. "
                f"Supported: [{DataType.SENTIMENT}]"
            )

        normalized = ticker.strip().upper().replace("$", "")
        days_back: int = kwargs.get("days_back", 7)
        data = await self._fetch_sentiment(normalized, days_back)

        return DataResult(
            data=data,
            provider=self.name,
            ticker=ticker,
            data_type=DataType.SENTIMENT,
            timestamp=datetime.now(tz=timezone.utc),
            warnings=data.pop("_warnings", []),
        )

    async def _fetch_sentiment(self, ticker: str, days_back: int) -> dict[str, Any]:
        """Fetch sentiment from all platforms concurrently."""
        tasks = [self._fetch_one_platform(spec, ticker, days_back) for spec in _PLATFORM_SPECS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Every platform attempt raised → a provider-level failure (throttle /
        # outage), NOT a "no buzz" answer. Raise so the DataLayer failure path
        # engages: serve last-known-good sentiment from cache (stale + retry
        # note) or a typed no-data result, AND skip caching this empty snapshot /
        # recording a false success. Folding the errors into warnings and
        # returning a successful 0/3 dict (the old behaviour) poisoned the cache
        # for the full TTL and bypassed the circuit breaker — the provider-level
        # form of "provider 全失败不许静默变空" (T2 #4). A successful-but-empty
        # response (untracked ticker, HTTP 200, zero activity) is NOT an
        # exception and flows through below as a legitimate, cacheable result.
        errors = [r for r in results if isinstance(r, BaseException)]
        if len(errors) == len(_PLATFORM_SPECS):
            detail = "; ".join(
                f"{spec['label']}: {_safe_platform_error_detail(r)}"
                for spec, r in zip(_PLATFORM_SPECS, results)
                if isinstance(r, BaseException)
            )
            if all(is_rate_limit_error(e) for e in errors):
                raise RateLimitedProviderError(f"Adanos rate limited on all platforms — {detail}")
            raise ProviderError(f"Adanos unavailable on all platforms — {detail}")

        sources: list[dict[str, Any]] = []
        warnings: list[str] = []

        for spec, result in zip(_PLATFORM_SPECS, results):
            if isinstance(result, BaseException):
                # Emit a CLEAN per-platform note — NEVER the raw exception, whose
                # repr embeds the internal Adanos URL + httpx boilerplate. This
                # warning is cached and later re-surfaced verbatim by the stale
                # cache fallback (layer.py), so it reaches the analyst card; the
                # raw detail is an audit trail that belongs in logs, not the
                # contract (frontend-contract red line ⑥: 审计轨道 ≠ 用户文案).
                logger.debug("adanos %s failed: %r", spec["label"], result)
                kind = "rate limited" if is_rate_limit_error(result) else "unavailable"
                warnings.append(f"{spec['label']} {kind}")
                sources.append(_empty_source(spec))
            else:
                sources.append(result)

        covered = [s for s in sources if s["has_data"]]
        buzz_values = [s["buzz_score"] for s in covered]
        bullish_values = [s["bullish_pct"] for s in covered if s["bullish_pct"] is not None]

        return {
            "ticker": ticker,
            "period_days": days_back,
            "coverage": f"{len(covered)}/{len(_PLATFORM_SPECS)}",
            "coverage_ratio": round(len(covered) / len(_PLATFORM_SPECS), 2),
            "average_buzz": round(mean(buzz_values), 1) if buzz_values else None,
            "bullish_avg": round(mean(bullish_values), 1) if bullish_values else None,
            "source_alignment": _compute_alignment(bullish_values),
            "sources": sources,
            "_warnings": warnings,
        }

    async def _fetch_one_platform(
        self, spec: dict[str, str], ticker: str, days_back: int
    ) -> dict[str, Any]:
        """Fetch and normalize data for a single platform."""
        try:
            resp = await self._get(spec["path"], params={"tickers": ticker, "days": days_back})
        except httpx.TimeoutException as e:
            raise ProviderError(f"Adanos timeout for {spec['label']}") from e
        except httpx.HTTPStatusError as e:
            # ONLY 429 carries throttling semantics; other 4xx/5xx stay generic.
            # _fetch_all currently folds per-platform failures into warnings,
            # but the wrap point types the error anyway so any future caller
            # that propagates it (or reads the warning text) classifies the
            # 429 structurally instead of by message wording.
            if e.response.status_code == 429:
                raise RateLimitedProviderError(
                    f"Adanos rate limited (HTTP 429) for {spec['label']}"
                ) from e
            raise ProviderError(
                f"Adanos API error for {spec['label']} (HTTP {e.response.status_code})"
            ) from e

        payload = resp.json()
        row: dict[str, Any] | None = None
        for item in payload.get("stocks", []):
            item_ticker = str(item.get("ticker", "")).strip().upper().replace("$", "")
            if item_ticker == ticker:
                row = item
                break

        return _normalize_source(spec, row)

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        """Rate-limited GET request to Adanos API."""
        async with self._lock:
            elapsed = time.monotonic() - self._last_call
            if elapsed < _MIN_INTERVAL:
                await asyncio.sleep(_MIN_INTERVAL - elapsed)
            self._last_call = time.monotonic()
            headers = {"X-API-Key": self._api_key}
            resp = await self._client.get(
                f"{_BASE_URL}{path}", params=params or {}, headers=headers
            )
            resp.raise_for_status()
            return resp

    async def close(self) -> None:
        """Release the shared httpx client. Called from DataLayer.close()."""
        await self._client.aclose()


def _normalize_source(spec: dict[str, str], row: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a single platform response into a standard dict."""
    buzz_score = _safe_float(row.get("buzz_score")) if row else 0.0
    # None ≠ 0: a missing bullish_pct must stay None, NOT collapse to 0.0 (= a
    # fabricated "0% bullish / 100% bearish"). _safe_float would coerce it to 0.0,
    # which both poisoned has_data below and fed _compute_alignment a phantom 0.
    bullish_pct = _safe_float_or_none(row.get("bullish_pct")) if row else None
    activity_value = _safe_int(row.get(spec["activity_field"])) if row else 0
    trend = row.get("trend") if row else None

    # "Has data" means the platform actually observed activity (buzz or mentions/
    # trades) for this ticker — NOT merely that a bullish_pct field was present. The
    # Adanos API returns a zero-activity placeholder row for untracked tickers; with
    # ``bullish_pct is not None`` in the disjunct (and _safe_float coercing the
    # absent pct to 0.0) that placeholder read as a confident 0%-bullish source, so
    # an unknown ticker surfaced as "100% bearish, 3/3 aligned" (probe 2026-06-09).
    has_data = bool(buzz_score > 0 or activity_value > 0)

    return {
        "key": spec["key"],
        "label": spec["label"],
        "buzz_score": round(buzz_score, 1),
        "bullish_pct": round(bullish_pct, 1) if bullish_pct is not None else None,
        "activity_label": spec["activity_label"],
        "activity_value": activity_value,
        "trend": trend or "n/a",
        "has_data": has_data,
    }


def _empty_source(spec: dict[str, str]) -> dict[str, Any]:
    """Return a source entry with no data (platform failed)."""
    return {
        "key": spec["key"],
        "label": spec["label"],
        "buzz_score": 0.0,
        "bullish_pct": None,
        "activity_label": spec["activity_label"],
        "activity_value": 0,
        "trend": "n/a",
        "has_data": False,
    }


def _safe_platform_error_detail(exc: BaseException) -> str:
    """Return compact Adanos diagnostics without carrying raw request URLs."""

    if is_rate_limit_error(exc):
        return "rate limited"
    cause = exc.__cause__
    if isinstance(cause, httpx.HTTPStatusError):
        return f"HTTP {cause.response.status_code}"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(cause, httpx.TimeoutException) or isinstance(exc, httpx.TimeoutException):
        return "timeout"
    return type(exc).__name__


def _compute_alignment(bullish_values: list[float]) -> AlignmentToken:
    """Classify cross-platform agreement as a stable enum token.

    Tokens, not prose: this value crosses the language boundary (route Literal →
    frontend whitelist → i18n key), so it must be machine-stable. The old free
    phrases ('Wide divergence' …) never matched the frontend's key set — the
    badge was dead UI. Direction (bullish/bearish) is deliberately absent: the
    bull/bear split bar already shows it; this token answers only "do the
    platforms agree with each other?".
    """
    if not bullish_values:
        return "no_data"
    if len(bullish_values) == 1:
        return "single_source"

    spread = max(bullish_values) - min(bullish_values)
    if spread <= 10:
        return "aligned"
    if spread <= 20:
        return "partial_divergence"
    return "split"


def _safe_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_float_or_none(value: Any) -> float | None:
    """Parse a float, preserving None for absent/blank/unparseable input.

    Distinct from :func:`_safe_float` (which floors to 0.0): for a *percentage*
    like ``bullish_pct`` a missing value is "not reported", not "0% bullish" — the
    None ≠ 0 discipline. Collapsing it to 0.0 fabricated a 100%-bearish signal for
    untracked tickers (probe 2026-06-09)."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0
