# P2d — Beyond FinRobot (LBO + IC Memo + Earnings + Excel + RAG)

> **For agentic workers:** Use superpowers:subagent-driven-development to implement task-by-task. Mark each checkbox when done.

**Goal:** Exceed FinRobot's capabilities by adding LBO modeling, IC Memo pipeline, Earnings Analysis, Excel export, and SEC 10-K RAG — each with deterministic code that LLM cannot replicate.

**Architecture:** Five parallel tracks, executed sequentially. Each track produces independently testable output.

**Tech Stack additions:** `openpyxl` (Excel), `rank-bm25` (BM25 keyword search for RAG). No embedding models — keeps install size under 50MB.

**Financial references:** Rosenbaum & Pearl *Investment Banking* (LBO formulas), CFA Level II (earnings analysis), EDGAR full-text search API (10-K retrieval).

---

## File Map

| File | Action | Track |
|------|--------|-------|
| `finagent/engine/models/financial.py` | Modify | LBO, Earnings |
| `finagent/engine/compute/lbo.py` | Create | LBO |
| `finagent/engine/pipelines/lbo.py` | Create | LBO |
| `finagent/engine/reports/templates/lbo.html` | Create | LBO |
| `finagent/engine/compute/earnings.py` | Create | Earnings |
| `finagent/engine/data/providers/fmp_provider.py` | Modify | Earnings |
| `finagent/engine/pipelines/earnings_analysis.py` | Create | Earnings |
| `finagent/engine/reports/templates/earnings.html` | Create | Earnings |
| `finagent/engine/pipelines/ic_memo.py` | Create | IC Memo |
| `finagent/engine/reports/templates/ic_memo.html` | Create | IC Memo |
| `finagent/engine/compute/spreadsheet_gen.py` | Create | Excel |
| `finagent/server.py` | Modify | Excel, RAG |
| `finagent/engine/compute/rag.py` | Create | RAG |
| `finagent/engine/data/providers/sec_provider.py` | Modify | RAG |
| `tests/unit/test_lbo.py` | Create | LBO |
| `tests/unit/test_earnings.py` | Create | Earnings |
| `tests/unit/test_spreadsheet_gen.py` | Create | Excel |
| `tests/unit/test_rag.py` | Create | RAG |
| `pyproject.toml` | Modify | All (add openpyxl, rank-bm25) |

---

## Track 1: LBO Compute Core

### Task 1: Models — `LBOInputs`, `LBOYear`, `LBOResult`

**File:** `finagent/engine/models/financial.py` (append)

**What LLM can't do:** Deterministic IRR from a multi-year cash flow schedule. LLM would hallucinate returns and debt paydown arithmetic. Newton-Raphson on NPV=0 must be in code.

```python
class LBOInputs(BaseModel):
    """Assumptions driving the LBO model."""
    ticker: str
    ltm_ebitda: float              # LTM EBITDA at entry (USD)
    entry_ev_ebitda: float         # Entry EV/EBITDA multiple
    exit_ev_ebitda: float          # Exit EV/EBITDA multiple
    holding_period_years: int = 5  # Typical PE hold = 3–7 years
    revenue_base: float            # LTM revenue at entry
    revenue_growth_rate: float     # Annual revenue growth (constant)
    ebitda_margin: float           # EBITDA/revenue (constant — conservative)
    da_pct_revenue: float = 0.04   # D&A as % of revenue
    capex_pct_revenue: float = 0.04
    nwc_change_pct_revenue: float = 0.01  # ΔNWC per unit of revenue change
    leverage_multiple: float = 5.0  # Total debt / EBITDA at entry
    interest_rate: float = 0.07    # Blended debt rate
    mandatory_amort_pct: float = 0.01  # 1% mandatory TLB amortization / year
    cash_sweep: bool = True        # Sweep all excess FCF to debt
    tax_rate: float = 0.25

class LBOYear(BaseModel):
    """One year of LBO operations."""
    year: int
    revenue: float
    ebitda: float
    da: float
    ebit: float
    interest_expense: float
    ebt: float
    taxes: float
    net_income: float
    capex: float
    delta_nwc: float
    fcf: float                     # Cash available for debt service
    mandatory_amort: float
    cash_sweep_amount: float
    total_debt_paydown: float
    ending_debt: float

class LBOResult(BaseModel):
    """Full LBO model output."""
    entry_ev: float
    entry_debt: float
    entry_equity: float
    schedule: list[LBOYear]        # One entry per holding year
    exit_ebitda: float
    exit_ev: float
    exit_equity: float
    moic: float
    irr: float                     # Annualized IRR (decimal, e.g. 0.22 = 22%)
    sensitivity: dict[str, list]   # entry_multiples, exit_multiples, irr_grid, moic_grid
```

