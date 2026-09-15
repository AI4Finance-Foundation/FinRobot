import math
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from datetime import date, datetime


# ---------------------------------------------------------------------------
# FinancialData sub-models (S1 refactor)
# ---------------------------------------------------------------------------


class IncomeStatement(BaseModel):
    """Income statement metrics."""

    revenue: float = Field(description="Annual revenue in USD")
    # None ≠ 0: a missing figure stays None so downstream withholds the derived
    # metric (data unavailable) instead of treating a fabricated 0 as a real
    # value — 0 EBITDA / 0 margin is a going-concern signal, not "not reported".
    ebitda: float | None = Field(default=None, description="EBITDA in USD; None when unavailable")
    net_income: float | None = Field(
        default=None, description="Net income in USD; None when unavailable"
    )
    # Gross margin can be negative: a loss-maker selling below cost (RIVN-class EV
    # makers) reports gross_margin < 0. The old `ge=0` was an asymmetric guard —
    # its sibling operating_margin already allowed negatives (ge=-5) — and 500'd
    # /financials for Rivian. gross_margin ≥ operating_margin always (opex ≥ 0), so
    # the same -5 floor is provably crash-free while still catching a percentage/
    # decimal mixup (e.g. -50 meaning -50%).
    #
    # Upper bound is a small-epsilon cushion, NOT a hard 100% throw: a margin > 100%
    # implies negative cost and is a SOFT rule (invariant-suite #5 — the sole
    # legitimate breach, a supplier-rebate contra-cost, is a flag, never a crash). The
    # real legitimacy exit is extractor._sanitize_margin, which WITHHOLDS (→ None) any
    # >100% figure so a broken provider value (FMP's UL grossProfit ≥ revenue, GM
    # 100.14% vs a real ~47%) shows N/A instead of crashing the whole report. le=1.02
    # keeps this schema from hard-failing on residual rounding noise from any future
    # un-sanitized constructor while still asserting against a gross percent/decimal mixup.
    gross_margin: float | None = Field(
        default=None, ge=-5, le=1.02, description="Gross margin as decimal; None when unavailable"
    )
    operating_margin: float | None = Field(
        default=None,
        ge=-5,
        le=1.02,
        description="Operating margin as decimal; None when unavailable",
    )
    # Absolute operating income (EBIT) in USD. Carried alongside the margin so the
    # comps target can hand calculate_core_pe a period-consistent EBIT instead of
    # operating_margin × a possibly XBRL-overridden revenue (BUG-017).
    operating_income: float | None = None
    depreciation_amortization: float | None = None
    # Capital expenditure in USD, positive magnitude (outflow). Caliber matches the
    # snapshot's period_basis — TTM sum-of-4-quarters cash-flow-statement capex when
    # the canonical fetch built a TTM snapshot (FMP's default single-snapshot path,
    # or yfinance's operatingCashflow−freeCashflow derivation), latest-fiscal-year on
    # the annual multi-year history path. Projected from NormalizedFinancials.
    # capital_expenditure (already part of the canonical contract since v2 — this is
    # only a new downstream projection field, not a canonical-cache schema change, so
    # no cache version bump). None ≠ 0: a provider that omits the cash-flow statement
    # stays None so dcf_current_actuals withholds/falls back rather than fabricating
    # a $0 capex. Optional → read-compatible with pre-existing serialized artifacts
    # (ttm_quarter_ends / is_adr precedent), so no schema migration needed.
    capital_expenditure: float | None = None
    rd_expense: float | None = None
    sga_expense: float | None = None
    interest_expense: float | None = None
    income_tax_expense: float | None = None
    """Income tax provision in USD. Carried from NormalizedFinancials so the DCF
    seed can derive a company-specific effective tax rate
    (tax / (net_income + tax)) instead of falling back to the Damodaran industry
    aggregate — which for distorted sectors (Software (Internet) = 40%, skewed by
    loss-makers) badly misstates a profitable mega-cap's real ~16-21% rate."""


class BalanceSheet(BaseModel):
    """Balance sheet metrics."""

    # None ≠ 0: a missing component is "not reported", not "the company has zero
    # debt/cash". Defaulting to 0 silently fabricated EV = market_cap + 0 − 0 =
    # market_cap, passing every downstream sanity gate while the net-debt bridge
    # was actually unknown. Consumers (dcf_seed/lbo_seed/fx_normalize) coerce to 0
    # only at the point of use and disclose it in provenance.
    total_debt: float | None = Field(
        default=None, description="Total debt in USD; None = not reported (≠ 0)"
    )
    total_cash: float | None = Field(
        default=None, description="Total cash in USD; None = not reported (≠ 0)"
    )
    # EV bridge completeness (numeric-audit family 3): preferred + minority interest
    # belong in EV; calculate_ev folds them in when reported. Carried here so the
    # extractor can pass them, and audit.ev_bridge can flag an UNREPORTED (None) one
    # whose assumed-0 would understate EV invisibly to the market_cap+debt−cash
    # identity (it still "balances"). None = not reported (≠ 0). Reporting-ccy (FX-scaled).
    preferred_stock: float | None = Field(
        default=None, description="Preferred equity in reporting ccy; None = not reported"
    )
    noncontrolling_interest: float | None = Field(
        default=None, description="Minority/NCI in reporting ccy; None = not reported"
    )


class MarketData(BaseModel):
    """Market and price data."""

    market_cap: float = Field(description="Market cap in USD")
    shares_outstanding: float = Field(gt=0)
    current_price: float = Field(gt=0)
    pe_ratio: float | None = None
    price_52w_high: float | None = None
    price_52w_low: float | None = None
    # Trailing-52-week PRICE return (NOT total return — dividends excluded), in
    # PERCENT units (e.g. -20.5 means -20.5%). Mirrors
    # ``NormalizedPrice.trailing_1y_return_pct()`` verbatim — same bars, same
    # earliest-close-to-latest-close convention — so it agrees with the
    # price_52w_high/low above (all three derive from the SAME canonical PRICE
    # snapshot). A pure ratio: untouched by fx_normalize's USD conversion (the
    # quote-currency scaling cancels out of a percentage change), so this field
    # reads identically whether ``financial_data`` is the native-quote extractor
    # output or the USD-normalized copy every later pipeline step consumes. None
    # when the price series has fewer than 2 bars (insufficient history).
    trailing_1y_return_pct: float | None = None
    # Industry / sector strings as reported by the data provider. Used by
    # dcf_seed to look up Damodaran industry medians when ticker-level data
    # is missing. None when provider didn't expose it.
    industry: str | None = None
    sector: str | None = None
    # Issuer country as reported by the provider — FMP /profile gives ISO-2
    # ("US"/"TW"), yfinance .info gives full names ("United States"/"Taiwan").
    # Consumed by the family-1 foreign_issuer_usd_tags acceptor; None = unknown.
    country: str | None = None
    # FMP /profile isAdr structural flag (True = confirmed ADR). The family-1
    # foreign_issuer_usd_tags acceptor suppresses its USD/USD review banner when
    # this is True (confirmed ADRs file in USD legitimately). None (yfinance path
    # / unknown) or False keeps the banner — a True is required to suppress.
    is_adr: bool | None = None
    # Raw provider-reported 5y beta — stored UNCONSTRAINED on purpose. This is the
    # raw-value layer (no financial judgement here, per the engine contract: raw
    # values stay traceable, sanity rulings happen in compute). Vendors emit short-
    # window glitches outside any economically possible band (SHEL −0.248, BP
    # −0.239, EQNR −0.752 — a whole sector compressed by a common upstream feed;
    # negative beta is impossible for a cyclical oil major), and clamping/rejecting
    # at the schema would crash the entire extraction for that ticker (refuse-to-
    # conclude). The WACC layer (_pick_with_provenance in dcf_seed/ddm_seed) is the
    # single point that judges the band [0, 5] and routes anything outside it to the
    # Damodaran industry levered beta proxy with disclosed provenance.
    beta: float | None = None


class ValuationMetrics(BaseModel):
    """Derived valuation multiples. Computed by code, not LLM."""

    model_config = ConfigDict(frozen=False)

    enterprise_value: float | None = None
    # EBITDA carried in two calibers (engine.compute.multiples):
    #   ebitda_operating = EBIT + D&A          → ev_ebitda          (PRIMARY)
    #   ebitda_reported  = NI+tax+interest+D&A → ev_ebitda_reported (street x-check)
    # ev_ebitda uses the operating caliber because EV already nets out cash;
    # the *_reported pair mirrors retail aggregators (which credit non-operating
    # income) so the UI can footnote the gap instead of looking "wrong".
    ebitda_operating: float | None = None
    ebitda_reported: float | None = None
    ev_ebitda: float | None = None
    ev_ebitda_reported: float | None = None
    ev_revenue: float | None = None
    # Book value per share (reporting currency) carried from the provider. Feeds the
    # cyclical comps P/B method (build_xbrl_aligned_company computes the target's
    # pb_ratio + the per-share book the peer median P/B is applied to). None when
    # the provider omits it.
    book_value_per_share: float | None = None


class DataProvenance(BaseModel):
    """Source + freshness + degradation flags for a snapshot's numbers.

    Surfaced to the UI (SourcedNumber popovers, degraded badges, "TTM 截至 X"
    label) so provenance is visible instead of hardcoded/assumed (ADR-0004).
    """

    model_config = ConfigDict(frozen=False)

    provider: str
    as_of: date | None = None  # financials period end — the data's semantic time
    period_basis: str = "ttm"
    pe_ttm_lag_quarters: int | None = None
    degraded: list[str] = Field(default_factory=list)  # close_only / ttm_lag / …


