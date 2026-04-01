# FinAgent Architecture

> A financial AI agent platform with extensible skill ecosystem.
> Version 0.4 | 2026-03-30

---

## What is FinAgent

FinAgent is a **financial-domain AI agent platform**.

It solves a specific gap: **academic financial AI tools** (FinRobot, FinRL) have excellent data utilities but are notebook-only, built on deprecated frameworks, and have no production story. **Generic agent frameworks** (DeerFlow, LangGraph) have powerful orchestration but zero financial domain knowledge. Neither serves financial professionals or quant developers well.

```
                Generic Agent Frameworks
                (DeerFlow, LangGraph, CrewAI)
                ┌─────────────────────────┐
                │ Powerful orchestration   │
                │ No domain knowledge     │
                │ No financial data       │
                └────────────┬────────────┘
                             │
                ┌────────────▼────────────┐
                │       FinAgent          │
                │                         │
                │  Financial agent engine  │
                │  + Skill ecosystem       │
                │  + Data layer            │
                │  + Desktop runtime       │
                └────────────┬────────────┘
                             │
                ┌────────────▼────────────┐
                │ Academic Financial AI    │
                │ (FinRobot, FinRL, FinGPT)│
                │ Great data utilities     │
                │ Notebook-only            │
                │ Deprecated frameworks    │
                └─────────────────────────┘
```

### Why it's worth starring

