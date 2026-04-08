# Structural Debt Fix (S1-S7) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 7 structural issues (S1-S7) that block clean P3 SDK design and open-source readiness.

**Architecture:** Bottom-up order — start with foundational types (S3 DataType enum, S4 extractor keys), then refactor the model (S1 FinancialData split), pipeline types (S2 StepOutput), and finish with infra (S5-S7). Each task is independently testable and committable.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, ruff, mypy

**Dependency order:** S3 → S4 → S1 → S2 → S5 → S6 → S7

**Key design decision for S1:** Use a Pydantic `model_validator(mode='before')` compatibility layer instead of property delegation. This allows `FinancialData(revenue=X, ...)` (old flat style) AND `FinancialData(income=IncomeStatement(...), ...)` (new structured style) to both work. Avoids the split-state mutation bug that property delegation would introduce.

---

## File Structure

### New files
- `finagent/engine/data/types.py` — `DataType` StrEnum (S3)
- `finagent/engine/data/keys.py` — `NormalizedFinancialKeys` TypedDict (S4, documentation-only; enforcement deferred)
- `tests/unit/test_data_types.py` — S3 tests
- `tests/unit/test_keys.py` — S4 tests
- `tests/unit/test_financial_models_split.py` — S1 tests
- `tests/unit/test_step_output_typed.py` — S2 tests
- `tests/conftest.py` — shared fixtures (S7)
- `SECURITY.md` — vulnerability reporting policy (S6)

### Modified files
- `finagent/engine/data/interface.py` — DataResult.data_type + DataProvider signatures
- `finagent/engine/data/providers/yfinance_provider.py` — DataType enum
- `finagent/engine/data/providers/fmp_provider.py` — DataType enum
- `finagent/engine/data/providers/finnhub_provider.py` — DataType enum
- `finagent/engine/data/providers/sec_provider.py` — DataType enum
- `finagent/engine/data/layer.py` — DataType enum
- `finagent/engine/data/cache.py` — DataType enum
- `finagent/engine/compute/extractor.py` — sub-model construction + REQUIRED_KEYS import
- `finagent/engine/models/financial.py` — FinancialData split + StepOutput typed
- `finagent/engine/pipelines/base.py` — PipelineResult typed, PipelineStep.required_data → list[DataType]
- `finagent/engine/orchestrator.py` — DataType enum
- `finagent/engine/agents/factory.py` — DataType enum
- `finagent/engine/pipelines/equity_research.py` — required_data uses DataType
- `finagent/engine/pipelines/dcf.py` — required_data uses DataType
- `finagent/engine/pipelines/comps.py` — required_data uses DataType
- `finagent/engine/pipelines/lbo.py` — required_data uses DataType
- `finagent/engine/pipelines/earnings_analysis.py` — required_data uses DataType
- `finagent/engine/pipelines/ic_memo.py` — required_data uses DataType
- `tests/unit/test_financial_models.py` — update _base_financial_data + validation tests
- `tests/unit/test_report_endpoints.py` — update _make_financial_data
- `tests/unit/test_data_processor.py` — update _make_financial_data
- `tests/unit/test_validators_v2.py` — update _make_fd
- `pyproject.toml` — mypy config

---

### Task 1: S3 — DataType StrEnum

**Files:**
- Create: `finagent/engine/data/types.py`
- Create: `tests/unit/test_data_types.py`
- Modify: `finagent/engine/data/interface.py`
- Modify: all 4 providers, layer.py, cache.py, orchestrator.py, factory.py
- Modify: `finagent/engine/pipelines/base.py` — `PipelineStep.required_data: list[str]` → `list[str | DataType]`
- Modify: all pipeline definition files (equity_research.py, dcf.py, comps.py, lbo.py, earnings_analysis.py, ic_memo.py) — `required_data=["financials"]` → `required_data=[DataType.FINANCIALS]`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_data_types.py
from finagent.engine.data.types import DataType


def test_data_type_values():
    assert DataType.FINANCIALS == "financials"
    assert DataType.PRICE == "price"
    assert DataType.NEWS == "news"
    assert DataType.EARNINGS == "earnings"
    assert DataType.FILINGS == "filings"
    assert DataType.PROFILE == "profile"
    assert DataType.RAG_10K == "10k_rag"


