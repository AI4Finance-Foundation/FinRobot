# P2a — Data Source Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add FMP, Finnhub, and SEC EDGAR data providers with chain fallback, fix the FCF formula with D&A data, and wire everything into the existing engine.

**Architecture:** Each new provider implements the existing `DataProvider` ABC (`interface.py:31-43`), normalizes API-specific keys internally, and returns `DataResult`. The `DataLayer` fallback loop is upgraded from "primary + 1 fallback" to "iterate all providers in priority order." `DCFInputs` gains `da_pct_revenue` so the FCF formula can use standard EBIT(1-T)+D&A when D&A data is available.

**Tech Stack:** httpx (async HTTP), pydantic/pydantic-settings, aiosqlite (cache), pytest + pytest-asyncio (tests)

**Spec:** `specs/P2a.md`

---

## File Map

| # | File | Action | Responsibility |
|---|------|--------|----------------|
| 1 | `finrobot/engine/models/financial.py` | Modify | Add D&A fields to FinancialData, DCFInputs, DCFResult |
| 2 | `finrobot/engine/compute/dcf.py` | Modify | Standard FCF formula when `da_pct_revenue` is set |
| 3 | `finrobot/config.py` | Modify | Add `fmp_api_key`, `finnhub_api_key`, `sec_user_agent` |
| 4 | `finrobot/engine/data/providers/fmp_provider.py` | Create | FMP API client with key normalization |
| 5 | `finrobot/engine/data/providers/finnhub_provider.py` | Create | Finnhub API client with key normalization |
| 6 | `finrobot/engine/data/providers/sec_provider.py` | Create | SEC EDGAR client (filings/MD&A) |
| 7 | `finrobot/engine/data/layer.py` | Modify | Chain fallback (iterate all providers) |
| 8 | `finrobot/engine/compute/extractor.py` | Modify | Extract D&A fields from normalized dict |
| 9 | `finrobot/cli.py` | Modify | Wire new providers into `_build_deps()` |
| 10 | `finrobot/server.py` | Modify | Wire new providers into `lifespan()` |
| 11 | `.env.example` | Modify | Document new env vars |

---

## Task 1: Models — add D&A fields

**Files:**
- Modify: `finrobot/engine/models/financial.py:8-46` (FinancialData), `:113-153` (DCFInputs), `:155-182` (DCFResult)
- Test: `tests/unit/test_financial_models.py`

- [ ] **Step 1: Write failing tests for new model fields**

Add to `tests/unit/test_financial_models.py`:

```python
# --- P2a: D&A fields ---

def test_financial_data_da_fields_default_none():
    """New D&A fields are Optional and default to None."""
    fd = FinancialData(
        ticker="AAPL", timestamp=datetime.now(tz=timezone.utc),
        revenue=100e9, ebitda=35e9, net_income=20e9,
        gross_margin=0.43, operating_margin=0.30,
        market_cap=2.5e12, shares_outstanding=15e9, current_price=170.0,
    )
    assert fd.depreciation_amortization is None
    assert fd.rd_expense is None
    assert fd.sga_expense is None
    assert fd.interest_expense is None


def test_financial_data_da_fields_set():
    fd = FinancialData(
        ticker="AAPL", timestamp=datetime.now(tz=timezone.utc),
        revenue=100e9, ebitda=35e9, net_income=20e9,
        gross_margin=0.43, operating_margin=0.30,
        market_cap=2.5e12, shares_outstanding=15e9, current_price=170.0,
        depreciation_amortization=11e9, rd_expense=22e9,
        sga_expense=18e9, interest_expense=3e9,
    )
    assert fd.depreciation_amortization == 11e9
    assert fd.rd_expense == 22e9


def test_dcf_inputs_da_pct_revenue_default_none():
    """da_pct_revenue defaults to None (P1.5 simplified formula)."""
    inputs = DCFInputs(
        revenue_base=100e9, revenue_growth_rates=[0.05],
        ebitda_margin=0.35, capex_pct_revenue=0.05,
        nwc_pct_revenue=0.02, risk_free_rate=0.04,
        beta=1.2, equity_risk_premium=0.05, cost_of_debt=0.04,
        debt_ratio=0.1, terminal_growth_rate=0.025,
        shares_outstanding=1e9, net_debt=10e9,
    )
    assert inputs.da_pct_revenue is None


def test_dcf_inputs_da_pct_revenue_set():
    inputs = DCFInputs(
        revenue_base=100e9, revenue_growth_rates=[0.05],
        ebitda_margin=0.35, capex_pct_revenue=0.05,
        nwc_pct_revenue=0.02, risk_free_rate=0.04,
        beta=1.2, equity_risk_premium=0.05, cost_of_debt=0.04,
        debt_ratio=0.1, terminal_growth_rate=0.025,
        shares_outstanding=1e9, net_debt=10e9,
        da_pct_revenue=0.10,
    )
    assert inputs.da_pct_revenue == 0.10


def test_dcf_inputs_da_pct_revenue_validation():
    """da_pct_revenue must be 0-0.5 when set."""
    with pytest.raises(ValidationError):
        DCFInputs(
            revenue_base=100e9, revenue_growth_rates=[0.05],
            ebitda_margin=0.35, capex_pct_revenue=0.05,
            nwc_pct_revenue=0.02, risk_free_rate=0.04,
            beta=1.2, equity_risk_premium=0.05, cost_of_debt=0.04,
            debt_ratio=0.1, terminal_growth_rate=0.025,
            shares_outstanding=1e9, net_debt=10e9,
            da_pct_revenue=0.8,  # > 0.5 → invalid
        )


def test_dcf_result_fcf_formula_default():
    """fcf_formula defaults to 'simplified'."""
    # Use a minimal DCFResult — we just care about the new field
    inputs = DCFInputs(
        revenue_base=100e9, revenue_growth_rates=[0.05],
        ebitda_margin=0.35, capex_pct_revenue=0.05,
        nwc_pct_revenue=0.02, risk_free_rate=0.04,
        beta=1.2, equity_risk_premium=0.05, cost_of_debt=0.04,
        debt_ratio=0.1, terminal_growth_rate=0.025,
        shares_outstanding=1e9, net_debt=10e9,
    )
    result = DCFResult(
        cost_of_equity=0.10, wacc=0.10, projection_years=1,
        projected_revenue=[105e9], projected_ebitda=[36.75e9],
        projected_fcf=[21.68e9], terminal_value=300e9,
        pv_terminal=272e9, pv_fcf_total=19.7e9,
        enterprise_value=291.7e9, equity_value=281.7e9,
        implied_price=281.7, inputs=inputs,
    )
    assert result.fcf_formula == "simplified"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_financial_models.py -v -k "da_pct or da_fields or fcf_formula"`
