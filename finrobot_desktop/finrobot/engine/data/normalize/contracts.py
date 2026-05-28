"""Canonical, runtime-enforced contracts for normalized provider output.

These replace the documentation-only ``keys.py`` TypedDict. Anything that
reaches compute/route/UI must be one of these models, so downstream code can
stop guessing provider-specific dict shapes (ADR-0004 root cause #1).

Provenance is a first-class field on every result: the provider that actually
served it, the data's semantic ``as_of`` (latest bar date / fiscal period end),
the wall-clock ``fetched_at``, and any ``degraded`` markers (close-only history,
TTM lag, inferred currency). The freshness pill must read ``as_of`` — not the
fetch timestamp — so it can't claim "实时" over a stale closing price.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Degradation markers carried in ``Provenance.degraded``. Surfaced to the UI so
# a fallback is visible rather than silent.
DEGRADED_CLOSE_ONLY = "close_only"  # no intraday OHLC; 52w high/low fall back to close
DEGRADED_TTM_LAG = "ttm_lag"  # TTM denominator trails the latest reported quarter
DEGRADED_CCY_INFERRED = "ccy_inferred"  # reporting currency inferred, not provider-stated


class Provenance(BaseModel):
    """Where a number came from and how fresh/trustworthy it is."""

    model_config = ConfigDict(frozen=False)

    provider: str
    as_of: datetime = Field(description="Semantic time of the data (latest bar / period end)")
    fetched_at: datetime = Field(description="Wall-clock time the upstream fetch completed")
    from_cache: bool = False
    degraded: list[str] = Field(default_factory=list)


class PriceBar(BaseModel):
    """One OHLCV bar. ``open/high/low`` are None for close-only feeds."""

    model_config = ConfigDict(frozen=False)

    date: date
    close: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None

    def high_or_close(self) -> float:
        return self.high if self.high is not None else self.close

    def low_or_close(self) -> float:
        return self.low if self.low is not None else self.close


class NormalizedPrice(BaseModel):
    """Canonical price series — already trimmed to the trailing 52 calendar
    weeks, ascending by date, in a single quote currency.

    All derived market metrics (52w high/low, 1y return, latest-session change)
    are computed from this one object so they can't diverge across endpoints.
    """

    model_config = ConfigDict(frozen=False)

    ticker: str
    quote_currency: str = "USD"
    bars: list[PriceBar] = Field(default_factory=list)
    current_price: float
    is_ohlc_complete: bool = True
    exchange: str | None = None
    provenance: Provenance

    def fifty_two_week_high(self) -> float | None:
        if not self.bars:
            return None
        return max(b.high_or_close() for b in self.bars)

    def fifty_two_week_low(self) -> float | None:
        if not self.bars:
            return None
        return min(b.low_or_close() for b in self.bars)

    def trailing_1y_return_pct(self) -> float | None:
        """Return % from the earliest in-window close to the latest close.

        Bars are pre-trimmed to the trailing 52 weeks, so ``bars[0]`` is the
        ~1-year-ago anchor — not an 17-month-old print (ADR-0004 root #2).
        """
        if len(self.bars) < 2:
            return None
        first = self.bars[0].close
        last = self.bars[-1].close
        if first == 0:
            return None
        return (last - first) / first * 100

    def latest_session_change(self) -> tuple[float | None, float | None]:
        """(change, change_pct) for the session of the most recent bar.

        This is the move into ``bars[-1].date`` (= the session ``current_price``
        belongs to), NOT "today". The UI must label it with ``provenance.as_of``
        so a closed-market view doesn't read the last session as live (audit A/B).
        """
        if len(self.bars) < 2:
            return None, None
        prev_close = self.bars[-2].close
        last_close = self.bars[-1].close
        if prev_close == 0:
            return None, None
        change = last_close - prev_close
        return change, change / prev_close * 100


class NormalizedFinancials(BaseModel):
    """Canonical fundamentals. Currency and TTM period are fields, not
    conventions, so ADR currency mismatches and TTM lag are visible."""

    model_config = ConfigDict(frozen=False)

    ticker: str
    company_name: str | None = None
    reporting_currency: str = "USD"  # IS/BS currency
    quote_currency: str = "USD"  # market_cap / price currency (differs for ADRs)
    period_end: date | None = None
    period_basis: Literal["ttm", "annual", "quarterly"] = "ttm"
    as_of: datetime = Field(description="Semantic time of the data (= period_end when known)")

    revenue: float
    ebitda: float | None = None
    net_income: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    market_cap: float
    shares_outstanding: float | None = None
    current_price: float | None = None
    pe_ratio: float | None = None
    pe_ttm_lag_quarters: int | None = None  # >0 → UI annotates "TTM 截至 X，落后 N 季"
    total_debt: float | None = None
    total_cash: float | None = None
    depreciation_amortization: float | None = None
    rd_expense: float | None = None
    sga_expense: float | None = None
    interest_expense: float | None = None
    dividend_per_share: float | None = None
    dividend_yield: float | None = None
    payout_ratio: float | None = None
    book_value_per_share: float | None = None
    return_on_equity: float | None = None
    forward_eps: float | None = None
    forward_pe: float | None = None
    trailing_eps: float | None = None
    industry: str | None = None
    sector: str | None = None
    country: str | None = None
    beta: float | None = None

    provenance: Provenance
