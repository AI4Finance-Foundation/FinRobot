# P2c — FinRobot Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring FinRobot's equity research output quality to parity with FinRobot (charts, reports, forecasting, catalyst analysis, data cleaning) while maintaining deterministic computation superiority.

**Architecture:** Three sequential phases — Phase A builds backend compute (data cleaning, historical metrics, forecasting, catalyst analysis, valuation synthesis, news); Phase B adds matplotlib charts + Jinja2 reports + API endpoints; Phase C adds Desktop UI with recharts, Zustand state, and settings. Each phase produces independently testable output.

**Tech Stack:** Python (matplotlib, jinja2, weasyprint), React 19 (recharts, zustand, tailwindcss@4, electron-store), vitest + @testing-library/react

**Spec:** `specs/P2c.md`

**Dev rules:** Read `CLAUDE.md` before starting. Key rules: one file at a time (write → test → commit → next), follow ARCHITECTURE.md, no untyped `dict` across boundaries, tests must verify correctness not just "runs".

---

## File Map

### Phase A — Backend Compute (Files 0a–8)

| File | Action | Responsibility |
|------|--------|----------------|
| `finrobot/engine/data/layer.py` | Modify | Add `fetch_historical()` method |
| `finrobot/engine/data/providers/fmp_provider.py` | Modify | Support `years` kwarg for multi-year data |
| `finrobot/engine/data/providers/finnhub_provider.py` | Modify | Support `years` kwarg + news capability |
| `finrobot/engine/data/providers/yfinance_provider.py` | Modify | Support `years` kwarg via `income_stmt` DataFrame |
| `finrobot/engine/compute/clean.py` | Create | `clean_financial_number()`, `FIELD_ALIASES`, `normalize_field_names()` |
| `finrobot/engine/models/financial.py` | Modify | Add 8 new Pydantic models |
| `finrobot/engine/compute/data_processor.py` | Create | `extract_historical_metrics()`, `forecast_financials()`, `calculate_cagr()` |
| `finrobot/engine/compute/catalyst.py` | Create | `CatalystAnalyzer` class with sorting/filtering |
| `finrobot/engine/compute/valuation_synthesis.py` | Create | `synthesize_valuations()` weighted average |
| `finrobot/engine/data/providers/fmp_provider.py` | Modify | Add `"news"` capability |
| `finrobot/engine/data/providers/finnhub_provider.py` | Modify | Add `"news"` capability |
| `finrobot/engine/compute/news.py` | Create | `RawNewsItem`, `NewsItem`, `fetch_news()`, `classify_news()` |

### Phase B — Charts + Reports (Files 9–14)

| File | Action | Responsibility |
|------|--------|----------------|
| `finrobot/engine/charts/__init__.py` | Create | Package init |
| `finrobot/engine/charts/base.py` | Create | `ChartConfig`, `render_to_base64()`, `validate_png()`, `ChartDataPoint`, `StepChartData` |
| `finrobot/engine/charts/revenue_ebitda.py` | Create | Revenue & EBITDA bar chart |
| `finrobot/engine/charts/margin_trend.py` | Create | Multi-line margin chart |
| `finrobot/engine/charts/peer_comparison.py` | Create | Grouped bar chart |
| `finrobot/engine/charts/sensitivity.py` | Create | WACC×TG heatmap |
| `finrobot/engine/charts/football_field.py` | Create | Horizontal range bars |
| `finrobot/engine/charts/price_chart.py` | Create | Price line + volume bars |
| `finrobot/engine/charts/eps_pe.py` | Create | Dual-axis EPS/PE chart |
| `finrobot/engine/charts/waterfall.py` | Create | Valuation waterfall |
| `finrobot/engine/charts/radar.py` | Create | Financial radar chart |
| `finrobot/engine/reports/__init__.py` | Create | Package init |
| `finrobot/engine/reports/html_renderer.py` | Create | Jinja2 report generator |
| `finrobot/engine/reports/templates/equity_research.html` | Create | 5-page Jinja2 template |
| `finrobot/engine/reports/templates/comps.html` | Create | Comps single-page template |
| `finrobot/engine/reports/templates/dcf.html` | Create | DCF single-page template |
| `finrobot/engine/reports/pdf_renderer.py` | Create | HTML → PDF conversion |
| `finrobot/server.py` | Modify | Add `/api/report/html`, `/api/report/pdf`, SSE `chart_data` |

### Phase C — Desktop UI (Files 15–21)

| File | Action | Responsibility |
|------|--------|----------------|
| `desktop/package.json` | Modify | Add recharts, tailwindcss@4, zustand, electron-store, vitest |
| `desktop/src/index.css` | Modify | Add `@import "tailwindcss"` |
| `desktop/src/stores/appStore.ts` | Create | Zustand global state |
| `desktop/src/components/Layout.tsx` | Create | Left/right split layout |
| `desktop/src/components/DataPanel.tsx` | Create | Right-side data panel |
| `desktop/src/components/charts/RevenueEbitdaChart.tsx` | Create | recharts bar chart |
| `desktop/src/components/charts/MarginTrendChart.tsx` | Create | recharts line chart |
| `desktop/src/components/charts/PeerComparisonChart.tsx` | Create | recharts grouped bars |
| `desktop/src/components/charts/SensitivityHeatmap.tsx` | Create | recharts heatmap |
| `desktop/src/components/charts/FootballField.tsx` | Create | recharts horizontal bars |
| `desktop/src/components/charts/PriceChart.tsx` | Create | recharts line + volume |
| `desktop/src/components/charts/EpsPeChart.tsx` | Create | recharts dual-axis |
| `desktop/src/components/charts/WaterfallChart.tsx` | Create | recharts waterfall |
| `desktop/src/components/charts/RadarChart.tsx` | Create | recharts radar |
| `desktop/src/components/SettingsView.tsx` | Create | API key + model settings |
| `desktop/src/components/ResearchView.tsx` | Modify | Add chart rendering |
| `desktop/src/components/DCFView.tsx` | Modify | Add heatmap + waterfall |
| `desktop/src/components/CompsView.tsx` | Modify | Add peer chart |
| `desktop/src/App.tsx` | Modify | Add Settings tab, Layout, Zustand |

---

## Phase A: Backend Compute

### Task 1: DataLayer `fetch_historical()` (File 0a)

**Files:**
- Modify: `finrobot/engine/data/layer.py`
- Test: `tests/unit/test_data_layer.py`

**Context:** Current `DataLayer.fetch()` returns a single `DataResult`. We need `fetch_historical()` that returns `list[DataResult]` for multi-year data. **Important:** The `DataProvider.fetch()` return type must NOT change — it always returns `DataResult` (single). When `years` kwarg is passed, providers pack multi-year data inside `DataResult.data["yearly_data"]` (a list of dicts). `DataLayer.fetch_historical()` then splits this into `list[DataResult]`.

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/unit/test_data_layer.py

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

from finrobot.engine.data.layer import DataLayer
from finrobot.engine.data.cache import DataCache
from finrobot.engine.data.interface import DataResult, DataProvider, ProviderError


def _make_data_result(ticker: str = "AAPL", year: int = 2024) -> DataResult:
    return DataResult(
        data={"revenue": 100e9 + year, "year": year},
        provider="mock",
        ticker=ticker,
        data_type="financials",
        timestamp=datetime.now(tz=timezone.utc),
    )


def _make_multi_year_data_result(ticker: str = "AAPL", years: int = 5) -> DataResult:
    """Provider packs multi-year data inside a single DataResult."""
    yearly = [{"revenue": 100e9 + y, "year": 2020 + y} for y in range(years)]
    return DataResult(
        data={"yearly_data": yearly},
        provider="mock",
        ticker=ticker,
        data_type="financials",
        timestamp=datetime.now(tz=timezone.utc),
    )


class TestFetchHistorical:
    @pytest.mark.asyncio
    async def test_fetch_historical_returns_list_of_data_results(self):
        """fetch_historical should split yearly_data into list[DataResult]."""
        mock_provider = MagicMock(spec=DataProvider)
        mock_provider.name = "mock"
        mock_provider.capabilities.return_value = ["financials"]
        mock_provider.fetch = AsyncMock(return_value=_make_multi_year_data_result("AAPL", 5))

        mock_cache = MagicMock(spec=DataCache)
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()

        layer = DataLayer(providers=[mock_provider], cache=mock_cache)
        results = await layer.fetch_historical("financials", "AAPL", years=5)

        assert isinstance(results, list)
        assert len(results) == 5
        mock_provider.fetch.assert_called_once_with("AAPL", "financials", years=5)

    @pytest.mark.asyncio
    async def test_fetch_historical_falls_back_to_next_provider(self):
        """If first provider fails, try next provider."""
        failing_provider = MagicMock(spec=DataProvider)
        failing_provider.name = "failing"
        failing_provider.capabilities.return_value = ["financials"]
        failing_provider.fetch = AsyncMock(side_effect=ProviderError("down"))

        good_provider = MagicMock(spec=DataProvider)
        good_provider.name = "good"
        good_provider.capabilities.return_value = ["financials"]
        good_provider.fetch = AsyncMock(return_value=_make_multi_year_data_result("AAPL", 3))

        mock_cache = MagicMock(spec=DataCache)
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()

        layer = DataLayer(providers=[failing_provider, good_provider], cache=mock_cache)
        results = await layer.fetch_historical("financials", "AAPL", years=3)

        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_fetch_historical_skips_unsupported_providers(self):
        """Providers that don't support data_type are skipped."""
        price_only = MagicMock(spec=DataProvider)
        price_only.name = "price_only"
        price_only.capabilities.return_value = ["price"]

        full = MagicMock(spec=DataProvider)
        full.name = "full"
        full.capabilities.return_value = ["financials"]
        full.fetch = AsyncMock(return_value=_make_multi_year_data_result("AAPL", 1))

        mock_cache = MagicMock(spec=DataCache)
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()

        layer = DataLayer(providers=[price_only, full], cache=mock_cache)
        results = await layer.fetch_historical("financials", "AAPL", years=1)

        assert len(results) == 1
        price_only.fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_historical_single_year_fallback(self):
        """If provider returns DataResult without yearly_data, wrap as single-element list."""
        mock_provider = MagicMock(spec=DataProvider)
        mock_provider.name = "mock"
        mock_provider.capabilities.return_value = ["financials"]
        mock_provider.fetch = AsyncMock(return_value=_make_data_result())

        mock_cache = MagicMock(spec=DataCache)
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()

        layer = DataLayer(providers=[mock_provider], cache=mock_cache)
        results = await layer.fetch_historical("financials", "AAPL", years=5)

        assert isinstance(results, list)
        assert len(results) == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_data_layer.py::TestFetchHistorical -x -v --tb=short