Expected: FAIL — attributes do not exist

- [ ] **Step 3: Add fields to models**

In `finrobot/engine/models/financial.py`:

Add to `FinancialData` (after `price_52w_low`, before `data_source`):
```python
    # P2a: detailed income statement items (None when provider doesn't supply them)
    depreciation_amortization: float | None = None
    rd_expense: float | None = None
    sga_expense: float | None = None
    interest_expense: float | None = None
```

Add to `DCFInputs` (after `nwc_pct_revenue`):
```python
    da_pct_revenue: float | None = Field(
        default=None,
        ge=0,
        le=0.5,
        description="D&A as % of revenue. None = use simplified FCF formula (P1.5).",
    )
```

Add to `DCFResult` (after `inputs`):
```python
    fcf_formula: str = "simplified"  # "simplified" | "standard_with_da"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_financial_models.py -v -k "da_pct or da_fields or fcf_formula"`
Expected: all PASS

- [ ] **Step 5: Run full model test suite**

Run: `uv run pytest tests/unit/test_financial_models.py -v`
Expected: all PASS (existing tests unbroken)

- [ ] **Step 6: Commit**

```bash
git add finrobot/engine/models/financial.py tests/unit/test_financial_models.py
git commit -m "feat(P2a-1): add D&A fields to FinancialData, DCFInputs, DCFResult"
```

---

## Task 2: DCF — standard FCF formula with D&A

**Files:**
- Modify: `finrobot/engine/compute/dcf.py:39-56` (FCF projection loop)
- Test: `tests/unit/test_dcf.py` (add new tests)

- [ ] **Step 1: Write failing tests for standard FCF formula**

Add to `tests/unit/test_dcf.py`:

```python
# --- P2a: standard FCF formula with D&A ---

def test_dcf_standard_formula_with_da_hand_calculated():
    """Standard FCF formula: EBIT(1-T) + D&A - CapEx - ΔNWC.

    Inputs:
      - revenue_base: 100B, growth: [0.05]*5, ebitda_margin: 0.35
      - da_pct_revenue: 0.10, capex_pct: 0.05, nwc_pct: 0.02, tax: 0.21
      - wacc_override: 0.10, tg: 0.025

    Year 1 hand calculation:
      rev      = 100B × 1.05 = 105B
      ebitda   = 105B × 0.35 = 36.75B
      da       = 105B × 0.10 = 10.5B
      ebit     = 36.75B - 10.5B = 26.25B
      fcf      = 26.25B × 0.79 + 10.5B - 105B × 0.05 - 105B × 0.02
               = 20.7375B + 10.5B - 5.25B - 2.1B
               = 23.8875B

    Compare to simplified formula (no D&A):
      fcf_simplified = 36.75B × 0.79 - 5.25B - 2.1B = 21.6825B

    The standard formula gives higher FCF because D&A provides a tax shield.
    Difference = D&A × tax_rate = 10.5B × 0.21 = 2.205B
    23.8875 - 21.6825 = 2.205B ✓

    Source: Damodaran, "Investment Valuation" 3rd Ed., Chapter 12.
    """
    inputs = _make_inputs(da_pct_revenue=0.10)
    result = calculate_dcf(inputs, wacc_override=0.10)

    # Y1 FCF check
    assert result.projected_fcf[0] == pytest.approx(23_887_500_000, rel=1e-9)

    # Formula tag
    assert result.fcf_formula == "standard_with_da"


def test_dcf_simplified_formula_when_da_none():
    """When da_pct_revenue is None, use P1.5 simplified formula."""
    inputs = _make_inputs()  # da_pct_revenue defaults to None
    result = calculate_dcf(inputs, wacc_override=0.10)
    assert result.fcf_formula == "simplified"
    # Y1 FCF should match simplified: EBITDA*(1-T) - capex - nwc
    rev1 = 100e9 * 1.05
    expected_fcf = rev1 * 0.35 * 0.79 - rev1 * 0.05 - rev1 * 0.02
    assert result.projected_fcf[0] == pytest.approx(expected_fcf, rel=1e-9)


def test_dcf_da_tax_shield_difference():
    """Standard - simplified = D&A × tax_rate (the tax shield)."""
    inputs_with_da = _make_inputs(da_pct_revenue=0.10)
    inputs_without = _make_inputs()

    r_with = calculate_dcf(inputs_with_da, wacc_override=0.10)
    r_without = calculate_dcf(inputs_without, wacc_override=0.10)

    # For each year, difference should be rev × da_pct × tax_rate
    for i in range(5):
        rev = r_with.projected_revenue[i]
        expected_diff = rev * 0.10 * 0.21
        actual_diff = r_with.projected_fcf[i] - r_without.projected_fcf[i]
        assert actual_diff == pytest.approx(expected_diff, rel=1e-9)


def test_dcf_da_zero_equivalent_to_simplified():
    """da_pct_revenue=0.0 means no D&A → EBIT=EBITDA, but formula is 'standard_with_da'."""
    inputs_da0 = _make_inputs(da_pct_revenue=0.0)
    inputs_none = _make_inputs()

    r_da0 = calculate_dcf(inputs_da0, wacc_override=0.10)
    r_none = calculate_dcf(inputs_none, wacc_override=0.10)

    # FCF values should be identical (D&A=0 → no tax shield difference)
    for i in range(5):
        assert r_da0.projected_fcf[i] == pytest.approx(r_none.projected_fcf[i], rel=1e-9)

    # But formula label differs
    assert r_da0.fcf_formula == "standard_with_da"
    assert r_none.fcf_formula == "simplified"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_dcf.py -v -k "da_"`
