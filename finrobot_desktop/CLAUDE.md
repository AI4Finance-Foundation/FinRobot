# CLAUDE.md

## Project

FinAgent — A financial AI agent platform with extensible skill ecosystem.
Full architecture: see `ARCHITECTURE.md` in project root.

Tech stack: PydanticAI + FastAPI + Electron + React 19.
No LangChain. No LangGraph. No AutoGen. No LiteLLM.

## Current Phase: P0

P0 goal: `finagent run` (conversational) and `finagent research AAPL` (pipeline) both work end-to-end.

### P0 Acceptance Criteria

Both must pass before P0 is considered done:

1. `finagent run "What's AAPL's PE ratio?"` → correct answer with real yfinance data, < 10 seconds
2. `finagent research AAPL` → Markdown report containing:
   - Financial data summary (revenue, EBITDA, margins — real yfinance data)
   - Peer company list (minimum 3 peers with justification)
   - Valuation range (with methodology stated)
   - Terminal shows: Step 1/5... Step 2/5... Step 3/5... Step 4/5... Step 5/5...
   - Total time < 60 seconds on Claude Sonnet 4.6
   - Each step provably ran (logged), no steps skipped

---

## Development Rules

### Rule 1: One file at a time

Never write multiple files in one pass. Workflow:
1. Write ONE file
2. Write its test file
3. Run tests, confirm pass
4. Only then move to the next file

### Rule 2: Test before moving on

After every file:
```bash
python -m pytest tests/ -x -v --tb=short
```
If any test fails, fix it before writing the next file. Never leave broken tests behind.

### Rule 3: Follow the implementation order exactly

Do not skip ahead. Do not reorder. The sequence is designed so each file only depends on files already completed above it.

### Rule 4: Only P0 code

Do not write code for P1a+ features. If you need something from a future phase, write a `# TODO(P1a): ...` comment and move on. Specifically:

- Do NOT import finrobot (P2a)
- Do NOT write skill loader/registry (P1a)
- Do NOT write sub-agents (P1b)
- Do NOT write Electron/React code (P1c)
- Do NOT write memory system (P3a)
- Do NOT write sdk.py (P3a)

### Rule 5: Only approved dependencies

```
pydantic-ai
fastapi
uvicorn
aiosqlite
yfinance
click
pytest
pytest-asyncio
```

Do not add any dependency not on this list without explicit approval.

### Rule 6: Follow ARCHITECTURE.md exactly

The architecture document contains exact class names, method signatures, tool docstrings, and pipeline step definitions. Use them verbatim. Do not rename classes, change signatures, or "improve" the design. If you think something in ARCHITECTURE.md is wrong, say so — don't silently change it.

---

## P0 Implementation Order — Detailed Specs

### File 1: `finagent/engine/data/interface.py`

**Purpose**: Define the DataProvider ABC and data models.

**Classes to implement**:
```python
from abc import ABC, abstractmethod
from pydantic import BaseModel
from datetime import datetime

class DataResult(BaseModel):
    """Structured result from any data provider."""
    data: dict                    # the actual financial data
    provider: str                 # which provider returned this
    ticker: str
    data_type: str                # 'financials' | 'price' | 'news' | 'filings'
    timestamp: datetime           # when this data was fetched
    warnings: list[str] = []     # e.g. "stale data from cache"

    def to_context_string(self) -> str:
        """Format data for LLM consumption. Human-readable, includes warnings."""

class DataProvider(ABC):
    """Every data source implements this."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def capabilities(self) -> list[str]:
        """Returns list of data_types this provider supports."""

    @abstractmethod
    async def fetch(self, ticker: str, data_type: str, **kwargs) -> DataResult: ...

class ProviderError(Exception):
    """Raised when a provider fails to fetch data."""
```

**Tests** (`tests/unit/test_data_interface.py`):
- DataResult.to_context_string() produces readable output
- DataResult with warnings includes them in context string
- DataProvider ABC cannot be instantiated directly
- ProviderError is a proper exception

**Dependencies**: None (this is the foundation)

---

### File 2: `finagent/engine/data/providers/yfinance_provider.py`

**Purpose**: Implement DataProvider for yfinance. This is the only provider in P0.

**Must support these data_types**:
- `"financials"` → revenue, EBITDA, net income, margins, PE ratio, market cap
- `"price"` → current price + 1 year price history (OHLCV)
- `"news"` → recent news headlines (yfinance has basic news)

**Not supported in P0** (return ProviderError with helpful message):
- `"filings"` → needs SEC EDGAR (P2b)

