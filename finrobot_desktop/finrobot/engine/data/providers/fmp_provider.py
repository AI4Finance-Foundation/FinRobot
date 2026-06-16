from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from finrobot.engine.primitives.ebitda import calculate_ebitda_operating
from finrobot.engine.primitives.industry import (
    bank_net_revenue,
    bank_operating_income_net_caliber,
    is_bank,
    semiconductor_role,
)
from finrobot.engine.data.interface import (
    DataProvider,
    DataResult,
    ProviderError,
    ProviderPlanError,
    RateLimitedProviderError,
)
from finrobot.engine.data.types import DataType

# FMP closed the whole /api/v3 (and /api/v4) endpoint family to accounts
# registered after 2025-08-31: every legacy call answers 403 "Legacy Endpoint"
# even with a valid key (live-verified 2026-06-11). All endpoints live on the
# /stable host now, with the symbol moved from the path into a ?symbol= query
# parameter and several per-endpoint schema changes (field renames, bare-array
# responses, split-out adjusted-price variants) — see each fetch method.
_BASE_URL = "https://financialmodelingprep.com/stable"
# Key-free 403 body markers for "the key is valid but the plan can't use this
# endpoint" (e.g. news / screener / transcripts outside the subscription tier).
# Mapped to ProviderPlanError so the data layer falls through WITHOUT charging
# the circuit breaker — same vocabulary as routes/settings's probe classifier.
_PLAN_GATE_MARKERS = ("legacy endpoint", "exclusive endpoint", "subscription")
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
# Peer-candidate FETCH-SCOPE band/cap applied before per-symbol enrichment
# (stable has no batch profile/quote, so pe + description cost one request per
# candidate). Must remain a SUPERSET of the operator's widest eligibility band
# — peer_screen.PEER_SCREEN_HIGH_AFFINITY_FLOOR_BAND (1/200x floor) and
# PEER_SCREEN_MCAP_BAND (20x ceiling); a unit test pins scope ⊇ operator so the
# two can't drift apart. The cap bounds worst-case request count; candidates are
# kept nearest-by-size and the operator re-applies precise banding/ranking.
_PEER_SCOPE_FLOOR_DIV = 200.0
_PEER_SCOPE_CAP_MULT = 20.0
_PEER_ENRICH_MAX = 60
# Trailing calendar window for the price-history fetch. 52 weeks + cushion so
# the downstream 52-week high/low window (366 calendar days) is fully covered
# even across weekend/holiday gaps at the boundary.
_PRICE_HISTORY_DAYS = 372


def _adjusted_bar(p: dict[str, Any]) -> dict[str, Any] | None:
    """Convert one /historical-price-eod/dividend-adjusted row to an OHLCV bar
    on the adjusted basis (the yfinance auto_adjust convention).

    The stable endpoint ships the whole bar pre-adjusted (``adjOpen`` /
    ``adjHigh`` / ``adjLow`` / ``adjClose``) — unlike legacy v3, which carried
    a nominal bar plus ``adjClose`` and required scaling O/H/L by
    ``adjClose/close`` ourselves. Returns None when the row lacks the date or
    adjClose (the caller drops it rather than emit a partial bar).
    """
    date = p.get("date")
    adj_close = p.get("adjClose")
    if date is None or adj_close is None:
        return None

    def _f(v: Any) -> float | None:
        return float(v) if isinstance(v, int | float) else None

    return {
        "date": date,
        "open": _f(p.get("adjOpen")),
        "high": _f(p.get("adjHigh")),
        "low": _f(p.get("adjLow")),
        "close": float(adj_close),
        "volume": _f(p.get("volume")),
    }


def _quarter_int(item: dict[str, Any]) -> int | None:
    """Quarter number from a stable transcript row.

    Stable answers ``period: "Q3"`` (string) where legacy v3 answered
    ``quarter: 3`` (int); tolerate both and return None when neither parses,
    so the caller can fall back to the quarter it requested.
    """
    q = item.get("quarter")
    if isinstance(q, int | float) and 1 <= int(q) <= 4:
        return int(q)
    period = str(item.get("period") or "")
    if len(period) == 2 and period[0] in "Qq" and period[1] in "1234":
        return int(period[1])
    return None


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