1. **Skill Ecosystem** — A unified format for financial AI workflows. 56 skills (sourced from Anthropic's financial-services-plugins) ship built-in. Anyone can write, publish, and compose skills. Skills are Markdown + YAML — no code needed.

2. **Financial Agent Engine** — Not a chatbot wrapper. Core financial analysis flows (equity research, DCF, comps) are **code-enforced pipelines** where each step must complete before the next begins. Skills provide the methodology for each step; code guarantees execution order. The LLM decides *how* to analyze, but never *whether* to skip a step.

3. **Unified Data Layer** — Abstracts data sources behind a single interface. yfinance built-in; FMP, Finnhub, SEC EDGAR planned for P2a-P2b; MCP bridge planned for P2b.

4. **Desktop-First Runtime** *(planned for P1c)* — Will run locally on Win + macOS. Data stays on your machine. Currently available as CLI and Python library; desktop app is planned.

---

## The Three Layers

```
┌──────────────────────────────────────────────────────┐
│  Layer 3: Clients                                    │
│  Desktop App (Electron + React) — P1c, not started    │
│  CLI — finagent run "analyze AAPL"   ✓ implemented   │
│  Python SDK — P3a, not started                       │
│  Future: Web, Mobile, MCP Server                     │
└──────────────────────────┬───────────────────────────┘
                           │ Vercel AI Data Stream (SSE)
                           │ or Python async generator
┌──────────────────────────▼───────────────────────────┐
│  Layer 2: Engine (the product)                       │
│                                                      │
│  ┌─────────────┐ ┌──────────────┐ ┌───────────────┐ │
│  │ Agent       │ │ Skill        │ │ Data           │ │
│  │ Orchestrator│ │ Runtime      │ │ Layer          │ │
│  │             │ │              │ │                │ │
│  │ Lead agent  │ │ Loader       │ │ Provider ABC   │ │
│  │ Pipelines   │ │ Registry     │ │ Cache + fallbk │ │
│  │ Sub-agents  │ │ Validator    │ │ MCP bridge     │ │
│  │ Streaming   │ │ Composer     │ │ (P2b)          │ │
│  │ (P1c)       │ │ (P3a)       │ │                │ │
│  └─────────────┘ └──────────────┘ └───────────────┘ │
│                                                      │
│  Built on: PydanticAI (MIT) + FastAPI (MIT)          │
└──────────────────────────┬───────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────┐
│  Layer 1: Adapters                                   │
│                                                      │
│  ┌─────────────────────┐ ┌─────────────────────────┐ │
│  │ FinRobot Data       │ │ Anthropic Skill         │ │
│  │ Adapter             │ │ Format Adapter          │ │
│  │ (P2a — not started) │ │ (vendor-time only) ✓    │ │
│  │                     │ │                         │ │
│  │ Wraps ONLY:         │ │ Reads:                  │ │
│  │ - fmp_utils.py      │ │ - financial-services-   │ │
│  │ - finnhub_utils.py  │ │   plugins format        │ │
│  │ - yfinance_utils.py │ │                         │ │
│  │ - sec_utils.py      │ │ Converts to:            │ │
│  │                     │ │ - FinAgent native format │ │
│  │ Does NOT wrap:      │ │ - stored in repo        │ │
│  │ - agents/workflow   │ │                         │ │
│  │ - AutoGen pipeline  │ │                         │ │
│  └─────────────────────┘ └─────────────────────────┘ │
│                                                      │
│  Never modifies upstream code. Adapter pattern only. │
└──────────────────────────────────────────────────────┘
```

---

## Layer 1: Adapters

### FinRobot Adapter — Data Only

**We only adapt FinRobot's data utilities, not its analysis pipeline.**

FinRobot's analysis pipeline (`agents/workflow.py`, `SingleAssistantShadow`, the multi-agent CoT system) is built on AutoGen 0.2, which Microsoft has deprecated. The pipeline already has active dependency breakage in GitHub issues. Instead of wrapping a rotting runtime, we rebuild the analysis capability — better — using our own code-enforced pipelines + Anthropic's institutional-grade skill methodology (see Layer 2).

What IS reliable: FinRobot's `data_source/` module — clean utility functions for FMP, Finnhub, yfinance, and SEC EDGAR. Pure data-fetching, no AutoGen dependency.

```python
# finagent/adapters/finrobot_data.py
class FinRobotDataAdapter:
    """Wraps finrobot.data_source.* behind typed async interfaces.
    Runs in subprocess to isolate FinRobot's dep chain from engine."""

    async def get_financials(self, ticker: str, period: str = "annual") -> FinancialData
    async def get_news(self, ticker: str, days: int = 7) -> list[NewsItem]
    async def get_price_history(self, ticker: str, period: str = "1y") -> PriceHistory
    async def get_filings(self, ticker: str, filing_type: str = "10-K") -> list[Filing]
```

**Subprocess isolation**: even `import finrobot` pulls in AutoGen's entire dep chain. The subprocess boundary keeps it from infecting the engine process.

**FinRobot is optional.** The engine works without it — yfinance covers basic use cases. FinRobot adapter unlocks FMP/Finnhub for users who have API keys.

### Anthropic Skill Format Adapter

Reads the `financial-services-plugins` format and normalizes into FinAgent skill format. Extracts `SKILL.md` content + command triggers from `commands/*.md`. No DeerFlow skill format adapter — DeerFlow skills are bound to its Docker sandbox runtime and can't run outside it.

---

## Layer 2: Engine

`pip install finagent` gets you this entire layer.

### 2.1 Agent Orchestrator — The Two Modes

The orchestrator has two distinct execution modes. The mode is selected automatically based on what the user asks.

#### Mode A: Conversational (simple questions, quick lookups)

For lightweight tasks — "What's AAPL's PE ratio?", "Show me TSLA's revenue trend", "Summarize today's market news" — the lead agent handles it directly with tool calls. No pipeline, no sub-agents. Fast.

```
User: "What's AAPL's PE ratio?"
    → Lead Agent calls query_financial_data("AAPL", "financials")
    → Gets structured data back
    → Answers directly: "Apple's trailing PE is 28.3x..."
```

#### Mode B: Pipeline (deep analysis, report generation)

For complex financial workflows — equity research, DCF valuation, comparable company analysis, IC memos — the orchestrator dispatches to a **code-enforced pipeline**. This is where the FinRobot-replacement logic lives.

```
User: "Write an initiating coverage report for AAPL"
    → Lead Agent recognizes this needs the equity_research pipeline
    → Dispatches to run_equity_research()
    → Pipeline enforces: data → analysis → valuation → synthesis → report
    → Each step MUST complete before the next begins
    → Each step runs the agent with skill methodology injected (P0: lead_agent; P1b: dedicated sub-agents)
    → Final report output
```

**The critical design principle: Code enforces the steps. Skills provide the methodology for each step. The LLM decides *how* to do each step, never *whether* to do it.**

This is strictly better than FinRobot's approach on the same data sources:
- FinRobot: AutoGen 0.2 code-enforced steps + hand-tuned CoT prompts + GPT-4
- FinAgent: PydanticAI code-enforced steps + Anthropic institutional-grade skill methodology + Claude/GPT-4o/any model

Same enforcement guarantee. Better methodology source. Better model options.

### 2.2 Pipeline Architecture

Pipelines are the core differentiator. They solve the "LLM might skip steps" problem that pure Skill-driven approaches have.

```python
# finagent/engine/pipelines/base.py

import logging

logger = logging.getLogger(__name__)

class PipelineStep:
    """A single enforced step in a financial analysis pipeline."""
    name: str
    skill_section: str | None    # which part of the skill to inject
    agent: Agent                 # dedicated sub-agent for this step
    required_data: list[str]     # data types this step needs
    validate: Callable           # output validation function

class Pipeline:
    """Code-enforced sequence of analysis steps.
    
    Each step:
    1. Receives structured data from previous steps (not free-text)
    2. Gets skill methodology injected as system prompt
    3. Runs a dedicated sub-agent
    4. Output is validated before proceeding
    5. If validation fails, step retries (up to max_retries, default 2)
    """
    steps: list[PipelineStep]
    max_retries: int = 2
    
    async def execute(self, ctx: RunContext[FinAgentDeps], ticker: str, **kwargs) -> PipelineResult:
        results = {}
        for step in self.steps:
            # 1. Gather required data (code-enforced, cannot skip)
            step_data = await self._gather_data(ctx, step.required_data, ticker, results)
            
            # 2. Load skill methodology for this step
            methodology = ""
            if step.skill_section and ctx.deps.skill_runtime:  # skill_runtime is None in P0
                skill = ctx.deps.skill_runtime.get(step.skill_section)
                if skill:
                    methodology = skill.full_content
            
            # 3. Run sub-agent with methodology + data
            prompt = self._build_step_prompt(step, step_data, methodology)
            step_result = await step.agent.run(prompt, deps=ctx.deps)
            
            # 4. Validate output, retry up to max_retries
            for attempt in range(self.max_retries):
                validation = step.validate(step_result.output)
                if validation.passed:
                    break
                step_result = await step.agent.run(
                    f"Previous output failed validation: {validation.error}\n"
                    f"Fix the issues and try again.\n\n{step_result.output}",
                    deps=ctx.deps,
                )
            else:
                # Retries exhausted, validation still failing.
                # Best-effort: continue with imperfect output rather than crash the pipeline.
                logger.warning(f"Pipeline step '{step.name}' failed validation after {self.max_retries} retries. Continuing with best-effort output.")
            
            # 5. Store for next steps
            results[step.name] = step_result.output
        
        return PipelineResult(steps=results)
```

### 2.3 Built-in Pipelines

#### Equity Research Pipeline

Replaces FinRobot's Data-CoT → Concept-CoT → Thesis-CoT with a five-step code-enforced pipeline. Methodology sourced from Anthropic's `initiating-coverage` skill (five-phase workflow: research → financial modelling → valuation → chart generation → report assembly).

```python
# finagent/engine/pipelines/equity_research.py

equity_research_pipeline = Pipeline(
    steps=[
        # Step 1: Data Collection (code-enforced, all sources queried)
        PipelineStep(
            name="data_collection",
            skill_section=None,  # no skill needed, pure data fetch
            agent=lead_agent,    # P0: all steps use lead_agent
                                 # P1b: switch to dedicated data_agent
            required_data=["financials", "price", "news"],  # "filings" added in P2b (SEC EDGAR)
            validate=lambda out: validate_has_fields(out, ["revenue", "ebitda", "price_history"]),
        ),
        
        # Step 2: Peer Identification & Comps
        PipelineStep(
            name="peer_analysis",
            skill_section="comps-analysis",  # Anthropic's comps methodology
            agent=lead_agent,    # P0: lead_agent; P1b: analysis_agent
            required_data=[],  # uses step 1 output
            # P0: validate_is_non_empty (skill not yet loaded, strict validator would false-fail)
            # P1b+: validate_has_peers(out, min_peers=3) (after skill runtime ships)
            validate=lambda out: validate_is_non_empty(out),
        ),
        
        # Step 3: Financial Analysis & Modeling
        PipelineStep(
            name="financial_modeling",
            skill_section="dcf-model",  # Anthropic's DCF methodology
            agent=lead_agent,    # P0: lead_agent; P1b: modeling_agent
            required_data=[],
            # P0: validate_is_non_empty
            # P1b+: validate_has_valuation(out)
            validate=lambda out: validate_is_non_empty(out),
        ),
        
        # Step 4: Thesis Construction
        PipelineStep(
            name="thesis",
            skill_section="initiating-coverage",  # Anthropic's IC methodology
            agent=lead_agent,    # P0: lead_agent; P1b: synthesis_agent
            required_data=[],
            # P0: validate_is_non_empty
            # P1b+: validate_has_sections (after skill runtime ships)
            validate=lambda out: validate_is_non_empty(out),
        ),
        
        # Step 5: Report Generation
        PipelineStep(
            name="report",
            skill_section=None,  # structured output, no skill
            agent=lead_agent,    # P0: lead_agent; P1b: report_agent
            required_data=[],
            # P0: validate_is_non_empty
            # P1b+: validate_report_format(out)
            validate=lambda out: validate_is_non_empty(out),
        ),
    ]
)
```

**How this compares to FinRobot step by step:**

| Step | FinRobot (AutoGen 0.2) | FinAgent (Pipeline + Skill) |
|------|----------------------|---------------------------|
| Data fetch | `data_source/*` utils via CoT Agent | Same utils via Data Layer (+ cache + fallback) |
| Analysis method | Hand-tuned CoT prompt | Anthropic's institutional-grade skill instructions |
| Step enforcement | AutoGen agent sequence (code) | Pipeline.execute() loop (code) |
| Inter-step data | Free-text conversation between agents | Structured `results` dict, validated |
| Validation | None (hope the agent got it right) | Per-step validation with retry |
| Output | Fixed Markdown template | Skill-defined format, flexible |
| Model | GPT-4 only | Any model (Claude, GPT-4o, DeepSeek, Ollama) |

**Design intent comparison — output quality to be validated against FinRobot benchmarks in integration tests.** The enforcement guarantee is identical in design — both use code to force step order. Methodology source differs (institutional skill files vs hand-tuned CoT prompts); which produces better output on specific tasks is an empirical question to be answered by testing, not assumed. Data passing is structured + validated vs free-text conversation. Per-step validation is new — FinRobot has none.

#### Comps Analysis Pipeline

```python
comps_pipeline = Pipeline(
    steps=[
        PipelineStep(name="target_data", ...),        # Fetch target financials
        PipelineStep(name="peer_selection", ...),      # Select & justify peers
        PipelineStep(name="peer_data", ...),           # Fetch all peer financials
        PipelineStep(name="multiples_calc", ...),      # Calculate trading multiples
        PipelineStep(name="statistical_bench", ...),   # Median, quartiles, positioning
        PipelineStep(name="output_gen",                # Generate Excel workbook
            skill_section="comps-analysis",            # Anthropic's comps methodology
            validate=lambda out: validate_has_fields(out, ["multiples_table", "statistics"]),
        ),
    ]
)
```

#### DCF Pipeline

```python
dcf_pipeline = Pipeline(
    steps=[
        PipelineStep(name="historical_data", ...),     # 3-5 years historical financials
        PipelineStep(name="projection", ...),          # Revenue/EBITDA/FCF projections
        PipelineStep(name="wacc", ...),                # WACC calculation
        PipelineStep(name="terminal_value", ...),      # Terminal value (exit multiple + perpetuity)
        PipelineStep(name="sensitivity", ...),         # Sensitivity table
        PipelineStep(name="output_gen",
            skill_section="dcf-model",
            validate=lambda out: validate_dcf_output(out),
        ),
    ]
)
```

More pipelines follow the same pattern: LBO, IC Memo, Earnings Analysis. Each is a code file in `engine/pipelines/`. Each references skills for methodology but enforces steps in code.

### 2.4 How the Lead Agent Dispatches

The code below shows the **full target state (P1b+)**. In P0, only `query_financial_data`, `activate_skill`, and `run_equity_research` are registered. `run_comps_analysis` and `run_dcf_valuation` are added in P1b.

```python
# finagent/engine/orchestrator.py

lead_agent = Agent(
    'anthropic:claude-sonnet-4-6',
    deps_type=FinAgentDeps,
    instructions=(Path(__file__).parent / "instructions.md").read_text(),
)

# --- Mode A tools: conversational, direct response ---

@lead_agent.tool
async def query_financial_data(
    ctx: RunContext[FinAgentDeps], ticker: str, data_type: str
) -> str:
    """Fetch financial data for quick questions.
    data_type: financials | price | news (filings available from P2b)"""
    return await ctx.deps.data_layer.fetch(data_type, ticker)


@lead_agent.tool
async def activate_skill(ctx: RunContext[FinAgentDeps], skill_id: str) -> str:
    """Activate a skill for ad-hoc professional workflows.
    Use this for tasks that don't have a dedicated pipeline."""
    if not ctx.deps.skill_runtime:  # P0: skill runtime not yet available
        return "Skill system is not yet available. Use direct data queries or pipeline commands instead."
    skill = ctx.deps.skill_runtime.get(skill_id)
    if not skill:
        return f"Unknown skill. Available: {ctx.deps.skill_runtime.list_ids()}"
    return skill.full_content


# --- Mode B tools: pipeline dispatch for deep analysis ---

@lead_agent.tool
async def run_equity_research(ctx: RunContext[FinAgentDeps], ticker: str) -> str:
    """Generate a comprehensive equity research report.
    Uses a multi-step enforced pipeline. Takes 30-120 seconds.
    Use this when the user asks for: equity research, initiating coverage,
    stock analysis report, investment thesis, or deep-dive analysis."""
    result = await equity_research_pipeline.execute(ctx, ticker)
    return result.format_summary()


@lead_agent.tool
async def run_comps_analysis(
    ctx: RunContext[FinAgentDeps], ticker: str, peers: list[str] | None = None
) -> str:
    """Build a comparable company analysis.
    Uses a multi-step enforced pipeline.
    Use when user asks for: comps, comparable companies, peer analysis,
    trading multiples comparison."""
    result = await comps_pipeline.execute(ctx, ticker, peers=peers)
    return result.format_summary()


@lead_agent.tool
async def run_dcf_valuation(ctx: RunContext[FinAgentDeps], ticker: str) -> str:
    """Run a DCF valuation model.
    Uses a multi-step enforced pipeline.
    Use when user asks for: DCF, discounted cash flow, intrinsic value,
    valuation model."""
    result = await dcf_pipeline.execute(ctx, ticker)
    return result.format_summary()
```

The lead agent has clear routing: simple question → direct tool call. Complex analysis → pipeline dispatch. The pipelines handle all enforcement internally.

### 2.5 Skill Runtime

Skills serve two roles in FinAgent:

1. **Methodology source for pipelines** — Pipeline steps inject skill content as instructions for their sub-agents. The pipeline code controls the step order; the skill controls the analytical method within each step.

2. **Standalone workflows for ad-hoc tasks** — For tasks without a dedicated pipeline (e.g., "draft a morning note", "prepare client meeting brief"), the lead agent loads the full skill via `activate_skill` and follows it directly. This is acceptable for less critical workflows where step-skipping is not catastrophic.

#### Skill Format

```yaml
---
id: comps-analysis
name: Comparable Company Analysis
version: 1.0.0
author: anthropic
domain: equity-research
triggers:
  - "comparable company"
  - "comps"
  - "peer analysis"
requires_data:
  - type: financials
  - type: price
requires_tools:
  - spreadsheet_gen               # P2c: openpyxl-based Excel gen (engine/tools/spreadsheet_gen.py)
requires_skills:                  # composition (P3, ignored before then)
  - dcf-model
compatible_models:                # optional, community-maintained
  - "anthropic:claude-*"
  - "openai:gpt-4o"
---

# Comparable Company Analysis
## Workflow
[step-by-step methodology...]
## Output format
[expected deliverables...]
```

`compatible_models` is optional. Community-maintained, not enforced. If untested, leave it empty — an empty field is honest; a stale field is misleading.

`requires_skills` is parsed from P0 but composition execution is P3. Before P3, each skill runs independently. This is documented in the spec to avoid user confusion.

#### Skill Registry

```python
class SkillRegistry:
    def search(self, query: str) -> list[Skill]
    def get(self, skill_id: str) -> Skill | None
    def list_summary(self) -> str          # compact for LLM context
    def install(self, source: str) -> Skill # .skill archive or git URL
    def validate(self, skill: Skill) -> list[ValidationError]
```

### 2.6 Data Layer

Provider interface + routing + caching + graceful degradation:

```python
class DataProvider(ABC):
    @abstractmethod
    async def fetch(self, ticker: str, data_type: str, **kwargs) -> DataResult: ...

class DataLayer:
    """cache check → primary provider → fallback → stale cache with warning."""
    def __init__(self, providers: list[DataProvider], cache: DataCache): ...
```

Built-in providers:

| Provider | Data Types | Cost | Role |
|---|---|---|---|
| yfinance | Price, basic financials | Free | Default fallback |
| FMP (via FinRobot adapter) | Detailed financials, ratios | $15-50/mo | Primary for fundamentals |
| Finnhub (via FinRobot adapter) | News, company profile | Free tier | Primary for news |
| SEC EDGAR | 10-K, 10-Q, proxy statements | Free | Primary for filings |
| MCP Bridge | Any external MCP data server | Varies | User-extensible |

---

## Layer 3: Clients

### Desktop App (Electron + React 19)

The first client, not the product.

```
desktop/
├── electron/
│   ├── main.ts              # Window + Python process lifecycle (uv sidecar)
│   ├── preload.ts           # IPC for safeStorage (Key encryption)
│   └── updater.ts           # electron-updater
├── renderer/                # React 19 + Vite + Tailwind CSS 4
│   ├── app/
│   │   ├── chat/             # Vercel AI SDK useChat
│   │   ├── workspace/        # Multi-panel: chart, report, data, skills
│   │   └── settings/         # API keys, model, skill management
│   ├── stores/               # Zustand
│   └── components/
└── resources/               # Bundled at build time by electron-builder
    ├── uv-darwin-arm64       # Platform-specific uv binaries
    ├── uv-darwin-x86_64
    ├── uv-win32-x64.exe
    └── python/              # pyproject.toml + uv.lock for the engine
```

**Python lifecycle** (managed by `main.ts`):
1. First launch: `uv sync` creates a local venv from `uv.lock` (~30-60s, shown as loading screen)
2. Every launch: `uv run finagent serve --port <port>` starts the FastAPI engine
3. Electron window connects to `localhost:<port>` — pure HTTP/SSE, no IPC for data

PydanticAI's VercelAIAdapter outputs Vercel AI Data Stream Protocol SSE. React's `useChat` consumes it. Zero custom protocol code.

**Pipeline progress streaming**: When a pipeline runs, each step completion emits an SSE event. The desktop UI shows a progress indicator: "Step 2/5: Peer analysis... ✓"

### CLI

```bash
finagent run "What's AAPL's PE ratio?"
finagent research AAPL                    # runs equity research pipeline
finagent comps AAPL --peers MSFT,GOOGL    # runs comps pipeline
finagent dcf AAPL                         # runs DCF pipeline
finagent serve --port 8000
finagent skill list
finagent skill install https://github.com/user/my-skill
```

### Python SDK

```python
from finagent import FinAgent

agent = FinAgent(model="anthropic:claude-sonnet-4-6")

# Quick question (Mode A)
result = await agent.run("What's AAPL's PE ratio?")

# Deep analysis (Mode B — pipeline)
report = await agent.research("AAPL")         # equity research pipeline
comps = await agent.comps("AAPL")             # comps pipeline
dcf = await agent.dcf("AAPL")                # DCF pipeline

# Streaming pipeline with progress
async for event in agent.research_stream("AAPL"):
    if event.type == "step_start":
        print(f"Starting: {event.step_name}...")
    elif event.type == "step_complete":
        print(f"Done: {event.step_name} ✓")
    elif event.type == "text":
        print(event.content, end="")

# Direct data access (no LLM)
data = await agent.data.fetch("financials", "AAPL")
```

---

## Project Structure

```
finagent/
├── engine/
│   ├── orchestrator.py             # Lead agent + tool registration
│   ├── deps.py                     # FinAgentDeps
│   ├── instructions.md             # System prompt
│   ├── pipelines/                  # CODE-ENFORCED analysis flows
│   │   ├── base.py                 # Pipeline + PipelineStep classes
│   │   ├── equity_research.py      # 5-step equity research
│   │   ├── comps.py                # 6-step comps analysis — P1b
│   │   ├── dcf.py                  # 6-step DCF valuation — P1b
│   │   ├── lbo.py                  # LBO modeling — P2c
│   │   ├── earnings.py             # Earnings analysis — P2c
│   │   └── validators.py           # Per-step output validation
│   ├── agents/                     # P1b: dedicated sub-agents for pipelines
│   │   ├── data_agent.py           # P0: lead_agent handles all steps
│   │   ├── analysis_agent.py       # P1b: split into specialists
│   │   ├── modeling_agent.py
│   │   ├── synthesis_agent.py
│   │   └── report_agent.py
│   ├── skills/                     # P1a
│   │   ├── spec.py                 # Skill Pydantic model
│   │   ├── registry.py             # Load, search, validate, install
│   │   ├── loader.py               # Parse SKILL.md + frontmatter
│   │   └── composer.py             # Dependency resolution (P3a)
│   ├── data/
│   │   ├── interface.py            # DataProvider ABC
│   │   ├── layer.py                # P0: basic routing; P2b: full cache + fallback chain
│   │   ├── cache.py                # P0: basic get/set; P2b: stale fallback + TTL
│   │   └── providers/
│   │       ├── yfinance_provider.py
│   │       ├── fmp_provider.py     # P2a
│   │       ├── finnhub_provider.py # P2a
│   │       ├── sec_provider.py     # P2b
│   │       └── mcp_bridge.py       # P2b
│   ├── tools/                          # Shared tools used by pipelines
│   │   └── spreadsheet_gen.py          # Excel generation (openpyxl) — P2c
│   └── memory/                         # P3a
│       ├── store.py
│       └── context.py
│
├── adapters/
│   ├── finrobot_data.py            # Wraps finrobot.data_source.* — P2a
│   ├── finrobot_worker.py          # Subprocess JSON-RPC runner — P2a
│   └── anthropic_skill_loader.py   # Used by scripts/sync-skills.sh at vendor time (not runtime)
│
├── server.py                       # FastAPI + VercelAIAdapter
├── cli.py                          # Click CLI
├── sdk.py                          # FinAgent Python API — P3a
│
├── skills/                         # Built-in skills (pre-converted to FinAgent native format)
│   ├── financial-analysis/         # Converted from Anthropic plugins at vendor time
│   ├── investment-banking/         # by scripts/sync-skills.sh
│   ├── equity-research/
│   ├── private-equity/
│   ├── wealth-management/
│   └── UPSTREAM_VERSION.txt        # Source commit hash for traceability
│
├── desktop/                        # Electron + React — P1c
│   ├── electron/
│   └── renderer/
│
├── scripts/
│   ├── sync-skills.sh              # Pull Anthropic plugins + convert → FinAgent native format
│   └── build-electron.sh           # electron-builder + uv sidecar packaging (P3b)
│
├── tests/
│   ├── unit/
│   │   ├── test_pipelines/         # Pipeline step logic with TestModel
│   │   ├── test_validators/        # Output validation functions
│   │   └── test_data_layer/        # Provider + cache logic
│   ├── integration/
│   │   ├── test_equity_research/   # Full pipeline with real yfinance
│   │   └── test_comps/             # Full pipeline with real data
│   └── e2e/
│
├── pyproject.toml
├── LICENSE                         # Apache 2.0
├── README.md
└── ARCHITECTURE.md
```

---

## Defensive FAQ

**"Why not just use FinRobot directly?"**

FinRobot's data utilities are excellent — we adapt them. But its analysis pipeline is on AutoGen 0.2 (deprecated by Microsoft, active breakage in GitHub issues). Our pipelines provide the same code-enforced step guarantee with better methodology (Anthropic's institutional-grade skills vs hand-tuned prompts), better inter-step data passing (structured + validated vs free-text conversation), and model freedom (any model vs OpenAI-only).

