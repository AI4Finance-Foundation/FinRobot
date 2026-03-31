# P1b Spec — Sub-Agents, Full Pipelines, Strict Validators

## Goal

Replace lead_agent one-for-all with 5 dedicated sub-agents, add comps and DCF pipelines, and switch from lenient to strict output validators. This is the **value validation milestone** — if P1b output quality doesn't meaningfully beat a well-prompted single LLM call, the pipeline architecture is over-engineering.

## Status: 🔄 In Progress

## Acceptance Criteria

All must pass:

1. `finagent research AAPL` → equity research pipeline uses 5 dedicated sub-agents (each step uses a different agent instance; step names visible in logs: "data_collection", "peer_analysis", etc.), strict validators pass on all steps
2. `finagent comps AAPL` → 6-step comps pipeline produces a trading multiples table with ≥3 peers, EV/EBITDA and P/E columns, and statistical benchmarks (median, quartiles)
3. `finagent dcf AAPL` → 6-step DCF pipeline produces projections, WACC calculation, terminal value, sensitivity table, and an implied price range
4. `python -m pytest tests/ -x -v --tb=short --ignore=tests/integration` — all unit tests pass (P0 + P1a + P1b)
5. **Quality gate**: `finagent research AAPL` output is compared side-by-side with a single well-prompted Claude Sonnet call using the same yfinance data. Pipeline output must contain structured sections (data summary, peer analysis, valuation, thesis, formatted report) that the single-call output lacks. This is a manual review — the test is skipped by default, run explicitly with `QUALITY_GATE=1 pytest tests/integration/test_p1b_acceptance.py::TestP1bAcceptance::test_quality_comparison`.

## Approved Dependencies

Same as P1a (no new dependencies).

```
pydantic-ai
pydantic-settings
fastapi
uvicorn
aiosqlite
yfinance
click
pyyaml
pytest
pytest-asyncio
```

## Scope Constraints

Do not write code for P1c+ features. If you need something from a future phase, write a `# TODO(P1c): ...` comment and move on. Specifically:

- Do NOT import finrobot (P2a)
- Do NOT write Electron/React code (P1c)
- Do NOT write memory system (P3a)
- Do NOT write sdk.py (P3a)
- Do NOT write skill composition/dependency resolution (P3a)
- Do NOT write spreadsheet_gen tool (P2c)
- Do NOT write LBO/earnings pipelines (P2c)

## Key Design Decisions

| Decision | Choice |
|---|---|
| Sub-agent count | 5: data, analysis, modeling, synthesis, report |
| Sub-agent instructions | Each has its own `instructions.md` in `finagent/engine/agents/` |
| Sub-agent model | All use `settings.model_name` (same model as lead_agent) |
| Sub-agent creation | Factory function `create_sub_agents(settings, skill_registry)` returns dict of agents |
| Pipeline step → agent mapping | Each PipelineStep references a sub-agent by role name, resolved from the dict |
| Strict validators | Text-based checks (keyword/structure matching), not LLM-as-judge |
| Comps pipeline | 6 steps per ARCHITECTURE.md section 2.3 |
| DCF pipeline | 6 steps per ARCHITECTURE.md section 2.3 |
| CLI commands | `finagent comps TICKER` and `finagent dcf TICKER`, same pattern as `finagent research` |

---

## Implementation Order — Detailed Specs

### File 21: `finagent/engine/agents/__init__.py` + `finagent/engine/agents/instructions/`

**Purpose**: Create the agents package and 5 instruction files.

**Create these files**:

1. `finagent/engine/agents/__init__.py` (empty)
2. `finagent/engine/agents/instructions/data_agent.md`
3. `finagent/engine/agents/instructions/analysis_agent.md`
4. `finagent/engine/agents/instructions/modeling_agent.md`
5. `finagent/engine/agents/instructions/synthesis_agent.md`
6. `finagent/engine/agents/instructions/report_agent.md`

**Instruction content guidelines**:

Each agent gets focused, role-specific instructions. These are system prompts that tell the LLM what it is and how to behave for its specific pipeline role.

```markdown
# data_agent.md
You are a financial data collection specialist.
Your job is to gather, organize, and summarize raw financial data for analysis.

When given a single ticker:
- Fetch financials (revenue, EBITDA, margins, ratios)
- Fetch price history and current valuation metrics
- Fetch recent news and sentiment
- Present data in structured, clearly labeled sections
- Include data source and timestamp
- Flag any missing or suspicious data points

When given multiple tickers (e.g. for peer data collection):
- Extract all ticker symbols from the context provided
- Fetch financials for EACH ticker using query_financial_data
- Present each company's data in its own clearly labeled section
- Ensure consistent metrics across all companies for comparability

Do NOT analyze or interpret the data. Just collect and organize it.
Always use the query_financial_data tool for real data. Never fabricate numbers.
```

```markdown
# analysis_agent.md
You are an equity research analyst specializing in peer analysis and comparable company evaluation.
Your job is to identify peers, build comps frameworks, and analyze competitive positioning.

When analyzing a company:
- Identify 3-5 relevant peer companies with justification for each
- Compare key operating metrics (revenue growth, margins, returns)
- Calculate and compare valuation multiples (EV/EBITDA, P/E, EV/Revenue)
- Position the target relative to peers (premium/discount and why)
- Note any comparability issues or adjustments needed

If skill methodology is provided in context, follow its framework and terminology.
```

