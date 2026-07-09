"""Typed projections from normalized canonical data to engine models.

ADR-0006 Step 4: functions here accept *already-normalized* typed inputs
(``NormalizedFinancials``, ``NormalizedPrice``) instead of raw ``DataResult``
dicts. The normalization关卡 lives exclusively in ``DataLayer.fetch_canonical``
— extractor is the projection layer (typed → FinancialData / CompanyFinancials
/ PriceHistory) that carries EBITDA caliber logic, EV handling, shares fallback,
and provenance merging. It must not re-normalize.

Historical per-year callers (``_helpers._build_historical_metrics``) that still
receive raw ``DataResult`` slices from ``fetch_historical`` wrap them with
``normalize_financials / normalize_price`` at the call site before passing here.
"""

from finrobot.engine.data.normalize.contracts import NormalizedFinancials, NormalizedPrice
from finrobot.engine.models.financial import (
    FIELD_WARN_EV_MISSING_NET_DEBT,
    FIELD_WARN_SHARES_DERIVED,
    DataProvenance,
    FinancialData,
    IncomeStatement,
    BalanceSheet,
    MarketData,
    ValuationMetrics,
    PriceHistory,
    CompanyFinancials,
)
from finrobot.engine.compute.operators.fx_normalize import (
    normalize_company_to_usd,
    normalize_financialdata_to_usd,
)
from finrobot.engine.compute.operators.multiples import calculate_ev
from finrobot.engine.primitives.book_value import (
    SHARES_PRICE_CONSISTENCY_TOL as _SHARES_PRICE_CONSISTENCY_TOL,
    reconcile_book_value_to_price_basis,
)
from finrobot.engine.primitives.ebitda import (
    calculate_ebitda_operating,
    calculate_ebitda_reported,
)
from finrobot.engine.primitives.industry import is_balance_sheet_financial, is_bank

# The tolerance governing when a reported share count is treated as OFF the quoted
# price's basis (→ use the market_cap/price-implied count for per-share calibers) is
# owned by ``primitives.book_value`` so the share-count reconciliation below and the
# book-value-per-share reconciliation move in lockstep on the same threshold.

# Economic band for a margin ratio. A gross/operating margin ABOVE 100% implies a
# negative cost of goods / operating cost — not credible: the only legitimate breach
# is a rare supplier-rebate contra-cost, indistinguishable from the far more common
# provider artifact of a dropped/restated cost line (FMP reports UL grossProfit ≥
# revenue with quarterly costOfRevenue=0, GM 100.14%, while the real gross margin is
# ~47% per the annual filings — unrecoverable in the TTM path). Withhold such a value
# (None → shown as N/A) rather than fabricate a 100% figure OR crash the IncomeStatement
# ``le`` bound. Invariant-suite #5: gross_margin ≤ 100% is a SOFT rule (compute-and-flag,
# legitimacy exit before any throw), not a hard model crash. Below -500% is a
# percent/decimal mixup (the same magnitude the ``ge=-5`` model floor documents).
_MARGIN_CEILING = 1.0
_MARGIN_FLOOR = -5.0


def _sanitize_margin(
    value: float | None, *, label: str, warnings: list[str] | None = None
) -> float | None:
    """Withhold (return None) a margin ratio outside the economically-credible band.

    A margin > 100% (implied negative cost) or < -500% (percent/decimal mixup) is not a
    trustworthy figure — return None so the metric shows N/A instead of a fabricated
    value, and never let it reach the IncomeStatement bound and crash the whole report.
    Byte-identical (returns the input) for every credible margin in ``[-5.0, 1.0]``.
    """
    if value is None:
        return None
    if value > _MARGIN_CEILING:
        if warnings is not None:
            warnings.append(
                f"{label} {value:.1%} exceeds 100% (implied negative cost) — the provider's "
                f"gross profit ≥ revenue with the cost line unreported/restated; withheld as "
                f"unreliable rather than shown as a fabricated 100% or crashing the report"
            )
        return None
    if value < _MARGIN_FLOOR:
        if warnings is not None:
            warnings.append(
                f"{label} {value:.1%} below -500% — a likely percent/decimal mixup or provider "
                f"error; withheld"
            )
        return None
    return value