def test_data_type_is_str():
    assert isinstance(DataType.FINANCIALS, str)
    assert f"type={DataType.FINANCIALS}" == "type=financials"


def test_data_type_comparison_with_str():
    assert DataType.FINANCIALS == "financials"
    assert "price" == DataType.PRICE
```

- [ ] **Step 2: Run test — expect FAIL (ModuleNotFoundError)**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinAgent && .venv/bin/pytest tests/unit/test_data_types.py -v`

- [ ] **Step 3: Create DataType enum**

```python
# finagent/engine/data/types.py
from enum import StrEnum


class DataType(StrEnum):
    """All valid data types in the FinAgent data layer.

    StrEnum ensures compile-time checking (typos caught by mypy/IDE)
    while remaining backwards-compatible with str comparisons.
    """

    FINANCIALS = "financials"
    PRICE = "price"
    NEWS = "news"
    EARNINGS = "earnings"
    FILINGS = "filings"
    PROFILE = "profile"
    RAG_10K = "10k_rag"
```

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Update interface.py signatures**

Add `from finagent.engine.data.types import DataType` and change:
- `DataResult.data_type: str` → `data_type: str | DataType`
- `DataProvider.fetch(data_type: str)` → `fetch(data_type: str | DataType)`
- `DataProvider.capabilities() -> list[str]` → `-> list[str | DataType]`

- [ ] **Step 6: Update all 4 providers**

Replace `_SUPPORTED = ["financials", "price", "news"]` with `_SUPPORTED = [DataType.FINANCIALS, DataType.PRICE, DataType.NEWS]` and all `data_type == "financials"` with `data_type == DataType.FINANCIALS` in yfinance/fmp/finnhub/sec providers.

- [ ] **Step 7: Update layer.py, cache.py, orchestrator.py, factory.py**

Replace string literals with DataType constants.

- [ ] **Step 8: Update PipelineStep.required_data and all pipeline definitions**

In `base.py`: `required_data: list[str] = ...` → `required_data: list[str | DataType] = ...`

In each pipeline file, replace string literals:
- `required_data=["financials", "price"]` → `required_data=[DataType.FINANCIALS, DataType.PRICE]`
- Add `from finagent.engine.data.types import DataType` import

Files: `equity_research.py`, `dcf.py`, `comps.py`, `lbo.py`, `earnings_analysis.py`, `ic_memo.py`

- [ ] **Step 9: Run full test suite**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinAgent && .venv/bin/pytest tests/unit/ -q --tb=short -k "not real"`
Expected: All pass (StrEnum == str, backwards compatible)

- [ ] **Step 10: Commit**

```bash
git add finagent/engine/data/types.py tests/unit/test_data_types.py \
  finagent/engine/data/interface.py finagent/engine/data/providers/ \
  finagent/engine/data/layer.py finagent/engine/data/cache.py \
  finagent/engine/orchestrator.py finagent/engine/agents/factory.py \
  finagent/engine/pipelines/
git commit -m "refactor(S3): replace data_type magic strings with DataType StrEnum

All providers, layer, cache, orchestrator, and pipeline definitions
now use typed DataType constants. StrEnum is backwards-compatible.