```markdown
# modeling_agent.md
You are a financial modeling specialist focused on valuation.
Your job is to build DCF models, project financials, and derive valuation ranges.

When modeling a company:
- Project revenue, EBITDA, and free cash flow for 3-5 years
- State assumptions explicitly (growth rates, margin trajectory, capex)
- Calculate WACC with stated inputs (risk-free rate, beta, equity risk premium, cost of debt)
- Compute terminal value using both perpetuity growth and exit multiple methods
- Present an implied price range with sensitivity analysis
- Show your work — all key calculations should be traceable

If skill methodology is provided in context, follow its framework and terminology.
```

```markdown
# synthesis_agent.md
You are an investment strategist specializing in thesis construction.
Your job is to synthesize data, analysis, and valuation into a coherent investment thesis.

When constructing a thesis:
- State a clear investment recommendation (Buy/Hold/Sell or equivalent)
- Identify 3-5 key catalysts (upside drivers)
- Identify 3-5 key risks (downside scenarios)
- Articulate what the market is missing or mispricing
- Reference specific data points from earlier analysis (don't hallucinate new ones)
- Provide a price target with timeframe and methodology basis

If skill methodology is provided in context, follow its framework and terminology.
```

```markdown
# report_agent.md
You are a financial report editor.
Your job is to assemble analysis into a polished, professional equity research report.

When generating a report:
- Use clear Markdown structure with headers
- Start with an executive summary (recommendation, price target, key metrics)
- Organize into standard sections: Company Overview, Financial Summary, Peer Analysis, Valuation, Investment Thesis, Risks, Appendix
- Ensure all numbers are consistent across sections (don't introduce new data)
- Use tables for financial data and multiples
- Keep professional tone — concise, data-driven, no filler

Do NOT add new analysis. Organize and present what previous steps produced.
```