class FinancialData(BaseModel):
    """Structured financial data for a single company.

    Access fields via sub-models:
        fd.income.revenue, fd.balance.total_debt, fd.market.market_cap, etc.
    """

    model_config = ConfigDict(frozen=False)

    ticker: str
    company_name: str = ""
    timestamp: datetime  # when this data was fetched — not the fiscal period end

    # Fiscal period this snapshot represents. Set by extract_financial_data when
    # the provider supplies `fiscal_year` or `date` (historical fetches do, the
    # single-year TTM fetch doesn't). Downstream consumers (extract_historical_
    # metrics, chart year labels) prefer this over `timestamp.year` so a
    # five-year history doesn't collapse to today's year five times.
    fiscal_period_end: date | None = None

    # Quarter-end dates of the quarters summed into a TTM snapshot (FMP builds TTM
    # = Σ latest 4 quarters). Carried so the numeric-audit family-4 verifier can
    # assert the four quarters don't overlap/gap/duplicate — a silently wrong TTM
    # corrupts every ratio (P/E, EV/EBITDA, margins) and the DCF growth it feeds.
    # Empty on the yfinance / annual paths (no per-quarter rows) — the verifier
    # then has nothing to audit and abstains. Optional → read-compatible with
    # cached canonical payloads (BUG-038 precedent), so no schema-version bump.
    ttm_quarter_ends: list[date] = Field(default_factory=list)

    income: IncomeStatement
    balance: BalanceSheet = Field(default_factory=BalanceSheet)
    market: MarketData
    valuation: ValuationMetrics = Field(default_factory=ValuationMetrics)

    # Currency tags carried from NormalizedFinancials (same meaning as on
    # CompanyFinancials): reporting_currency = IS/BS line items, quote_currency =
    # market_cap/price. They DISAGREE for foreign-listed ADRs (TSM: TWD / USD).
    # build_xbrl_aligned_company reads these to FX-normalize a foreign target to
    # canonical USD before comps multiples, symmetric with the peer path (BUG-018).
    reporting_currency: str = "USD"
    quote_currency: str = "USD"

    data_source: str = "yfinance"
    provenance: DataProvenance | None = None
    warnings: list[str] = Field(default_factory=list)
    field_warnings: dict[str, list[str]] = Field(default_factory=dict)
    """Structured, per-field warning *codes* (not prose) — keyed by the field a
    caveat belongs to (``ev_ebitda`` / ``pe`` / …), each a stable code the UI
    maps to a localized caveat next to that specific number. The free-text
    :attr:`warnings` stays the row-level catch-all; this is what lets a caveat
    sit on the exact cell it concerns instead of a generic row marker."""

    @model_validator(mode="after")
    def _withhold_cross_currency_ratios(self) -> "FinancialData":
        """Structural invariant: a cross-currency EV/multiple cannot exist.

        When ``reporting_currency != quote_currency`` (a foreign ADR whose FX
        normalization was skipped or failed — see the DataLayer canonical FX
        gate) every EV-based ratio mixes a quote-currency ``market_cap`` with
        reporting-currency net debt, so it is meaningless (the -75B TSM EV, probe
        2026-06-09). Rather than trust each consumer to remember the currency
        check, withhold the affected fields HERE at construction: a mixed-currency
        ``enterprise_value`` / ``ev_ebitda`` / ``ev_revenue`` / ``pe_ratio`` can
        never reach the /financials route, Coverage table or AI orchestrator. The
        mismatch then reads honestly as "withheld" instead of a wrong/negative
        number. Single-currency snapshots (the common case once the canonical FX
        gate has run) hit the early return and are untouched.
        """
        if self.reporting_currency.upper() == self.quote_currency.upper():
            return self
        withheld = False
        for attr in ("enterprise_value", "ev_ebitda", "ev_ebitda_reported", "ev_revenue"):
            if getattr(self.valuation, attr) is not None:
                setattr(self.valuation, attr, None)
                withheld = True
        # pe = market_cap[quote ccy] / net_income[reporting ccy] is mixed too.
        if self.market.pe_ratio is not None:
            self.market.pe_ratio = None
            withheld = True
        if withheld:
            codes = self.field_warnings.setdefault("ev_ebitda", [])
            if FIELD_WARN_EV_CROSS_CURRENCY not in codes:
                codes.append(FIELD_WARN_EV_CROSS_CURRENCY)
            warning = (
                f"{self.ticker}: reporting currency {self.reporting_currency} ≠ quote "
                f"currency {self.quote_currency} and FX normalization was unavailable — "
                "EV, EV/EBITDA, EV/Revenue and P/E withheld (a cross-currency ratio is "
                "meaningless)."
            )
            if warning not in self.warnings:
                self.warnings.append(warning)
        return self


# ── Structured field-warning codes (attach at the generation site, where the
# affected field is known; consumers map code → localized caveat) ────────────
FIELD_WARN_EV_MISSING_NET_DEBT = "ev_missing_net_debt"
"""EV (hence EV/EBITDA, EV/Revenue) uncomputable — provider lacked debt/cash."""
FIELD_WARN_SHARES_DERIVED = "shares_derived"
"""shares_outstanding derived as market_cap/price — per-share (EPS, P/E) approximate."""
FIELD_WARN_EV_CROSS_CURRENCY = "ev_cross_currency"
"""EV / EV-multiples / P/E withheld — reporting≠quote currency and FX unavailable,
so a quote-ccy market_cap and reporting-ccy net debt can't form a valid ratio."""


class PriceHistory(BaseModel):
    """Structured price history."""

    ticker: str
    period: str
    data_points: int
    current_price: float
    high_52w: float
    low_52w: float
    avg_price: float


class CompanyFinancials(BaseModel):
    """Financial data for one company in a peer set.

    Two currency tags because yfinance carries them separately and they
    DISAGREE for foreign-listed ADRs:

    - ``reporting_currency`` (ISO 4217): currency of the income-statement
      and balance-sheet line items — ``revenue, ebitda, net_income,
      total_debt, total_cash``.
    - ``quote_currency`` (ISO 4217): currency of the market quote —
      ``market_cap`` (and any price-derived field).

    For US issuers both are USD. For TSM ADR they are TWD and USD
    respectively — that mismatch collapses EV/EBITDA to 0.158x without
    normalization. See ``finrobot.engine.compute.operators.fx_normalize`` for the
    canonical-USD pipeline applied before EV/EBITDA is computed.
    """

    model_config = ConfigDict(frozen=False)

    ticker: str
    name: str | None = None
    revenue: float
    # None ≠ 0: a provider that omits these must not be treated as zero EBITDA /
    # earnings / margin — that fabrication poisoned the peer median and the NOPAT
    # core P/E. Downstream multiples withhold the affected ratio when None.
    ebitda: float | None = None
    net_income: float | None = None
    # Forward consensus (FY1) — populated per-peer from DataType.FORWARD_ESTIMATES
    # via the red-line leaf compute.operators.forward_estimates.get_forward_financials,
    # which selects the nearest fiscal-year-end ≥ today (NOT rows[0]). forward_eps
    # is analyst-consensus EPS (already core/normalized — analysts strip one-offs),
    # so forward_pe = market_cap / (forward_eps × shares) feeds a forward_comps
    # method that is intentionally SEPARATE from the trailing NOPAT core_pe (one
    # forward caliber on both target and peers). None when no consensus is available
    # → that peer falls back to trailing for the comps median.
    forward_eps: float | None = None
    forward_pe: float | None = None
    market_cap: float
    # None ≠ 0: None means the provider did not report the figure, so EV (and
    # the EV-based multiples) MUST be withheld rather than computed against an
    # assumed-zero net-debt — that fabrication silently poisoned the peer median
    # (a cash-rich peer reported as debt=cash=0 → EV=market_cap). Mirrors the
    # target path in extract_financial_data, which already refuses EV when debt
    # or cash is missing.
    total_debt: float | None = None
    total_cash: float | None = None
    # EV-bridge completeness for peers (mirrors target FinancialData.balance):
    # calculate_ev folds preferred + NCI into a peer's EV when reported, so a peer
    # carrying them does not feed an understated EV/EBITDA into the comps median.
    # None ≠ 0 (not carried). Reporting-currency (FX-scaled with the other balance lines).
    preferred_stock: float | None = None
    noncontrolling_interest: float | None = None
    enterprise_value: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    # Absolute operating income (EBIT) in the reporting currency. calculate_core_pe
    # builds NOPAT from this directly instead of operating_margin × revenue, so a
    # revenue that was XBRL-TTM-reconciled (override_company_with_xbrl) can't drag
    # EBIT to a cross-period margin×revenue product (BUG-017). FX-normalized with
    # the other reporting-currency line items. None → fall back to margin×revenue.
    operating_income: float | None = None
    pe_ratio: float | None = None
    ev_ebitda: float | None = None
    ev_revenue: float | None = None
    # Book value PER SHARE (reporting currency) and price-to-book = market_cap /
    # (book_value_per_share × shares). P/B is the standard cyclical-comps multiple:
    # book equity doesn't whipsaw with the cycle the way trough EPS (negative) or
    # peak EPS (inflated) do, so a memory/storage peer median P/B prices the target
    # without the成长股 forward-P/E × cycle-peak-EPS artifact ($2199 for MU). None
    # when the provider omits book value per share, or shares are unavailable.
    book_value_per_share: float | None = None
    pb_ratio: float | None = None
    # Income tax provision in USD, carried from the provider so calculate_core_pe
    # can derive a company-specific effective rate (tax / (net_income + tax)) for
    # the NOPAT core-earnings caliber. None when the provider omits it.
    income_tax_expense: float | None = None
    # NOPAT-based core-earnings fields, filled by calculate_core_pe (a set-level
    # pass — the degenerate-tax fallback needs the whole peer set). They give P/E
    # comps a consistent earnings caliber: as-reported net income mixes in
    # non-operating items that differ across the set (NVDA's TTM investment gains,
    # AMD/AVGO near-zero effective tax), making raw P/E apples-to-oranges.
    effective_tax_rate: float | None = None
    core_net_income: float | None = None  # NOPAT = EBIT × (1 − effective_tax_rate)
    core_pe_ratio: float | None = None  # market_cap / NOPAT, gated by P/E sanity bounds
    reporting_currency: str = "USD"
    quote_currency: str = "USD"
    # [待核] note set when SEC XBRL TTM diverged materially from the FMP TTM base
    # and we kept FMP rather than overriding (ADR-0008). None when the two agree
    # or no XBRL was available. Rolled up into PeerComps.warnings for display.
    ttm_divergence_note: str | None = None
    # Multiples that had computable inputs but fell outside the published sanity
    # bounds and were nulled by calculate_multiples (so excluded from medians).
    # Recorded so a thinned peer set is never silent — this is the *real* signal
    # that replaced the tautological range check in validate_peer_comps, which
    # could never fire because the floor had already nulled out-of-range values.
    sanity_drops: list[str] = Field(default_factory=list)