Closes S3-struct."
```

---

### Task 2: S4 — NormalizedFinancialKeys TypedDict (documentation-only)

**Scope note:** This task adds the canonical key documentation. Runtime enforcement (typing `data` as `NormalizedFinancialKeys` in extractor and providers) is deferred — it requires updating all provider normalization return types, which is a larger change.

**Files:**
- Create: `finagent/engine/data/keys.py`
- Create: `tests/unit/test_keys.py`
- Modify: `finagent/engine/compute/extractor.py` (import only)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_keys.py
from finagent.engine.data.keys import NormalizedFinancialKeys, REQUIRED_KEYS, OPTIONAL_KEYS


def test_required_keys_defined():
    assert "revenue" in REQUIRED_KEYS
    assert "ebitda" in REQUIRED_KEYS
    assert "market_cap" in REQUIRED_KEYS
    assert "current_price" in REQUIRED_KEYS


def test_optional_keys_defined():
    assert "depreciation_amortization" in OPTIONAL_KEYS
    assert "rd_expense" in OPTIONAL_KEYS
    assert "total_debt" in OPTIONAL_KEYS


def test_typed_dict_accepts_valid_data():
    data: NormalizedFinancialKeys = {
        "revenue": 1e9, "ebitda": 2e8, "net_income": 1e8,
        "market_cap": 5e9, "shares_outstanding": 1e8,
        "current_price": 50.0, "gross_margin": 0.4, "operating_margin": 0.15,
    }
    assert data["revenue"] == 1e9
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Create keys.py**

```python
# finagent/engine/data/keys.py
"""Canonical financial data keys that all providers must normalize to.

This documents the contract between providers and the extractor.
Runtime enforcement is not yet implemented — providers still return
untyped dicts. This file enables future mypy checking and serves
as the single source of truth for key names.
"""

from typing import TypedDict


class NormalizedFinancialKeys(TypedDict, total=False):
    """Keys that providers include in DataResult.data for data_type='financials'."""

    # Required (must be present and non-None)
    revenue: float
    ebitda: float
    net_income: float
    market_cap: float
    shares_outstanding: float
    current_price: float
    gross_margin: float
    operating_margin: float

    # Optional (None/missing = not available)
    total_debt: float | None
    total_cash: float | None
    pe_ratio: float | None
    depreciation_amortization: float | None
    rd_expense: float | None
    sga_expense: float | None
    interest_expense: float | None


REQUIRED_KEYS = frozenset({
    "revenue", "ebitda", "net_income", "market_cap",
    "shares_outstanding", "current_price", "gross_margin", "operating_margin",
})

OPTIONAL_KEYS = frozenset({
    "total_debt", "total_cash", "pe_ratio",
    "depreciation_amortization", "rd_expense", "sga_expense", "interest_expense",
})

ALL_KEYS = REQUIRED_KEYS | OPTIONAL_KEYS
```

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Add documentation import to extractor.py**

At top of `finagent/engine/compute/extractor.py`, add:
```python
from finagent.engine.data.keys import REQUIRED_KEYS  # noqa: F401 — documents expected keys
```

No behavior change. Run extractor tests to confirm.

- [ ] **Step 6: Commit**

```bash
git add finagent/engine/data/keys.py tests/unit/test_keys.py finagent/engine/compute/extractor.py
git commit -m "docs(S4): add NormalizedFinancialKeys TypedDict for provider-extractor contract

Documents canonical key names. Runtime enforcement deferred.

Closes S4-struct."
```

---

### Task 3: S1 — Split FinancialData God Object

**Strategy:** Add 4 sub-models (IncomeStatement, BalanceSheet, MarketData, ValuationMetrics). Rewrite FinancialData to compose them internally, with a `model_validator(mode='before')` that accepts BOTH flat kwargs (backwards compat) and structured sub-model kwargs (new style). No property delegation — fields stay as real Pydantic fields, the validator just routes flat kwargs into sub-models before Pydantic processes them.

**Files:**
- Modify: `finagent/engine/models/financial.py`
- Modify: `finagent/engine/compute/extractor.py`
- Create: `tests/unit/test_financial_models_split.py`
- Modify: `tests/unit/test_financial_models.py` — NO CHANGES NEEDED (flat kwargs still work via validator)
- Modify: `tests/unit/test_report_endpoints.py` — NO CHANGES NEEDED
- Modify: `tests/unit/test_data_processor.py` — NO CHANGES NEEDED
- Modify: `tests/unit/test_validators_v2.py` — NO CHANGES NEEDED

- [ ] **Step 1: Write the failing test for sub-models**

```python
# tests/unit/test_financial_models_split.py
from datetime import datetime, timezone
from pydantic import ValidationError
from finagent.engine.models.financial import (
    IncomeStatement, BalanceSheet, MarketData, ValuationMetrics, FinancialData,
)


def test_income_statement():
    stmt = IncomeStatement(
        revenue=1e9, ebitda=2e8, net_income=1e8,
        gross_margin=0.4, operating_margin=0.15,
    )
    assert stmt.revenue == 1e9


