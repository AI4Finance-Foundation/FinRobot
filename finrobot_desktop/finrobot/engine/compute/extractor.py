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
    DataProvenance,
    FinancialData,
    IncomeStatement,
    BalanceSheet,
    MarketData,
    ValuationMetrics,
    PriceHistory,
    CompanyFinancials,
)
from finrobot.engine.compute.multiples import (
    calculate_ebitda_operating,
    calculate_ebitda_reported,
    calculate_ev,
)


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

    raw_debt = fin.total_debt
    raw_cash = fin.total_cash
    total_debt = raw_debt if raw_debt is not None else 0
    total_cash = raw_cash if raw_cash is not None else 0

    # --- N15: consistent EV handling ---
    # Only compute EV when both total_debt and total_cash are available.
    # Matches prompts.py behavior: no defaulting missing components to 0.
    ev: float | None = None
    ev_ebitda: float | None = None
    ev_ebitda_reported: float | None = None
    ev_revenue: float | None = None

    if raw_debt is not None and raw_cash is not None:
        ev = calculate_ev(market_cap, total_debt, total_cash)
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

    # 52w high/low from the canonical (windowed to trailing 52 weeks, intraday
    # high/low when present, close fallback otherwise).
    high_52w = price.fifty_two_week_high()
    low_52w = price.fifty_two_week_low()

    current_price = price.current_price or fin.current_price
    if not current_price or current_price <= 0:
        raise ValueError(
            f"Could not determine current_price for {ticker}. "
            "Ensure the price provider is configured and returning data."
        )

    # --- shares_outstanding: refuse silent fallback to 1 ---
    shares = fin.shares_outstanding
    if shares is None or shares <= 0:
        shares = market_cap / current_price
        warnings.append(
            f"shares_outstanding missing or invalid from {fin.provenance.provider} "
            f"for {ticker} — derived as market_cap/price ({shares:,.0f}). "
            "Per-share metrics (EPS, P/E) may be approximate."
        )

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
        timestamp=fin.provenance.fetched_at,
        fiscal_period_end=fin.period_end,
        income=IncomeStatement(
            revenue=revenue,
            ebitda=ebitda or 0,
            net_income=fin.net_income or 0,
            gross_margin=fin.gross_margin or 0,
            operating_margin=fin.operating_margin or 0,
            depreciation_amortization=fin.depreciation_amortization,
            rd_expense=fin.rd_expense,
            sga_expense=fin.sga_expense,
            interest_expense=fin.interest_expense,
            income_tax_expense=fin.income_tax_expense,
        ),
        balance=BalanceSheet(
            total_debt=total_debt,
            total_cash=total_cash,
        ),
        market=MarketData(
            market_cap=market_cap,
            shares_outstanding=shares,
            current_price=current_price,
            pe_ratio=fin.pe_ratio,
            price_52w_high=high_52w,
            price_52w_low=low_52w,
            industry=fin.industry,
            sector=fin.sector,
            beta=fin.beta,
        ),
        valuation=ValuationMetrics(
            enterprise_value=ev,
            ebitda_operating=ebitda_operating,
            ebitda_reported=ebitda_reported,
            ev_ebitda=ev_ebitda,
            ev_ebitda_reported=ev_ebitda_reported,
            ev_revenue=ev_revenue,
        ),
        data_source=fin.provenance.provider,
        provenance=DataProvenance(
            provider=fin.provenance.provider,
            as_of=fin.period_end,
            period_basis=fin.period_basis,
            pe_ttm_lag_quarters=fin.pe_ttm_lag_quarters,
            # Combine financials degraded flags (ttm_lag, ccy_inferred) with the
            # price feed's (close_only) since the snapshot shows both 52w (price)
            # and P/E (financials) numbers.
            degraded=list(dict.fromkeys([*fin.provenance.degraded, *price.provenance.degraded])),
        ),
        warnings=warnings,
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

    ``reporting_currency`` carries the resolved IS/BS currency (ISO 4217); the
    country-based override corrects yfinance ADR mis-tags so the downstream FX
    step converts before EV/EBITDA is computed. Raises ValueError for missing
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

    return CompanyFinancials(
        ticker=ticker,
        name=fin.company_name,
        revenue=revenue,
        ebitda=ebitda_operating or 0,
        net_income=fin.net_income or 0,
        market_cap=market_cap,
        total_debt=fin.total_debt,
        total_cash=fin.total_cash,
        gross_margin=fin.gross_margin or 0,
        operating_margin=fin.operating_margin or 0,
        pe_ratio=fin.pe_ratio,
        reporting_currency=fin.reporting_currency,
        quote_currency=fin.quote_currency,
    )


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