---

### Task 2: `compute/lbo.py`

**File:** `finagent/engine/compute/lbo.py` (create)

**Formulas (Rosenbaum & Pearl, Ch. 8):**

```
Entry EV = entry_ev_ebitda × ltm_ebitda
Entry Debt = leverage_multiple × ltm_ebitda
Entry Equity = Entry EV − Entry Debt

Year i operations:
  Revenue_i = Revenue_{i-1} × (1 + revenue_growth_rate)
  EBITDA_i  = Revenue_i × ebitda_margin
  D&A_i     = Revenue_i × da_pct_revenue
  EBIT_i    = EBITDA_i − D&A_i
  Interest_i = Debt_{beginning,i} × interest_rate
  EBT_i     = EBIT_i − Interest_i
  Taxes_i   = max(EBT_i × tax_rate, 0)   # No negative taxes
  NetInc_i  = EBT_i − Taxes_i
  CapEx_i   = Revenue_i × capex_pct_revenue
  ΔNWC_i   = (Revenue_i − Revenue_{i-1}) × nwc_change_pct_revenue
  FCF_i     = NetInc_i + D&A_i − CapEx_i − ΔNWC_i
  MandAmort_i = Entry Debt × mandatory_amort_pct
  Sweep_i   = max(FCF_i − MandAmort_i, 0) if cash_sweep else 0
  Paydown_i = min(MandAmort_i + Sweep_i, Debt_{beginning,i})
  Debt_{end,i} = Debt_{beginning,i} − Paydown_i

Exit (year = holding_period):
  Exit EBITDA = EBITDA_{holding_period}
  Exit EV     = exit_ev_ebitda × Exit EBITDA
  Exit Equity = Exit EV − Debt_{end,holding_period}

MOIC = Exit Equity / Entry Equity
IRR  = (Exit_Equity / Entry_Equity)^(1/n) - 1   ← closed-form, no external deps
       If Exit_Equity ≤ 0 or Entry_Equity ≤ 0: IRR = -1.0 (total loss)
       Valid for single hold-to-exit cash flow (no interim dividends).

Sensitivity grid:
  entry_range = [entry_ev_ebitda - 1.5, ..., entry_ev_ebitda + 1.5] step 0.5
  exit_range  = [exit_ev_ebitda - 2.0, ..., exit_ev_ebitda + 2.0] step 0.5
  For each (e_entry, e_exit): run calculate_lbo() with overrides, collect IRR/MOIC
```

**Function signatures:**
```python
def calculate_lbo(inputs: LBOInputs) -> LBOResult: ...
def _run_schedule(inputs: LBOInputs) -> tuple[list[LBOYear], float, float]: ...
    # returns (schedule, exit_ebitda, exit_equity)
def _compute_irr(entry_equity: float, exit_equity: float, years: int) -> float: ...
def calculate_lbo_sensitivity(
    inputs: LBOInputs,
    entry_range: list[float] | None = None,
    exit_range: list[float] | None = None,
) -> dict[str, list]: ...
```

**Test file:** `tests/unit/test_lbo.py`

Reference case (manual calculation):
```
ltm_ebitda = 100, entry_ev_ebitda = 8.0, exit_ev_ebitda = 10.0
leverage_multiple = 5.0, holding_period = 5, revenue_base = 500
revenue_growth = 0.05, ebitda_margin = 0.20, da_pct = 0.04
capex_pct = 0.04, nwc_pct = 0.01, interest = 0.07, amort = 0.01, tax = 0.25

Entry: EV=800, Debt=500, Equity=300

Year 1: Rev=525, EBITDA=105, DA=21, EBIT=84, Interest=500×0.07=35,
        EBT=49, Tax=12.25, NetInc=36.75, CapEx=21, ΔNWC=0.25,
        FCF=36.75+21-21-0.25=36.5
        Amort=5, Sweep=31.5, Paydown=36.5, Debt_end=463.5

Year 5 (approximate, debt ~250):
  Equity_exit ≈ Exit_EV - Remaining_Debt > 300
  MOIC > 2.0×, IRR > 0.15
```

