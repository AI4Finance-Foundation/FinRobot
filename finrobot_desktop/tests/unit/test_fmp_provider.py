"""FMP Provider unit tests. All HTTP calls are mocked."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from finrobot.engine.data.interface import DataResult, ProviderError
from finrobot.engine.data.providers.fmp_provider import FMPProvider


@pytest.fixture
def provider():
    return FMPProvider(api_key="test-key")


def _fmp_income_response(ticker: str = "AAPL") -> list[dict]:
    """Mock FMP /income-statement response (array of annual periods)."""
    return [
        {
            "date": "2025-09-30",
            "symbol": ticker,
            "revenue": 394_328_000_000,
            "ebitda": 137_352_000_000,
            "netIncome": 96_995_000_000,
            "depreciationAndAmortization": 11_519_000_000,
            "grossProfit": 180_683_000_000,
            "operatingIncome": 123_216_000_000,
            "researchAndDevelopmentExpenses": 29_915_000_000,
            "sellingGeneralAndAdministrative": 27_552_000_000,
            "interestExpense": 3_933_000_000,
        }
    ]


def _fmp_quarterly_income_response(
    ticker: str = "AAPL", reported_currency: str = "USD"
) -> list[dict]:
    """Mock FMP quarterly income rows used for current TTM financials."""
    return [
        {
            "date": f"2026-0{quarter + 1}-28",
            "symbol": ticker,
            "reportedCurrency": reported_currency,
            "revenue": 100_000_000_000,
            "ebitda": 30_000_000_000,
            "netIncome": 20_000_000_000,
            "depreciationAndAmortization": 3_000_000_000,
            "grossProfit": 45_000_000_000,
            "operatingIncome": 25_000_000_000,
            "incomeTaxExpense": 2_000_000_000,
            "researchAndDevelopmentExpenses": 7_000_000_000,
            "sellingGeneralAndAdministrative": 6_000_000_000,
            "interestExpense": 1_000_000_000,
        }
        for quarter in range(4)
    ]


def _fmp_quarterly_cashflow_response(ticker: str = "AAPL", da: int = 3_000_000_000) -> list[dict]:
    """Mock FMP quarterly cash-flow rows — the authoritative D&A source for the
    TTM snapshot (the income statement leaves the freshest quarter's D&A at 0)."""
    return [
        {
            "date": f"2026-0{quarter + 1}-28",
            "symbol": ticker,
            "depreciationAndAmortization": da,
            "operatingCashFlow": 28_000_000_000,
        }
        for quarter in range(4)
    ]


def _fmp_balance_response(ticker: str = "AAPL") -> list[dict]:
    return [
        {
            "date": "2025-09-30",
            "symbol": ticker,
            "totalDebt": 111_088_000_000,
            "cashAndCashEquivalents": 29_965_000_000,
            "totalStockholdersEquity": 56_950_000_000,
        }
    ]


def _fmp_profile_response(
    ticker: str = "AAPL", currency: str = "USD", country: str = "US"
) -> list[dict]:
    return [
        {
            "symbol": ticker,
            "mktCap": 2_620_000_000_000,
            "beta": 1.24,
            "price": 175.0,
            "volAvg": 54_000_000,
            "companyName": "Apple Inc.",
            "industry": "Consumer Electronics",
            "sector": "Technology",
            "exchange": "NASDAQ",
            "currency": currency,
            "country": country,
        }
    ]


def _mock_response(json_data, status_code=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


class TestFMPFetch:
    @pytest.mark.asyncio
    async def test_fetch_financials_returns_normalized_keys(self, provider):
        """FMP-specific keys are normalized to common format."""
        responses = [
            _mock_response(_fmp_quarterly_income_response()),
            _mock_response(_fmp_balance_response()),
            _mock_response(_fmp_quarterly_cashflow_response()),
            _mock_response(_fmp_profile_response()),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "financials")

        assert result.provider == "fmp"
        assert result.ticker == "AAPL"
        assert result.data_type == "financials"
        # Key normalization checks
        assert result.data["period_basis"] == "ttm"
        assert result.data["revenue"] == 400_000_000_000
        # EBITDA is the operating caliber: OI 100B + D&A 12B = 112B, NOT FMP's
        # raw ebitda field sum (120B).
        assert result.data["ebitda"] == 112_000_000_000
        assert result.data["operating_income"] == 100_000_000_000
        assert result.data["income_tax_expense"] == 8_000_000_000
        assert result.data["depreciation_amortization"] == 12_000_000_000
        assert result.data["rd_expense"] == 28_000_000_000
        assert result.data["sga_expense"] == 24_000_000_000
        assert result.data["interest_expense"] == 4_000_000_000
        assert result.data["total_debt"] == 111_088_000_000
        assert result.data["total_cash"] == 29_965_000_000
        assert result.data["market_cap"] == 2_620_000_000_000
        # Currency tags must be emitted for cross-border FX normalization.
        assert result.data["financial_currency"] == "USD"
        assert result.data["quote_currency"] == "USD"
        assert result.data["country"] == "US"

    @pytest.mark.asyncio
    async def test_missing_balance_items_stay_none_not_zero(self, provider):
        """A balance sheet that omits totalDebt / cash must yield None, not 0, so
        enterprise value is left undefined rather than fabricated (market_cap + 0
        - 0). Regression for the silent debt/cash → 0 default that poisoned EV and
        every EV-based multiple."""
        balance_without_debt = [{"date": "2025-09-30", "symbol": "AAPL"}]
        responses = [
            _mock_response(_fmp_quarterly_income_response()),
            _mock_response(balance_without_debt),
            _mock_response(_fmp_quarterly_cashflow_response()),
            _mock_response(_fmp_profile_response()),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "financials")
        assert result.data["total_debt"] is None
        assert result.data["total_cash"] is None

    @pytest.mark.asyncio
    async def test_fetch_financials_tags_foreign_adr_currency(self, provider):
        """ADR regression (verified against ~/.finrobot cache 2026-05-29): FMP
        reports a foreign issuer's income statement in its home currency
        (reportedCurrency=TWD for TSM) while the ADR quote is USD. The provider
        MUST surface both so extract_company_financials + fx_normalize convert
        before EV/EBITDA — otherwise a TWD EBITDA divides a USD market cap and
        produces the sub-1x garbage the sanity floor only partly catches."""
        responses = [
            _mock_response(_fmp_quarterly_income_response("TSM", reported_currency="TWD")),
            _mock_response(_fmp_balance_response("TSM")),
            _mock_response(_fmp_quarterly_cashflow_response("TSM")),
            _mock_response(_fmp_profile_response("TSM", currency="USD", country="TW")),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("TSM", "financials")

        assert result.data["financial_currency"] == "TWD"
        assert result.data["quote_currency"] == "USD"
        assert result.data["country"] == "TW"

        # End-to-end: extract_company_financials must resolve reporting_currency
        # from the provider dict (the gap this fix closes — it used to default USD).
        # ADR-0006: extractor now accepts NormalizedFinancials; wrap with normalize_financials.
        from finrobot.engine.compute.extractor import extract_company_financials
        from finrobot.engine.data.normalize.financials import normalize_financials

        company = extract_company_financials(normalize_financials(result))
        assert company.reporting_currency == "TWD"
        assert company.quote_currency == "USD"

    @pytest.mark.asyncio
    async def test_fetch_unsupported_data_type_raises(self, provider):
        with pytest.raises(ProviderError, match="not supported"):
            await provider.fetch("AAPL", "unknown_type")

    @pytest.mark.asyncio
    async def test_api_error_raises_provider_error(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "403", request=MagicMock(), response=MagicMock(status_code=403)
                )
            ),
        ):
            with pytest.raises(ProviderError):
                await provider.fetch("AAPL", "financials")

    @pytest.mark.asyncio
    async def test_timeout_raises_provider_error(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(side_effect=httpx.TimeoutException("timeout")),
        ):
            with pytest.raises(ProviderError, match="timeout"):
                await provider.fetch("AAPL", "financials")


def _fmp_multi_year_income(ticker="AAPL", years=3):
    base_revenue = 394_328_000_000
    return [
        {
            "date": f"{2024 - i}-09-30",
            "symbol": ticker,
            "revenue": base_revenue - i * 10_000_000_000,
            "ebitda": 130_000_000_000 - i * 5_000_000_000,
            "netIncome": 97_000_000_000 - i * 3_000_000_000,
            "grossProfit": 181_000_000_000 - i * 4_000_000_000,
            "operatingIncome": 119_000_000_000 - i * 3_000_000_000,
            "eps": 6.15 - i * 0.4,
            "epsdiluted": 6.10 - i * 0.4,
            "depreciationAndAmortization": 11_000_000_000,
            "researchAndDevelopmentExpenses": 30_000_000_000,
            "sellingGeneralAndAdministrative": 25_000_000_000,
            "interestExpense": 3_500_000_000,
        }
        for i in range(years)
    ]


def _fmp_multi_year_cashflow(ticker="AAPL", years=3):
    """Cash-flow rows aligned by fiscal-year date to _fmp_multi_year_income."""
    return [
        {
            "date": f"{2024 - i}-09-30",
            "symbol": ticker,
            "operatingCashFlow": 110_000_000_000 - i * 5_000_000_000,
            "netCashProvidedByOperatingActivities": 110_000_000_000 - i * 5_000_000_000,
            # FMP reports capex as a negative (cash outflow); provider must abs() it.
            "capitalExpenditure": -(10_000_000_000 + i * 500_000_000),
            "changeInWorkingCapital": -2_000_000_000 + i * 300_000_000,
            # Investing/financing are reported as signed totals (typically negative).
            # FMP's actual field name misspells "Activities" as "Activites".
            "netCashUsedForInvestingActivites": -(8_000_000_000 + i * 400_000_000),
            "netCashUsedProvidedByFinancingActivities": -(95_000_000_000 - i * 3_000_000_000),
            "depreciationAndAmortization": 11_000_000_000,
        }
        for i in range(years)
    ]


class TestFMPFetchHistorical:
    @pytest.mark.asyncio
    async def test_fetch_with_years_packs_yearly_data(self, provider):
        # Call order for years>1: income, balance, cash-flow, profile.
        responses = [
            _mock_response(_fmp_multi_year_income("AAPL", 3)),
            _mock_response(_fmp_balance_response()),
            _mock_response(_fmp_multi_year_cashflow("AAPL", 3)),
            _mock_response(_fmp_profile_response()),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "financials", years=3)
        assert isinstance(result, DataResult)
        assert "yearly_data" in result.data
        assert len(result.data["yearly_data"]) == 3
        assert result.data["yearly_data"][0]["revenue"] == 394_328_000_000
        # FCF trio must be populated from the cash-flow statement, with capex
        # sign-normalized to a positive magnitude (DCF FCF = OCF − CapEx − ΔNWC).
        y0 = result.data["yearly_data"][0]
        assert y0["operating_cash_flow"] == 110_000_000_000
        assert y0["capital_expenditure"] == 10_000_000_000
        assert y0["change_in_working_capital"] == -2_000_000_000
        # fiscal_year must be present and non-None in every yearly entry;
        # historical_loaders.py line 55 does `data.get("fiscal_year") or data.get("date")`
        # — a missing fiscal_year causes all years to be skipped → band.sample_count == 0.
        for entry in result.data["yearly_data"]:
            assert entry.get("fiscal_year") is not None, (
                f"yearly entry missing fiscal_year: {entry}"
            )

    @pytest.mark.asyncio
    async def test_yearly_data_carries_full_historical_schema(self, provider):
        """门一 Step 2: historical yearly_data must carry every field the
        HistoricalMetrics consumer needs (eps, absolute gross_profit /
        operating_income, and investing/financing cash flow) — not just the
        FCF trio. Otherwise switching historical_extractor onto the DataLayer
        drops EPS history and the income-statement absolutes."""
        responses = [
            _mock_response(_fmp_multi_year_income("AAPL", 3)),
            _mock_response(_fmp_balance_response()),
            _mock_response(_fmp_multi_year_cashflow("AAPL", 3)),
            _mock_response(_fmp_profile_response()),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "financials", years=3)
        y0 = result.data["yearly_data"][0]
        # Income-statement absolutes (consumer derives cogs = revenue - gross_profit)
        assert y0["gross_profit"] == 181_000_000_000
        assert y0["operating_income"] == 119_000_000_000
        # Basic EPS — feeds data_processor share derivation + EpsPeChart
        assert y0["eps"] == pytest.approx(6.15)
        # Full cash-flow statement (investing/financing signed, not abs)
        assert y0["investing_cash_flow"] == -8_000_000_000
        assert y0["financing_cash_flow"] == -95_000_000_000

    @pytest.mark.asyncio
    async def test_missing_cashflow_row_yields_none_not_crash(self, provider):
        """If the cash-flow statement is short a year, that year's FCF fields
        are None rather than crashing the whole historical fetch."""
        responses = [
            _mock_response(_fmp_multi_year_income("AAPL", 3)),
            _mock_response(_fmp_balance_response()),
            _mock_response(_fmp_multi_year_cashflow("AAPL", 1)),  # only newest year
            _mock_response(_fmp_profile_response()),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "financials", years=3)
        years = result.data["yearly_data"]
        assert years[0]["operating_cash_flow"] == 110_000_000_000
        # Years 2 and 3 have no matching cash-flow row → None, not a KeyError.
        assert years[1]["operating_cash_flow"] is None
        assert years[1]["capital_expenditure"] is None
        assert years[2]["change_in_working_capital"] is None

    @pytest.mark.asyncio
    async def test_fetch_without_years_returns_flat(self, provider):
        responses = [
            _mock_response(_fmp_quarterly_income_response()),
            _mock_response(_fmp_balance_response()),
            _mock_response(_fmp_quarterly_cashflow_response()),
            _mock_response(_fmp_profile_response()),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "financials")
        assert isinstance(result, DataResult)
        assert "yearly_data" not in result.data
        assert result.data["revenue"] == 400_000_000_000
        # Single-year flat result must also carry fiscal_year
        assert result.data.get("fiscal_year") is not None

    @pytest.mark.asyncio
    async def test_ttm_da_sourced_from_cashflow_not_income(self, provider):
        """Reproduces the TSLA caliber bug: FMP's income statement drops D&A to
        0 for the freshest quarter while the cash-flow statement carries it. TTM
        D&A and the recomputed EBITDA must come from cash flow, not the income
        sum, otherwise EV/EBITDA reads inflated."""
        income = _fmp_quarterly_income_response()
        income[0]["depreciationAndAmortization"] = 0  # freshest quarter dropped
        responses = [
            _mock_response(income),
            _mock_response(_fmp_balance_response()),
            _mock_response(_fmp_quarterly_cashflow_response(da=3_000_000_000)),
            _mock_response(_fmp_profile_response()),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "financials")
        # Income-statement D&A sum would be 9B (3 quarters); cash flow gives 12B.
        assert result.data["depreciation_amortization"] == 12_000_000_000
        # Operating EBITDA = OI 100B + cash-flow D&A 12B = 112B (not 109B).
        assert result.data["ebitda"] == 112_000_000_000

    @pytest.mark.asyncio
    async def test_ttm_tsla_real_world_caliber(self, provider):
        """External-source anchor (FMP API pulled 2026-05-28): TSLA Q1 2026
        income-statement D&A is 0 (provider quirk for the freshest quarter),
        while cash-flow D&A is intact. Verifies the recomputed EBITDA matches
        the externally-verified ground truth, not the contaminated IS-derived
        value the artifact-as-shipped exposed in the 2026-05-28 audit."""
        # TSLA actual quarterly cash-flow D&A (FMP /cash-flow-statement, $B):
        # Q1 2026 1.590, Q4 2025 1.643, Q3 2025 1.625, Q2 2025 1.433 → 6.291B
        cf_da_tsla = [1_590_000_000, 1_643_000_000, 1_625_000_000, 1_433_000_000]
        # Operating income (FMP /income-statement, $B):
        # Q1 2026 0.941, Q4 2025 1.409, Q3 2025 1.624, Q2 2025 0.923 → 4.897B
        op_inc_tsla = [941_000_000, 1_409_000_000, 1_624_000_000, 923_000_000]
        # FMP's IS-ebitda field per quarter ($B): 0.840, 2.909, 3.660, 3.068
        # → sums to 10.477B (the WRONG value the 2026-05-28 artifact displayed).
        is_ebitda_tsla = [840_000_000, 2_909_000_000, 3_660_000_000, 3_068_000_000]
        # FMP's IS-D&A per quarter ($B): 0.000, 1.643, 1.625, 1.433 → 4.701B
        is_da_tsla = [0, 1_643_000_000, 1_625_000_000, 1_433_000_000]

        income = [
            {
                "date": f"2026-0{4 - i}-30",
                "symbol": "TSLA",
                "revenue": 24_000_000_000,
                "ebitda": is_ebitda_tsla[i],
                "netIncome": 1_000_000_000,
                "grossProfit": 4_500_000_000,
                "operatingIncome": op_inc_tsla[i],
                "depreciationAndAmortization": is_da_tsla[i],
                "incomeTaxExpense": 100_000_000,
                "researchAndDevelopmentExpenses": 1_000_000_000,
                "sellingGeneralAndAdministrative": 1_300_000_000,
                "interestExpense": 0,
            }
            for i in range(4)
        ]
        cashflow = [
            {
                "date": f"2026-0{4 - i}-30",
                "symbol": "TSLA",
                "depreciationAndAmortization": cf_da_tsla[i],
                "operatingCashFlow": 4_000_000_000,
            }
            for i in range(4)
        ]
        responses = [
            _mock_response(income),
            _mock_response(_fmp_balance_response("TSLA")),
            _mock_response(cashflow),
            _mock_response(_fmp_profile_response("TSLA")),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("TSLA", "financials")

        # External truth from FMP API pull on 2026-05-28:
        #   TTM cash-flow D&A = $6.291B (Q1 1.590 + Q4 1.643 + Q3 1.625 + Q2 1.433)
        #   TTM operating income = $4.897B
        #   Operating EBITDA = OI + D&A = $11.188B
        # Pre-fix artifact (art_2026-05-28T12:17:33) shipped EBITDA = $10.477B
        # (FMP raw IS-ebitda field sum) and D&A = $4.701B (IS sum, Q1 missing).
        assert result.data["depreciation_amortization"] == 6_291_000_000
        assert result.data["operating_income"] == 4_897_000_000
        assert result.data["ebitda"] == 11_188_000_000
        # The wrong values the audit caught — make sure we never re-display these.
        assert result.data["ebitda"] != 10_477_000_000
        assert result.data["depreciation_amortization"] != 4_701_000_000


class TestFMPQuote:
    """门一 Step 3: lightweight QUOTE path via /quote/{ticker} (no OHLC pull)."""

    def test_quote_in_capabilities(self, provider):
        assert "quote" in provider.capabilities()

    @pytest.mark.asyncio
    async def test_quote_returns_price(self, provider):
        resp = _mock_response([{"symbol": "AAPL", "price": 187.5, "exchange": "NASDAQ"}])
        with patch.object(provider, "_get", AsyncMock(return_value=resp)):
            result = await provider.fetch("AAPL", "quote")
        assert result.data == {"price": 187.5}
        assert result.data_type == "quote"

    @pytest.mark.asyncio
    async def test_quote_empty_response_raises(self, provider):
        with patch.object(provider, "_get", AsyncMock(return_value=_mock_response([]))):
            with pytest.raises(ProviderError):
                await provider.fetch("AAPL", "quote")


class TestFMPProviderInterface:
    def test_name(self, provider):
        assert provider.name == "fmp"

    def test_capabilities(self, provider):
        caps = provider.capabilities()
        assert "financials" in caps
        # price was added when yfinance rate-limit fallback became necessary
        # — exercise here so a future trim of _SUPPORTED can't silently
        # break the multi-provider PRICE fallback chain.
        assert "price" in caps


def _fmp_news_response(ticker="AAPL"):
    return [
        {
            "title": "Apple Q4 earnings beat",
            "site": "Reuters",
            "publishedDate": "2024-10-31T16:00:00.000Z",
            "url": "https://example.com/1",
        },
        {
            "title": "iPhone 16 sales strong",
            "site": "Bloomberg",
            "publishedDate": "2024-10-30T14:00:00.000Z",
            "url": "https://example.com/2",
        },
    ]


class TestFMPNews:
    @pytest.mark.asyncio
    async def test_fetch_news_returns_news_items(self, provider):
        with patch.object(
            provider, "_get", AsyncMock(return_value=_mock_response(_fmp_news_response()))
        ):
            result = await provider.fetch("AAPL", "news")
        assert isinstance(result, DataResult)
        assert result.data_type == "news"
        items = result.data["news_items"]
        assert len(items) == 2
        assert items[0]["title"] == "Apple Q4 earnings beat"
        assert items[0]["source"] == "Reuters"

    @pytest.mark.asyncio
    async def test_news_in_capabilities(self, provider):
        assert "news" in provider.capabilities()


def _fmp_earnings_response(ticker="AAPL"):
    return [
        {
            "date": "2024-10-31",
            "symbol": ticker,
            "epsActual": 1.64,
            "epsEstimated": 1.60,
            "revenueActual": 94_930_000_000,
            "revenueEstimated": 94_210_000_000,
        },
        {
            "date": "2024-07-31",
            "symbol": ticker,
            "epsActual": 1.40,
            "epsEstimated": 1.35,
            "revenueActual": 85_778_000_000,
            "revenueEstimated": 84_530_000_000,
        },
    ]


class TestFMPEarnings:
    @pytest.mark.asyncio
    async def test_fetch_earnings_returns_normalized_keys(self, provider):
        """FMP earnings-surprises response is normalized to common format."""
        with patch.object(
            provider, "_get", AsyncMock(return_value=_mock_response(_fmp_earnings_response()))
        ):
            result = await provider.fetch("AAPL", "earnings")
        assert result.provider == "fmp"
        assert result.data_type == "earnings"
        history = result.data["earnings_history"]
        assert len(history) == 2
        first = history[0]
        assert first["date"] == "2024-10-31"
        assert first["eps_actual"] == 1.64
        assert first["eps_estimated"] == 1.60
        assert first["revenue_actual"] == 94_930_000_000
        assert first["revenue_estimated"] == 94_210_000_000

    @pytest.mark.asyncio
    async def test_earnings_in_capabilities(self, provider):
        assert "earnings" in provider.capabilities()

    @pytest.mark.asyncio
    async def test_earnings_skips_entries_with_null_eps(self, provider):
        """Entries without epsActual or epsEstimated should be filtered out."""
        raw = [
            {
                "date": "2024-10-31",
                "epsActual": 1.64,
                "epsEstimated": 1.60,
                "revenueActual": 90e9,
                "revenueEstimated": 89e9,
            },
            {
                "date": "2024-07-31",
                "epsActual": None,
                "epsEstimated": 1.35,
                "revenueActual": 85e9,
                "revenueEstimated": 84e9,
            },
        ]
        with patch.object(provider, "_get", AsyncMock(return_value=_mock_response(raw))):
            result = await provider.fetch("AAPL", "earnings")
        assert len(result.data["earnings_history"]) == 1


def _fmp_analyst_estimates_response(ticker: str = "AAPL") -> list[dict]:
    """Mock FMP /analyst-estimates response (annual, farthest-future first)."""
    return [
        {"date": "2028-09-30", "symbol": ticker, "estimatedEpsAvg": 11.0},
        {"date": "2027-09-30", "symbol": ticker, "estimatedEpsAvg": 9.8},
        {
            "date": "2026-09-30",
            "symbol": ticker,
            "estimatedRevenueAvg": 4.65e11,
            "estimatedEbitdaAvg": 1.55e11,
            "estimatedEpsAvg": 8.6,
        },
    ]


class TestFMPForwardEstimates:
    @pytest.mark.asyncio
    async def test_fetch_forward_estimates_ships_raw_rows(self, provider):
        """Provider returns FMP rows verbatim under 'rows' — it never derives
        a forward number itself (that's the red-line leaf's job)."""
        with patch.object(
            provider,
            "_get",
            AsyncMock(return_value=_mock_response(_fmp_analyst_estimates_response())),
        ):
            result = await provider.fetch("AAPL", "forward_estimates")
        assert result.provider == "fmp"
        assert result.data_type == "forward_estimates"
        rows = result.data["rows"]
        assert len(rows) == 3
        assert rows[0]["date"] == "2028-09-30"  # order preserved; leaf picks FY1
        assert rows[2]["estimatedEpsAvg"] == 8.6

    @pytest.mark.asyncio
    async def test_forward_estimates_in_capabilities(self, provider):
        assert "forward_estimates" in provider.capabilities()

    @pytest.mark.asyncio
    async def test_non_list_response_yields_empty_rows(self, provider):
        """A malformed (non-list) FMP body degrades to empty rows, never raises."""
        with patch.object(
            provider, "_get", AsyncMock(return_value=_mock_response({"error": "not found"}))
        ):
            result = await provider.fetch("AAPL", "forward_estimates")
        assert result.data["rows"] == []


def _fmp_quote_response(ticker: str = "AAPL", price: float = 175.0) -> list[dict]:
    """Mock FMP /quote/{ticker} response."""
    return [
        {
            "symbol": ticker,
            "name": "Apple Inc.",
            "price": price,
            "exchange": "NASDAQ",
            "exchangeShortName": "NASDAQ",
            "marketCap": 2_620_000_000_000,
            "volume": 54_000_000,
        }
    ]


def _fmp_historical_price_response(days: int = 3) -> dict:
    """Mock FMP /historical-price-full/{ticker} response.

    FMP returns newest-first; the provider reverses to match yfinance's
    oldest-first ordering. We hand back newest-first here to exercise that.
    """
    return {
        "symbol": "AAPL",
        "historical": [
            {
                "date": "2026-05-23",
                "open": 174.0,
                "high": 176.0,
                "low": 173.5,
                "close": 175.0,
                "volume": 50_000_000,
            },
            {
                "date": "2026-05-22",
                "open": 172.0,
                "high": 174.5,
                "low": 171.0,
                "close": 174.0,
                "volume": 48_000_000,
            },
            {
                "date": "2026-05-21",
                "open": 170.0,
                "high": 172.5,
                "low": 169.5,
                "close": 172.0,
                "volume": 45_000_000,
            },
        ][:days],
    }


class TestFMPPrice:
    """PRICE fallback path — exists so yfinance rate-limit failures hit FMP
    next instead of falling straight through to the 20h-stale-cache warning
    the user saw in production (2026-05-25)."""

    @pytest.mark.asyncio
    async def test_fetch_price_returns_yfinance_compatible_shape(self, provider):
        responses = [
            _mock_response(_fmp_quote_response("AAPL", price=175.5)),
            _mock_response(_fmp_historical_price_response(days=3)),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "price")

        assert isinstance(result, DataResult)
        assert result.provider == "fmp"
        assert result.ticker == "AAPL"
        assert result.data_type == "price"
        assert result.data["current_price"] == 175.5
        assert result.data["exchange"] == "NASDAQ"
        # Oldest first — extract_financial_data relies on this ordering when
        # it pulls 52w high/low from the close column.
        history = result.data["price_history"]
        assert [p["date"] for p in history] == ["2026-05-21", "2026-05-22", "2026-05-23"]
        assert history[0]["close"] == 172.0
        assert history[-1]["close"] == 175.0

    @pytest.mark.asyncio
    async def test_fetch_price_requests_calendar_year_ohlc(self, provider):
        """Regression: timeseries=365 counts *trading* days (~17 months), which
        let early-2025 lows leak into the 52-week range. Must request a ~1yr
        calendar date range, and must NOT pass serietype=line (which strips the
        intraday high/low the 52-week high/low depend on)."""
        from datetime import date as _date

        get_mock = AsyncMock(
            side_effect=[
                _mock_response(_fmp_quote_response("AAPL", price=175.5)),
                _mock_response(_fmp_historical_price_response(days=3)),
            ]
        )
        with patch.object(provider, "_get", get_mock):
            await provider.fetch("AAPL", "price")

        hist_call = next(c for c in get_mock.call_args_list if "historical-price-full" in c.args[0])
        params = hist_call.kwargs.get("params", {})
        assert "serietype" not in params, "serietype=line strips intraday high/low"
        assert "timeseries" not in params, "trading-day count ≠ calendar year"
        assert "from" in params and "to" in params, "must request a calendar-day range"
        span = (_date.fromisoformat(params["to"]) - _date.fromisoformat(params["from"])).days
        assert 360 <= span <= 372, f"expected ~1yr window, got {span}d"

    @pytest.mark.asyncio
    async def test_fetch_price_empty_quote_raises(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(side_effect=[_mock_response([]), _mock_response({"historical": []})]),
        ):
            with pytest.raises(ProviderError, match="no data"):
                await provider.fetch("DELISTED", "price")

    @pytest.mark.asyncio
    async def test_fetch_price_missing_price_field_raises(self, provider):
        responses = [
            _mock_response([{"symbol": "BAD", "exchange": "NASDAQ"}]),  # no price
            _mock_response({"historical": []}),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            with pytest.raises(ProviderError, match="no price field"):
                await provider.fetch("BAD", "price")

    @pytest.mark.asyncio
    async def test_fetch_price_handles_empty_history(self, provider):
        """No history rows → empty price_history list, not a crash."""
        responses = [
            _mock_response(_fmp_quote_response("NEW", price=10.0)),
            _mock_response({"symbol": "NEW", "historical": []}),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("NEW", "price")
        assert result.data["current_price"] == 10.0
        assert result.data["price_history"] == []


class TestFMPNetworkErrors:
    """New catch branches: ConnectError / RemoteProtocolError / ReadError / WriteError."""

    @pytest.mark.asyncio
    async def test_connect_error_raises_provider_error(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(side_effect=httpx.ConnectError("connection refused")),
        ):
            with pytest.raises(ProviderError, match="network error"):
                await provider.fetch("AAPL", "financials")

    @pytest.mark.asyncio
    async def test_remote_protocol_error_raises_provider_error(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(side_effect=httpx.RemoteProtocolError("unexpected EOF")),
        ):
            with pytest.raises(ProviderError, match="network error"):
                await provider.fetch("AAPL", "financials")

    @pytest.mark.asyncio
    async def test_read_error_raises_provider_error(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(side_effect=httpx.ReadError("read failed")),
        ):
            with pytest.raises(ProviderError, match="network error"):
                await provider.fetch("AAPL", "news")

    @pytest.mark.asyncio
    async def test_write_error_raises_provider_error(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(side_effect=httpx.WriteError("write failed")),
        ):
            with pytest.raises(ProviderError, match="network error"):
                await provider.fetch("AAPL", "earnings")


class TestFMPRateLimiter:
    def test_provider_has_rate_limit_attributes(self, provider):
        """Rate limiter requires _lock and _last_call on every instance."""
        import asyncio

        assert hasattr(provider, "_lock")
        assert isinstance(provider._lock, asyncio.Lock)
        assert hasattr(provider, "_last_call")
        assert isinstance(provider._last_call, float)

    @pytest.mark.asyncio
    async def test_rate_limiter_sleeps_on_rapid_calls(self, provider, monkeypatch):
        """Second call within MIN_INTERVAL must trigger asyncio.sleep."""
        import asyncio
        import time
        from finrobot.engine.data.providers.fmp_provider import _MIN_INTERVAL

        sleep_durations: list[float] = []

        async def mock_sleep(secs: float) -> None:
            sleep_durations.append(secs)

        monkeypatch.setattr(asyncio, "sleep", mock_sleep)

        # Simulate last call happening just now (elapsed << _MIN_INTERVAL)
        provider._last_call = time.monotonic()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        # Provider now owns a long-lived httpx client (instantiated in __init__)
        # so we monkeypatch the per-instance .get instead of httpx.AsyncClient.
        provider._client.get = AsyncMock(return_value=mock_resp)

        await provider._get("/test")

        assert len(sleep_durations) == 1
        assert sleep_durations[0] <= _MIN_INTERVAL
        assert sleep_durations[0] > 0