```
Expected: FAIL — `DataLayer` has no `fetch_historical` method.

- [ ] **Step 3: Implement `fetch_historical`**

Add to `finrobot/engine/data/layer.py` after the existing `fetch()` method:

```python
async def fetch_historical(
    self, data_type: str, ticker: str, years: int = 5, **kwargs
) -> list[DataResult]:
    """Fetch multi-year historical data.

    What this code does that raw LLM cannot: deterministic provider chain
    fallback for historical data — iterates providers in priority order,
    passes years kwarg, splits single DataResult into list[DataResult].

    Provider.fetch() always returns DataResult (interface unchanged).
    When years kwarg is passed, providers pack multi-year data inside
    DataResult.data["yearly_data"]. This method splits it into a list.
    """
    for provider in self._providers:
        if data_type not in provider.capabilities():
            continue
        try:
            result = await provider.fetch(ticker, data_type, years=years, **kwargs)
            return self._split_yearly(result)
        except ProviderError as e:
            logger.warning(
                f"Provider '{provider.name}' failed for {ticker}/{data_type} "
                f"(historical, {years}y): {e}"
            )
            continue

    msg = f"Historical data unavailable for {ticker}/{data_type}: all providers failed."
    logger.error(msg)
    return []

@staticmethod
def _split_yearly(result: DataResult) -> list[DataResult]:
    """Split a DataResult with yearly_data into list[DataResult].

    If the result has no yearly_data key, return as single-element list.
    """
    yearly = result.data.get("yearly_data")
    if not yearly or not isinstance(yearly, list):
        return [result]

    return [
        DataResult(
            data=year_data,
            provider=result.provider,
            ticker=result.ticker,
            data_type=result.data_type,
            timestamp=result.timestamp,
            warnings=result.warnings,
        )
        for year_data in yearly
    ]
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_data_layer.py -x -v --tb=short
```
Expected: ALL PASS (including existing tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && git add finrobot/engine/data/layer.py tests/unit/test_data_layer.py && git commit -m "feat(P2c-0a): add DataLayer.fetch_historical() for multi-year data"
```

---

### Task 2: FMP Provider multi-year support (File 0b)

**Files:**
- Modify: `finrobot/engine/data/providers/fmp_provider.py`
- Test: `tests/unit/test_fmp_provider.py`

**Context:** FMP API supports `?limit=N` on `/income-statement/`. When `years` kwarg is passed, fetch N years and pack them into `DataResult.data["yearly_data"]`. Provider always returns `DataResult` (interface unchanged). Existing single-year behavior must not break.

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/unit/test_fmp_provider.py

def _fmp_multi_year_income(ticker: str = "AAPL", years: int = 3) -> list[dict]:
    """Mock FMP response for multi-year income statements."""
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
            "depreciationAndAmortization": 11_000_000_000,
            "researchAndDevelopmentExpenses": 30_000_000_000,
            "sellingGeneralAndAdministrative": 25_000_000_000,
            "interestExpense": 3_500_000_000,
        }
        for i in range(years)
    ]


class TestFMPFetchHistorical:
    @pytest.mark.asyncio
    async def test_fetch_with_years_packs_yearly_data(self, provider):
        """When years kwarg is passed, DataResult.data has yearly_data list."""
        responses = [
            _mock_response(_fmp_multi_year_income("AAPL", 3)),
            _mock_response(_fmp_balance_response()),
            _mock_response(_fmp_profile_response()),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "financials", years=3)

        assert isinstance(result, DataResult)  # Always DataResult, never list
        assert "yearly_data" in result.data
        assert len(result.data["yearly_data"]) == 3
        assert result.data["yearly_data"][0]["revenue"] == 394_328_000_000

    @pytest.mark.asyncio
    async def test_fetch_without_years_returns_single_result(self, provider):
        """Default behavior unchanged: returns single DataResult with flat data."""
        responses = [
            _mock_response(_fmp_income_response()),
            _mock_response(_fmp_balance_response()),
            _mock_response(_fmp_profile_response()),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "financials")

        assert isinstance(result, DataResult)
        assert "yearly_data" not in result.data
        assert result.data["revenue"] == 394_328_000_000
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_fmp_provider.py::TestFMPFetchHistorical -x -v --tb=short
```
Expected: FAIL — current `fetch()` ignores `years` kwarg, always returns single `DataResult`.

- [ ] **Step 3: Implement multi-year support in FMP provider**

Modify `finrobot/engine/data/providers/fmp_provider.py` — replace the `fetch` method. **Return type stays `DataResult`** — multi-year data is packed inside `data["yearly_data"]`:

```python
async def fetch(self, ticker: str, data_type: str, **kwargs) -> DataResult:
    if data_type not in _SUPPORTED:
        raise ProviderError(
            f"data_type '{data_type}' is not supported by FMP. Supported: {_SUPPORTED}"
        )

    years = kwargs.get("years")
    limit = years if years else 1

    try:
        income = (
            await self._get(f"/income-statement/{ticker}", params={"limit": limit})
        ).json()
        balance = (
            await self._get(f"/balance-sheet-statement/{ticker}", params={"limit": 1})
        ).json()
        profile = (await self._get(f"/profile/{ticker}")).json()
    except httpx.TimeoutException as e:
        raise ProviderError(f"FMP timeout for '{ticker}': {e}") from e
    except httpx.HTTPStatusError as e:
        raise ProviderError(f"FMP API error for '{ticker}': {e}") from e
    except ProviderError:
        raise
    except Exception as e:
        raise ProviderError(f"FMP fetch failed for '{ticker}': {e}") from e

    bal = (balance[0] if balance else {})
    prof = (profile[0] if profile else {})

    def _build_result(inc: dict) -> DataResult:
        data = {
            "revenue": inc.get("revenue"),
            "ebitda": inc.get("ebitda"),
            "net_income": inc.get("netIncome"),
            "gross_margin": (
                inc["grossProfit"] / inc["revenue"]
                if inc.get("grossProfit") and inc.get("revenue")
                else None
            ),
            "operating_margin": (
                inc["operatingIncome"] / inc["revenue"]
                if inc.get("operatingIncome") and inc.get("revenue")
                else None
            ),
            "depreciation_amortization": inc.get("depreciationAndAmortization"),
            "rd_expense": inc.get("researchAndDevelopmentExpenses"),
            "sga_expense": inc.get("sellingGeneralAndAdministrative"),
            "interest_expense": inc.get("interestExpense"),
            "total_debt": bal.get("totalDebt", 0),
            "total_cash": bal.get("cashAndCashEquivalents", 0),
            "market_cap": prof.get("mktCap"),
            "shares_outstanding": (
                int(prof["mktCap"] / prof["price"])
                if prof.get("mktCap") and prof.get("price")
                else None
            ),
            "pe_ratio": (
                prof["price"] / (inc["netIncome"] / int(prof["mktCap"] / prof["price"]))
                if inc.get("netIncome")
                and prof.get("mktCap")
                and prof.get("price")
                and inc["netIncome"] > 0
                else None
            ),
            "beta": prof.get("beta"),
            "current_price": prof.get("price"),
            "company_name": prof.get("companyName"),
            "industry": prof.get("industry"),
            "sector": prof.get("sector"),
            "fiscal_date": inc.get("date"),
        }
        return DataResult(
            data=data,
            provider=self.name,
            ticker=ticker,
            data_type=data_type,
            timestamp=datetime.now(tz=timezone.utc),
        )

    if years and len(income) > 1:
        # Pack multi-year data inside a single DataResult
        yearly_data = [_build_result(inc).data for inc in income]
        return DataResult(
            data={"yearly_data": yearly_data},
            provider=self.name,
            ticker=ticker,
            data_type=data_type,
            timestamp=datetime.now(tz=timezone.utc),
        )

    inc = income[0] if income else {}
    return _build_result(inc)
```

- [ ] **Step 4: Run all FMP tests + existing tests**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_fmp_provider.py -x -v --tb=short
```
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && git add finrobot/engine/data/providers/fmp_provider.py tests/unit/test_fmp_provider.py && git commit -m "feat(P2c-0b): FMP provider multi-year support via ?limit=N"
```

---

### Task 3: Finnhub Provider multi-year support (File 0c)

**Files:**
- Modify: `finrobot/engine/data/providers/finnhub_provider.py`
- Test: `tests/unit/test_finnhub_provider.py`

**Context:** Finnhub's `/stock/financials-reported?freq=annual` already returns multiple years of data. When `years` kwarg is passed, parse the first N filings and pack them into `DataResult.data["yearly_data"]`. Provider always returns `DataResult` (interface unchanged).

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/unit/test_finnhub_provider.py

def _finnhub_multi_year_reported(ticker: str = "AAPL", years: int = 3) -> dict:
    """Mock Finnhub financials-reported response with multiple years."""
    return {
        "data": [
            {
                "year": 2024 - i,
                "report": {
                    "ic": [
                        {"concept": "Revenues", "value": 394e9 - i * 10e9},
                        {"concept": "NetIncomeLoss", "value": 97e9 - i * 3e9},
                        {"concept": "DepreciationAndAmortization", "value": 11e9},
                        {"concept": "OperatingIncomeLoss", "value": 119e9 - i * 3e9},
                        {"concept": "CostOfGoodsAndServicesSold", "value": 213e9 + i * 5e9},
                    ],
                    "bs": [
                        {"concept": "LongTermDebt", "value": 100e9},
                        {"concept": "CashAndCashEquivalentsAtCarryingValue", "value": 30e9},
                    ],
                },
            }
            for i in range(years)
        ]
    }


class TestFinnhubFetchHistorical:
    @pytest.mark.asyncio
    async def test_fetch_with_years_returns_list(self, provider):
        """When years kwarg is passed, return list[DataResult]."""
        profile_resp = _mock_response(_finnhub_profile_response())
        reported_resp = _mock_response(_finnhub_multi_year_reported("AAPL", 3))
        with patch.object(provider, "_get", AsyncMock(side_effect=[profile_resp, reported_resp])):
            result = await provider.fetch("AAPL", "financials", years=3)

        assert isinstance(result, DataResult)  # Always DataResult
        assert "yearly_data" in result.data
        assert len(result.data["yearly_data"]) == 3
        assert result.data["yearly_data"][0]["revenue"] == 394e9

    @pytest.mark.asyncio
    async def test_fetch_without_years_unchanged(self, provider):
        """Default behavior returns single DataResult with flat data."""
        profile_resp = _mock_response(_finnhub_profile_response())
        reported_resp = _mock_response(_finnhub_reported_response())
        with patch.object(provider, "_get", AsyncMock(side_effect=[profile_resp, reported_resp])):
            result = await provider.fetch("AAPL", "financials")

        assert isinstance(result, DataResult)
        assert "yearly_data" not in result.data
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_finnhub_provider.py::TestFinnhubFetchHistorical -x -v --tb=short
```

- [ ] **Step 3: Implement multi-year in Finnhub provider**

Modify `_fetch_financials` to accept `years` and refactor `fetch()` to pass it:

```python
async def fetch(self, ticker: str, data_type: str, **kwargs) -> DataResult:
    if data_type not in _SUPPORTED:
        raise ProviderError(
            f"data_type '{data_type}' is not supported by Finnhub. Supported: {_SUPPORTED}"
        )
    try:
        if data_type == "financials":
            return await self._fetch_financials(ticker, years=kwargs.get("years"))
        elif data_type == "profile":
            data = await self._fetch_profile(ticker)
        else:
            raise ProviderError(f"Unhandled data_type: {data_type}")
    except httpx.TimeoutException as e:
        raise ProviderError(f"Finnhub timeout for '{ticker}': {e}") from e
    except httpx.HTTPStatusError as e:
        raise ProviderError(f"Finnhub API error for '{ticker}': {e}") from e
    except ProviderError:
        raise
    except Exception as e:
        raise ProviderError(f"Finnhub fetch failed for '{ticker}': {e}") from e

    return DataResult(
        data=data,
        provider=self.name,
        ticker=ticker,
        data_type=data_type,
        timestamp=datetime.now(tz=timezone.utc),
    )

async def _fetch_financials(
    self, ticker: str, years: int | None = None
) -> DataResult:
    profile = (await self._get("/stock/profile2", params={"symbol": ticker})).json()
    reported = (
        await self._get(
            "/stock/financials-reported",
            params={"symbol": ticker, "freq": "annual"},
        )
    ).json()

    filings = reported.get("data", [])
    mkt_cap_millions = profile.get("marketCapitalization", 0)
    shares_millions = profile.get("shareOutstanding", 0)

    def _parse_filing(filing: dict) -> dict:
        report = filing.get("report", {})

        def _find_concept(section: str, concept: str) -> float | None:
            items = report.get(section, [])
            for item in items:
                if item.get("concept") == concept:
                    return item.get("value")
            return None

        revenue = _find_concept("ic", "Revenues")
        net_income = _find_concept("ic", "NetIncomeLoss")
        da = _find_concept("ic", "DepreciationAndAmortization")
        operating_income = _find_concept("ic", "OperatingIncomeLoss")
        cogs = _find_concept("ic", "CostOfGoodsAndServicesSold")
        total_debt = _find_concept("bs", "LongTermDebt") or 0
        total_cash = _find_concept("bs", "CashAndCashEquivalentsAtCarryingValue") or 0

        return {
            "revenue": revenue,
            "ebitda": (
                (operating_income or 0) + (da or 0) if operating_income is not None else None
            ),
            "net_income": net_income,
            "depreciation_amortization": da,
            "total_debt": total_debt,
            "total_cash": total_cash,
            "market_cap": mkt_cap_millions * 1_000_000 if mkt_cap_millions else None,
            "shares_outstanding": shares_millions * 1_000_000 if shares_millions else None,
            "gross_margin": (
                (revenue - cogs) / revenue if revenue and cogs is not None else None
            ),
            "operating_margin": (
                operating_income / revenue
                if revenue and operating_income is not None
                else None
            ),
            "current_price": None,
            "company_name": profile.get("name"),
            "industry": profile.get("finnhubIndustry"),
            "fiscal_year": filing.get("year"),
        }

    def _make_result(data: dict) -> DataResult:
        return DataResult(
            data=data,
            provider=self.name,
            ticker=ticker,
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )

    if years and len(filings) > 1:
        n = min(years, len(filings))
        yearly_data = [_parse_filing(f) for f in filings[:n]]
        return DataResult(
            data={"yearly_data": yearly_data},
            provider=self.name,
            ticker=ticker,
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )

    latest = filings[0] if filings else {}
    return _make_result(_parse_filing(latest))
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_finnhub_provider.py -x -v --tb=short
```

- [ ] **Step 5: Commit**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && git add finrobot/engine/data/providers/finnhub_provider.py tests/unit/test_finnhub_provider.py && git commit -m "feat(P2c-0c): Finnhub provider multi-year support"
```

---

### Task 4: yfinance Provider multi-year support (File 0d)

**Files:**
- Modify: `finrobot/engine/data/providers/yfinance_provider.py`
- Test: `tests/unit/test_yfinance_provider.py`

**Context:** yfinance's `Ticker.income_stmt` returns a DataFrame where each column is a year (most recent first). When `years` kwarg is passed, split the DataFrame columns into `list[DataResult]`.

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/unit/test_yfinance_provider.py
import pandas as pd

def _mock_income_stmt(years: int = 3) -> pd.DataFrame:
    """Mock yfinance income_stmt DataFrame (columns = years, most recent first)."""
    data = {}
    for i in range(years):
        col = pd.Timestamp(f"{2024 - i}-09-30")
        data[col] = {
            "Total Revenue": 394e9 - i * 10e9,
            "EBITDA": 130e9 - i * 5e9,
            "Net Income": 97e9 - i * 3e9,
            "Gross Profit": 181e9 - i * 4e9,
            "Operating Income": 119e9 - i * 3e9,
        }
    return pd.DataFrame(data)


class TestYFinanceFetchHistorical:
    @pytest.mark.asyncio
    async def test_fetch_with_years_returns_list(self):
        provider = YFinanceProvider()
        mock_ticker = MagicMock()
        mock_ticker.info = {
            "totalRevenue": 394e9, "ebitda": 130e9,
            "netIncomeToCommon": 97e9, "grossMargins": 0.46,
            "operatingMargins": 0.30, "trailingPE": 28.0,
            "marketCap": 3e12, "sharesOutstanding": 15e9,
            "totalDebt": 100e9, "totalCash": 60e9,
        }
        mock_ticker.income_stmt = _mock_income_stmt(3)

        with patch("finrobot.engine.data.providers.yfinance_provider._make_ticker", return_value=mock_ticker):
            with patch("asyncio.to_thread", new_callable=lambda: _sync_to_thread):
                result = await provider.fetch("AAPL", "financials", years=3)

        assert isinstance(result, DataResult)  # Always DataResult
        assert "yearly_data" in result.data
        assert len(result.data["yearly_data"]) == 3
        assert result.data["yearly_data"][0]["revenue"] == 394e9
```

**Note:** The exact mock pattern depends on how `asyncio.to_thread` is used. The implementer should adapt the mock to match the existing test patterns in `test_yfinance_provider.py`.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_yfinance_provider.py::TestYFinanceFetchHistorical -x -v --tb=short
```

- [ ] **Step 3: Implement multi-year in yfinance provider**

In `_fetch_financials`, add the `years` branch. When `years` is provided and > 1, access `t.income_stmt` DataFrame and split columns:

```python
def _fetch_financials(self, ticker: str, info: dict, *, years: int | None = None, t=None) -> DataResult:
    if years and years > 1 and t is not None:
        return self._fetch_historical_financials(ticker, info, t, years)

    # Existing single-year logic unchanged
    try:
        data = {
            "revenue": info.get("totalRevenue"),
            # ... (keep existing code exactly as-is)
        }
    except Exception as e:
        raise ProviderError(f"Failed to fetch financials for '{ticker}': {e}") from e

    return DataResult(
        data=data, provider=self.name, ticker=ticker,
        data_type="financials", timestamp=datetime.now(tz=timezone.utc),
    )

def _fetch_historical_financials(
    self, ticker: str, info: dict, t, years: int
) -> DataResult:
    """Pack income_stmt DataFrame columns into DataResult.data["yearly_data"]."""
    try:
        stmt = t.income_stmt
    except Exception as e:
        raise ProviderError(f"Failed to fetch historical financials for '{ticker}': {e}") from e

    if stmt is None or stmt.empty:
        return self._fetch_financials(ticker, info)

    yearly_data = []
    for col in list(stmt.columns)[:years]:
        col_data = stmt[col]
        data = {
            "revenue": col_data.get("Total Revenue"),
            "ebitda": col_data.get("EBITDA"),
            "net_income": col_data.get("Net Income"),
            "gross_margin": (
                col_data.get("Gross Profit") / col_data.get("Total Revenue")
                if col_data.get("Total Revenue") and col_data.get("Gross Profit")
                else info.get("grossMargins")
            ),
            "operating_margin": (
                col_data.get("Operating Income") / col_data.get("Total Revenue")
                if col_data.get("Total Revenue") and col_data.get("Operating Income")
                else info.get("operatingMargins")
            ),
            "market_cap": info.get("marketCap"),
            "shares_outstanding": info.get("sharesOutstanding"),
            "total_debt": info.get("totalDebt", 0),
            "total_cash": info.get("totalCash", 0),
            "fiscal_date": str(col.date()) if hasattr(col, "date") else str(col),
        }
        yearly_data.append(data)

    if not yearly_data:
        return self._fetch_financials(ticker, info)

    return DataResult(
        data={"yearly_data": yearly_data},
        provider=self.name, ticker=ticker,
        data_type="financials", timestamp=datetime.now(tz=timezone.utc),
    )
```

Also update `fetch()` to pass `years` and `t` to `_fetch_financials`:

```python
if data_type == "financials":
    years = kwargs.get("years")
    result = self._fetch_financials(ticker, info, years=years, t=t)
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_yfinance_provider.py -x -v --tb=short
```

- [ ] **Step 5: Commit**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && git add finrobot/engine/data/providers/yfinance_provider.py tests/unit/test_yfinance_provider.py && git commit -m "feat(P2c-0d): yfinance provider multi-year support via income_stmt DataFrame"
```

---

### Task 5: Data cleaning — `clean.py` (File 1)

**Files:**
- Create: `finrobot/engine/compute/clean.py`
- Test: `tests/unit/test_clean.py`

**Context:** Pure deterministic data cleaning functions. No LLM. Handles the mess that financial data comes in (commas, parentheses for negatives, currency symbols, percentages, N/A strings, multiple field name conventions across providers).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_clean.py
import pytest
from finrobot.engine.compute.clean import clean_financial_number, normalize_field_names, FIELD_ALIASES


class TestCleanFinancialNumber:
    """What this code does that raw LLM cannot: deterministic, reproducible
    parsing of financial number formats. Same input always gives same output."""

    def test_plain_integer(self):
        assert clean_financial_number(1234) == 1234.0

    def test_plain_float(self):
        assert clean_financial_number(1234.56) == 1234.56

    def test_string_integer(self):
        assert clean_financial_number("1234") == 1234.0

    def test_commas(self):
        assert clean_financial_number("1,234,567") == 1_234_567.0

    def test_commas_with_decimals(self):
        assert clean_financial_number("1,234.56") == 1234.56

    def test_parentheses_negative(self):
        assert clean_financial_number("(1,234)") == -1234.0

    def test_parentheses_negative_with_decimals(self):
        assert clean_financial_number("(1,234.56)") == -1234.56

    def test_dollar_sign(self):
        assert clean_financial_number("$1,234") == 1234.0

    def test_dollar_sign_negative(self):
        assert clean_financial_number("$(1,234.56)") == -1234.56

    def test_percentage(self):
        assert clean_financial_number("12.5%") == 0.125

    def test_percentage_negative(self):
        assert clean_financial_number("-3.2%") == -0.032

    def test_none_returns_none(self):
        assert clean_financial_number(None) is None

    def test_empty_string_returns_none(self):
        assert clean_financial_number("") is None

    def test_na_returns_none(self):
        assert clean_financial_number("N/A") is None

    def test_na_lowercase(self):
        assert clean_financial_number("n/a") is None

    def test_dash_returns_none(self):
        assert clean_financial_number("-") is None

    def test_zero(self):
        assert clean_financial_number(0) == 0.0

    def test_negative_number(self):
        assert clean_financial_number(-500.25) == -500.25

    def test_string_negative(self):
        assert clean_financial_number("-500.25") == -500.25

    def test_whitespace_stripped(self):
        assert clean_financial_number("  1,234  ") == 1234.0