**"How do you guarantee pipelines are as good as FinRobot's CoT?"**

Same enforcement mechanism (code-forced step order), different methodology source (Anthropic's institutional skills vs FinRobot's research-tuned CoT prompts), per-step output validation (FinRobot has none), and the same underlying data sources. Which approach produces better output on specific tasks is an empirical question — our integration test suite includes FinRobot benchmark comparisons to validate this claim, not assume it.

**"Why not just use DeerFlow?"**

DeerFlow is a generic SuperAgent. No financial data layer, no institutional skills, no financial analysis pipelines, requires Docker. You'd build everything from scratch.

**"Why not just use Claude Cowork + financial-services-plugins?"**

Proprietary platform. FinAgent makes those skills runnable with any model, on any platform, with code-enforced pipeline execution that Cowork doesn't expose.

**"This is just glue code."**

The pipeline system with per-step validation, the data layer with provider abstraction + fallback chain, the subprocess-isolated FinRobot adapter, and the two-mode orchestrator (conversational + pipeline) are original engineering. Adapters are necessary but not the product.

**"How does this compare to OpenBB, FinChat, Bloomberg Copilot?"**

These are the real competitive benchmarks — not FinRobot (which is an academic tool, not a product).

- **OpenBB Terminal**: Open-source, local-first, excellent financial data aggregation. But no AI pipelines, no skill system, no LLM-enforced analysis workflows. FinAgent's differentiator is the pipeline + skill layer on top of similar data sources. If OpenBB adds AI pipelines with step enforcement, that's the real threat.
- **FinChat**: AI-powered financial Q&A with high-quality output. But closed-source SaaS, single-model (proprietary), no local execution, no extensibility. FinAgent trades output polish for model-agnosticism, local data control, and extensible skill ecosystem.
- **Bloomberg Copilot**: Enterprise-grade, deeply integrated with Bloomberg data. Inaccessible to individual developers, quants, and small firms. FinAgent targets the audience Bloomberg doesn't serve.