class PeerComps(BaseModel):
    """Comparable company analysis result."""

    model_config = ConfigDict(frozen=False)

    target: CompanyFinancials
    peers: list[CompanyFinancials] = Field(min_length=1)

    # Computed by code
    median_ev_ebitda: float | None = None
    median_pe: float | None = None
    median_ev_revenue: float | None = None
    mean_ev_ebitda: float | None = None
    mean_pe: float | None = None
    # Peer median of the NOPAT-based core P/E (calculate_core_pe). The comps_pe
    # valuation method pairs this with the target's core EPS so numerator and
    # denominator share one earnings caliber.
    median_core_pe: float | None = None
    # Peer median of forward P/E (market_cap / FY1 consensus net income, set per
    # peer in _fetch_one_peer). Sparser than trailing — only US issuers with
    # analyst consensus contribute. Feeds the forward_comps valuation method,
    # which pairs it with the target's forward EPS (one forward caliber both sides).
    median_forward_pe: float | None = None
    # How many peers actually fed each median after NM/sanity exclusions — a
    # "median" of one survivor is a single peer's multiple wearing a median's
    # authority (TSLA 2026-06-10: TM carried no forward P/E, so the published
    # "peer median forward P/E 5.8x" was GM alone). The comps_pe method refuses
    # a median below its sample floor instead of pricing a target off it.
    pe_sample_n: int = 0
    core_pe_sample_n: int = 0
    forward_pe_sample_n: int = 0
    # Peer median price-to-book and its sample count. The PRIMARY cyclical comps
    # multiple (book equity is cycle-stable, unlike trough/peak EPS). Same NM/
    # sanity gating and sample-count discipline as median_pe — a "median" of <3
    # survivors is refused by _comps_median_refusal rather than pricing a target
    # off one peer's P/B.
    median_pb: float | None = None
    pb_sample_n: int = 0

    # Through-cycle ROE (mean of annual eps / book_value_per_share) for the target and
    # the peer-median. Set ONLY for the insurer cohort (is_balance_sheet_financial and
    # not is_bank), where a flat peer-median P/B grants no quality premium and mis-
    # prices a high-ROE insurer (PGR comps $115 vs price $216) — comps_pb scales the
    # median P/B by target_tcROE / peer_median_tcROE. None (both) → no ROE adjustment,
    # comps_pb keeps the flat median (banks / non-financials byte-identical).
    target_through_cycle_roe: float | None = None
    peer_median_through_cycle_roe: float | None = None

    # LLM-provided
    peer_justification: str = ""
    positioning_narrative: str = ""

    # Data-quality warnings produced by calculate_peer_statistics / validators
    warnings: list[str] = Field(default_factory=list)


class PeerSelection(BaseModel):
    """LLM structured output for peer selection step."""

    tickers: list[str] = Field(
        min_length=3,
        max_length=10,
        description="Peer ticker symbols. Exactly 3-10 publicly traded companies.",
    )
    rationale: str = Field(description="One sentence: why these peers were selected.")