def test_balance_sheet_defaults():
    bs = BalanceSheet()
    assert bs.total_debt == 0
    assert bs.total_cash == 0


def test_market_data():
    md = MarketData(market_cap=5e9, shares_outstanding=1e8, current_price=50.0)
    assert md.current_price == 50.0


def test_valuation_metrics_defaults():
    vm = ValuationMetrics()
    assert vm.enterprise_value is None


def test_new_structured_constructor():
    """New code can construct with sub-models directly."""
    fd = FinancialData(
        ticker="AAPL",
        timestamp=datetime.now(tz=timezone.utc),
        income=IncomeStatement(
            revenue=1e9, ebitda=2e8, net_income=1e8,
            gross_margin=0.4, operating_margin=0.15,
        ),
        balance=BalanceSheet(total_debt=5e8, total_cash=2e8),
        market=MarketData(market_cap=5e9, shares_outstanding=1e8, current_price=50.0),
        valuation=ValuationMetrics(enterprise_value=5.3e9, ev_ebitda=26.5),
    )
    assert fd.revenue == 1e9
    assert fd.total_debt == 5e8
    assert fd.market_cap == 5e9
    assert fd.enterprise_value == 5.3e9


def test_flat_constructor_still_works():
    """Old code constructing with flat kwargs still works via model_validator."""
    fd = FinancialData(
        ticker="AAPL",
        timestamp=datetime.now(tz=timezone.utc),
        revenue=1e9, ebitda=2e8, net_income=1e8,
        gross_margin=0.4, operating_margin=0.15,
        market_cap=5e9, shares_outstanding=1e8, current_price=50.0,
        total_debt=5e8, total_cash=2e8,
    )
    assert fd.revenue == 1e9
    assert fd.income.revenue == 1e9
    assert fd.total_debt == 5e8
    assert fd.balance.total_debt == 5e8


def test_flat_constructor_validation_still_works():
    """Field validators on sub-models still fire from flat constructor."""
    with pytest.raises(ValidationError):
        FinancialData(
            ticker="AAPL",
            timestamp=datetime.now(tz=timezone.utc),
            revenue=1e9, ebitda=2e8, net_income=1e8,
            gross_margin=-0.1,  # should fail ge=0
            operating_margin=0.15,
            market_cap=5e9, shares_outstanding=1e8, current_price=50.0,
        )


def test_mutation_works():
    """Direct field mutation still works (frozen=False)."""
    fd = FinancialData(
        ticker="AAPL",
        timestamp=datetime.now(tz=timezone.utc),
        revenue=1e9, ebitda=2e8, net_income=1e8,
        gross_margin=0.4, operating_margin=0.15,
        market_cap=5e9, shares_outstanding=1e8, current_price=50.0,
    )
    fd.ev_ebitda = 25.0
    assert fd.ev_ebitda == 25.0
    # Also accessible via sub-model (in sync, not split-state)
    assert fd.valuation.ev_ebitda == 25.0


import pytest
```

- [ ] **Step 2: Run test — expect FAIL (ImportError: cannot import name 'IncomeStatement')**

- [ ] **Step 3: Implement sub-models and refactored FinancialData**

Add 4 sub-models above FinancialData in `financial.py`. Then rewrite FinancialData keeping ALL original fields as real Pydantic fields (not properties), but grouped into sub-models. The trick: `model_validator(mode='before')` intercepts flat kwargs and routes them to sub-model dicts.

```python
class IncomeStatement(BaseModel):
    """Income statement metrics."""
    revenue: float = Field(description="Annual revenue in USD")
    ebitda: float = Field(description="EBITDA in USD")
    net_income: float = Field(description="Net income in USD")
    gross_margin: float = Field(ge=0, le=1)
    operating_margin: float = Field(ge=-5, le=1)
    depreciation_amortization: float | None = None
    rd_expense: float | None = None
    sga_expense: float | None = None
    interest_expense: float | None = None


class BalanceSheet(BaseModel):
    """Balance sheet metrics."""
    total_debt: float = Field(default=0)
    total_cash: float = Field(default=0)


