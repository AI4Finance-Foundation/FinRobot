import asyncio
import logging
import math
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any, cast

import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFException

from finrobot.engine.data.interface import DataProvider, DataResult, ProviderError
from finrobot.engine.data.types import DataType

logger = logging.getLogger(__name__)

# Reduce "Too Many Requests" errors from Yahoo Finance
try:
    yf.set_tz_cache_dir("/tmp/yf_cache")
except (AttributeError, OSError, TypeError):
    pass  # non-critical, ignore if not supported by this yfinance version

_SUPPORTED = [
    DataType.FINANCIALS,
    DataType.PRICE,
    DataType.PRICE_RANGE,
    DataType.QUOTE,
    DataType.NEWS,
]
_CALL_DELAY = 1.0  # seconds between the info fetch and subsequent calls

# ---------------------------------------------------------------------------
# yfinance row-name lookup tables for the historical (multi-year) financials.
# yfinance uses different row labels by ticker/region/version — each list is
# tried in order, first match wins. These live here (not in the compute layer)
# because they encode yfinance-specific schema variance; the compute consumer
# (historical_extractor) reads the normalized per-year dict this provider emits.
# ---------------------------------------------------------------------------
_REVENUE_NAMES = ["Total Revenue", "Revenue", "Net Revenue"]
_GROSS_PROFIT_NAMES = ["Gross Profit"]
_EBITDA_NAMES = ["EBITDA", "Normalized EBITDA"]
_OPERATING_INCOME_NAMES = ["Operating Income", "Total Operating Profit Loss"]
_NET_INCOME_NAMES = [
    "Net Income",
    "Net Income Common Stockholders",
    "Net Income From Continuing And Discontinued Operation",
]
_EPS_NAMES = ["Basic EPS", "Diluted EPS", "EPS"]
_SGA_NAMES = [
    "Selling General Administrative",
    "Selling General And Administration",
    "General And Administrative Expense",
]
_OPERATING_CF_NAMES = [
    "Operating Cash Flow",
    "Cash Flow From Continuing Operating Activities",
    "Net Cash Provided By Operating Activities",
]
_INVESTING_CF_NAMES = [
    "Investing Cash Flow",
    "Cash Flow From Continuing Investing Activities",
    "Net Cash Used For Investing Activities",
    "Net Cash Provided By Investing Activities",
]
_FINANCING_CF_NAMES = [
    "Financing Cash Flow",
    "Cash Flow From Continuing Financing Activities",
    "Net Cash Used Provided By Financing Activities",
    "Net Cash Provided By Financing Activities",
]
_DA_NAMES = [
    "Depreciation And Amortization",
    "Depreciation Amortization Depletion",
    "Reconciled Depreciation",
    "Depreciation",
]
_CAPEX_NAMES = [
    "Capital Expenditure",
    "Capital Expenditures",
    "Purchase Of Ppe",
    "Net Ppe Purchase And Sale",
]
_NWC_CHANGE_NAMES = [
    "Change In Working Capital",
    "Changes In Working Capital",
]


def _make_ticker(symbol: str) -> yf.Ticker:
    """Create a Ticker. Let yfinance use its internal curl_cffi session."""
    return yf.Ticker(symbol)


def _get_row(df: pd.DataFrame | None, names: Sequence[str]) -> pd.Series | None:
    """Return the first matching row from *df* by trying *names* in order.

    Returns None if *df* is empty, *names* is empty, or no name matches.
    This is the single point of yfinance row-name variance handling.
    """
    if df is None or df.empty or not names:
        return None
    for name in names:
        if name in df.index:
            return cast(pd.Series, df.loc[name])
    return None


def _safe_float(value: object) -> float | None:
    """Convert a scalar to float; return None on any error or NaN.

    NaN is treated as missing (not a legitimate 0) so the downstream consumer
    can distinguish "row existed but empty" from "cell was zero".
    """
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if math.isnan(result):
        return None
    return result


def _cell(row: pd.Series | None, col: Any) -> float | None:
    """Read one cell from a row Series, tolerating a missing row/column/NaN."""
    if row is None:
        return None
    try:
        return _safe_float(row[col])
    except (KeyError, IndexError):
        return None