def _book_value_per_share(bal: dict[str, Any], shares: int | float | None) -> float | None:
    """Book value per COMMON share = (stockholders' equity − preferred) / shares.

    Same None ≠ 0 contract as ``_resolve_total_debt``: None (never 0, never
    fabricated) when equity is unreported or the share count is missing /
    non-positive. The cyclical primary multiple ``comps_pb`` multiplies the peer
    median P/B by this; a missing figure must withhold the method, not invent $0.

    Preferred stock is subtracted to land on common-shareholder equity — matching
    yfinance's ``bookValue`` (Mode A/B symmetry) and stockanalysis.com. Without it
    a bank/REIT with a large preferred slug is overstated (live-probed WFC +10%,
    BAC +9%; invisible for memory names like MU whose preferred is 0).
    ``totalStockholdersEquity`` is already parent-only (FMP carries
    ``minorityInterest`` separately — verified totalEquity == totalStockholders-
    Equity + minorityInterest), so NCI is correctly NOT subtracted. Raw
    reporting-currency: FX normalization (currency.py / fx_normalize.py) and the
    single-currency pb_ratio (extract_company_financials) are downstream.
    """
    equity = bal.get("totalStockholdersEquity")
    if equity is None or not shares or shares <= 0:
        return None
    preferred = bal.get("preferredStock") or 0.0
    return (float(equity) - float(preferred)) / shares