class TestNormalizeFieldNames:
    def test_maps_camel_case_to_canonical(self):
        data = {"costOfRevenue": 100, "sellingGeneralAndAdministrative": 50}
        result = normalize_field_names(data)
        assert result["cost_of_revenue"] == 100
        assert result["sga"] == 50

    def test_first_match_wins(self):
        data = {"costOfRevenue": 100, "costOfGoodsSold": 200}
        result = normalize_field_names(data)
        assert result["cost_of_revenue"] == 100

    def test_passthrough_unknown_keys(self):
        data = {"revenue": 500, "unknown_field": 42}
        result = normalize_field_names(data)
        assert result["revenue"] == 500
        assert result["unknown_field"] == 42

    def test_empty_dict(self):
        assert normalize_field_names({}) == {}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_clean.py -x -v --tb=short
```
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement `clean.py`**

```python
# finrobot/engine/compute/clean.py
"""Financial data cleaning utilities.

What this code does that raw LLM cannot: deterministic, reproducible parsing
of financial number formats (commas, parentheses for negatives, currency
symbols, percentages, N/A). Same input always produces the same float output.
"""

from __future__ import annotations

import re

_NA_VALUES = {"n/a", "na", "none", "null", "-", "--", "—", ""}


def clean_financial_number(value: str | float | int | None) -> float | None:
    """Parse a financial number from various string formats to float.

    Handles:
    - Commas: "1,234,567" → 1234567.0
    - Parentheses (negative): "(1,234)" → -1234.0
    - Currency symbols: "$1,234" → 1234.0
    - Percentage: "12.5%" → 0.125
    - N/A, None, empty string → None
    - Already numeric → pass through
    """
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    s = str(value).strip()
    if s.lower() in _NA_VALUES:
        return None

    # Check for percentage before stripping symbols
    is_pct = s.endswith("%")
    if is_pct:
        s = s[:-1]

    # Check for parentheses (accounting negative notation)
    is_negative = s.startswith("(") and s.endswith(")")
    if is_negative:
        s = s[1:-1]

    # Remove currency symbols and whitespace
    s = re.sub(r"[$ €£¥₹]", "", s).strip()

    # Remove commas
    s = s.replace(",", "")

    if not s:
        return None

    try:
        result = float(s)
    except ValueError:
        return None

    if is_negative:
        result = -result
    if is_pct:
        result = result / 100

    return result


# Field name aliases: canonical_name → list of provider-specific variants
FIELD_ALIASES: dict[str, list[str]] = {
    "cost_of_revenue": [
        "costOfRevenue",
        "costOfGoodsSold",
        "totalCostOfSales",
        "cost_of_goods_sold",
        "CostOfGoodsAndServicesSold",
    ],
    "sga": [
        "sellingGeneralAndAdministrative",
        "sgaExpense",
        "selling_general_administrative",
        "SellingGeneralAndAdministrativeExpense",
    ],
    "depreciation_amortization": [
        "depreciationAndAmortization",
        "depreciation",
        "da",
        "DepreciationAndAmortization",
    ],
    "rd_expense": [
        "researchAndDevelopmentExpenses",
        "rdExpense",
        "research_and_development",
        "ResearchAndDevelopmentExpense",
    ],
    "interest_expense": [
        "interestExpense",
        "InterestExpense",
        "interest_expense_non_operating",
    ],
    "operating_income": [
        "operatingIncome",
        "OperatingIncomeLoss",
        "operating_income_loss",
    ],
    "gross_profit": [
        "grossProfit",
        "GrossProfit",
        "gross_profit_loss",
    ],
}


def normalize_field_names(
    data: dict, aliases: dict[str, list[str]] = FIELD_ALIASES
) -> dict:
    """Map provider-specific field names to canonical names.

    For each canonical name, try all known aliases against the input dict.
    First match wins. Keys not matching any alias are passed through unchanged.
    """
    result = {}
    used_keys: set[str] = set()

    for canonical, variants in aliases.items():
        for variant in variants:
            if variant in data and variant not in used_keys:
                result[canonical] = data[variant]
                used_keys.add(variant)
                break

    # Pass through keys that weren't consumed by aliases
    for key, value in data.items():
        if key not in used_keys:
            result[key] = value

    return result
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_clean.py -x -v --tb=short
```

- [ ] **Step 5: Run full test suite to verify no breakage**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/ -x -v --tb=short
```

- [ ] **Step 6: Commit**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && git add finrobot/engine/compute/clean.py tests/unit/test_clean.py && git commit -m "feat(P2c-1): add clean_financial_number() and field name normalization"
```

---

### Task 6: New Pydantic models (File 2)

**Files:**
- Modify: `finrobot/engine/models/financial.py`
- Test: `tests/unit/test_financial_models.py`

**Context:** Add 8 new models to `financial.py`: `HistoricalMetrics`, `MarginAssumptions`, `ForecastAssumptions`, `ForecastResult`, `CatalystEvent`, `CatalystAnalysis`, `ValuationMethod`, `ValuationSynthesis`. Also add `CatalystAnalysis` to `StructuredOutput` union if one exists (only LLM output types go in the union).

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/unit/test_financial_models.py
from pydantic import ValidationError
from finrobot.engine.models.financial import (
    HistoricalMetrics, MarginAssumptions, ForecastAssumptions, ForecastResult,
    CatalystEvent, CatalystAnalysis, ValuationMethod, ValuationSynthesis,
)


class TestHistoricalMetrics:
    def test_valid_construction(self):
        hm = HistoricalMetrics(
            years=[2022, 2023, 2024],
            revenue=[300e9, 350e9, 394e9],
            revenue_growth_yoy=[None, 350e9 / 300e9 - 1, 394e9 / 350e9 - 1],
            cogs=[160e9, 175e9, 213e9],
            gross_profit=[140e9, 175e9, 181e9],
            gross_margin=[0.467, 0.500, 0.459],
            sga=[20e9, 22e9, 25e9],
            sga_ratio=[0.067, 0.063, 0.063],
            ebitda=[110e9, 120e9, 130e9],
            ebitda_margin=[0.367, 0.343, 0.330],
            operating_income=[100e9, 110e9, 119e9],
            operating_margin=[0.333, 0.314, 0.302],
            net_income=[80e9, 90e9, 97e9],
            eps=[5.0, 5.8, 6.42],
            pe_ratio=[None, 25.0, 28.3],
            cagr_revenue=0.146,
            ticker="AAPL",
        )
        assert hm.ticker == "AAPL"
        assert len(hm.years) == 3


class TestForecastResult:
    def test_valid_construction(self):
        fr = ForecastResult(
            years=[2025, 2026, 2027],
            revenue=[420e9, 445e9, 467e9],
            ebitda=[140e9, 150e9, 158e9],
            net_income=[100e9, 107e9, 112e9],
            eps=[6.8, 7.2, 7.5],
            assumptions=ForecastAssumptions(
                revenue_growth_rates=[0.07, 0.06, 0.05],
                gross_margin=0.46,
                ebitda_margin=0.33,
                sga_ratio=0.063,
            ),
        )
        assert fr.assumptions.tax_rate == 0.21  # default


class TestCatalystEvent:
    def test_valid_event(self):
        event = CatalystEvent(
            category="product_launch",
            headline="Vision Pro Gen 2 announced",
            sentiment="positive",
            impact_score=4,
            probability=0.8,
            reasoning="Strong pre-orders",
        )
        assert event.impact_score == 4

    def test_impact_score_bounds(self):
        with pytest.raises(ValidationError):
            CatalystEvent(
                category="earnings", headline="x", sentiment="positive",
                impact_score=6, probability=0.5, reasoning="x",
            )


class TestValuationSynthesis:
    def test_valid_synthesis(self):
        vs = ValuationSynthesis(
            methods=[
                ValuationMethod(name="DCF", low=200, mid=245, high=290, confidence=0.5, source="DCF"),
                ValuationMethod(name="Comps", low=220, mid=250, high=280, confidence=0.3, source="EV/EBITDA"),
            ],
            weighted_price=247.0,
            current_price=230.0,
            upside_downside=0.074,
        )
        assert len(vs.methods) == 2
        assert vs.upside_downside == pytest.approx(0.074)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_financial_models.py::TestHistoricalMetrics -x -v --tb=short
```
Expected: FAIL — models not defined yet.

- [ ] **Step 3: Add models to `financial.py`**

Append the following after `StepOutput` in `finrobot/engine/models/financial.py`:

```python
from typing import Literal


class HistoricalMetrics(BaseModel):
    """Multi-year historical financial metrics extracted from provider data."""

    years: list[int]
    revenue: list[float]
    revenue_growth_yoy: list[float | None]
    cogs: list[float]
    gross_profit: list[float]
    gross_margin: list[float]
    sga: list[float]
    sga_ratio: list[float]
    ebitda: list[float]
    ebitda_margin: list[float]
    operating_income: list[float]
    operating_margin: list[float]
    net_income: list[float]
    eps: list[float]
    pe_ratio: list[float | None]
    cagr_revenue: float | None
    ticker: str
    price_data_available: bool = False


class MarginAssumptions(BaseModel):
    """User-provided or default margin targets for forecasting."""

    gross_margin_target: float | None = None
    ebitda_margin_target: float | None = None
    sga_ratio_target: float | None = None


class ForecastAssumptions(BaseModel):
    """Records exactly which assumptions were used in a forecast."""

    revenue_growth_rates: list[float]
    gross_margin: float
    ebitda_margin: float
    sga_ratio: float
    tax_rate: float = 0.21


class ForecastResult(BaseModel):
    """Deterministic 3-year financial forecast output."""

    years: list[int]
    revenue: list[float]
    ebitda: list[float]
    net_income: list[float]
    eps: list[float]
    assumptions: ForecastAssumptions


class CatalystEvent(BaseModel):
    """Single catalyst event extracted by LLM from news."""

    category: Literal[
        "product_launch", "earnings", "regulatory",
        "acquisition", "management", "market",
    ]
    headline: str
    sentiment: Literal["positive", "negative", "neutral"]
    impact_score: int = Field(ge=1, le=5)
    probability: float = Field(ge=0, le=1)
    reasoning: str


class CatalystAnalysis(BaseModel):
    """LLM-structured catalyst analysis output."""

    events: list[CatalystEvent]
    overall_sentiment: Literal["bullish", "bearish", "neutral"]
    key_catalysts: list[str]


class ValuationMethod(BaseModel):
    """One valuation method's result range."""

    name: str
    low: float
    mid: float
    high: float
    confidence: float = Field(ge=0, le=1)
    source: str


class ValuationSynthesis(BaseModel):
    """Multi-method valuation synthesis. Football field data derives from methods."""

    methods: list[ValuationMethod]
    weighted_price: float
    current_price: float
    upside_downside: float
```