def _build_yearly_financials(
    income_stmt: pd.DataFrame, cashflow: pd.DataFrame | None, max_years: int
) -> list[dict[str, Any]]:
    """Transform yfinance income_stmt + cashflow DataFrames into the canonical
    per-year normalized dict (same schema FMP emits), newest-first.

    Emits None (not 0.0) for missing cells — the historical_extractor consumer
    owns the None→0.0 fill and the revenue-NaN year filtering, so this stays a
    pure provider-shape→normalized-dict translation. CapEx is sign-flipped to a
    positive magnitude (FCF formula convention); D&A is reported positive.
    """
    cols = list(income_stmt.columns[:max_years])
    has_cf = cashflow is not None and not cashflow.empty

    rev_row = _get_row(income_stmt, _REVENUE_NAMES)
    gp_row = _get_row(income_stmt, _GROSS_PROFIT_NAMES)
    ebitda_row = _get_row(income_stmt, _EBITDA_NAMES)
    oi_row = _get_row(income_stmt, _OPERATING_INCOME_NAMES)
    ni_row = _get_row(income_stmt, _NET_INCOME_NAMES)
    eps_row = _get_row(income_stmt, _EPS_NAMES)
    sga_row = _get_row(income_stmt, _SGA_NAMES)

    ocf_row = _get_row(cashflow, _OPERATING_CF_NAMES) if has_cf else None
    icf_row = _get_row(cashflow, _INVESTING_CF_NAMES) if has_cf else None
    fcf_row = _get_row(cashflow, _FINANCING_CF_NAMES) if has_cf else None
    da_row = _get_row(cashflow, _DA_NAMES) if has_cf else None
    capex_row = _get_row(cashflow, _CAPEX_NAMES) if has_cf else None
    nwc_row = _get_row(cashflow, _NWC_CHANGE_NAMES) if has_cf else None

    yearly: list[dict[str, Any]] = []
    for col in cols:
        rev = _cell(rev_row, col)
        gp = _cell(gp_row, col)
        oi = _cell(oi_row, col)
        capex_raw = _cell(capex_row, col)
        yearly.append(
            {
                "fiscal_year": str(col.date()) if hasattr(col, "date") else str(col),
                "revenue": rev,
                "gross_profit": gp,
                "operating_income": oi,
                "ebitda": _cell(ebitda_row, col),
                "net_income": _cell(ni_row, col),
                "eps": _cell(eps_row, col),
                "sga_expense": _cell(sga_row, col),
                "gross_margin": gp / rev if (gp is not None and rev) else None,
                "operating_margin": oi / rev if (oi is not None and rev) else None,
                "operating_cash_flow": _cell(ocf_row, col),
                "investing_cash_flow": _cell(icf_row, col),
                "financing_cash_flow": _cell(fcf_row, col),
                "depreciation_amortization": _cell(da_row, col),
                "capital_expenditure": abs(capex_raw) if capex_raw is not None else None,
                "change_in_working_capital": _cell(nwc_row, col),
            }
        )
    return yearly