Tests must assert:
- `result.entry_ev == pytest.approx(800)` (unit inputs: ltm_ebitda=100, entry_ev_ebitda=8.0)
- `result.entry_debt == pytest.approx(500)`
- `result.entry_equity == pytest.approx(300)`
- `result.schedule[0].interest_expense == pytest.approx(35.0)`
- `result.schedule[0].fcf == pytest.approx(36.5)`
- `result.moic > 2.0`
- `0.15 < result.irr < 0.40`
- `len(result.schedule) == 5`
- Test `irr_total_loss`: exit_equity ≤ 0 → `result.irr == -1.0`
- Test sensitivity: `len(result.sensitivity["irr_grid"]) == len(result.sensitivity["entry_multiples"])`

**Step 1:** Write failing tests in `test_lbo.py`
**Step 2:** Create `LBOInputs`, `LBOYear`, `LBOResult` in `models/financial.py`
**Step 3:** Implement `compute/lbo.py`
**Step 4:** All tests pass

- [ ] Step 1: Write test_lbo.py with all assertions above
- [ ] Step 2: Add LBO models to financial.py
- [ ] Step 3: Implement compute/lbo.py
- [ ] Step 4: Tests pass (`pytest tests/unit/test_lbo.py -v`)

---

### Task 3: LBO Pipeline — `pipelines/lbo.py`

**File:** `finagent/engine/pipelines/lbo.py` (create)

4 pipeline steps:

| Step | Name | execute_fn | Required data |
|------|------|------------|---------------|
| 1 | `data_collection` | None | `["financials", "price"]` |
| 2 | `lbo_parameters` | `_execute_lbo_params` | prior steps |
| 3 | `lbo_calculation` | `_execute_lbo_calc` | prior steps |
| 4 | `lbo_narrative` | None | prior steps |

```python
async def _execute_lbo_params(agent, deps, prompt, structured_context, ticker):
    """LLM selects LBOInputs assumptions from financial data."""
    param_agent = Agent(deps.settings.model_name, output_type=LBOInputs, ...)
    try:
        result = await param_agent.run(prompt, deps=deps)
        return StepOutput(text=result.output.model_dump_json(), structured=result.output)
    except (AgentRunError, ValidationError, ValueError) as e:
        raise ValueError(f"LLM failed to produce valid LBO parameters: {e}") from e

async def _execute_lbo_calc(agent, deps, prompt, structured_context, ticker):
    """Deterministic LBO calculation from LBOInputs."""
    inputs = structured_context.get("lbo_parameters")
    if not isinstance(inputs, LBOInputs):
        raise ValueError("lbo_parameters step must produce LBOInputs")
    result = calculate_lbo(inputs)
    sensitivity = calculate_lbo_sensitivity(inputs)
    result = result.model_copy(update={"sensitivity": sensitivity})
    narrative = (
        f"LBO implies {result.moic:.1f}× MOIC and {result.irr:.1%} IRR over "
        f"{inputs.holding_period_years} years. Entry equity: ${result.entry_equity/1e6:.0f}M, "
        f"Exit equity: ${result.exit_equity/1e6:.0f}M."
    )
    return StepOutput(text=narrative, structured=result)
```

Validators:
- Step 2: `validate_lbo_inputs` — checks `entry_ev_ebitda > 0`, `leverage_multiple < 12`
- Step 3: `validate_lbo_result` — checks `moic > 0`, `-1.0 ≤ irr ≤ 10.0`

Add to `validators.py`:
```python
def validate_lbo_inputs(data: LBOInputs) -> ValidationResult: ...
def validate_lbo_result(data: LBOResult) -> ValidationResult: ...
```

Register in orchestrator (same pattern as `run_dcf_valuation`):
```python
async def run_lbo_analysis(ticker: str, ctx: RunContext[FinAgentDeps]) -> str:
    pipeline = build_lbo_pipeline()
    result = await pipeline.execute(ctx.deps, ticker)
    ctx.deps.report_cache[ticker.upper()] = build_report_context(ticker, result)
    return result.format_summary()
```

- [ ] Step 1: Write pipeline steps and execute_fn functions in lbo.py
- [ ] Step 2: Add validators to validators.py
- [ ] Step 3: Register run_lbo_analysis in orchestrator.py
- [ ] Step 4: Add LBO report template (lbo.html) — mirror DCF template structure