def extract_financial_data(
    fin: NormalizedFinancials,
    price: NormalizedPrice,
) -> FinancialData:
    """Project NormalizedFinancials + NormalizedPrice into FinancialData.

    Normalization has already happened upstream (ADR-0006): ``fin`` and
    ``price`` are typed, currency-resolved, provenance-stamped objects from
    ``DataLayer.fetch_canonical``.  This function only computes derived
    fields (EBITDA calibers, EV, shares fallback, 52w high/low) and assembles
    the engine model.

    Two EBITDA calibers are recomputed from absolute line items so neither
    rides on a provider's opaque (and, for the latest quarter, sometimes
    D&A-less) ebitda field. Operating is the primary EV/EBITDA numerator;
    reported is the street cross-check. Falls back to the provider-supplied
    ebitda only when components are absent (e.g. yfinance-sourced snapshots).

    Raises ValueError for missing critical fields (revenue, market_cap).
    Non-critical missing fields (debt, cash, D&A) are defaulted and recorded
    in FinancialData.warnings so the caller can surface them to the user.
    """
    ticker = fin.ticker

    revenue = fin.revenue
    market_cap = fin.market_cap

    # Banks have no COGS, so gross margin is undefined. FMP forces its non-bank
    # template (~60% phantom) and yfinance returns 0% — suppress to None at this
    # symmetric chokepoint so neither provider's meaningless value reaches the
    # report (Mode A/B parity; the FMP provider also suppresses at source).
    bank = is_bank(industry=fin.industry, sector=fin.sector)
    gross_margin = None if bank else fin.gross_margin

    # Two EBITDA calibers, recomputed from absolute line items so neither
    # rides on a provider's opaque (and, for the latest quarter, sometimes
    # D&A-less) ebitda field. Operating is the primary EV/EBITDA numerator;
    # reported is the street cross-check. Falls back to the provider-supplied
    # ebitda only when components are absent (e.g. yfinance-sourced snapshots).
    ebitda_operating = calculate_ebitda_operating(
        fin.operating_income, fin.depreciation_amortization
    )
    if ebitda_operating is None:
        ebitda_operating = fin.ebitda
    ebitda_reported = calculate_ebitda_reported(
        fin.net_income,
        fin.income_tax_expense,
        fin.interest_expense,
        fin.depreciation_amortization,
    )
    ebitda = ebitda_operating

    if not revenue:
        raise ValueError(f"Missing or zero revenue for {ticker}")
    if not market_cap:
        raise ValueError(f"Missing or zero market_cap for {ticker}")

    warnings: list[str] = []
    field_warnings: dict[str, list[str]] = {}

    raw_debt = fin.total_debt
    raw_cash = fin.total_cash
    total_debt = raw_debt if raw_debt is not None else 0
    total_cash = raw_cash if raw_cash is not None else 0

    # --- current_price: the authoritative market basis (live quote) ---
    current_price = price.current_price or fin.current_price
    if not current_price or current_price <= 0:
        raise ValueError(
            f"Could not determine current_price for {ticker}. "
            "Ensure the price provider is configured and returning data."
        )

    # --- shares_outstanding: price-consistent count for per-share valuation ---
    # Every per-share figure downstream (DCF implied price via seed_dcf_inputs,
    # comps EPS, LBO/EV-EBITDA/P-FCF targets) divides an equity/enterprise TOTAL
    # by this count and compares the result to current_price — so the count MUST
    # be on the SAME basis as the price, i.e. market_cap / current_price. A
    # reported filing count that covers only ONE class of a multi-class issuer
    # (yfinance .info reports single-class for GOOG/META/FOX) would put total
    # net_income over a single-class denominator and overstate EPS ~class-ratio×.
    # FMP already reports the all-class mc/price count, so this only corrects the
    # degraded yfinance-only path — making it symmetric with FMP (no Mode A/B gap).
    implied_shares = market_cap / current_price
    reported_shares = fin.shares_outstanding
    if reported_shares is None or reported_shares <= 0:
        shares = implied_shares
        warnings.append(
            f"shares_outstanding missing or invalid from {fin.provenance.provider} "
            f"for {ticker} — derived as market_cap/price ({shares:,.0f}). "
            "Per-share metrics (EPS, P/E) may be approximate."
        )
        field_warnings.setdefault("pe", []).append(FIELD_WARN_SHARES_DERIVED)
    elif abs(reported_shares - implied_shares) / implied_shares > _SHARES_PRICE_CONSISTENCY_TOL:
        shares = implied_shares
        warnings.append(
            f"shares_outstanding from {fin.provenance.provider} for {ticker} "
            f"({reported_shares:,.0f}) diverges "
            f"{abs(reported_shares - implied_shares) / implied_shares:.0%} from "
            f"market_cap/price ({implied_shares:,.0f}) — likely a single share class "
            "of a multi-class issuer or an ADR ratio. Using the price-consistent "
            "count so per-share metrics (EPS, P/E, implied price) stay on the "
            "market's basis."
        )
        field_warnings.setdefault("pe", []).append(FIELD_WARN_SHARES_DERIVED)
    else:
        shares = reported_shares

    # --- book value per share on the SAME price-consistent basis as `shares`/EPS ---
    # The provider divided book equity by `reported_shares`; when that count is off
    # the quoted price's basis (BP's /shares-float ~437M vs the ~2.62B ADR count) the
    # per-ordinary bvps ($128) is the ADR ratio × the per-ADR figure ($21). Rescale
    # it in lockstep with `shares` above (same tol, same market_cap/current_price) so
    # the displayed bvps and the comps_pb anchor (peer median P/B × bvps) sit on the
    # per-ADR price basis. No-op / byte-identical for US issuers and price-consistent
    # ADRs (SHEL/HSBC/TSM). `market_cap` is still the raw provider cap here (marked to
    # the live price just below), matching `implied_shares` computed above.
    bvps_price_consistent, bvps_note = reconcile_book_value_to_price_basis(
        fin.book_value_per_share, reported_shares, market_cap, current_price
    )
    if bvps_note is not None:
        warnings.append(bvps_note)

    # --- mark market_cap to the live price basis ---
    # The provider market_cap rides a cached profile snapshot that can lag
    # current_price (FMP profile mktCap froze at the prior close while the quote
    # moved intraday), leaving market_cap / P/E / EV-EBITDA ~the day's move below
    # the live price shown right beside them. `shares` is already forced onto
    # current_price's basis above, so shares × current_price is the coherent live
    # cap, and EV / P/E rebuild from it below. When `shares` was DERIVED (degraded
    # or single-class fallback = market_cap/current_price) this recovers the
    # provider cap unchanged — a no-op on those paths (regression 2026-06-09:
    # KO/TSM +0.00%, AAPL +1.84%, MU +9.95% on a +10% day; shares × price == FMP
    # live marketCap to 0.00% across the basket).
    mc_reported = market_cap
    market_cap = shares * current_price
    mc_ratio = market_cap / mc_reported if mc_reported else 1.0

    # --- N15: consistent EV handling ---
    # Only compute EV when both total_debt and total_cash are available.
    # Matches prompts.py behavior: no defaulting missing components to 0.
    ev: float | None = None
    ev_ebitda: float | None = None
    ev_ebitda_reported: float | None = None
    ev_revenue: float | None = None

    if raw_debt is not None and raw_cash is not None:
        ev = calculate_ev(
            market_cap,
            total_debt,
            total_cash,
            fin.preferred_stock or 0.0,
            fin.noncontrolling_interest or 0.0,
        )
        ev_ebitda = ev / ebitda_operating if (ebitda_operating and ebitda_operating > 0) else None
        ev_ebitda_reported = (
            ev / ebitda_reported if (ebitda_reported and ebitda_reported > 0) else None
        )
        ev_revenue = ev / revenue if revenue > 0 else None
    else:
        missing_ev_parts = []
        if raw_debt is None:
            missing_ev_parts.append("total_debt")
        if raw_cash is None:
            missing_ev_parts.append("total_cash")
        warnings.append(
            f"{', '.join(missing_ev_parts)} not available from provider — "
            "EV and EV-based multiples (EV/EBITDA, EV/Revenue) cannot be computed"
        )
        field_warnings.setdefault("ev_ebitda", []).append(FIELD_WARN_EV_MISSING_NET_DEBT)

    # Balance-sheet financials (banks / insurers): deposits / float / reserves are
    # operating raw material, not capital structure, and there is no clean above-the-line
    # EBITDA — so enterprise value and EVERY EV-based multiple are category errors
    # (``audit.sector_sign`` flags exactly ``enterprise_value`` + ``ev_ebitda`` for these
    # issuers). Enforce the invariant HERE, at the single canonical FinancialData producer,
    # so NO consumer surface can leak it: the /financials snapshot tile, the historical-bands
    # current override, coverage rows, and the report all read this object. This is the
    # STRUCTURAL gate for the recurring "a new surface forgot to suppress bank EV/EBITDA"
    # family (the live /financials + /historical-bands endpoints were leak surfaces 5 & 6 on
    # 2026-06-26; comps/report suppressed per-path since 06-24). sector_sign is now a pure
    # backstop. Bank-applicable metrics (P/E, P/B, market cap) are untouched — only the
    # EV-based fields are nulled. is_balance_sheet_financial (NOT is_bank) is the wider
    # cash-flow-suppression boundary, matching the comps builder + aggregator.
    if is_balance_sheet_financial(industry=fin.industry, sector=fin.sector):
        ev = None
        ev_ebitda = None
        ev_ebitda_reported = None
        ev_revenue = None

    # 52w high/low from the canonical (windowed to trailing 52 weeks, intraday
    # high/low when present, close fallback otherwise).
    high_52w = price.fifty_two_week_high()
    low_52w = price.fifty_two_week_low()

    # P/E marked to the live cap: scale the provider's ratio (= mc_reported /
    # net_income) by the mark-to-live adjustment so it tracks the live cap while
    # preserving the provider's None semantics (ADR / cross-currency → None).
    pe_ratio = fin.pe_ratio * mc_ratio if fin.pe_ratio is not None else None

    # Carry any warnings that arrived on the canonical objects (e.g. cross-validate
    # discrepancies forwarded from raw fetch).
    for w in fin.warnings:
        if w not in warnings:
            warnings.append(w)
    for w in price.warnings:
        if w not in warnings:
            warnings.append(w)

    return FinancialData(
        ticker=ticker,
        company_name=fin.company_name or "",
        # As-of of THIS snapshot's headline = the session the displayed
        # current_price belongs to (PRICE canonical's semantic ``as_of``), NOT the
        # FINANCIALS fetch time. The two canonicals have independent TTLs, so the
        # FINANCIALS fetch (which embeds a staler price) can lag the dedicated
        # PRICE canonical by a full session; stamping fin.fetched_at here mislabels
        # the "As of" pill against the fresh price the market block / 13 chapters
        # actually render (AAPL 2026-07-02: pill said 06-30 16:14 while the
        # headline was 07-01's $294.38). The financials' own period is separately
        # carried in ``fiscal_period_end`` / the "TTM 截至 X" label, so no fidelity
        # is lost. Contract: the freshness pill reads the price ``as_of``
        # (normalize/contracts Provenance docstring).
        timestamp=price.provenance.as_of,
        fiscal_period_end=fin.period_end,
        # Carry the TTM constituent quarter-ends so audit.ttm_period can assert the
        # four quarters don't overlap/gap (numeric-audit family-4). Empty on the
        # yfinance / annual paths → the verifier abstains.
        ttm_quarter_ends=fin.ttm_quarter_ends,
        income=IncomeStatement(
            revenue=revenue,
            # None ≠ 0: propagate a missing figure as None so the derived metric
            # is withheld (data unavailable) rather than fabricated as a real 0.
            ebitda=ebitda,
            net_income=fin.net_income,
            # Withhold an economically-impossible margin (>100% / <-500%) so a broken
            # provider figure (UL: FMP grossProfit ≥ revenue) shows N/A instead of
            # crashing the IncomeStatement le bound or printing a fabricated 100%.
            gross_margin=_sanitize_margin(gross_margin, label="gross_margin", warnings=warnings),
            operating_margin=_sanitize_margin(
                fin.operating_margin, label="operating_margin", warnings=warnings
            ),
            operating_income=fin.operating_income,
            depreciation_amortization=fin.depreciation_amortization,
            capital_expenditure=fin.capital_expenditure,
            rd_expense=fin.rd_expense,
            sga_expense=fin.sga_expense,
            interest_expense=fin.interest_expense,
            income_tax_expense=fin.income_tax_expense,
        ),
        balance=BalanceSheet(
            # Preserve None (not reported) into FinancialData — the local
            # total_debt/total_cash are 0-coerced only for the guarded EV calc
            # above; the stored balance must not fabricate a zero (N15/#10).
            total_debt=raw_debt,
            total_cash=raw_cash,
            # EV-bridge completeness (numeric-audit family 3): preferred + NCI are
            # folded into calculate_ev above when reported; carried here so
            # audit.ev_bridge can flag an UNREPORTED (None) one. None ≠ 0.
            preferred_stock=fin.preferred_stock,
            noncontrolling_interest=fin.noncontrolling_interest,
        ),
        market=MarketData(
            market_cap=market_cap,
            shares_outstanding=shares,
            current_price=current_price,
            pe_ratio=pe_ratio,
            price_52w_high=high_52w,
            price_52w_low=low_52w,
            # Same canonical PRICE object the 52w high/low above derive from —
            # single source, self-consistent (thesis-prompt momentum context).
            trailing_1y_return_pct=price.trailing_1y_return_pct(),
            industry=fin.industry,
            sector=fin.sector,
            country=fin.country,
            is_adr=fin.is_adr,
            beta=fin.beta,
        ),
        valuation=ValuationMetrics(
            enterprise_value=ev,
            ebitda_operating=ebitda_operating,
            ebitda_reported=ebitda_reported,
            ev_ebitda=ev_ebitda,
            ev_ebitda_reported=ev_ebitda_reported,
            ev_revenue=ev_revenue,
            # Per-ADR (price-consistent) per-share book value, carried for the cyclical
            # comps P/B method (the target's pb_ratio is derived in
            # build_xbrl_aligned_company from this bvps × the reconciled shares above,
            # so it stays self-consistent = market_cap/book_equity).
            book_value_per_share=bvps_price_consistent,
        ),
        # Carry the currency tags so a foreign target (TWD financials, USD
        # market_cap) can be FX-normalized in build_xbrl_aligned_company before
        # comps multiples — without these the target defaulted to USD/USD and
        # core_pe collapsed for ADRs (BUG-018).
        reporting_currency=fin.reporting_currency,
        quote_currency=fin.quote_currency,
        data_source=fin.provenance.provider,
        provenance=DataProvenance(
            provider=fin.provenance.provider,
            as_of=fin.period_end,
            period_basis=fin.period_basis,
            pe_ttm_lag_quarters=fin.pe_ttm_lag_quarters,
            # Combine financials degraded flags (ttm_lag) with the price
            # feed's (close_only) since the snapshot shows both 52w (price)
            # and P/E (financials) numbers.
            degraded=list(dict.fromkeys([*fin.provenance.degraded, *price.provenance.degraded])),
        ),
        warnings=warnings,
        field_warnings=field_warnings,
    )