class YFinanceProvider(DataProvider):
    """DataProvider backed by yfinance. Free, no API key required."""

    @property
    def name(self) -> str:
        return "yfinance"

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
            "pe_ratio",
            "total_debt",
            "total_cash",
        }

    async def fetch(self, ticker: str, data_type: str | DataType, **kwargs: Any) -> DataResult:
        if data_type == DataType.FILINGS:
            raise ProviderError(
                f"data_type '{DataType.FILINGS}' is not supported by yfinance. "
                "SEC EDGAR provider will be added in P2b."
            )
        if data_type not in _SUPPORTED:
            raise ProviderError(
                f"data_type '{data_type}' is not supported by yfinance. Supported: {_SUPPORTED}"
            )

        # QUOTE is the lightweight current-price path: fast_info.last_price only,
        # NO heavy .info round-trip. Handled before the validation block below so
        # high-fan-out dashboard quotes stay cheap (the whole point of QUOTE vs PRICE).
        if data_type == DataType.QUOTE:
            return await self._fetch_quote(ticker)

        # PRICE_RANGE is OHLCV-only — no current-price/marketCap needed, so skip
        # the heavy .info round-trip like QUOTE does.
        if data_type == DataType.PRICE_RANGE:
            return await self._fetch_price_range(
                ticker,
                start=kwargs["start"],
                end=kwargs["end"],
                interval=kwargs.get("interval", "1d"),
            )

        # Fetch and validate ticker info. info is passed to sub-methods
        # to avoid a redundant second HTTP call. We use explicit
        # if-raise instead of `assert` because Tauri builds may run
        # Python under -O, which strips `assert` and would let a None
        # leak into _fetch_* and surface as a generic AttributeError.
        #
        # No in-provider retry/backoff: the DataLayer already iterates
        # providers in priority order (FMP → Finnhub → yfinance → ...)
        # on ProviderError, so retrying inside yfinance both blocked
        # fallback for ~17s per call (3 × [2,5,10] sleep) and double-
        # counted toward Yahoo's rate-limit budget. Surfacing the 429
        # immediately lets the layer hop to the next provider in <1s.
        info: dict[str, Any] | None = None
        t: yf.Ticker | None = None
        try:
            t = await asyncio.to_thread(_make_ticker, ticker)
            if t is None:
                raise ProviderError(f"yfinance returned no Ticker object for '{ticker}'")
            _t: yf.Ticker = t  # capture for lambda — avoids mypy union-attr on closure
            info = await asyncio.to_thread(lambda: _t.info)
            if not info or (
                info.get("regularMarketPrice") is None
                and info.get("currentPrice") is None
                and info.get("marketCap") is None
            ):
                if info is not None and len(info) <= 1:
                    raise ProviderError(f"Ticker '{ticker}' not found or returned no data")
        except ProviderError:
            raise
        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            YFException,
        ) as e:
            raise ProviderError(f"Failed to fetch ticker '{ticker}': {e}") from e

        if t is None or info is None:
            raise ProviderError(
                f"yfinance fetch exited without populating ticker/info for '{ticker}'"
            )

        if data_type == DataType.FINANCIALS:
            years_kwarg = kwargs.get("years")
            if years_kwarg and years_kwarg > 1:
                result = await self._fetch_historical_financials(ticker, info, t, years_kwarg)
            else:
                result = self._fetch_financials(ticker, info)
        elif data_type == DataType.PRICE:
            await asyncio.sleep(_CALL_DELAY)
            result = await self._fetch_price(ticker, t, info)
        elif data_type == DataType.NEWS:
            await asyncio.sleep(_CALL_DELAY)
            result = await self._fetch_news(ticker, t)
        else:
            raise ProviderError(
                f"data_type '{data_type}' is in _SUPPORTED but no fetch branch handles it. "
                "Add an elif above this guard when extending _SUPPORTED."
            )

        return result

    async def _fetch_quote(self, ticker: str) -> DataResult:
        """Lightweight current price via ``fast_info`` — no ``.info`` round-trip.

        Raises ProviderError on any failure (including Yahoo 429, which arrives
        as a YFException subclass and is wrapped here); the message carries the
        rate-limit signal so callers can classify it via ``is_rate_limit_error``.
        """

        def _blocking() -> float | None:
            t = _make_ticker(ticker)
            info = t.fast_info
            price = getattr(info, "last_price", None)
            if price is None:
                price = getattr(info, "lastPrice", None)
            return float(price) if price is not None else None

        try:
            price = await asyncio.to_thread(_blocking)
        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            YFException,
        ) as e:
            raise ProviderError(f"Failed to fetch quote for '{ticker}': {e}") from e
        if price is None:
            raise ProviderError(f"yfinance returned no quote for '{ticker}'")
        return DataResult(
            data={"price": price},
            provider=self.name,
            ticker=ticker,
            data_type=DataType.QUOTE,
            timestamp=datetime.now(tz=timezone.utc),
        )

    def _fetch_financials(self, ticker: str, info: dict[str, Any]) -> DataResult:
        # dict.get() never raises; no try/except needed here
        data = {
            "revenue": info.get("totalRevenue"),
            "ebitda": info.get("ebitda"),
            "net_income": info.get("netIncomeToCommon"),
            "gross_margin": info.get("grossMargins"),
            "operating_margin": info.get("operatingMargins"),
            "pe_ratio": info.get("trailingPE"),
            "market_cap": info.get("marketCap"),
            "shares_outstanding": info.get("sharesOutstanding"),
            "total_debt": info.get("totalDebt"),
            "total_cash": info.get("totalCash"),
            "company_name": info.get("shortName") or info.get("longName"),
            # TTM cash-flow actuals for a real FCF = OCF − CapEx (computed
            # downstream, never LLM-estimated). yfinance `info` exposes TTM
            # operatingCashflow + freeCashflow but no capex line, so derive
            # capex = OCF − FCF (positive magnitude) when both are present.
            "operating_cash_flow": info.get("operatingCashflow"),
            "capital_expenditure": (
                info["operatingCashflow"] - info["freeCashflow"]
                if isinstance(info.get("operatingCashflow"), int | float)
                and isinstance(info.get("freeCashflow"), int | float)
                else None
            ),
            # Industry/sector for valuation model routing (DDM vs DCF)
            "industry": info.get("industry"),
            "sector": info.get("sector"),
            # Dividend data for DDM valuation
            "dividend_per_share": info.get("dividendRate"),
            "dividend_yield": info.get("dividendYield"),
            "payout_ratio": info.get("payoutRatio"),
            # Bank-specific metrics (available for financials)
            "book_value_per_share": info.get("bookValue"),
            "return_on_equity": info.get("returnOnEquity"),
            # v5 PR4c forward-estimate inputs — required by
            # engine/compute/operators/forward_estimates.py. yfinance only carries
            # forward EPS / PE (no consensus EBITDA / FCF), so the leaf has
            # to derive forward EBITDA/FCF from forward_revenue × TTM margin.
            "forward_eps": info.get("forwardEps"),
            "forward_pe": info.get("forwardPE"),
            "trailing_eps": info.get("trailingEps"),
            # ISO 4217 currency codes — yfinance carries two different ones
            # and they DISAGREE for foreign-listed ADRs:
            #
            #   - "currency"          → quote currency: marketCap, price,
            #                            shares × price are in this unit
            #   - "financialCurrency" → IS/BS reporting currency: revenue,
            #                            ebitda, net_income, debt, cash are
            #                            in this unit
            #
            # For TSM (ADR): currency=USD, financialCurrency=TWD — the very
            # mismatch that produces EV/EBITDA=0.158x without normalization.
            # For 2330.TW (local listing): both = TWD.
            # For most US issuers: both = USD.
            "quote_currency": info.get("currency") or "USD",
            "financial_currency": info.get("financialCurrency") or "USD",
            # Country of incorporation — used by extractor to cross-check
            # financialCurrency when the provider tag is unreliable (e.g. TSM
            # ADR where yfinance returns financialCurrency="USD" despite IS/BS
            # being reported in TWD).
            "country": info.get("country"),
        }
        return DataResult(
            data=data,
            provider=self.name,
            ticker=ticker,
            data_type=DataType.FINANCIALS,
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def _fetch_historical_financials(
        self, ticker: str, info: dict[str, Any], t: yf.Ticker, years: int
    ) -> DataResult:
        """Fetch multi-year financials from the income_stmt + cashflow DataFrames.

        Emits the canonical per-year normalized dict (the same schema FMP emits)
        so the provider-agnostic historical_extractor can build a complete
        HistoricalMetrics — including the DCF cash-flow trio (OCF/CapEx/ΔNWC),
        D&A, EPS and SGA — when yfinance is the active source. Falls back to
        single-year (_fetch_financials) if income_stmt is empty.
        """
        try:
            income_stmt = await asyncio.to_thread(lambda: t.income_stmt)
            cashflow = await asyncio.to_thread(lambda: t.cashflow)
        except (AttributeError, KeyError, ValueError, TypeError) as e:
            logger.warning(
                f"Historical data extraction failed for {ticker}, falling back to single-year: {e}"
            )
            return self._fetch_financials(ticker, info)

        if income_stmt is None or income_stmt.empty:
            return self._fetch_financials(ticker, info)

        yearly_data = _build_yearly_financials(income_stmt, cashflow, years)

        return DataResult(
            data={"yearly_data": yearly_data},
            provider=self.name,
            ticker=ticker,
            data_type=DataType.FINANCIALS,
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def _fetch_price(self, ticker: str, t: yf.Ticker, info: dict[str, Any]) -> DataResult:
        try:
            current_price = info.get("currentPrice") or info.get("regularMarketPrice")
            # Exchange name for the LIVE pill (TickerHero) — NASDAQ vs NYSE
            # vs AMEX matters for retail investors who associate trust signals
            # with exchange. fullExchangeName ("NasdaqGS" etc.) gets pretty-
            # printed by the UI; raw "exchange" code is the fallback.
            exchange = (
                info.get("fullExchangeName")
                or info.get("exchange")
                or info.get("exchangeShortName")
            )
            hist = await asyncio.to_thread(t.history, period="1y")
            price_history = []
            for date, row in hist.iterrows():
                price_history.append(
                    {
                        "date": str(date.date()),
                        "open": row["Open"],
                        "high": row["High"],
                        "low": row["Low"],
                        "close": row["Close"],
                        "volume": row["Volume"],
                    }
                )
        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            YFException,
        ) as e:
            raise ProviderError(f"Failed to fetch price for '{ticker}': {e}") from e

        return DataResult(
            data={
                "current_price": current_price,
                "price_history": price_history,
                "exchange": exchange,
            },
            provider=self.name,
            ticker=ticker,
            data_type=DataType.PRICE,
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def _fetch_price_range(
        self, ticker: str, *, start: str, end: str, interval: str = "1d"
    ) -> DataResult:
        """Arbitrary-range split/dividend-adjusted daily OHLCV.

        Uses ``Ticker.history(start, end, auto_adjust=True)`` — the adjusted
        basis that lines up with FMP's ``adjClose`` (verified live 2026-06-02),
        so a multi-year backtest doesn't break across a split. Throttled by
        ``_CALL_DELAY`` like every other yfinance call; no in-provider retry
        (DataLayer owns fallback). ``interval`` passes through to yfinance.
        """
        await asyncio.sleep(_CALL_DELAY)
        bars: list[dict[str, Any]] = []
        try:
            t = await asyncio.to_thread(_make_ticker, ticker)
            if t is None:
                raise ProviderError(f"yfinance returned no Ticker object for '{ticker}'")
            _t: yf.Ticker = t  # capture for the closure — avoids mypy union-attr
            hist = await asyncio.to_thread(
                lambda: _t.history(start=start, end=end, interval=interval, auto_adjust=True)
            )
            # Some yfinance versions return MultiIndex columns even for a single
            # ticker; flatten to the level-0 OHLCV names.
            if hasattr(hist.columns, "levels") and len(hist.columns.levels) > 1:
                hist.columns = hist.columns.droplevel(1)
            for dt, row in hist.iterrows():
                bars.append(
                    {
                        "date": str(dt.date()),
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                        "volume": float(row["Volume"]),
                    }
                )
        except ProviderError:
            raise
        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            YFException,
        ) as e:
            raise ProviderError(f"Failed to fetch price range for '{ticker}': {e}") from e

        if not bars:
            raise ProviderError(
                f"yfinance returned no bars for '{ticker}' between {start} and {end}"
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

    async def _fetch_news(self, ticker: str, t: yf.Ticker) -> DataResult:
        try:
            raw_news = await asyncio.to_thread(lambda: t.news or [])
            news_items = []
            for item in raw_news:
                content = item.get("content", {})
                title = content.get("title") or item.get("title", "")
                if not title:
                    continue
                news_items.append(
                    {
                        "title": title,
                        "source": (
                            content.get("provider", {}).get("displayName")
                            or item.get("publisher", "yfinance")
                        ),
                        "published": (
                            content.get("pubDate") or item.get("providerPublishTime", "")
                        ),
                        "url": (content.get("canonicalUrl", {}).get("url") or item.get("link", "")),
                    }
                )
        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            YFException,
        ) as e:
            raise ProviderError(f"Failed to fetch news for '{ticker}': {e}") from e

        return DataResult(
            data={"news_items": news_items},
            provider=self.name,
            ticker=ticker,
            data_type=DataType.NEWS,
            timestamp=datetime.now(tz=timezone.utc),
        )