Also add `Literal` to the existing import at the top of the file:

```python
from typing import Any, Literal
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_financial_models.py -x -v --tb=short
```

- [ ] **Step 5: Run full test suite**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/ -x -v --tb=short
```

- [ ] **Step 6: Commit**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && git add finrobot/engine/models/financial.py tests/unit/test_financial_models.py && git commit -m "feat(P2c-2): add HistoricalMetrics, ForecastResult, Catalyst, Valuation models"
```

---

### Task 7: Data processor — `extract_historical_metrics()` + `forecast_financials()` (File 3)

**Files:**
- Create: `finrobot/engine/compute/data_processor.py`
- Test: `tests/unit/test_data_processor.py`

**Context:** Core deterministic computation. Takes multi-year `FinancialData` list, computes margins, growth rates, CAGR, and generates 3-year forecasts from user-provided assumptions. All math must be hand-verifiable.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_data_processor.py
import pytest
from datetime import datetime, timezone
from finrobot.engine.models.financial import (
    FinancialData, HistoricalMetrics, MarginAssumptions, ForecastAssumptions, ForecastResult,
)
from finrobot.engine.compute.data_processor import (
    extract_historical_metrics, forecast_financials, calculate_cagr,
)


def _make_financial_data(year: int, revenue: float, ebitda: float, net_income: float,
                          sga: float = 25e9, cogs: float = 210e9) -> FinancialData:
    gross_profit = revenue - cogs
    return FinancialData(
        ticker="AAPL", timestamp=datetime(year, 12, 31, tzinfo=timezone.utc),
        revenue=revenue, ebitda=ebitda, net_income=net_income,
        gross_margin=gross_profit / revenue, operating_margin=ebitda / revenue * 0.9,
        market_cap=3e12, shares_outstanding=15e9, current_price=200.0,
        sga_expense=sga,
    )


class TestCalculateCagr:
    def test_basic_cagr(self):
        """CAGR = (end/start)^(1/n) - 1.
        Source: CFA Institute formula.
        100 → 150 over 5 years = (150/100)^(1/5) - 1 ≈ 0.08447"""
        result = calculate_cagr(100, 150, 5)
        assert result == pytest.approx(0.08447, abs=0.001)

    def test_cagr_one_year(self):
        """1 year: CAGR = (200/100)^1 - 1 = 1.0"""
        result = calculate_cagr(100, 200, 1)
        assert result == pytest.approx(1.0)

    def test_cagr_zero_start(self):
        assert calculate_cagr(0, 100, 5) is None

    def test_cagr_negative_start(self):
        assert calculate_cagr(-100, 100, 5) is None


class TestExtractHistoricalMetrics:
    def test_three_year_metrics(self):
        """Hand-calculated verification of 3-year metrics extraction."""
        data = [
            _make_financial_data(2022, revenue=300e9, ebitda=100e9, net_income=70e9, cogs=165e9),
            _make_financial_data(2023, revenue=350e9, ebitda=120e9, net_income=85e9, cogs=185e9),
            _make_financial_data(2024, revenue=394e9, ebitda=130e9, net_income=97e9, cogs=213e9),
        ]
        hm = extract_historical_metrics(data)

        assert hm.years == [2022, 2023, 2024]
        assert hm.revenue == [300e9, 350e9, 394e9]
        assert hm.ticker == "AAPL"

        # YoY growth: None, (350-300)/300=0.1667, (394-350)/350=0.1257
        assert hm.revenue_growth_yoy[0] is None
        assert hm.revenue_growth_yoy[1] == pytest.approx(50e9 / 300e9, abs=0.001)
        assert hm.revenue_growth_yoy[2] == pytest.approx(44e9 / 350e9, abs=0.001)

        # Gross margin: (300-165)/300=0.45, (350-185)/350=0.4714, (394-213)/394=0.4594
        assert hm.gross_margin[0] == pytest.approx(135e9 / 300e9, abs=0.001)

        # EBITDA margin: 100/300=0.333, 120/350=0.343, 130/394=0.330
        assert hm.ebitda_margin[0] == pytest.approx(100e9 / 300e9, abs=0.001)
        assert hm.ebitda_margin[2] == pytest.approx(130e9 / 394e9, abs=0.001)

        # CAGR: (394/300)^(1/2) - 1 ≈ 0.1459
        assert hm.cagr_revenue == pytest.approx((394e9 / 300e9) ** (1 / 2) - 1, abs=0.001)


class TestForecastFinancials:
    def test_three_year_forecast(self):
        """Hand-calculated 3-year forecast from known base.

        Base year: revenue=394e9, growth=[0.07, 0.06, 0.05]
        Year 1: 394e9 * 1.07 = 421.58e9
        Year 2: 421.58e9 * 1.06 = 446.8748e9
        Year 3: 446.8748e9 * 1.05 = 469.21854e9

        EBITDA margin 0.33:
        Year 1 EBITDA: 421.58e9 * 0.33 = 139.1214e9
        """
        hm = HistoricalMetrics(
            years=[2022, 2023, 2024], revenue=[300e9, 350e9, 394e9],
            revenue_growth_yoy=[None, 0.167, 0.126],
            cogs=[165e9, 185e9, 213e9], gross_profit=[135e9, 165e9, 181e9],
            gross_margin=[0.45, 0.471, 0.459], sga=[20e9, 22e9, 25e9],
            sga_ratio=[0.067, 0.063, 0.063], ebitda=[100e9, 120e9, 130e9],
            ebitda_margin=[0.333, 0.343, 0.330],
            operating_income=[90e9, 108e9, 117e9],
            operating_margin=[0.30, 0.309, 0.297],
            net_income=[70e9, 85e9, 97e9], eps=[4.67, 5.67, 6.47],
            pe_ratio=[None, None, None], cagr_revenue=0.146, ticker="AAPL",
        )

        result = forecast_financials(
            hm,
            revenue_growth_assumptions=[0.07, 0.06, 0.05],
            margin_assumptions=MarginAssumptions(ebitda_margin_target=0.33),
        )

        assert result.years == [2025, 2026, 2027]

        # Revenue verification
        expected_rev_y1 = 394e9 * 1.07
        assert result.revenue[0] == pytest.approx(expected_rev_y1, rel=1e-6)
        expected_rev_y2 = expected_rev_y1 * 1.06
        assert result.revenue[1] == pytest.approx(expected_rev_y2, rel=1e-6)

        # EBITDA verification
        expected_ebitda_y1 = expected_rev_y1 * 0.33
        assert result.ebitda[0] == pytest.approx(expected_ebitda_y1, rel=1e-6)

        # Net income: EBITDA × (1 - tax_rate) = 421.58e9 × 0.33 × 0.79
        # = 139.1214e9 × 0.79 = 109.906e9
        expected_ni_y1 = expected_ebitda_y1 * (1 - 0.21)
        assert result.net_income[0] == pytest.approx(expected_ni_y1, rel=1e-6)

        # EPS: net_income / shares
        # shares = last_ni / last_eps = 97e9 / 6.47 ≈ 14.99e9
        shares = 97e9 / 6.47
        expected_eps_y1 = expected_ni_y1 / shares
        assert result.eps[0] == pytest.approx(expected_eps_y1, rel=1e-3)

        # Assumptions recorded
        assert result.assumptions.revenue_growth_rates == [0.07, 0.06, 0.05]
        assert result.assumptions.ebitda_margin == 0.33
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_data_processor.py -x -v --tb=short
```

- [ ] **Step 3: Implement `data_processor.py`**

```python
# finrobot/engine/compute/data_processor.py
"""Historical metrics extraction and financial forecasting.

What this code does that raw LLM cannot: deterministic arithmetic for
margins, growth rates, CAGR, and multi-year forecasts. Every number is
reproducible from typed inputs. The LLM selects assumptions; code does math.
"""

from __future__ import annotations

from statistics import mean

from finrobot.engine.models.financial import (
    FinancialData,
    ForecastAssumptions,
    ForecastResult,
    HistoricalMetrics,
    MarginAssumptions,
    PriceHistory,
)


def calculate_cagr(start: float, end: float, years: int) -> float | None:
    """Compound Annual Growth Rate = (end/start)^(1/years) - 1.

    Source: CFA Institute, Quantitative Methods.
    Returns None if start <= 0 or years <= 0.
    """
    if start <= 0 or years <= 0:
        return None
    return (end / start) ** (1 / years) - 1


def extract_historical_metrics(
    financial_data: list[FinancialData],
    price_data: PriceHistory | None = None,
    years: int = 5,
) -> HistoricalMetrics:
    """Extract structured multi-year metrics from a list of FinancialData.

    Sorts by timestamp (oldest first), computes YoY growth, margins, CAGR.
    """
    if not financial_data:
        raise ValueError("financial_data list is empty")

    # Sort oldest first
    sorted_data = sorted(financial_data, key=lambda fd: fd.timestamp)[:years]
    ticker = sorted_data[0].ticker

    year_list = [fd.timestamp.year for fd in sorted_data]
    revenues = [fd.revenue for fd in sorted_data]
    ebitdas = [fd.ebitda for fd in sorted_data]
    net_incomes = [fd.net_income for fd in sorted_data]
    shares = [fd.shares_outstanding for fd in sorted_data]

    # YoY revenue growth
    growth = [None]
    for i in range(1, len(revenues)):
        if revenues[i - 1] and revenues[i - 1] > 0:
            growth.append((revenues[i] - revenues[i - 1]) / revenues[i - 1])
        else:
            growth.append(None)

    # Margins
    gross_margins = [fd.gross_margin for fd in sorted_data]
    operating_margins = [fd.operating_margin for fd in sorted_data]
    ebitda_margins = [e / r if r > 0 else 0 for e, r in zip(ebitdas, revenues)]

    # COGS and gross profit
    cogs_list = [r * (1 - gm) for r, gm in zip(revenues, gross_margins)]
    gross_profits = [r * gm for r, gm in zip(revenues, gross_margins)]

    # SGA
    sga_list = [fd.sga_expense or 0 for fd in sorted_data]
    sga_ratios = [s / r if r > 0 else 0 for s, r in zip(sga_list, revenues)]

    # Operating income
    op_incomes = [r * om for r, om in zip(revenues, operating_margins)]

    # EPS
    eps_list = [ni / s if s > 0 else 0 for ni, s in zip(net_incomes, shares)]

    # PE ratio
    pe_ratios: list[float | None] = [None] * len(sorted_data)
    if price_data and price_data.current_price > 0:
        # Only last year gets PE from current price
        if eps_list[-1] > 0:
            pe_ratios[-1] = price_data.current_price / eps_list[-1]

    # CAGR
    n_years = len(revenues) - 1
    cagr = calculate_cagr(revenues[0], revenues[-1], n_years) if n_years > 0 else None

    return HistoricalMetrics(
        years=year_list,
        revenue=revenues,
        revenue_growth_yoy=growth,
        cogs=cogs_list,
        gross_profit=gross_profits,
        gross_margin=gross_margins,
        sga=sga_list,
        sga_ratio=sga_ratios,
        ebitda=ebitdas,
        ebitda_margin=ebitda_margins,
        operating_income=op_incomes,
        operating_margin=operating_margins,
        net_income=net_incomes,
        eps=eps_list,
        pe_ratio=pe_ratios,
        cagr_revenue=cagr,
        ticker=ticker,
        price_data_available=price_data is not None,
    )