---

## Track 2: Earnings Analysis

### Task 4: FMP `earnings` capability

**File:** `finagent/engine/data/providers/fmp_provider.py` (modify)

Add to `capabilities()`: `"earnings"`

New endpoint: `/earnings-surprises/{ticker}` returns list of:
```json
[{"date": "2024-10-31", "symbol": "AAPL", "epsActual": 1.64, "epsEstimated": 1.60,
  "revenueActual": 94930000000, "revenueEstimated": 94210000000}]
```

Normalized output: `DataResult.data["earnings_history"]` = list of dicts with keys:
- `date`, `eps_actual`, `eps_estimated`, `revenue_actual`, `revenue_estimated`

- [ ] Add `earnings` to `_fetch_earnings()` method and `capabilities()`
- [ ] Add tests to `test_fmp_provider.py`: `TestFMPEarnings.test_fetch_earnings_returns_normalized_keys`

---

### Task 5: `compute/earnings.py`

**File:** `finagent/engine/compute/earnings.py` (create)

**What LLM can't do:** Deterministic beat/miss classification with surprise magnitude. LLM would inconsistently classify "inline" vs "beat". Code enforces exact thresholds from consensus research (Livnat & Mendenhall 2006: ≥ 2% surprise = statistically significant beat).

```python
from enum import Enum

class SurpriseDirection(str, Enum):
    BEAT = "beat"
    MISS = "miss"
    INLINE = "inline"

class EarningsSurprise(BaseModel):
    date: str
    eps_actual: float
    eps_estimated: float
    eps_surprise_pct: float        # (actual - est) / |est| × 100
    eps_direction: SurpriseDirection
    revenue_actual: float
    revenue_estimated: float
    revenue_surprise_pct: float
    revenue_direction: SurpriseDirection

class EarningsResult(BaseModel):
    ticker: str
    surprises: list[EarningsSurprise]
    beat_rate: float               # % of quarters with EPS beat (trailing N)
    avg_eps_surprise_pct: float
    avg_revenue_surprise_pct: float
    consecutive_beats: int         # Current consecutive beat streak
```

**Formulas:**
```
eps_surprise_pct = (eps_actual - eps_estimated) / abs(eps_estimated) × 100
  if eps_estimated == 0: surprise_pct = 0.0

direction:
  > +2.0%  → BEAT
  < -2.0%  → MISS
  else     → INLINE

beat_rate = count(eps_direction == BEAT) / len(surprises)
consecutive_beats = count from most recent backwards until first non-BEAT
```

**Test file:** `tests/unit/test_earnings.py`

Numeric test case:
```
eps_actual=1.64, eps_estimated=1.60
→ surprise = (1.64-1.60)/1.60 × 100 = 2.5% → BEAT

eps_actual=1.55, eps_estimated=1.60
→ surprise = (1.55-1.60)/1.60 × 100 = -3.125% → MISS

eps_actual=1.61, eps_estimated=1.60
→ surprise = 0.625% → INLINE

beat_rate for [BEAT, BEAT, MISS, BEAT, INLINE] = 3/5 = 0.6
consecutive_beats for [BEAT, BEAT, MISS, BEAT] (most recent first) = 1
```

```python
def calculate_earnings_surprises(ticker: str, earnings_history: list[dict]) -> EarningsResult: ...
def _classify_surprise(pct: float) -> SurpriseDirection: ...
def _count_consecutive_beats(surprises: list[EarningsSurprise]) -> int: ...
```

- [ ] Step 1: Write test_earnings.py with assertions for all 3 surprise cases + beat_rate + consecutive_beats
- [ ] Step 2: Add EarningsSurprise, EarningsResult to models/financial.py
- [ ] Step 3: Implement compute/earnings.py
- [ ] Step 4: Tests pass

---

### Task 6: Earnings Analysis Pipeline — `pipelines/earnings_analysis.py`

4 steps:

| Step | Name | execute_fn | Note |
|------|------|------------|------|
| 1 | `earnings_data` | `_execute_earnings_data` | Fetches + calculates EarningsResult |
| 2 | `financial_context` | None | Fetches financials for trend context |
| 3 | `earnings_analysis` | None | LLM interprets patterns |
| 4 | `forward_outlook` | None | LLM generates earnings outlook |

