from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from finrobot.engine.primitives.ebitda import calculate_ebitda_operating
from finrobot.engine.primitives.industry import bank_net_revenue, is_bank
from finrobot.engine.data.interface import DataProvider, DataResult, ProviderError
from finrobot.engine.data.types import DataType

_BASE_URL = "https://financialmodelingprep.com/api/v3"
# Some endpoints only exist on FMP's newer "stable" host (different base, not under
# /api/v3). The legacy v3 /earnings-surprises endpoint carries a different schema
# (actualEarningResult/estimatedEarning, no revenue) and silently yields zero usable
# rows; stable/earnings is the one that exposes epsActual/epsEstimated/revenueActual/
# revenueEstimated (live-verified).
_STABLE_BASE = "https://financialmodelingprep.com/stable"
_V4_BASE_URL = "https://financialmodelingprep.com/api/v4"
_SUPPORTED = [
    DataType.FINANCIALS,
    DataType.PRICE,
    DataType.PRICE_RANGE,
    DataType.QUOTE,
    DataType.NEWS,
    DataType.EARNINGS,
    DataType.EARNINGS_TRANSCRIPT,
    DataType.FORWARD_ESTIMATES,
    DataType.PEER_CANDIDATES,
]
_TIMEOUT = 15.0
_MIN_INTERVAL = 0.15  # 6 req/sec — stays within per-minute burst limits on all FMP tiers
# Trailing calendar window for the price-history fetch. 52 weeks + cushion so
# the downstream 52-week high/low window (366 calendar days) is fully covered
# even across weekend/holiday gaps at the boundary.
_PRICE_HISTORY_DAYS = 372


def _adjust_fmp_bar(p: dict[str, Any]) -> dict[str, Any] | None:
    """Convert one FMP /historical-price-full row to a split/dividend-adjusted
    OHLCV bar (the yfinance auto_adjust basis).

    ``adjClose`` becomes the canonical close; O/H/L are scaled by
    ``adjClose/close`` so the whole bar sits on the adjusted basis. Returns None
    when the row lacks the date / close / adjClose needed to adjust (the caller
    drops it rather than emit a half-adjusted bar).
    """
    date = p.get("date")
    close = p.get("close")
    adj_close = p.get("adjClose")
    if date is None or not close or adj_close is None:
        return None
    ratio = adj_close / close

    def _scale(v: Any) -> float | None:
        return float(v) * ratio if v is not None else None

    return {
        "date": date,
        "open": _scale(p.get("open")),
        "high": _scale(p.get("high")),
        "low": _scale(p.get("low")),
        "close": float(adj_close),
        "volume": float(p["volume"]) if p.get("volume") is not None else None,
    }


def _resolve_total_debt(bal: dict[str, Any]) -> float | None:
    """Total debt from a balance-sheet row, defended against FMP quirks.

    ``totalDebt`` is the headline field, but FMP occasionally reports it absent
    while the components are present. Sum ``longTermDebt + shortTermDebt`` as a
    fallback. Preserves the None ≠ 0 contract: a genuinely debt-free filing
    (totalDebt == 0, no components) returns 0, while a *missing* figure
    (totalDebt None, no components) returns None so EV is withheld rather than
    fabricated. Does NOT rescue an all-zero freshest-quarter stub — that is
    backfilled from the annual filing upstream, before this runs.
    """
    td = bal.get("totalDebt")
    if td:
        return float(td)
    lt = bal.get("longTermDebt") or 0
    st = bal.get("shortTermDebt") or 0
    component = lt + st
    if component:
        return float(component)
    return float(td) if td is not None else None


def _derive_pe(
    mkt_cap: float | None,
    net_income: float | None,
    *,
    fin_ccy: str | None,
    quote_ccy: str | None,
    profile_pe: float | None = None,
) -> float | None:
    """P/E from the FMP snapshot, guarded against a cross-currency fabrication.

    ``market_cap`` is quote-currency, ``net_income`` reporting-currency. For ADRs
    these disagree (SAP USD/EUR, TSM USD/TWD, TM USD/JPY) and FMP's ``profile.pe``
    is currently None, so the naive ``mkt_cap / net_income`` fallback shipped a
    dimensionally-mixed P/E into the snapshot (SAP 29.4x, TSM 1.11x, TM 0.06x —
    live probe 2026-06-06). The provider is synchronous with no FX rate, so a
    mixed-currency P/E cannot be made correct here: return None (the snapshot
    renders N/A) and let ``fx_normalize.normalize_financialdata_to_usd`` recompute
    it from same-currency USD inputs for the absolute-valuation paths.

    ``profile_pe`` (FMP's own self-consistent figure) is trusted when present; the
    currency guard only governs the ``mkt_cap / net_income`` fallback.
    """
    if profile_pe:
        return profile_pe
    if not (mkt_cap and net_income and net_income > 0):
        return None
    if fin_ccy != quote_ccy:
        return None
    return mkt_cap / net_income