Expected: FAIL — `DCFInputs` rejects `da_pct_revenue` (Task 1 must be done first), or `fcf_formula` not in result

- [ ] **Step 3: Modify calculate_dcf()**

In `finrobot/engine/compute/dcf.py`, replace the FCF projection loop (lines 44-56) with:

```python
    prev_revenue = inputs.revenue_base
    for g in inputs.revenue_growth_rates:
        rev = prev_revenue * (1 + g)
        ebitda = rev * inputs.ebitda_margin

        if inputs.da_pct_revenue is not None:
            # P2a standard: EBIT(1-T) + D&A - CapEx - ΔNWC
            da = rev * inputs.da_pct_revenue
            ebit = ebitda - da
            fcf = (
                ebit * (1 - inputs.tax_rate)
                + da
                - rev * inputs.capex_pct_revenue
                - rev * inputs.nwc_pct_revenue
            )
        else:
            # P1.5 simplified: EBITDA(1-T) - CapEx - ΔNWC
            fcf = (
                ebitda * (1 - inputs.tax_rate)
                - rev * inputs.capex_pct_revenue
                - rev * inputs.nwc_pct_revenue
            )

        projected_revenue.append(rev)
        projected_ebitda.append(ebitda)
        projected_fcf.append(fcf)
        prev_revenue = rev
```

Also update the return statement to include `fcf_formula`:

```python
    return DCFResult(
        cost_of_equity=cost_of_equity,
        wacc=wacc,
        projection_years=n,
        projected_revenue=projected_revenue,
        projected_ebitda=projected_ebitda,
        projected_fcf=projected_fcf,
        terminal_value=terminal_value,
        pv_terminal=pv_terminal,
        pv_fcf_total=pv_fcf_total,
        enterprise_value=enterprise_value,
        equity_value=equity_value,
        implied_price=implied_price,
        inputs=inputs,
        fcf_formula="standard_with_da" if inputs.da_pct_revenue is not None else "simplified",
    )
```

- [ ] **Step 4: Run new tests**

Run: `uv run pytest tests/unit/test_dcf.py -v -k "da_"`
Expected: all PASS

- [ ] **Step 5: Run full DCF test suite (regression)**

Run: `uv run pytest tests/unit/test_dcf.py -v`
Expected: all PASS (existing tests return `fcf_formula="simplified"` by default — no breakage)

- [ ] **Step 6: Commit**

```bash
git add finrobot/engine/compute/dcf.py tests/unit/test_dcf.py
git commit -m "feat(P2a-2): standard FCF formula with D&A tax shield in calculate_dcf"
```

---

## Task 3: Config — add API key fields

**Files:**
- Modify: `finrobot/config.py:7-30` (FinRobotSettings)
- Modify: `.env.example`
- Test: inline verification (pydantic-settings defaults)

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_config_p2a.py`:

```python
from finrobot.config import FinRobotSettings


def test_fmp_api_key_default_empty():
    s = FinRobotSettings(model_name="test:test")
    assert s.fmp_api_key == ""


def test_finnhub_api_key_default_empty():
    s = FinRobotSettings(model_name="test:test")
    assert s.finnhub_api_key == ""


def test_sec_user_agent_default():
    s = FinRobotSettings(model_name="test:test")
    assert "FinRobot" in s.sec_user_agent
    assert "@" in s.sec_user_agent