**Key details**:
- Instructions are concise and role-focused — each agent knows its lane
- Instructions reference "skill methodology" generically — the actual skill content is injected by the pipeline at runtime, not baked into instructions
- `query_financial_data` tool is only registered on data_agent (it's the only one that needs to fetch data)
- Other agents work with data passed from previous pipeline steps

**Tests**: No dedicated tests — instructions are static text. Validated transitively through pipeline tests.

**Dependencies**: None

---

### File 22: `finagent/engine/agents/factory.py`

**Purpose**: Factory function that creates all sub-agents. Central place where agent creation logic lives.

```python
from pathlib import Path
from pydantic_ai import Agent, RunContext
from finagent.engine.deps import FinAgentDeps
from finagent.engine.skills.registry import SkillRegistry
from finagent.config import FinAgentSettings

INSTRUCTIONS_DIR = Path(__file__).parent / "instructions"

def create_sub_agents(
    settings: FinAgentSettings,
    skill_registry: SkillRegistry | None = None,
) -> dict[str, Agent]:
    """Create all 5 dedicated sub-agents.
    
    Returns:
        dict mapping role name to Agent:
        {
            "data": Agent,
            "analysis": Agent,
            "modeling": Agent,
            "synthesis": Agent,
            "report": Agent,
        }
    """
    agents = {}
    
    for role in ["data", "analysis", "modeling", "synthesis", "report"]:
        instructions = (INSTRUCTIONS_DIR / f"{role}_agent.md").read_text()
        
        agent = Agent(
            settings.model_name,
            deps_type=FinAgentDeps,
            instructions=instructions,
            defer_model_check=True,  # don't validate API key at creation time
        )
        
        agents[role] = agent
    
    # Only data_agent gets the query_financial_data tool
    @agents["data"].tool
    async def query_financial_data(
        ctx: RunContext[FinAgentDeps], ticker: str, data_type: str
    ) -> str:
        """Fetch financial data. data_type: financials | price | news"""
        result = await ctx.deps.data_layer.fetch(data_type, ticker)
        return result.to_context_string()
    
    return agents
```

**Key details**:
- All agents share the same `settings.model_name` — model-agnostic, same as lead_agent
- All agents share `deps_type=FinAgentDeps` — they can access data_layer and skill_runtime through deps
- Only `data` agent gets `query_financial_data` tool — other agents don't fetch data, they work with data passed from previous steps
- Skill content is NOT baked into agent instructions here — it's injected per-step by `Pipeline.execute()` (already implemented in P0/P1a `base.py`)
- `skill_registry` parameter is reserved for future use (e.g., appending skill summaries to specific agents). P1b passes it but doesn't use it inside the factory.

**Tests** (`tests/unit/test_agent_factory.py`):
- `create_sub_agents(settings)` returns dict with 5 keys: data, analysis, modeling, synthesis, report
- Each value is a pydantic-ai Agent instance
- data agent has `query_financial_data` tool
- analysis/modeling/synthesis/report agents do NOT have `query_financial_data` tool
- All agents use `settings.model_name`

**Dependencies**: File 21

---

### File 23: `finagent/engine/pipelines/validators.py` (extend)

**Purpose**: Add strict validators alongside existing lenient ones. Lenient validators remain for backward compatibility and testing.

**New functions to add**:

```python
def validate_has_peers(output: str, min_peers: int = 3) -> ValidationResult:
    """Strict validator for peer analysis step.
    Checks that output mentions at least `min_peers` distinct company names/tickers.
    
    Strategy: look for patterns like:
    - Uppercase 2-5 letter sequences that look like tickers (MSFT, GOOGL, META)
    - Exclude common financial acronyms that are NOT tickers:
      WACC, DCF, EBITDA, GAAP, IFRS, FCF, ROIC, ROE, ROA, EPS, YOY, QOQ,
      CAGR, IPO, M&A, LBO, SEC, GDP, CPI, FED, NYSE, ETF, CEO, CFO, COO,
      BUY, SELL, HOLD, NOTE, USD, EUR, GBP, JPY, CNY
    - Common peer-related phrases ("peer", "comparable", "competitor")
    - Explicit peer lists or tables
    """

def validate_has_valuation(output: str) -> ValidationResult:
    """Strict validator for financial modeling step.
    Checks that output contains valuation methodology and numbers.
    
    Must find at least 2 of:
    - DCF/discounted cash flow related terms
    - WACC or discount rate mention
    - Terminal value mention
    - Price target or implied value
    - Revenue/EBITDA projections
    """

def validate_has_thesis(output: str) -> ValidationResult:
    """Strict validator for thesis construction step.
    Checks that output contains investment thesis structure.
    
    Must find at least 2 of:
    - Recommendation (buy/hold/sell or equivalent)
    - Catalyst or upside driver
    - Risk or downside scenario
    - Price target with basis
    """

def validate_report_format(output: str) -> ValidationResult:
    """Strict validator for report generation step.
    Checks that output has proper report structure.
    
    Must find:
    - At least 3 Markdown headers (##)
    - At least 200 words
    - At least 2 of: "summary", "valuation", "risk", "thesis", "peer", "financial"
    """

def validate_has_comps_table(output: str) -> ValidationResult:
    """Strict validator for comps pipeline output.
    Checks for multiples table structure.
    
    Must find:
    - At least 3 company mentions (tickers or names) — reuse validate_has_peers exclusion list
    - At least 2 of: "EV/EBITDA", "P/E", "EV/Revenue", "multiple"
    - Statistical terms: "median", "mean", or "average"
    """

def validate_dcf_output(output: str) -> ValidationResult:
    """Strict validator for DCF pipeline output.
    Checks for DCF model components.
    
    Must find at least 3 of:
    - WACC or discount rate
    - Terminal value
    - Free cash flow or FCF
    - Sensitivity or scenario
    - Implied price or valuation range
    """
```

**Key details**:
- All validators are text-based pattern matching — no LLM-as-judge, no external calls
- Validators check for **structure and methodology keywords**, not correctness of numbers
- Each validator returns `ValidationResult(passed=True/False, error="missing: ...")`
- Lenient validators (`validate_is_non_empty`, `validate_has_fields`) are NOT removed — still used in tests and as fallbacks
- Validators are intentionally generous — they verify the agent followed the methodology, not that the analysis is good. Quality is validated in integration tests, not validators.

**Tests** (`tests/unit/test_validators.py` — extend):
- validate_has_peers with 3+ tickers → passed
- validate_has_peers with 1 ticker → failed, error mentions "peers"
- validate_has_valuation with DCF + WACC + terminal value → passed
- validate_has_valuation with empty text → failed
- validate_has_thesis with recommendation + catalyst + risk → passed
- validate_has_thesis with just a recommendation → failed
- validate_report_format with headers + length + sections → passed
- validate_report_format with no headers → failed
- validate_has_comps_table with tickers + multiples + median → passed
- validate_dcf_output with 3+ DCF components → passed
- validate_dcf_output with just "DCF" mentioned → failed

**Dependencies**: None (extends existing file)

---

### File 24: `finagent/engine/pipelines/equity_research.py` (rewrite)

**Purpose**: Update equity research pipeline to use sub-agents and strict validators.

**Changes from P0/P1a version**:

```python
from finagent.engine.pipelines.base import Pipeline, PipelineStep
from finagent.engine.pipelines.validators import (
    validate_has_fields,
    validate_has_peers,
    validate_has_valuation,
    validate_has_thesis,
    validate_report_format,
)
from pydantic_ai import Agent

def create_equity_research_pipeline(agents: dict[str, Agent]) -> Pipeline:
    """Factory function. Now accepts dict of sub-agents instead of a single agent.
    
    Args:
        agents: dict from create_sub_agents(), keys: data, analysis, modeling, synthesis, report
    """
    return Pipeline(
        steps=[
            PipelineStep(
                name="data_collection",
                skill_section=None,
                agent=agents["data"],          # was: lead_agent
                required_data=["financials", "price", "news"],
                validate=lambda out: validate_has_fields(out, ["revenue", "ebitda", "price_history"]),
            ),
            PipelineStep(
                name="peer_analysis",
                skill_section="comps-analysis",
                agent=agents["analysis"],      # was: lead_agent
                required_data=[],
                validate=lambda out: validate_has_peers(out, min_peers=3),  # was: validate_is_non_empty
            ),
            PipelineStep(
                name="financial_modeling",
                skill_section="dcf-model",
                agent=agents["modeling"],       # was: lead_agent
                required_data=[],
                validate=lambda out: validate_has_valuation(out),  # was: validate_is_non_empty
            ),
            PipelineStep(
                name="thesis",
                skill_section="initiating-coverage",
                agent=agents["synthesis"],      # was: lead_agent
                required_data=[],
                validate=lambda out: validate_has_thesis(out),  # was: validate_is_non_empty
            ),
            PipelineStep(
                name="report",
                skill_section=None,
                agent=agents["report"],         # was: lead_agent
                required_data=[],
                validate=lambda out: validate_report_format(out),  # was: validate_is_non_empty
            ),
        ]
    )
```

**⚠️ Breaking change**: `create_equity_research_pipeline` now takes `agents: dict[str, Agent]` instead of `agent: Agent`. **All callers and tests must be updated in this same file to avoid test breakage (Rule 2).**

**Callers to update simultaneously**:
- `finagent/engine/orchestrator.py`: already handled in File 27 (comes after)
- `finagent/cli.py`: already handled in File 28 (comes after)
- But **existing tests must be fixed NOW** as part of File 24:

**Update `tests/unit/test_equity_research_pipeline.py`** — use agents dict:
```python
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

def make_test_agents():
    """Create agents dict with TestModel for unit testing."""
    agents = {}
    for role in ["data", "analysis", "modeling", "synthesis", "report"]:
        agents[role] = Agent(TestModel(), deps_type=FinAgentDeps, defer_model_check=True)
    return agents

# All tests use make_test_agents() instead of a single Agent
```

**Update `tests/integration/test_p0_acceptance.py`** — use agents dict:
```python
from finagent.engine.agents.factory import create_sub_agents

# BEFORE:
pipeline = create_equity_research_pipeline(agent)
# AFTER:
sub_agents = create_sub_agents(settings)
pipeline = create_equity_research_pipeline(sub_agents)
```

**Update `tests/integration/test_p1a_acceptance.py`** — same pattern if it creates pipeline directly.

**Tests** (`tests/unit/test_equity_research_pipeline.py` — rewrite):
- Pipeline has exactly 5 steps (unchanged)
- Step names are: data_collection, peer_analysis, financial_modeling, thesis, report (unchanged)
- Step agents are different instances (not all the same agent)
- data_collection uses agents["data"]
- peer_analysis uses agents["analysis"]
- Step 2 validator is validate_has_peers (not validate_is_non_empty)
- Step 3 validator is validate_has_valuation (not validate_is_non_empty)
- Execute with TestModel agents produces PipelineResult with all 5 step keys
- **All P0/P1a tests still pass** (run full suite before proceeding)

**Dependencies**: Files 22, 23

---

### File 25: `finagent/engine/pipelines/comps.py`

**Purpose**: 6-step comparable company analysis pipeline. New file.

```python
from finagent.engine.pipelines.base import Pipeline, PipelineStep
from finagent.engine.pipelines.validators import (
    validate_has_fields,
    validate_has_peers,
    validate_is_non_empty,
    validate_has_comps_table,
)
from pydantic_ai import Agent

def create_comps_pipeline(agents: dict[str, Agent]) -> Pipeline:
    """6-step comps analysis pipeline per ARCHITECTURE.md section 2.3."""
    return Pipeline(
        steps=[
            PipelineStep(
                name="target_data",
                skill_section=None,
                agent=agents["data"],
                required_data=["financials", "price"],
                validate=lambda out: validate_has_fields(out, ["revenue", "ebitda"]),
            ),
            PipelineStep(
                name="peer_selection",
                skill_section="comps-analysis",
                agent=agents["analysis"],
                required_data=[],
                validate=lambda out: validate_has_peers(out, min_peers=3),
            ),
            PipelineStep(
                name="peer_data",
                skill_section=None,
                agent=agents["data"],
                required_data=[],  # uses peer list from step 2 — data_agent fetches each peer's financials
                validate=lambda out: validate_has_fields(out, ["revenue", "ebitda"]),
            ),
            PipelineStep(
                name="multiples_calc",
                skill_section="comps-analysis",
                agent=agents["modeling"],
                required_data=[],
                validate=lambda out: validate_is_non_empty(out),  # TODO(P2c): validate_has_multiples_table
            ),
            PipelineStep(
                name="statistical_bench",
                skill_section="comps-analysis",
                agent=agents["analysis"],
                required_data=[],
                validate=lambda out: validate_is_non_empty(out),  # TODO(P2c): validate_has_statistics
            ),
            PipelineStep(
                name="output_gen",
                skill_section="comps-analysis",
                agent=agents["report"],
                required_data=[],
                validate=lambda out: validate_has_comps_table(out),
            ),
        ]
    )
```

**Key details**:
- Step 3 (peer_data) reuses `data` agent — it needs to fetch financials for each peer identified in step 2
- The `_build_step_prompt()` in base.py passes previous step results as context, so peer_data step sees the peer list from step 2
- Steps 4-5 use lenient validators with TODOs — full multiples table validation is P2c when spreadsheet_gen is available
- Step 6 uses `validate_has_comps_table` — the strict validator checking for peer tickers + multiples + statistics

**Tests** (`tests/unit/test_comps_pipeline.py`):
- Pipeline has exactly 6 steps
- Step names are: target_data, peer_selection, peer_data, multiples_calc, statistical_bench, output_gen
- target_data uses agents["data"]
- peer_selection uses agents["analysis"]
- peer_data uses agents["data"] (reuse)
- output_gen uses agents["report"]
- Execute with TestModel agents produces PipelineResult with all 6 step keys

**Dependencies**: Files 22, 23

---

### File 26: `finagent/engine/pipelines/dcf.py`

**Purpose**: 6-step DCF valuation pipeline. New file.

```python
from finagent.engine.pipelines.base import Pipeline, PipelineStep
from finagent.engine.pipelines.validators import (
    validate_has_fields,
    validate_is_non_empty,
    validate_dcf_output,
    validate_has_valuation,
)
from pydantic_ai import Agent

def create_dcf_pipeline(agents: dict[str, Agent]) -> Pipeline:
    """6-step DCF valuation pipeline per ARCHITECTURE.md section 2.3."""
    return Pipeline(
        steps=[
            PipelineStep(
                name="historical_data",
                skill_section=None,
                agent=agents["data"],
                required_data=["financials", "price"],
                validate=lambda out: validate_has_fields(out, ["revenue", "ebitda"]),
            ),
            PipelineStep(
                name="projection",
                skill_section="dcf-model",
                agent=agents["modeling"],
                required_data=[],
                validate=lambda out: validate_is_non_empty(out),  # projections are hard to validate structurally
            ),
            PipelineStep(
                name="wacc",
                skill_section="dcf-model",
                agent=agents["modeling"],
                required_data=[],
                validate=lambda out: validate_has_valuation(out),
            ),
            PipelineStep(
                name="terminal_value",
                skill_section="dcf-model",
                agent=agents["modeling"],
                required_data=[],
                validate=lambda out: validate_is_non_empty(out),
            ),
            PipelineStep(
                name="sensitivity",
                skill_section="dcf-model",
                agent=agents["modeling"],
                required_data=[],
                validate=lambda out: validate_is_non_empty(out),
            ),
            PipelineStep(
                name="output_gen",
                skill_section="dcf-model",
                agent=agents["report"],
                required_data=[],
                validate=lambda out: validate_dcf_output(out),
            ),
        ]
    )
```

**Key details**:
- Steps 2-5 all use `modeling` agent — DCF is modeling-heavy
- Step 6 uses `report` agent for final assembly
- `dcf-model` skill is injected into steps 2-6 for methodology guidance
- Some steps use lenient `validate_is_non_empty` because intermediate modeling outputs (projections, terminal value) are hard to validate structurally without understanding the numbers

**Tests** (`tests/unit/test_dcf_pipeline.py`):
- Pipeline has exactly 6 steps
- Step names are: historical_data, projection, wacc, terminal_value, sensitivity, output_gen
- historical_data uses agents["data"]
- projection/wacc/terminal_value/sensitivity use agents["modeling"]
- output_gen uses agents["report"]
- Execute with TestModel agents produces PipelineResult with all 6 step keys

**Dependencies**: Files 22, 23

---

### File 27: `finagent/engine/orchestrator.py` (update)

**Purpose**: Register `run_comps_analysis` and `run_dcf_valuation` tools. Update `create_lead_agent` to create sub-agents and pass them to pipeline factories.

**Changes to `create_lead_agent()`**:

```python
from finagent.engine.agents.factory import create_sub_agents

def create_lead_agent(settings, skill_registry=None):
    # ... existing instructions + skill_summary logic ...
    
    agent = Agent(
        settings.model_name,
        deps_type=FinAgentDeps,
        instructions=instructions,
        defer_model_check=True,  # don't validate API key at creation time
    )
    
    # Create sub-agents for pipelines
    sub_agents = create_sub_agents(settings, skill_registry)
    
    # --- existing tools (unchanged) ---
    @agent.tool
    async def query_financial_data(...): ...
    
    @agent.tool
    async def activate_skill(...): ...
    
    # --- updated equity research tool ---
    from finagent.engine.pipelines.equity_research import create_equity_research_pipeline
    equity_pipeline = create_equity_research_pipeline(sub_agents)  # was: agent
    
    @agent.tool
    async def run_equity_research(ctx: RunContext[FinAgentDeps], ticker: str) -> str:
        """Generate a comprehensive equity research report.
        Uses a multi-step enforced pipeline. Takes 30-120 seconds.
        Use this when the user asks for: equity research, initiating coverage,
        stock analysis report, investment thesis, or deep-dive analysis."""
        result = await equity_pipeline.execute(ctx.deps, ticker)
        return result.format_summary()
    
    # --- NEW: comps tool ---
    from finagent.engine.pipelines.comps import create_comps_pipeline
    comps_pipeline = create_comps_pipeline(sub_agents)
    
    @agent.tool
    async def run_comps_analysis(
        ctx: RunContext[FinAgentDeps], ticker: str
    ) -> str:
        """Build a comparable company analysis.
        Uses a multi-step enforced pipeline.
        Use when user asks for: comps, comparable companies, peer analysis,
        trading multiples comparison."""
        result = await comps_pipeline.execute(ctx.deps, ticker)
        return result.format_summary()
    
    # --- NEW: dcf tool ---
    from finagent.engine.pipelines.dcf import create_dcf_pipeline
    dcf_pipeline = create_dcf_pipeline(sub_agents)
    
    @agent.tool
    async def run_dcf_valuation(ctx: RunContext[FinAgentDeps], ticker: str) -> str:
        """Run a DCF valuation model.
        Uses a multi-step enforced pipeline.
        Use when user asks for: DCF, discounted cash flow, intrinsic value,
        valuation model."""
        result = await dcf_pipeline.execute(ctx.deps, ticker)
        return result.format_summary()
    
    return agent
```

**Key details**:
- `create_sub_agents()` is called once inside the factory — all pipelines share the same agent instances
- `create_equity_research_pipeline` signature changed from `agent` to `sub_agents` dict
- Two new tools registered: `run_comps_analysis` and `run_dcf_valuation`
- Tool docstrings match ARCHITECTURE.md section 2.4 exactly — these guide LLM routing
- `--peers` support deferred to P2c (requires Pipeline.execute() kwargs forwarding)

**Tests** (`tests/unit/test_orchestrator.py` — extend):
- create_lead_agent returns agent with 5 tools: query_financial_data, activate_skill, run_equity_research, run_comps_analysis, run_dcf_valuation
- Functional test: agent with TestModel routes "comps analysis for AAPL" to run_comps_analysis tool
- Functional test: agent with TestModel routes "DCF valuation for AAPL" to run_dcf_valuation tool

**Dependencies**: Files 22, 24, 25, 26

---

### File 28: `finagent/cli.py` (update)

**Purpose**: Add `finagent comps` and `finagent dcf` commands. Refactor `_build_runtime()` to avoid creating unused lead_agent in pipeline commands.

**Refactor `_build_runtime()`** — split into `_build_deps()` + `_build_runtime()`:

```python
def _build_deps(model: str | None = None) -> FinAgentDeps:
    """Build deps only. No agent creation.
    Used by pipeline commands that create their own sub-agents.
    Access settings via deps.settings."""
    settings = get_settings()
    if model:
        settings = get_settings(model_name=model)
    settings.apply_api_keys()
    
    skills_path = Path(settings.skills_dir)
    registry = SkillRegistry(skills_path) if skills_path.exists() else None
    
    cache = DataCache(settings.cache_db_path)
    data_layer = DataLayer(providers=[YFinanceProvider()], cache=cache)
    deps = FinAgentDeps(data_layer=data_layer, settings=settings, skill_runtime=registry)
    
    return deps

def _build_runtime(model: str | None = None) -> tuple[Agent, FinAgentDeps]:
    """Build lead agent + deps. Used by `run` command (Mode A)."""
    deps = _build_deps(model)
    agent = create_lead_agent(deps.settings, skill_registry=deps.skill_runtime)
    return agent, deps
```

**New commands**:

```python
@cli.command()
@click.argument("ticker")
@click.option("--model", default=None)
def comps(ticker: str, model: str | None):
    """Run comparable company analysis pipeline.
    
    # TODO(P2c): add --peers option when Pipeline.execute() supports kwargs forwarding
    """
    deps = _build_deps(model)
    
    from finagent.engine.agents.factory import create_sub_agents
    from finagent.engine.pipelines.comps import create_comps_pipeline
    
    sub_agents = create_sub_agents(deps.settings, skill_registry=deps.skill_runtime)
    pipeline = create_comps_pipeline(sub_agents)
    
    import asyncio
    result = asyncio.run(pipeline.execute(deps, ticker))
    click.echo(result.format_summary())


@cli.command()
@click.argument("ticker")
@click.option("--model", default=None)
def dcf(ticker: str, model: str | None):
    """Run DCF valuation pipeline."""
    deps = _build_deps(model)
    
    from finagent.engine.agents.factory import create_sub_agents
    from finagent.engine.pipelines.dcf import create_dcf_pipeline
    
    sub_agents = create_sub_agents(deps.settings, skill_registry=deps.skill_runtime)
    pipeline = create_dcf_pipeline(sub_agents)
    
    import asyncio
    result = asyncio.run(pipeline.execute(deps, ticker))
    click.echo(result.format_summary())
```

**Also update `research` command** — uses `_build_deps()` + sub-agents:

```python
@cli.command()
@click.argument("ticker")
@click.option("--model", default=None)
def research(ticker: str, model: str | None):
    """Run equity research pipeline on a ticker (Mode B)."""
    deps = _build_deps(model)
    
    from finagent.engine.agents.factory import create_sub_agents
    from finagent.engine.pipelines.equity_research import create_equity_research_pipeline
    
    sub_agents = create_sub_agents(deps.settings, skill_registry=deps.skill_runtime)
    pipeline = create_equity_research_pipeline(sub_agents)
    
    import asyncio
    result = asyncio.run(pipeline.execute(deps, ticker))
    click.echo(result.format_summary())
```

**`run` command stays on `_build_runtime()`** (Mode A needs lead_agent):
```python
@cli.command()
@click.argument("question")
@click.option("--model", default=None)
def run(question: str, model: str | None):
    """Ask a quick financial question (Mode A)."""
    agent, deps = _build_runtime(model)
    result = agent.run_sync(question, deps=deps)
    click.echo(result.output)
```

**Key details**:
- `--peers` option removed from P1b — `Pipeline.execute()` doesn't forward kwargs to steps. Marked as TODO(P2c).
- `_build_deps()` returns deps — access settings via `deps.settings`, no agent creation, no wasted work
- `_build_runtime()` wraps `_build_deps()` + creates lead_agent — only used by `run` command
- Pipeline commands (research, comps, dcf) use `_build_deps()` → `create_sub_agents()` → pipeline — sub-agents created exactly once
- `run` command uses `_build_runtime()` → lead_agent (which internally creates sub-agents for its pipeline tools, but that's the orchestrator's concern)

**Tests** (`tests/unit/test_cli.py` — extend):
- `finagent comps AAPL` doesn't crash (TestModel mock)
- `finagent dcf AAPL` doesn't crash (TestModel mock)
- `finagent research AAPL` still works with sub-agents
- `_build_deps()` returns FinAgentDeps with settings and skill_runtime accessible via deps.settings
- `_build_runtime()` returns agent + deps

**Dependencies**: Files 22, 24, 25, 26, 27

---

### File 29: `tests/integration/test_p1b_acceptance.py`

**Purpose**: P1b acceptance gate + quality validation.

```python
import os
import pytest
from pathlib import Path
from finagent.config import get_settings
from finagent.engine.skills.registry import SkillRegistry
from finagent.engine.agents.factory import create_sub_agents
from finagent.engine.pipelines.equity_research import create_equity_research_pipeline
from finagent.engine.pipelines.comps import create_comps_pipeline
from finagent.engine.pipelines.dcf import create_dcf_pipeline
from finagent.engine.deps import FinAgentDeps
from finagent.engine.data.layer import DataLayer
from finagent.engine.data.cache import DataCache
from finagent.engine.data.providers.yfinance_provider import YFinanceProvider

SKILLS_DIR = Path(get_settings().skills_dir)

def _build_test_env():
    settings = get_settings()
    settings.apply_api_keys()
    registry = SkillRegistry(SKILLS_DIR) if SKILLS_DIR.exists() else None
    sub_agents = create_sub_agents(settings, skill_registry=registry)
    cache = DataCache(":memory:")
    data_layer = DataLayer(providers=[YFinanceProvider()], cache=cache)
    deps = FinAgentDeps(data_layer=data_layer, settings=settings, skill_runtime=registry)
    return sub_agents, deps


class TestP1bAcceptance:

    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_equity_research_with_sub_agents(self):
        """P1b acceptance: equity research uses sub-agents and strict validators."""
        sub_agents, deps = _build_test_env()
        pipeline = create_equity_research_pipeline(sub_agents)
        result = await pipeline.execute(deps, "AAPL")
        
        assert set(result.steps.keys()) == {
            "data_collection", "peer_analysis", "financial_modeling", "thesis", "report"
        }
        
        # Strict validator checks (these would fail with P0 lenient validators)
        summary = result.format_summary().lower()
        assert any(kw in summary for kw in ["ev/ebitda", "p/e", "peer", "comparable"])
        assert any(kw in summary for kw in ["dcf", "wacc", "discount rate", "terminal"])
        assert any(kw in summary for kw in ["buy", "hold", "sell", "catalyst", "risk"])

    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_comps_pipeline(self):
        """P1b acceptance: comps pipeline produces peer multiples table."""
        sub_agents, deps = _build_test_env()
        pipeline = create_comps_pipeline(sub_agents)
        result = await pipeline.execute(deps, "AAPL")
        
        assert set(result.steps.keys()) == {
            "target_data", "peer_selection", "peer_data",
            "multiples_calc", "statistical_bench", "output_gen"
        }
        
        output = result.format_summary().lower()
        assert any(kw in output for kw in ["ev/ebitda", "p/e", "multiple"])
        assert any(kw in output for kw in ["median", "mean", "average"])

    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_dcf_pipeline(self):
        """P1b acceptance: DCF pipeline produces valuation model."""
        sub_agents, deps = _build_test_env()
        pipeline = create_dcf_pipeline(sub_agents)
        result = await pipeline.execute(deps, "AAPL")
        
        assert set(result.steps.keys()) == {
            "historical_data", "projection", "wacc",
            "terminal_value", "sensitivity", "output_gen"
        }
        
        output = result.format_summary().lower()
        assert any(kw in output for kw in ["wacc", "discount rate"])
        assert any(kw in output for kw in ["terminal value", "exit multiple", "perpetuity"])

    @pytest.mark.skipif(
        not os.getenv("QUALITY_GATE"),
        reason="Manual quality gate — run with: QUALITY_GATE=1 pytest tests/integration/test_p1b_acceptance.py::TestP1bAcceptance::test_quality_comparison"
    )
    @pytest.mark.asyncio
    async def test_quality_comparison(self):
        """P1b QUALITY GATE: Pipeline output vs single-call LLM output.
        
        This test is the project's value validation milestone.
        Run manually and review output side-by-side.
        
        If pipeline output is NOT meaningfully better than single-call output,
        the pipeline architecture is over-engineering and the project should pivot.
        
        Comparison methodology:
        1. Fetch AAPL data via yfinance (same data for both)
        2. Run finagent equity research pipeline → pipeline_output
        3. Run single Claude/GPT call with ONLY query_financial_data tool → single_call_output
           (NO pipeline tools registered — forces LLM to do everything in one pass)
        4. Compare: structure, methodology depth, data accuracy, actionability
        """
        sub_agents, deps = _build_test_env()
        
        # 1. Pipeline output (5 sub-agents, 5 enforced steps)
        pipeline = create_equity_research_pipeline(sub_agents)
        pipeline_result = await pipeline.execute(deps, "AAPL")
        pipeline_output = pipeline_result.format_summary()
        
        # 2. Single-call output — a bare agent with ONLY query_financial_data
        #    NO pipeline tools registered. LLM must do all analysis in one pass.
        from pydantic_ai import Agent, RunContext
        settings = get_settings()
        single_agent = Agent(
            settings.model_name,
            deps_type=FinAgentDeps,
            instructions="You are a financial analyst. Use real data from tools. Never fabricate numbers.",
            defer_model_check=True,
        )
        
        @single_agent.tool
        async def query_financial_data(
            ctx: RunContext[FinAgentDeps], ticker: str, data_type: str
        ) -> str:
            result = await ctx.deps.data_layer.fetch(data_type, ticker)
            return result.to_context_string()
        
        single_result = await single_agent.run(
            "Fetch financials, price, and news for AAPL using query_financial_data. "
            "Then write a comprehensive equity research report covering: "
            "financial summary, peer analysis with at least 3 comparable companies, "
            "DCF valuation with WACC and terminal value, investment thesis with "
            "catalysts and risks, and a final recommendation with price target. "
            "Use real data only.",
            deps=deps,
        )
        single_output = single_result.output
        
        # Print both for manual comparison
        print("\n" + "="*80)
        print("PIPELINE OUTPUT (5 sub-agents, 5 enforced steps, skill injection)")
        print("="*80)
        print(pipeline_output[:3000])
        print("\n" + "="*80)
        print("SINGLE-CALL OUTPUT (1 agent, 1 pass, no pipeline)")
        print("="*80)
        print(single_output[:3000])
        print("\n" + "="*80)
        print("COMPARE: Does pipeline output have better structure, ")
        print("methodology depth, and data accuracy than single-call?")
        print("If NO → pipeline architecture is over-engineering. Consider pivot.")
        print("="*80)
```

**Dependencies**: All P1b files

---

## Implementation Order Summary

| # | File | Type | Description |
|---|---|---|---|
| 21 | `finagent/engine/agents/__init__.py` + instructions/ | New | Agent package + 5 instruction files |
| 22 | `finagent/engine/agents/factory.py` | New | `create_sub_agents()` factory |
| 23 | `finagent/engine/pipelines/validators.py` | Extend | 6 strict validators |
| 24 | `finagent/engine/pipelines/equity_research.py` + existing tests | Rewrite | Sub-agents + strict validators + fix all callers/tests |
| 25 | `finagent/engine/pipelines/comps.py` | New | 6-step comps pipeline |
| 26 | `finagent/engine/pipelines/dcf.py` | New | 6-step DCF pipeline |
| 27 | `finagent/engine/orchestrator.py` | Update | Register comps/dcf tools, use sub-agents |
| 28 | `finagent/cli.py` | Update | `finagent comps` / `finagent dcf` + `_build_deps()` refactor |
| 29 | `tests/integration/test_p1b_acceptance.py` | New | Acceptance + quality gate |

**Order matters**: 21 → 22 → 23 → 24 → 25 → 26 → 27 → 28 → 29

**File 24 is the riskiest** — it changes `create_equity_research_pipeline` signature AND updates all existing tests in the same step. Run full test suite before proceeding to File 25.

**File 29 is the value gate** — the `test_quality_comparison` determines whether the project direction is correct.

---

## ⚠️ P1a Breaking Changes

P1b changes `create_equity_research_pipeline(agent)` → `create_equity_research_pipeline(agents_dict)`. All callers must update:

1. **`finagent/engine/orchestrator.py`**: `create_equity_research_pipeline(agent)` → `create_equity_research_pipeline(sub_agents)` (File 27)
2. **`finagent/cli.py`**: `research` command creates sub-agents and passes dict (File 28)
3. **`tests/unit/test_equity_research_pipeline.py`**: use mock agents dict (File 24 — updated immediately with the signature change)
4. **`tests/integration/test_p0_acceptance.py`**: use sub-agents (File 24 — updated immediately)
5. **`tests/integration/test_p1a_acceptance.py`**: use sub-agents if applicable (File 24 — updated immediately)

---

## Things That Do NOT Exist in P1b

- FinRobot data adapter (P2a)
- Additional data providers: FMP, Finnhub, SEC EDGAR (P2a/P2b)
- LBO/earnings/IC memo pipelines (P2c)
- spreadsheet_gen tool (P2c)
- Electron/React desktop app (P1c)
- Memory system (P3a)
- Skill composition (P3a)
- Python SDK (P3a)

If any code imports from `finagent.adapters`, `finagent.desktop`, `finagent.engine.memory`, or `finagent.engine.tools`, you have a bug.

---

## Package Structure After P1b

```
finagent/
├── __init__.py
├── config.py
├── engine/
│   ├── __init__.py
│   ├── orchestrator.py          # UPDATED: sub-agents, comps/dcf tools
│   ├── deps.py
│   ├── instructions.md          # Lead agent instructions (unchanged)
│   ├── agents/                  # NEW in P1b
│   │   ├── __init__.py
│   │   ├── factory.py           # create_sub_agents()
│   │   └── instructions/
│   │       ├── data_agent.md
│   │       ├── analysis_agent.md
│   │       ├── modeling_agent.md
│   │       ├── synthesis_agent.md
│   │       └── report_agent.md
│   ├── data/                    # unchanged
│   │   └── ...
│   ├── pipelines/               # UPDATED
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── equity_research.py   # REWRITTEN: sub-agents + strict validators
│   │   ├── comps.py             # NEW
│   │   ├── dcf.py               # NEW
│   │   └── validators.py        # EXTENDED: 6 strict validators added
│   └── skills/                  # unchanged from P1a
│       └── ...
├── server.py
├── cli.py                       # UPDATED: comps/dcf commands
│
├── skills/                      # unchanged
│   └── ...
│
└── tests/
    ├── unit/
    │   ├── test_agent_factory.py     # NEW
    │   ├── test_comps_pipeline.py    # NEW
    │   ├── test_dcf_pipeline.py      # NEW
    │   ├── test_validators.py        # EXTENDED
    │   ├── test_equity_research_pipeline.py  # REWRITTEN
    │   ├── test_orchestrator.py      # EXTENDED
    │   ├── test_cli.py              # EXTENDED
    │   └── ...
    └── integration/
        ├── test_p0_acceptance.py     # UPDATED signatures
        ├── test_p1a_acceptance.py    # UPDATED signatures
        └── test_p1b_acceptance.py    # NEW — includes quality gate
```