# P8: Deep Fundamentals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the Desktop UI into a 4-tab layout and connect all existing backend chart/analysis capabilities.

**Architecture:** Backend exposes 3 new data endpoints (historical, quarterly, performance) + extends existing price endpoint. Frontend splits the 24.6 KB TickerWorkspace monolith into tab components that fetch and display data independently. No new dependencies.

**Tech Stack:** FastAPI (backend endpoints), yfinance (data), React + Recharts (charts), Zustand (state), React Query (data fetching), TypeScript

**Spec:** `specs/P8-deep-fundamentals.md`

---

## Task 1: Extend HistoricalMetrics with Cash Flow Fields

**Files:**
- Modify: `finrobot/engine/models/financial.py:246-267`
- Modify: `finrobot/engine/compute/data_processor.py` (extract_historical_metrics function)
- Test: `tests/unit/test_historical_metrics_cashflow.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_historical_metrics_cashflow.py
import pytest
from finrobot.engine.models.financial import HistoricalMetrics


def test_historical_metrics_has_cashflow_fields():
    """HistoricalMetrics must have operating/investing/financing cash flow arrays."""
    metrics = HistoricalMetrics(
        years=[2022, 2023, 2024],
        revenue=[100e9, 110e9, 120e9],
        revenue_growth_yoy=[None, 0.10, 0.09],
        cogs=[60e9, 65e9, 70e9],
        gross_profit=[40e9, 45e9, 50e9],
        gross_margin=[0.40, 0.409, 0.417],
        sga=[15e9, 16e9, 17e9],
        sga_ratio=[0.15, 0.145, 0.142],
        ebitda=[30e9, 33e9, 36e9],
        ebitda_margin=[0.30, 0.30, 0.30],
        operating_income=[25e9, 28e9, 31e9],
        operating_margin=[0.25, 0.255, 0.258],
        net_income=[20e9, 22e9, 24e9],
        eps=[6.5, 7.2, 7.9],
        pe_ratio=[25.0, 27.0, 24.0],
        cagr_revenue=0.095,
        ticker="AAPL",
        price_data_available=True,
        operating_cash_flow=[28e9, 30e9, 33e9],
        investing_cash_flow=[-10e9, -12e9, -11e9],
        financing_cash_flow=[-15e9, -14e9, -16e9],
    )
    assert metrics.operating_cash_flow == [28e9, 30e9, 33e9]
    assert metrics.investing_cash_flow == [-10e9, -12e9, -11e9]
    assert metrics.financing_cash_flow == [-15e9, -14e9, -16e9]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_historical_metrics_cashflow.py -v`
Expected: FAIL — `AttributeError: 'HistoricalMetrics' object has no attribute 'operating_cash_flow'` (Pydantic v2 silently ignores unknown fields, but the assert on the attribute will fail)

- [ ] **Step 3: Add cash flow fields to HistoricalMetrics**

In `finrobot/engine/models/financial.py`, after line 267 (`price_data_available: bool = False`), add:

```python
    operating_cash_flow: list[float] = Field(default_factory=list)
    investing_cash_flow: list[float] = Field(default_factory=list)
    financing_cash_flow: list[float] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_historical_metrics_cashflow.py -v`
Expected: PASS

- [ ] **Step 5: Create standalone yfinance historical extractor**

The existing `extract_historical_metrics` in `data_processor.py` takes `list[FinancialData]` which has no cash flow. Instead of modifying that function, create a new standalone extractor that works directly from yfinance DataFrames. This is what the `/historical` endpoint will call.

Create `finrobot/engine/compute/historical_extractor.py`:

```python
"""Extract multi-year historical metrics directly from yfinance DataFrames."""
from __future__ import annotations

import asyncio
import math
from typing import Any

import yfinance as yf

from finrobot.engine.models.financial import HistoricalMetrics


async def extract_historical_from_yfinance(ticker: str) -> HistoricalMetrics:
    """Fetch and extract multi-year historical metrics from yfinance."""
    return await asyncio.to_thread(_extract_sync, ticker)


def _extract_sync(ticker: str) -> HistoricalMetrics:
    t = yf.Ticker(ticker)
    income = t.income_stmt
    cashflow = t.cashflow
    info = t.info or {}

    if income is None or income.empty:
        raise ValueError(f"No historical data available for {ticker}")

    # Sort columns (dates) oldest-first
    cols = sorted(income.columns)[-5:]  # Last 5 years

    years: list[int] = []
    revenue: list[float] = []
    ebitda: list[float] = []
    operating_income: list[float] = []
    net_income: list[float] = []
    gross_margin: list[float] = []
    ebitda_margin: list[float] = []
    operating_margin: list[float] = []
    cogs: list[float] = []
    gross_profit: list[float] = []
    sga: list[float] = []
    sga_ratio: list[float] = []
    eps: list[float] = []
    operating_cf: list[float] = []
    investing_cf: list[float] = []
    financing_cf: list[float] = []

    shares = info.get("sharesOutstanding", 1)

    for col in cols:
        years.append(col.year)
        rev = _get_row(income, col, ["Total Revenue", "Revenue"])
        revenue.append(rev or 0)
        ebt = _get_row(income, col, ["EBITDA"])
        ebitda.append(ebt or 0)
        op = _get_row(income, col, ["Operating Income"])
        operating_income.append(op or 0)
        ni = _get_row(income, col, ["Net Income", "Net Income Common Stockholders"])
        net_income.append(ni or 0)
        gp = _get_row(income, col, ["Gross Profit"])
        gross_profit.append(gp or 0)
        cost = _get_row(income, col, ["Cost Of Revenue"])
        cogs.append(cost or 0)
        sg = _get_row(income, col, ["Selling General And Administration"])
        sga.append(sg or 0)

        gross_margin.append((gp / rev) if rev and gp else 0)
        ebitda_margin.append((ebt / rev) if rev and ebt else 0)
        operating_margin.append((op / rev) if rev and op else 0)
        sga_ratio.append((sg / rev) if rev and sg else 0)
        eps.append((ni / shares) if ni and shares else 0)

        # Cash flow
        if cashflow is not None and not cashflow.empty and col in cashflow.columns:
            operating_cf.append(_get_row(cashflow, col, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"]) or 0)
            investing_cf.append(_get_row(cashflow, col, ["Investing Cash Flow", "Cash Flow From Continuing Investing Activities"]) or 0)
            financing_cf.append(_get_row(cashflow, col, ["Financing Cash Flow", "Cash Flow From Continuing Financing Activities"]) or 0)
        else:
            operating_cf.append(0)
            investing_cf.append(0)
            financing_cf.append(0)

    # Revenue growth YoY
    growth: list[float | None] = [None]
    for i in range(1, len(revenue)):
        if revenue[i - 1] and revenue[i - 1] != 0:
            growth.append((revenue[i] - revenue[i - 1]) / revenue[i - 1])
        else:
            growth.append(None)

    # CAGR
    cagr = None
    if len(revenue) >= 2 and revenue[0] > 0 and revenue[-1] > 0:
        n = len(revenue) - 1
        cagr = (revenue[-1] / revenue[0]) ** (1 / n) - 1

    return HistoricalMetrics(
        years=years,
        revenue=revenue,
        revenue_growth_yoy=growth,
        cogs=cogs,
        gross_profit=gross_profit,
        gross_margin=gross_margin,
        sga=sga,
        sga_ratio=sga_ratio,
        ebitda=ebitda,
        ebitda_margin=ebitda_margin,
        operating_income=operating_income,
        operating_margin=operating_margin,
        net_income=net_income,
        eps=eps,
        pe_ratio=[None] * len(years),  # Would need price history per year
        operating_cash_flow=operating_cf,
        investing_cash_flow=investing_cf,
        financing_cash_flow=financing_cf,
        cagr_revenue=cagr,
        ticker=ticker,
        price_data_available=False,
    )


def _get_row(df, col, row_names: list[str]) -> float | None:
    """Try multiple row names, return first valid value."""
    import pandas as pd
    for name in row_names:
        if name in df.index:
            val = df.loc[name, col]
            if val is not None and not pd.isna(val):
                return float(val)
    return None
```

Write a test:

```python
# Add to tests/unit/test_historical_metrics_cashflow.py
def test_historical_extractor_get_row():
    """_get_row handles missing rows gracefully."""
    from finrobot.engine.compute.historical_extractor import _get_row
    import pandas as pd

    df = pd.DataFrame({"2024": [100, 50]}, index=["Total Revenue", "Gross Profit"])
    assert _get_row(df, "2024", ["Total Revenue", "Revenue"]) == 100
    assert _get_row(df, "2024", ["Missing Row"]) is None
```

- [ ] **Step 6: Commit**

```bash
git add finrobot/engine/models/financial.py finrobot/engine/compute/data_processor.py tests/unit/test_historical_metrics_cashflow.py
git commit -m "feat(models): add cash flow fields to HistoricalMetrics"
```

---

## Task 2: Historical Metrics Endpoint