def extract_company_financials(fin: NormalizedFinancials) -> CompanyFinancials:
    """Project NormalizedFinancials into CompanyFinancials for a peer comps row.

    Runs the SAME EBITDA-caliber logic as the target path
    (``extract_financial_data``) so the peer EV/EBITDA numerator matches the
    target's instead of mixing calibers:

    - **EBITDA = operating caliber (EBIT + D&A)** recomputed from line items,
      falling back to the provider's reported ``ebitda`` only when operating
      components are absent. Previously the peer used the raw provider
      ``ebitda`` (reported caliber: NI+tax+interest+D&A) while the target used
      operating — for cash-rich peers the two differ materially and the table
      compared apples to oranges.
    - **total_debt / total_cash stay None when the provider omits them** so
      ``calculate_multiples`` withholds EV instead of fabricating EV=market_cap
      and poisoning the median. Previously ``or 0`` silently assumed zero net debt.

    ``reporting_currency`` carries the provider's IS/BS currency tag (ISO 4217,
    taken at face value — see normalize.currency) so the downstream FX step
    converts before EV/EBITDA is computed. Raises ValueError for missing
    revenue/market_cap so the caller drops the peer rather than comparing zeros.
    """
    ticker = fin.ticker

    revenue = fin.revenue
    market_cap = fin.market_cap
    if not revenue:
        raise ValueError(f"Missing or zero revenue for peer {ticker}")
    if not market_cap:
        raise ValueError(f"Missing or zero market_cap for peer {ticker}")

    # Operating EBITDA (EBIT + D&A) is the canonical EV/EBITDA numerator since
    # EV already nets out cash. Reported fallback only when components missing —
    # identical treatment to the target so neither side fabricates a caliber.
    ebitda_operating = calculate_ebitda_operating(
        fin.operating_income, fin.depreciation_amortization
    )
    if ebitda_operating is None:
        ebitda_operating = fin.ebitda

    # P/B = market_cap / book equity (book equity = bvps × shares). Computed ONLY
    # for single-currency issuers (reporting == quote): market_cap is quote-ccy and
    # book equity is reporting-ccy, so a TWD/USD ADR would mix units (the same leg
    # forward_pe / pe_ratio gate on). US memory/storage peers (MU/WDC/STX/SNDK) are
    # all USD/USD → clean; a foreign memory peer leaves pb_ratio None and falls back
    # to P/E in the comps median rather than printing a cross-currency P/B. Withheld
    # (None) on non-positive book equity — a negative-equity P/B is meaningless.
    bvps = fin.book_value_per_share
    pb_ratio: float | None = None
    single_currency = fin.reporting_currency == fin.quote_currency
    if (
        single_currency
        and bvps is not None
        and bvps > 0
        and fin.shares_outstanding is not None
        and fin.shares_outstanding > 0
        and market_cap > 0
    ):
        pb_ratio = market_cap / (bvps * fin.shares_outstanding)

    # pb_ratio above stays on the self-consistent RAW pair (bvps × shares =
    # book_equity, so pb = market_cap/book_equity is byte-identical and correct even
    # when the provider count is off the price basis). The CARRIED book value is
    # separately re-expressed on the per-ADR price basis so a peer's displayed bvps is
    # coherent with its price (no-op for US / price-consistent peers). Only the target
    # row's bvps feeds comps_pb as an anchor, but keeping the peer's coherent avoids a
    # latent per-ordinary figure leaking into any future consumer.
    bvps_anchor, _bvps_note = reconcile_book_value_to_price_basis(
        bvps, fin.shares_outstanding, market_cap, fin.current_price
    )

    return CompanyFinancials(
        ticker=ticker,
        name=fin.company_name,
        revenue=revenue,
        # None ≠ 0: propagate a missing figure as None so the affected multiple is
        # withheld (data unavailable) rather than computed against a fabricated 0.
        ebitda=ebitda_operating,
        net_income=fin.net_income,
        market_cap=market_cap,
        total_debt=fin.total_debt,
        total_cash=fin.total_cash,
        # EV-bridge completeness: carry preferred + NCI so calculate_multiples folds
        # them into this company's EV (symmetric with the target extract path).
        preferred_stock=fin.preferred_stock,
        noncontrolling_interest=fin.noncontrolling_interest,
        # Banks have no COGS — suppress the meaningless gross margin so a bank
        # peer row doesn't show ~60% (FMP) / 0% (yfinance). Symmetric with the
        # target path (extract_financial_data) and the FMP provider source fix.
        # A >100% (impossible) margin is withheld too so a broken provider figure
        # doesn't print a fabricated 100% in the comps table (peer path has no
        # warnings channel — silent withhold, mirroring how peers drop other fields).
        gross_margin=None
        if is_bank(industry=fin.industry, sector=fin.sector)
        else _sanitize_margin(fin.gross_margin, label="gross_margin"),
        operating_margin=_sanitize_margin(fin.operating_margin, label="operating_margin"),
        # Period-consistent EBIT for NOPAT core P/E (BUG-017) — preferred over
        # operating_margin × revenue once revenue may be XBRL-reconciled.
        operating_income=fin.operating_income,
        pe_ratio=fin.pe_ratio,
        # P/B (cyclical comps multiple) + the per-ADR per-share book value. bvps is
        # reporting-ccy (FX-scaled with the other reporting items in
        # normalize_company_to_usd); pb_ratio is computed single-currency above from
        # the raw pair so it's already dimensionless and unaffected by the anchor's
        # per-ADR rescale.
        book_value_per_share=bvps_anchor,
        pb_ratio=pb_ratio,
        income_tax_expense=fin.income_tax_expense,
        reporting_currency=fin.reporting_currency,
        quote_currency=fin.quote_currency,
    )