class FMPProvider(DataProvider):
    """DataProvider backed by Financial Modeling Prep API.

    Provides D&A, R&D, SGA, and other detailed financials that yfinance lacks.
    API key required — get one at https://financialmodelingprep.com/
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._lock = asyncio.Lock()
        self._last_call: float = 0.0
        # Reuse one AsyncClient across requests so TCP/TLS handshakes amortise
        # across the entire FMP session instead of paying ~100 ms per call.
        self._client = httpx.AsyncClient(timeout=_TIMEOUT)

    @property
    def name(self) -> str:
        return "fmp"

    def capabilities(self) -> list[str | DataType]:
        return list(_SUPPORTED)

    @property
    def financials_fields(self) -> set[str]:
        return {
            "revenue",
            "ebitda",
            "net_income",
            "market_cap",
            "shares_outstanding",
            "gross_margin",
            "operating_margin",
            "depreciation_amortization",
            "rd_expense",
            "sga_expense",
            "interest_expense",
            "total_debt",
            "total_cash",
            "pe_ratio",
            "current_price",
        }

    async def fetch(self, ticker: str, data_type: str | DataType, **kwargs: Any) -> DataResult:
        if data_type not in _SUPPORTED:
            raise ProviderError(
                f"data_type '{data_type}' is not supported by FMP. Supported: {_SUPPORTED}"
            )
        if data_type == DataType.PRICE:
            return await self._fetch_price(ticker)
        if data_type == DataType.PRICE_RANGE:
            return await self._fetch_price_range(
                ticker,
                start=kwargs["start"],
                end=kwargs["end"],
                interval=kwargs.get("interval", "1d"),
            )
        if data_type == DataType.QUOTE:
            return await self._fetch_quote(ticker)
        if data_type == DataType.NEWS:
            return await self._fetch_news(ticker)
        if data_type == DataType.EARNINGS:
            return await self._fetch_earnings(ticker)
        if data_type == DataType.EARNINGS_TRANSCRIPT:
            quarter: int | None = kwargs.get("quarter")
            year: int | None = kwargs.get("year")
            limit: int = kwargs.get("limit", 4)
            return await self._fetch_earnings_transcript(
                ticker, quarter=quarter, year=year, limit=limit
            )
        if data_type == DataType.FORWARD_ESTIMATES:
            return await self._fetch_forward_estimates(ticker)
        if data_type == DataType.PEER_CANDIDATES:
            return await self._fetch_peer_candidates(ticker)
        years: int | None = kwargs.get("years")
        warnings: list[str] = []
        cashflow: list[dict[str, Any]] = []
        with self._wrap_errors(ticker, "fetch"):
            if years and years > 1:
                income = self._expect_rows(
                    (
                        await self._get(f"/income-statement/{ticker}", params={"limit": years})
                    ).json(),
                    ticker,
                    "/income-statement",
                    required=True,
                )
                # Pull `years` of annual balance sheets (not limit:1) so each
                # historical year's net debt comes from THAT year's filing. Reusing
                # the latest balance sheet for every year distorted the EV side of
                # the historical EV/EBITDA bands for companies whose debt structure
                # moved across years (BUG-012).
                balance = self._expect_rows(
                    (
                        await self._get(
                            f"/balance-sheet-statement/{ticker}", params={"limit": years}
                        )
                    ).json(),
                    ticker,
                    "/balance-sheet-statement",
                )
                # DCF's FCF = OCF − CapEx − ΔNWC. The income statement carries
                # none of those; without this cash-flow pull FMP-sourced history
                # silently drops every cash-flow input and DCF degrades to
                # industry-median assumptions (see 门一 baseline spec).
                cashflow = self._expect_rows(
                    (
                        await self._get(f"/cash-flow-statement/{ticker}", params={"limit": years})
                    ).json(),
                    ticker,
                    "/cash-flow-statement",
                )
            else:
                income = self._expect_rows(
                    (
                        await self._get(
                            f"/income-statement/{ticker}",
                            params={"period": "quarter", "limit": 4},
                        )
                    ).json(),
                    ticker,
                    "/income-statement",
                    required=True,
                )
                balance = self._expect_rows(
                    (
                        await self._get(
                            f"/balance-sheet-statement/{ticker}",
                            params={"period": "quarter", "limit": 1},
                        )
                    ).json(),
                    ticker,
                    "/balance-sheet-statement",
                )
                # FMP often ships a DEBT STUB on the freshest quarter: totalDebt /
                # longTermDebt / shortTermDebt all 0 until FMP backfills the
                # detail (cash is usually already populated). Trusting that 0
                # fabricates a debt-free balance (EV = market_cap − cash), and
                # because it's a literal 0 — not None — the None≠0 guard
                # downstream can't catch it (real-world hit: SAP Q1'26 stub vs
                # €8.07B annual debt). Debt is a slow-moving stock, so when the
                # quarter is a stub, backfill the debt lines from the latest
                # ANNUAL filing (keep the quarter's fresher cash). See
                # project-memory/已知bug-待修清单.
                # Stub signature: the row is a REAL filing (cash backfilled) but
                # every debt line is 0/None. A wholly-empty row (no cash either)
                # is just missing data — leave it None, don't chase the annual.
                if (
                    balance
                    and balance[0].get("cashAndCashEquivalents")
                    and not any(
                        balance[0].get(f) for f in ("totalDebt", "longTermDebt", "shortTermDebt")
                    )
                ):
                    annual_balance = self._expect_rows(
                        (
                            await self._get(
                                f"/balance-sheet-statement/{ticker}", params={"limit": 1}
                            )
                        ).json(),
                        ticker,
                        "/balance-sheet-statement (annual stub backfill)",
                    )
                    if annual_balance:
                        for f in ("totalDebt", "longTermDebt", "shortTermDebt"):
                            balance[0][f] = annual_balance[0].get(f)
                        warnings.append(
                            f"FMP latest-quarter balance for {ticker} was a debt stub "
                            "(all debt lines 0); total_debt backfilled from the latest "
                            "annual filing (cash kept from the quarter)."
                        )
                # D&A on FMP's income statement is unreliable for the freshest
                # quarter (it arrives 0 until FMP backfills), which silently
                # understates TTM EBITDA. The cash-flow statement carries the
                # real per-quarter D&A — fetch the matching 4 quarters and let
                # _build_ttm_data prefer it. (Same call order as the years>1
                # branch: income → balance → cash-flow → profile.)
                cashflow = self._expect_rows(
                    (
                        await self._get(
                            f"/cash-flow-statement/{ticker}",
                            params={"period": "quarter", "limit": 4},
                        )
                    ).json(),
                    ticker,
                    "/cash-flow-statement",
                )
                if len(income) < 4:
                    warnings.append(
                        f"FMP returned only {len(income)} quarterly income rows for {ticker}; "
                        "TTM metrics use the available rows."
                    )
            profile = self._expect_rows(
                (await self._get(f"/profile/{ticker}")).json(), ticker, "/profile"
            )
            # FMP /profile carries NO share count, which is why shares were
            # historically back-solved as int(mktCap/price) — a tautology that
            # turned price×shares≈mktCap into a fake cross-check. /quote DOES expose
            # a real sharesOutstanding (its mktCap is price×shares, i.e. shares is
            # the source), so prefer it. Best-effort: a /quote 429 / parse failure
            # must not sink the whole financials fetch — fall back to the derived
            # value and warn.
            try:
                quote = (await self._get(f"/quote/{ticker}")).json()
            except (httpx.HTTPError, ProviderError) as exc:
                quote = []
                # Same invariant as _wrap_errors: a raw httpx exception embeds
                # the request URL with ?apikey=<live key>, and this warning
                # flows into DataResult.warnings → shareable artifacts.
                if isinstance(exc, httpx.HTTPStatusError):
                    detail = f"HTTP {exc.response.status_code}"
                elif isinstance(exc, ProviderError):
                    detail = str(exc)
                else:
                    detail = type(exc).__name__
                warnings.append(
                    f"FMP /quote/{ticker} unavailable ({detail}); "
                    "shares_outstanding falls back to mktCap/price"
                )

        bal = balance[0] if balance else {}
        prof = profile[0] if profile else {}
        if is_bank(industry=prof.get("industry"), sector=prof.get("sector")):
            warnings.append(
                f"{ticker} is a bank: revenue is served as total NET revenue "
                "(net interest income + noninterest income = FMP gross revenue − "
                "interest expense), not FMP's gross top line; gross margin is "
                "suppressed (banks have no COGS)."
            )
        quote_row = quote[0] if isinstance(quote, list) and quote else {}
        shares_raw = quote_row.get("sharesOutstanding")
        # Real, independent share count from /quote; None ⇒ the builders derive it.
        quote_shares = (
            int(shares_raw) if isinstance(shares_raw, int | float) and shares_raw > 0 else None
        )
        if quote_shares is None:
            warnings.append(
                f"FMP shares_outstanding for {ticker} derived as int(mktCap/price) — "
                "not an independent figure (/quote had no sharesOutstanding)"
            )

        if years and years > 1 and len(income) > 1:
            # Align cash-flow AND balance-sheet rows to income rows by
            # fiscal-year-end date so each year's OCF/CapEx/ΔNWC and net debt come
            # from the matching period (BUG-012). income is newest-first, so index
            # 0 is the current year — only that row gets the live profile's market
            # data (market_cap/shares/price/PE/beta); older rows carry None for
            # those because the profile is a point-in-time snapshot with no history
            # and would otherwise stamp today's market cap onto every past year
            # (BUG-028).
            cf_by_date = {cf.get("date"): cf for cf in cashflow if isinstance(cf, dict)}
            bal_by_date = {b.get("date"): b for b in balance if isinstance(b, dict)}
            data: dict[str, Any] = {
                "yearly_data": [
                    self._build_single_year_data(
                        inc_i,
                        bal_by_date.get(inc_i.get("date"), {}),
                        prof,
                        cf_by_date.get(inc_i.get("date")),
                        is_current=(idx == 0),
                        quote_shares=quote_shares,
                    )
                    for idx, inc_i in enumerate(income)
                ],
            }
        else:
            data = self._build_ttm_data(income, bal, prof, cashflow, quote_shares)

        return DataResult(
            data=data,
            provider=self.name,
            ticker=ticker,
            data_type=data_type,
            timestamp=datetime.now(tz=timezone.utc),
            warnings=warnings,
        )

    @staticmethod
    def _build_single_year_data(
        inc: dict[str, Any],
        bal: dict[str, Any],
        prof: dict[str, Any],
        cf: dict[str, Any] | None = None,
        *,
        is_current: bool = True,
        quote_shares: int | None = None,
    ) -> dict[str, Any]:
        """Extract a flat dict of normalized financial fields for one year.

        ``is_current`` marks the most-recent period. Market-data fields
        (market_cap / shares / price / PE / beta) come from the live profile,
        which has no history — so for older years (``is_current=False``) they are
        left None instead of stamping today's snapshot onto a past fiscal year
        (BUG-028). Statement fields (income / balance / cash-flow) are always the
        period's own.
        """
        revenue = inc.get("revenue")
        gross_profit = inc.get("grossProfit")
        operating_income = inc.get("operatingIncome")
        net_income = inc.get("netIncome")
        # Banks: FMP forces a non-bank template. ``revenue`` is the GROSS sum
        # (total interest income + noninterest income); the analyst-quoted top
        # line is total NET revenue = revenue − interest expense (ties to SEC
        # RevenuesNetOfInterestExpense — see primitives.industry.bank_net_revenue).
        # And a bank has no COGS, so grossProfit / grossMargin are meaningless
        # (FMP still reports ~60% on its forced template) — suppress to None.
        if is_bank(industry=prof.get("industry"), sector=prof.get("sector")):
            net_revenue = bank_net_revenue(revenue, inc.get("interestExpense"))
            if net_revenue is not None:
                revenue = net_revenue
            gross_profit = None
        # Profile market data is a point-in-time snapshot — only valid for the
        # current period. Historical years get None (no historical price here).
        mkt_cap = prof.get("mktCap") if is_current else None
        price = prof.get("price") if is_current else None
        beta = prof.get("beta") if is_current else None
        # Prefer the real /quote sharesOutstanding (independent source). Only the
        # current period carries live market data, so older years stay None rather
        # than stamping today's share count onto a past fiscal year (BUG-028).
        shares: int | None
        if is_current and quote_shares:
            shares = quote_shares
        else:
            shares = int(mkt_cap / price) if mkt_cap and price else None
        cf = cf or {}
        # FMP reports capitalExpenditure as a negative (cash outflow); the rest
        # of the codebase + the DCF FCF formula expect a positive magnitude.
        capex_raw = cf.get("capitalExpenditure")
        capex = abs(capex_raw) if isinstance(capex_raw, int | float) else None
        # PE = market_cap / net_income (algebraically equivalent to
        # price / EPS where EPS = net_income / shares = net_income * price / mkt_cap).
        # None on historical rows (mkt_cap None: mixing today's cap with a past
        # year's net income, BUG-028) AND on cross-currency ADRs (_derive_pe
        # guard: quote-ccy mkt_cap / reporting-ccy net_income is dimensionally
        # mixed — SAP/TSM/TM, probe 2026-06-06).
        pe_ratio = _derive_pe(
            mkt_cap,
            net_income,
            fin_ccy=inc.get("reportedCurrency"),
            quote_ccy=prof.get("currency"),
        )
        return {
            "revenue": revenue,
            "ebitda": inc.get("ebitda"),
            "net_income": net_income,
            # Absolute income-statement line items — the HistoricalMetrics
            # consumer derives cogs = revenue - gross_profit and recomputes
            # margins itself, so it needs the absolutes, not just the ratios.
            "gross_profit": gross_profit,
            "operating_income": operating_income,
            "gross_margin": gross_profit / revenue if gross_profit and revenue else None,
            "operating_margin": (
                operating_income / revenue if operating_income and revenue else None
            ),
            # Basic EPS — feeds the per-year EpsPeChart and data_processor's
            # net_income/eps share-count derivation. FMP `eps` is basic.
            "eps": inc.get("eps"),
            "depreciation_amortization": inc.get("depreciationAndAmortization"),
            "rd_expense": inc.get("researchAndDevelopmentExpenses"),
            "sga_expense": inc.get("sellingGeneralAndAdministrative"),
            "interest_expense": inc.get("interestExpense"),
            # Full cash-flow statement. FCF trio (OCF/CapEx/ΔNWC) feeds DCF;
            # investing/financing complete the HistoricalMetrics cash-flow
            # contract. capex is abs()'d above; investing/financing keep their
            # native sign (typically negative). FMP misspells the investing
            # field as "Activites" — fall back to the correct spelling too.
            "operating_cash_flow": (
                cf.get("operatingCashFlow") or cf.get("netCashProvidedByOperatingActivities")
            ),
            "investing_cash_flow": cf.get(
                "netCashUsedForInvestingActivites",
                cf.get("netCashUsedForInvestingActivities"),
            ),
            "financing_cash_flow": cf.get(
                "netCashUsedProvidedByFinancingActivities",
                cf.get("netCashProvidedByUsedForFinancingActivities"),
            ),
            "capital_expenditure": capex,
            "change_in_working_capital": cf.get("changeInWorkingCapital"),
            # None ≠ 0: a missing balance-sheet line must stay None so enterprise
            # value is left undefined rather than fabricated (market_cap + 0 - 0).
            # calculate_multiples only computes EV when both are present.
            "total_debt": _resolve_total_debt(bal),
            # EV cash caliber = cash & equivalents + short-term investments
            # (``cashAndShortTermInvestments``). EV nets out near-cash marketable
            # securities, so subtracting cash-only systematically OVERSTATED EV for
            # ST-investment-rich names (SEC-verified: MSFT +$46B, NVDA ~+$40B,
            # TSLA +$28B). yfinance's ``total_cash`` already carries this caliber,
            # so both provider paths now agree (Mode A/B symmetry).
            "total_cash": bal.get("cashAndShortTermInvestments"),
            # EV-bridge completeness (numeric-audit family 3): carry preferred +
            # minority/NCI so the audit can flag an EV that omits them. None ≠ 0.
            "preferred_stock": bal.get("preferredStock"),
            "noncontrolling_interest": bal.get("minorityInterest"),
            "market_cap": mkt_cap,
            "shares_outstanding": shares,
            "pe_ratio": pe_ratio,
            "beta": beta,
            "current_price": price,
            "company_name": prof.get("companyName"),
            "industry": prof.get("industry"),
            "sector": prof.get("sector"),
            # fiscal_year is required by historical_loaders.py for band computation;
            # "date" is fiscal-year-end (YYYY-MM-DD), more precise than calendarYear.
            "fiscal_year": inc.get("date") or inc.get("calendarYear"),
            # Currency tags for cross-border FX normalization — see _build_ttm_data.
            "financial_currency": inc.get("reportedCurrency"),
            "quote_currency": prof.get("currency"),
            "country": prof.get("country"),
        }

    @classmethod
    def _build_ttm_data(
        cls,
        income_rows: list[dict[str, Any]],
        bal: dict[str, Any],
        prof: dict[str, Any],
        cashflow_rows: list[dict[str, Any]] | None = None,
        quote_shares: int | None = None,
    ) -> dict[str, Any]:
        """Build a current snapshot from the latest four quarterly rows."""
        if not income_rows:
            return cls._build_single_year_data({}, bal, prof, quote_shares=quote_shares)

        def _sum(rows: list[dict[str, Any]], key: str) -> float | None:
            values = [float(r[key]) for r in rows if isinstance(r.get(key), int | float)]
            return sum(values) if values else None

        def total(key: str) -> float | None:
            return _sum(income_rows, key)

        latest = income_rows[0]
        revenue = total("revenue")
        gross_profit = total("grossProfit")
        operating_income = total("operatingIncome")
        net_income = total("netIncome")
        # Banks: serve total NET revenue (gross − interest expense, ties to SEC
        # RevenuesNetOfInterestExpense) and suppress the meaningless COGS-based
        # gross profit/margin. See _build_single_year_data + primitives.industry.
        if is_bank(industry=prof.get("industry"), sector=prof.get("sector")):
            net_revenue = bank_net_revenue(revenue, total("interestExpense"))
            if net_revenue is not None:
                revenue = net_revenue
            gross_profit = None
        income_tax_expense = total("incomeTaxExpense")
        # D&A: prefer the cash-flow statement (authoritative; carries the
        # freshest quarter that the income statement leaves at 0), fall back to
        # the income statement only if cash flow is unavailable.
        da = _sum(cashflow_rows, "depreciationAndAmortization") if cashflow_rows else None
        if da is None:
            da = total("depreciationAndAmortization")
        # TTM cash-flow actuals for a real FCF = OCF − CapEx (computed downstream,
        # never hand-estimated by the LLM). FMP reports capitalExpenditure as a
        # negative outflow; store the positive magnitude.
        ttm_ocf = _sum(cashflow_rows, "operatingCashFlow") if cashflow_rows else None
        ttm_capex_raw = _sum(cashflow_rows, "capitalExpenditure") if cashflow_rows else None
        ttm_capex = abs(ttm_capex_raw) if ttm_capex_raw is not None else None
        # EBITDA recomputed on the operating caliber (EBIT + D&A) rather than
        # trusting FMP's `ebitda` field, which inherits the same dropped-D&A
        # contamination for the latest quarter. Fall back to FMP's field only
        # when the components are missing. See primitives.ebitda.calculate_ebitda_operating.
        ebitda = calculate_ebitda_operating(operating_income, da)
        if ebitda is None:
            ebitda = total("ebitda")
        mkt_cap = prof.get("mktCap")
        price = prof.get("price")
        # Prefer the real /quote sharesOutstanding (independent source); the TTM
        # snapshot is always the current period. Fall back to int(mktCap/price)
        # only when /quote was unavailable.
        shares: int | None
        if quote_shares:
            shares = quote_shares
        else:
            shares = int(mkt_cap / price) if mkt_cap and price else None
        pe_ratio = _derive_pe(
            mkt_cap,
            net_income,
            fin_ccy=latest.get("reportedCurrency"),
            quote_ccy=prof.get("currency"),
            profile_pe=prof.get("pe"),
        )
        return {
            "revenue": revenue,
            "ebitda": ebitda,
            "net_income": net_income,
            "operating_income": operating_income,
            "income_tax_expense": income_tax_expense,
            "gross_margin": gross_profit / revenue if gross_profit and revenue else None,
            "operating_margin": (
                operating_income / revenue if operating_income and revenue else None
            ),
            "depreciation_amortization": da,
            "operating_cash_flow": ttm_ocf,
            "capital_expenditure": ttm_capex,
            "rd_expense": total("researchAndDevelopmentExpenses"),
            "sga_expense": total("sellingGeneralAndAdministrative"),
            "interest_expense": total("interestExpense"),
            # None ≠ 0: a missing balance-sheet line must stay None so enterprise
            # value is left undefined rather than fabricated (market_cap + 0 - 0).
            # calculate_multiples only computes EV when both are present.
            "total_debt": _resolve_total_debt(bal),
            # EV cash caliber = cash & equivalents + short-term investments
            # (``cashAndShortTermInvestments``) — see the TTM path above. Keeps the
            # two FMP entry points symmetric and matches yfinance's caliber.
            "total_cash": bal.get("cashAndShortTermInvestments"),
            # EV-bridge completeness (numeric-audit family 3): carry preferred +
            # minority/NCI so the audit can flag an EV that omits them. None ≠ 0.
            "preferred_stock": bal.get("preferredStock"),
            "noncontrolling_interest": bal.get("minorityInterest"),
            "market_cap": mkt_cap,
            "shares_outstanding": shares,
            "pe_ratio": pe_ratio,
            "beta": prof.get("beta"),
            "current_price": price,
            "company_name": prof.get("companyName"),
            "industry": prof.get("industry"),
            "sector": prof.get("sector"),
            "fiscal_year": latest.get("date") or latest.get("calendarYear"),
            "period_basis": "ttm",
            # Quarter-end dates of the quarters summed into this TTM (numeric-audit
            # family-4 non-overlap check). The single-year / historical path
            # (_build_single_year_data) deliberately omits this — there are no
            # constituent quarters to audit there.
            "ttm_quarter_ends": [r.get("date") for r in income_rows if r.get("date")],
            # Currency tags drive cross-border peer FX normalization
            # (fx_normalize). Income-statement items are in reportedCurrency
            # (TWD for TSM, JPY for Toyota); the ADR quote is in profile.currency
            # (USD). Without these, extract_company_financials defaults both to
            # USD and the EV/EBITDA mixes a USD market cap with a local-currency
            # EBITDA — the sub-1x garbage the sanity floor only partly catches.
            "financial_currency": latest.get("reportedCurrency"),
            "quote_currency": prof.get("currency"),
            "country": prof.get("country"),
        }

    async def _fetch_price(self, ticker: str) -> DataResult:
        """Fetch current price + 1y OHLCV history from FMP.

        Returns the same shape as YFinanceProvider._fetch_price so downstream
        consumers (extract_financial_data, MarketDataZone, technical_payload)
        work without provider-specific branches. This is the fallback path
        when yfinance gets rate-limited — without it, every ticker hitting a
        yfinance 429 falls through to the 20h-stale-cache warning the user
        sees in production.
        """
        # Request a trailing-1-year *calendar* range (not timeseries=N, which
        # counts trading days: 365 trading days ≈ 17 months and dragged
        # early-2025 lows into the 52-week low). No serietype=line — that strips
        # OHLC down to close only, and the 52-week high/low need intraday high/low.
        today = datetime.now(tz=timezone.utc).date()
        start = today - timedelta(days=_PRICE_HISTORY_DAYS)
        with self._wrap_errors(ticker, "price fetch"):
            quote_resp = (await self._get(f"/quote/{ticker}")).json()
            hist_resp = (
                await self._get(
                    f"/historical-price-full/{ticker}",
                    params={"from": start.isoformat(), "to": today.isoformat()},
                )
            ).json()

        if not isinstance(quote_resp, list) or not quote_resp:
            raise ProviderError(f"FMP /quote/{ticker} returned no data — ticker may be delisted")
        quote = quote_resp[0]
        current_price = quote.get("price")
        if current_price is None:
            raise ProviderError(f"FMP /quote/{ticker} returned no price field")
        exchange = quote.get("exchange") or quote.get("exchangeShortName")

        # FMP /historical-price-full returns newest-first under "historical";
        # reverse so the price_history list matches yfinance's oldest-first
        # ordering that the rest of the codebase already assumes.
        #
        # Route every bar through _adjust_fmp_bar so price_history sits on the
        # same split/dividend-adjusted basis as _fetch_price_range and yfinance
        # (auto_adjust=True). FMP's raw ``close`` is the nominal quote — a
        # pre-split day carries the unsplit price, so consuming it directly would
        # blow up the downstream 52-week high/low and SMA20/50/200 for any name
        # with a split in the trailing year (a 10:1 split → 52w high ≈ 10× spot).
        # Bars lacking adjClose are dropped rather than emitted half-adjusted.
        raw_hist: list[dict[str, Any]] = []
        if isinstance(hist_resp, dict):
            raw_hist = list(reversed(hist_resp.get("historical", [])))
        price_history = [b for p in raw_hist if (b := _adjust_fmp_bar(p)) is not None]

        return DataResult(
            data={
                "current_price": float(current_price),
                "price_history": price_history,
                "exchange": exchange,
                # Authoritative observation instant of the quote (unix epoch
                # seconds). normalize_price stamps Provenance.as_of from this so a
                # closed-market last-close reads as the real 16:00 ET close, not
                # the bar date's midnight (~20h stale-overstatement otherwise).
                "quote_timestamp": quote.get("timestamp"),
            },
            provider=self.name,
            ticker=ticker,
            data_type=DataType.PRICE,
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def _fetch_price_range(
        self, ticker: str, *, start: str, end: str, interval: str = "1d"
    ) -> DataResult:
        """Arbitrary-range daily OHLCV via /historical-price-full?from=&to=.

        Bars are split/dividend-adjusted to match yfinance ``auto_adjust=True``:
        FMP's raw ``close`` is the nominal quote (a pre-split day carries the
        unsplit price, injecting a discontinuity at the split that would corrupt
        a multi-year backtest), so we adopt ``adjClose`` as the close and scale
        O/H/L by ``adjClose/close``. Verified live 2026-06-02 against the AAPL
        2020-08-31 4:1 split — FMP adjClose matched yfinance auto_adjust close to
        ≤0.02%. ``interval`` other than ``"1d"`` is not supported by this endpoint.
        """
        if interval != "1d":
            raise ProviderError(f"FMP price_range supports only interval='1d', got {interval!r}")
        with self._wrap_errors(ticker, "price range fetch"):
            resp = (
                await self._get(
                    f"/historical-price-full/{ticker}",
                    params={"from": start, "to": end},
                )
            ).json()
        # FMP returns newest-first under "historical"; reverse to oldest-first so
        # the bar list is ascending like every other price path in the codebase.
        raw_hist: list[dict[str, Any]] = []
        if isinstance(resp, dict):
            raw_hist = list(reversed(resp.get("historical", [])))
        if not raw_hist:
            raise ProviderError(
                f"FMP /historical-price-full/{ticker} returned no bars for {start}..{end}"
            )
        bars = [b for p in raw_hist if (b := _adjust_fmp_bar(p)) is not None]
        if not bars:
            raise ProviderError(
                f"FMP /historical-price-full/{ticker} bars lacked adjClose for {start}..{end}"
            )
        return DataResult(
            data={
                "ticker": ticker.upper(),
                "interval": interval,
                "bars": bars,
                "adjusted": True,
                "source_provider": self.name,
            },
            provider=self.name,
            ticker=ticker,
            data_type=DataType.PRICE_RANGE,
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def _fetch_quote(self, ticker: str) -> DataResult:
        """Lightweight current price via /quote/{ticker} — no OHLC history pull.

        The full ``_fetch_price`` also fetches a year of historical bars; QUOTE
        skips that so high-fan-out dashboard quotes stay one cheap call.
        """
        with self._wrap_errors(ticker, "quote fetch"):
            resp = (await self._get(f"/quote/{ticker}")).json()
        if not isinstance(resp, list) or not resp:
            raise ProviderError(f"FMP /quote/{ticker} returned no data — ticker may be delisted")
        price = resp[0].get("price")
        if price is None:
            raise ProviderError(f"FMP /quote/{ticker} returned no price field")
        return DataResult(
            data={"price": float(price)},
            provider=self.name,
            ticker=ticker,
            data_type=DataType.QUOTE,
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def _fetch_news(self, ticker: str) -> DataResult:
        """Fetch recent news articles for a ticker from FMP /stock_news endpoint."""
        with self._wrap_errors(ticker, "news fetch"):
            resp = await self._get("/stock_news", params={"tickers": ticker, "limit": 20})
        # required=True: an empty FMP news list must fall through to the
        # news_aggregator (yfinance headlines + Alpha Vantage sentiment) at the
        # end of the provider chain instead of becoming a zero-news "success"
        # that is indistinguishable from "genuinely no news".
        raw = self._expect_rows(resp.json(), ticker, "/stock_news", required=True)
        news_items = [
            {
                "title": item.get("title", ""),
                "source": item.get("site", ""),
                "published": item.get("publishedDate", ""),
                "url": item.get("url", ""),
            }
            for item in raw
        ]
        return DataResult(
            data={"news_items": news_items},
            provider=self.name,
            ticker=ticker,
            data_type=DataType.NEWS,
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def _fetch_earnings(self, ticker: str) -> DataResult:
        """Fetch earnings surprises from FMP stable/earnings (eps + revenue).

        Uses the ``stable`` host (not /api/v3): only this endpoint exposes
        epsActual/epsEstimated/revenueActual/revenueEstimated. Future quarters are
        returned with epsActual=null and are dropped by the eps None-filter below.
        """
        with self._wrap_errors(ticker, "earnings fetch"):
            resp = await self._get(
                "/earnings",
                params={"symbol": ticker, "limit": 40},
                base=_STABLE_BASE,
            )
        # Type-gate only: an empty earnings history is honest for a fresh IPO
        # and FMP is the sole EARNINGS provider (no chain to fall through to).
        raw = self._expect_rows(resp.json(), ticker, "stable/earnings")
        earnings_history = [
            {
                "date": item.get("date", ""),
                "eps_actual": item.get("epsActual"),
                "eps_estimated": item.get("epsEstimated"),
                "revenue_actual": item.get("revenueActual"),
                "revenue_estimated": item.get("revenueEstimated"),
            }
            for item in raw
            if item.get("epsActual") is not None and item.get("epsEstimated") is not None
        ]
        return DataResult(
            data={"earnings_history": earnings_history},
            provider=self.name,
            ticker=ticker,
            data_type=DataType.EARNINGS,
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def _fetch_earnings_transcript(
        self,
        ticker: str,
        *,
        quarter: int | None = None,
        year: int | None = None,
        limit: int = 4,
    ) -> DataResult:
        """Fetch earnings call transcript(s) from FMP.

        If ``quarter`` and ``year`` are specified, fetches a single transcript.
        Otherwise fetches available transcripts and returns up to ``limit``
        most recent ones.
        """
        with self._wrap_errors(ticker, "earnings transcript fetch"):
            if quarter is not None and year is not None:
                resp = await self._get(
                    f"/earning_call_transcript/{ticker}",
                    params={"quarter": quarter, "year": year},
                )
            else:
                # FMP lists available transcripts at this endpoint without q/y params
                resp = await self._get(f"/earning_call_transcript/{ticker}")
        raw = self._expect_rows(resp.json(), ticker, "/earning_call_transcript")

        transcripts = []
        for item in raw[:limit]:
            transcripts.append(
                {
                    "ticker": ticker.upper(),
                    "quarter": item.get("quarter", 0),
                    "year": item.get("year", 0),
                    "date": item.get("date", ""),
                    "content": item.get("content", ""),
                }
            )

        return DataResult(
            data={"transcripts": transcripts},
            provider=self.name,
            ticker=ticker,
            data_type=DataType.EARNINGS_TRANSCRIPT,
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def _fetch_forward_estimates(self, ticker: str) -> DataResult:
        """Fetch annual analyst consensus estimates from FMP /analyst-estimates.

        Ships the raw rows (farthest-future first, as FMP orders them) under
        ``rows``. FY1 selection and forward-EPS/EBITDA/FCF口径 belong to the
        red-line leaf ``compute.forward_estimates.get_forward_financials`` — this
        provider never derives a forward number itself (spec §6.4.1).
        """
        with self._wrap_errors(ticker, "analyst-estimates fetch"):
            resp = await self._get(f"/analyst-estimates/{ticker}", params={"period": "annual"})
        raw: Any = resp.json()
        rows = raw if isinstance(raw, list) else []
        return DataResult(
            data={"rows": rows},
            provider=self.name,
            ticker=ticker,
            data_type=DataType.FORWARD_ESTIMATES,
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def _fetch_peer_candidates(self, ticker: str) -> DataResult:
        """Fetch the RAW peer-candidate pool for deterministic comps selection.

        Four raw parts, all through the shared ``_get`` rate limiter:
          profile          — target's industry / sector / market cap (the fetch
                             scope parameters for the two screens)
          stock_peers      — FMP v4 cross-recommendation list
          industry_screen  — same-industry symbols (mcap > $1B, top 50)
          sector_screen    — same-sector symbols (mcap > target/20, top 50 —
                             a FETCH-SCOPE floor so we don't pull thousands of
                             rows; the precise band is re-applied by the
                             operator)
          quotes           — market cap + trailing P/E per candidate (batched)

        No selection logic here: tiering / NM-filter / size ranking are the
        pure operator ``compute.operators.peer_screen.screen_peers`` (ADR-0014).
        """
        with self._wrap_errors(ticker, "peer-candidates fetch"):
            profile_raw = (await self._get(f"/profile/{ticker}")).json()
            profile = profile_raw[0] if isinstance(profile_raw, list) and profile_raw else {}
            industry = str(profile.get("industry") or "")
            sector = str(profile.get("sector") or "")
            company_name = str(profile.get("companyName") or "")
            description = str(profile.get("description") or "")
            try:
                target_mcap = float(profile.get("mktCap") or 0.0)
            except (TypeError, ValueError):
                target_mcap = 0.0

            peers_raw = (
                await self._get("/stock_peers", params={"symbol": ticker}, base=_V4_BASE_URL)
            ).json()
            stock_peers: list[str] = []
            if isinstance(peers_raw, list) and peers_raw:
                stock_peers = [str(p) for p in peers_raw[0].get("peersList", [])]

            industry_screen: list[str] = []
            if industry:
                rows = (
                    await self._get(
                        "/stock-screener",
                        params={
                            "industry": industry,
                            "marketCapMoreThan": 1_000_000_000,
                            "limit": 50,
                        },
                    )
                ).json()
                rows = rows if isinstance(rows, list) else []
                industry_screen = [str(r["symbol"]) for r in rows if r.get("symbol")]

            sector_screen: list[str] = []
            if sector and target_mcap > 0:
                rows = (
                    await self._get(
                        "/stock-screener",
                        params={
                            "sector": sector,
                            "marketCapMoreThan": int(target_mcap / 20),
                            "limit": 50,
                        },
                    )
                ).json()
                rows = rows if isinstance(rows, list) else []
                sector_screen = [str(r["symbol"]) for r in rows if r.get("symbol")]

            symbols = sorted(
                {s for s in (*stock_peers, *industry_screen, *sector_screen) if s != ticker}
            )
            profiles: dict[str, dict[str, str]] = {}
            for i in range(0, len(symbols), 40):
                chunk = symbols[i : i + 40]
                rows = (await self._get(f"/profile/{','.join(chunk)}")).json()
                rows = rows if isinstance(rows, list) else []
                for r in rows:
                    sym = r.get("symbol")
                    if not sym:
                        continue
                    profiles[str(sym)] = {
                        "company_name": str(r.get("companyName") or ""),
                        "sector": str(r.get("sector") or ""),
                        "industry": str(r.get("industry") or ""),
                        "description": str(r.get("description") or ""),
                    }

            quotes: dict[str, dict[str, float | None]] = {}
            for i in range(0, len(symbols), 40):
                chunk = symbols[i : i + 40]
                rows = (await self._get(f"/quote/{','.join(chunk)}")).json()
                rows = rows if isinstance(rows, list) else []
                for r in rows:
                    sym = r.get("symbol")
                    if not sym:
                        continue
                    try:
                        mcap = float(r.get("marketCap") or 0.0)
                    except (TypeError, ValueError):
                        mcap = 0.0
                    pe_raw = r.get("pe")
                    try:
                        pe = float(pe_raw) if pe_raw is not None else None
                    except (TypeError, ValueError):
                        pe = None
                    quotes[str(sym)] = {"market_cap": mcap, "pe": pe}

        return DataResult(
            data={
                "profile": {
                    "company_name": company_name,
                    "industry": industry,
                    "sector": sector,
                    "market_cap": target_mcap,
                    "description": description,
                },
                "stock_peers": stock_peers,
                "industry_screen": industry_screen,
                "sector_screen": sector_screen,
                "profiles": profiles,
                "quotes": quotes,
            },
            provider=self.name,
            ticker=ticker,
            data_type=DataType.PEER_CANDIDATES,
            timestamp=datetime.now(tz=timezone.utc),
        )

    @contextmanager
    def _wrap_errors(self, ticker: str, op: str) -> Iterator[None]:
        """Translate httpx + parse errors into ProviderError with a uniform message.

        Used by every public fetch path so each call site only needs to label
        the operation; message formatting and exception fanout live here.
        """
        # Never interpolate the raw httpx exception: its str() includes the
        # request URL, which carries ``?apikey=<live key>``. Use status code +
        # sanitized context only; ``from e`` keeps the full detail for
        # server-side logging without leaking it into the transcript.
        try:
            yield
        except httpx.TimeoutException as e:
            raise ProviderError(f"FMP timeout during {op} for '{ticker}'") from e
        except httpx.HTTPStatusError as e:
            raise ProviderError(
                f"FMP HTTP {e.response.status_code} during {op} for '{ticker}'"
            ) from e
        except (
            httpx.ConnectError,
            httpx.RemoteProtocolError,
            httpx.ReadError,
            httpx.WriteError,
        ) as e:
            raise ProviderError(
                f"FMP network error ({type(e).__name__}) during {op} for '{ticker}'"
            ) from e
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            raise ProviderError(f"FMP {op} failed for '{ticker}' ({type(e).__name__})") from e

    @staticmethod
    def _expect_rows(
        payload: Any, ticker: str, endpoint: str, *, required: bool = False
    ) -> list[dict[str, Any]]:
        """Validate an FMP payload that must be a JSON array.

        FMP signals some errors as HTTP 200 with a dict body
        (``{"Error Message": ...}``). Row-indexing such a body outside
        ``_wrap_errors`` escaped the ProviderError failure chain as
        KeyError/AttributeError — no provider fallback, no stale serve, just
        an opaque 500. ``required=True`` additionally rejects an EMPTY array:
        an empty primary (uncovered/delisted ticker) would otherwise become an
        all-None "success" that blocks the next provider's real data and gets
        cached for the slot's TTL (same invariant as _fetch_price's empty-quote
        raise).
        """
        if not isinstance(payload, list):
            raise ProviderError(f"FMP {endpoint} returned a non-array payload for '{ticker}'")
        if required and not payload:
            raise ProviderError(f"FMP {endpoint} returned no rows for '{ticker}'")
        return payload

    async def _get(
        self, path: str, params: dict[str, Any] | None = None, *, base: str = _BASE_URL
    ) -> httpx.Response:
        """Make authenticated, rate-limited GET request to FMP API.

        Serialises concurrent calls via asyncio.Lock and enforces a minimum
        inter-request interval (_MIN_INTERVAL) to avoid per-minute burst limits.
        ``base`` selects the host (default v3; pass _STABLE_BASE for stable-only
        endpoints like /earnings).
        """
        # Hold the lock ONLY for the rate-limit gate — it paces request STARTS to
        # _MIN_INTERVAL apart. Release it BEFORE the HTTP round-trip so concurrent
        # requests' network I/O overlaps. Holding it across self._client.get()
        # fully serialized all FMP traffic and head-of-line-blocked on any single
        # slow request (effective ~1/(interval+RTT) req/s instead of the intended
        # 6). httpx.AsyncClient is built for concurrent requests, so the GET is
        # safe outside the lock.
        async with self._lock:
            elapsed = time.monotonic() - self._last_call
            if elapsed < _MIN_INTERVAL:
                await asyncio.sleep(_MIN_INTERVAL - elapsed)
            self._last_call = time.monotonic()
        p: dict[str, Any] = {"apikey": self._api_key}
        if params:
            p.update(params)
        resp = await self._client.get(f"{base}{path}", params=p)
        resp.raise_for_status()
        return resp

    async def close(self) -> None:
        """Release the shared httpx client. Called from DataLayer.close()."""
        await self._client.aclose()