class MarketData(BaseModel):
    """Market and price data."""
    market_cap: float = Field(description="Market cap in USD")
    shares_outstanding: float = Field(gt=0)
    current_price: float = Field(gt=0)
    pe_ratio: float | None = None
    price_52w_high: float | None = None
    price_52w_low: float | None = None


class ValuationMetrics(BaseModel):
    """Derived valuation multiples. Computed by code, not LLM."""
    model_config = ConfigDict(frozen=False)
    enterprise_value: float | None = None
    ev_ebitda: float | None = None
    ev_revenue: float | None = None
```

FinancialData rewrite:

```python
class FinancialData(BaseModel):
    """Structured financial data for a single company.

    Composed of focused sub-models. Accepts both:
    - Structured: FinancialData(income=IncomeStatement(...), ...)
    - Flat (backwards compat): FinancialData(revenue=X, ebitda=Y, ...)
    """
    model_config = ConfigDict(frozen=False)

    ticker: str
    timestamp: datetime

    # Sub-models
    income: IncomeStatement
    balance: BalanceSheet = Field(default_factory=BalanceSheet)
    market: MarketData
    valuation: ValuationMetrics = Field(default_factory=ValuationMetrics)

    # Metadata
    data_source: str = "yfinance"
    warnings: list[str] = Field(default_factory=list)

    # --- Flat-field aliases for backwards compatibility ---
    # These are real Pydantic fields that stay in sync with sub-models
    # via the model_validator below.

    @model_validator(mode="before")
    @classmethod
    def _route_flat_kwargs(cls, data: Any) -> Any:
        """Accept flat kwargs and route them to sub-model dicts."""
        if not isinstance(data, dict):
            return data

        # If sub-models are already provided, pass through
        if "income" in data:
            return data

        # Route flat kwargs to sub-model dicts
        income_keys = {
            "revenue", "ebitda", "net_income", "gross_margin", "operating_margin",
            "depreciation_amortization", "rd_expense", "sga_expense", "interest_expense",
        }
        balance_keys = {"total_debt", "total_cash"}
        market_keys = {
            "market_cap", "shares_outstanding", "current_price", "pe_ratio",
            "price_52w_high", "price_52w_low",
        }
        valuation_keys = {"enterprise_value", "ev_ebitda", "ev_revenue"}

        income_data = {k: data.pop(k) for k in list(data) if k in income_keys}
        balance_data = {k: data.pop(k) for k in list(data) if k in balance_keys}
        market_data = {k: data.pop(k) for k in list(data) if k in market_keys}
        valuation_data = {k: data.pop(k) for k in list(data) if k in valuation_keys}

        if income_data:
            data["income"] = income_data
        if balance_data:
            data["balance"] = balance_data
        if market_data:
            data["market"] = market_data
        if valuation_data:
            data["valuation"] = valuation_data

        return data

    # --- Convenience accessors (read from sub-models) ---
    @property
    def revenue(self) -> float: return self.income.revenue
    @property
    def ebitda(self) -> float: return self.income.ebitda
    @property
    def net_income(self) -> float: return self.income.net_income
    @property
    def gross_margin(self) -> float: return self.income.gross_margin
    @property
    def operating_margin(self) -> float: return self.income.operating_margin
    @property
    def depreciation_amortization(self) -> float | None: return self.income.depreciation_amortization
    @property
    def rd_expense(self) -> float | None: return self.income.rd_expense
    @property
    def sga_expense(self) -> float | None: return self.income.sga_expense
    @property
    def interest_expense(self) -> float | None: return self.income.interest_expense
    @property
    def total_debt(self) -> float: return self.balance.total_debt
    @property
    def total_cash(self) -> float: return self.balance.total_cash
    @property
    def market_cap(self) -> float: return self.market.market_cap
    @property
    def shares_outstanding(self) -> float: return self.market.shares_outstanding
    @property
    def current_price(self) -> float: return self.market.current_price
    @property
    def pe_ratio(self) -> float | None: return self.market.pe_ratio
    @property
    def price_52w_high(self) -> float | None: return self.market.price_52w_high
    @property
    def price_52w_low(self) -> float | None: return self.market.price_52w_low
    @property
    def enterprise_value(self) -> float | None: return self.valuation.enterprise_value
    @property
    def ev_ebitda(self) -> float | None: return self.valuation.ev_ebitda
    @property
    def ev_revenue(self) -> float | None: return self.valuation.ev_revenue