```python
async def _execute_earnings_data(agent, deps, prompt, structured_context, ticker):
    earnings_result = await deps.data_layer.fetch("earnings", ticker)
    history = earnings_result.data.get("earnings_history", [])
    calculated = calculate_earnings_surprises(ticker, history)
    text = (
        f"Beat rate: {calculated.beat_rate:.0%}. "
        f"Avg EPS surprise: {calculated.avg_eps_surprise_pct:+.1f}%. "
        f"Consecutive beats: {calculated.consecutive_beats}."
    )
    return StepOutput(text=text, structured=calculated)
```

- [ ] Implement pipelines/earnings_analysis.py
- [ ] Add run_earnings_analysis tool to orchestrator.py
- [ ] Add earnings.html report template

---

## Track 3: IC Memo Pipeline

### Task 7: `pipelines/ic_memo.py`

**What makes IC Memo distinct from equity_research:** IC Memo is an investment committee recommendation document with explicit IRR/MOIC targets, risk factors table, and a binary Invest/Pass recommendation. It runs both DCF and LBO pipelines internally and synthesizes them.

5 steps:

| Step | Name | execute_fn | Note |
|------|------|------------|------|
| 1 | `situation_overview` | None | Company overview + transaction rationale |
| 2 | `financial_analysis` | `_execute_ic_financials` | Runs DCF + LBO inline, returns both results |
| 3 | `investment_thesis` | None | LLM articulates 3-5 key investment considerations |
| 4 | `risk_factors` | `_execute_risk_factors` | LLM generates + code ranks risks |
| 5 | `recommendation` | `_execute_recommendation` | LLM verdict + code validates IRR ≥ threshold |

```python
async def _execute_ic_financials(agent, deps, prompt, structured_context, ticker):
    """Runs DCF and LBO calculations, returns ICFinancials with both results."""
    # Re-use: extract data → run both models → combine
    financials = await deps.data_layer.fetch("financials", ticker)
    price = await deps.data_layer.fetch("price", ticker)
    financial_data = extract_financial_data(financials, price)

    # DCF: use param_agent same as dcf pipeline
    dcf_result = ... (same as _execute_dcf_calc)

    # LBO: use param_agent for LBOInputs, then calculate_lbo
    lbo_inputs = ... (same as _execute_lbo_params)
    lbo_result = calculate_lbo(lbo_inputs)

    combined = ICFinancials(
        financial_data=financial_data,
        dcf_result=dcf_result,
        lbo_result=lbo_result,
    )
    text = (
        f"DCF: ${dcf_result.implied_price:.2f}/share. "
        f"LBO: {lbo_result.moic:.1f}× MOIC, {lbo_result.irr:.1%} IRR."
    )
    return StepOutput(text=text, structured=combined)

class ICFinancials(BaseModel):
    """Combined DCF + LBO results for IC Memo."""
    financial_data: FinancialData
    dcf_result: DCFResult
    lbo_result: LBOResult

async def _execute_recommendation(agent, deps, prompt, structured_context, ticker):
    """LLM verdict, but code enforces: IRR < 15% → can only recommend Pass."""
    ic_financials = structured_context.get("financial_analysis")
    step_result = await agent.run(prompt, deps=deps)
    # Code gate: if IRR < 15%, override to Pass
    if isinstance(ic_financials, ICFinancials):
        irr = ic_financials.lbo_result.irr
        if irr < 0.15:
            return StepOutput(
                text=f"[Code gate: IRR {irr:.1%} < 15% minimum hurdle. Recommendation: PASS]\n"
                     + step_result.output,
                structured=None,
            )
    return StepOutput(text=step_result.output, structured=None)
```

Add `ICFinancials` to `models/financial.py`.

- [ ] Add ICFinancials model to models/financial.py
- [ ] Implement pipelines/ic_memo.py
- [ ] Add run_ic_memo tool to orchestrator.py
- [ ] Add ic_memo.html report template (4 sections: Situation, Financial Summary, Investment Thesis, Risks + Recommendation)

---

## Track 4: Excel Output (`spreadsheet_gen`)

### Task 8: `compute/spreadsheet_gen.py`

**What LLM can't do:** Generate a binary `.xlsx` file with formula cells, frozen panes, conditional formatting, and multi-sheet structure. LLM can output CSV at most.

**Dependency:** Add `openpyxl>=3.1` to `pyproject.toml` under `[project.dependencies]`.