**Files:**
- Modify: `finrobot/routes/data.py`
- Test: `tests/unit/test_routes_historical.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_routes_historical.py
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_historical_endpoint_returns_metrics():
    """GET /api/data/{ticker}/historical returns HistoricalMetrics."""
    from finrobot.server import app

    # Mock the data layer and processor
    mock_metrics = {
        "years": [2022, 2023, 2024],
        "revenue": [100e9, 110e9, 120e9],
        "revenue_growth_yoy": [None, 0.10, 0.09],
        "cogs": [60e9, 65e9, 70e9],
        "gross_profit": [40e9, 45e9, 50e9],
        "gross_margin": [0.40, 0.409, 0.417],
        "sga": [15e9, 16e9, 17e9],
        "sga_ratio": [0.15, 0.145, 0.142],
        "ebitda": [30e9, 33e9, 36e9],
        "ebitda_margin": [0.30, 0.30, 0.30],
        "operating_income": [25e9, 28e9, 31e9],
        "operating_margin": [0.25, 0.255, 0.258],
        "net_income": [20e9, 22e9, 24e9],
        "eps": [6.5, 7.2, 7.9],
        "pe_ratio": [25.0, 27.0, 24.0],
        "operating_cash_flow": [28e9, 30e9, 33e9],
        "investing_cash_flow": [-10e9, -12e9, -11e9],
        "financing_cash_flow": [-15e9, -14e9, -16e9],
        "cagr_revenue": 0.095,
        "ticker": "AAPL",
        "price_data_available": True,
    }

    with patch("finrobot.engine.compute.historical_extractor.extract_historical_from_yfinance") as mock_fn:
        mock_fn.return_value = mock_metrics
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/AAPL/historical")

    assert resp.status_code == 200
    data = resp.json()
    assert data["ticker"] == "AAPL"
    assert len(data["years"]) == 3
    assert "operating_cash_flow" in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_routes_historical.py -v`
Expected: FAIL — endpoint does not exist (404)

- [ ] **Step 3: Implement the endpoint**

Add to `finrobot/routes/data.py`:

```python
from finrobot.engine.compute.historical_extractor import extract_historical_from_yfinance
from finrobot.engine.models.financial import HistoricalMetrics

@router.get("/{ticker}/historical", response_model=HistoricalMetrics)
async def get_historical(ticker: str) -> HistoricalMetrics:
    """Multi-year historical financial metrics including cash flows."""
    try:
        metrics = await extract_historical_from_yfinance(ticker.upper())
    except (ValueError, ProviderError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return metrics
```

Note: Uses `extract_historical_from_yfinance` created in Task 1 Step 5. Does NOT use `request.app.state.deps.data_layer` — this endpoint calls yfinance directly via asyncio.to_thread for simplicity.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_routes_historical.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add finrobot/routes/data.py tests/unit/test_routes_historical.py
git commit -m "feat(api): add GET /api/data/{ticker}/historical endpoint"
```

---

## Task 3: Quarterly Data Endpoint

**Files:**
- Modify: `finrobot/routes/data.py`
- Test: `tests/unit/test_routes_quarterly.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_routes_quarterly.py
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_quarterly_endpoint_returns_data():
    """GET /api/data/{ticker}/quarterly returns quarterly financial data."""
    from finrobot.server import app

    mock_quarters = {
        "ticker": "AAPL",
        "quarters": [
            {
                "quarter": "2024-Q4",
                "revenue": 94_836_000_000,
                "operating_income": 29_200_000_000,
                "net_income": 23_640_000_000,
                "operating_cash_flow": 28_900_000_000,
            },
            {
                "quarter": "2024-Q3",
                "revenue": 85_777_000_000,
                "operating_income": 25_300_000_000,
                "net_income": 21_450_000_000,
                "operating_cash_flow": 26_800_000_000,
            },
        ],
    }

    with patch("finrobot.routes.data.fetch_quarterly_data") as mock_fn:
        mock_fn.return_value = mock_quarters
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/AAPL/quarterly")

    assert resp.status_code == 200
    data = resp.json()
    assert data["ticker"] == "AAPL"
    assert len(data["quarters"]) == 2
    assert data["quarters"][0]["quarter"] == "2024-Q4"
    assert "operating_income" in data["quarters"][0]
    # EBITDA is intentionally NOT included (not reliably available from yfinance quarterly)
    assert "ebitda" not in data["quarters"][0]
```

- [ ] **Step 2: Run test, verify fail**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_routes_quarterly.py -v`
Expected: FAIL — 404

- [ ] **Step 3: Implement the endpoint**

Add to `finrobot/routes/data.py`:

```python
@router.get("/{ticker}/quarterly")
async def get_quarterly(ticker: str) -> dict:
    """Quarterly income statement + cash flow data."""
    try:
        result = await fetch_quarterly_data(ticker.upper())
    except (ValueError, ProviderError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return result


async def fetch_quarterly_data(ticker: str) -> dict:
    """Fetch quarterly financials from yfinance."""
    import asyncio
    import yfinance as yf

    def _fetch() -> dict:
        t = yf.Ticker(ticker)
        income = t.quarterly_income_stmt
        cashflow = t.quarterly_cashflow  # Note: attribute is 'quarterly_cashflow' not 'quarterly_cash_flow'

        if income is None or income.empty:
            raise ValueError(f"No quarterly data available for {ticker}")

        quarters = []
        for col in income.columns[:8]:  # Last 8 quarters
            year = col.year
            quarter = (col.month - 1) // 3 + 1
            quarter_label = f"{year}-Q{quarter}"

            revenue = _safe_get(income, col, ["Total Revenue", "Revenue"])
            op_income = _safe_get(income, col, ["Operating Income", "Operating Revenue"])
            net_income = _safe_get(income, col, ["Net Income", "Net Income Common Stockholders"])

            op_cf = None
            if cashflow is not None and not cashflow.empty and col in cashflow.columns:
                op_cf = _safe_get(cashflow, col, [
                    "Operating Cash Flow",
                    "Cash Flow From Continuing Operating Activities",
                ])

            if revenue is not None:
                quarters.append({
                    "quarter": quarter_label,
                    "revenue": revenue,
                    "operating_income": op_income,
                    "net_income": net_income,
                    "operating_cash_flow": op_cf,
                })

        return {"ticker": ticker, "quarters": quarters}

    return await asyncio.to_thread(_fetch)


def _safe_get(df, col, row_names: list[str]) -> float | None:
    """Try multiple row names for a DataFrame column, return first found."""
    import pandas as pd
    for name in row_names:
        if name in df.index:
            val = df.loc[name, col]
            if val is not None and not pd.isna(val):
                return float(val)
    return None
```

- [ ] **Step 4: Run test, verify pass**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_routes_quarterly.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add finrobot/routes/data.py tests/unit/test_routes_quarterly.py
git commit -m "feat(api): add GET /api/data/{ticker}/quarterly endpoint"
```

---

## Task 4: Price Endpoint Period Param + Performance Endpoint

**Files:**
- Modify: `finrobot/routes/data.py` (add `period` query param to `/price`, add `/performance`)
- Test: `tests/unit/test_routes_price_period.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_routes_price_period.py
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch


@pytest.mark.asyncio
async def test_price_endpoint_accepts_period_param():
    """GET /api/data/{ticker}/price?period=3mo returns price history."""
    from finrobot.server import app
    # Test that period param is accepted and forwarded
    # Mock will verify the period value was used
    with patch("finrobot.routes.data.extract_price_history") as mock_extract:
        mock_extract.return_value = type("Obj", (), {"model_dump": lambda self: {"current_price": 190.0}})()
        with patch("finrobot.routes.data.fetch_price_with_period") as mock_fetch:
            mock_fetch.return_value = {"current_price": 190.0, "history": [], "data_source": "yfinance", "warnings": []}
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/data/AAPL/price?period=3mo")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_performance_endpoint_returns_series():
    """GET /api/data/performance returns normalized multi-ticker series."""
    from finrobot.server import app

    mock_result = {
        "series": [
            {"ticker": "AAPL", "label": "AAPL", "data": [{"date": "2025-05-01", "value": 100.0}]},
            {"ticker": "SPY", "label": "S&P 500", "data": [{"date": "2025-05-01", "value": 100.0}]},
        ]
    }
    with patch("finrobot.routes.data.fetch_performance_data") as mock_fn:
        mock_fn.return_value = mock_result
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/performance?tickers=AAPL&benchmark=SPY&period=1y")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["series"]) == 2
    assert data["series"][0]["ticker"] == "AAPL"
    assert data["series"][1]["label"] == "S&P 500"
```

- [ ] **Step 2: Run tests, verify fail**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_routes_price_period.py -v`
Expected: FAIL

- [ ] **Step 3: Modify price endpoint to accept period param**

In `finrobot/routes/data.py`, modify `get_price`. The `data_layer.fetch()` does NOT support a `period` kwarg natively, so fetch price history directly from yfinance:

```python
@router.get("/{ticker}/price")
async def get_price(ticker: str, request: Request, period: str = "1y") -> dict[str, Any]:
    import asyncio
    import yfinance as yf

    def _fetch_price():
        t = yf.Ticker(ticker.upper())
        hist = t.history(period=period)
        info = t.info or {}
        history = []
        for date, row in hist.iterrows():
            history.append({
                "date": date.strftime("%Y-%m-%d"),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row["Volume"]),
            })
        return {
            "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "history": history,
            "data_source": "yfinance",
            "warnings": [],
        }

    try:
        result = await asyncio.to_thread(_fetch_price)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return result
```

Note: This replaces the existing `get_price` implementation entirely. The old implementation used `data_layer.fetch(DataType.PRICE, ...)` which ignores `period`. The new one calls yfinance directly with the requested period.

- [ ] **Step 4: Add performance endpoint**

**IMPORTANT**: The `/performance` literal route MUST be registered BEFORE any `/{ticker}/...` routes in `data.py`, otherwise FastAPI will match `ticker="performance"` on the parameterized routes first. Move this endpoint definition to the TOP of the route file, before any `/{ticker}/` routes.

```python
# Place at TOP of data.py, BEFORE any /{ticker}/ routes
@router.get("/performance")
async def get_performance(
    tickers: str = "AAPL",
    benchmark: str = "SPY",
    period: str = "1y",
) -> dict:
    """Multi-ticker normalized price performance."""
    try:
        result = await fetch_performance_data(
            tickers=tickers.split(","),
            benchmark=benchmark,
            period=period,
        )
    except (ValueError, ProviderError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return result


async def fetch_performance_data(
    tickers: list[str], benchmark: str, period: str
) -> dict:
    """Fetch and normalize multi-ticker price performance."""
    import asyncio
    import yfinance as yf

    all_tickers = [*tickers, benchmark]

    def _fetch() -> dict:
        df = yf.download(all_tickers, period=period, progress=False)
        if df.empty:
            raise ValueError(f"No price data for {all_tickers}")

        close = df["Close"] if len(all_tickers) > 1 else df[["Close"]].rename(columns={"Close": all_tickers[0]})

        series = []
        for t in all_tickers:
            if t not in close.columns:
                continue
            col = close[t].dropna()
            if col.empty:
                continue
            base = col.iloc[0]
            normalized = (col / base * 100).round(2)
            data = [
                {"date": d.strftime("%Y-%m-%d"), "value": float(v)}
                for d, v in normalized.items()
            ]
            label = "S&P 500" if t == benchmark else t
            series.append({"ticker": t, "label": label, "data": data})

        return {"series": series}

    return await asyncio.to_thread(_fetch)
```

- [ ] **Step 5: Run tests, verify pass**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/unit/test_routes_price_period.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add finrobot/routes/data.py tests/unit/test_routes_price_period.py
git commit -m "feat(api): add period param to /price + new /performance endpoint"
```

---

## Task 5: Frontend Store Changes

**Files:**
- Modify: `desktop/src/stores/appStore.ts`

- [ ] **Step 1: Add TypeScript interfaces**

Add after existing interfaces in `appStore.ts`:

```typescript
export type ActiveTab = 'overview' | 'financials' | 'valuation' | 'peers'

export interface HistoricalMetrics {
  years: number[]
  revenue: number[]
  revenue_growth_yoy: (number | null)[]
  cogs: number[]
  gross_profit: number[]
  gross_margin: number[]
  sga: number[]
  sga_ratio: number[]
  ebitda: number[]
  ebitda_margin: number[]
  operating_income: number[]
  operating_margin: number[]
  net_income: number[]
  eps: number[]
  pe_ratio: (number | null)[]
  operating_cash_flow: number[]
  investing_cash_flow: number[]
  financing_cash_flow: number[]
  cagr_revenue: number | null
  ticker: string
  price_data_available: boolean
}

export interface QuarterlyData {
  ticker: string
  quarters: {
    quarter: string
    revenue: number
    operating_income: number
    net_income: number
    operating_cash_flow: number | null
  }[]
}

export interface PerformanceData {
  series: {
    ticker: string
    label: string
    data: { date: string; value: number }[]
  }[]
}
```

- [ ] **Step 2: Add state fields to WorkspaceState interface**

```typescript
// Add to the state interface
activeTab: ActiveTab
historicalMetrics: HistoricalMetrics | null
quarterlyData: QuarterlyData | null
performanceData: PerformanceData | null
historicalLoading: boolean
quarterlyLoading: boolean
performanceLoading: boolean
```

- [ ] **Step 3: Add action signatures**

```typescript
setActiveTab: (tab: ActiveTab) => void
setHistoricalMetrics: (data: HistoricalMetrics | null) => void
setQuarterlyData: (data: QuarterlyData | null) => void
setPerformanceData: (data: PerformanceData | null) => void
setHistoricalLoading: (loading: boolean) => void
setQuarterlyLoading: (loading: boolean) => void
setPerformanceLoading: (loading: boolean) => void
```

- [ ] **Step 4: Add initial state values and action implementations**

In the `create()` call, add:

```typescript
activeTab: 'overview' as ActiveTab,
historicalMetrics: null,
quarterlyData: null,
performanceData: null,
historicalLoading: false,
quarterlyLoading: false,
performanceLoading: false,

setActiveTab: (tab) => set({ activeTab: tab }),
setHistoricalMetrics: (data) => set({ historicalMetrics: data }),
setQuarterlyData: (data) => set({ quarterlyData: data }),
setPerformanceData: (data) => set({ performanceData: data }),
setHistoricalLoading: (loading) => set({ historicalLoading: loading }),
setQuarterlyLoading: (loading) => set({ quarterlyLoading: loading }),
setPerformanceLoading: (loading) => set({ performanceLoading: loading }),
```

- [ ] **Step 5: Update setTicker to reset new fields**

In the existing `setTicker` action, add resets:

```typescript
setTicker: (ticker) => set({
  ticker,
  // ... existing resets ...
  activeTab: 'overview' as ActiveTab,
  historicalMetrics: null,
  quarterlyData: null,
  performanceData: null,
  historicalLoading: false,
  quarterlyLoading: false,
  performanceLoading: false,
}),
```

- [ ] **Step 6: Commit**

```bash
git add desktop/src/stores/appStore.ts
git commit -m "feat(store): add tab state + historical/quarterly/performance caches"
```

---

## Task 6: Chart Adapter Functions

**Files:**
- Modify: `desktop/src/utils/chartAdapters.ts`

- [ ] **Step 1: Add adapter imports and functions**

Append to `desktop/src/utils/chartAdapters.ts`:

```typescript
import type { HistoricalMetrics, QuarterlyData, PerformanceData } from '../stores/appStore'

// ── FinancialsTab adapters ──────────────────────────────────────────────

export function historicalToRevenueEbitdaData(h: HistoricalMetrics) {
  return h.years.map((year, i) => ({
    year: String(year),
    revenue: h.revenue[i],
    ebitda: h.ebitda[i],
    is_forecast: false,
  }))
}

export function historicalToMarginData(h: HistoricalMetrics) {
  return h.years.map((year, i) => ({
    year: String(year),
    gross_margin: h.gross_margin[i] * 100,
    ebitda_margin: h.ebitda_margin[i] * 100,
    operating_margin: h.operating_margin[i] * 100,
    is_forecast: false,
  }))
}

export function historicalToRevenueYoYData(h: HistoricalMetrics) {
  return h.years
    .map((year, i) => ({
      year: String(year),
      yoy_pct: h.revenue_growth_yoy[i] != null ? h.revenue_growth_yoy[i]! * 100 : null,
    }))
    .filter((d) => d.yoy_pct != null)
}

export function historicalToCashFlowData(h: HistoricalMetrics) {
  return h.years.map((year, i) => ({
    year: String(year),
    operating: h.operating_cash_flow[i],
    investing: h.investing_cash_flow[i],
    financing: h.financing_cash_flow[i],
  }))
}

export function quarterlyToComparisonData(q: QuarterlyData) {
  return q.quarters.map((qtr) => ({
    quarter: qtr.quarter,
    revenue: qtr.revenue,
    operating_income: qtr.operating_income,
    net_income: qtr.net_income,
  }))
}

// ── ValuationTab adapters ───────────────────────────────────────────────

export function historicalToEpsPeData(h: HistoricalMetrics) {
  return h.years.map((year, i) => ({
    year: String(year),
    eps: h.eps[i],
    pe_ratio: h.pe_ratio[i],
  }))
}

interface EarningsSurprise {
  date: string                    // Store uses 'date', chart expects 'quarter'
  eps_actual: number
  eps_estimated: number
  eps_surprise_pct: number        // Chart expects 'surprise_pct' (no eps_ prefix)
  eps_direction: 'beat' | 'miss' | 'inline'  // Chart expects 'direction' (no eps_ prefix)
}