def forecast_financials(
    historical: HistoricalMetrics,
    revenue_growth_assumptions: list[float],
    margin_assumptions: MarginAssumptions,
) -> ForecastResult:
    """Deterministic N-year financial forecast.

    User controls all assumptions; code only does arithmetic.
    """
    if not revenue_growth_assumptions:
        raise ValueError("revenue_growth_assumptions must not be empty")

    base_year = historical.years[-1]
    base_revenue = historical.revenue[-1]
    base_shares = historical.eps[-1]  # we need shares; derive from last year
    last_ni = historical.net_income[-1]
    last_eps = historical.eps[-1]
    shares = last_ni / last_eps if last_eps > 0 else 1

    # Resolve margins: use target if provided, else historical average
    ebitda_margin = margin_assumptions.ebitda_margin_target or mean(historical.ebitda_margin)
    gross_margin = margin_assumptions.gross_margin_target or mean(historical.gross_margin)
    sga_ratio = margin_assumptions.sga_ratio_target or mean(historical.sga_ratio)
    tax_rate = 0.21

    forecast_years = []
    forecast_revenue = []
    forecast_ebitda = []
    forecast_net_income = []
    forecast_eps = []

    prev_revenue = base_revenue
    for i, g in enumerate(revenue_growth_assumptions):
        year = base_year + 1 + i
        rev = prev_revenue * (1 + g)
        ebitda = rev * ebitda_margin
        # Simplified: net_income ≈ EBITDA × (1 - tax) - SGA residual
        # More precise: revenue * (ebitda_margin - sga_adjustment) * (1 - tax)
        # Use: net_income = (revenue * operating_margin_approx) * (1 - tax)
        # where operating_margin_approx ≈ ebitda_margin (simplified since SGA already in EBITDA)
        ni = ebitda * (1 - tax_rate)
        eps = ni / shares if shares > 0 else 0

        forecast_years.append(year)
        forecast_revenue.append(rev)
        forecast_ebitda.append(ebitda)
        forecast_net_income.append(ni)
        forecast_eps.append(eps)
        prev_revenue = rev

    return ForecastResult(
        years=forecast_years,
        revenue=forecast_revenue,
        ebitda=forecast_ebitda,
        net_income=forecast_net_income,
        eps=forecast_eps,
        assumptions=ForecastAssumptions(
            revenue_growth_rates=revenue_growth_assumptions,
            gross_margin=gross_margin,
            ebitda_margin=ebitda_margin,
            sga_ratio=sga_ratio,
            tax_rate=tax_rate,
        ),
    )
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_data_processor.py -x -v --tb=short
```

- [ ] **Step 5: Run full test suite**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/ -x -v --tb=short
```

- [ ] **Step 6: Commit**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && git add finrobot/engine/compute/data_processor.py tests/unit/test_data_processor.py && git commit -m "feat(P2c-3): add data_processor with historical metrics extraction and forecasting"
```

---

### Task 8: Catalyst analyzer (File 4)

**Files:**
- Create: `finrobot/engine/compute/catalyst.py`
- Test: `tests/unit/test_catalyst.py`

**Context:** The LLM extracts `CatalystAnalysis` via PydanticAI `output_type`. This module provides the sorting/filtering/ranking logic that wraps the LLM call — the deterministic code part.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_catalyst.py
import pytest
from finrobot.engine.models.financial import CatalystEvent, CatalystAnalysis
from finrobot.engine.compute.catalyst import rank_catalysts, filter_by_impact


def _make_events() -> list[CatalystEvent]:
    return [
        CatalystEvent(category="earnings", headline="Q4 beat", sentiment="positive",
                      impact_score=4, probability=0.9, reasoning="Strong"),
        CatalystEvent(category="regulatory", headline="EU fine", sentiment="negative",
                      impact_score=3, probability=0.6, reasoning="Pending"),
        CatalystEvent(category="product_launch", headline="New chip", sentiment="positive",
                      impact_score=5, probability=0.7, reasoning="M4 launch"),
        CatalystEvent(category="market", headline="Rate cut", sentiment="positive",
                      impact_score=2, probability=0.4, reasoning="Fed"),
    ]


class TestRankCatalysts:
    def test_ranks_by_impact_times_probability(self):
        """Ranking = impact_score × probability (expected impact).
        New chip: 5×0.7=3.5, Q4 beat: 4×0.9=3.6, EU fine: 3×0.6=1.8, Rate cut: 2×0.4=0.8"""
        events = _make_events()
        ranked = rank_catalysts(events)
        # Q4 beat (3.6) > New chip (3.5) > EU fine (1.8) > Rate cut (0.8)
        assert ranked[0].headline == "Q4 beat"
        assert ranked[1].headline == "New chip"
        assert ranked[-1].headline == "Rate cut"

    def test_top_n(self):
        events = _make_events()
        ranked = rank_catalysts(events, top_n=2)
        assert len(ranked) == 2


class TestFilterByImpact:
    def test_filter_minimum_impact(self):
        events = _make_events()
        filtered = filter_by_impact(events, min_score=4)
        assert len(filtered) == 2
        assert all(e.impact_score >= 4 for e in filtered)

    def test_filter_by_sentiment(self):
        events = _make_events()
        filtered = filter_by_impact(events, sentiment="positive")
        assert len(filtered) == 3
        assert all(e.sentiment == "positive" for e in filtered)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_catalyst.py -x -v --tb=short
```

- [ ] **Step 3: Implement `catalyst.py`**

```python
# finrobot/engine/compute/catalyst.py
"""Catalyst event ranking and filtering.

What this code does that raw LLM cannot: deterministic sorting by
expected impact (impact_score × probability), reproducible filtering
by thresholds. The LLM extracts events; this code ranks them.
"""

from __future__ import annotations

from finrobot.engine.models.financial import CatalystEvent


def rank_catalysts(
    events: list[CatalystEvent],
    top_n: int | None = None,
) -> list[CatalystEvent]:
    """Rank catalyst events by expected impact (impact_score × probability).

    Higher expected impact = more important.
    Returns sorted list (descending). If top_n, returns only top N.
    """
    ranked = sorted(
        events,
        key=lambda e: e.impact_score * e.probability,
        reverse=True,
    )
    if top_n is not None:
        return ranked[:top_n]
    return ranked


def filter_by_impact(
    events: list[CatalystEvent],
    min_score: int = 1,
    sentiment: str | None = None,
) -> list[CatalystEvent]:
    """Filter events by minimum impact score and/or sentiment."""
    result = [e for e in events if e.impact_score >= min_score]
    if sentiment is not None:
        result = [e for e in result if e.sentiment == sentiment]
    return result
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_catalyst.py -x -v --tb=short
```

- [ ] **Step 5: Commit**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && git add finrobot/engine/compute/catalyst.py tests/unit/test_catalyst.py && git commit -m "feat(P2c-4): add catalyst ranking and filtering logic"
```

---

### Task 9: Valuation synthesis (File 5)

**Files:**
- Create: `finrobot/engine/compute/valuation_synthesis.py`
- Test: `tests/unit/test_valuation_synthesis.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_valuation_synthesis.py
import pytest
from finrobot.engine.models.financial import ValuationMethod, ValuationSynthesis
from finrobot.engine.compute.valuation_synthesis import synthesize_valuations


class TestSynthesizeValuations:
    def test_weighted_average_three_methods(self):
        """Hand-calculated weighted average.

        DCF: mid=245, confidence=0.5
        EV/EBITDA: mid=250, confidence=0.3
        P/E: mid=240, confidence=0.2

        Total confidence = 0.5 + 0.3 + 0.2 = 1.0
        Weighted = (245×0.5 + 250×0.3 + 240×0.2) / 1.0
                 = (122.5 + 75.0 + 48.0) / 1.0
                 = 245.5
        """
        methods = [
            ValuationMethod(name="DCF", low=210, mid=245, high=290, confidence=0.5, source="DCF"),
            ValuationMethod(name="EV/EBITDA", low=220, mid=250, high=280, confidence=0.3, source="Comps"),
            ValuationMethod(name="P/E", low=210, mid=240, high=260, confidence=0.2, source="PE Comps"),
        ]
        result = synthesize_valuations(methods, current_price=230.0)

        assert result.weighted_price == pytest.approx(245.5, abs=0.01)
        assert result.current_price == 230.0
        # upside = (245.5 - 230) / 230 = 0.06739
        assert result.upside_downside == pytest.approx(0.06739, abs=0.001)
        assert len(result.methods) == 3

    def test_single_method(self):
        methods = [
            ValuationMethod(name="DCF", low=200, mid=250, high=300, confidence=1.0, source="DCF"),
        ]
        result = synthesize_valuations(methods, current_price=200.0)
        assert result.weighted_price == 250.0
        assert result.upside_downside == pytest.approx(0.25)

    def test_empty_methods_raises(self):
        with pytest.raises(ValueError):
            synthesize_valuations([], current_price=200.0)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_valuation_synthesis.py -x -v --tb=short
```

- [ ] **Step 3: Implement**

```python
# finrobot/engine/compute/valuation_synthesis.py
"""Multi-method valuation synthesis.

What this code does that raw LLM cannot: deterministic confidence-weighted
average across valuation methods. Same inputs always produce the same
target price and upside/downside calculation.
"""

from __future__ import annotations

from finrobot.engine.models.financial import ValuationMethod, ValuationSynthesis


def synthesize_valuations(
    methods: list[ValuationMethod],
    current_price: float,
) -> ValuationSynthesis:
    """Compute confidence-weighted average target price across methods.

    Formula: weighted_price = Σ(mid_i × confidence_i) / Σ(confidence_i)
    upside_downside = (weighted_price - current_price) / current_price
    """
    if not methods:
        raise ValueError("At least one valuation method is required")

    total_confidence = sum(m.confidence for m in methods)
    if total_confidence <= 0:
        raise ValueError("Total confidence must be positive")

    weighted_price = sum(m.mid * m.confidence for m in methods) / total_confidence
    upside_downside = (weighted_price - current_price) / current_price

    return ValuationSynthesis(
        methods=methods,
        weighted_price=weighted_price,
        current_price=current_price,
        upside_downside=upside_downside,
    )
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_valuation_synthesis.py -x -v --tb=short
```

- [ ] **Step 5: Commit**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && git add finrobot/engine/compute/valuation_synthesis.py tests/unit/test_valuation_synthesis.py && git commit -m "feat(P2c-5): add valuation synthesis with confidence-weighted averaging"
```