**Key implementation details**:
- All yfinance calls must be wrapped in try/except — yfinance is unreliable
- Use `yfinance.Ticker(ticker)` API
- Return structured DataResult, not raw yfinance objects
- financials data_type should return: revenue, ebitda, net_income, gross_margin, operating_margin, pe_ratio, market_cap, shares_outstanding

**Tests** (`tests/unit/test_yfinance_provider.py`):
- fetch("AAPL", "financials") returns DataResult with revenue > 0
- fetch("AAPL", "price") returns DataResult with price_history list
- fetch("AAPL", "news") returns DataResult with headlines list
- fetch("INVALID_TICKER_XYZ", "financials") raises ProviderError
- fetch("AAPL", "filings") raises ProviderError with "not supported" message
- capabilities() returns ["financials", "price", "news"]
- name property returns "yfinance"

**Note**: These are integration tests that hit real yfinance. Mark them with `@pytest.mark.integration` and also write unit tests with mocked yfinance for CI.

**Dependencies**: File 1 (interface.py)

---

### File 3: `finagent/engine/data/cache.py`

**Purpose**: SQLite cache for financial data. Avoid redundant API calls.

**Class**:
```python
class DataCache:
    def __init__(self, db_path: str = "finagent_cache.db"): ...
    async def get(self, data_type: str, ticker: str, max_age_hours: int = 24) -> CachedResult | None: ...
    async def set(self, data_type: str, ticker: str, result: DataResult) -> None: ...
    async def clear(self, ticker: str | None = None) -> None: ...

class CachedResult(BaseModel):
    data: DataResult
    is_stale: bool          # True if older than max_age_hours
    cached_at: datetime
```

**Key details**:
- SQLite table: `cache(data_type TEXT, ticker TEXT, data JSON, cached_at TIMESTAMP, PRIMARY KEY (data_type, ticker))`
- get() returns None if not in cache
- get() returns CachedResult with is_stale=True if older than max_age_hours (but still returns the data — stale data is better than no data)
- Use aiosqlite for async access
- Auto-create table on first use

**Tests** (`tests/unit/test_cache.py`):
- set then get returns same data
- get non-existent key returns None
- get stale data returns CachedResult with is_stale=True
- get fresh data returns CachedResult with is_stale=False
- clear(ticker) only clears that ticker
- clear() clears everything

**Dependencies**: File 1 (interface.py)

---

### File 4: `finagent/engine/data/layer.py`

**Purpose**: DataLayer routes requests to providers with caching and fallback.

**Class**:
```python
class DataLayer:
    def __init__(self, providers: list[DataProvider], cache: DataCache): ...

    async def fetch(self, data_type: str, ticker: str, **kwargs) -> DataResult:
        """
        Flow:
        1. Check cache → if fresh, return
        2. Find provider that supports this data_type
        3. Try fetch → success → cache → return
        4. If fails → try fallback provider
        5. If all fail → return stale cache with warning
        6. If no cache at all → raise ProviderError
        """

    def _select_provider(self, data_type: str) -> DataProvider | None: ...
    def _select_fallback(self, data_type: str) -> DataProvider | None: ...
```

**Key details**:
- In P0 there's only one provider (yfinance), so fallback just returns stale cache
- The abstraction matters for P2a+ when FMP/Finnhub are added
- fetch() must never raise unless there's literally no data anywhere