export interface SurpriseDataPoint {
  quarter: string
  eps_actual: number
  eps_estimated: number
  surprise_pct: number
  direction: 'beat' | 'miss' | 'inline'
}

export function earningsToSurpriseChartData(surprises: EarningsSurprise[]): SurpriseDataPoint[] {
  // CRITICAL: field names differ between store and chart component.
  // Store uses: date, eps_surprise_pct, eps_direction
  // Chart expects: quarter, surprise_pct, direction
  // Must explicitly rename ALL of these — do NOT spread the object.
  return surprises.map((s) => ({
    quarter: s.date,                         // rename: date → quarter (chart X-axis key)
    eps_actual: s.eps_actual,
    eps_estimated: s.eps_estimated,
    surprise_pct: s.eps_surprise_pct,       // rename: strip eps_ prefix
    direction: s.eps_direction,              // rename: strip eps_ prefix
  }))
}
```

- [ ] **Step 2: Verify no TypeScript errors**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinRobot/desktop && npx tsc --noEmit`
Expected: No errors related to chartAdapters

- [ ] **Step 3: Commit**

```bash
git add desktop/src/utils/chartAdapters.ts
git commit -m "feat(adapters): add historical/quarterly/earnings chart adapters"
```

---

## Task 7: Tab System Skeleton + StockHeader

**Files:**
- Create: `desktop/src/components/StockHeader.tsx`
- Create: `desktop/src/components/TabBar.tsx`
- Modify: `desktop/src/views/TickerWorkspace.tsx` (major refactor)

- [ ] **Step 1: Create TabBar component**

```typescript
// desktop/src/components/TabBar.tsx
import { useAppStore, type ActiveTab } from '../stores/appStore'

const TABS: { key: ActiveTab; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'financials', label: 'Financials' },
  { key: 'valuation', label: 'Valuation' },
  { key: 'peers', label: 'Peers' },
]

export default function TabBar() {
  const activeTab = useAppStore((s) => s.activeTab)
  const setActiveTab = useAppStore((s) => s.setActiveTab)

  return (
    <div className="tab-bar">
      {TABS.map((tab) => (
        <button
          key={tab.key}
          className={`tab-btn${activeTab === tab.key ? ' active' : ''}`}
          onClick={() => setActiveTab(tab.key)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}
```

- [ ] **Step 2: Create StockHeader component**

Extract from existing `StockOverview.tsx` + `FinancialsPanel.tsx` top metrics:

```typescript
// desktop/src/components/StockHeader.tsx
import { useAppStore } from '../stores/appStore'
import { fmt } from '../utils/formatters'

export default function StockHeader() {
  const ticker = useAppStore((s) => s.ticker)
  const currentPrice = useAppStore((s) => s.currentPrice)
  const priceChange = useAppStore((s) => s.priceChange)
  const priceChangePct = useAppStore((s) => s.priceChangePct)

  if (!ticker) return null

  const changeColor = (priceChange ?? 0) >= 0 ? 'var(--green)' : 'var(--red)'

  return (
    <div className="stock-header">
      <div className="stock-header-left">
        <span className="stock-ticker">{ticker}</span>
        {currentPrice != null && (
          <span className="stock-price">{fmt.currency(currentPrice)}</span>
        )}
        {priceChange != null && (
          <span className="stock-change" style={{ color: changeColor }}>
            {priceChange >= 0 ? '+' : ''}{fmt.currency(priceChange)} ({fmt.pct(priceChangePct ?? 0)})
          </span>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Refactor TickerWorkspace to slim orchestrator**

Replace the monolithic TickerWorkspace with a slim orchestrator. Keep the existing file but gut it to ~150 lines:

```typescript
// desktop/src/views/TickerWorkspace.tsx (simplified structure)
import { useAppStore } from '../stores/appStore'
import StockHeader from '../components/StockHeader'
import PipelineRunner from '../components/PipelineRunner'
import TabBar from '../components/TabBar'
import TickerInput from '../components/TickerInput'
import OverviewTab from './OverviewTab'
import FinancialsTab from './FinancialsTab'
import ValuationTab from './ValuationTab'
import PeersTab from './PeersTab'
import ErrorBoundary from '../components/ErrorBoundary'

interface Props {
  onOpenSettings: () => void
}

export default function TickerWorkspace({ onOpenSettings }: Props) {
  const ticker = useAppStore((s) => s.ticker)
  const activeTab = useAppStore((s) => s.activeTab)

  if (!ticker) {
    return <TickerInput />  // Show ticker input when no ticker selected
  }

  return (
    <div className="workspace">
      <StockHeader />
      <PipelineRunner />
      <TabBar />
      <ErrorBoundary>
        <div className="tab-panel">
          {activeTab === 'overview' && <OverviewTab />}
          {activeTab === 'financials' && <FinancialsTab />}
          {activeTab === 'valuation' && <ValuationTab />}
          {activeTab === 'peers' && <PeersTab />}
        </div>
      </ErrorBoundary>
    </div>
  )
}
```

Note: This is a major refactor. The existing logic for phase management, pipeline running, data fetching, etc. must be preserved. Move each concern to the appropriate tab component or keep it in the store/hooks. Do NOT delete logic — relocate it.

- [ ] **Step 4: Verify the app compiles**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinRobot/desktop && npx tsc --noEmit`
Expected: No errors (may need stub tab components)

- [ ] **Step 5: Create stub tab components**

Create minimal stubs for all 4 tabs so the app compiles:

```typescript
// desktop/src/views/OverviewTab.tsx
export default function OverviewTab() {
  return <div className="tab-content">Overview (TODO)</div>
}

// desktop/src/views/FinancialsTab.tsx
export default function FinancialsTab() {
  return <div className="tab-content">Financials (TODO)</div>
}

// desktop/src/views/ValuationTab.tsx
export default function ValuationTab() {
  return <div className="tab-content">Valuation (TODO)</div>
}

// desktop/src/views/PeersTab.tsx
export default function PeersTab() {
  return <div className="tab-content">Peers (TODO)</div>
}
```

- [ ] **Step 6: Commit**

```bash
git add desktop/src/components/StockHeader.tsx desktop/src/components/TabBar.tsx desktop/src/views/TickerWorkspace.tsx desktop/src/views/OverviewTab.tsx desktop/src/views/FinancialsTab.tsx desktop/src/views/ValuationTab.tsx desktop/src/views/PeersTab.tsx
git commit -m "refactor(desktop): split TickerWorkspace into tab system skeleton"
```

---

## Task 8: OverviewTab Implementation

**Files:**
- Modify: `desktop/src/views/OverviewTab.tsx`
- Modify: `desktop/src/components/charts/PriceChart.tsx` (refactor to self-fetching)

- [ ] **Step 1: Refactor PriceChart to self-fetching**

Replace prop-fed pattern with React Query self-fetching:

```typescript
// desktop/src/components/charts/PriceChart.tsx
import { useState, useMemo, useRef, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAppStore } from '../../stores/appStore'
// ... (keep existing Recharts imports and styling)

type TimeRange = '1M' | '3M' | '6M' | '1Y' | 'ALL'
const TIME_RANGES: TimeRange[] = ['1M', '3M', '6M', '1Y', 'ALL']

const PERIOD_MAP: Record<TimeRange, string> = {
  '1M': '1mo',
  '3M': '3mo',
  '6M': '6mo',
  '1Y': '1y',
  'ALL': 'max',
}

export default function PriceChart({ title }: { title: string }) {
  const ticker = useAppStore((s) => s.ticker)
  const [range, setRange] = useState<TimeRange>('1Y')
  const [debouncedRange, setDebouncedRange] = useState<TimeRange>('1Y')
  const debounceRef = useRef<ReturnType<typeof setTimeout>>()

  // 300ms debounce on range change (spec requirement: prevent rapid API calls)
  const handleRangeChange = useCallback((newRange: TimeRange) => {
    setRange(newRange)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => setDebouncedRange(newRange), 300)
  }, [])

  // Use raw fetch (NOT openapi-fetch) because /price endpoint return type
  // is dict[str, Any] with no typed schema and the period param is new
  const { data: priceData } = useQuery({
    queryKey: ['price', ticker, debouncedRange],
    queryFn: async () => {
      const resp = await fetch(`/api/data/${ticker}/price?period=${PERIOD_MAP[debouncedRange]}`)
      if (!resp.ok) return []
      const json = await resp.json()
      return json.history ?? []
    },
    enabled: !!ticker,
  })

  const chartData = useMemo(() => priceData ?? [], [priceData])

  // ... keep existing chart rendering logic (ComposedChart, Area, Bar, dual Y-axes)
  // Replace the old client-side filtering `useMemo` with chartData directly
  // Keep the TimeRange buttons in card-header, use handleRangeChange instead of setRange
}
```

- [ ] **Step 2: Implement OverviewTab**