**Function signatures:**
```python
def generate_dcf_excel(dcf_result: DCFResult, dcf_inputs: DCFInputs) -> bytes:
    """Return raw .xlsx bytes for a DCF model workbook."""

def generate_lbo_excel(lbo_result: LBOResult, lbo_inputs: LBOInputs) -> bytes:
    """Return raw .xlsx bytes for an LBO model workbook."""

def generate_comps_excel(peers: list[CompanyFinancials]) -> bytes:
    """Return raw .xlsx bytes for a comparable companies table."""
```

**DCF workbook structure (3 sheets):**
- `Summary`: Key outputs — implied price, WACC, EV, IRR range from sensitivity
- `Projections`: Year-by-year Revenue / EBITDA / FCF table with formatted numbers
- `Sensitivity`: WACC × TG sensitivity table with conditional formatting
  - Green: implied price > current price × 1.1
  - Red: implied price < current price × 0.9
  - Yellow: in between

**LBO workbook structure (3 sheets):**
- `Summary`: Entry/Exit assumptions, MOIC, IRR
- `Debt Schedule`: Year-by-year EBITDA, FCF, debt paydown, ending debt
- `Sensitivity`: Entry × Exit multiple grid for IRR (conditional format: green > 20%, red < 15%)

**Formatting rules:**
- All USD values: `"$#,##0"` format
- All percentages: `"0.0%"` format
- All multiples: `"0.0x"` format
- Header row: bold, fill color `#1a365d` (same as chart primary color), white font
- Freeze panes at row 2 (below header) on all sheets

**Test file:** `tests/unit/test_spreadsheet_gen.py`

Tests must verify:
```python
def test_generate_dcf_excel_returns_valid_xlsx():
    """Output is a valid .xlsx file parseable by openpyxl."""
    from finagent.engine.compute.spreadsheet_gen import generate_dcf_excel
    from finagent.engine.models.financial import DCFInputs, DCFResult
    from finagent.engine.compute.dcf import calculate_dcf
    import openpyxl, io

    inputs = DCFInputs(...)  # minimal valid inputs
    result = calculate_dcf(inputs)
    xlsx_bytes = generate_dcf_excel(result, inputs)

    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
    assert "Summary" in wb.sheetnames
    assert "Projections" in wb.sheetnames
    assert "Sensitivity" in wb.sheetnames

def test_generate_lbo_excel_has_debt_schedule():
    ...
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
    ws = wb["Debt Schedule"]
    assert ws.max_row == inputs.holding_period_years + 1  # header + N years

def test_dcf_excel_sensitivity_sheet_has_correct_dimensions():
    # Sensitivity table: rows = len(wacc_range), cols = len(tg_range)
    ...
```

**API endpoint** — add to `server.py`:
```python
@app.get("/api/export/excel/{analysis_type}/{ticker}")
async def export_excel(analysis_type: str, ticker: str, request: Request):
    """Download .xlsx for analysis_type in {'dcf', 'lbo', 'comps'}."""
    cache = request.app.state.deps.report_cache.get(ticker.upper())
    if cache is None:
        raise HTTPException(status_code=404, detail="Run analysis first")
    # extract result from cache, call appropriate generate_*_excel()
    ...
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={ticker}_{analysis_type}.xlsx"},
    )
```

**Desktop:** Add "Export Excel" button to `DCFView.tsx` and `LBOView.tsx` (new component).

- [ ] Add `openpyxl>=3.1` to pyproject.toml
- [ ] Write test_spreadsheet_gen.py with all 3 test functions
- [ ] Implement compute/spreadsheet_gen.py
- [ ] Add /api/export/excel endpoint to server.py
- [ ] Tests pass

---

## Track 5: SEC 10-K RAG

### Task 9: `compute/rag.py` — BM25 keyword search

**What LLM can't do:** Deterministic passage retrieval from a 100-page 10-K filing. LLM would hallucinate passages; BM25 retrieves the actual text at a specific rank position.

**Why BM25 over embeddings:** No 80MB model download, no inference latency, deterministic results, easily testable. Upgrade path to embeddings is straightforward (same interface, different scorer).

**Dependency:** Add `rank-bm25>=0.2.2` to `pyproject.toml`.