class DCFInputs(BaseModel):
    """Inputs for DCF calculation. Built by ``seed_dcf_inputs`` from real
    filings (3y historical medians) + Damodaran industry fallback. The LLM
    never selects these numbers — it only interprets them in the output_gen
    narrative step.

    FCF formula (standard, always used):
        FCF = EBIT(1-tax) + D&A - CapEx - ΔNWC
            = (EBITDA - D&A)(1-tax) + D&A - revenue*capex_pct - revenue*nwc_pct

    ``da_pct_revenue`` carries the D&A tax shield and is always populated by
    seed_dcf_inputs.
    """

    revenue_base: float = Field(
        description=(
            "Base-year revenue in USD (the current run-rate — TTM by default). Year 1 "
            "is projected off it. The consensus seed restates Year-1 growth to NTM "
            "caliber (growth from this TTM base to the FY1 estimate) so the FY-over-FY "
            "consensus rate does not double-count the current fiscal year's realized stub."
        )
    )
    revenue_growth_rates: list[float] = Field(
        min_length=1, description="Projected annual growth rates as decimals"
    )
    ebitda_margin: float = Field(ge=0, le=1, description="Projected EBITDA margin")
    capex_pct_revenue: float = Field(ge=0, le=1, description="Capex as % of revenue")
    nwc_pct_revenue: float = Field(
        ge=-0.2, le=0.5, description="Net working capital change as % of revenue"
    )
    terminal_nwc_pct_revenue: float | None = Field(
        default=None,
        ge=-0.10,
        le=0.10,
        description=(
            "Steady-state ΔNWC as % of revenue for the Gordon perpetuity, seeded "
            "as marginal NWC ratio median(ΔNWC/Δrevenue) × terminal growth. The "
            "explicit-window nwc_pct_revenue embeds the historical growth rate, "
            "so holding it into a low-growth perpetuity overstates the drag (or "
            "the subsidy) several-fold. None = fall back to nwc_pct_revenue "
            "(inputs built without multi-year history, e.g. direct REST payloads)."
        ),
    )
    da_pct_revenue: float = Field(
        default=0.0,
        ge=0,
        le=0.5,
        description=(
            "D&A as % of revenue, carrying the tax shield in the FCF formula. "
            "Default 0.0 means no shield; seed_dcf_inputs always sets a non-zero "
            "value from 3y filings or Damodaran fallback. Direct callers may omit it."
        ),
    )
    tax_rate: float = Field(ge=0, le=1, default=0.21)

    # WACC inputs
    risk_free_rate: float = Field(ge=0, le=0.15)
    beta: float = Field(ge=0, le=5)
    equity_risk_premium: float = Field(ge=0, le=0.15)
    cost_of_debt: float = Field(ge=0, le=0.20)
    debt_ratio: float = Field(ge=0, le=1, description="Debt / (Debt + Equity)")

    # Terminal value
    terminal_growth_rate: float = Field(ge=0, le=0.05, description="Long-term growth rate")

    shares_outstanding: float = Field(gt=0)
    net_debt: float = Field(description="Total debt - cash. Negative if net cash.")

    # Finiteness gate for the three fields without ge/le bounds (bounded
    # fields reject NaN for free — NaN fails every comparison). A NaN in
    # revenue_base / net_debt / any growth rate sails through calculate_dcf's
    # guards (NaN comparisons are all False) and ships implied_price=NaN into
    # the aggregation band; JSON bodies accept the NaN literal, so the
    # POST /monte-carlo direct-construction path is live, not theoretical.
    @field_validator("revenue_base", "net_debt")
    @classmethod
    def _reject_non_finite_scalar(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("must be finite — NaN/Inf is not a number, it's missing data")
        return v

    @field_validator("revenue_growth_rates")
    @classmethod
    def _reject_non_finite_growth(cls, v: list[float]) -> list[float]:
        for i, g in enumerate(v):
            if not math.isfinite(g):
                raise ValueError(
                    f"revenue_growth_rates[{i}] must be finite — "
                    "NaN/Inf is not a number, it's missing data"
                )
        return v

    currency: str = Field(
        default="USD",
        description=(
            "ISO 4217 quote currency of the per-share / equity outputs "
            "(``implied_price`` is ``equity_value / shares_outstanding``, a market "
            "quote, so it follows ``FinancialData.quote_currency`` — TWD for TSM, "
            "EUR for SAP). Threaded by ``seed_dcf_inputs`` from the financials "
            "snapshot; ``calculate_dcf`` passes it through to ``DCFResult`` so the "
            "artifact carries a real currency tag and the diff formatter never "
            "has to assume USD. Defaults to USD so direct callers and "
            "JSON-round-tripped legacy artifacts (no ``currency`` key) still "
            "validate — same read-compat precedent as ``ttm_quarter_ends``."
        ),
    )

    assumption_provenance: dict[str, str] = Field(
        default_factory=dict,
        description="Maps assumption field names to their reasoning/source",
    )

    nwc_clamped: bool = Field(
        default=False,
        description=(
            "True when the explicit-window ΔNWC/revenue median sat outside the "
            "±10% modelling band and was clamped to it. A structured signal — "
            "independent of the nwc_pct_revenue provenance STRING — that drives the "
            "⚠ on the report's model-vs-current reconciliation ΔNWC row. False for "
            "direct/legacy construction (read-compat)."
        ),
    )

    inputs_fetched_at: datetime | None = Field(
        default=None,
        description=(
            "Wall-clock time the market/financial inputs behind this seed were "
            "fetched (= FinancialData.timestamp, the canonical fetch time). "
            "Stamped by seed_dcf_inputs so every surface that prints a DCF/WACC "
            "(REST /dcf-seed, chat Monte-Carlo, artifacts via "
            "DCFResult.inputs) can show 'inputs as of X' — 门四溯源半. None for "
            "direct construction (user-supplied REST bodies have no fetch time; "
            "never fabricate a now()) and for JSON-round-tripped legacy "
            "artifacts (read-compat, ttm_quarter_ends precedent)."
        ),
    )


class MarketImpliedCheck(BaseModel):
    """Reverse-DCF reality check: what the CURRENT market price implies.

    The forward DCF answers "given my assumptions, what is it worth?". This
    inverts it: "given the market's price, what constant growth (or discount
    rate) is the market implicitly pricing in?" — a Damodaran-style sanity
    check. It is the honest companion to a fair-value point: a DCF mid 60% below
    market is meaningless on its own, but "the market is pricing in 23%/yr
    growth — plausible?" is a checkable, user-understandable statement.

    All fields are COMPUTED (deterministic reverse-DCF), never LLM-narrated.
    Scalars only (no baked prose) so the bilingual UI renders the localized
    sentence and the thesis LLM cites the numbers in the report's language.
    """

    horizon_years: int
    """Explicit high-growth window the implied growth is solved over — matches
    the forward DCF's own projection_years so the two are directly comparable."""
    implied_growth: float | None = None
    """Constant annual revenue growth the market price implies over
    ``horizon_years``. None when the price is unreachable within the solver's
    growth bracket — see ``growth_unreachable``."""
    implied_wacc: float | None = None
    """Discount rate the market price implies under the seeded growth schedule.
    None when unreachable within the WACC bracket."""
    growth_unreachable: bool = False
    """True when NO growth in the solver bracket reaches the market price — the
    single most important signal that the price is NOT growth-explainable
    (option-value stock, e.g. TSLA: even 50% growth implies only ~$65 vs $418).
    When True the product must NOT present a fundamentals point target as the
    headline; the honest output is "priced on optionality the DCF cannot model"."""
    growth_ceiling: float | None = None
    """The solver's max growth tried (e.g. 0.50), for the unreachable narrative
    ("even {ceiling:.0%} growth only implies ${ceiling_price})."""
    ceiling_price: float | None = None
    """Implied price at ``growth_ceiling`` — the highest the DCF can reach. Lets
    the UI/narrative quantify how far the market sits beyond any plausible
    growth (TSLA: $65 ceiling vs $418 market)."""


class MarketImpliedNature(BaseModel):
    """Per-name valuation *nature*, re-solved against the LIVE price — the honest
    cross-name read for the Coverage desk.

    A cross-name *ranking* by implied-growth gap was deliberately rejected: the
    reverse solver fits a FLAT constant growth while the forward DCF projects a
    DECAYING schedule, so a single implied-growth scalar sits systematically
    below the decay-base anchor by an amount that scales with the name's growth
    tier — ranking by that gap ranks "whose growth curve is steepest", not
    "whose expectation is most stretched". What *does* survive that critique is a
    per-name **classification**, which is what this carries:

    * ``fundamental`` — the live price IS explainable by some growth in the
      solver bracket. ``implied_growth`` is the constant annual revenue growth
      the price implies, shown as per-name context (NOT a sortable cross-name
      number — see above).
    * ``option_value`` — no growth in the bracket reaches the price AND that
      verdict survives the most favourable plausible WACC (a band lower). The
      market is pricing optionality no cash-flow model can capture (TSLA-type).
      The robust, deterministic *exclusion* signal — and the moat: a generic LLM
      cannot reproduce it.
    * ``near_ceiling`` — unreachable at the name's own WACC, but a plausibly
      lower WACC rescues it into the solvable range. Flagged WACC-sensitive
      rather than asserting optionality, because the verdict would silently flip
      with the discount-rate assumption (and an unsourceable flip is exactly the
      kind of number this product refuses to ship).

    All fields are COMPUTED (deterministic reverse-DCF), never LLM-narrated.
    """

    kind: Literal["fundamental", "option_value", "near_ceiling"]
    implied_growth: float | None = None
    """Constant annual revenue growth the live price implies (``fundamental``
    only; None on the unreachable paths and when the price sits below even the
    bracket floor)."""
    implied_wacc: float | None = None
    """Discount rate the live price implies under the seeded growth schedule —
    surfaced so the growth read isn't mistaken for assumption-free (a high-beta
    name shows higher implied growth partly via its own higher WACC)."""
    horizon_years: int
    """Explicit window the implied growth is solved over (the source DCF's own
    ``projection_years``), so the number is anchored to a stated horizon."""
    growth_ceiling: float | None = None
    """The solver's max growth tried (``option_value``/``near_ceiling`` only) —
    for the narrative "even {ceiling:.0%} growth implies only ${ceiling_price}"."""
    ceiling_price: float | None = None
    """Implied price at ``growth_ceiling`` — how far the live price sits beyond
    any plausible growth. ``option_value``/``near_ceiling`` only."""


class DCFResult(BaseModel):
    """DCF valuation output. All numbers computed by code, not LLM."""

    # WACC
    cost_of_equity: float | None  # None when wacc_override was used
    wacc: float

    # Projections
    projection_years: int
    projected_revenue: list[float]
    projected_ebitda: list[float]
    projected_fcf: list[float]

    # Terminal value
    terminal_value: float
    pv_terminal: float
    # Steady-state perpetuity BASE (capex normalized to the maintenance anchor,
    # ΔNWC to the marginal ratio — see operators/dcf._terminal_fcf). It is NOT
    # projected_fcf[-1]: without disclosing it a reader reconstructing Gordon
    # from the printed FCF path lands ~2x off and reads the gap as an error
    # (KO external audit 2026-07-07). Optional for legacy-artifact read-compat.
    terminal_fcf: float | None = None

    # Valuation
    pv_fcf_total: float
    enterprise_value: float
    equity_value: float
    implied_price: float

    # ISO 4217 quote currency of implied_price / equity_value, threaded from
    # DCFInputs.currency (← FinancialData.quote_currency). Lets the artifact
    # carry a real currency tag so the semantic-diff formatter stamps the right
    # symbol for non-USD issuers instead of assuming "$". Defaults to USD for
    # read-compat with legacy artifacts that predate the field.
    currency: str = "USD"

    # Sensitivity
    sensitivity_table: dict[str, Any] | None = None

    # ±2pp EBITDA-margin swing on the base case (operators.dcf.margin_swing):
    # (implied_price_at_-2pp, implied_price_at_+2pp), low→high. Either end None
    # when that shifted margin degrades (out of [0, 1], Gordon guard, non-positive
    # terminal FCF / equity); the whole field None when neither end is valid or the
    # caller didn't run it. The terminal value capitalizes the steady-state margin
    # (70-80% of EV), so this is the load-bearing sensitivity the WACC×TG grid
    # never surfaces. Absent on legacy artifacts.
    margin_swing: tuple[float | None, float | None] | None = None

    # Current-reality actuals for the four DCF drivers, keyed
    # revenue_growth / ebitda_margin / capex_pct_revenue / nwc_pct_revenue — the
    # "Current" column of the report's model-vs-current reconciliation
    # (operators.dcf_seed.dcf_current_actuals). Calibers are MIXED and disclosed
    # per cell: ebitda_margin is always TTM (income.ebitda/revenue, the freshest
    # 12-month figure); capex_pct_revenue is TTM when the canonical snapshot carries
    # a TTM capex figure (see assumption_current_actuals_capex_ttm — the ONLY driver
    # whose caliber varies per ticker/run) and otherwise falls back to latest fiscal
    # year; revenue_growth / nwc_pct_revenue are always the latest fiscal year (no
    # TTM source for ΔNWC in the canonical snapshot). Per-driver None when the source
    # lacks a usable point (never fabricated); whole field None when not computed
    # (legacy).
    assumption_current_actuals: dict[str, float | None] | None = None

    # Fiscal year of the latest-FY current actuals (ΔNWC / growth, and capex on the
    # fallback path) — lets the report label those cells "FY<year>" beside the
    # TTM-labelled cells. None when history was empty or the caller didn't compute it.
    assumption_current_actuals_fy: int | None = None

    # True when assumption_current_actuals["capex_pct_revenue"] is TTM-caliber
    # (income.capital_expenditure / income.revenue from the canonical snapshot);
    # False when dcf_seed.dcf_current_actuals fell back to the latest-FY ratio (the
    # canonical snapshot's cash-flow statement was thin/unavailable for this ticker
    # even though other TTM fields resolved — margin's TTM source is the income
    # statement, capex's is the cash-flow statement, so the two can diverge); None
    # when assumption_current_actuals itself wasn't computed (legacy). The report's
    # reconciliation table reads this to pick the capex row's caliber tag dynamically
    # ("TTM" vs "FY<year>") instead of a static label — a static tag would mislabel
    # the fallback case (BUG-023 displayed==actual family).
    assumption_current_actuals_capex_ttm: bool | None = None

    # Reverse-DCF reality check (what the market price implies). None when the
    # caller didn't run it (e.g. no current price available).
    market_implied: MarketImpliedCheck | None = None

    # Inputs used (for reproducibility)
    inputs: DCFInputs


class ThesisResult(BaseModel):
    """Investment thesis. LLM provides judgment, code validates structure.

    narrative fields are optional so old artifacts still
    validate after the schema bump; new pipeline runs populate them once
    the LLM cooperates. Together these 6 slots cover the standard 8
    8-agent surface (tagline / company_overview / investment_overview /
    valuation_overview / risks / competitor_analysis / major_takeaways /
    news_summary) — investment_overview maps to recommendation + narrative,
    major_takeaways maps to key_takeaways, risks maps to risks list.
    """

    recommendation: str = Field(description="Buy/Hold/Sell (always directional)")
    price_target: float | None = Field(
        default=None,
        description=(
            "12-month price target. None when the POINT is honestly withheld "
            "(valuation_withheld) — the only number available would be fabricated, "
            "so the system publishes the directional verdict + range instead of "
            "averaging non-corroborating methods into a phantom point. The verdict "
            "is ALWAYS directional regardless (the REVIEW state is deleted)."
        ),
    )
    price_target_basis: str
    catalysts: list[str] = Field(
        min_length=1,
        description=(
            "3-5 UPSIDE drivers ONLY (reasons the stock could rise) — rendered under a "
            "green 'Bull Case' heading. Never place a downside item here: investigations, "
            "lawsuits, antitrust probes, regulatory penalties, margin pressure and "
            "demand/backlash concerns are `risks`, not catalysts. Each entry must either "
            "(a) correspond to a real event from the injected catalyst-analysis "
            "'Key positive catalysts' list (paraphrase, don't invent), or (b) cite a "
            "number from the numeric-discipline whitelist (a valuation method, peer "
            "multiple, or momentum figure) as the driver — never a discrete "
            "forward-looking event (product launch, FDA approval, M&A, contract win) "
            "that was not supplied, and never an unquantified claim with no number "
            "behind it. If no catalyst events were supplied, ground every entry in a "
            "whitelisted number instead of fabricating a substitute event."
        ),
    )
    risks: list[str] = Field(
        min_length=1,
        description=(
            "3-5 DOWNSIDE scenarios ONLY (reasons the stock could fall) — rendered under "
            "a red 'Bear Case' heading. Each entry must cite at least one number from "
            "the numeric-discipline whitelist (a valuation range, peer multiple, "
            "momentum drawdown, market-implied growth, etc.) or reference a specific "
            "negative catalyst from the injected 'Key negative catalysts' list — avoid "
            "unquantified verdict language ('faces headwinds', 'competitive pressure') "
            "with no supporting figure."
        ),
    )
    narrative: str = Field(
        description=(
            "The thesis argument in 2-3 SHORT paragraphs separated by a blank line — "
            "NOT one dense block of text (a wall is unreadable in the report). Plain "
            "prose only: no markdown headers, no ** bold **, no bullet syntax — the "
            "Company Overview / Valuation Overview / Competitor Analysis sections each "
            "have their own dedicated fields, so do not duplicate them as a mini-report "
            "inside the narrative. Every paragraph must cite at least one number from "
            "the prompt's numeric-discipline whitelist — a verdict-only sentence with "
            "no backing figure (e.g. 'attractively valued' or 'a resilient moat' with "
            "no number behind it) is not acceptable analyst prose."
        ),
    )

    # ── narrative LLM narrative slots ───────────────────────────────
    tagline: str | None = Field(
        default=None,
        description=(
            "One-sentence shareable conclusion (≤ 60 characters). "
            "Example: 'NVDA · AI compute super-cycle winner, ~30% upside still on the table'."
        ),
    )
    key_takeaways: list[str] | None = Field(
        default=None,
        description=(
            "3-5 bullet points the analyst reader should walk away with. "
            "Distinct from `catalysts` (future events) and `risks` (downsides) "
            "— these are present-tense conclusions."
        ),
    )
    company_overview: str | None = Field(
        default=None,
        description=(
            "200-300 word Company Overview (8th synthesis slot). "
            "Cover business model, reportable segments with revenue mix, "
            "geographic exposure, and the durable moat. Investment-bank "
            "tone — no retail simplification."
        ),
    )
    valuation_overview: str | None = Field(
        default=None,
        description=(
            "150-200 word explanation of why DCF / Comps / DDM diverge and how the "
            "weighted target was reached."
        ),
    )
    competitor_analysis: str | None = Field(
        default=None,
        description=(
            "Competitive-landscape narrative vs peers — a plain-language summary of "
            "market-share / growth / multiple comparisons."
        ),
    )
    news_summary: str | None = Field(
        default=None,
        description="3-5 sentence overall-sentiment narrative of the last 30 days of key news.",
    )
    momentum_divergence_note: str | None = Field(
        default=None,
        description=(
            "2-4 sentence explanation of what the market's OWN recent price action is "
            "pricing in, and why this recommendation differs from it. ONLY fill this "
            "field when the recommendation strongly disagrees with the stock's trailing "
            "1-year price return — a BUY on a stock down more than 15% over the past "
            "year, or a SELL on a stock up more than 30%. The thesis prompt injects an "
            "explicit MANDATORY instruction when that condition holds; leave this null "
            "otherwise (do not write it for an ordinary, non-divergent call). Do not "
            "restate the general bull/bear case here — this is specifically about the "
            "market's price action vs the call — and cite only numbers from the "
            "numeric-discipline whitelist (never invent a new figure to justify the "
            "divergence)."
        ),
    )


class StepOutput(BaseModel):
    """Wrapper for pipeline step output: text for report + optional structured data.

    The `structured` field accepts a BaseModel instance, a dict, or None.
    Uses ConfigDict(arbitrary_types_allowed=True) to prevent Pydantic validation
    that would try to instantiate BaseModel directly. The type annotation
    `object` is intentionally broad to prevent Pydantic coercion.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    text: str
    structured: object | None = Field(default=None)  # Accepts BaseModel, dict, or any object
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "Step-level warnings for the artifact's machine-readable warnings "
            "array. The channel for a step that degrades with structured=None "
            "(e.g. financial_modeling when the DCF is not applicable): builder "
            "warning harvesting only walks structured models' .warnings fields, "
            "so without this the degrade reason lived exclusively in server "
            "logs and the UI showed a bare 'DCF FAIR VALUE —' with no cause."
        ),
    )


class HistoricalMetrics(BaseModel):
    """Multi-year historical financial metrics extracted from provider data."""

    # Currency of every absolute monetary field (revenue/ebitda/eps/cash
    # flows…). The extractor normalizes native-reporting ADR history (TSM:
    # TWD) to the quote currency at today's spot before assembly; when FX is
    # unavailable the figures stay native and this tag says so — renderers and
    # LLM prompts must not assume USD. None = currency tags absent upstream
    # (test fakes / legacy rows). Ratios, margins and CAGR are
    # currency-invariant either way.
    currency: str | None = None

    # Provider that served the yearly statements ("fmp" / "yfinance";
    # "mixed:a+b" when years came from different providers in one fetch).
    # None = built by a path that didn't record provenance (test fakes /
    # legacy cache rows). Lets the /historical route disclose an FMP→yfinance
    # silent fallback the same way /financials and /price already do.
    data_source: str | None = None
    # Free-text user-facing notes (e.g. the FMP-degradation warning the route
    # appends). Mirrors the warnings convention on the canonical contracts.
    warnings: list[str] = Field(default_factory=list)

    years: list[int]
    revenue: list[float]
    revenue_growth_yoy: list[float | None]
    # cogs / gross_profit are None (not 0.0) for a year whose gross_profit the
    # provider omitted — chiefly no-COGS businesses (banks: fmp_provider sets
    # gross_profit=None). Fabricating cogs = revenue − 0 there would show a bank
    # "COGS = full revenue, gross profit = $0", which is misleading, not missing.
    cogs: list[float | None]
    gross_profit: list[float | None]
    # Margins are None for a year whose numerator the provider omitted — a
    # missing margin is "not reported", distinct from a real 0% (None ≠ 0). The
    # other absolute line items keep the 0.0 fill (all-zero row = missing
    # convention used by dcf_seed._median_ratio).
    gross_margin: list[float | None]
    sga: list[float]
    sga_ratio: list[float | None]
    ebitda: list[float]
    ebitda_margin: list[float | None]
    operating_income: list[float]
    operating_margin: list[float | None]
    net_income: list[float]
    eps: list[float]
    pe_ratio: list[float | None]
    cagr_revenue: float | None
    ticker: str
    price_data_available: bool = False
    operating_cash_flow: list[float] = Field(default_factory=list)
    investing_cash_flow: list[float] = Field(default_factory=list)
    financing_cash_flow: list[float] = Field(default_factory=list)

    # P7 — line items needed for standard DCF FCF formula: EBIT(1-t) + D&A - CapEx - ΔNWC.
    # Parallel to revenue/ebitda — same year ordering. Empty when provider didn't expose
    # the row; downstream consumers (dcf_seed) must fall back to industry medians and mark
    # provenance accordingly.
    depreciation_amortization: list[float] = Field(default_factory=list)
    capital_expenditure: list[float] = Field(default_factory=list)
    change_in_working_capital: list[float] = Field(default_factory=list)

    # Per-year parent shareholders' equity (parallel to net_income/years). Populated
    # from the yearly balance sheet; None for a year the provider omitted. Enables a
    # through-cycle ROE = mean(net_income / shareholders_equity) — both raw, so it
    # survives a historical year whose market-derived share count (and thus book value
    # PER SHARE) is missing. Feeds the insurer comps ROE adjustment. Empty when the
    # producer path predates this field (test fakes / legacy cache); consumers must
    # guard for a short/empty list.
    shareholders_equity: list[float | None] = Field(default_factory=list)


class CatalystEvent(BaseModel):
    """Single catalyst event extracted by LLM from news."""

    category: Literal[
        "product_launch",
        "earnings",
        "regulatory",
        "acquisition",
        "management",
        "market",
    ]
    headline: str
    sentiment: Literal["positive", "negative", "neutral"]
    impact_score: int = Field(ge=1, le=5)
    probability: float = Field(
        default=0.7,
        ge=0,
        le=1,
        exclude=True,
        description=(
            "Internal weight in the expected-impact aggregate (net_sentiment), NOT a "
            "displayed forecast: news events are weighted 0.7, primary-source 8-Ks 1.0. "
            "``exclude=True`` keeps it off EVERY serialization surface (the artifact "
            "export bundle, the /catalysts response) — these are PAST events, so a shown "
            "probability is fake precision, and the frontend already dropped its column "
            "(ChapterCatalysts/ChapterNews). The number-crunching that consumes it "
            "(_expected_impact, cluster rep selection, net_sentiment) reads the live "
            "ATTRIBUTE, which ``exclude`` does not touch, so ranking is byte-identical. "
            "``default`` is only for the /catalysts dump→model_validate round-trip (that "
            "route is news-only → weight 0.7, so reconstruction is lossless); the two "
            "real producers always pass it explicitly, so the default never authors a value."
        ),
    )
    reasoning: str
    published: datetime | None = None
    url: str | None = None
    source_count: int = Field(
        default=1,
        ge=1,
        description=(
            "How many near-duplicate news items collapsed into this one event "
            "after cluster_near_duplicates (1 = no dedup applied / singleton). "
            "The same regulatory lawsuit covered by 4 different law-firm press "
            "releases is ONE catalyst with source_count=4, not 4 events double-"
            "counted in net_sentiment / total_catalysts."
        ),
    )


class CatalystAnalysis(BaseModel):
    """LLM-structured catalyst analysis output."""

    events: list[CatalystEvent]
    overall_sentiment: Literal["bullish", "bearish", "neutral"]
    key_catalysts: list[str]
    # P6 additions
    net_sentiment: float = Field(
        default=0.0,
        description=(
            "Mean expected impact per event (impact × probability × sign), clamped "
            "to [-5, 5]. Mean, not sum — a 30-event news day must not saturate the "
            "scale (see summarize_catalyst_outlook)."
        ),
    )
    category_breakdown: dict[str, int] = Field(default_factory=dict)
    top_positive: list[CatalystEvent] = Field(default_factory=list)
    top_negative: list[CatalystEvent] = Field(default_factory=list)


class ValuationMethod(BaseModel):
    """One valuation method's result range."""

    name: str
    low: float
    mid: float
    high: float
    confidence: float = Field(
        ge=0,
        le=1,
        description=(
            "Method weight in the confidence-weighted price synthesis (NOT prediction accuracy). "
            "A higher value means this method is trusted more in the weighted average; "
            "it does NOT mean '85% chance the target is right'. Based on data quality / "
            "methodology robustness (DCF 0.85, forward comps 0.78 …), not back-tested accuracy."
        ),
    )
    source: str
    assumptions: str | None = Field(
        default=None,
        description=(
            "Short human-readable summary of the load-bearing assumptions behind "
            "`mid` — e.g. DCF's 'WACC 16.6% · 5年增长40%→2.5% · β2.24'. A mid like "
            "$73 is not a valuation, it's an answer conditional on these. Carried "
            "downstream so a price is never cited naked."
        ),
    )
    rerating_ratio: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Multiples methods only: implied multiple / the target's own current "
            "same-caliber multiple (mirrored from ValuationMethodRange.rerating_ratio "
            "by build_valuation_synthesis). The confidence dial reads it to GRADE "
            "re-rating dominance (cap the tier when far-from-1 ratios drag the blend "
            "off the cash-flow anchor); None for intrinsic methods and on the "
            "mixed-caliber comps fallback."
        ),
    )