async def normalize_peer_to_usd(
    company: CompanyFinancials, *, fmp_api_key: str | None = None
) -> CompanyFinancials:
    """Convert a peer's IS/BS items (and market_cap if quoted in non-USD) to
    canonical USD using today's spot FX. No-op fast path when both currency
    tags are already USD — the common case for US peers.

    ``fmp_api_key`` is forwarded to the FX layer as a fallback source so a
    yfinance rate-limit storm doesn't drop an otherwise-fetchable foreign peer.

    Lives here (a compute coordinator, alongside ``extract_company_financials``)
    rather than in any one pipeline so BOTH the comps pipeline AND the
    ``analyze competitors`` path normalize peers through the identical FX recipe
    — there is exactly one comps normalization path, never two (BUG-016).
    """
    if company.reporting_currency == "USD" and company.quote_currency == "USD":
        return company
    # Lazy: fx pulls yfinance; kept off the cold-start import path (test_cold_import).
    from finrobot.engine.data.providers.fx import fetch_fx_rate_to_usd

    reporting_rate = (
        1.0
        if company.reporting_currency == "USD"
        else await fetch_fx_rate_to_usd(company.reporting_currency, fmp_api_key=fmp_api_key)
    )
    if company.quote_currency == "USD":
        quote_rate = 1.0
    elif company.quote_currency == company.reporting_currency:
        # Local listing (e.g. 2330.TW): both tags equal, reuse the rate.
        quote_rate = reporting_rate
    else:
        quote_rate = await fetch_fx_rate_to_usd(company.quote_currency, fmp_api_key=fmp_api_key)
    return normalize_company_to_usd(company, reporting_rate, quote_rate)


