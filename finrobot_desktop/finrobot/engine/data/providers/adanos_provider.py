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
from typing import Any

import httpx

from finrobot.engine.data.interface import DataProvider, DataResult, ProviderError
from finrobot.engine.data.types import DataType

logger = logging.getLogger(__name__)

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
        tasks = [
            self._fetch_one_platform(spec, ticker, days_back)
            for spec in _PLATFORM_SPECS
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        sources: list[dict[str, Any]] = []
        warnings: list[str] = []

        for spec, result in zip(_PLATFORM_SPECS, results):
            if isinstance(result, BaseException):
                warnings.append(f"{spec['label']}: {result}")
                sources.append(_empty_source(spec))
            else:
                sources.append(result)

        covered = [s for s in sources if s["has_data"]]
        buzz_values = [s["buzz_score"] for s in covered]
        bullish_values = [
            s["bullish_pct"] for s in covered if s["bullish_pct"] is not None
        ]

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
            resp = await self._get(
                spec["path"], params={"tickers": ticker, "days": days_back}
            )
        except httpx.TimeoutException as e:
            raise ProviderError(f"Adanos timeout for {spec['label']}: {e}") from e
        except httpx.HTTPStatusError as e:
            raise ProviderError(f"Adanos API error for {spec['label']}: {e}") from e

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
    bullish_pct = _safe_float(row.get("bullish_pct")) if row else None
    activity_value = _safe_int(row.get(spec["activity_field"])) if row else 0
    trend = row.get("trend") if row else None

    has_data = bool(buzz_score > 0 or activity_value > 0 or bullish_pct is not None)

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


def _compute_alignment(bullish_values: list[float]) -> str:
    """Classify source alignment based on bullish_pct values."""
    if not bullish_values:
        return "No coverage"
    if len(bullish_values) == 1:
        return "Single-source signal"

    avg = mean(bullish_values)
    spread = max(bullish_values) - min(bullish_values)

    if spread <= 10:
        if avg >= 55:
            return "Bullish alignment"
        if avg <= 45:
            return "Bearish alignment"
        return "Neutral alignment"
    if spread <= 20:
        return "Partial divergence"
    return "Wide divergence"


def _safe_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0