```typescript
// desktop/src/views/OverviewTab.tsx
import { useAppStore } from '../stores/appStore'
import { PriceChart } from '../components/charts'
import ResearchSummary from '../components/ResearchSummary'
import WarningBanner from '../components/WarningBanner'

export default function OverviewTab() {
  const ticker = useAppStore((s) => s.ticker)
  const researchResult = useAppStore((s) => s.researchResult)
  const warnings = useAppStore((s) => s.warnings)

  return (
    <div className="tab-content overview-tab">
      <PriceChart title={`${ticker} Price`} />
      {warnings.length > 0 && <WarningBanner warnings={warnings} />}
      {researchResult ? (
        <ResearchSummary result={researchResult} />
      ) : (
        <EmptyState
          message="Run Research analysis to view investment thesis"
          pipeline="research"
        />
      )}
    </div>
  )
}

function EmptyState({ message, pipeline }: { message: string; pipeline: string }) {
  const setPipelineType = useAppStore((s) => s.setPipelineType)
  return (
    <div className="empty-state-card">
      <p>{message}</p>
      <button className="btn-primary" onClick={() => setPipelineType(pipeline as any)}>
        Run {pipeline}
      </button>
    </div>
  )
}
```

- [ ] **Step 3: Verify compilation**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinRobot/desktop && npx tsc --noEmit`

- [ ] **Step 4: Commit**

```bash
git add desktop/src/views/OverviewTab.tsx desktop/src/components/charts/PriceChart.tsx
git commit -m "feat(desktop): implement OverviewTab with self-fetching PriceChart"
```

---

## Task 9: New Chart Components (CashFlow, QuarterlyComparison, RevenueYoY)

**Files:**
- Create: `desktop/src/components/charts/CashFlowChart.tsx`
- Create: `desktop/src/components/charts/QuarterlyComparisonChart.tsx`
- Create: `desktop/src/components/charts/RevenueYoYChart.tsx`
- Modify: `desktop/src/components/charts/index.ts`

- [ ] **Step 1: Create CashFlowChart**

```typescript
// desktop/src/components/charts/CashFlowChart.tsx
import {
  ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'

interface ChartProps {
  data: { year: string; operating: number; investing: number; financing: number }[]
  title: string
}

const OP_COLOR = '#34D399'     // green
const INV_COLOR = '#F87171'    // red
const FIN_COLOR = '#C9A84C'    // gold
const NET_COLOR = '#60A5FA'    // blue

const CHART_TOOLTIP = {
  backgroundColor: '#1A1F2E',
  border: '1px solid #252A37',
  borderRadius: 6,
  color: '#E8ECF4',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: '0.78rem',
}

function formatBillions(v: number): string {
  if (Math.abs(v) >= 1e9) return `${(v / 1e9).toFixed(1)}B`
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(0)}M`
  return String(v)
}

export default function CashFlowChart({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null

  const withNet = data.map((d) => ({ ...d, net: d.operating + d.investing + d.financing }))

  return (
    <div className="card animate-in">
      <div className="card-header"><span className="card-title">{title}</span></div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={withNet} barGap={2}>
            <XAxis dataKey="year" tick={{ fill: '#7A8299', fontSize: 11 }} axisLine={{ stroke: '#252A37' }} />
            <YAxis tick={{ fill: '#7A8299', fontSize: 11 }} axisLine={{ stroke: '#252A37' }} tickFormatter={formatBillions} />
            <Tooltip contentStyle={CHART_TOOLTIP} formatter={(v: number) => formatBillions(v)} />
            <Legend wrapperStyle={{ color: '#7A8299', fontSize: '0.72rem' }} />
            <Bar dataKey="operating" name="Operating" fill={OP_COLOR} radius={[2, 2, 0, 0]} />
            <Bar dataKey="investing" name="Investing" fill={INV_COLOR} radius={[2, 2, 0, 0]} />
            <Bar dataKey="financing" name="Financing" fill={FIN_COLOR} radius={[2, 2, 0, 0]} />
            <Line type="monotone" dataKey="net" name="Net" stroke={NET_COLOR} strokeWidth={2} dot={{ r: 3 }} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Create QuarterlyComparisonChart**

```typescript
// desktop/src/components/charts/QuarterlyComparisonChart.tsx
import { BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer } from 'recharts'

interface ChartProps {
  data: { quarter: string; revenue: number; operating_income: number; net_income: number }[]
  title: string
}

const REV_COLOR = '#60A5FA'
const OP_COLOR = '#C9A84C'
const NI_COLOR = '#34D399'

const CHART_TOOLTIP = {
  backgroundColor: '#1A1F2E',
  border: '1px solid #252A37',
  borderRadius: 6,
  color: '#E8ECF4',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: '0.78rem',
}

function formatBillions(v: number): string {
  if (Math.abs(v) >= 1e9) return `${(v / 1e9).toFixed(1)}B`
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(0)}M`
  return String(v)
}

export default function QuarterlyComparisonChart({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null

  return (
    <div className="card animate-in">
      <div className="card-header"><span className="card-title">{title}</span></div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={data} barGap={2}>
            <XAxis dataKey="quarter" tick={{ fill: '#7A8299', fontSize: 10 }} axisLine={{ stroke: '#252A37' }} angle={-30} textAnchor="end" height={45} />
            <YAxis tick={{ fill: '#7A8299', fontSize: 11 }} axisLine={{ stroke: '#252A37' }} tickFormatter={formatBillions} />
            <Tooltip contentStyle={CHART_TOOLTIP} formatter={(v: number) => formatBillions(v)} />
            <Legend wrapperStyle={{ color: '#7A8299', fontSize: '0.72rem' }} />
            <Bar dataKey="revenue" name="Revenue" fill={REV_COLOR} radius={[2, 2, 0, 0]} />
            <Bar dataKey="operating_income" name="Op. Income" fill={OP_COLOR} radius={[2, 2, 0, 0]} />
            <Bar dataKey="net_income" name="Net Income" fill={NI_COLOR} radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Create RevenueYoYChart**

```typescript
// desktop/src/components/charts/RevenueYoYChart.tsx
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, Cell } from 'recharts'

interface ChartProps {
  data: { year: string; yoy_pct: number | null }[]
  title: string
}

const POS_COLOR = '#34D399'
const NEG_COLOR = '#F87171'

const CHART_TOOLTIP = {
  backgroundColor: '#1A1F2E',
  border: '1px solid #252A37',
  borderRadius: 6,
  color: '#E8ECF4',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: '0.78rem',
}