def test_fmp_api_key_from_kwargs():
    s = FinRobotSettings(model_name="test:test", fmp_api_key="abc123")
    assert s.fmp_api_key == "abc123"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_config_p2a.py -v`
Expected: FAIL — `fmp_api_key` not a valid field

- [ ] **Step 3: Add fields to FinRobotSettings**

In `finrobot/config.py`, add after `openai_api_key` (line 23):

```python
    # Data provider API keys (P2a)
    fmp_api_key: str = ""
    finnhub_api_key: str = ""
    sec_user_agent: str = "FinRobot admin@example.com"
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_config_p2a.py -v`
Expected: all PASS

- [ ] **Step 5: Update .env.example**

Add after the `FINAGENT_OPENAI_API_KEY` line:

```
# Data provider API keys (P2a — optional, enables richer data)
# FINAGENT_FMP_API_KEY=...             # financialmodelingprep.com — D&A, detailed financials
# FINAGENT_FINNHUB_API_KEY=...         # finnhub.io — real-time quotes, company profiles
# FINAGENT_SEC_USER_AGENT=YourCompany you@email.com  # SEC EDGAR requires User-Agent
```

- [ ] **Step 6: Commit**

```bash
git add finrobot/config.py .env.example tests/unit/test_config_p2a.py
git commit -m "feat(P2a-3): add FMP/Finnhub/SEC config fields to FinRobotSettings"
```

---

## Task 4: FMP Provider

**Files:**
- Create: `finrobot/engine/data/providers/fmp_provider.py`
- Test: `tests/unit/test_fmp_provider.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_fmp_provider.py`:

```python
"""FMP Provider unit tests. All HTTP calls are mocked."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest

from finrobot.engine.data.interface import ProviderError
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


def _fmp_profile_response(ticker: str = "AAPL") -> list[dict]:
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
    async def test_fetch_financials_returns_normalized_keys(self, provider):
        """FMP-specific keys are normalized to common format."""
        responses = [
            _mock_response(_fmp_income_response()),
            _mock_response(_fmp_balance_response()),
            _mock_response(_fmp_profile_response()),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "financials")

        assert result.provider == "fmp"
        assert result.ticker == "AAPL"
        assert result.data_type == "financials"
        # Key normalization checks
        assert result.data["revenue"] == 394_328_000_000
        assert result.data["ebitda"] == 137_352_000_000
        assert result.data["depreciation_amortization"] == 11_519_000_000
        assert result.data["rd_expense"] == 29_915_000_000
        assert result.data["sga_expense"] == 27_552_000_000
        assert result.data["interest_expense"] == 3_933_000_000
        assert result.data["total_debt"] == 111_088_000_000
        assert result.data["total_cash"] == 29_965_000_000
        assert result.data["market_cap"] == 2_620_000_000_000

    async def test_fetch_unsupported_data_type_raises(self, provider):
        with pytest.raises(ProviderError, match="not supported"):
            await provider.fetch("AAPL", "news")

    async def test_api_error_raises_provider_error(self, provider):
        with patch.object(
            provider, "_get", AsyncMock(side_effect=httpx.HTTPStatusError(
                "403", request=MagicMock(), response=MagicMock(status_code=403)
            ))
        ):
            with pytest.raises(ProviderError):
                await provider.fetch("AAPL", "financials")

    async def test_timeout_raises_provider_error(self, provider):
        with patch.object(
            provider, "_get", AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        ):
            with pytest.raises(ProviderError, match="timeout"):
                await provider.fetch("AAPL", "financials")


class TestFMPProviderInterface:
    def test_name(self, provider):
        assert provider.name == "fmp"

    def test_capabilities(self, provider):
        caps = provider.capabilities()
        assert "financials" in caps
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_fmp_provider.py -v`
Expected: FAIL — `fmp_provider` module does not exist

- [ ] **Step 3: Implement FMPProvider**

Create `finrobot/engine/data/providers/fmp_provider.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from finrobot.engine.data.interface import DataProvider, DataResult, ProviderError

_BASE_URL = "https://financialmodelingprep.com/api/v3"
_SUPPORTED = ["financials"]
_TIMEOUT = 15.0


class FMPProvider(DataProvider):
    """DataProvider backed by Financial Modeling Prep API.

    Provides D&A, R&D, SGA, and other detailed financials that yfinance lacks.
    API key required — get one at https://financialmodelingprep.com/
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "fmp"

    def capabilities(self) -> list[str]:
        return list(_SUPPORTED)

    async def fetch(self, ticker: str, data_type: str, **kwargs) -> DataResult:
        if data_type not in _SUPPORTED:
            raise ProviderError(
                f"data_type '{data_type}' is not supported by FMP. Supported: {_SUPPORTED}"
            )
        try:
            income = (await self._get(f"/income-statement/{ticker}", params={"limit": 1})).json()
            balance = (await self._get(f"/balance-sheet-statement/{ticker}", params={"limit": 1})).json()
            profile = (await self._get(f"/profile/{ticker}")).json()
        except httpx.TimeoutException as e:
            raise ProviderError(f"FMP timeout for '{ticker}': {e}") from e
        except httpx.HTTPStatusError as e:
            raise ProviderError(f"FMP API error for '{ticker}': {e}") from e
        except Exception as e:
            raise ProviderError(f"FMP fetch failed for '{ticker}': {e}") from e

        inc = income[0] if income else {}
        bal = balance[0] if balance else {}
        prof = profile[0] if profile else {}

        # Key normalization: FMP keys → common keys
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
                if inc.get("netIncome") and prof.get("mktCap") and prof.get("price")
                and inc["netIncome"] > 0
                else None
            ),
            "beta": prof.get("beta"),
            "current_price": prof.get("price"),
            "company_name": prof.get("companyName"),
            "industry": prof.get("industry"),
            "sector": prof.get("sector"),
        }

        return DataResult(
            data=data,
            provider=self.name,
            ticker=ticker,
            data_type=data_type,
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        """Make authenticated GET request to FMP API."""
        p = {"apikey": self._api_key}
        if params:
            p.update(params)
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{_BASE_URL}{path}", params=p)
            resp.raise_for_status()
            return resp
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_fmp_provider.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add finrobot/engine/data/providers/fmp_provider.py tests/unit/test_fmp_provider.py
git commit -m "feat(P2a-4): FMP provider with key normalization"
```

---

## Task 5: Finnhub Provider

**Files:**
- Create: `finrobot/engine/data/providers/finnhub_provider.py`
- Test: `tests/unit/test_finnhub_provider.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_finnhub_provider.py`:

```python
"""Finnhub Provider unit tests. All HTTP calls are mocked."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest

from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.providers.finnhub_provider import FinnhubProvider


@pytest.fixture
def provider():
    return FinnhubProvider(api_key="test-key")


def _finnhub_financials_response() -> dict:
    """Mock Finnhub /stock/metric response."""
    return {
        "metric": {
            "revenuePerShareAnnual": 25.0,
            "epsAnnual": 6.5,
            "ebitdaPerShareTTM": 8.75,
            "peBasicExclExtraTTM": 28.0,
            "10DayAverageTradingVolume": 54.0,
            "52WeekHigh": 199.0,
            "52WeekLow": 130.0,
            "beta": 1.24,
        },
        "series": {},
    }


def _finnhub_profile_response() -> dict:
    """Mock Finnhub /stock/profile2 response."""
    return {
        "ticker": "AAPL",
        "name": "Apple Inc",
        "finnhubIndustry": "Technology",
        "marketCapitalization": 2_620_000,  # Finnhub reports in millions
        "shareOutstanding": 15_000,         # millions
        "exchange": "NASDAQ",
    }


def _finnhub_financials_reported_response() -> dict:
    """Mock Finnhub /stock/financials-reported response (SEC filings)."""
    return {
        "data": [
            {
                "year": 2025,
                "quarter": 0,
                "report": {
                    "ic": [
                        {"concept": "Revenues", "value": 394_328_000_000},
                        {"concept": "CostOfGoodsAndServicesSold", "value": 213_645_000_000},
                        {"concept": "OperatingIncomeLoss", "value": 123_216_000_000},
                        {"concept": "NetIncomeLoss", "value": 96_995_000_000},
                        {"concept": "DepreciationAndAmortization", "value": 11_519_000_000},
                    ],
                    "bs": [
                        {"concept": "LongTermDebt", "value": 98_071_000_000},
                        {"concept": "CashAndCashEquivalentsAtCarryingValue", "value": 29_965_000_000},
                    ],
                },
            }
        ]
    }


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


class TestFinnhubFetch:
    async def test_fetch_financials_returns_normalized_keys(self, provider):
        responses = [
            _mock_response(_finnhub_profile_response()),
            _mock_response(_finnhub_financials_reported_response()),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "financials")

        assert result.provider == "finnhub"
        assert result.data["revenue"] == 394_328_000_000
        assert result.data["depreciation_amortization"] == 11_519_000_000
        assert result.data["market_cap"] == 2_620_000_000_000  # converted from millions

    async def test_fetch_profile(self, provider):
        with patch.object(
            provider, "_get", AsyncMock(return_value=_mock_response(_finnhub_profile_response()))
        ):
            result = await provider.fetch("AAPL", "profile")
        assert result.data_type == "profile"
        assert result.data["company_name"] == "Apple Inc"

    async def test_unsupported_type_raises(self, provider):
        with pytest.raises(ProviderError, match="not supported"):
            await provider.fetch("AAPL", "news")

    async def test_timeout_raises_provider_error(self, provider):
        with patch.object(
            provider, "_get", AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        ):
            with pytest.raises(ProviderError, match="timeout"):
                await provider.fetch("AAPL", "financials")


class TestFinnhubInterface:
    def test_name(self, provider):
        assert provider.name == "finnhub"

    def test_capabilities(self, provider):
        caps = provider.capabilities()
        assert "financials" in caps
        assert "profile" in caps
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_finnhub_provider.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement FinnhubProvider**

Create `finrobot/engine/data/providers/finnhub_provider.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from finrobot.engine.data.interface import DataProvider, DataResult, ProviderError

_BASE_URL = "https://finnhub.io/api/v1"
_SUPPORTED = ["financials", "profile"]
_TIMEOUT = 15.0


class FinnhubProvider(DataProvider):
    """DataProvider backed by Finnhub API.

    Provides company profiles, basic financials, and SEC-reported data.
    API key required — get one at https://finnhub.io/
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "finnhub"

    def capabilities(self) -> list[str]:
        return list(_SUPPORTED)

    async def fetch(self, ticker: str, data_type: str, **kwargs) -> DataResult:
        if data_type not in _SUPPORTED:
            raise ProviderError(
                f"data_type '{data_type}' is not supported by Finnhub. Supported: {_SUPPORTED}"
            )
        try:
            if data_type == "financials":
                data = await self._fetch_financials(ticker)
            elif data_type == "profile":
                data = await self._fetch_profile(ticker)
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

    async def _fetch_financials(self, ticker: str) -> dict:
        profile = (await self._get("/stock/profile2", params={"symbol": ticker})).json()

        reported = (await self._get(
            "/stock/financials-reported",
            params={"symbol": ticker, "freq": "annual"},
        )).json()

        # Extract latest annual filing
        filings = reported.get("data", [])
        latest = filings[0] if filings else {}
        report = latest.get("report", {})

        def _find_concept(section: str, concept: str) -> float | None:
            items = report.get(section, [])
            for item in items:
                if item.get("concept") == concept:
                    return item.get("value")
            return None

        mkt_cap_millions = profile.get("marketCapitalization", 0)
        shares_millions = profile.get("shareOutstanding", 0)

        revenue = _find_concept("ic", "Revenues")
        net_income = _find_concept("ic", "NetIncomeLoss")
        da = _find_concept("ic", "DepreciationAndAmortization")
        total_debt = _find_concept("bs", "LongTermDebt") or 0
        total_cash = _find_concept("bs", "CashAndCashEquivalentsAtCarryingValue") or 0

        return {
            "revenue": revenue,
            "ebitda": (
                (_find_concept("ic", "OperatingIncomeLoss") or 0) + (da or 0)
                if _find_concept("ic", "OperatingIncomeLoss") is not None
                else None
            ),
            "net_income": net_income,
            "depreciation_amortization": da,
            "total_debt": total_debt,
            "total_cash": total_cash,
            "market_cap": mkt_cap_millions * 1_000_000 if mkt_cap_millions else None,
            "shares_outstanding": shares_millions * 1_000_000 if shares_millions else None,
            "gross_margin": (
                (revenue - _find_concept("ic", "CostOfGoodsAndServicesSold")) / revenue
                if revenue and _find_concept("ic", "CostOfGoodsAndServicesSold") is not None
                else None
            ),
            "operating_margin": (
                _find_concept("ic", "OperatingIncomeLoss") / revenue
                if revenue and _find_concept("ic", "OperatingIncomeLoss") is not None
                else None
            ),
            "current_price": None,  # profile endpoint doesn't always provide price
            "company_name": profile.get("name"),
            "industry": profile.get("finnhubIndustry"),
        }

    async def _fetch_profile(self, ticker: str) -> dict:
        profile = (await self._get("/stock/profile2", params={"symbol": ticker})).json()
        return {
            "company_name": profile.get("name"),
            "industry": profile.get("finnhubIndustry"),
            "market_cap": (profile.get("marketCapitalization", 0) or 0) * 1_000_000,
            "shares_outstanding": (profile.get("shareOutstanding", 0) or 0) * 1_000_000,
            "exchange": profile.get("exchange"),
        }

    async def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        """Make authenticated GET request to Finnhub API."""
        headers = {"X-Finnhub-Token": self._api_key}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{_BASE_URL}{path}", params=params or {}, headers=headers)
            resp.raise_for_status()
            return resp
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_finnhub_provider.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add finrobot/engine/data/providers/finnhub_provider.py tests/unit/test_finnhub_provider.py
git commit -m "feat(P2a-5): Finnhub provider with key normalization"
```

---

## Task 6: SEC EDGAR Provider

**Files:**
- Create: `finrobot/engine/data/providers/sec_provider.py`
- Test: `tests/unit/test_sec_provider.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_sec_provider.py`:

```python
"""SEC EDGAR Provider unit tests. All HTTP calls are mocked."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest

from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.providers.sec_provider import SECEdgarProvider


@pytest.fixture
def provider():
    return SECEdgarProvider(user_agent="TestAgent test@test.com")


def _sec_submissions_response() -> dict:
    """Mock SEC EDGAR /submissions/ response."""
    return {
        "cik": "0000320193",
        "entityType": "operating",
        "name": "Apple Inc",
        "tickers": ["AAPL"],
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-24-000081"],
                "filingDate": ["2024-11-01"],
                "form": ["10-K"],
                "primaryDocument": ["aapl-20240928.htm"],
            }
        },
    }


def _sec_company_tickers_response() -> dict:
    """Mock SEC company_tickers.json — used by _resolve_cik()."""
    return {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc"},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
    }


def _mock_response(json_data=None, text_data=None, status_code=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    if json_data is not None:
        resp.json.return_value = json_data
    if text_data is not None:
        resp.text = text_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


class TestSECEdgarFetch:
    async def test_fetch_filings_returns_10k_info(self, provider):
        """_fetch_filings calls _get twice: _resolve_cik then submissions."""
        responses = [
            _mock_response(_sec_company_tickers_response()),   # _resolve_cik
            _mock_response(_sec_submissions_response()),        # submissions
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "filings")

        assert result.provider == "sec_edgar"
        assert result.data_type == "filings"
        assert result.data["latest_10k_date"] == "2024-11-01"
        assert result.data["has_10k"] is True

    async def test_unsupported_type_raises(self, provider):
        with pytest.raises(ProviderError, match="not supported"):
            await provider.fetch("AAPL", "financials")

    async def test_user_agent_in_headers(self, provider):
        """SEC EDGAR requires User-Agent header."""
        assert provider._user_agent == "TestAgent test@test.com"

    async def test_timeout_raises_provider_error(self, provider):
        with patch.object(
            provider, "_get", AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        ):
            with pytest.raises(ProviderError, match="timeout"):
                await provider.fetch("AAPL", "filings")

    async def test_rate_limit_403_raises_provider_error(self, provider):
        with patch.object(
            provider, "_get",
            AsyncMock(side_effect=httpx.HTTPStatusError(
                "403", request=MagicMock(), response=MagicMock(status_code=403)
            )),
        ):
            with pytest.raises(ProviderError):
                await provider.fetch("AAPL", "filings")


class TestSECEdgarInterface:
    def test_name(self, provider):
        assert provider.name == "sec_edgar"

    def test_capabilities(self, provider):
        caps = provider.capabilities()
        assert "filings" in caps
        assert "financials" not in caps
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_sec_provider.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement SECEdgarProvider**

Create `finrobot/engine/data/providers/sec_provider.py`:

```python
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from finrobot.engine.data.interface import DataProvider, DataResult, ProviderError

_SUBMISSIONS_URL = "https://data.sec.gov/submissions"
_SUPPORTED = ["filings"]
_TIMEOUT = 15.0
_MIN_REQUEST_INTERVAL = 0.11  # SEC rate limit: 10 req/s → at least 100ms between requests


class SECEdgarProvider(DataProvider):
    """DataProvider for SEC EDGAR (10-K/10-Q filings).

    Free, no API key required, but requires a User-Agent header
    (SEC policy: 'CompanyName AdminEmail').
    Rate limit: 10 requests/second.
    """

    def __init__(self, user_agent: str) -> None:
        self._user_agent = user_agent
        self._last_request: float = 0

    @property
    def name(self) -> str:
        return "sec_edgar"

    def capabilities(self) -> list[str]:
        return list(_SUPPORTED)

    async def fetch(self, ticker: str, data_type: str, **kwargs) -> DataResult:
        if data_type not in _SUPPORTED:
            raise ProviderError(
                f"data_type '{data_type}' is not supported by SEC EDGAR. Supported: {_SUPPORTED}"
            )
        try:
            data = await self._fetch_filings(ticker)
        except httpx.TimeoutException as e:
            raise ProviderError(f"SEC EDGAR timeout for '{ticker}': {e}") from e
        except httpx.HTTPStatusError as e:
            raise ProviderError(f"SEC EDGAR API error for '{ticker}': {e}") from e
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"SEC EDGAR fetch failed for '{ticker}': {e}") from e

        return DataResult(
            data=data,
            provider=self.name,
            ticker=ticker,
            data_type=data_type,
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def _fetch_filings(self, ticker: str) -> dict:
        """Fetch latest 10-K filing metadata from SEC EDGAR."""
        # Step 1: Get CIK from ticker via submissions endpoint
        # SEC uses CIK (Central Index Key) as the primary identifier
        cik = await self._resolve_cik(ticker)
        submissions = (await self._get(f"{_SUBMISSIONS_URL}/CIK{cik}.json")).json()

        filings = submissions.get("filings", {}).get("recent", {})
        forms = filings.get("form", [])
        dates = filings.get("filingDate", [])
        accessions = filings.get("accessionNumber", [])

        # Find latest 10-K
        latest_10k_idx = None
        for i, form in enumerate(forms):
            if form == "10-K":
                latest_10k_idx = i
                break

        if latest_10k_idx is None:
            return {
                "company_name": submissions.get("name"),
                "cik": cik,
                "latest_10k_date": None,
                "latest_10k_accession": None,
                "has_10k": False,
            }

        return {
            "company_name": submissions.get("name"),
            "cik": cik,
            "latest_10k_date": dates[latest_10k_idx],
            "latest_10k_accession": accessions[latest_10k_idx],
            "has_10k": True,
        }

    async def _resolve_cik(self, ticker: str) -> str:
        """Resolve ticker to zero-padded CIK."""
        tickers = (await self._get("https://www.sec.gov/files/company_tickers.json")).json()
        for entry in tickers.values():
            if entry.get("ticker", "").upper() == ticker.upper():
                return str(entry["cik_str"]).zfill(10)
        raise ProviderError(f"Could not resolve CIK for ticker '{ticker}'")

    async def _get(self, url: str) -> httpx.Response:
        """Make rate-limited GET request with required User-Agent."""
        # Respect SEC rate limit
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request
        if elapsed < _MIN_REQUEST_INTERVAL:
            await asyncio.sleep(_MIN_REQUEST_INTERVAL - elapsed)

        headers = {
            "User-Agent": self._user_agent,
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
            self._last_request = asyncio.get_event_loop().time()
            resp.raise_for_status()
            return resp
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_sec_provider.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add finrobot/engine/data/providers/sec_provider.py tests/unit/test_sec_provider.py
git commit -m "feat(P2a-6): SEC EDGAR provider with rate limiting and User-Agent"
```

**Note:** The spec mentions `fetch_mdna(ticker)` for extracting the MD&A section from 10-K filings. This requires HTML parsing of the full filing document, which is complex and orthogonal to the data infrastructure work. Deferred to a follow-up task after the provider chain is proven. The current implementation retrieves filing metadata (date, accession number) which is sufficient for the acceptance criteria.

---

## Task 7: DataLayer — chain fallback

**Files:**
- Modify: `finrobot/engine/data/layer.py:15-88`
- Test: `tests/unit/test_data_layer.py` (add chain tests)

- [ ] **Step 1: Write failing tests for 3-provider chain**

Add to `tests/unit/test_data_layer.py`:

```python
class TestChainFallback:
    """P2a: chain fallback iterates all providers, not just primary + 1 fallback."""

    async def test_three_provider_chain_first_succeeds(self, cache):
        p1 = MockProvider("fmp", ["financials"], result=_make_result(provider="fmp"))
        p2 = MockProvider("finnhub", ["financials"])
        p3 = MockProvider("yfinance", ["financials"])
        layer = DataLayer([p1, p2, p3], cache)
        result = await layer.fetch("financials", "AAPL")
        assert result.provider == "fmp"
        assert p1.fetch_called == 1
        assert p2.fetch_called == 0
        assert p3.fetch_called == 0

    async def test_three_provider_chain_first_fails_second_succeeds(self, cache):
        p1 = MockProvider("fmp", ["financials"], raises=ProviderError("fmp down"))
        p2 = MockProvider("finnhub", ["financials"], result=_make_result(provider="finnhub"))
        p3 = MockProvider("yfinance", ["financials"])
        layer = DataLayer([p1, p2, p3], cache)
        result = await layer.fetch("financials", "AAPL")
        assert result.provider == "finnhub"
        assert p1.fetch_called == 1
        assert p2.fetch_called == 1
        assert p3.fetch_called == 0

    async def test_three_provider_chain_first_two_fail_third_succeeds(self, cache):
        p1 = MockProvider("fmp", ["financials"], raises=ProviderError("fmp down"))
        p2 = MockProvider("finnhub", ["financials"], raises=ProviderError("finnhub down"))
        p3 = MockProvider("yfinance", ["financials"], result=_make_result(provider="yfinance"))
        layer = DataLayer([p1, p2, p3], cache)
        result = await layer.fetch("financials", "AAPL")
        assert result.provider == "yfinance"
        assert p1.fetch_called == 1
        assert p2.fetch_called == 1
        assert p3.fetch_called == 1

    async def test_all_three_fail_returns_error(self, cache):
        p1 = MockProvider("fmp", ["financials"], raises=ProviderError("fmp down"))
        p2 = MockProvider("finnhub", ["financials"], raises=ProviderError("finnhub down"))
        p3 = MockProvider("yfinance", ["financials"], raises=ProviderError("yfinance down"))
        layer = DataLayer([p1, p2, p3], cache)
        result = await layer.fetch("financials", "AAPL")
        assert result.provider == "none"
        assert any("unavailable" in w.lower() or "failed" in w.lower() for w in result.warnings)
```

- [ ] **Step 2: Run tests to verify the third-provider test fails**

Run: `uv run pytest tests/unit/test_data_layer.py::TestChainFallback -v`
Expected: `test_three_provider_chain_first_two_fail_third_succeeds` FAILS — current code only tries primary + 1 fallback

- [ ] **Step 3: Modify DataLayer.fetch() to chain all providers**

Replace the `fetch()` method and remove `_select_provider` / `_select_fallback` in `finrobot/engine/data/layer.py`:

```python
    async def fetch(self, data_type: str, ticker: str, **kwargs) -> DataResult:
        """
        Flow:
        1. Check cache → if fresh, return
        2. Iterate all providers supporting this data_type (in priority order)
        3. First successful fetch → cache → return
        4. All providers failed → return stale cache with warning
        5. No cache at all → return error DataResult
        """
        # 1. Fresh cache hit
        cached = await self._cache.get(data_type, ticker)
        if cached is not None and not cached.is_stale:
            return cached.data

        # 2. Try each provider in order
        for provider in self._providers:
            if data_type not in provider.capabilities():
                continue
            try:
                result = await provider.fetch(ticker, data_type, **kwargs)
                await self._cache.set(data_type, ticker, result)
                return result
            except ProviderError as e:
                logger.warning(
                    f"Provider '{provider.name}' failed for {ticker}/{data_type}: {e}"
                )
                continue

        # 3. All providers failed — return stale cache with warning if available
        if cached is not None:
            stale = cached.data
            return stale.model_copy(
                update={"warnings": stale.warnings + ["stale data: all providers failed"]}
            )

        # 4. No data anywhere
        msg = (
            f"Data unavailable for {ticker}/{data_type}: "
            "all providers failed and no cache exists."
        )
        logger.error(msg)
        return DataResult(
            data={"error": msg},
            provider="none",
            ticker=ticker,
            data_type=data_type,
            timestamp=datetime.now(tz=timezone.utc),
            warnings=[msg],
        )
```

Remove the `_select_provider` and `_select_fallback` methods entirely.

- [ ] **Step 4: Run all data layer tests**

Run: `uv run pytest tests/unit/test_data_layer.py -v`
Expected: all PASS (new chain tests + existing tests — existing tests use 1-2 providers which still work)

- [ ] **Step 5: Commit**

```bash
git add finrobot/engine/data/layer.py tests/unit/test_data_layer.py
git commit -m "feat(P2a-7): chain fallback — iterate all providers in priority order"
```

---

## Task 8: Extractor — extract D&A fields

**Files:**
- Modify: `finrobot/engine/compute/extractor.py:36-55` (return statement)
- Test: add to existing extractor tests or create `tests/unit/test_extractor_da.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_extractor_da.py`:

```python
from datetime import datetime, timezone

from finrobot.engine.data.interface import DataResult
from finrobot.engine.compute.extractor import extract_financial_data


def _make_financials_result(**overrides) -> DataResult:
    data = {
        "revenue": 394e9,
        "ebitda": 137e9,
        "net_income": 97e9,
        "gross_margin": 0.43,
        "operating_margin": 0.30,
        "market_cap": 2.6e12,
        "shares_outstanding": 15e9,
        "total_debt": 111e9,
        "total_cash": 30e9,
    }
    data.update(overrides)
    return DataResult(
        data=data, provider="fmp", ticker="AAPL",
        data_type="financials", timestamp=datetime.now(tz=timezone.utc),
    )


def _make_price_result() -> DataResult:
    return DataResult(
        data={"current_price": 175.0, "price_history": [{"close": 175.0}]},
        provider="fmp", ticker="AAPL",
        data_type="price", timestamp=datetime.now(tz=timezone.utc),
    )


def test_extract_da_from_fmp():
    """When provider supplies D&A, it appears in FinancialData."""
    fin = _make_financials_result(depreciation_amortization=11.5e9)
    result = extract_financial_data(fin, _make_price_result())
    assert result.depreciation_amortization == 11.5e9


def test_extract_da_none_from_yfinance():
    """When provider doesn't supply D&A, field is None."""
    fin = _make_financials_result()  # no depreciation_amortization key
    result = extract_financial_data(fin, _make_price_result())
    assert result.depreciation_amortization is None


def test_extract_rd_sga_interest():
    fin = _make_financials_result(
        rd_expense=30e9, sga_expense=28e9, interest_expense=4e9,
    )
    result = extract_financial_data(fin, _make_price_result())
    assert result.rd_expense == 30e9
    assert result.sga_expense == 28e9
    assert result.interest_expense == 4e9
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_extractor_da.py -v`
Expected: FAIL — `FinancialData` doesn't pass D&A fields yet (Task 1 model changes exist, but extractor doesn't extract them)

- [ ] **Step 3: Add D&A extraction to extractor**

In `finrobot/engine/compute/extractor.py`, in `extract_financial_data()`, add new fields to the return `FinancialData(...)` constructor (after `price_52w_low=low_52w`):

```python
        depreciation_amortization=data.get("depreciation_amortization"),
        rd_expense=data.get("rd_expense"),
        sga_expense=data.get("sga_expense"),
        interest_expense=data.get("interest_expense"),
```

Also update `data_source` to use the provider name:

```python
        data_source=financials_result.provider,
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_extractor_da.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add finrobot/engine/compute/extractor.py tests/unit/test_extractor_da.py
git commit -m "feat(P2a-8): extract D&A/R&D/SGA/interest fields in extractor"
```

---

## Task 9: Wire providers into CLI and Server

**Files:**
- Modify: `finrobot/cli.py:9-30` (`_build_deps()`)
- Modify: `finrobot/server.py:31-35` (lifespan)

- [ ] **Step 1: Modify _build_deps() in cli.py**

Replace the DataLayer construction in `finrobot/cli.py` `_build_deps()` (around line 26-27):

```python
    # Build provider chain: FMP (if key) → Finnhub (if key) → yfinance (always)
    # SEC EDGAR is always available (no API key needed, uses User-Agent header)
    from finrobot.engine.data.providers.sec_provider import SECEdgarProvider

    providers: list = []
    if settings.fmp_api_key:
        from finrobot.engine.data.providers.fmp_provider import FMPProvider

        providers.append(FMPProvider(api_key=settings.fmp_api_key))
    if settings.finnhub_api_key:
        from finrobot.engine.data.providers.finnhub_provider import FinnhubProvider

        providers.append(FinnhubProvider(api_key=settings.finnhub_api_key))
    providers.append(YFinanceProvider())  # always last (free fallback)
    providers.append(SECEdgarProvider(user_agent=settings.sec_user_agent))  # filings only

    cache = DataCache(settings.cache_db_path)
    data_layer = DataLayer(providers=providers, cache=cache)
```

- [ ] **Step 2: Modify lifespan() in server.py**

**First**, remove the top-level import at line 14:
```python
# DELETE this line:
from finrobot.engine.data.providers.yfinance_provider import YFinanceProvider
```

Then replace the DataLayer construction in `lifespan()` (around line 33-34):

```python
    # Build provider chain: FMP (if key) → Finnhub (if key) → yfinance (always) + SEC EDGAR
    from finrobot.engine.data.providers.yfinance_provider import YFinanceProvider
    from finrobot.engine.data.providers.sec_provider import SECEdgarProvider

    providers: list = []
    if settings.fmp_api_key:
        from finrobot.engine.data.providers.fmp_provider import FMPProvider

        providers.append(FMPProvider(api_key=settings.fmp_api_key))
    if settings.finnhub_api_key:
        from finrobot.engine.data.providers.finnhub_provider import FinnhubProvider

        providers.append(FinnhubProvider(api_key=settings.finnhub_api_key))
    providers.append(YFinanceProvider())
    providers.append(SECEdgarProvider(user_agent=settings.sec_user_agent))

    cache = DataCache(settings.cache_db_path)
    data_layer = DataLayer(providers=providers, cache=cache)
```

- [ ] **Step 3: Run existing tests to check for regressions**

Run: `uv run pytest tests/unit/ -v`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add finrobot/cli.py finrobot/server.py
git commit -m "feat(P2a-9): wire FMP/Finnhub/yfinance provider chain into CLI and server"
```

---

## Task 10: Quality gates

- [ ] **Step 1: Format**

Run: `uv run ruff format finrobot/`

- [ ] **Step 2: Lint**

Run: `uv run ruff check finrobot/`
Fix any issues.

- [ ] **Step 3: Type check**

Run: `uv run mypy finrobot/ --ignore-missing-imports`
Fix any issues.

- [ ] **Step 4: Full test suite**

Run: `uv run pytest tests/unit/ -v`
Expected: all PASS

- [ ] **Step 5: Commit any fixes**

```bash
git add -A
git commit -m "chore(P2a-10): quality gates — format, lint, type check"
```

---

## Task Dependency Graph

```
Task 1 (models)
  ├── Task 2 (dcf formula) ← depends on DCFInputs.da_pct_revenue
  ├── Task 8 (extractor)   ← depends on FinancialData new fields
  └── Task 3 (config)
        ├── Task 4 (FMP provider)     ← depends on fmp_api_key
        ├── Task 5 (Finnhub provider) ← depends on finnhub_api_key
        └── Task 6 (SEC provider)     ← depends on sec_user_agent
              └── Task 7 (DataLayer chain) ← can be done after any provider
                    └── Task 9 (wiring)    ← depends on providers + DataLayer
                          └── Task 10 (quality gates)
```

Parallelizable: Tasks 4, 5, 6 are independent of each other (after Task 3).
Tasks 2 and 8 are independent of each other (after Task 1).