The honest positioning: FinAgent occupies a gap — local + model-agnostic + code-enforced pipelines + extensible skills — that no mature open-source project fills today. Whether the gap is large enough to sustain a project depends on execution quality from P2a onward and whether developers actually build on it.

**"Will the skill ecosystem actually develop?"**

Unknown. 56 Anthropic built-in skills provide cold-start value, but "ecosystem" requires external contributors, and contributors don't appear by default. The realistic strategy:

1. P1a-P1b: Make built-in skills genuinely useful (measurable output quality improvement in pipelines).
2. Post-P1b: Author 5-10 high-quality example skills ourselves as templates.
3. Validate organic adoption before investing in skill marketplace, publishing tools, or community infrastructure.

If no one writes skills after step 2, the "ecosystem" claim should be downgraded to "extensible library" in project messaging.

**"Electron + PyInstaller is a known nightmare."**

It is — which is why we don't use PyInstaller. P3b uses **uv sidecar** instead.

uv is a single Rust-compiled binary (~15MB) that replaces pip, virtualenv, and PyInstaller in one shot. The Electron app bundles platform-specific uv binaries in `resources/` and runs `uv sync` on first launch to create a local venv from the locked `uv.lock`. After that, `uv run finagent serve --port <port>` starts the Python engine, and Electron connects to `localhost:<port>`.