class ValuationSynthesis(BaseModel):
    """Multi-method valuation synthesis. Football field data derives from methods."""

    methods: list[ValuationMethod]
    weighted_price: float | None
    """None when fewer than 2 methods are available — single-method "averages"
    are meaningless cross-checks and MUST NOT be presented as weighted targets."""
    current_price: float
    upside_downside: float | None
    """None when weighted_price is None (no valid cross-check available)."""
    outlier_methods: list[str] = Field(
        default_factory=list,
        description=(
            "Method names whose mid deviates > 30% from the cross-method median. "
            "Populated by synthesize_valuations; empty when fewer than 2 methods."
        ),
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Human-readable warnings produced during synthesis (e.g. spread alerts).",
    )
    # --- Confidence dial (the graded call; see ADR 估值优雅降级) ---
    # The redesign deletes the REVIEW verdict AND the binary `reliable` data-health
    # gate: a synthesis ALWAYS yields a directional call, with uncertainty expressed
    # as a confidence tier + a widening target band (Morningstar-style: uncertainty
    # widens the margin of safety, never withholds the call) and, only when the sole
    # available number would be fabricated, a withheld POINT (`valuation_withheld`).
    # Default "low" so a legacy artifact (no confidence persisted) never implies
    # conviction it wasn't graded for.
    confidence: Literal["high", "medium", "low", "very_low"] = Field(
        default="low",
        description=(
            "Analytical confidence tier — derived from method count + cross-method "
            "agreement (max/min spread) + data-degradation + provenance, AND capped when "
            "the model/market ratio falls outside the [0.25x, 4x] calibration band "
            "(option-value regime) or when a corroborated blend is re-rating-led "
            "(multiples premises beyond RERATING_GAP_RATIO_K dragging the blend past "
            "RERATING_ANCHOR_DISPLACEMENT_M off the DCF anchor — a premise bet, not a "
            "corroborated read). Deliberately NOT a function of distance-to-market "
            "within band: two methods that agree the stock is rich (KO) stay HIGH "
            "confidence. Drives band width + the asymmetric verdict thresholds; it is "
            "never a reason to withhold the directional call."
        ),
    )
    target_low: float | None = Field(
        default=None,
        description=(
            "Low end of the headline price-target range. Widens as confidence drops and "
            "always spans the surviving method mids on divergence (so an analyst sees the "
            "real method disagreement, not a false-precise point). None when no point "
            "anchor exists (valuation_withheld)."
        ),
    )
    target_high: float | None = Field(
        default=None, description="High end of the headline price-target range (see target_low)."
    )
    anchor_method: str | None = Field(
        default=None,
        description=(
            "Name of the method the headline point anchors on under the comparability "
            "rule (cyclical / unique business → DCF; rich peer set → comps). The point "
            "sits AT the anchor, never a blended midpoint of divergent methods. None when "
            "methods corroborate (plain weighted average) or the target is withheld."
        ),
    )
    valuation_withheld: bool = Field(
        default=False,
        description=(
            "True when the POINT target is honestly withheld — corrupt input, a single "
            "method wildly off-market, or no fundamental anchor — because the only number "
            "available would be fabricated (绝不编数字). The directional VERDICT still "
            "ships from the market-implied / reverse-DCF read. This is NOT a refusal to "
            "rate (the deleted REVIEW state); it is the explicit flag every withhold "
            "producer sets and every downstream gate keys on (replacing the old "
            "recommendation=='REVIEW' sentinel)."
        ),
    )
    degradation_note: str | None = Field(
        default=None,
        description=(
            "Human-readable disclosure of what degraded and which proxy/anchor was used "
            "(e.g. 'methods diverge 7x — anchored DCF, comps_pb shown as range cap' / "
            "'no peer comps — single-method DCF, wider band'). Surfaced to the analyst so "
            "every degraded call is traceable."
        ),
    )
    mna_transition: bool = Field(
        default=False,
        description=(
            "True when the name just closed a stock-funded acquisition / large secondary "
            "(current share count materially above the pre-deal weighted-avg baseline). Its "
            "TTM per-share metrics (DDM g, comps EPS, ROE) mix a post-deal share count with "
            "mostly-pre-deal earnings, so every method reads spuriously bearish while the "
            "market prices the pro-forma entity. resolve_canonical_thesis withholds the "
            "poisoned point and holds the verdict neutral (HOLD) on this flag — a "
            "data-lineage degradation, NOT a calibration call. Default False."
        ),
    )
    financial_sector: bool = Field(
        default=False,
        description=(
            "True for a balance-sheet financial (bank / risk-carrying insurer) whose "
            "cash-flow valuation methods — FCFF-DCF, EV/EBITDA, P/FCF — are suppressed as "
            "category errors (deposits / float / reserves are operating raw material, not "
            "capital structure). The football field leads on P/B · P/E (+ DDM / residual "
            "income for banks). Persisted so a consumer (the report chapters) can frame the "
            "absent DCF / Monte-Carlo / EV-EBITDA-band panels as 'not applicable to a "
            "balance-sheet financial' rather than 'missing — re-run', WITHOUT re-deriving "
            "is_balance_sheet_financial in the client (single authority stays in Python). "
            "Default False."
        ),
    )