```

**Critical: mutation support.** For fields that existing code mutates (ev_ebitda, ev_revenue, enterprise_value), add setters that write through to sub-models:

```python
    @ev_ebitda.setter
    def ev_ebitda(self, value: float | None) -> None:
        self.valuation.ev_ebitda = value

    @ev_revenue.setter
    def ev_revenue(self, value: float | None) -> None:
        self.valuation.ev_revenue = value

    @enterprise_value.setter
    def enterprise_value(self, value: float | None) -> None:
        self.valuation.enterprise_value = value
```

- [ ] **Step 4: Update extractor.py to use structured constructor**

Change `extract_financial_data()` return to use sub-models (new style):
```python
return FinancialData(
    ticker=ticker,
    timestamp=financials_result.timestamp,
    income=IncomeStatement(
        revenue=revenue, ebitda=ebitda or 0, net_income=data.get("net_income") or 0,
        gross_margin=data.get("gross_margin") or 0, operating_margin=data.get("operating_margin") or 0,
        depreciation_amortization=da, rd_expense=data.get("rd_expense"),
        sga_expense=data.get("sga_expense"), interest_expense=data.get("interest_expense"),
    ),
    balance=BalanceSheet(total_debt=total_debt, total_cash=total_cash),
    market=MarketData(
        market_cap=market_cap, shares_outstanding=data.get("shares_outstanding") or 1,
        current_price=current_price, pe_ratio=data.get("pe_ratio"),
        price_52w_high=high_52w, price_52w_low=low_52w,
    ),
    valuation=ValuationMetrics(enterprise_value=ev, ev_ebitda=ev_ebitda, ev_revenue=ev_revenue),
    data_source=financials_result.provider, warnings=warnings,
)
```

- [ ] **Step 5: Run new tests**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinAgent && .venv/bin/pytest tests/unit/test_financial_models_split.py -v`
Expected: All pass

- [ ] **Step 6: Run ALL existing tests — no changes to test files expected**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinAgent && .venv/bin/pytest tests/unit/ -q --tb=short -k "not real"`

Expected: All pass. The model_validator accepts flat kwargs, so:
- `test_financial_models.py::_base_financial_data()` — flat kwargs → routed to sub-models ✓
- `test_financial_models.py::test_financial_data_rejects_negative_gross_margin` — `gross_margin=-0.1` routed to IncomeStatement → ValidationError ✓
- `test_financial_models.py::test_financial_data_allows_mutation` — `fd.ev_ebitda = 25.0` → setter writes to valuation ✓
- `test_report_endpoints.py::_make_financial_data()` — flat kwargs ✓
- `test_data_processor.py::_make_financial_data()` — flat kwargs ✓
- `test_validators_v2.py::_make_fd()` — flat kwargs ✓

**If any test fails:** The model_validator has a bug. Fix the validator, not the test. The whole point is backwards compatibility.

- [ ] **Step 7: Commit**

```bash
git add finagent/engine/models/financial.py finagent/engine/compute/extractor.py \
  tests/unit/test_financial_models_split.py
git commit -m "refactor(S1): split FinancialData into IncomeStatement/BalanceSheet/MarketData/ValuationMetrics

model_validator(mode='before') routes flat kwargs to sub-models,
preserving full backwards compatibility. Setters for mutable
valuation fields prevent split-state bugs.

Closes S1-struct."
```

---

### Task 4: S2 — Type StepOutput.structured

**Files:**
- Modify: `finagent/engine/models/financial.py:209-213`
- Modify: `finagent/engine/pipelines/base.py`
- Create: `tests/unit/test_step_output_typed.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_step_output_typed.py
from pydantic import BaseModel
from finagent.engine.models.financial import StepOutput


class _FakeModel(BaseModel):
    value: float


def test_step_output_accepts_none():
    so = StepOutput(text="x")
    assert so.structured is None