Why this is fundamentally different from PyInstaller:
- **No binary repackaging** — uv installs native wheels directly. numpy/pandas just work, no DLL hell, no fragile hooks.
- **`uv.lock` guarantees reproducibility** across platforms — same as cargo.lock or yarn.lock.
- **Dependency upgrades** are trivial — update uv.lock and re-release. No re-tuning PyInstaller hooks.
- **uv binary itself is cross-platform** — electron-builder selects the right one per OS at build time.

The only trade-off: first launch requires internet to install Python deps (~30-60 seconds with a loading screen). For offline installs: pre-download wheel cache into `resources/wheels/`, then `uv sync --offline --find-links ./wheels/` — adds ~150-200MB to package size but removes the network requirement.

This approach affects only `desktop/electron/main.ts` (launch logic) and `scripts/build-electron.sh` (packaging). The engine layer is completely unchanged.

### Value Validation Milestones

P0 and P1a only prove the framework runs — not that it produces value. The real validation points:

| Milestone | What it proves | When |
|---|---|---|
| P1b complete | Pipeline output quality with skill injection + strict validators. **Compare equity research output vs FinChat on same tickers.** If no quality advantage, reassess project direction. | After P1b |
| P2a complete | FinRobot data adapter works. Multi-source data (FMP + Finnhub + yfinance) actually improves output vs yfinance-only. | After P2a |
| 5 external skills authored | Someone outside the core team wrote a skill and it works. Ecosystem is viable. | Post-P1b, ongoing |
| First non-author user runs `finagent research` and finds output useful | Product-market fit signal. | Anytime post-P1b |