async def normalize_financials_to_usd(
    financials: FinancialData, *, fmp_api_key: str | None = None
) -> FinancialData:
    """Convert a ticker's IS/BS items (and market_cap/price if quoted non-USD) to
    canonical USD using today's spot FX. No-op fast path when both currency tags
    are already USD — the common US-issuer case.

    The ``FinancialData`` sibling of :func:`normalize_peer_to_usd`: the single
    async fetch-and-normalize recipe every absolute-valuation seed caller (DCF /
    DDM / IC-memo pipelines + the dcf-seed route) runs BEFORE
    ``seed_dcf_inputs`` / ``seed_ddm_inputs``, so a foreign issuer's TWD
    revenue/net_income/debt never mixes with its USD market_cap (BUG-073). The
    seed leaves stay pure/sync; the async FX read happens here.

    ``fmp_api_key`` is forwarded to the FX layer as a fallback source so a
    yfinance rate-limit storm doesn't strand an otherwise-fetchable foreign rate.
    """
    if financials.reporting_currency == "USD" and financials.quote_currency == "USD":
        return financials
    # Lazy: fx pulls yfinance; kept off the cold-start import path (test_cold_import).
    from finrobot.engine.data.providers.fx import fetch_fx_rate_to_usd

    reporting_rate = (
        1.0
        if financials.reporting_currency == "USD"
        else await fetch_fx_rate_to_usd(financials.reporting_currency, fmp_api_key=fmp_api_key)
    )
    if financials.quote_currency == "USD":
        quote_rate = 1.0
    elif financials.quote_currency == financials.reporting_currency:
        # Local listing (e.g. 2330.TW): both tags equal, reuse the rate.
        quote_rate = reporting_rate
    else:
        quote_rate = await fetch_fx_rate_to_usd(financials.quote_currency, fmp_api_key=fmp_api_key)
    return normalize_financialdata_to_usd(financials, reporting_rate, quote_rate)


def extract_price_history(price: NormalizedPrice) -> PriceHistory:
    """Project NormalizedPrice into PriceHistory.

    Reads typed bars (``price.bars``) instead of raw dict ``data.get()``.
    avg_price = mean of bar closes; data_points = number of bars;
    52w high/low from the canonical derived methods (intraday high/low
    with close fallback, window already trimmed to trailing 52 weeks).
    """
    closes = [b.close for b in price.bars]
    avg = sum(closes) / len(closes) if closes else 0.0
    high_52w = price.fifty_two_week_high()
    low_52w = price.fifty_two_week_low()
    return PriceHistory(
        ticker=price.ticker,
        period="1y",
        data_points=len(price.bars),
        current_price=price.current_price,
        high_52w=high_52w if high_52w is not None else 0.0,
        low_52w=low_52w if low_52w is not None else 0.0,
        avg_price=avg,
    )