# ---------------------------------------------------------------------------
# LBO Models (P2d)
# ---------------------------------------------------------------------------


class LBOInputs(BaseModel):
    """Assumptions driving the LBO model. LLM selects these, code computes math."""

    ticker: str
    ltm_ebitda: float = Field(gt=0, description="LTM EBITDA at entry (USD)")
    entry_ebitda: float | None = Field(
        default=None,
        gt=0,
        description=(
            "EBITDA the entry EV and acquisition debt are PRICED on (USD). None → "
            "price on ltm_ebitda (the non-cyclical case). For a commodity/deep-cyclical "
            "this is the NORMALIZED through-cycle EBITDA (revenue_base × through-cycle "
            "EBITDA margin) so entry leverage is underwritten against sustainable earnings, "
            "matching the projection caliber, not the current cycle-peak/trough LTM."
        ),
    )
    entry_ev_ebitda: float = Field(gt=0, description="Entry EV/EBITDA multiple")
    exit_ev_ebitda: float = Field(gt=0, description="Exit EV/EBITDA multiple")
    holding_period_years: int = Field(default=5, ge=1, le=10)
    revenue_base: float = Field(gt=0, description="LTM revenue at entry (USD)")
    revenue_growth_rate: float = Field(
        ge=-0.5, le=1.0, description="Annual revenue growth (constant)"
    )
    ebitda_margin: float = Field(ge=0, le=1, description="EBITDA/revenue (constant)")
    da_pct_revenue: float = Field(default=0.04, ge=0, le=0.3)
    capex_pct_revenue: float = Field(default=0.04, ge=0, le=0.5)
    nwc_change_pct_revenue: float = Field(default=0.01, ge=-0.2, le=0.3)
    leverage_multiple: float = Field(
        default=5.0, ge=0, le=20, description="Total debt / EBITDA at entry"
    )
    interest_rate: float = Field(default=0.07, ge=0, le=0.5, description="Blended debt rate")
    mandatory_amort_pct: float = Field(
        default=0.01, ge=0, le=0.5, description="Mandatory amortization as % of entry debt per year"
    )
    cash_sweep: bool = Field(default=True, description="Sweep all excess FCF to debt")
    tax_rate: float = Field(default=0.25, ge=0, le=1)

    # Parallels DCFInputs.assumption_provenance — populated by seed_lbo_inputs.
    # Maps each LBO assumption field name to a Chinese-localised explanation of
    # where the number came from (3y historical median / industry median / PE
    # convention) so the UI can render a 散户-friendly provenance panel.
    # The DCFInputs equivalent is the canonical reference for the contract.
    assumption_provenance: dict[str, str] = Field(
        default_factory=dict,
        description="Maps assumption field names to their reasoning/source",
    )


class LBOYear(BaseModel):
    """One year of LBO operations. All numbers deterministically computed."""

    year: int
    revenue: float
    ebitda: float
    da: float
    ebit: float
    interest_expense: float
    ebt: float
    taxes: float
    net_income: float
    capex: float
    delta_nwc: float
    fcf: float  # Cash available for debt service
    mandatory_amort: float
    cash_sweep_amount: float
    total_debt_paydown: float
    revolver_draw: float = 0.0  # Revolver borrowing when FCF < mandatory amort (cash-burn year)
    ending_debt: float


class LBOResult(BaseModel):
    """Full LBO model output. All returns computed by code, not LLM."""

    entry_ev: float
    entry_debt: float
    entry_equity: float
    schedule: list[LBOYear] = Field(min_length=1)
    exit_ebitda: float
    exit_ev: float
    exit_equity: float
    moic: float | None = Field(
        default=None,
        description="MOIC (×). 0 = total loss (equity wiped at exit). "
        "None = undefined (non-positive entry equity: debt ≥ entry EV — impossible structure).",
    )
    irr: float | None = Field(
        default=None,
        description="Annualized IRR (decimal). -1.0 = total loss (equity wiped at exit). "
        "None = undefined (non-positive entry equity — impossible LBO structure).",
    )
    self_financing: bool | None = Field(
        default=None,
        description=(
            "Whether the modeled levered FCF deleverages the acquisition debt over the "
            "hold (exit debt < entry debt). False = the deal does NOT self-finance: "
            "projected operating cash flow is negative across the hold, the revolver funds "
            "the shortfall every year and net debt RISES instead of amortizing, so any "
            "positive exit equity is manufactured by exit-multiple expansion on a larger, "
            "debt-financed EBITDA base — NOT by operating deleveraging. MOIC / IRR are then "
            "exit-multiple-dependent, not returns a sponsor could underwrite at this "
            "structure, and must not headline as achievable. None = undefined (impossible "
            "structure: non-positive entry equity)."
        ),
    )
    sensitivity: dict[str, Any] = Field(
        default_factory=dict,
        description="entry_multiples, exit_multiples, irr_grid, moic_grid",
    )
    irr_formula_warning: str | None = None
    capital_structure_warning: str | None = None


# ---------------------------------------------------------------------------
# Earnings Models (P2d)
# ---------------------------------------------------------------------------


class EarningsSurprise(BaseModel):
    """Single quarter earnings surprise. All computed by code from raw provider data."""

    date: str
    eps_actual: float | None  # None when provider omits the value (None ≠ 0)
    eps_estimated: float | None
    eps_surprise_pct: float | None  # (actual-est)/|est|×100; None if est==0 or input missing
    eps_direction: str  # "beat" | "miss" | "inline" | "n/a" (n/a = undefined, est == 0)
    revenue_actual: float | None  # None ≠ 0: missing revenue stays None, never fabricated $0
    revenue_estimated: float | None
    revenue_surprise_pct: float | None  # None if est==0 or input missing (undefined surprise)
    revenue_direction: str  # "beat" | "miss" | "inline" | "n/a"