If P1b output quality doesn't meaningfully exceed a well-prompted single Claude/GPT-4o call with the same data, the pipeline architecture is over-engineering and the project should pivot to a simpler tool.

---

## Implementation Priority

| Phase | Deliverable | What's in it |
|---|---|---|
| **P0** | `finagent run` + `finagent research AAPL` | Lead agent handles both modes. Mode A: direct tool calls. Mode B: equity_research pipeline (all 5 steps, all using lead_agent — no sub-agents yet). yfinance provider + CLI. Proves Pipeline.execute() enforced sequencing works. See P0 acceptance criteria below. |
| P1a | Skill runtime | Loader + registry + `activate_skill` tool. Skills in repo are already in FinAgent native format (converted at vendor time — see below). Must ship before P1b because strict validators depend on skill methodology injection. |
| P1b | Dedicated sub-agents + full pipelines | Split lead_agent into data/analysis/modeling/synthesis/report agents. Complete equity_research (5 steps) + comps + dcf pipelines. Strict validators on (skill methodology now available from P1a). |
| P1c | Desktop app | Electron + React + useChat + pipeline progress UI |
| P2a | FinRobot data adapter | Subprocess isolation, FMP + Finnhub providers |
| P2b | Full data layer | SEC EDGAR, cache, fallback chain, MCP bridge |
| P2c | More pipelines + tools | LBO, earnings, IC memo pipelines. spreadsheet_gen tool (openpyxl). |
| P3a | Advanced | Memory, skill composition, Python SDK |
| P3b | Packaging | uv sidecar + electron-builder. Bundled uv binary creates venv on first launch; no PyInstaller. |