**Tests** (`tests/unit/test_data_layer.py`):
- fetch with empty cache calls provider
- fetch with fresh cache returns cache (doesn't call provider)
- fetch with stale cache calls provider, updates cache
- fetch when provider fails returns stale cache with warning
- fetch when provider fails and no cache raises ProviderError
- Multiple providers: selects correct one for data_type

Use mock providers for unit tests (create a MockProvider that implements DataProvider).

**Dependencies**: Files 1, 2, 3

---

### File 5: `finagent/engine/pipelines/validators.py`

**Purpose**: Validation functions for pipeline step outputs.

**Functions**:
```python
class ValidationResult(BaseModel):
    passed: bool
    error: str | None = None

def validate_is_non_empty(output: str) -> ValidationResult:
    """P0 validator. Passes if output is non-empty string."""

def validate_has_fields(output: str, fields: list[str]) -> ValidationResult:
    """P0 validator for data collection step. Checks that output mentions all required fields."""
```

**Key details**:
- P0 validators are intentionally lenient — they verify the pipeline produces output, not that the output is perfect
- validate_has_fields does simple string matching (checks if field names appear in output)
- Strict validators (validate_has_peers, validate_has_valuation, etc.) are P1b — do NOT implement them now, add TODO comments

**Tests** (`tests/unit/test_validators.py`):
- validate_is_non_empty("hello") → passed=True
- validate_is_non_empty("") → passed=False
- validate_is_non_empty("   ") → passed=False
- validate_has_fields("revenue is 100B, ebitda is 50B", ["revenue", "ebitda"]) → passed=True
- validate_has_fields("revenue is 100B", ["revenue", "ebitda"]) → passed=False, error mentions "ebitda"

**Dependencies**: None

---

### File 6: `finagent/engine/pipelines/base.py`

**Purpose**: The Pipeline and PipelineStep framework. This is the most critical file in the entire project.

**Classes**: Implement exactly as shown in ARCHITECTURE.md section 2.2, including:
- PipelineStep dataclass with: name, skill_section, agent, required_data, validate
- Pipeline dataclass with: steps, max_retries=2
- Pipeline.execute() with the exact flow: gather_data → load_skill (with None guard) → run agent → validate with retry loop → store results
- PipelineResult model with steps dict and format_summary() method

**Additional methods to implement**:
```python
class Pipeline:
    async def _gather_data(self, ctx, required_data, ticker, previous_results) -> str:
        """Fetch required data via DataLayer OR use previous step results.
        If required_data is empty, format previous_results as context string."""

    def _build_step_prompt(self, step, step_data, methodology) -> str:
        """Build the prompt for this step's agent.
        Includes: step name, data context, methodology (if any), output instructions."""
```

**Key details**:
- Pipeline.execute() must log each step start/completion to stdout: "Step 1/5: data_collection..." "Step 1/5: data_collection ✓"
- If validation fails after all retries, continue to next step anyway (don't crash the pipeline) but log a warning
- PipelineResult.format_summary() concatenates all step outputs into a readable Markdown report

**Tests** (`tests/unit/test_pipeline_base.py`):
- Pipeline with 3 steps executes all in order (use mock agent)
- Pipeline step with failed validation retries up to max_retries
- Pipeline step with failed validation after all retries continues (doesn't crash)
- Pipeline._gather_data fetches from DataLayer when required_data is non-empty
- Pipeline._gather_data uses previous results when required_data is empty
- Pipeline.execute logs step progress
- PipelineResult.format_summary produces non-empty Markdown

Use PydanticAI's TestModel for mock agents.

**Dependencies**: Files 1, 4, 5

---

### File 7: `finagent/engine/deps.py`

**Purpose**: The FinAgentDeps dataclass — dependency injection container.

```python
from dataclasses import dataclass
from finagent.engine.data.layer import DataLayer

@dataclass
class FinAgentDeps:
    data_layer: DataLayer
    skill_runtime: object | None = None   # P0: None. P1a: SkillRegistry
    model_name: str = "anthropic:claude-sonnet-4-6"
```

**Key details**:
- skill_runtime is None in P0. This is why Pipeline.execute() and activate_skill have None guards.
- Keep this file minimal. Do not add fields for P1a+ features.

**Tests**: No dedicated test file needed — tested transitively through orchestrator and pipeline tests.

**Dependencies**: File 4

---

### File 8: `finagent/engine/orchestrator.py`

**Purpose**: Lead agent definition + tool registration.

**Implement exactly as shown in ARCHITECTURE.md section 2.4**:
- lead_agent = Agent(...) with deps_type=FinAgentDeps
- instructions loaded from engine/instructions.md
- Tool: query_financial_data (Mode A)
- Tool: activate_skill (Mode A, with None guard)
- Tool: run_equity_research (Mode B)
- Do NOT register run_comps_analysis or run_dcf_valuation (P1b pipelines)

**Also create**: `finagent/engine/instructions.md`
```markdown
You are FinAgent, a professional financial analysis assistant.

You have two modes of operation:

**Quick queries**: For simple questions about financial data (prices, ratios, news),
use the query_financial_data tool to fetch real data and answer directly.

**Deep analysis**: For comprehensive analysis requests (equity research, initiating coverage,
investment thesis), use the run_equity_research tool which runs a multi-step pipeline.

Always use real data from tools. Never fabricate financial numbers.
When presenting data, include the source and timestamp.
```

**Tests** (`tests/unit/test_orchestrator.py`):
- Agent has query_financial_data tool registered
- Agent has activate_skill tool registered
- Agent has run_equity_research tool registered
- activate_skill returns "not available" message when skill_runtime is None
- Test with PydanticAI TestModel that agent calls query_financial_data for simple questions
- Test with PydanticAI TestModel that agent calls run_equity_research for research requests

**Dependencies**: Files 4, 6, 7

---

### File 9: `finagent/engine/pipelines/equity_research.py`

**Purpose**: The 5-step equity research pipeline. Implement exactly as in ARCHITECTURE.md section 2.3.

**Key details**:
- All 5 steps use lead_agent (imported from orchestrator)
- Steps 2-5 use validate_is_non_empty (P0 lenient validators)
- Step 1 uses validate_has_fields(["revenue", "ebitda", "price_history"])
- skill_section values are strings ("comps-analysis", "dcf-model", "initiating-coverage") but they won't resolve in P0 because skill_runtime is None — this is expected

**Tests** (`tests/unit/test_equity_research_pipeline.py`):
- Pipeline has exactly 5 steps
- Step names are: data_collection, peer_analysis, financial_modeling, thesis, report
- Steps 2-5 skill_sections are set correctly
- Execute with TestModel agent produces PipelineResult with all 5 step keys
- Execute logs 5 step progress messages

**Dependencies**: Files 6, 8, 5

---

### File 10: `finagent/server.py`

**Purpose**: FastAPI server with VercelAIAdapter.

```python
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response
from pydantic_ai.ui.vercel_ai import VercelAIAdapter

app = FastAPI(title="FinAgent")

@app.post("/chat")
async def chat(request: Request) -> Response:
    # Build deps, create agent, dispatch
    return await VercelAIAdapter.dispatch_request(request, agent=agent, deps=deps)

@app.get("/health")
async def health():
    return {"status": "ready", "phase": "P0"}
```

**Key details**:
- Agent creation can accept model override from request body
- deps construction: create DataLayer with yfinance provider + DataCache
- /health endpoint is needed for Electron startup (P1c) — implement it now

**Tests** (`tests/unit/test_server.py`):
- /health returns 200 with {"status": "ready"}
- /chat endpoint exists and accepts POST
- Use httpx.AsyncClient for testing FastAPI

**Dependencies**: Files 4, 7, 8

---

### File 11: `finagent/cli.py`

**Purpose**: CLI entry points.

```python
import click

@click.group()
def cli(): ...

@cli.command()
@click.argument("question")
@click.option("--model", default="anthropic:claude-sonnet-4-6")
def run(question: str, model: str):
    """Ask a quick financial question (Mode A)."""

@cli.command()
@click.argument("ticker")
@click.option("--model", default="anthropic:claude-sonnet-4-6")
def research(ticker: str, model: str):
    """Run equity research pipeline on a ticker (Mode B)."""

@cli.command()
@click.option("--port", default=8000)
def serve(port: int):
    """Start the FinAgent server."""
```

**Key details**:
- `run` command: creates agent + deps, calls agent.run_sync(), prints result
- `research` command: creates agent + deps, calls equity_research_pipeline.execute(), prints formatted report with step progress
- `serve` command: starts uvicorn with server.app
- Entry point in pyproject.toml: `[project.scripts] finagent = "finagent.cli:cli"`

**Tests** (`tests/unit/test_cli.py`):
- Use click.testing.CliRunner
- `finagent run "test"` doesn't crash (use TestModel mock)
- `finagent research AAPL` doesn't crash (use TestModel mock)
- `finagent serve` starts (just verify it doesn't crash on import)

**Dependencies**: Files 4, 7, 8, 9, 10

---

### File 12: End-to-end acceptance test

**File**: `tests/integration/test_p0_acceptance.py`

This is the final gate. Both acceptance criteria must pass:

```python
@pytest.mark.integration
@pytest.mark.slow
async def test_mode_a_quick_query():
    """P0 acceptance: finagent run 'What is AAPL's PE ratio?'
    Must return real data in < 10 seconds."""

@pytest.mark.integration
@pytest.mark.slow
async def test_mode_b_equity_research():
    """P0 acceptance: finagent research AAPL
    Must produce report with financials + peers + valuation in < 60 seconds."""
```

**These tests call real APIs** (yfinance + LLM). They are slow and cost money. Run them manually, not in CI.

**Dependencies**: All P0 files

---

## Package Structure

```
finagent/
├── __init__.py
├── engine/
│   ├── __init__.py
│   ├── orchestrator.py
│   ├── deps.py
│   ├── instructions.md
│   ├── data/
│   │   ├── __init__.py
│   │   ├── interface.py
│   │   ├── layer.py
│   │   ├── cache.py
│   │   └── providers/
│   │       ├── __init__.py
│   │       └── yfinance_provider.py
│   └── pipelines/
│       ├── __init__.py
│       ├── base.py
│       ├── equity_research.py
│       └── validators.py
├── server.py
└── cli.py
```

Every directory needs an `__init__.py`. Do not forget them.

---

## Things That Do NOT Exist in P0

These will cause ImportError if you try to use them:
- `finagent.engine.skills` — P1a
- `finagent.engine.agents` — P1b
- `finagent.engine.memory` — P3a
- `finagent.engine.tools` — P2c
- `finagent.adapters` — P2a
- `finagent.sdk` — P3a
- `finagent.desktop` — P1c

If any code you write imports from these modules, you have a bug.