def test_step_output_accepts_dict():
    so = StepOutput(text="x", structured={"key": "value"})
    assert so.structured == {"key": "value"}


def test_step_output_accepts_base_model():
    model = _FakeModel(value=42.0)
    so = StepOutput(text="x", structured=model)
    assert so.structured.value == 42.0


def test_step_output_structured_not_any():
    """The type annotation should not be Any."""
    from typing import get_type_hints, Any
    hints = get_type_hints(StepOutput)
    assert hints["structured"] is not Any
```

- [ ] **Step 2: Run test — expect test_step_output_structured_not_any FAILS**

- [ ] **Step 3: Change StepOutput.structured type**

```python
class StepOutput(BaseModel):
    """Wrapper for pipeline step output."""
    text: str
    structured: BaseModel | dict | None = None
```

- [ ] **Step 4: Update PipelineResult and _store_output types**

In `base.py`:
```python
class PipelineResult(BaseModel):
    steps: dict[str, str]
    structured_data: dict[str, BaseModel | dict] = Field(default_factory=dict)
    failed_validations: list[dict[str, str]] = Field(default_factory=list)

    def get_data(self, step_name: str) -> BaseModel | dict | None:
        return self.structured_data.get(step_name)
```

Update `_execute_step_once` return type: `StepOutput | str | Any` → `StepOutput | str`
Update `_store_output` parameter: `output: StepOutput | str | Any` → `output: StepOutput | str`

- [ ] **Step 5: Run tests**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinAgent && .venv/bin/pytest tests/unit/test_step_output_typed.py tests/unit/ -q --tb=short -k "not real"`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add finagent/engine/models/financial.py finagent/engine/pipelines/base.py \
  tests/unit/test_step_output_typed.py
git commit -m "refactor(S2): replace StepOutput.structured: Any with BaseModel | dict | None

Eliminates Any from pipeline data flow. PipelineResult also typed.

Closes S2-struct."
```

---

### Task 5: S5 — mypy Configuration

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add mypy to dev deps and config**

```toml
# Add to [project.optional-dependencies] dev list:
"mypy>=1.10",

# Append new section:
[tool.mypy]
python_version = "3.11"
warn_return_any = true
warn_unused_configs = true
disallow_any_generics = true
check_untyped_defs = true

[[tool.mypy.overrides]]
module = "finagent.*"
disallow_untyped_defs = true
warn_unreachable = true

[[tool.mypy.overrides]]
module = [
    "yfinance.*",
    "pydantic_ai.*",
    "rank_bm25.*",
    "openpyxl.*",
    "aiosqlite.*",
]
ignore_missing_imports = true
```

- [ ] **Step 2: Install and run mypy on full package**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinAgent && .venv/bin/pip install -e ".[dev]" && .venv/bin/mypy finagent/ --no-error-summary 2>&1 | head -50`

Expected: Some pre-existing errors may surface. **Do not fix them in this task** — document the count. The purpose of this task is to install and configure mypy, not fix all type errors. The S1-S4 changes above should be clean.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "infra(S5): add mypy config with per-package stub overrides

finagent.* gets strict checking. Third-party stubs configured.

Closes S5-infra."
```

---

### Task 6: S6 — SECURITY.md

**Files:**
- Create: `SECURITY.md`

- [ ] **Step 1: Create SECURITY.md**

```markdown
# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