---

### Task 10: FMP news capability (File 6)

**Files:**
- Modify: `finrobot/engine/data/providers/fmp_provider.py`
- Test: `tests/unit/test_fmp_provider.py`

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/unit/test_fmp_provider.py

def _fmp_news_response(ticker: str = "AAPL") -> list[dict]:
    return [
        {"title": "Apple Q4 earnings beat", "site": "Reuters", "publishedDate": "2024-10-31T16:00:00.000Z", "url": "https://example.com/1"},
        {"title": "iPhone 16 sales strong", "site": "Bloomberg", "publishedDate": "2024-10-30T14:00:00.000Z", "url": "https://example.com/2"},
    ]


class TestFMPNews:
    @pytest.mark.asyncio
    async def test_fetch_news_returns_data_result_with_news_items(self, provider):
        with patch.object(provider, "_get", AsyncMock(return_value=_mock_response(_fmp_news_response()))):
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_fmp_provider.py::TestFMPNews -x -v --tb=short
```

- [ ] **Step 3: Add news support to FMP provider**

Update `_SUPPORTED` and add news branch to `fetch()`:

```python
_SUPPORTED = ["financials", "news"]
```

Add `_fetch_news` method and news branch in `fetch()`:

```python
# In fetch(), after the financial data section:
if data_type == "news":
    return await self._fetch_news(ticker)
# ... existing financials code ...

async def _fetch_news(self, ticker: str) -> DataResult:
    """Fetch recent news from FMP News API."""
    try:
        resp = await self._get(f"/stock_news", params={"tickers": ticker, "limit": 20})
        raw = resp.json()
    except Exception as e:
        raise ProviderError(f"FMP news fetch failed for '{ticker}': {e}") from e

    news_items = []
    for item in (raw or []):
        news_items.append({
            "title": item.get("title", ""),
            "source": item.get("site", ""),
            "published": item.get("publishedDate", ""),
            "url": item.get("url", ""),
        })

    return DataResult(
        data={"news_items": news_items},
        provider=self.name,
        ticker=ticker,
        data_type="news",
        timestamp=datetime.now(tz=timezone.utc),
    )
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_fmp_provider.py -x -v --tb=short
```

- [ ] **Step 5: Commit**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && git add finrobot/engine/data/providers/fmp_provider.py tests/unit/test_fmp_provider.py && git commit -m "feat(P2c-6): add FMP news capability"
```

---

### Task 11: Finnhub news capability (File 7)

**Files:**
- Modify: `finrobot/engine/data/providers/finnhub_provider.py`
- Test: `tests/unit/test_finnhub_provider.py`

Same pattern as Task 10 — add `"news"` to `_SUPPORTED`, add `_fetch_news()` method using Finnhub's `/company-news` endpoint. Returns `DataResult(data={"news_items": [...]})`.

- [ ] **Step 1: Write the failing test** (similar pattern to FMP)
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** — add `"news"` to `_SUPPORTED`, news branch in `fetch()`, `_fetch_news()` method
- [ ] **Step 4: Run tests**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_finnhub_provider.py -x -v --tb=short
```

- [ ] **Step 5: Commit**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && git add finrobot/engine/data/providers/finnhub_provider.py tests/unit/test_finnhub_provider.py && git commit -m "feat(P2c-7): add Finnhub news capability"
```

---

### Task 12: News module — `news.py` (File 8)

**Files:**
- Create: `finrobot/engine/compute/news.py`
- Test: `tests/unit/test_news.py`

**Context:** Defines `RawNewsItem`, `NewsItem` (module-internal types). `fetch_news()` converts `DataResult.data["news_items"]` to `list[RawNewsItem]`. `classify_news()` uses PydanticAI to classify via LLM.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_news.py
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from finrobot.engine.data.interface import DataResult
from finrobot.engine.compute.news import RawNewsItem, NewsItem, parse_raw_news


class TestParseRawNews:
    def test_converts_data_result_to_raw_news_items(self):
        dr = DataResult(
            data={"news_items": [
                {"title": "Apple beats Q4", "source": "Reuters",
                 "published": "2024-10-31T16:00:00.000Z", "url": "https://example.com/1"},
                {"title": "iPhone strong", "source": "Bloomberg",
                 "published": "2024-10-30T14:00:00.000Z", "url": "https://example.com/2"},
            ]},
            provider="fmp", ticker="AAPL", data_type="news",
            timestamp=datetime.now(tz=timezone.utc),
        )
        items = parse_raw_news(dr)
        assert len(items) == 2
        assert isinstance(items[0], RawNewsItem)
        assert items[0].title == "Apple beats Q4"
        assert items[0].source == "Reuters"

    def test_empty_news_items(self):
        dr = DataResult(
            data={"news_items": []},
            provider="fmp", ticker="AAPL", data_type="news",
            timestamp=datetime.now(tz=timezone.utc),
        )
        assert parse_raw_news(dr) == []

    def test_missing_news_items_key(self):
        dr = DataResult(
            data={},
            provider="fmp", ticker="AAPL", data_type="news",
            timestamp=datetime.now(tz=timezone.utc),
        )
        assert parse_raw_news(dr) == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_news.py -x -v --tb=short
```

- [ ] **Step 3: Implement `news.py`**

```python
# finrobot/engine/compute/news.py
"""News fetching and classification.

What this code does that raw LLM cannot: deterministic conversion of
provider DataResult into typed RawNewsItem list. The LLM does classification;
this module handles I/O and type conversion.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from finrobot.engine.data.interface import DataResult


class RawNewsItem(BaseModel):
    """Raw news item from provider, before LLM classification."""

    title: str
    source: str
    published: datetime
    url: str


class NewsItem(BaseModel):
    """News item after LLM classification and sentiment analysis."""

    title: str
    source: str
    published: datetime
    url: str
    category: Literal[
        "earnings", "product", "regulatory", "macro",
        "analyst", "management", "other",
    ]
    sentiment: Literal["positive", "negative", "neutral"]
    importance: int = Field(ge=1, le=5)
    summary: str


def _parse_datetime(s: str) -> datetime:
    """Parse ISO datetime string. Handles various provider formats."""
    from datetime import timezone as tz
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        dt = datetime.now(tz=tz.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz.utc)
    return dt


def parse_raw_news(data_result: DataResult) -> list[RawNewsItem]:
    """Convert DataResult.data['news_items'] to typed RawNewsItem list."""
    items = data_result.data.get("news_items", [])
    return [
        RawNewsItem(
            title=item.get("title", ""),
            source=item.get("source", ""),
            published=_parse_datetime(item.get("published", "")),
            url=item.get("url", ""),
        )
        for item in items
        if item.get("title")
    ]
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_news.py -x -v --tb=short
```

- [ ] **Step 5: Run full test suite**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/ -x -v --tb=short
```

- [ ] **Step 6: Commit**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && git add finrobot/engine/compute/news.py tests/unit/test_news.py && git commit -m "feat(P2c-8): add news module with RawNewsItem parsing"
```

---

### Task 13: Add matplotlib + jinja2 to pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dependencies**

Add to the `dependencies` list in `pyproject.toml`:

```toml
"matplotlib>=3.8",
"jinja2>=3.1",
"weasyprint>=61",
```

- [ ] **Step 2: Install**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && uv sync
```

- [ ] **Step 3: Verify import works**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -c "import matplotlib; import jinja2; import weasyprint; print('OK')"
```

**Note:** weasyprint requires system libraries (pango, cairo). On macOS: `brew install pango`. On Linux: `apt-get install libpango-1.0-0 libpangocairo-1.0-0`. If weasyprint install fails, use `reportlab>=4.0` as fallback.

- [ ] **Step 4: Commit**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && git add pyproject.toml uv.lock && git commit -m "chore(P2c): add matplotlib and jinja2 dependencies"
```

---

## Phase B: Charts + Reports

> **Note:** Phase B and C tasks follow the same TDD pattern as Phase A. Due to the massive scope (42 tasks total), Phase A provides full code for every task. Phase B provides the first chart in full detail as a template; remaining charts follow the identical pattern. Phase C provides structural guidance. **Before starting Phase B or C, the implementer should expand these sections to full detail using the Phase A template and the spec (`specs/P2c.md`)** — specifically the chart data contract table (spec lines 189-201) and frontend test strategy (spec lines 562-566).

### Task 14: Chart base — `ChartConfig`, `render_to_base64`, `ChartDataPoint` (File 9)

**Files:**
- Create: `finrobot/engine/charts/__init__.py`
- Create: `finrobot/engine/charts/base.py`
- Test: `tests/unit/test_charts_base.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_charts_base.py
import pytest
from finrobot.engine.charts.base import ChartConfig, render_to_base64, validate_png, ChartDataPoint, StepChartData


class TestChartConfig:
    def test_default_colors(self):
        config = ChartConfig()
        assert config.primary_color == "#1a365d"
        assert config.accent_color == "#d4a843"
        assert config.neutral_color == "#6b7280"

    def test_default_size(self):
        config = ChartConfig()
        assert config.width == 10
        assert config.height == 6


class TestRenderToBase64:
    def test_returns_valid_base64_string(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots()
        ax.bar(["A", "B"], [1, 2])
        ax.set_title("Test")

        png_bytes = render_to_base64(fig)
        assert isinstance(png_bytes, str)
        assert png_bytes.startswith("data:image/png;base64,")
        plt.close(fig)


class TestValidatePng:
    def test_valid_png(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot([1, 2, 3])
        import io
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100)
        data = buf.getvalue()
        plt.close(fig)

        assert validate_png(data) is True
        assert data[:4] == b"\x89PNG"

    def test_invalid_png(self):
        assert validate_png(b"not a png") is False


class TestChartDataPoint:
    def test_valid_construction(self):
        cdp = ChartDataPoint(
            chart_type="revenue_ebitda",
            data=[{"year": 2024, "revenue": 394e9, "ebitda": 130e9, "is_forecast": False}],
            title="Revenue & EBITDA",
        )
        assert cdp.chart_type == "revenue_ebitda"
        assert len(cdp.data) == 1


class TestStepChartData:
    def test_default_empty(self):
        scd = StepChartData()
        assert scd.charts == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_charts_base.py -x -v --tb=short
```

- [ ] **Step 3: Create `__init__.py` and `base.py`**

```python
# finrobot/engine/charts/__init__.py
```

```python
# finrobot/engine/charts/base.py
"""Chart configuration, rendering utilities, and chart data types.

What this code does that raw LLM cannot: generates actual PNG image bytes
from matplotlib figures with consistent professional styling. Also defines
the typed data contract between backend and frontend chart rendering.
"""

from __future__ import annotations

import base64
import io
from typing import Literal

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pydantic import BaseModel


class ChartConfig(BaseModel):
    """Unified chart styling for professional financial reports."""

    primary_color: str = "#1a365d"
    accent_color: str = "#d4a843"
    neutral_color: str = "#6b7280"
    background_color: str = "#ffffff"
    font_family: str = "sans-serif"
    width: float = 10
    height: float = 6
    dpi: int = 150


class ChartDataPoint(BaseModel):
    """Single chart's data for SSE transmission to frontend."""

    chart_type: Literal[
        "revenue_ebitda", "margin_trend", "peer_comparison",
        "sensitivity", "football_field", "price", "eps_pe",
        "waterfall", "radar",
    ]
    data: list[dict[str, float | str | None | bool]]
    title: str
    x_label: str = ""
    y_label: str = ""


