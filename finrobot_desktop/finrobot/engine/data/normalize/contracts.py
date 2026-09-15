"""Canonical, runtime-enforced contracts for normalized provider output.

These replace the documentation-only ``keys.py`` TypedDict. Anything that
reaches compute/route/UI must be one of these models, so downstream code can
stop guessing provider-specific dict shapes (ADR-0004 root cause #1).

Provenance is a first-class field on every result: the provider that actually
served it, the data's semantic ``as_of`` (latest bar date / fiscal period end),
the wall-clock ``fetched_at``, and any ``degraded`` markers (close-only history,
TTM lag). The freshness pill must read ``as_of`` — not the fetch timestamp — so
it can't claim "实时" over a stale closing price.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
# v4: FINANCIALS canonical now FX-normalizes a foreign ADR (reporting≠quote) to a
# single currency at the gate (DataLayer._fetch_canonical_uncached, class A). Old v3
# payloads store the mixed-currency snapshot (e.g. TWD IS/BS line items beside a USD
# market quote) that made extract_financial_data form a negative EV — unsafe to
# trust, so a bump forces a refetch+convert instead of serving the laundered mix.
# v5 — 2026-06-10: the country→currency rewrite is retired (21-ticker probe:
# yfinance financialCurrency 21/21 correct; the heuristic corrupted 7/9 genuine
# USD-reporting foreign issuers — see normalize.currency module docstring). Old
# v4 FINANCIALS snapshots for that class hold FX-scaled WRONG line items (SHEL
# ×~1.27, LULU ×~0.73, marked "ccy_inferred"+fx_normalized in provenance) — they
# must miss so normalization re-runs with the tag taken at face value.
# v6 — 2026-06-13: the canonical slot key now folds in the WINNING provider
# (``…:canonical:v6:provider=<name>``). Before, every provider's normalized
# snapshot for one ticker shared a single ``…:canonical:v5/<ticker>`` slot, so a
# silent provider swap (FMP rate-limited → yfinance fallback wins) overwrote a
# DIFFERENT-caliber snapshot under the same key — different period_basis,
# ttm_quarter_ends, or reporting_currency — and a later read served a caliber the
# rest of the run didn't assume. Provider-qualifying the slot isolates calibers;
# old v5 keys are unreachable under the new format → they miss and refetch
# (acceptable, never serves the wrong caliber). period_basis is deliberately NOT
# folded into the key: it is only known AFTER fetch+normalize, so the cache READ
# (which precedes the provider walk) could never reconstruct it — provider
# identity, resolvable up front from the chain, is the implementable caliber gate.
# v7 — 2026-06-14: the FMP FINANCIALS payload now emits book_value_per_share (it
# was None on the FMP path — only yfinance filled it), so commodity-cyclical names
# (MU / memory-storage) recover their PRIMARY comps_pb multiple instead of being
# forced to REVIEW for lack of a cross-checked method. Old v6 canonical snapshots
# carry book_value_per_share=None / pb_ratio=None; the canonical slot is read
# before the raw slot and has a 24h TTL, so without this bump a fresh-but-pre-fix
# snapshot would keep comps_pb dead until expiry. Pairs with the FINANCIALS
# raw-slot bump (cache._RAW_SLOT_VERSION) so the rebuild refetches a payload that
# actually carries the field rather than re-normalizing a stale raw row.
# v8 — 2026-06-22: the FMP FINANCIALS payload now emits dividend_per_share /
# payout_ratio / dividend_yield (/ratios-ttm) and return_on_equity
# (/key-metrics-ttm). These were None on the FMP path — only yfinance filled them,
# but the canonical is single-winning-provider (v6 caliber-isolation decision), so
# any FMP-primary ticker landed dividend/payout/ROE=None → seed_ddm_inputs raised
# "no dividend" for banks and dividend payers (verified KO/JPM 2026-06-22). Old v7
# canonical snapshots carry these as None; the canonical slot is read before the
# raw slot and has a 24h TTL, so without this bump a fresh-but-pre-fix snapshot
# would keep DDM dead until expiry. Pairs with the FINANCIALS raw-slot bump.
# v9 — 2026-07-01: PRICE canonical no longer silently defaults a missing
# quote_currency to USD. Old PRICE snapshots may have stamped foreign local
# quotes (TWD/HKD/JPY) as USD, letting coverage/valuation compare native prices
# against USD targets. Miss old canonicals so full PRICE refetches with an
# explicit quote-currency tag or a visible unknown-currency degrade.
# v10 — 2026-07-06: FINANCIALS TTM now sizes its aggregation window to the filing
# cadence. FMP returns 6-month rows on `period=quarter` for SEMI-ANNUAL filers (UL
# and many UK/EU/AU issuers), which the old sum-of-4 double-counted to 24 months
# (UL TTM revenue ~127B vs a ~50B fiscal year; every TTM flow + EV/EBITDA·P/E built
# on it ~2×). Old canonical snapshots for those issuers carry the doubled TTM; the
# canonical slot is read before the raw slot with a 24h TTL, so without this bump a
# fresh-but-pre-fix snapshot keeps serving the 2× figure until expiry. Pairs with
# the FINANCIALS raw-slot bump (cache._RAW_SLOT_VERSION) so the rebuild refetches
# and re-aggregates on the cadence-aware window rather than re-normalizing the
# stale doubled raw row. Quarterly issuers are byte-identical (window stays 4).
CANONICAL_CONTRACT_VERSION = 10

# Degradation markers carried in ``Provenance.degraded``. Surfaced to the UI so
# a fallback is visible rather than silent.
# (Retired 2026-06-10: "ccy_inferred" — written only by the country→currency
# rewrite; survives in pre-v5 snapshots and old artifacts as an inert string.)
DEGRADED_CLOSE_ONLY = "close_only"  # no intraday OHLC; 52w high/low fall back to close
DEGRADED_TTM_LAG = "ttm_lag"  # TTM denominator trails the latest reported quarter
# provider gave no real-time current_price; using the latest bar's close as a
# stand-in. Lets the UI avoid claiming a stale close is a live "实时" quote.
DEGRADED_PRICE_FALLBACK_CLOSE = "price_fallback_close"
# provider gave no quote timestamp, so ``as_of`` was inferred from the last bar's
# session close instead of the authoritative trade instant — age is accurate to
# the session, not the minute. Distinct from a missing PRICE: the number is real,
# only its observation time is approximate.
DEGRADED_QUOTE_TS_MISSING = "quote_ts_missing"
# Provider returned a usable PRICE but did not identify the quote currency. This
# is not safe to default to USD: a foreign local listing would bypass FX and feed
# native prices into USD comparisons. Downstream FX gates see UNKNOWN and abstain.
DEGRADED_QUOTE_CURRENCY_MISSING = "quote_currency_missing"
# The live provider served a quote WITHOUT history bars (Finnhub free tier:
# /quote works, /stock/candle is premium-403) and the layer grafted the bars
# from the last cached PRICE row instead of letting the chart go blank.
# current_price is live; bars / 52w range / session change are as-of the stale
# row. Stale-but-complete beats fresh-but-empty, but it must be FLAGGED.
DEGRADED_PRICE_HISTORY_STALE = "price_history_stale"
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
# A foreign ADR (reporting_currency≠quote_currency) had its reporting-currency
# line items FX-converted to the quote currency at the canonical gate, so the
# snapshot is single-currency and EV/multiples are well-defined (class A fix).
DEGRADED_FX_NORMALIZED = "fx_normalized"
# FX rate fetch failed for a reporting≠quote snapshot, so it ships un-converted
# (mixed currency). The FinancialData model invariant withholds EV-based ratios
# (None + warning) rather than emit a cross-currency value — surfaced so the UI
# shows "无法换算" instead of a silently wrong/negative multiple.
DEGRADED_FX_UNAVAILABLE = "fx_unavailable"


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
    """One OHLCV bar. ``open/high/low`` are None for close-only feeds.

    构造期不变量 (机械闸门, T4#5 二次复发升级 2026-06-11): a bar without a
    finite close is not a bar. yfinance hands all-NaN OHLC session rows; NaN
    slips every ``is None`` gate, serializes to close:null, and crashes chart
    consumers. Producers must FILTER such rows out before constructing —
    a non-finite ``close`` here raises (报错 > 编数字); non-finite optional
    fields coerce to None (close-only bar stays legitimate).
    """

    model_config = ConfigDict(frozen=False)

    date: date
    close: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None

    @field_validator("close")
    @classmethod
    def _close_must_be_finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("PriceBar.close must be finite — drop the bar, never fabricate")
        return v

    @field_validator("open", "high", "low", "volume")
    @classmethod
    def _optional_non_finite_to_none(cls, v: float | None) -> float | None:
        return v if v is None or math.isfinite(v) else None

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
    quote_currency: str = "UNKNOWN"
    bars: list[PriceBar] = Field(default_factory=list)
    current_price: float
    is_ohlc_complete: bool = True
    exchange: str | None = None
    # Provider's raw per-exchange session phase (yfinance ``marketState``:
    # REGULAR / PRE / PREPRE / POST / POSTPOST / CLOSED), or None when the source
    # has no such field (FMP /quote). Carried — not pre-classified — so the
    # time-varying SessionState is computed fresh at read time by every consumer
    # via ``compute_session_state(market_state=…)``. Old cached canonical entries
    # (written before this field) read back as None → clock-window fallback.
    market_state: str | None = None
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

    def to_prompt_summary(self, recent_bars: int = 5) -> dict[str, Any]:
        """Compact PRICE view for an LLM prompt: derived metrics + the MOST RECENT
        bars only (the tail), not the full 52-week ASCENDING series.

        The LLM computes nothing from raw bars — every market metric here is
        deterministic — and dumping the whole ascending series led the data agent
        to narrate the OLDEST bars (``bars[0]`` ≈ one year ago) as "Recent Price
        History" (the 2026-06-09 TSLA report showed a June-2025 window). The most
        recent bars are the TAIL, so the summary surfaces those, correctly labeled.
        """
        change, change_pct = self.latest_session_change()
        recent = self.bars[-recent_bars:] if self.bars else []
        return {
            "ticker": self.ticker,
            "quote_currency": self.quote_currency,
            "current_price": self.current_price,
            "as_of": self.provenance.as_of.isoformat(),
            "fifty_two_week_high": self.fifty_two_week_high(),
            "fifty_two_week_low": self.fifty_two_week_low(),
            "trailing_1y_return_pct": self.trailing_1y_return_pct(),
            "latest_session_change": change,
            "latest_session_change_pct": change_pct,
            "most_recent_bars": [b.model_dump(mode="json") for b in recent],
            "warnings": self.warnings,
        }


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
    # FMP /profile isAdr structural flag (True = confirmed ADR). Lets the family-1
    # foreign_issuer_usd_tags acceptor suppress its USD/USD review banner for a
    # confirmed ADR. None on the yfinance path (.info has no isAdr) = "unknown",
    # which keeps the banner. Optional → read-compatible with cached canonical
    # payloads (BUG-038 precedent), so no schema-version bump.
    is_adr: bool | None = None
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


def financials_with_display_price(
    fin: NormalizedFinancials, price: NormalizedPrice
) -> NormalizedFinancials:
    """Overlay the dedicated PRICE canonical's live basis onto a FINANCIALS
    snapshot's own price-derived fields (``current_price`` / ``market_cap`` /
    ``pe_ratio``).

    The FINANCIALS canonical bundles a price / market_cap / P-E captured at the
    FINANCIALS fetch, which lags the dedicated (fresher) PRICE canonical. The
    structured producer (``extract_financial_data``) already reconciles this — it
    marks the market block to the live PRICE basis — but any surface that renders
    the RAW FINANCIALS snapshot (the LLM data-collection prompt) would otherwise
    show the stale price and narrate it into the artifact's ``summary_text``, a
    SECOND as-of inside one artifact (AAPL 2026-07-02: summary $287.98 vs headline
    $294.38). Scale market_cap / P-E by the same price move so all three stay
    mutually consistent (market_cap = shares × live price — exactly what
    ``extract_financial_data`` marks to, since the provider's reported cap =
    shares × its own price). No-op when either price is missing / ≤ 0 (nothing to
    mark to). Both prices are quote-currency, so the ratio is unitless and safe
    for ADRs.
    """
    live = price.current_price
    stale = fin.current_price
    if not live or live <= 0 or not stale or stale <= 0:
        return fin
    ratio = live / stale
    return fin.model_copy(
        update={
            "current_price": live,
            "market_cap": fin.market_cap * ratio if fin.market_cap is not None else None,
            "pe_ratio": fin.pe_ratio * ratio if fin.pe_ratio is not None else None,
        }
    )


class NormalizedForwardEstimates(BaseModel):
    """Canonical analyst-consensus estimates — a typed ENVELOPE, not a parse.

    ``rows`` stays the raw FMP /analyst-estimates row list on purpose: spec
    §6.4.1 makes ``compute.operators.forward_estimates`` the only module allowed
    to interpret a forward row (FY1 selection, growth derivation), so this
    contract must not re-derive anything. What the canonical gate buys here is
    transport-level: one versioned cache slot, a single-flight per ticker,
    provenance stamping, and a shared failure semantic (ProviderError raised to
    every caller) — so the five DCF-seed entries can never transiently diverge
    on whether consensus exists for a ticker.

    ``as_of`` mirrors ``fetched_at``: FMP serves the CURRENT consensus and the
    payload carries no publication instant, so fetch time is the honest semantic
    timestamp (the rows' fiscal-year dates are forecast targets, not data ages).
    """

    model_config = ConfigDict(frozen=False)

    ticker: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
    provenance: Provenance
    warnings: list[str] = Field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        """The ``{"rows": [...]}`` shape the red-line leaf consumes
        (``get_forward_financials`` / ``get_forward_revenue_growth``)."""
        return {"rows": self.rows}