def _derive_pe(
    mkt_cap: float | None,
    net_income: float | None,
    *,
    fin_ccy: str | None,
    quote_ccy: str | None,
) -> float | None:
    """P/E from the FMP snapshot, guarded against a cross-currency fabrication.

    ``market_cap`` is quote-currency, ``net_income`` reporting-currency. For ADRs
    these disagree (SAP USD/EUR, TSM USD/TWD, TM USD/JPY), and a naive
    ``mkt_cap / net_income`` once shipped a dimensionally-mixed P/E into the
    snapshot (SAP 29.4x, TSM 1.11x, TM 0.06x — live probe 2026-06-06). The
    provider is synchronous with no FX rate, so a mixed-currency P/E cannot be
    made correct here: return None (the snapshot renders N/A) and let
    ``fx_normalize.normalize_financialdata_to_usd`` recompute it from
    same-currency USD inputs for the absolute-valuation paths.

    Stable carries no vendor P/E anywhere on this fetch path (legacy profile.pe
    was already None in live v3 payloads, and stable dropped the field — along
    with quote.pe — outright), so the guarded ratio is the only source.
    """
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
                        await self._get(
                            "/income-statement",
                            params={"symbol": ticker, "period": "annual", "limit": years},
                        )
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
                            "/balance-sheet-statement",
                            params={"symbol": ticker, "period": "annual", "limit": years},
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
                        await self._get(
                            "/cash-flow-statement",
                            params={"symbol": ticker, "period": "annual", "limit": years},
                        )
                    ).json(),
                    ticker,
                    "/cash-flow-statement",
                )
            else:
                income = self._expect_rows(
                    (
                        await self._get(
                            "/income-statement",
                            params={"symbol": ticker, "period": "quarter", "limit": 4},
                        )
                    ).json(),
                    ticker,
                    "/income-statement",
                    required=True,
                )
                balance = self._expect_rows(
                    (
                        await self._get(
                            "/balance-sheet-statement",
                            params={"symbol": ticker, "period": "quarter", "limit": 1},
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
                                "/balance-sheet-statement",
                                params={"symbol": ticker, "period": "annual", "limit": 1},
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
                            "/cash-flow-statement",
                            params={"symbol": ticker, "period": "quarter", "limit": 4},
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
                (await self._get("/profile", params={"symbol": ticker})).json(),
                ticker,
                "/profile",
            )
            # Neither stable /profile nor stable /quote carries a share count
            # (legacy v3 /quote's sharesOutstanding is gone), so shares would be
            # back-solved as int(marketCap/price) — a tautology that turns
            # price×shares≈marketCap into a fake cross-check. /shares-float DOES
            # expose a real outstandingShares, so prefer it. Best-effort: a
            # shares-float 429/403 (the free plan symbol-limits it) must not sink
            # the whole financials fetch — fall back to the derived value and warn.
            try:
                shares_rows = (await self._get("/shares-float", params={"symbol": ticker})).json()
            except (httpx.HTTPError, ProviderError) as exc:
                shares_rows = []
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
                    f"FMP /shares-float for {ticker} unavailable ({detail}); "
                    "shares_outstanding falls back to marketCap/price"
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
        shares_row = shares_rows[0] if isinstance(shares_rows, list) and shares_rows else {}
        shares_raw = shares_row.get("outstandingShares")
        # Real, independent share count from /shares-float; None ⇒ the builders
        # derive it.
        quote_shares = (
            int(shares_raw) if isinstance(shares_raw, int | float) and shares_raw > 0 else None
        )
        if quote_shares is None:
            warnings.append(
                f"FMP shares_outstanding for {ticker} derived as int(marketCap/price) — "
                "not an independent figure (/shares-float had no outstandingShares)"
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
        # ``operating_margin`` numerator. For a non-bank it's just operating_income
        # over the gross top line (single caliber). For a bank, once ``revenue``
        # switches to NET revenue below, the numerator must be the net-revenue-
        # caliber operating income so the ratio stays single-caliber (see the
        # bank branch).
        operating_income_for_margin = operating_income
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
                # operating_margin = OI / net_revenue is single-caliber ONLY when
                # FMP's operatingIncome already absorbed interest expense (identity
                # gross − costAndExpenses == OI). bank_operating_income_net_caliber
                # returns OI unchanged when it holds, None when the template is
                # anomalous — abstain rather than emit a mixed-caliber margin.
                operating_income_for_margin = bank_operating_income_net_caliber(
                    inc.get("revenue"), inc.get("costAndExpenses"), operating_income
                )
            gross_profit = None
        # Profile market data is a point-in-time snapshot — only valid for the
        # current period. Historical years get None (no historical price here).
        mkt_cap = prof.get("marketCap") if is_current else None
        price = prof.get("price") if is_current else None
        beta = prof.get("beta") if is_current else None
        # Prefer the real /shares-float outstandingShares (independent source).
        # Only the current period carries live market data, so older years stay
        # None rather than stamping today's share count onto a past fiscal year
        # (BUG-028).
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
        # Historical EV/EBITDA bands compare the CURRENT operating-EBITDA multiple
        # (EBIT + D&A, see _build_ttm_data / current_ev_ebitda) against the per-year
        # band quantiles. FMP's own ``ebitda`` field is the BOTTOM-UP caliber
        # (NetIncome + Tax + Interest + D&A — includes non-operating/interest
        # income), which runs materially ABOVE operating EBITDA for cash-rich names
        # (live-verified TSLA: FMP ebitda 9–18% over OI+D&A per year). Serving the
        # bottom-up caliber here made the band classifier compare two different
        # calibers and biased 贵/合理/便宜. Recompute on the operating caliber so
        # both legs match; fall back to FMP's field only when OI or D&A is missing
        # (faithful, never fabricated). D&A here is the income statement's own —
        # the dropped-freshest-quarter quirk only affects the TTM path, annual
        # filings carry full-year D&A.
        ebitda_operating = calculate_ebitda_operating(
            operating_income, inc.get("depreciationAndAmortization")
        )
        ebitda = ebitda_operating if ebitda_operating is not None else inc.get("ebitda")
        return {
            "revenue": revenue,
            "ebitda": ebitda,
            "net_income": net_income,
            # Absolute income-statement line items — the HistoricalMetrics
            # consumer derives cogs = revenue - gross_profit and recomputes
            # margins itself, so it needs the absolutes, not just the ratios.
            "gross_profit": gross_profit,
            "operating_income": operating_income,
            "gross_margin": gross_profit / revenue if gross_profit and revenue else None,
            # operating_income_for_margin == operating_income for non-banks; for a
            # bank it's the net-revenue-caliber numerator (or None if the FMP
            # template can't be verified single-caliber) so the ratio doesn't mix a
            # gross-template numerator with a net-revenue denominator.
            "operating_margin": (
                operating_income_for_margin / revenue
                if operating_income_for_margin and revenue
                else None
            ),
            # Basic EPS — feeds the per-year EpsPeChart and data_processor's
            # net_income/eps share-count derivation. FMP `eps` is basic.
            "eps": inc.get("eps"),
            "depreciation_amortization": inc.get("depreciationAndAmortization"),
            "rd_expense": inc.get("researchAndDevelopmentExpenses"),
            # Stable's field is the full "...Expenses" name. (Legacy code read
            # "sellingGeneralAndAdministrative", which matches no documented FMP
            # field in either generation — sga_expense was silently None from
            # this provider the whole time; the unit-test fixtures mirrored the
            # same wrong name, so mocks stayed green.)
            "sga_expense": inc.get("sellingGeneralAndAdministrativeExpenses"),
            "interest_expense": inc.get("interestExpense"),
            # Full cash-flow statement. FCF trio (OCF/CapEx/ΔNWC) feeds DCF;
            # investing/financing complete the HistoricalMetrics cash-flow
            # contract. capex is abs()'d above; investing/financing keep their
            # native sign (typically negative). Stable fixed v3's misspelled
            # "...InvestingActivites" — both flows are now "netCashProvidedBy…".
            "operating_cash_flow": (
                cf.get("operatingCashFlow") or cf.get("netCashProvidedByOperatingActivities")
            ),
            "investing_cash_flow": cf.get("netCashProvidedByInvestingActivities"),
            "financing_cash_flow": cf.get("netCashProvidedByFinancingActivities"),
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
            # Book value per common share (cyclical comps_pb anchor). None ≠ 0:
            # withheld when equity or shares is missing; raw reporting-ccy.
            "book_value_per_share": _book_value_per_share(bal, shares),
            "pe_ratio": pe_ratio,
            "beta": beta,
            "current_price": price,
            "company_name": prof.get("companyName"),
            "industry": prof.get("industry"),
            "sector": prof.get("sector"),
            # fiscal_year is required by historical_loaders.py for band computation;
            # "date" is fiscal-year-end (YYYY-MM-DD), more precise than the bare
            # fiscalYear label (stable's rename of v3 calendarYear).
            "fiscal_year": inc.get("date") or inc.get("fiscalYear"),
            # Currency tags for cross-border FX normalization — see _build_ttm_data.
            "financial_currency": inc.get("reportedCurrency"),
            "quote_currency": prof.get("currency"),
            "country": prof.get("country"),
            # FMP /profile structural flag: True for confirmed ADRs (SAP/SHEL/TSM
            # /BABA/NVO/TM). Lets the family-1 foreign_issuer_usd_tags acceptor
            # suppress its review banner for a confirmed-ADR USD/USD snapshot
            # (legitimate USD filing) while still flagging an unverified one.
            "is_adr": prof.get("isAdr"),
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
        # operating_margin numerator — kept on the SAME caliber as ``revenue``
        # below (see the bank branch + _build_single_year_data).
        operating_income_for_margin = operating_income
        # Banks: serve total NET revenue (gross − interest expense, ties to SEC
        # RevenuesNetOfInterestExpense) and suppress the meaningless COGS-based
        # gross profit/margin. See _build_single_year_data + primitives.industry.
        if is_bank(industry=prof.get("industry"), sector=prof.get("sector")):
            net_revenue = bank_net_revenue(revenue, total("interestExpense"))
            if net_revenue is not None:
                revenue = net_revenue
                # Single-caliber operating_margin: OI / net_revenue is valid only
                # when FMP's operatingIncome already absorbed interest expense
                # (TTM identity gross − costAndExpenses == OI). Abstain to None
                # otherwise rather than emit a mixed-caliber margin.
                operating_income_for_margin = bank_operating_income_net_caliber(
                    total("revenue"), total("costAndExpenses"), operating_income
                )
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
        mkt_cap = prof.get("marketCap")
        price = prof.get("price")
        # Prefer the real /shares-float outstandingShares (independent source);
        # the TTM snapshot is always the current period. Fall back to
        # int(marketCap/price) only when /shares-float was unavailable.
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
        )
        return {
            "revenue": revenue,
            "ebitda": ebitda,
            "net_income": net_income,
            "operating_income": operating_income,
            "income_tax_expense": income_tax_expense,
            "gross_margin": gross_profit / revenue if gross_profit and revenue else None,
            # operating_income_for_margin == operating_income for non-banks; for a
            # bank it's the net-revenue-caliber numerator (or None when the FMP
            # template can't be verified single-caliber) — never a gross-template
            # numerator over a net-revenue denominator.
            "operating_margin": (
                operating_income_for_margin / revenue
                if operating_income_for_margin and revenue
                else None
            ),
            "depreciation_amortization": da,
            "operating_cash_flow": ttm_ocf,
            "capital_expenditure": ttm_capex,
            "rd_expense": total("researchAndDevelopmentExpenses"),
            # Full "...Expenses" name — see _build_single_year_data.
            "sga_expense": total("sellingGeneralAndAdministrativeExpenses"),
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
            # Book value per common share (cyclical comps_pb anchor). None ≠ 0:
            # withheld when equity or shares is missing; raw reporting-ccy.
            "book_value_per_share": _book_value_per_share(bal, shares),
            "pe_ratio": pe_ratio,
            "beta": prof.get("beta"),
            "current_price": price,
            "company_name": prof.get("companyName"),
            "industry": prof.get("industry"),
            "sector": prof.get("sector"),
            "fiscal_year": latest.get("date") or latest.get("fiscalYear"),
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
            # FMP /profile structural flag — see _build_single_year_data. Lets the
            # family-1 acceptor suppress its review banner for a confirmed ADR.
            "is_adr": prof.get("isAdr"),
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
        # early-2025 lows into the 52-week low). The dividend-adjusted variant
        # carries the full adjusted OHLC bar — the 52-week high/low need the
        # intraday high/low, so the close-only "light" variant won't do.
        today = datetime.now(tz=timezone.utc).date()
        start = today - timedelta(days=_PRICE_HISTORY_DAYS)
        with self._wrap_errors(ticker, "price fetch"):
            quote_resp = (await self._get("/quote", params={"symbol": ticker})).json()
            hist_resp = (
                await self._get(
                    "/historical-price-eod/dividend-adjusted",
                    params={"symbol": ticker, "from": start.isoformat(), "to": today.isoformat()},
                )
            ).json()

        if not isinstance(quote_resp, list) or not quote_resp:
            raise ProviderError(f"FMP /quote/{ticker} returned no data — ticker may be delisted")
        quote = quote_resp[0]
        current_price = quote.get("price")
        if current_price is None:
            raise ProviderError(f"FMP /quote/{ticker} returned no price field")
        exchange = quote.get("exchange")

        # Stable returns a BARE array (no {symbol, historical: [...]} wrapper).
        # Adjusted basis: the dividend-adjusted variant matches yfinance
        # auto_adjust (split+dividend) — stable's "full" variant carries no
        # adjClose at all, and its nominal close would blow up the downstream
        # 52-week high/low and SMA20/50/200 for any name with a split in the
        # trailing year (a 10:1 split → 52w high ≈ 10× spot). Bars lacking
        # adjClose are dropped rather than emitted partial, and the list is
        # explicitly sorted oldest-first (the codebase-wide bar ordering)
        # instead of trusting the API's undocumented ordering.
        raw_hist: list[Any] = hist_resp if isinstance(hist_resp, list) else []
        price_history = sorted(
            (b for p in raw_hist if isinstance(p, dict) and (b := _adjusted_bar(p)) is not None),
            key=lambda b: str(b["date"]),
        )

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
        """Arbitrary-range daily OHLCV via /historical-price-eod/dividend-adjusted.

        Bars are split/dividend-adjusted to match yfinance ``auto_adjust=True``
        (a nominal pre-split close injects a discontinuity at the split that
        would corrupt a multi-year backtest). The legacy v3 basis was verified
        live 2026-06-02 against the AAPL 2020-08-31 4:1 split (adjClose matched
        yfinance auto_adjust to ≤0.02%); the stable dividend-adjusted variant
        ships the whole bar pre-adjusted. ``interval`` other than ``"1d"`` is
        not supported by this endpoint.
        """
        if interval != "1d":
            raise ProviderError(f"FMP price_range supports only interval='1d', got {interval!r}")
        with self._wrap_errors(ticker, "price range fetch"):
            resp = (
                await self._get(
                    "/historical-price-eod/dividend-adjusted",
                    params={"symbol": ticker, "from": start, "to": end},
                )
            ).json()
        # Stable returns a bare array; sort oldest-first explicitly so the bar
        # list is ascending like every other price path in the codebase.
        raw_hist: list[Any] = resp if isinstance(resp, list) else []
        if not raw_hist:
            raise ProviderError(
                f"FMP historical-price-eod returned no bars for {ticker} {start}..{end}"
            )
        bars = sorted(
            (b for p in raw_hist if isinstance(p, dict) and (b := _adjusted_bar(p)) is not None),
            key=lambda b: str(b["date"]),
        )
        if not bars:
            raise ProviderError(
                f"FMP historical-price-eod bars lacked adjClose for {ticker} {start}..{end}"
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
        """Lightweight current price via /quote?symbol= — no OHLC history pull.

        The full ``_fetch_price`` also fetches a year of historical bars; QUOTE
        skips that so high-fan-out dashboard quotes stay one cheap call.
        """
        with self._wrap_errors(ticker, "quote fetch"):
            resp = (await self._get("/quote", params={"symbol": ticker})).json()
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
        """Fetch recent news articles for a ticker from stable /news/stock.

        Plan note: this endpoint is paywalled below the Starter tier — a free
        key gets a 403 plan body, which ``_get`` maps to ProviderPlanError so
        the chain falls through to the news_aggregator without charging the
        circuit breaker.
        """
        with self._wrap_errors(ticker, "news fetch"):
            resp = await self._get("/news/stock", params={"symbols": ticker, "limit": 20})
        # required=True: an empty FMP news list must fall through to the
        # news_aggregator (yfinance headlines + Alpha Vantage sentiment) at the
        # end of the provider chain instead of becoming a zero-news "success"
        # that is indistinguishable from "genuinely no news".
        raw = self._expect_rows(resp.json(), ticker, "/news/stock", required=True)
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
        """Fetch earnings surprises from stable /earnings (eps + revenue).

        This endpoint was stable-only even before the full migration (the
        legacy v3 /earnings-surprises carried a different schema and zero
        usable rows — BUG-001); it exposes epsActual/epsEstimated/
        revenueActual/revenueEstimated. Future quarters are returned with
        epsActual=null and are dropped by the eps None-filter below.
        """
        with self._wrap_errors(ticker, "earnings fetch"):
            resp = await self._get("/earnings", params={"symbol": ticker, "limit": 40})
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
        """Fetch earnings call transcript(s) from stable /earning-call-transcript.

        If ``quarter`` and ``year`` are specified, fetches a single transcript.
        Otherwise the stable API no longer lists transcripts at the bare content
        endpoint (year/quarter became required), so the available sessions come
        from /earning-call-transcript-dates and the newest ``limit`` are fetched
        individually. Plan note: transcript content sits in FMP's top tier —
        lower plans get a 403 plan body → ProviderPlanError → honest failure
        without charging the circuit breaker.
        """
        with self._wrap_errors(ticker, "earnings transcript fetch"):
            if quarter is not None and year is not None:
                wanted: list[tuple[int, int]] = [(year, quarter)]
            else:
                dates_raw = self._expect_rows(
                    (
                        await self._get("/earning-call-transcript-dates", params={"symbol": ticker})
                    ).json(),
                    ticker,
                    "/earning-call-transcript-dates",
                )
                # Sort by session date descending ourselves instead of trusting
                # the API ordering; rows carry {quarter, fiscalYear, date}.
                dated = sorted(
                    (d for d in dates_raw if d.get("fiscalYear") and d.get("quarter")),
                    key=lambda d: str(d.get("date") or ""),
                    reverse=True,
                )
                wanted = [(int(d["fiscalYear"]), int(d["quarter"])) for d in dated[:limit]]

            transcripts: list[dict[str, Any]] = []
            for want_year, want_quarter in wanted:
                rows = self._expect_rows(
                    (
                        await self._get(
                            "/earning-call-transcript",
                            params={"symbol": ticker, "year": want_year, "quarter": want_quarter},
                        )
                    ).json(),
                    ticker,
                    "/earning-call-transcript",
                )
                for item in rows[: max(1, limit - len(transcripts))]:
                    transcripts.append(
                        {
                            "ticker": ticker.upper(),
                            # Stable answers the quarter as period="Q3"; keep the
                            # legacy int contract for downstream consumers.
                            "quarter": _quarter_int(item) or want_quarter,
                            "year": item.get("year") or want_year,
                            "date": item.get("date", ""),
                            "content": item.get("content", ""),
                        }
                    )
                if len(transcripts) >= limit:
                    break

        return DataResult(
            data={"transcripts": transcripts},
            provider=self.name,
            ticker=ticker,
            data_type=DataType.EARNINGS_TRANSCRIPT,
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def _fetch_forward_estimates(self, ticker: str) -> DataResult:
        """Fetch annual analyst consensus estimates from stable /analyst-estimates.

        Ships the raw rows (farthest-future first, as FMP orders them) under
        ``rows``. FY1 selection and forward-EPS/EBITDA/FCF口径 belong to the
        red-line leaf ``compute.forward_estimates.get_forward_financials`` — this
        provider never derives a forward number itself (spec §6.4.1).

        Stable renamed every figure by dropping the "estimated" prefix
        (estimatedRevenueAvg → revenueAvg, estimatedEpsAvg → epsAvg, …); the
        consuming operator reads the stable names, and the FORWARD_ESTIMATES
        raw-cache slot is version-bumped so legacy-named cached rows miss.
        ``limit=10`` is explicit: the free plan caps this endpoint at 10 rows
        per call, and 10 annual rows comfortably cover FY1 selection.
        """
        with self._wrap_errors(ticker, "analyst-estimates fetch"):
            resp = await self._get(
                "/analyst-estimates",
                params={"symbol": ticker, "period": "annual", "page": 0, "limit": 10},
            )
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

        Raw parts, all through the shared ``_get`` rate limiter:
          profile          — target's industry / sector / market cap (the fetch
                             scope parameters for the two screens)
          stock_peers      — stable cross-recommendation list (one row per peer,
                             carrying mktCap)
          industry_screen  — same-industry symbols (mcap > $1B, top 50)
          sector_screen    — same-sector symbols (mcap > target/20, top 50 —
                             a FETCH-SCOPE floor so we don't pull thousands of
                             rows; the precise band is re-applied by the
                             operator)
          quotes           — market cap (harvested from the rows above) +
                             trailing P/E per in-scope candidate (/ratios-ttm,
                             one request each — stable has no batch quote and
                             dropped quote.pe)
          profiles         — per-candidate descriptions, fetched ONLY when the
                             target classifies as semiconductor (the only case
                             the operator's value-chain gate reads them)

        No selection logic here: tiering / NM-filter / size ranking are the
        pure operator ``compute.operators.peer_screen.screen_peers`` (ADR-0014).
        The scope band/cap before enrichment is fetch-cost control, mirror of
        the screens' ``limit=50``.
        """
        warnings: list[str] = []
        with self._wrap_errors(ticker, "peer-candidates fetch"):
            profile_raw = (await self._get("/profile", params={"symbol": ticker})).json()
            profile = profile_raw[0] if isinstance(profile_raw, list) and profile_raw else {}
            industry = str(profile.get("industry") or "")
            sector = str(profile.get("sector") or "")
            company_name = str(profile.get("companyName") or "")
            description = str(profile.get("description") or "")
            try:
                target_mcap = float(profile.get("marketCap") or 0.0)
            except (TypeError, ValueError):
                target_mcap = 0.0

            # Candidate market caps are harvested from the rows the pool fetches
            # ALREADY return (stable /stock-peers rows carry mktCap; screener
            # rows carry marketCap) — stable removed the v3 batch /quote, and
            # its single /quote dropped the pe field anyway, so the old
            # "40-symbol chunked quotes" enrichment is unportable.
            mcap_by_sym: dict[str, float] = {}

            stock_peers: list[str] = []
            peers_rows = (await self._get("/stock-peers", params={"symbol": ticker})).json()
            # Stable restructured peers: one row per peer
            # ({symbol, companyName, price, mktCap}) instead of v4's single
            # {symbol, peersList: [...]} row. NB the field here is still the
            # OLD "mktCap" name (unlike profile's "marketCap").
            if isinstance(peers_rows, list):
                for r in peers_rows:
                    if not isinstance(r, dict) or not r.get("symbol"):
                        continue
                    sym = str(r["symbol"])
                    stock_peers.append(sym)
                    try:
                        mcap_by_sym[sym] = float(r.get("mktCap") or 0.0)
                    except (TypeError, ValueError):
                        pass

            async def _screen(params: dict[str, Any], label: str) -> list[str]:
                """One /company-screener pull; plan-gated → empty + warning.

                The screener sits behind a paid tier — on a free key it must
                DEGRADE the pool (stock-peers still feed it) instead of sinking
                the whole PEER_CANDIDATES fetch.
                """
                try:
                    rows = (await self._get("/company-screener", params=params)).json()
                except ProviderPlanError:
                    warnings.append(
                        f"FMP /company-screener ({label}) unavailable on this plan; "
                        "peer pool degraded to stock-peers cross-recommendations"
                    )
                    return []
                rows = rows if isinstance(rows, list) else []
                out: list[str] = []
                for r in rows:
                    if not isinstance(r, dict) or not r.get("symbol"):
                        continue
                    sym = str(r["symbol"])
                    out.append(sym)
                    try:
                        mcap_by_sym.setdefault(sym, float(r.get("marketCap") or 0.0))
                    except (TypeError, ValueError):
                        pass
                return out

            industry_screen: list[str] = []
            if industry:
                industry_screen = await _screen(
                    {"industry": industry, "marketCapMoreThan": 1_000_000_000, "limit": 50},
                    "industry",
                )

            sector_screen: list[str] = []
            if sector and target_mcap > 0:
                sector_screen = await _screen(
                    {"sector": sector, "marketCapMoreThan": int(target_mcap / 20), "limit": 50},
                    "sector",
                )

            symbols = sorted(
                {s for s in (*stock_peers, *industry_screen, *sector_screen) if s != ticker}
            )

            # FETCH-SCOPE band + cap before per-symbol enrichment (stable has no
            # batch endpoints, so pe/description cost ONE REQUEST PER CANDIDATE).
            # The band must be a superset of the operator's widest eligibility
            # band ([1/200x, 20x] — peer_screen.PEER_SCREEN_HIGH_AFFINITY_FLOOR_
            # BAND / PEER_SCREEN_MCAP_BAND; a unit test pins scope ⊇ operator so
            # the two can't drift apart), and the cap keeps nearest-by-size
            # candidates — the operator re-applies the precise band and ranking,
            # same fetch-scope-vs-selection split as the screener's limit=50.
            if target_mcap > 0:
                in_scope = [
                    s
                    for s in symbols
                    if (m := mcap_by_sym.get(s, 0.0)) > 0
                    and target_mcap / _PEER_SCOPE_FLOOR_DIV
                    <= m
                    <= target_mcap * _PEER_SCOPE_CAP_MULT
                ]
                in_scope.sort(key=lambda s: abs(math.log(mcap_by_sym[s] / target_mcap)))
                if len(in_scope) > _PEER_ENRICH_MAX:
                    warnings.append(
                        f"FMP peer pool for {ticker}: {len(in_scope)} in-band candidates, "
                        f"enriching only the {_PEER_ENRICH_MAX} nearest by size "
                        "(per-symbol request cost on the stable API)"
                    )
                    in_scope = in_scope[:_PEER_ENRICH_MAX]
            else:
                in_scope = []

            # Trailing P/E per candidate — stable /quote lost the pe field, so
            # the only per-symbol source is /ratios-ttm (priceToEarningsRatioTTM,
            # trailing caliber like v3 quote.pe). pe=None just NM-drops the
            # candidate in the operator, so per-symbol failures degrade softly.
            quotes: dict[str, dict[str, float | None]] = {}
            pe_failures = 0
            for sym in in_scope:
                pe: float | None = None
                try:
                    ratio_rows = (await self._get("/ratios-ttm", params={"symbol": sym})).json()
                    if isinstance(ratio_rows, list) and ratio_rows:
                        pe_raw = ratio_rows[0].get("priceToEarningsRatioTTM")
                        pe = float(pe_raw) if pe_raw is not None else None
                except (httpx.HTTPError, ProviderError, TypeError, ValueError):
                    pe_failures += 1
                quotes[sym] = {"market_cap": mcap_by_sym.get(sym, 0.0), "pe": pe}
            if pe_failures:
                warnings.append(
                    f"FMP /ratios-ttm failed for {pe_failures}/{len(in_scope)} peer "
                    f"candidates of {ticker}; those candidates carry pe=None and are "
                    "NM-dropped by the peer screen"
                )

            # Candidate profile descriptions exist ONLY to let the operator's
            # value-chain gate split semiconductor roles (design vs foundry vs
            # equipment) — the gate never consults them for any other target
            # (primitives.industry.semiconductor_role is the SHARED predicate, so
            # "provider fetches" ⇔ "operator reads" can't drift). Skipping them
            # for non-semiconductor targets saves one request per candidate.
            profiles: dict[str, dict[str, str]] = {}
            if semiconductor_role(profile) is not None:
                for sym in in_scope:
                    try:
                        rows = (await self._get("/profile", params={"symbol": sym})).json()
                    except (httpx.HTTPError, ProviderError):
                        continue
                    row = rows[0] if isinstance(rows, list) and rows else None
                    if not isinstance(row, dict):
                        continue
                    profiles[sym] = {
                        "company_name": str(row.get("companyName") or ""),
                        "sector": str(row.get("sector") or ""),
                        "industry": str(row.get("industry") or ""),
                        "description": str(row.get("description") or ""),
                    }

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
            warnings=warnings,
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
            # FMP status semantics (live-verified, 强制清单 T2#1): 401 = invalid
            # key, 403 = plan/legacy restriction, 429 = bandwidth/rate limit.
            # ONLY 429 maps to the typed RateLimitedProviderError — a blanket
            # 4xx mapping would mis-classify auth/plan failures as transient
            # throttling and make callers preserve stale forever.
            if e.response.status_code == 429:
                raise RateLimitedProviderError(f"FMP HTTP 429 during {op} for '{ticker}'") from e
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

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        """Make authenticated, rate-limited GET request to the FMP stable API.

        Serialises concurrent calls via asyncio.Lock and enforces a minimum
        inter-request interval (_MIN_INTERVAL) to avoid per-minute burst limits.
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
        resp = await self._client.get(f"{_BASE_URL}{path}", params=p)
        # A 403 with a "Legacy/Exclusive Endpoint" body means the KEY IS VALID
        # but the plan doesn't include this endpoint (free plan: news / screener
        # / transcripts / some symbols). Classify it HERE — the body text is the
        # only signal and is key-free — so the data layer can fall through the
        # provider chain without charging the circuit breaker. The message
        # carries path + status only, never the URL (which embeds ?apikey=).
        if resp.status_code == 403:
            try:
                body = resp.text[:500].lower()
            except httpx.ResponseNotRead:  # pragma: no cover — GET pre-reads
                body = ""
            if any(marker in body for marker in _PLAN_GATE_MARKERS):
                raise ProviderPlanError(
                    f"FMP plan does not include {path} (HTTP 403 plan/legacy restriction)"
                )
        resp.raise_for_status()
        return resp

    async def close(self) -> None:
        """Release the shared httpx client. Called from DataLayer.close()."""
        await self._client.aclose()