class EarningsResult(BaseModel):
    """Aggregated earnings quality metrics. Computed from N quarters of data."""

    ticker: str
    surprises: list[EarningsSurprise]
    beat_rate: float = Field(ge=0, le=1, description="% of quarters with EPS beat")
    avg_eps_surprise_pct: float
    avg_revenue_surprise_pct: float
    consecutive_beats: int = Field(
        ge=0, description="Current consecutive beat streak (most recent first)"
    )


# ---------------------------------------------------------------------------
# IC Memo Models (P2d)
# ---------------------------------------------------------------------------


class ICFinancials(BaseModel):
    """Combined DCF + LBO results for IC Memo financial analysis step."""

    financial_data: "FinancialData"
    dcf_result: DCFResult
    lbo_result: LBOResult


# ---------------------------------------------------------------------------
# DDM Models (bank/dividend valuation)
# ---------------------------------------------------------------------------


class DDMInputs(BaseModel):
    """Inputs for Dividend Discount Model.

    DDM is the standard valuation method for banks, utilities, and
    dividend-paying stocks where traditional free cash flow is not meaningful.
    Banks earn via net interest income and return cash primarily through dividends.

    LLM selects these assumptions; code computes the valuation math.
    """

    dividend_per_share: float = Field(gt=0, description="Most recent annual DPS")
    dividend_growth_rates: list[float] = Field(
        min_length=1,
        max_length=10,
        description="Projected annual dividend growth rates as decimals",
    )

    # Same finiteness gate as DCFInputs.revenue_growth_rates (the unbounded-
    # list sibling): a NaN growth rate slips past calculate_ddm's < -1 guard
    # (NaN comparisons are False) and poisons the dividend projection.
    @field_validator("dividend_growth_rates")
    @classmethod
    def _reject_non_finite_growth(cls, v: list[float]) -> list[float]:
        for i, g in enumerate(v):
            if not math.isfinite(g):
                raise ValueError(
                    f"dividend_growth_rates[{i}] must be finite — "
                    "NaN/Inf is not a number, it's missing data"
                )
        return v

    payout_ratio: float = Field(ge=0, le=1, description="Dividend payout ratio")

    # Cost of equity inputs (CAPM)
    risk_free_rate: float = Field(ge=0, le=0.15)
    beta: float = Field(ge=0, le=3)
    equity_risk_premium: float = Field(ge=0, le=0.15)

    terminal_growth_rate: float = Field(ge=0, le=0.05)
    terminal_payout_ratio: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description=(
            "Payout ratio applied in the Gordon-perpetuity terminal phase. When "
            "set, the terminal dividend is normalized to the payout a mature firm "
            "can sustain at its ROE and terminal growth (≈ 1 − g/ROE), correcting "
            "the naive DDM error of holding a low trailing payout into perpetuity. "
            "seed_ddm_inputs derives this; when None calculate_ddm falls back to "
            "the constant-payout (naive Gordon) terminal."
        ),
    )
    shares_outstanding: float = Field(gt=0)
    current_price: float = Field(gt=0)

    # Bank-specific context (optional, for enriching narrative)
    book_value_per_share: float | None = None
    return_on_equity: float | None = None
    tier1_ratio: float | None = None
    net_interest_margin: float | None = None

    assumption_provenance: dict[str, str] = Field(
        default_factory=dict,
        description="Maps assumption field names to their reasoning/source",
    )


class DDMResult(BaseModel):
    """DDM valuation output. All numbers computed by code, not LLM.

    Uses cost of equity (not WACC) as discount rate because dividends
    are paid to equity holders only.
    """

    cost_of_equity: float
    projected_dividends: list[float]
    pv_dividends: list[float]
    pv_dividends_total: float
    terminal_dividend: float
    terminal_value: float
    pv_terminal: float
    equity_value_per_share: float
    inputs: DDMInputs

    @property
    def upside(self) -> float:
        """Upside/downside vs current price as a decimal."""
        return self.equity_value_per_share / self.inputs.current_price - 1


class RIResult(BaseModel):
    """Residual-income (justified-P/B) valuation output. Code-computed, not LLM.

    A bank is worth its book value plus the present value of the excess return it
    earns over its cost of equity: V = BVPS × [1 + (ROE − CoE)/(CoE − g)]. Unlike
    the DDM it is ROE-coherent (no P/B-vs-P/E divergence to mis-anchor) and
    buyback-invariant — it anchors on hard book value, not a projected payout — and
    it is correctly bearish when ROE < CoE (value below book, the right read for a
    chronic underperformer). The bank's intrinsic anchor.
    """

    cost_of_equity: float
    book_value_per_share: float
    return_on_equity: float
    excess_return: float
    """ROE − CoE: the spread the franchise earns over its cost of equity (the sign
    of the value premium/discount to book)."""
    terminal_growth_rate: float
    justified_pb: float
    """V / BVPS = 1 + (ROE − CoE)/(CoE − g) — the justified price-to-book."""
    equity_value_per_share: float
    """RI at TRAILING ROE — the independent low end of the bank's value band (our own
    realized return, an accounting fact)."""
    forward_return_on_equity: float | None = None
    """FY1 consensus ROE = trailing ROE × (consensus NI / trailing NI). None when no
    forward estimate is available."""
    forward_value: float | None = None
    """RI at FORWARD (consensus) ROE — the recovery high end of the value band. The
    band [equity_value_per_share, forward_value] brackets the trough→normalized
    uncertainty; the verdict is price-vs-band, never a single perpetuity-ROE point.
    None when no forward estimate is available (single-stage fallback)."""
    inputs: DDMInputs

    # No ``upside`` property (unlike DDMResult): a bank's RI is consumed ONLY as the
    # [trailing, forward] band via _ri_method → price-vs-band, never as a single point.
    # A trailing-only upside here would be the −40%-single-trough-ROE figure the band
    # design exists to refuse — deliberately absent, not forgotten.


# ---------------------------------------------------------------------------
# Football Field aggregation (v5 §6.4)
# ---------------------------------------------------------------------------


ValuationMethodType = Literal["valuation", "multiple"]
"""Distinguishes independent valuation methods (DCF / Comps / DDM / LBO) from
multiple-based reverse-engineered ranges (EV/EBITDA, P/FCF) so the UI can render
them with different visual weight — solid bars vs dashed bars (spec §6.4)."""

ValuationMethodName = Literal[
    "dcf",
    "comps_pe",
    "comps_pb",
    "lbo",
    "ddm",
    "residual_income",
    "ev_ebitda",
    "p_fcf",
]


class ValuationMethodRange(BaseModel):
    """One method's low / mid / high target-price band for the Football Field.

    A leaner cousin of ValuationMethod tagged with `method_type` so the front
    end can render valuation methods as solid bars and multiple-based reverse
    ranges as dashed bars (v5 §6.4).
    """

    method: ValuationMethodName
    method_type: ValuationMethodType
    low: float = Field(gt=0)
    mid: float = Field(gt=0)
    high: float = Field(gt=0)
    confidence: float = Field(
        ge=0,
        le=1,
        description=(
            "Method weight in the confidence-weighted price synthesis (NOT prediction accuracy). "
            "Used internally as the weight in weighted_price = Σ(mid×wt)/Σ(wt). "
            "Does not represent a probability of the target being correct."
        ),
    )
    source: str = Field(description="Human-readable provenance, e.g. 'implied_price ± 20%'")
    assumptions: str | None = Field(
        default=None,
        description=(
            "Short summary of the load-bearing assumptions behind `mid`, built at "
            "the source where the underlying result object is in scope. Propagated "
            "to ValuationMethod.assumptions so a price is never cited naked."
        ),
    )
    rerating_ratio: float | None = Field(
        default=None,
        gt=0,
        description=(
            "For a MULTIPLES method only: the multiple shift its premise implicitly bets "
            "on, as `method-implied multiple / the target's own current SAME-caliber "
            "multiple` (comps_pe: peer-median anchor vs self; ev_ebitda: own 5y band mid "
            "vs price-implied). 1.0 = prices the target exactly where it trades; 1.38 = "
            "assumes a +38% re-rate; 0.7 = a de-rate. Set ONLY where the two sides share "
            "one caliber (the mixed-caliber comps fallback stays None — 绝不混口径), by the "
            "same aggregator code that builds the re-rating disclosure. None for "
            "cash-flow/intrinsic methods (DCF/DDM/RI/LBO), which carry no re-rating "
            "premise. Structured twin of the assumptions-string disclosure so the "
            "confidence dial can GRADE re-rating dominance without parsing prose."
        ),
    )
    warnings: list[str] = Field(default_factory=list)


class ValuationAggregate(BaseModel):
    """Response payload for ``GET /api/valuation/aggregate/{ticker}``.

    Contains every method we could compute for the ticker at request time.
    Missing methods are simply absent from `methods`; the UI shows what's
    available and explains the gaps via `warnings`.
    """

    ticker: str
    current_price: float | None
    as_of: datetime
    methods: list[ValuationMethodRange]
    warnings: list[str] = Field(default_factory=list)
    # Forward-estimates provenance — tells the analyst WHICH forecast fiscal year
    # drives comps_pe / ev_ebitda / p_fcf rows (e.g. "2026-09-30"), where the
    # numbers came from, and how much to trust them. None when forward data was
    # unavailable (those rows are absent from `methods` anyway).
    forward_fiscal_period: str | None = None
    forward_confidence: str | None = None
    forward_source: str | None = None


# ---------------------------------------------------------------------------
# Scenario SOTP — reverse-SOTP market-implied decomposition (Batch 3B v1)
# ---------------------------------------------------------------------------
#
# For "option-value" names (TSLA-class: no growth in the reverse-DCF bracket
# reaches the live price), a fundamentals point target is dishonest. SOTP gives
# the publishable, sourceable alternative: a deterministic cash-flow FLOOR from
# SEC-filed reportable segments × comparable multiples, then a pure-subtraction
# reverse decomposition of how much of the live market cap the floor does NOT
# explain (= the market's implied option value for robotaxi/FSD/Optimus).
#
# v1 is 100% sourceable, zero fabricated forward assumptions. It is an
# independent option-value CHANNEL (structured_context["sotp_breakdown"] /
# football-field SOTP row) — it does NOT enter confidence-weighted point-target
# synthesis, so it never trips the method-corroboration span gate
# (METHOD_CORROBORATION_SPAN_K) against the DCF floor. All fields are COMPUTED
# (deterministic arithmetic), never LLM-narrated — scalars only, the bilingual
# UI renders the sentence.