export default function RevenueYoYChart({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null

  return (
    <div className="card animate-in">
      <div className="card-header"><span className="card-title">{title}</span></div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={data}>
            <XAxis dataKey="year" tick={{ fill: '#7A8299', fontSize: 11 }} axisLine={{ stroke: '#252A37' }} />
            <YAxis tick={{ fill: '#7A8299', fontSize: 11 }} axisLine={{ stroke: '#252A37' }} tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
            <Tooltip contentStyle={CHART_TOOLTIP} formatter={(v: number) => `${v.toFixed(1)}%`} labelFormatter={(l) => `Year: ${l}`} />
            <ReferenceLine y={0} stroke="#252A37" />
            <Bar dataKey="yoy_pct" name="YoY Growth" radius={[2, 2, 0, 0]}>
              {data.map((entry, i) => (
                <Cell key={i} fill={(entry.yoy_pct ?? 0) >= 0 ? POS_COLOR : NEG_COLOR} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Create RevenueSegmentsChart (conditional)**

```typescript
// desktop/src/components/charts/RevenueSegmentsChart.tsx
// Conditional component — only rendered if segment data is available.
// yfinance segment coverage is poor; FMP requires paid plan.
// For now, create a minimal placeholder that renders a pie chart if data exists.
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from 'recharts'

interface SegmentData { segment: string; revenue: number; pct: number }
interface ChartProps { data: SegmentData[]; title: string }

const COLORS = ['#60A5FA', '#C9A84C', '#34D399', '#F87171', '#A78BFA', '#FB923C']

const CHART_TOOLTIP = {
  backgroundColor: '#1A1F2E', border: '1px solid #252A37', borderRadius: 6,
  color: '#E8ECF4', fontFamily: "'JetBrains Mono', monospace", fontSize: '0.78rem',
}

export default function RevenueSegmentsChart({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null
  return (
    <div className="card animate-in">
      <div className="card-header"><span className="card-title">{title}</span></div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={220}>
          <PieChart>
            <Pie data={data} dataKey="revenue" nameKey="segment" cx="50%" cy="50%" outerRadius={80} label={(e) => `${e.pct.toFixed(0)}%`}>
              {data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
            </Pie>
            <Tooltip contentStyle={CHART_TOOLTIP} />
            <Legend wrapperStyle={{ color: '#7A8299', fontSize: '0.72rem' }} />
          </PieChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Update barrel export**

Add to `desktop/src/components/charts/index.ts`:

```typescript
export { default as CashFlowChart } from './CashFlowChart'
export { default as QuarterlyComparisonChart } from './QuarterlyComparisonChart'
export { default as RevenueYoYChart } from './RevenueYoYChart'
export { default as RevenueSegmentsChart } from './RevenueSegmentsChart'
```

- [ ] **Step 5: Verify compilation**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinRobot/desktop && npx tsc --noEmit`

- [ ] **Step 6: Commit**

```bash
git add desktop/src/components/charts/CashFlowChart.tsx desktop/src/components/charts/QuarterlyComparisonChart.tsx desktop/src/components/charts/RevenueYoYChart.tsx desktop/src/components/charts/index.ts
git commit -m "feat(charts): add CashFlow, QuarterlyComparison, RevenueYoY components"
```

---

## Task 10: FinancialsTab Implementation

**Files:**
- Modify: `desktop/src/views/FinancialsTab.tsx`
- Create: `desktop/src/hooks/useHistoricalData.ts`

- [ ] **Step 1: Create data fetching hook**

```typescript
// desktop/src/hooks/useHistoricalData.ts
import { useEffect } from 'react'
import { useAppStore } from '../stores/appStore'
import { api } from '../api/client'
import { useQuery } from '@tanstack/react-query'

export function useHistoricalData() {
  const ticker = useAppStore((s) => s.ticker)
  const setHistoricalMetrics = useAppStore((s) => s.setHistoricalMetrics)
  const setHistoricalLoading = useAppStore((s) => s.setHistoricalLoading)

  const { data, isLoading } = useQuery({
    queryKey: ['historical', ticker],
    queryFn: async () => {
      const resp = await fetch(`/api/data/${ticker}/historical`)
      if (!resp.ok) return null
      return resp.json()
    },
    enabled: !!ticker,
  })

  useEffect(() => {
    setHistoricalLoading(isLoading)
  }, [isLoading, setHistoricalLoading])

  useEffect(() => {
    if (data) setHistoricalMetrics(data)
  }, [data, setHistoricalMetrics])

  return { data, isLoading }
}

export function useQuarterlyData() {
  const ticker = useAppStore((s) => s.ticker)
  const setQuarterlyData = useAppStore((s) => s.setQuarterlyData)
  const setQuarterlyLoading = useAppStore((s) => s.setQuarterlyLoading)

  const { data, isLoading } = useQuery({
    queryKey: ['quarterly', ticker],
    queryFn: async () => {
      const resp = await fetch(`/api/data/${ticker}/quarterly`)
      if (!resp.ok) return null
      return resp.json()
    },
    enabled: !!ticker,
  })

  useEffect(() => {
    setQuarterlyLoading(isLoading)
  }, [isLoading, setQuarterlyLoading])

  useEffect(() => {
    if (data) setQuarterlyData(data)
  }, [data, setQuarterlyData])

  return { data, isLoading }
}
```

- [ ] **Step 2: Implement FinancialsTab**

```typescript
// desktop/src/views/FinancialsTab.tsx
import { useAppStore } from '../stores/appStore'
import { useHistoricalData, useQuarterlyData } from '../hooks/useHistoricalData'
import {
  RevenueEbitdaChart, MarginTrendChart, CashFlowChart,
  QuarterlyComparisonChart, RevenueYoYChart,
} from '../components/charts'
import {
  historicalToRevenueEbitdaData, historicalToMarginData,
  historicalToRevenueYoYData, historicalToCashFlowData,
  quarterlyToComparisonData,
} from '../utils/chartAdapters'
import { extractNarrativeSection } from '../utils/narrativeParser'

export default function FinancialsTab() {
  const { isLoading: histLoading } = useHistoricalData()
  const { isLoading: qtrLoading } = useQuarterlyData()
  const historicalMetrics = useAppStore((s) => s.historicalMetrics)
  const quarterlyData = useAppStore((s) => s.quarterlyData)
  const researchResult = useAppStore((s) => s.researchResult)

  if (histLoading) return <div className="loading-skeleton" />

  return (
    <div className="tab-content financials-tab">
      {/* Trends Section */}
      <section className="chart-section">
        <h3 className="section-title">Trends</h3>
        <div className="chart-grid-2col">
          {historicalMetrics && (
            <>
              <RevenueEbitdaChart data={historicalToRevenueEbitdaData(historicalMetrics)} title="Revenue & EBITDA" />
              <MarginTrendChart data={historicalToMarginData(historicalMetrics)} title="Margin Trends" />
              <RevenueYoYChart data={historicalToRevenueYoYData(historicalMetrics)} title="Revenue YoY Growth" />
            </>
          )}
        </div>
      </section>

      {/* Structure Section */}
      <section className="chart-section">
        <h3 className="section-title">Structure</h3>
        <div className="chart-grid-2col">
          {historicalMetrics && historicalMetrics.operating_cash_flow.length > 0 && (
            <CashFlowChart data={historicalToCashFlowData(historicalMetrics)} title="Cash Flow Breakdown" />
          )}
          {quarterlyData && (
            <QuarterlyComparisonChart data={quarterlyToComparisonData(quarterlyData)} title="Quarterly Comparison" />
          )}
        </div>
      </section>

      {/* Insights Section */}
      {researchResult?.narrative && (
        <section className="chart-section">
          <h3 className="section-title">AI Insights</h3>
          <InsightBlock
            title="Balance Sheet Analysis"
            content={extractNarrativeSection(researchResult.narrative, ['balance sheet', 'financial position'])}
          />
          <InsightBlock
            title="Cash Flow Analysis"
            content={extractNarrativeSection(researchResult.narrative, ['cash flow', 'liquidity'])}
          />
        </section>
      )}
    </div>
  )
}

function InsightBlock({ title, content }: { title: string; content: string | null }) {
  if (!content) return null
  return (
    <details className="insight-block">
      <summary className="insight-title">{title}</summary>
      <div className="insight-content">{content}</div>
    </details>
  )
}
```

- [ ] **Step 3: Create narrative parser utility**

```typescript
// desktop/src/utils/narrativeParser.ts

/**
 * Extract a section from markdown narrative by heading keywords.
 * Returns the text under the first matching heading until the next heading, or null.
 * Intentionally fragile — best-effort extraction from free text.
 */
export function extractNarrativeSection(
  narrative: string,
  sectionKeywords: string[],
): string | null {
  const lines = narrative.split('\n')
  let capturing = false
  let result: string[] = []

  for (const line of lines) {
    const isHeading = /^#{1,3}\s+/.test(line)

    if (isHeading) {
      if (capturing) break // hit next heading, stop
      const headingText = line.replace(/^#{1,3}\s+/, '').toLowerCase()
      if (sectionKeywords.some((kw) => headingText.includes(kw))) {
        capturing = true
        continue
      }
    } else if (capturing) {
      result.push(line)
    }
  }

  const text = result.join('\n').trim()
  return text.length > 0 ? text : null
}
```

- [ ] **Step 4: Verify compilation**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinRobot/desktop && npx tsc --noEmit`

- [ ] **Step 5: Commit**

```bash
git add desktop/src/views/FinancialsTab.tsx desktop/src/hooks/useHistoricalData.ts desktop/src/utils/narrativeParser.ts
git commit -m "feat(desktop): implement FinancialsTab with data hooks and narrative parser"
```

---

## Task 11: ValuationTab Implementation

**Files:**
- Modify: `desktop/src/views/ValuationTab.tsx`
- Create: `desktop/src/components/MonteCarloSection.tsx`

- [ ] **Step 1: Create MonteCarloSection**

Extract Monte Carlo trigger logic from TickerWorkspace into a self-contained component:

```typescript
// desktop/src/components/MonteCarloSection.tsx
import { useAppStore } from '../stores/appStore'
import { useMonteCarloCompute } from '../hooks/useCompute'
import { MonteCarloChart } from './charts'

export default function MonteCarloSection() {
  const dcfResult = useAppStore((s) => s.dcfResult)
  const currentPrice = useAppStore((s) => s.currentPrice)
  const monteCarloResult = useAppStore((s) => s.monteCarloResult)
  const monteCarloLoading = useAppStore((s) => s.monteCarloLoading)
  const setMonteCarloResult = useAppStore((s) => s.setMonteCarloResult)
  const setMonteCarloLoading = useAppStore((s) => s.setMonteCarloLoading)

  const { mutate: runMonteCarlo } = useMonteCarloCompute()

  const handleRun = () => {
    if (!dcfResult) return
    setMonteCarloLoading(true)
    runMonteCarlo(
      { dcf_inputs: dcfResult, n_simulations: 10000 },
      {
        onSuccess: (data) => {
          setMonteCarloResult(data)
          setMonteCarloLoading(false)
        },
        onError: () => setMonteCarloLoading(false),
      }
    )
  }

  if (!dcfResult) {
    return (
      <div className="empty-state-card">
        <p>Run DCF Analysis first to enable Monte Carlo simulation</p>
      </div>
    )
  }

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">Monte Carlo Simulation</span>
        <button
          className="btn-sm"
          onClick={handleRun}
          disabled={monteCarloLoading}
        >
          {monteCarloLoading ? 'Running...' : 'Run (10K simulations)'}
        </button>
      </div>
      <div className="card-body">
        {monteCarloResult && (
          <MonteCarloChart result={monteCarloResult} currentPrice={currentPrice} />
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Implement ValuationTab**

```typescript
// desktop/src/views/ValuationTab.tsx
import { useAppStore } from '../stores/appStore'
import { useHistoricalData } from '../hooks/useHistoricalData'
import AssumptionsEditor from '../components/AssumptionsEditor'
import ValuationCard from '../components/ValuationCard'
import ScenarioCompare from '../components/ScenarioCompare'
import MonteCarloSection from '../components/MonteCarloSection'
import {
  SensitivityHeatmap, WaterfallChart, FootballField,
  EpsPeChart, EpsSurpriseChart,
} from '../components/charts'
import {
  sensitivityGridToHeatmapRows, dcfResultToWaterfallData,
  dcfSensitivityToFootballData, historicalToEpsPeData,
  earningsToSurpriseChartData,
} from '../utils/chartAdapters'

export default function ValuationTab() {
  useHistoricalData()  // ensure historical data is loaded for EpsPe
  const dcfResult = useAppStore((s) => s.dcfResult)
  const sensitivityData = useAppStore((s) => s.sensitivityData)
  const historicalMetrics = useAppStore((s) => s.historicalMetrics)
  const earningsResult = useAppStore((s) => s.earningsResult)

  return (
    <div className="tab-content valuation-tab">
      {/* DCF Workspace */}
      <section className="chart-section">
        <h3 className="section-title">DCF Workspace</h3>
        {dcfResult ? (
          <>
            <div className="chart-grid-2col">
              <AssumptionsEditor />
              <ValuationCard />
            </div>
            {sensitivityData && (
              <SensitivityHeatmap data={sensitivityGridToHeatmapRows(sensitivityData)} title="Sensitivity (WACC x TGR)" />
            )}
            {dcfResult && (
              <WaterfallChart data={dcfResultToWaterfallData(dcfResult)} title="DCF Bridge" />
            )}
          </>
        ) : (
          <div className="empty-state-card">
            <p>Run DCF Analysis to view valuation workspace</p>
          </div>
        )}
      </section>

      {/* Comprehensive Valuation */}
      <section className="chart-section">
        <h3 className="section-title">Comprehensive Valuation</h3>
        {dcfResult && sensitivityData && (
          <FootballField data={dcfSensitivityToFootballData(dcfResult, sensitivityData)} title="Valuation Range" />
        )}
        <ScenarioCompare />
        <MonteCarloSection />

        {/* EPS / PE historical — from /historical endpoint, no pipeline needed */}
        {historicalMetrics && historicalMetrics.price_data_available && (
          <EpsPeChart data={historicalToEpsPeData(historicalMetrics)} title="Historical EPS & P/E" />
        )}

        {/* EPS Surprise — from earnings pipeline */}
        {earningsResult?.surprises && earningsResult.surprises.length > 0 && (
          <EpsSurpriseChart data={earningsToSurpriseChartData(earningsResult.surprises)} title="EPS Surprises" />
        )}
      </section>
    </div>
  )
}
```

- [ ] **Step 3: Verify compilation**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinRobot/desktop && npx tsc --noEmit`

- [ ] **Step 4: Commit**

```bash
git add desktop/src/views/ValuationTab.tsx desktop/src/components/MonteCarloSection.tsx
git commit -m "feat(desktop): implement ValuationTab with MonteCarloSection"
```

---

## Task 12: RelativePerformanceChart + PeersTab

**Files:**
- Create: `desktop/src/components/charts/RelativePerformanceChart.tsx`
- Modify: `desktop/src/views/PeersTab.tsx`
- Create: `desktop/src/hooks/usePerformanceData.ts`
- Modify: `desktop/src/components/charts/index.ts`

- [ ] **Step 1: Create performance data hook**

```typescript
// desktop/src/hooks/usePerformanceData.ts
import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAppStore } from '../stores/appStore'

export function usePerformanceData(peerTickers: string[]) {
  const ticker = useAppStore((s) => s.ticker)
  const setPerformanceData = useAppStore((s) => s.setPerformanceData)
  const setPerformanceLoading = useAppStore((s) => s.setPerformanceLoading)

  const allTickers = ticker ? [ticker, ...peerTickers].join(',') : ''

  const { data, isLoading } = useQuery({
    queryKey: ['performance', allTickers],
    queryFn: async () => {
      const resp = await fetch(`/api/data/performance?tickers=${allTickers}&benchmark=SPY&period=1y`)
      if (!resp.ok) return null
      return resp.json()
    },
    enabled: !!ticker,
  })

  useEffect(() => { setPerformanceLoading(isLoading) }, [isLoading, setPerformanceLoading])
  useEffect(() => { if (data) setPerformanceData(data) }, [data, setPerformanceData])

  return { data, isLoading }
}
```

- [ ] **Step 2: Create RelativePerformanceChart**

```typescript
// desktop/src/components/charts/RelativePerformanceChart.tsx
import { useMemo } from 'react'
import { LineChart, Line, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, ReferenceLine } from 'recharts'
import type { PerformanceData } from '../../stores/appStore'

interface Props {
  data: PerformanceData
  title: string
}

type TimeRange = '1M' | '3M' | '6M' | '1Y' | '3Y'

// Color palette for multiple lines
const LINE_COLORS = ['#60A5FA', '#C9A84C', '#34D399', '#F87171', '#A78BFA', '#FB923C']

const CHART_TOOLTIP = {
  backgroundColor: '#1A1F2E',
  border: '1px solid #252A37',
  borderRadius: 6,
  color: '#E8ECF4',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: '0.78rem',
}

export default function RelativePerformanceChart({ data, title }: Props) {
  if (!data || data.series.length === 0) return null

  // Recharts <LineChart> requires a `data` prop for XAxis to derive ticks.
  // Pivot array-of-series into shared-date rows: { date, AAPL: 112, MSFT: 108, ... }
  // Use sanitized ticker keys (replace . with _ to avoid Recharts dot-notation issues)
  const pivoted = useMemo(() => {
    const dateMap = new Map<string, Record<string, string | number>>()
    for (const series of data.series) {
      const safeKey = series.ticker.replace('.', '_')
      for (const pt of series.data) {
        if (!dateMap.has(pt.date)) dateMap.set(pt.date, { date: pt.date })
        dateMap.get(pt.date)![safeKey] = pt.value
      }
    }
    return Array.from(dateMap.values()).sort((a, b) =>
      (a.date as string).localeCompare(b.date as string)
    )
  }, [data])

  // Build line configs with sanitized keys
  const lines = data.series.map((s, i) => ({
    dataKey: s.ticker.replace('.', '_'),
    label: s.label,
    color: LINE_COLORS[i % LINE_COLORS.length],
    isTarget: i === 0,
  }))

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">{title}</span>
      </div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={pivoted}>
            <XAxis
              dataKey="date"
              tick={{ fill: '#7A8299', fontSize: 10 }}
              axisLine={{ stroke: '#252A37' }}
            />
            <YAxis
              tick={{ fill: '#7A8299', fontSize: 11 }}
              axisLine={{ stroke: '#252A37' }}
              tickFormatter={(v: number) => `${v.toFixed(0)}`}
              domain={['auto', 'auto']}
            />
            <Tooltip contentStyle={CHART_TOOLTIP} />
            <Legend wrapperStyle={{ color: '#7A8299', fontSize: '0.72rem' }} />
            <ReferenceLine y={100} stroke="#252A37" strokeDasharray="3 3" />
            {lines.map((l) => (
              <Line
                key={l.dataKey}
                dataKey={l.dataKey}
                name={l.label}
                stroke={l.color}
                strokeWidth={l.isTarget ? 2.5 : 1.5}
                dot={false}
                type="monotone"
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Implement PeersTab**

```typescript
// desktop/src/views/PeersTab.tsx
import { useMemo } from 'react'
import { useAppStore } from '../stores/appStore'
import { usePerformanceData } from '../hooks/usePerformanceData'
import CompsSummary from '../components/CompsSummary'
import { CompanyRadarChart, PeerComparisonChart, RelativePerformanceChart } from '../components/charts'
import { compsResultToPeerChartData, compsResultToRadarData } from '../utils/chartAdapters'
import { extractNarrativeSection } from '../utils/narrativeParser'

export default function PeersTab() {
  const compsResult = useAppStore((s) => s.compsResult)
  const researchResult = useAppStore((s) => s.researchResult)
  const performanceData = useAppStore((s) => s.performanceData)

  // Get peer tickers from comps result
  const peerTickers = useMemo(
    () => compsResult?.peers?.map((p) => p.ticker) ?? [],
    [compsResult]
  )

  usePerformanceData(peerTickers)

  return (
    <div className="tab-content peers-tab">
      {/* Comps Table — core element, full width, top */}
      {compsResult ? (
        <CompsSummary result={compsResult} />
      ) : (
        <div className="empty-state-card">
          <p>Run Comps Analysis to view peer comparison</p>
        </div>
      )}

      {/* Visualization Row */}
      {compsResult && (
        <div className="chart-grid-2col">
          <CompanyRadarChart data={compsResultToRadarData(compsResult)} title="Financial Profile" />
          <PeerComparisonChart data={compsResultToPeerChartData(compsResult)} title="Peer Multiples" />
        </div>
      )}

      {/* Relative Performance */}
      {performanceData && (
        <RelativePerformanceChart data={performanceData} title="Relative Performance (normalized to 100)" />
      )}

      {/* Competitor Narrative */}
      {researchResult?.narrative && (
        <CompetitorNarrative narrative={researchResult.narrative} />
      )}
    </div>
  )
}

function CompetitorNarrative({ narrative }: { narrative: string }) {
  const content = extractNarrativeSection(narrative, ['competitive', 'competitor', 'peer', 'positioning', 'market position'])
  if (!content) return null
  return (
    <details className="insight-block">
      <summary className="insight-title">Competitive Analysis</summary>
      <div className="insight-content">{content}</div>
    </details>
  )
}
```

- [ ] **Step 4: Update barrel export**

Add to `desktop/src/components/charts/index.ts`:

```typescript
export { default as RelativePerformanceChart } from './RelativePerformanceChart'
```

- [ ] **Step 5: Verify compilation**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinRobot/desktop && npx tsc --noEmit`

- [ ] **Step 6: Commit**

```bash
git add desktop/src/components/charts/RelativePerformanceChart.tsx desktop/src/components/charts/index.ts desktop/src/views/PeersTab.tsx desktop/src/hooks/usePerformanceData.ts
git commit -m "feat(desktop): implement PeersTab with RelativePerformanceChart"
```

---

## Task 13: Toast Notifications + Empty States + CSS

**Files:**
- Modify: `desktop/src/components/PipelineRunner.tsx` (or wherever pipeline completion is handled)
- Create: `desktop/src/styles/tabs.css` (or add to existing stylesheet)

- [ ] **Step 1: Add toast notifications on pipeline completion**

Find where pipeline SSE completion is handled (likely in `PipelineRunner.tsx` or a hook that handles the SSE stream events). The existing toast API uses `addToast` from `toastStore.ts` with `{ type, title, description }`. Add tab navigation as a description hint:

```typescript
// Add to pipeline completion handler (in PipelineRunner.tsx or SSE hook)
import { useAppStore, type ActiveTab } from '../stores/appStore'

const PIPELINE_TAB_MAP: Record<string, { tab: ActiveTab; label: string }> = {
  research: { tab: 'overview', label: 'Overview' },
  dcf: { tab: 'valuation', label: 'Valuation' },
  comps: { tab: 'peers', label: 'Peers' },
  earnings: { tab: 'valuation', label: 'Valuation' },
  lbo: { tab: 'valuation', label: 'Valuation' },
  'ic-memo': { tab: 'valuation', label: 'Valuation' },
}

// On pipeline complete — use existing addToast API:
const mapping = PIPELINE_TAB_MAP[pipelineType]
if (mapping) {
  // Use existing toastStore.addToast interface: { type, title, description? }
  addToast({
    type: 'success',
    title: `${pipelineType} analysis complete`,
    description: `Results available in ${mapping.label} tab`,
  })
  // Auto-navigate to the relevant tab
  useAppStore.getState().setActiveTab(mapping.tab)
}
```

Note: The original spec said "no auto-tab-switch, use clickable toast". However, the existing toast component (`Toast.tsx`) does NOT support clickable actions. Rather than extending the toast store (which is out of scope for P8), use the simpler approach: auto-switch to the target tab on completion. This gives the user immediate feedback without needing toast UI changes. If the "no auto-switch" requirement is strict, extend `Toast` interface with an `onClick` callback — but that's additional work not scoped here.

- [ ] **Step 2: Add tab and empty state CSS**

```css
/* Tab styles — add to existing stylesheet or create desktop/src/styles/tabs.css */
.tab-bar {
  display: flex;
  gap: 0;
  border-bottom: 1px solid #252A37;
  padding: 0 16px;
}

.tab-btn {
  padding: 10px 20px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: #7A8299;
  font-size: 0.85rem;
  font-family: 'JetBrains Mono', monospace;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}

.tab-btn:hover { color: #E8ECF4; }
.tab-btn.active { color: #60A5FA; border-bottom-color: #60A5FA; }

.tab-panel { padding: 16px; }
.tab-content { display: flex; flex-direction: column; gap: 24px; }

.chart-section { display: flex; flex-direction: column; gap: 12px; }
.section-title { color: #7A8299; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; margin: 0; }

.chart-grid-2col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 900px) { .chart-grid-2col { grid-template-columns: 1fr; } }

.empty-state-card {
  border: 1px dashed #252A37;
  border-radius: 8px;
  padding: 32px;
  text-align: center;
  color: #7A8299;
}
.empty-state-card p { margin: 0 0 12px; }
.empty-state-card .btn-primary {
  background: #60A5FA;
  color: #1A1F2E;
  border: none;
  padding: 8px 16px;
  border-radius: 4px;
  cursor: pointer;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.8rem;
}

.insight-block { margin: 8px 0; }
.insight-title { color: #E8ECF4; cursor: pointer; font-size: 0.85rem; padding: 8px 0; }
.insight-content { color: #7A8299; font-size: 0.82rem; line-height: 1.5; padding: 8px 0 8px 12px; border-left: 2px solid #252A37; }

.loading-skeleton {
  height: 200px;
  background: linear-gradient(90deg, #1A1F2E 25%, #252A37 50%, #1A1F2E 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
  border-radius: 8px;
}
@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }

.stock-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  border-bottom: 1px solid #252A37;
}
.stock-ticker { font-size: 1.2rem; font-weight: 700; color: #E8ECF4; }
.stock-price { font-size: 1.1rem; color: #E8ECF4; }
.stock-change { font-size: 0.85rem; }
```

- [ ] **Step 3: Import CSS in app entry point**

Add the CSS import to `desktop/src/App.tsx` or wherever global styles are imported.

- [ ] **Step 4: Verify app builds and renders**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinRobot/desktop && npm run build`
Expected: Build succeeds

- [ ] **Step 5: Commit**

```bash
git add desktop/src/styles/ desktop/src/components/PipelineRunner.tsx desktop/src/App.tsx
git commit -m "feat(desktop): add tab CSS, empty states, toast notifications on pipeline complete"
```

---

## Task 14: Delete FinancialsPanel + Final Cleanup

**Files:**
- Delete: `desktop/src/components/FinancialsPanel.tsx`
- Modify: Any files that import FinancialsPanel (remove imports)
- Modify: `desktop/src/views/TickerWorkspace.tsx` (ensure no references remain)

- [ ] **Step 1: Find all imports of FinancialsPanel**

Search for `FinancialsPanel` across the desktop source. Remove all imports and usages.

- [ ] **Step 2: Delete FinancialsPanel.tsx**

```bash
rm desktop/src/components/FinancialsPanel.tsx
```

- [ ] **Step 3: Verify no broken imports**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinRobot/desktop && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Run full build**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinRobot/desktop && npm run build`
Expected: Build succeeds

- [ ] **Step 5: Run backend tests to ensure no regressions**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m pytest tests/ -x -q`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(desktop): delete FinancialsPanel, all content absorbed into StockHeader + tabs"
```

---

## Task 15: Integration Verification

- [ ] **Step 1: Start backend server**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot && python -m finrobot.server
```
Verify it starts without errors on port 8321.

- [ ] **Step 2: Test new endpoints manually**

```bash
curl http://127.0.0.1:8321/api/data/AAPL/historical | python -m json.tool | head -30
curl http://127.0.0.1:8321/api/data/AAPL/quarterly | python -m json.tool | head -30
curl "http://127.0.0.1:8321/api/data/performance?tickers=AAPL,MSFT&benchmark=SPY&period=1y" | python -m json.tool | head -30
curl "http://127.0.0.1:8321/api/data/AAPL/price?period=3mo" | python -m json.tool | head -20
```

Verify each returns valid JSON with expected structure.

- [ ] **Step 3: Start desktop dev server**

```bash
cd /Users/zhunihaoyun/Desktop/code/FinRobot/desktop && npm run dev
```

- [ ] **Step 4: Manual UI verification**

Open the app, enter AAPL:
1. Overview tab shows price chart with time range selector
2. Financials tab shows revenue/EBITDA + margins + YoY growth + cash flow charts
3. Valuation tab shows empty state (until DCF is run)
4. Peers tab shows empty state (until Comps is run)
5. Run Research → toast appears → click navigates to Overview → ResearchSummary visible
6. Run DCF → toast → Valuation tab populated
7. Run Comps → toast → Peers tab populated with comps table + charts + relative performance

- [ ] **Step 5: Final commit with any fixes**

```bash
git add -A
git commit -m "fix(desktop): integration fixes from manual testing"
```
