#!/usr/bin/env python
# coding: utf-8

"""Optional Adanos-backed retail sentiment snapshot for US stock reports."""

from __future__ import annotations

from statistics import mean
from typing import Any, Dict, List, Optional

import requests


class RetailSentimentClient:
    """Fetch structured retail sentiment snapshots for one stock ticker."""

    PLATFORM_SPECS = (
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

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.adanos.org",
        timeout: int = 10,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_snapshot(self, ticker: str, days_back: int = 7) -> Dict[str, Any]:
        """Return a compact retail sentiment snapshot across public sources."""
        normalized_ticker = ticker.strip().upper().replace("$", "")
        sources: List[Dict[str, Any]] = []

        for spec in self.PLATFORM_SPECS:
            try:
                row = self._fetch_source_row(spec, normalized_ticker, days_back)
            except Exception as exc:
                print(
                    f"Warning: Failed to fetch retail sentiment for {normalized_ticker} "
                    f"from {spec['label']}: {exc}"
                )
                row = None
            sources.append(self._normalize_source(spec, row))

        covered_sources = [source for source in sources if source["has_data"]]
        buzz_values = [source["buzz_score"] for source in covered_sources]
        bullish_values = [
            source["bullish_pct"]
            for source in covered_sources
            if source["bullish_pct"] is not None
        ]

        return {
            "ticker": normalized_ticker,
            "period_days": days_back,
            "coverage": f"{len(covered_sources)}/{len(self.PLATFORM_SPECS)}",
            "coverage_ratio": round(len(covered_sources) / len(self.PLATFORM_SPECS), 2),
            "average_buzz": round(mean(buzz_values), 1) if buzz_values else None,
            "bullish_avg": round(mean(bullish_values), 1) if bullish_values else None,
            "source_alignment": self._compute_source_alignment(bullish_values),
            "sources": sources,
        }

    def _fetch_source_row(
        self,
        spec: Dict[str, str],
        ticker: str,
        days_back: int,
    ) -> Optional[Dict[str, Any]]:
        response = requests.get(
            f"{self.base_url}{spec['path']}",
            params={"tickers": ticker, "days": days_back},
            headers={"X-API-Key": self.api_key},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()

        for item in payload.get("stocks", []):
            item_ticker = str(item.get("ticker") or "").strip().upper().replace("$", "")
            if item_ticker == ticker:
                return item

        return None

    def _normalize_source(
        self,
        spec: Dict[str, str],
        row: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        buzz_score = self._safe_float(row.get("buzz_score")) if row else 0.0
        bullish_pct = self._safe_float(row.get("bullish_pct")) if row else None
        activity_value = self._safe_int(row.get(spec["activity_field"])) if row else 0
        trend = row.get("trend") if row else None

        has_data = bool(
            buzz_score > 0
            or activity_value > 0
            or bullish_pct is not None
        )

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

    @staticmethod
    def _compute_source_alignment(bullish_values: List[float]) -> str:
        if not bullish_values:
            return "No coverage"
        if len(bullish_values) == 1:
            return "Single-source signal"

        avg_value = mean(bullish_values)
        spread = max(bullish_values) - min(bullish_values)

        if spread <= 10:
            if avg_value >= 55:
                return "Bullish alignment"
            if avg_value <= 45:
                return "Bearish alignment"
            return "Neutral alignment"
        if spread <= 20:
            return "Partial divergence"
        return "Wide divergence"

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_int(value: Any) -> int:
        if value is None or value == "":
            return 0
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


def format_retail_sentiment_for_prompt(snapshot: Dict[str, Any]) -> str:
    """Render a compact plain-text summary for the news summary prompt."""
    if not snapshot:
        return ""

    lines = [
        "## Retail Sentiment Insights",
        f"- Average Buzz: {snapshot.get('average_buzz', 'N/A')}/100" if snapshot.get("average_buzz") is not None else "- Average Buzz: N/A",
        f"- Bullish Avg: {snapshot.get('bullish_avg', 'N/A')}%" if snapshot.get("bullish_avg") is not None else "- Bullish Avg: N/A",
        f"- Source Alignment: {snapshot.get('source_alignment', 'N/A')}",
        f"- Coverage: {snapshot.get('coverage', '0/3')}",
    ]

    for source in snapshot.get("sources", []):
        if not source.get("has_data"):
            continue
        bullish = (
            f"{source['bullish_pct']}%"
            if source.get("bullish_pct") is not None
            else "N/A"
        )
        lines.append(
            f"- {source['label']}: buzz {source['buzz_score']}/100, "
            f"bullish {bullish}, "
            f"{source['activity_label'].lower()} {source['activity_value']}, "
            f"trend {source['trend']}"
        )

    return "\n".join(lines)
