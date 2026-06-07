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

# Canonical contract version. Bump whenever a Normalized* model changes shape
# in a way that makes an old cached payload unsafe to deserialize/trust. The
# cache encodes this in the canonical slot key (``…:canonical:v<N>``) so a bump
# auto-invalidates stale entries with no migration script (ADR-0006 decision C1).
# v2: added NormalizedFinancials.operating_cash_flow / capital_expenditure (TTM)
# so the cashflow analysis reports a real OCF−CapEx FCF; old v1 canonicals lack
# these and would serve None, so bump to refetch.
# v3: PRICE canonical now flows through the validated fetch_price() path, and
# audit-critical EV / TTM fields are treated as semantic cache shape changes.
# Old v2 payloads may lack price cross-source warnings and optional audit fields,
# which changes publication safety even when Pydantic can deserialize them.
# NOT bumped for the revenue/market_cap float→(float | None) change (BUG-038/039/042):
# old v2 payloads store these as floats, which deserialize cleanly into the wider
# type, and every downstream consumer collapses a stale fabricated 0.0 and a fresh
# None onto the same path (``if not revenue: raise`` / ``_fmt_num`` → "N/A"), so no
# cached entry can surface a wrong number. Bumping would only invalidate valid
# caches for a semantically identical result.
CANONICAL_CONTRACT_VERSION = 3

# Degradation markers carried in ``Provenance.degraded``. Surfaced to the UI so
# a fallback is visible rather than silent.
DEGRADED_CLOSE_ONLY = "close_only"  # no intraday OHLC; 52w high/low fall back to close
DEGRADED_TTM_LAG = "ttm_lag"  # TTM denominator trails the latest reported quarter
DEGRADED_CCY_INFERRED = "ccy_inferred"  # reporting currency inferred, not provider-stated
# provider gave no real-time current_price; using the latest bar's close as a
# stand-in. Lets the UI avoid claiming a stale close is a live "实时" quote.
DEGRADED_PRICE_FALLBACK_CLOSE = "price_fallback_close"
# Two live quote sources disagreed beyond tolerance on the current price. The
# primary value still flows as a flagged number; downstream publish gates can
# inspect the field-suffixed marker instead of parsing warning prose.
DEGRADED_PRICE_DIVERGENCE_PREFIX = "price_divergence"
# Two providers disagreed beyond tolerance on a KEY financials field
# (revenue / net_income). The primary (FMP) value still flows — analysts prefer
# a flagged number over no number — but this STRUCTURED marker lets dcf_seed /
# comps programmatically down-confidence or tag [金融待核] instead of relying on
# the free-text cross_validate warning. Field-suffixed (``provider_divergence:revenue``)
# so consumers know which number to distrust; build with ``degraded_provider_divergence(field)``.
DEGRADED_PROVIDER_DIVERGENCE_PREFIX = "provider_divergence"
# period_basis was absent or unrecognized; defaulted to "ttm". Prevents silently
# mislabeling annual/quarterly data as TTM when a provider omits the field or
# sends a non-standard string (e.g. "fy2024", "ltm").
DEGRADED_PERIOD_BASIS_UNKNOWN = "period_basis_unknown"
# A provider was in circuit-breaker cooldown and skipped for this fetch.
# Provider-suffixed (``circuit_open:fmp``) so the UI can name the absent source.
DEGRADED_CIRCUIT_OPEN_PREFIX = "circuit_open"


def degraded_circuit_open(provider_name: str) -> str:
    """Structured ``Provenance.degraded`` marker for a circuit-open provider skip,
    e.g. ``circuit_open:fmp``."""
    return f"{DEGRADED_CIRCUIT_OPEN_PREFIX}:{provider_name}"


def degraded_provider_divergence(field: str) -> str:
    """Structured ``Provenance.degraded`` marker for a cross-provider KEY-field
    divergence, e.g. ``provider_divergence:revenue``."""
    return f"{DEGRADED_PROVIDER_DIVERGENCE_PREFIX}:{field}"


def degraded_price_divergence(field: str) -> str:
    """Structured ``Provenance.degraded`` marker for a cross-source PRICE
    discrepancy, e.g. ``price_divergence:current_price``."""

    return f"{DEGRADED_PRICE_DIVERGENCE_PREFIX}:{field}"


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
    # Free-text warnings carried from the raw fetch (e.g. cross-provider
    # discrepancies, stale-cache notices). Distinct from provenance.degraded,
    # which is an enum of structured fallback markers.
    warnings: list[str] = Field(default_factory=list)

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

    revenue: float | None = None
    ebitda: float | None = None
    net_income: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    # Absolute income-statement line items feeding the two EBITDA calibers
    # (engine.compute.multiples). Carried alongside the margins because the
    # operating EBITDA = operating_income + D&A and the reported EBITDA =
    # net_income + income_tax_expense + interest_expense + D&A.
    operating_income: float | None = None
    income_tax_expense: float | None = None
    market_cap: float | None = None
    shares_outstanding: float | None = None
    current_price: float | None = None
    pe_ratio: float | None = None
    pe_ttm_lag_quarters: int | None = None  # >0 → UI annotates "TTM 截至 X，落后 N 季"
    total_debt: float | None = None
    total_cash: float | None = None
    # EV-bridge completeness (numeric-audit family 3). New optional fields are
    # read-compatible with cached canonical payloads (old entries → None), so the
    # schema version is intentionally NOT bumped (same call as BUG-038/039/042).
    preferred_stock: float | None = None
    noncontrolling_interest: float | None = None
    depreciation_amortization: float | None = None
    rd_expense: float | None = None
    sga_expense: float | None = None
    interest_expense: float | None = None
    # TTM cash-flow actuals so the cashflow analysis reports a real, traceable
    # FCF (= OCF − CapEx) instead of letting the LLM hand-compute it from a
    # prompt formula. capex is stored as a positive magnitude (outflow). None
    # when the provider didn't supply the cash-flow statement.
    operating_cash_flow: float | None = None
    capital_expenditure: float | None = None
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
    # Quarter-end dates of the quarters summed into a TTM snapshot (numeric-audit
    # family-4 non-overlap check). Populated only on the FMP TTM path (Σ 4
    # quarters); empty on yfinance / annual rows. Optional → read-compatible with
    # cached canonical payloads (BUG-038 precedent), so no schema-version bump.
    ttm_quarter_ends: list[date] = Field(default_factory=list)

    provenance: Provenance
    # Free-text warnings carried from the raw fetch (e.g. cross-provider
    # discrepancies surfaced by cross_validate). Distinct from
    # provenance.degraded, which is an enum of structured fallback markers.
    warnings: list[str] = Field(default_factory=list)