```python
from dataclasses import dataclass
from rank_bm25 import BM25Okapi

@dataclass
class Chunk:
    text: str
    source: str          # e.g. "10-K/2024/MD&A"
    chunk_index: int
    char_start: int

class BM25Index:
    """BM25 index over text chunks. Deterministic, no external model."""

    def __init__(self, chunks: list[Chunk]) -> None:
        self._chunks = chunks
        tokenized = [c.text.lower().split() for c in chunks]
        self._bm25 = BM25Okapi(tokenized)

    def search(self, query: str, top_k: int = 5) -> list[tuple[Chunk, float]]:
        """Return top_k chunks by BM25 score, descending."""
        scores = self._bm25.get_scores(query.lower().split())
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        return [(self._chunks[i], float(s)) for i, s in ranked[:top_k] if s > 0]

def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[Chunk]:
    """Split text into overlapping word-chunks.

    What this code does that raw LLM cannot: deterministic chunking with
    controlled overlap so no sentence is stranded at a chunk boundary.
    chunk_size and overlap are in words, not characters.
    """
    words = text.split()
    chunks: list[Chunk] = []
    # Build a cumulative char-offset map: offset[i] = start of words[i] in text
    offsets: list[int] = []
    pos = 0
    for w in words:
        pos = text.find(w, pos)
        offsets.append(pos)
        pos += len(w)
    i = 0
    while i < len(words):
        chunk_words = words[i : i + chunk_size]
        text_slice = " ".join(chunk_words)
        char_start = offsets[i] if i < len(offsets) else 0
        chunks.append(Chunk(text=text_slice, source="", chunk_index=len(chunks), char_start=char_start))
        i += chunk_size - overlap
    return chunks
```

**Test file:** `tests/unit/test_rag.py`

```python
def test_chunk_text_correct_count():
    # 1000 words, chunk_size=100, overlap=10 → ceil(1000/90) = ~12 chunks
    text = " ".join(["word"] * 1000)
    chunks = chunk_text(text, chunk_size=100, overlap=10)
    assert len(chunks) >= 10

def test_bm25_index_retrieves_relevant_chunk():
    """Chunk containing 'liquidity risk' must rank higher for that query."""
    chunks = [
        Chunk(text="The company faces market risk from interest rates.", source="risk", chunk_index=0, char_start=0),
        Chunk(text="Liquidity risk arises from inability to meet obligations.", source="risk", chunk_index=1, char_start=0),
        Chunk(text="Revenue increased 12% year over year.", source="ops", chunk_index=2, char_start=0),
    ]
    index = BM25Index(chunks)
    results = index.search("liquidity risk")
    assert results[0][0].chunk_index == 1

def test_bm25_returns_empty_for_zero_score_query():
    """Query with no matching terms returns empty list."""
    ...

def test_chunk_overlap_prevents_stranded_words():
    """Last chunk must contain at least overlap words from second-to-last chunk."""
    ...
```

---

### Task 10: SEC provider RAG integration

**File:** `finagent/engine/data/providers/sec_provider.py` (modify)

Current state: Fetches 10-K metadata + MD&A text (N3 fix). Returns `DataResult.data["mdna_text"]`.

Add new capability: `"10k_rag"` — returns a pre-built BM25Index as an opaque object in `DataResult.data["rag_index"]`.

```python
async def _fetch_10k_rag(self, ticker: str) -> DataResult:
    """Fetch 10-K MD&A + build BM25 index for RAG queries.

    Calls fetch(ticker, "filings") to reuse the existing 10-K fetch path
    (which returns DataResult with mdna_text). Cannot call _fetch_filings
    directly — it returns tuple[dict, list[str]], not DataResult.
    """
    base_result = await self.fetch(ticker, "filings")
    mdna_text = base_result.data.get("mdna_text", "")
    if not mdna_text:
        return base_result  # No text, no index
    chunks = chunk_text(mdna_text, chunk_size=300, overlap=30)
    for chunk in chunks:
        chunk.source = f"10-K/MD&A/{ticker}"
    rag_index = BM25Index(chunks)
    return DataResult(
        data={**base_result.data, "rag_index": rag_index, "chunk_count": len(chunks)},
        provider="sec_edgar",
        ticker=ticker,
        data_type="10k_rag",
        timestamp=base_result.timestamp,
    )
```

**Equity Research integration** — modify Step 1 in `equity_research.py`:

When `"10k_rag"` is available in DataLayer, fetch it. Extract top 3 relevant passages for "risk factors" and "business overview" queries. Prepend them to the step 1 prompt as `[SEC 10-K Context]`.

