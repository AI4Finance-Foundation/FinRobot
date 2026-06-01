from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from finrobot.engine.compute.multiples import calculate_ebitda_operating
from finrobot.engine.data.interface import DataProvider, DataResult, ProviderError
from finrobot.engine.data.types import DataType

_BASE_URL = "https://financialmodelingprep.com/api/v3"
_SUPPORTED = [
    DataType.FINANCIALS,
    DataType.PRICE,
    DataType.QUOTE,
    DataType.NEWS,
    DataType.EARNINGS,
    DataType.EARNINGS_TRANSCRIPT,
    DataType.FORWARD_ESTIMATES,
]
_TIMEOUT = 15.0
_MIN_INTERVAL = 0.15  # 6 req/sec — stays within per-minute burst limits on all FMP tiers
# Trailing calendar window for the price-history fetch. 52 weeks + cushion so
# the downstream 52-week high/low window (366 calendar days) is fully covered
# even across weekend/holiday gaps at the boundary.
_PRICE_HISTORY_DAYS = 372


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
        years: int | None = kwargs.get("years")
        warnings: list[str] = []
        cashflow: list[dict[str, Any]] = []
        with self._wrap_errors(ticker, "fetch"):
            if years and years > 1:
                income = (
                    await self._get(f"/income-statement/{ticker}", params={"limit": years})
                ).json()
                balance = (
                    await self._get(f"/balance-sheet-statement/{ticker}", params={"limit": 1})
                ).json()
                # DCF's FCF = OCF − CapEx − ΔNWC. The income statement carries
                # none of those; without this cash-flow pull FMP-sourced history
                # silently drops every cash-flow input and DCF degrades to
                # industry-median assumptions (see 门一 baseline spec).
                cashflow = (
                    await self._get(f"/cash-flow-statement/{ticker}", params={"limit": years})
                ).json()
            else:
                income = (
                    await self._get(
                        f"/income-statement/{ticker}",
                        params={"period": "quarter", "limit": 4},
                    )
                ).json()
                balance = (
                    await self._get(
                        f"/balance-sheet-statement/{ticker}",
                        params={"period": "quarter", "limit": 1},
                    )
                ).json()
                # D&A on FMP's income statement is unreliable for the freshest
                # quarter (it arrives 0 until FMP backfills), which silently
                # understates TTM EBITDA. The cash-flow statement carries the
                # real per-quarter D&A — fetch the matching 4 quarters and let
                # _build_ttm_data prefer it. (Same call order as the years>1
                # branch: income → balance → cash-flow → profile.)
                cashflow = (
                    await self._get(
                        f"/cash-flow-statement/{ticker}",
                        params={"period": "quarter", "limit": 4},
                    )
                ).json()
                if len(income) < 4:
                    warnings.append(
                        f"FMP returned only {len(income)} quarterly income rows for {ticker}; "
                        "TTM metrics use the available rows."
                    )
            profile = (await self._get(f"/profile/{ticker}")).json()

        bal = balance[0] if balance else {}
        prof = profile[0] if profile else {}

        if years and years > 1 and len(income) > 1:
            # Align cash-flow rows to income rows by fiscal-year-end date so
            # each year's OCF/CapEx/ΔNWC come from the matching period.
            cf_by_date = {cf.get("date"): cf for cf in cashflow if isinstance(cf, dict)}
            data: dict[str, Any] = {
                "yearly_data": [
                    self._build_single_year_data(
                        inc_i, bal, prof, cf_by_date.get(inc_i.get("date"))
                    )
                    for inc_i in income
                ],
            }
        else:
            data = self._build_ttm_data(income, bal, prof, cashflow)

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
    ) -> dict[str, Any]:
        """Extract a flat dict of normalized financial fields for one year."""
        revenue = inc.get("revenue")
        gross_profit = inc.get("grossProfit")
        operating_income = inc.get("operatingIncome")
        net_income = inc.get("netIncome")
        mkt_cap = prof.get("mktCap")
        price = prof.get("price")
        shares = int(mkt_cap / price) if mkt_cap and price else None
        cf = cf or {}
        # FMP reports capitalExpenditure as a negative (cash outflow); the rest
        # of the codebase + the DCF FCF formula expect a positive magnitude.
        capex_raw = cf.get("capitalExpenditure")
        capex = abs(capex_raw) if isinstance(capex_raw, int | float) else None
        # PE = market_cap / net_income (algebraically equivalent to
        # price / EPS where EPS = net_income / shares = net_income * price / mkt_cap).
        pe_ratio = mkt_cap / net_income if mkt_cap and net_income and net_income > 0 else None
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
            "total_debt": bal.get("totalDebt"),
            "total_cash": bal.get("cashAndCashEquivalents"),
            "market_cap": mkt_cap,
            "shares_outstanding": shares,
            "pe_ratio": pe_ratio,
            "beta": prof.get("beta"),
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
    ) -> dict[str, Any]:
        """Build a current snapshot from the latest four quarterly rows."""
        if not income_rows:
            return cls._build_single_year_data({}, bal, prof)

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
        income_tax_expense = total("incomeTaxExpense")
        # D&A: prefer the cash-flow statement (authoritative; carries the
        # freshest quarter that the income statement leaves at 0), fall back to
        # the income statement only if cash flow is unavailable.
        da = _sum(cashflow_rows, "depreciationAndAmortization") if cashflow_rows else None
        if da is None:
            da = total("depreciationAndAmortization")
        # EBITDA recomputed on the operating caliber (EBIT + D&A) rather than
        # trusting FMP's `ebitda` field, which inherits the same dropped-D&A
        # contamination for the latest quarter. Fall back to FMP's field only
        # when the components are missing. See multiples.calculate_ebitda_operating.
        ebitda = calculate_ebitda_operating(operating_income, da)
        if ebitda is None:
            ebitda = total("ebitda")
        mkt_cap = prof.get("mktCap")
        price = prof.get("price")
        shares = int(mkt_cap / price) if mkt_cap and price else None
        profile_pe = prof.get("pe")
        pe_ratio = (
            profile_pe
            if profile_pe
            else mkt_cap / net_income
            if mkt_cap and net_income and net_income > 0
            else None
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
            "rd_expense": total("researchAndDevelopmentExpenses"),
            "sga_expense": total("sellingGeneralAndAdministrative"),
            "interest_expense": total("interestExpense"),
            # None ≠ 0: a missing balance-sheet line must stay None so enterprise
            # value is left undefined rather than fabricated (market_cap + 0 - 0).
            # calculate_multiples only computes EV when both are present.
            "total_debt": bal.get("totalDebt"),
            "total_cash": bal.get("cashAndCashEquivalents"),
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
        raw_hist: list[dict[str, Any]] = []
        if isinstance(hist_resp, dict):
            raw_hist = list(reversed(hist_resp.get("historical", [])))
        price_history = [
            {
                "date": p.get("date"),
                "open": p.get("open"),
                "high": p.get("high"),
                "low": p.get("low"),
                "close": p.get("close"),
                "volume": p.get("volume"),
            }
            for p in raw_hist
        ]

        return DataResult(
            data={
                "current_price": float(current_price),
                "price_history": price_history,
                "exchange": exchange,
            },
            provider=self.name,
            ticker=ticker,
            data_type=DataType.PRICE,
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
        raw: list[dict[str, Any]] = resp.json()
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
        """Fetch earnings surprises from FMP /earnings-surprises/{ticker}."""
        with self._wrap_errors(ticker, "earnings fetch"):
            resp = await self._get(f"/earnings-surprises/{ticker}")
        raw: list[dict[str, Any]] = resp.json()
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
        raw: list[dict[str, Any]] = resp.json()

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

    @contextmanager
    def _wrap_errors(self, ticker: str, op: str) -> Iterator[None]:
        """Translate httpx + parse errors into ProviderError with a uniform message.

        Used by every public fetch path so each call site only needs to label
        the operation; message formatting and exception fanout live here.
        """
        try:
            yield
        except httpx.TimeoutException as e:
            raise ProviderError(f"FMP timeout during {op} for '{ticker}': {e}") from e
        except httpx.HTTPStatusError as e:
            raise ProviderError(f"FMP API error during {op} for '{ticker}': {e}") from e
        except (
            httpx.ConnectError,
            httpx.RemoteProtocolError,
            httpx.ReadError,
            httpx.WriteError,
        ) as e:
            raise ProviderError(f"FMP network error during {op} for '{ticker}': {e}") from e
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            raise ProviderError(f"FMP {op} failed for '{ticker}': {e}") from e

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        """Make authenticated, rate-limited GET request to FMP API.

        Serialises concurrent calls via asyncio.Lock and enforces a minimum
        inter-request interval (_MIN_INTERVAL) to avoid per-minute burst limits.
        """
        async with self._lock:
            elapsed = time.monotonic() - self._last_call
            if elapsed < _MIN_INTERVAL:
                await asyncio.sleep(_MIN_INTERVAL - elapsed)
            self._last_call = time.monotonic()
            p: dict[str, Any] = {"apikey": self._api_key}
            if params:
                p.update(params)
            resp = await self._client.get(f"{_BASE_URL}{path}", params=p)
            resp.raise_for_status()
            return resp

    async def close(self) -> None:
        """Release the shared httpx client. Called from DataLayer.close()."""
        await self._client.aclose()