class SegmentValuation(BaseModel):
    """One reportable segment's cash-flow valuation leg of the SOTP floor.

    Every field is sourceable: ``metric_value`` traces to a 10-K accession +
    XBRL concept + dimension member; ``multiple``/``multiple_source`` to the
    comparable basis. ``implied_ev = metric_value × multiple`` (pure product).
    """

    name: str
    """Canonical segment name, e.g. "Automotive" / "Energy generation and storage"."""
    metric_label: str
    """Caliber string for the metric, e.g. "FY2025 segment gross profit"."""
    metric_value: float
    """Absolute USD value of the valuation metric (segment gross profit / EBIT)."""
    multiple: float
    """Deterministic comparable multiple applied (e.g. peer-median EV/gross-profit)."""
    multiple_source: str
    """Sourceable caliber for the multiple, e.g. "auto OEM peer median EV/gross-profit"."""
    implied_ev: float
    """metric_value × multiple — this segment's EV contribution to the floor."""


class SOTPScenarioBand(BaseModel):
    """Forward scenario band for an option-value name (Batch 3B v2 · C 4-point merge).

    TWO calibers, each COMPLETE and DISTINCTLY LABELLED — never blended (team-lead
    2026-07-06, C):

      1. ``cash_flow_floor`` — the reverse-SOTP cash-flow floor: a PRESENT value,
         the robotaxi-fails downside. An INDEPENDENT anchor, not a leg of the street
         range.
      2. ``bear`` / ``base`` / ``bull`` — the 12-month analyst price-target
         DISTRIBUTION (street low / consensus / high): FORWARD values.

    🔴 HARD RULE — NO CROSS-CALIBER RATIO. ``range_position`` is the SAME-caliber
    street-range position (price within [bear, bull], both 12-month forward). A
    floor→street ratio (e.g. (price − floor)/(bull − floor)) mixes a present value
    with a forward target across time bases and is FORBIDDEN on every surface — it
    is never computed or stored, and a consumer must NOT place the live-price marker
    on a [floor, bull] axis (that marker's position IS that forbidden ratio). The
    floor's relation to price is expressed ONLY as ``floor_coverage`` (floor /
    price — both present values, same caliber). And ``range_position`` MUST NEVER be
    surfaced as a "robotaxi / optionality success probability" (that ceiling is
    un-sourceable; the reverse-SOTP ``option_ev_if_success`` is kept None for it).

    All fields COMPUTED + sourceable; confidence is inherently low (street-anchored,
    forward, [金融待核 F2]).
    """

    cash_flow_floor: float | None = None
    """Reverse-SOTP cash-flow floor (per share, PRESENT value, robotaxi-fails
    downside) — an independent anchor beside the street cluster, NOT a street leg.
    None when the floor is unavailable."""
    floor_coverage: float | None = None
    """cash_flow_floor / current_price — the ONLY floor-vs-price relation allowed
    (both present values, same caliber). e.g. 0.10 = the floor covers ~10% of the
    live price. A floor→street-target ratio is forbidden (cross-caliber)."""
    bear: float
    """Street LOW 12-month analyst target (the bearish-analyst leg)."""
    base: float
    """Street CONSENSUS 12-month analyst target (the central leg)."""
    bull: float
    """Street HIGH 12-month analyst target (the bullish-analyst leg)."""
    median: float | None = None
    """Street MEDIAN 12-month target (context; None if the source omits it)."""
    current_price: float
    range_position: float
    """(current_price − bear) / (bull − bear): the live price's position within the
    12-month STREET range — SAME caliber (both forward). NEVER a floor→street ratio
    (cross-caliber, forbidden) and NEVER a robotaxi-success probability. NOT clamped:
    < 0 (market below the most bearish target) or > 1 (above the most bullish) is a
    legal, informative signal."""
    analyst_count: int | None = None
    """Recent-year count of analysts contributing targets (coverage depth); None
    when the source omits it (confidence is then downgraded)."""
    confidence: str = "low"
    """"low" (street-anchored, forward) or "very_low" (thin analyst coverage)."""
    source: str
    """Sourceable provenance: the FMP price-target endpoints + as-of."""
    as_of: datetime
    warnings: list[str] = Field(default_factory=list)


class SOTPBreakdown(BaseModel):
    """Reverse-SOTP market-implied decomposition for an option-value name.

    The publishable REVIEW-state product: a deterministic cash-flow floor
    (modelable segments × comparable multiples) plus the pure-subtraction
    implied option value the market assigns above that floor. NOT a point target
    — ``price_floor`` is a floor, not a forecast; it lives in basis narrative,
    never in ``thesis.price_target``, so the headline [0.5×,2×]/[0.25×,4×] gates
    are no-ops here (no headline per-share target is produced).

    All fields COMPUTED, no baked prose (mirrors MarketImpliedCheck/Nature).
    Tolerant of extremes by design: ``implied_option_pct`` may exceed 1 (a
    cash-burning name whose floor is tiny) or go negative (floor above market →
    ``floor_exceeds_market``); no ``ge=0/le=1`` guard that would reject a legal
    extreme (spec §8#6).
    """

    ticker: str
    as_of: datetime
    modelable_segments: list[SegmentValuation]
    """Cash-flow-modelable segments (Automotive / Energy …); the floor's legs."""
    ev_floor: float
    """Σ modelable_segments.implied_ev — the deterministic enterprise-value floor."""
    net_debt: float
    """Net debt subtracted to bridge EV floor → equity floor (negative = net cash)."""
    equity_floor: float
    """ev_floor − net_debt."""
    price_floor: float
    """equity_floor / shares_outstanding — the per-share cash-flow floor (NOT a target)."""
    shares_outstanding: float
    current_price: float
    market_equity: float
    """current_price × shares_outstanding."""
    implied_option_ev: float
    """market_equity − equity_floor — the value the market assigns to the option
    segment (robotaxi/FSD/Optimus), reverse-derived, zero fabricated forward."""
    implied_option_pct: float
    """implied_option_ev / market_equity — option value as a share of live cap.
    May exceed 1 or go negative; not clamped (see class docstring)."""
    # Implied success probability (optional second leg; needs an external anchor):
    option_ev_if_success: float | None = None
    """External sell-side SOTP ceiling for the success state (source string set)."""
    option_anchor_source: str | None = None
    implied_success_probability: float | None = None
    """implied_option_ev / option_ev_if_success — the market-IMPLIED success
    probability (reverse-derived from price, NOT a forecast we authored)."""
    # Degeneracy / rejection signals (mirror MarketImpliedCheck.growth_unreachable):
    floor_exceeds_market: bool = False
    """equity_floor > market_equity → not an option-premium name; SOTP option
    decomposition does not apply (it should go through ordinary multi-method)."""
    market_exceeds_success_ceiling: bool = False
    """implied_success_probability > 1 → live price exceeds even the full success
    SOTP ceiling — a stronger over-pricing signal than reverse-DCF unreachable."""
    scenario_band: SOTPScenarioBand | None = None
    """Forward STREET-anchored scenario band (12-month analyst target distribution).
    A SEPARATE semantic block from the reverse-SOTP decomposition above: its
    range_position is street positioning, NEVER a robotaxi-success probability (see
    SOTPScenarioBand). None when analyst price targets are unavailable."""
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Lightweight segment overview — non-SOTP display for the Company Overview
# chapter (BACKLOG A4, 2026-07-09).
# ---------------------------------------------------------------------------
#
# SOTP (above) is a heavy reverse-decomposition VALUATION channel, gated on
# ``classify_market_implied_nature().kind == "option_value"`` — it never fires
# for an ordinary name. This is the opposite: a DISPLAY-only breakdown (no
# multiples, no implied EV, no market residual) for every OTHER ticker, so the
# Company Overview chapter can show real segment revenue mix instead of the
# hardcoded "segment data unavailable" line that was stale the moment SOTP
# proved SEC XBRL segment facts ARE fetchable (2026-05-28 assertion, disproven
# by the SOTP fetch shipped 2026-07-06).
#
# XBRL-ONLY source (BACKLOG A4, 2026-07-09 — an FMP product-mix fallback was
# added then removed the same day, see FMPProvider note): ASC-280 reportable
# segments from the 10-K XBRL (extract_segment_facts) — the audited disclosure
# unit management runs the business by (MSFT: 3 segments). Revenue + EITHER
# gross_profit (TSLA-style: segment-level gross profit disclosed) OR
# operating_income (MSFT-style: segment-level operating income disclosed, no
# segment gross profit) — never both for the same issuer. An issuer whose XBRL
# has no cleanly-anchorable reportable-segment breakdown (e.g. KO: reportable
# segments collapse onto a single ``OperatingSegmentsMember`` label crossed with
# a second axis, unrecoverable single-axis) degrades to NO SegmentOverview — an
# honest "not available", NEVER a fabricated / mis-taxonomied substitute.
class SegmentShare(BaseModel):
    """One reportable segment's revenue (+ optional profitability) row.

    ``revenue_share`` is the segment's share of the SUM of segment revenues in
    THIS SAME breakdown — not a share of the company's consolidated total
    revenue (which may not reconcile exactly due to corporate/eliminations
    items ASC 280 lets an issuer omit from the segment table; see
    ``SegmentOverview`` caveat). None when revenue itself is unavailable for
    this segment, or when no segment in the breakdown has any revenue.
    """

    name: str
    revenue: float | None = None
    revenue_share: float | None = None
    operating_income: float | None = None
    """MSFT-style segment profitability metric. None for a gross-profit-anchored
    breakdown (TSLA-style)."""
    gross_profit: float | None = None
    """TSLA-style segment profitability metric. None for an operating-income-
    anchored breakdown (MSFT-style)."""


class SegmentOverview(BaseModel):
    """Lightweight, display-only reportable-segment revenue mix.

    Populated for tickers that are NOT SOTP option-value candidates (SOTP owns
    the heavier reverse-decomposition valuation for those). No valuation math —
    the synthesis LLM cites ``segments[].revenue_share`` in ``company_overview``
    prose (deterministic whitelist injection, never free narration) and the
    Company Overview chapter renders the same rows as a table. All fields
    COMPUTED/fetched, zero LLM involvement in the numbers themselves. XBRL-only
    provenance (``source`` is a single-value Literal, kept for provenance
    labelling + future extension).
    """

    ticker: str
    as_of: datetime
    source: Literal["sec_xbrl_business_segment"]
    period_label: str
    """e.g. "FY ending 2025-06-30"."""
    segments: list[SegmentShare]
    warnings: list[str] = Field(default_factory=list)