1. **Do NOT open a public GitHub issue** for security vulnerabilities.
2. Open a [private security advisory](https://github.com/YOUR_ORG/finagent/security/advisories/new) on GitHub.
3. Include: description, reproduction steps, impact assessment.
4. We will acknowledge within 48 hours and provide a fix timeline within 7 days.

## Security Considerations

### API Key Management
- API keys are passed via environment variables or pydantic-settings.
- Keys are never logged, cached to disk, or included in error messages.
- `.env` is in `.gitignore`. Never commit API keys.

### Local Server
- FastAPI server binds to `127.0.0.1` by default (local-only).
- Do not expose to the internet without authentication middleware.
- `FINAGENT_HOST` controls the bind address.

### Data Cache
- Financial data cached in local SQLite (`finagent_cache.db`, gitignored).
- Contains market data, not credentials.

### LLM Data Flow
- Financial data is sent to the configured LLM provider for analysis.
- Review your LLM provider's data retention policy.
- No data is sent to services other than the configured LLM and data providers.
```

- [ ] **Step 2: Commit**

```bash
git add SECURITY.md
git commit -m "docs(S6): add SECURITY.md

Closes S6-infra."
```

---

### Task 7: S7 — Shared conftest.py

**Files:**
- Create: `tests/conftest.py`

**Scope note:** The shared conftest adds NEW fixtures for common patterns. Existing inline fixtures in `test_fmp_provider.py` and `test_finnhub_provider.py` (which capture sleep durations for rate-limiter assertions) are NOT migrated — they have different semantics than the shared `mock_sleep` and must stay local.

- [ ] **Step 1: Create tests/conftest.py**

```python
# tests/conftest.py
"""Shared test fixtures for FinAgent test suite."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def sample_financial_data_dict():
    """Canonical normalized financial data dict (as returned by providers)."""
    return {
        "revenue": 394_328_000_000,
        "ebitda": 130_541_000_000,
        "net_income": 96_995_000_000,
        "market_cap": 2_800_000_000_000,
        "shares_outstanding": 15_550_000_000,
        "current_price": 180.0,
        "gross_margin": 0.438,
        "operating_margin": 0.302,
        "total_debt": 111_088_000_000,
        "total_cash": 29_965_000_000,
        "pe_ratio": 28.87,
        "depreciation_amortization": 11_519_000_000,
        "rd_expense": 29_915_000_000,
        "sga_expense": 24_932_000_000,
        "interest_expense": 3_933_000_000,
    }


@pytest.fixture
def sample_price_data_dict():
    """Canonical price data dict (as returned by providers)."""
    return {
        "current_price": 180.0,
        "price_history": [
            {"close": 170.0}, {"close": 175.0}, {"close": 180.0},
            {"close": 195.0}, {"close": 150.0},
        ],
    }


@pytest.fixture
def now():
    """Deterministic timestamp for tests."""
    return datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def mock_sleep(monkeypatch):
    """Patch asyncio.sleep to be instant. For rate-limiter tests that need
    to capture sleep durations, keep the local fixture — do NOT use this one."""
    mock = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", mock)
    return mock
```

- [ ] **Step 2: Run all tests to verify conftest is picked up without conflicts**

Run: `cd /Users/zhunihaoyun/Desktop/code/FinAgent && .venv/bin/pytest tests/unit/ -q --tb=short -k "not real"`
Expected: All pass (new fixtures are additive)

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "infra(S7): add shared conftest.py with common test fixtures

Adds sample_financial_data_dict, sample_price_data_dict, now,
mock_sleep fixtures. Existing rate-limiter fixtures stay local.

Closes S7-infra."
```

---

## Final Verification

After all 7 tasks:

- [ ] **Full test suite:** `cd /Users/zhunihaoyun/Desktop/code/FinAgent && .venv/bin/pytest tests/unit/ -q --tb=short -k "not real"`
  Expected: 555+ pass (plus ~15 new tests)

- [ ] **Ruff:** `cd /Users/zhunihaoyun/Desktop/code/FinAgent && .venv/bin/ruff check finagent/`
  Expected: 0 warnings

- [ ] **Mypy on refactored files:** `cd /Users/zhunihaoyun/Desktop/code/FinAgent && .venv/bin/mypy finagent/engine/data/types.py finagent/engine/data/keys.py finagent/engine/models/financial.py finagent/engine/pipelines/base.py`
  Expected: 0 errors

- [ ] **No remaining magic strings:** `grep -rn '"financials"\|"price"\|"news"\|"earnings"\|"filings"\|"profile"\|"10k_rag"' finagent/engine/ | grep -v "types.py" | grep -v "test_"`
  Expected: 0 matches outside DataType enum

- [ ] **No remaining Any in pipeline:** `grep -rn ": Any" finagent/engine/models/ finagent/engine/pipelines/base.py`
  Expected: Only in model_validator parameter signature (required by Pydantic)