class StepChartData(BaseModel):
    """All chart data produced by a single pipeline step."""

    charts: list[ChartDataPoint] = []


def render_to_base64(fig: plt.Figure, dpi: int = 150) -> str:
    """Render matplotlib Figure to base64-encoded PNG data URI."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor="white")
    buf.seek(0)
    encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
    plt.close(fig)
    return f"data:image/png;base64,{encoded}"


def validate_png(data: bytes) -> bool:
    """Check if bytes represent a valid PNG (magic bytes check)."""
    return len(data) > 8 and data[:4] == b"\x89PNG"
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_charts_base.py -x -v --tb=short
```

- [ ] **Step 5: Commit**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && git add finrobot/engine/charts/__init__.py finrobot/engine/charts/base.py tests/unit/test_charts_base.py && git commit -m "feat(P2c-9): add chart base with ChartConfig, render_to_base64, ChartDataPoint"
```

---

### Tasks 15–23: Individual chart files (Files 10a–10i)

Each chart follows the same template. For brevity, here's the pattern and the first one in full:

**Template per chart:**
1. Write test: verify PNG magic bytes, size matches config, title/labels correct
2. Run test → fails
3. Implement `render(data, config) -> bytes`
4. Run test → passes
5. Commit

#### Task 15: `revenue_ebitda.py` (File 10a)

**Files:**
- Create: `finrobot/engine/charts/revenue_ebitda.py`
- Test: `tests/unit/test_chart_revenue_ebitda.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_chart_revenue_ebitda.py
import pytest
from finrobot.engine.charts.base import ChartConfig, validate_png, ChartDataPoint
from finrobot.engine.charts.revenue_ebitda import render


def _sample_data() -> ChartDataPoint:
    return ChartDataPoint(
        chart_type="revenue_ebitda",
        title="AAPL Revenue & EBITDA",
        data=[
            {"year": 2022, "revenue": 300e9, "ebitda": 100e9, "is_forecast": False},
            {"year": 2023, "revenue": 350e9, "ebitda": 120e9, "is_forecast": False},
            {"year": 2024, "revenue": 394e9, "ebitda": 130e9, "is_forecast": False},
            {"year": 2025, "revenue": 422e9, "ebitda": 139e9, "is_forecast": True},
        ],
    )


class TestRevenueEbitdaChart:
    def test_renders_valid_png(self):
        data = _sample_data()
        png_bytes = render(data)
        assert validate_png(png_bytes)
        assert len(png_bytes) > 1000  # reasonable minimum size

    def test_figure_has_correct_title(self):
        """Verify matplotlib Figure title before rendering."""
        import matplotlib
        matplotlib.use("Agg")
        from finrobot.engine.charts.revenue_ebitda import _create_figure

        data = _sample_data()
        fig = _create_figure(data)
        ax = fig.axes[0]
        assert "Revenue" in ax.get_title() or "AAPL" in fig._suptitle.get_text()

    def test_respects_chart_config_size(self):
        data = _sample_data()
        config = ChartConfig(width=12, height=8)
        png_bytes = render(data, config=config)
        assert validate_png(png_bytes)
```

- [ ] **Step 2-5: Implement, test, commit**

```python
# finrobot/engine/charts/revenue_ebitda.py
"""Revenue & EBITDA bar chart with forecast distinction."""

from __future__ import annotations

import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from finrobot.engine.charts.base import ChartConfig, ChartDataPoint


def _create_figure(
    data: ChartDataPoint, config: ChartConfig | None = None
) -> plt.Figure:
    cfg = config or ChartConfig()
    fig, ax = plt.subplots(figsize=(cfg.width, cfg.height))

    years = [d["year"] for d in data.data]
    revenues = [d["revenue"] / 1e9 for d in data.data]
    ebitdas = [d["ebitda"] / 1e9 for d in data.data]
    is_forecast = [d.get("is_forecast", False) for d in data.data]

    x = np.arange(len(years))
    width = 0.35

    # Historical bars solid, forecast bars hatched
    for i, (yr, rev, ebt, fc) in enumerate(zip(years, revenues, ebitdas, is_forecast)):
        hatch = "//" if fc else None
        alpha = 0.7 if fc else 1.0
        ax.bar(x[i] - width / 2, rev, width, color=cfg.primary_color,
               alpha=alpha, hatch=hatch, label="Revenue" if i == 0 else "")
        ax.bar(x[i] + width / 2, ebt, width, color=cfg.accent_color,
               alpha=alpha, hatch=hatch, label="EBITDA" if i == 0 else "")

    ax.set_xticks(x)
    ax.set_xticklabels([str(int(y)) + ("E" if fc else "") for y, fc in zip(years, is_forecast)])
    ax.set_ylabel("USD (Billions)")
    ax.set_title(data.title)
    ax.legend()
    fig.tight_layout()
    return fig


def render(data: ChartDataPoint, config: ChartConfig | None = None) -> bytes:
    """Render Revenue & EBITDA bar chart as PNG bytes."""
    fig = _create_figure(data, config)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=(config or ChartConfig()).dpi,
                bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()
```

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && git add finrobot/engine/charts/revenue_ebitda.py tests/unit/test_chart_revenue_ebitda.py && git commit -m "feat(P2c-10a): add revenue/EBITDA bar chart"
```

#### Tasks 16–23: Remaining charts (Files 10b–10i)

Each follows the same pattern. The implementer should:

1. **10b: `margin_trend.py`** — multi-line chart with 3 margin series (gross, EBITDA, operating). Test: 3 lines rendered, y-axis labeled "Margin (%)".
2. **10c: `peer_comparison.py`** — grouped bar chart, target ticker highlighted. Test: target bar uses `accent_color`.
3. **10d: `sensitivity.py`** — WACC×TG heatmap using `ax.imshow()`. Test: correct dimensions (len(wacc) × len(tg)).
4. **10e: `football_field.py`** — horizontal bar chart with low/mid/high ranges. Test: one bar per method.
5. **10f: `price_chart.py`** — price line + volume bars (dual y-axis). Test: two axes created.
6. **10g: `eps_pe.py`** — dual-axis chart. Test: left axis "EPS", right axis "PE Ratio".
7. **10h: `waterfall.py`** — waterfall with running total. Test: final bar labeled "Equity Value" or "is_total=True".
8. **10i: `radar.py`** — polar projection radar chart. Test: uses `projection='polar'`.

**Each chart commit message:** `feat(P2c-10X): add [chart_name] chart`

---

### Task 24: HTML report renderer (File 11)

**Files:**
- Create: `finrobot/engine/reports/__init__.py`
- Create: `finrobot/engine/reports/html_renderer.py`
- Test: `tests/unit/test_html_renderer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_html_renderer.py
import pytest
from finrobot.engine.reports.html_renderer import render_equity_report


class TestRenderEquityReport:
    def test_returns_html_string(self):
        context = {
            "ticker": "AAPL",
            "company_name": "Apple Inc.",
            "current_price": 230.0,
            "market_cap": 3e12,
            "recommendation": "Buy",
            "charts": {},  # base64 chart strings
        }
        html = render_equity_report(context)
        assert "<html" in html.lower()
        assert "AAPL" in html
        assert "Apple Inc." in html

    def test_contains_all_five_pages(self):
        context = {
            "ticker": "TEST",
            "company_name": "Test Corp",
            "current_price": 100.0,
            "market_cap": 1e9,
            "recommendation": "Hold",
            "charts": {},
        }
        html = render_equity_report(context)
        assert "page-1" in html or "overview" in html.lower()
```

- [ ] **Step 2–6: Implement (Jinja2 rendering + template), test, commit**

The renderer loads templates from `finrobot/engine/reports/templates/` and fills them with context data + base64 chart images.

---

### Task 25: HTML templates (File 12)

Create 3 Jinja2 templates. These are HTML files, not Python — test them through the renderer.

- [ ] **Step 1:** Create `finrobot/engine/reports/templates/equity_research.html`
- [ ] **Step 2:** Create `finrobot/engine/reports/templates/comps.html`
- [ ] **Step 3:** Create `finrobot/engine/reports/templates/dcf.html`
- [ ] **Step 4:** Test through renderer tests
- [ ] **Step 5:** Commit

---

### Task 26: PDF renderer (File 13)

Create `finrobot/engine/reports/pdf_renderer.py` using weasyprint (or reportlab fallback). Test: generates bytes that start with `%PDF`.

---

### Task 27: Server endpoints (File 14)

Add `/api/report/html` and `/api/report/pdf` endpoints to `finrobot/server.py`. Add `chart_data: StepChartData | None` to pipeline event structure.

---

## Phase C: Desktop UI

> Phase C tasks (28–35) cover frontend work. Due to the different toolchain (npm, TypeScript, vitest), each task includes npm commands. The implementer should follow the spec's File 15–21 ordering.

### Task 28: Tech stack upgrade (File 15)

- [ ] Install dependencies:
```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot/desktop && npm install recharts zustand electron-store && npm install -D tailwindcss@4 vitest @testing-library/react @testing-library/jest-dom jsdom
```
- [ ] Add `@import "tailwindcss"` to `desktop/src/index.css`
- [ ] Create `desktop/src/stores/appStore.ts` (Zustand store)
- [ ] Commit

### Task 29: Layout components (File 16)

- Create `Layout.tsx` (left/right split) and `DataPanel.tsx`
- Test with vitest: renders without crash, contains expected DOM structure

### Tasks 30–38: Recharts components (File 17a–17i)

One component per task, each with `*.test.tsx`. Follow the `ChartDataPoint` data contract table from the spec.

### Task 39: Settings page (File 18)

- `SettingsView.tsx` with electron-store + safeStorage

### Task 40: Report preview + download (File 19)

- "View Full Report" button opens new window
- "Download PDF" button calls `/api/report/pdf`

### Task 41: Update existing views (File 20)

- `ResearchView.tsx`: add chart rendering from `chart_data`
- `DCFView.tsx`: add sensitivity heatmap + waterfall
- `CompsView.tsx`: add peer comparison chart

### Task 42: Update App.tsx (File 21)

- Integrate Zustand store
- Add Settings tab
- Wrap in Layout component

---

## Final Verification

After all tasks complete:

- [ ] **Run full backend test suite:**
```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/ -x -v --tb=short
```

- [ ] **Run frontend tests:**
```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot/desktop && npm run test
```

- [ ] **Verify acceptance criteria from spec** (all 16 items in `specs/P2c.md` §验收标准)

- [ ] **Update ARCHITECTURE.md** (post-implementation, per spec §Self-Review)