```python
async def _execute_data_collection(agent, deps, prompt, structured_context, ticker):
    # ... existing code ...
    # NEW: try to get RAG passages
    rag_context = ""
    try:
        rag_result = await deps.data_layer.fetch("10k_rag", ticker)
        index: BM25Index = rag_result.data["rag_index"]
        risk_passages = index.search("risk factors material adverse", top_k=2)
        biz_passages = index.search("business overview revenue growth", top_k=2)
        passages = risk_passages + biz_passages
        rag_context = "\n\n".join(
            f"[10-K passage, score={s:.2f}]: {c.text[:300]}" for c, s in passages
        )
    except (ProviderError, KeyError):
        pass  # SEC data optional — don't fail equity research
    ...
```

- [ ] Add `rank-bm25>=0.2.2` to pyproject.toml
- [ ] Write test_rag.py with all 4 test functions
- [ ] Implement compute/rag.py
- [ ] Add `10k_rag` capability to sec_provider.py — two places:
  1. Add `"10k_rag"` to `_SUPPORTED` (or equivalent capability list)
  2. Add routing in `fetch()` dispatch: `elif data_type == "10k_rag": return await self._fetch_10k_rag(ticker)`
- [ ] Wire RAG context into equity_research step 1
- [ ] Tests pass

---

## BACKLOG.md Updates

When implementation is complete, update `BACKLOG.md` P2d section:

```markdown
## P2d: 超越 FinRobot（新增管线 + Excel 输出）
- [x] LBO pipeline + compute/lbo.py
- [x] IC Memo pipeline
- [x] Earnings Analysis pipeline
- [x] spreadsheet_gen（openpyxl Excel 输出）
- [x] SEC 10-K 深度解析 + RAG
```

---

## Defect Pre-Register

Known risks to watch during P2d implementation:

| ID | Risk | Mitigation |
|----|------|------------|
| D1 | ~~`scipy.optimize.brentq`~~ (resolved) | Closed-form IRR `(exit/entry)^(1/n)-1` used — no scipy, no edge cases |
| D2 | LBO with negative exit equity: IRR formula returns NaN | Check `exit_equity <= 0` before computing, return -1.0 |
| D3 | FMP `earnings-surprises` endpoint returns empty for small-cap tickers | Graceful fallback: EarningsResult with empty surprises list, beat_rate=0.0 |
| D4 | openpyxl chart objects complicate xlsx validation | Do NOT use openpyxl chart objects (they're buggy) — only data tables with conditional formatting |
| D5 | BM25 on very short MD&A text (< 50 words) | chunk_text must handle edge case: return single chunk if text too short |
| D6 | IC Memo runs two LLM agents per step — doubles cost | Document in docstring. Do not optimize prematurely. |

For D1: implement `_compute_irr` without scipy:

```python
def _compute_irr(entry_equity: float, exit_equity: float, years: int) -> float:
    """Closed-form IRR for single hold-to-exit cash flow. No external dependencies.

    Solves: entry_equity = exit_equity / (1+r)^years
    → r = (exit_equity / entry_equity)^(1/years) - 1
    """
    if exit_equity <= 0 or entry_equity <= 0:
        return -1.0
    return (exit_equity / entry_equity) ** (1.0 / years) - 1.0
```

This is the closed-form solution for a single cash flow (no interim dividends). Accurate for simple hold-to-exit LBO with full exit at year N.

---

## Open Questions (Must Answer Before Implementation)

**Q1:** IC Memo `_execute_ic_financials` runs two LLM param_agents in sequence (DCF + LBO). If one fails, does the whole step fail? **Proposed answer:** Yes — both are required for IC Memo; surface the error with context ("DCF parameter extraction failed"). No partial IC Memo.

**Q2:** Should `generate_comps_excel` be callable without a prior comps pipeline run? **Proposed answer:** Yes — it takes `list[CompanyFinancials]` directly, not a cache key. Pipeline tool passes the data. This keeps compute modules free of pipeline dependencies.

**Q3:** For Earnings Analysis, if FMP doesn't have consensus estimates for a ticker (common for small-cap), should the pipeline fail or skip the beat/miss analysis? **Proposed answer:** Skip — set all `eps_estimated=0, eps_direction=INLINE` and log a warning. Beat rate and consecutive beats are 0. The LLM narrative step should note data limitations.