**P0 scope note**: P0 uses one lead_agent for all pipeline steps. This is intentional — the goal is proving the Pipeline framework forces step order, not optimizing per-step agent quality. Sub-agent specialization is P1b.

**P0 acceptance criteria** — P0 is done when both of these pass:

1. **Mode A**: `finagent run "What's AAPL's PE ratio?"` → returns a correct answer with real yfinance data in < 10 seconds.
2. **Mode B**: `finagent research AAPL` → outputs a Markdown report containing:
   - Financial data summary (revenue, EBITDA, margins — real yfinance data, not hallucinated)
   - Peer company list (minimum 3 peers with justification)
   - Valuation range (with methodology stated)
   - Pipeline progress visible in terminal (Step 1/5... Step 2/5... Step 3/5... Step 4/5... Step 5/5...)
   - Total execution time < 60 seconds on Claude Sonnet 4.6
   - Each pipeline step provably ran (logged), no steps skipped

If Mode B output quality is poor (vague, no real numbers, hallucinated data), that's a P1a problem (skill methodology not yet injected). But the pipeline must demonstrably execute all steps in order with real data flowing between them.

**Vendored skill format note**: The `skills/` directory in the repo stores Anthropic's skills **already converted to FinAgent native format**. The conversion happens in `scripts/sync-skills.sh` at vendor time, not at runtime. This means P1a (skill runtime) can read them immediately without waiting for a separate Anthropic format adapter. `UPSTREAM_VERSION.txt` records the source commit hash for traceability.

---

## License Compatibility

| Component | License | Commercial Use |
|---|---|---|
| FinAgent (this project) | Apache 2.0 | ✅ |
| FinRobot (upstream, data utils only) | Apache 2.0 | ✅ |
| financial-services-plugins (upstream) | Apache 2.0 | ✅ |
| PydanticAI | MIT | ✅ |
| Electron | MIT | ✅ |
| FastAPI | MIT | ✅ |