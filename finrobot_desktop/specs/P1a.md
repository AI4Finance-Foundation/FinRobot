# P1a Spec — Skill Runtime

## Goal

Skill runtime — load, search, list, and inject 56 vendored Anthropic skills into pipeline steps and conversational `activate_skill` tool.

## Status: 🔄 In Progress

## Acceptance Criteria

All must pass:

1. `finagent skill list` → prints all 56 skills grouped by domain, with id + name
2. `finagent skill search "comps"` → returns matching skills with id + name + description snippet
3. Pipeline skill injection: `finagent research AAPL` with skills loaded → step 2-4 outputs contain methodology keywords from the injected skill (e.g. "EV/EBITDA" or "trading multiples" for peer_analysis, "DCF" or "discount rate" for financial_modeling). Validated by `@pytest.mark.integration` test with real LLM.
4. `python -m pytest tests/ -x -v --tb=short` — all unit tests pass (P0 + P1a, including updated P0 orchestrator tests)
5. `activate_skill("comps-analysis")` returns full skill content (not "Skill system is not yet available")

## Approved Dependencies

All P0 dependencies plus:

```
pyyaml              # YAML frontmatter parsing
```

## Scope Constraints

Do not write code for P1b+ features. If you need something from a future phase, write a `# TODO(P1b): ...` comment and move on. Specifically:

- Do NOT import finrobot (P2a)
- Do NOT write sub-agents (P1b)
- Do NOT write Electron/React code (P1c)
- Do NOT write memory system (P3a)
- Do NOT write sdk.py (P3a)
- Do NOT write skill composition/dependency resolution (P3a)
- Do NOT write requires_data/requires_tools enforcement (P1b/P2c)

## Key Design Decisions

| Decision | Choice |
|---|---|
| Skill storage | `skills/{domain}/{id}/SKILL.md` — one directory per skill |
| Skills location | Project root `skills/` directory, resolved via `FinAgentSettings.skills_dir` |
| Skill injection | Full Markdown body injected into LLM context (no section splitting) |
| Search mechanism | Keyword matching on name + triggers + description (no vector search) |
| LLM skill selection | LLM sees `list_summary()` in system prompt → calls `activate_skill(id)` → full content injected |
| Tool registration | `@agent.tool` decorator inside factory function scope (not module-level) |
| Upstream conversion | `id` from path, `version` 1.0.0, `author` anthropic, `domain` from directory, `triggers` from name/desc, `requires_*` all empty |

## Upstream Source

56 skills from `~/Desktop/code/Fin/financial-services-plugins/`

**Two upstream formats exist** (conversion script must handle both):
- **Format A** (45 skills, Anthropic self-authored): No YAML frontmatter. Name is H1 heading, description is a `description:` text line, triggers embedded as `Triggers on "..."` in description.
- **Format B** (11 skills, partner-built e.g. spglobal/lseg): Standard YAML frontmatter with `name` + `description` fields.

---

## ⚠️ P0 Breaking Changes

P1a requires refactoring orchestrator.py from module-level agent to factory function. This breaks P0's module-level `lead_agent` export. The following P0 code must be updated as part of File 18:

1. **`finagent/engine/orchestrator.py`**: `lead_agent = Agent(...)` at module level → `create_lead_agent()` factory
2. **`tests/unit/test_orchestrator.py`**: `from ... import lead_agent` → `agent = create_lead_agent(test_settings)`
3. **`finagent/server.py`**: module-level `import lead_agent` → lifespan initialization with `create_lead_agent()`
4. **`finagent/cli.py`**: Remove `FakeCtx` hack, `research` command calls `pipeline.execute(deps, ticker)` directly
5. **`finagent/engine/pipelines/base.py`**: `Pipeline.execute(ctx, ticker)` → `Pipeline.execute(deps, ticker)` — accepts `FinAgentDeps` instead of `RunContext` (eliminates need for FakeCtx entirely)

---

## Implementation Order — Detailed Specs

### File 13: `finagent/engine/skills/spec.py`

**Purpose**: Skill Pydantic model — the in-memory representation of a loaded skill.

**Also create**: `finagent/engine/skills/__init__.py` (empty file, required for Python package).

**Class**:
```python
from pydantic import BaseModel

class Skill(BaseModel):
    """A loaded skill with metadata and content."""
    id: str                              # e.g. "comps-analysis"
    name: str                            # e.g. "Comparable Company Analysis"
    version: str                         # e.g. "1.0.0"
    author: str                          # e.g. "anthropic"
    domain: str                          # e.g. "equity-research"
    description: str                     # first paragraph of body, or frontmatter description
    triggers: list[str] = []             # search keywords
    requires_data: list[dict] = []       # parsed but not enforced until P1b
    requires_tools: list[str] = []       # parsed but not enforced until P2c
    requires_skills: list[str] = []      # parsed but not enforced until P3a
    compatible_models: list[str] = []    # optional, informational only
    full_content: str                    # entire Markdown body (everything after frontmatter)
    source_path: str                     # filesystem path to SKILL.md

    def summary(self) -> str:
        """One-line summary for LLM context: '{id}: {name} — {description[:80]}'"""
        desc = self.description[:80] + "..." if len(self.description) > 80 else self.description
        return f"{self.id}: {self.name} — {desc}"
```

**Key details**:
- `full_content` is the complete Markdown body below the YAML frontmatter `---` fence. No section splitting.
- `description` is extracted from either: (a) `description` field in YAML frontmatter, or (b) the first non-empty paragraph of the Markdown body if frontmatter has no description. Loader handles this logic.
- `summary()` is what gets aggregated into `list_summary()` — must be compact enough that 56 summaries fit in ~4K tokens.
- **Don't forget `finagent/engine/skills/__init__.py`** — missing it causes ImportError.

**Tests** (`tests/unit/test_skill_spec.py`):
- Skill model validates with all required fields
- Skill model with only required fields (empty optional lists) works
- summary() returns expected format
- summary() truncates long descriptions at 80 chars

**Dependencies**: None

---

### File 14: `finagent/engine/skills/loader.py`

**Purpose**: Parse a single SKILL.md file into a Skill model. Handles YAML frontmatter extraction + Markdown body separation.

**Functions**:
```python
import yaml
from pathlib import Path
from finagent.engine.skills.spec import Skill

def load_skill(path: Path) -> Skill:
    """Load a single SKILL.md file into a Skill model.
    
    Expected format:
    ---
    id: comps-analysis
    name: Comparable Company Analysis
    version: 1.0.0
    author: anthropic
    domain: equity-research
    triggers: [...]
    ---
    
    # Comparable Company Analysis
    ## Workflow
    ...
    """

def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Split YAML frontmatter from Markdown body.
    Returns (frontmatter_dict, markdown_body).
    Raises SkillLoadError if no valid frontmatter found."""

def _extract_description(frontmatter: dict, body: str) -> str:
    """Get description from frontmatter, or fall back to first paragraph of body."""

class SkillLoadError(Exception):
    """Raised when a skill file cannot be parsed."""
```

**Key details**:
- Uses `pyyaml` for YAML parsing
- Frontmatter is delimited by `---` at start and end (standard YAML frontmatter convention)
- If frontmatter is missing required fields (`id`, `name`), raise `SkillLoadError`
- `version` defaults to `"1.0.0"` if missing
- `author` defaults to `"unknown"` if missing
- `domain` defaults to `"general"` if missing
- All list fields default to `[]` if missing
- `source_path` is set to `str(path)` for traceability

**Tests** (`tests/unit/test_skill_loader.py`):
- load_skill with valid SKILL.md returns correct Skill
- load_skill extracts frontmatter and body correctly
- load_skill with missing `id` raises SkillLoadError
- load_skill with missing `name` raises SkillLoadError
- load_skill with missing optional fields uses defaults
- _parse_frontmatter correctly splits content
- _parse_frontmatter with no frontmatter raises SkillLoadError
- _extract_description prefers frontmatter description
- _extract_description falls back to first paragraph of body

Create test fixture: `tests/fixtures/skills/test-domain/test-skill/SKILL.md` with valid content.

**Dependencies**: File 13

---

### File 15: `finagent/engine/skills/registry.py`

**Purpose**: Load all skills from disk, provide search/get/list operations.

**Class**:
```python
from pathlib import Path
from finagent.engine.skills.spec import Skill
from finagent.engine.skills.loader import load_skill, SkillLoadError

class SkillRegistry:
    """Loads and indexes all skills from a directory tree.
    
    Expected directory structure:
    skills/
    ├── equity-research/
    │   ├── comps-analysis/
    │   │   └── SKILL.md
    │   └── dcf-model/
    │       └── SKILL.md
    ├── investment-banking/
    │   └── lbo-model/
    │       └── SKILL.md
    └── ...
    """
    
    def __init__(self, skills_dir: Path):
        self._skills: dict[str, Skill] = {}    # id → Skill
        self._load_all(skills_dir)
    
    def _load_all(self, skills_dir: Path) -> None:
        """Walk skills_dir, find all SKILL.md files, load each.
        Log warning and skip on SkillLoadError (don't crash on one bad skill)."""
    
    def get(self, skill_id: str) -> Skill | None:
        """Get skill by exact id. Returns None if not found."""
    
    def search(self, query: str) -> list[Skill]:
        """Search skills by keyword matching against name, triggers, description.
        Case-insensitive. Returns skills sorted by relevance (name match > trigger match > description match)."""
    
    def list_all(self) -> list[Skill]:
        """Return all loaded skills, sorted by domain then id."""
    
    def list_summary(self) -> str:
        """Compact summary of all skills for LLM context window.
        Format:
        
        ## Available Skills
        
        **equity-research**
        - comps-analysis: Comparable Company Analysis — Builds a trading comps table...
        - dcf-model: DCF Valuation Model — Constructs a discounted cash flow...
        
        **investment-banking**
        - lbo-model: LBO Analysis — ...
        
        Use activate_skill(skill_id) to load full methodology.
        """
    
    def list_ids(self) -> list[str]:
        """Return all skill ids. Used by activate_skill error message."""
    
    @property
    def count(self) -> int:
        return len(self._skills)
```

**Key details**:
- Constructor walks the directory tree looking for `SKILL.md` files. Pattern: `skills_dir/**/SKILL.md`
- If a SKILL.md fails to parse, log warning and continue (don't crash the whole registry)
- `search()` scoring: +3 for query in name, +2 for query in any trigger, +1 for query in description. Return all with score > 0, sorted descending.
- `list_summary()` groups by domain. This string gets appended to the agent's system prompt so the LLM knows what skills are available.
- `list_ids()` is used by `activate_skill` tool when skill not found: "Unknown skill. Available: [...]"

**Tests** (`tests/unit/test_skill_registry.py`):
- Registry loads skills from test fixtures directory
- Registry skips bad SKILL.md with warning (doesn't crash)
- get() returns correct skill by id
- get() returns None for unknown id
- search("comps") returns skills with "comps" in name/triggers
- search() is case-insensitive
- search() returns empty list for no match
- list_all() returns all skills sorted by domain then id
- list_summary() contains all skill ids grouped by domain
- list_ids() returns list of all ids
- count returns correct number

Create additional test fixtures: 2-3 skills in different domains under `tests/fixtures/skills/`.

**Dependencies**: Files 13, 14

---

### File 16: `scripts/convert_skills.py`

**Purpose**: One-time conversion script. Reads all 56 upstream Anthropic skills from `~/Desktop/code/Fin/financial-services-plugins/` and writes them in FinAgent native format to `skills/`.

**Also create**: `scripts/` directory (does not exist in current repo).

**⚠️ Critical: Upstream has TWO formats**

The upstream repo contains two different SKILL.md formats:

**Format A — Anthropic self-authored skills (45 of 56)**:
```markdown
# Comparable Company Analysis

description: Builds a trading comps table with EV/EBITDA, P/E, and revenue multiples. Triggers on "comps", "comparable companies", "peer analysis", "trading multiples".

## Workflow
[step-by-step methodology...]
```
No YAML frontmatter. Name is H1 heading. Description is a plain text line starting with `description:`. Triggers are embedded in the description text after `Triggers on`.

**Format B — Partner-built skills (11 of 56, e.g. spglobal/lseg)**:
```markdown
---
name: fx-carry-trade
description: Evaluate FX carry trade opportunities...
---

# FX Carry Trade Analysis
[body...]
```
Standard YAML frontmatter with `---` delimiters.

**The conversion script MUST handle both formats.** If it only handles Format B, 45 skills will fail to parse and `registry.count` will be 11 instead of 56, failing acceptance criteria.

**Script logic**:
```python
"""Convert Anthropic financial-services-plugins to FinAgent native skill format.

Usage:
    python scripts/convert_skills.py --source ~/Desktop/code/Fin/financial-services-plugins/ --output skills/
"""
import argparse
import re
import yaml
from pathlib import Path

def parse_upstream_skill(content: str) -> tuple[str, str, str]:
    """Detect upstream format and extract (name, description, body).
    
    Format A (no frontmatter): H1 heading + description: line + body
    Format B (YAML frontmatter): --- delimited YAML + body
    """
    if content.startswith("---"):
        # Format B: YAML frontmatter
        fm, body = _parse_yaml_frontmatter(content)
        return fm["name"], fm.get("description", ""), body
    else:
        # Format A: H1 heading + description: text line
        lines = content.splitlines()
        name = lines[0].lstrip("# ").strip() if lines else "Unknown"
        desc_line = next((l for l in lines if l.strip().startswith("description:")), "")
        description = desc_line.split("description:", 1)[-1].strip() if desc_line else ""
        body = content  # keep full body unchanged
        return name, description, body

def _parse_yaml_frontmatter(content: str) -> tuple[dict, str]:
    """Split YAML frontmatter from body for Format B files."""

def extract_triggers(name: str, description: str) -> list[str]:
    """Extract keyword triggers. Priority order:
    
    1. Parse explicit 'Triggers on "comps", "peer analysis"' from description (Format A)
       → regex: Triggers on (.+)$ then extract quoted strings
    2. If no explicit triggers found, fall back to splitting name into lowercase words
    
    Examples:
    - description='...Triggers on "comps", "peer analysis".' → ["comps", "peer analysis"]
    - name='Comparable Company Analysis', no triggers in desc → ["comparable", "company", "analysis"]
    """

def generate_id(name: str, source_path: Path) -> str:
    """Generate id from upstream directory name (NOT from skill name).
    
    source_path = .../comps-analysis/SKILL.md
    → source_path.parent.name = "comps-analysis"
    
    This MUST match the skill_section strings hardcoded in orchestrator.py
    (e.g. "comps-analysis", "dcf-model", "initiating-coverage").
    Do NOT generate from name — 'Comparable Company Analysis' → 'comparable-company-analysis'
    would NOT match 'comps-analysis' and skill injection would silently fail.
    """
    return source_path.parent.name

def infer_domain(source_path: Path) -> str:
    """Infer domain from upstream directory structure.
    Map upstream directory names to FinAgent domains."""

def convert_skill(source_path: Path, output_dir: Path) -> None:
    """Convert a single upstream skill to FinAgent native format.
    
    1. Read SKILL.md
    2. parse_upstream_skill() to detect format and extract name/desc/body
    3. generate_id(), infer_domain(), extract_triggers()
    4. Write FinAgent native format: enriched YAML frontmatter + original body
    """

def main():
    parser = argparse.ArgumentParser(description="Convert Anthropic skills to FinAgent format")
    parser.add_argument("--source", required=True, help="Path to financial-services-plugins/")
    parser.add_argument("--output", default="skills/", help="Output directory")
    args = parser.parse_args()
    
    source = Path(args.source)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    
    # Walk source, find all SKILL.md files
    # Convert each with parse_upstream_skill() (handles both formats)
    # Write UPSTREAM_VERSION.txt with source path + timestamp
    # Print summary: X skills converted (Y Format A, Z Format B)
    
    print(f"Converted {count} skills to {output}")
```

**Key details**:
- This is a **one-time script**, not a runtime component. It runs once to populate `skills/`.
- **Must handle both Format A (45 skills) and Format B (11 skills)** — see `parse_upstream_skill()`
- `extract_triggers()` prioritizes explicit `Triggers on "..."` from upstream descriptions, falls back to name-splitting
- Writes FinAgent format: enriched YAML frontmatter + original body unchanged
- Creates `skills/UPSTREAM_VERSION.txt` with source path and conversion timestamp
- Does NOT modify upstream files
- The `skills/` directory (output) gets committed to git
- Print conversion summary including format breakdown for verification

**Tests**: No unit tests for the script itself — it's run once and the output (the converted skills) is validated by the SkillRegistry tests loading them. However, after running, manually verify: `find skills/ -name SKILL.md | wc -l` should output `56`.

**Dependencies**: None (standalone script)

---

### File 17: Integration hookup — `finagent/engine/deps.py` + `finagent/config.py` (modify)

**Purpose**: Wire SkillRegistry into FinAgentDeps. Add `skills_dir` to settings for unified path resolution.

**Changes to `finagent/config.py`**:
```python
class FinAgentSettings(BaseSettings):
    # ... existing fields ...
    skills_dir: str = "skills"   # path to vendored skills directory (relative to project root or absolute)
```

**Also update `.env.example`** — add:
```ini
# Skills directory (relative to project root)
# FINAGENT_SKILLS_DIR=skills
```

**Changes to `finagent/engine/deps.py`**:
```python
from dataclasses import dataclass
from finagent.engine.data.layer import DataLayer
from finagent.engine.skills.registry import SkillRegistry  # NEW
from finagent.config import FinAgentSettings

@dataclass
class FinAgentDeps:
    data_layer: DataLayer
    settings: FinAgentSettings
    skill_runtime: SkillRegistry | None = None   # P0: None → P1a: SkillRegistry instance
```

**Key details**:
- `skill_runtime` type changes from `object | None` to `SkillRegistry | None`
- Still defaults to None so P0 code continues to work unmodified
- Callers (cli.py, server.py) are responsible for creating SkillRegistry and passing it
- `settings.skills_dir` provides a single source of truth for where skills live — all callers use this instead of hardcoding paths

**Tests**: Existing P0 tests must still pass (skill_runtime=None path unchanged). Add one test for new `skills_dir` default in test_config.py.

**Dependencies**: File 15

---

### File 18: Integration hookup — `finagent/engine/orchestrator.py` + `server.py` + P0 tests (major refactor)

**Purpose**: Refactor from module-level agent to factory function. Wire skill summary into agent instructions. Update all callers.

**This is the most complex P1a file. It touches orchestrator.py, server.py, and P0 tests.**

#### 18a. Refactor orchestrator.py

Replace module-level `lead_agent = Agent(...)` with `create_lead_agent()` factory:

```python
from pathlib import Path
from pydantic_ai import Agent, RunContext
from finagent.engine.deps import FinAgentDeps
from finagent.engine.skills.registry import SkillRegistry
from finagent.config import FinAgentSettings

def create_lead_agent(settings: FinAgentSettings, skill_registry: SkillRegistry | None = None) -> Agent:
    """Factory: create lead agent with tools and instructions.
    
    Tool registration uses @agent.tool decorator inside factory scope.
    The decorator targets the `agent` instance created within this function.
    This is a standard pydantic-ai pattern — equivalent to module-level
    decoration but scoped to the factory-created instance.
    """
    instructions = (Path(__file__).parent / "instructions.md").read_text()
    if skill_registry:
        instructions += "\n\n" + skill_registry.list_summary()
    
    agent = Agent(
        settings.model_name,
        deps_type=FinAgentDeps,
        instructions=instructions,
    )
    
    # --- Tool registration (decorator targets the local `agent` instance) ---
    
    @agent.tool
    async def query_financial_data(
        ctx: RunContext[FinAgentDeps], ticker: str, data_type: str
    ) -> str:
        """Fetch financial data for quick questions.
        data_type: financials | price | news (filings available from P2b)"""
        result = await ctx.deps.data_layer.fetch(data_type, ticker)
        return result.to_context_string()
    
    @agent.tool
    async def activate_skill(ctx: RunContext[FinAgentDeps], skill_id: str) -> str:
        """Activate a skill for ad-hoc professional workflows.
        Use this for tasks that don't have a dedicated pipeline."""
        if not ctx.deps.skill_runtime:
            return "Skill system is not yet available. Use direct data queries or pipeline commands instead."
        skill = ctx.deps.skill_runtime.get(skill_id)
        if not skill:
            return f"Unknown skill. Available: {ctx.deps.skill_runtime.list_ids()}"
        return skill.full_content
    
    # Pipeline tool — import here to avoid circular dependency
    from finagent.engine.pipelines.equity_research import create_equity_research_pipeline
    equity_pipeline = create_equity_research_pipeline(agent)
    
    @agent.tool
    async def run_equity_research(ctx: RunContext[FinAgentDeps], ticker: str) -> str:
        """Generate a comprehensive equity research report.
        Uses a multi-step enforced pipeline. Takes 30-120 seconds."""
        result = await equity_pipeline.execute(ctx.deps, ticker)  # pass ctx.deps, not ctx
        return result.format_summary()
    
    return agent
```

#### 18b. Update server.py

Replace module-level import with lifespan initialization:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pathlib import Path
from finagent.config import get_settings
from finagent.engine.orchestrator import create_lead_agent
from finagent.engine.deps import FinAgentDeps
from finagent.engine.data.layer import DataLayer
from finagent.engine.data.cache import DataCache
from finagent.engine.data.providers.yfinance_provider import YFinanceProvider
from finagent.engine.skills.registry import SkillRegistry

@asynccontextmanager
async def lifespan(app):
    settings = get_settings()
    settings.apply_api_keys()
    
    # Load skills if available
    skills_path = Path(settings.skills_dir)
    registry = SkillRegistry(skills_path) if skills_path.exists() else None
    
    # Create agent and deps
    agent = create_lead_agent(settings, skill_registry=registry)
    cache = DataCache(settings.cache_db_path)
    data_layer = DataLayer(providers=[YFinanceProvider()], cache=cache)
    deps = FinAgentDeps(data_layer=data_layer, settings=settings, skill_runtime=registry)
    
    app.state.agent = agent
    app.state.deps = deps
    yield

app = FastAPI(title="FinAgent", lifespan=lifespan)

@app.post("/chat")
async def chat(request: Request) -> Response:
    return await VercelAIAdapter.dispatch_request(
        request, agent=request.app.state.agent, deps=request.app.state.deps
    )

@app.get("/health")
async def health():
    return {"status": "ready", "phase": "P1a"}
```

#### 18c. Update P0 orchestrator tests

All tests that imported `lead_agent` must use `create_lead_agent()` instead:

```python
# BEFORE (P0):
from finagent.engine.orchestrator import lead_agent

def test_agent_has_tools():
    tool_names = [t.name for t in lead_agent.tools]
    assert "query_financial_data" in tool_names

# AFTER (P1a):
from finagent.engine.orchestrator import create_lead_agent
from finagent.config import get_settings

def test_agent_has_tools():
    """Verify tools are registered by running agent with TestModel
    and checking it can select the expected tools."""
    settings = get_settings(model_name="test")
    agent = create_lead_agent(settings)
    # Use functional test: run agent with TestModel, verify tool calls
    # Do NOT use agent._function_tools or other private APIs
```

**Tests** (`tests/unit/test_orchestrator.py` — rewrite):
- create_lead_agent(settings) returns Agent with all 3 tools registered
- create_lead_agent(settings, skill_registry=None) → instructions don't contain "Available Skills"
- create_lead_agent(settings, skill_registry=mock_registry) → instructions contain skill summaries
- activate_skill with skill_runtime=None returns "not available"
- activate_skill with skill_runtime set returns skill full_content
- activate_skill with unknown id returns error with available ids list
- run_equity_research tool exists and is callable

**Dependencies**: Files 13, 15, existing Files 7, 8, 9, 10

---

### File 19: Integration hookup — `finagent/cli.py` (modify)

**Purpose**: Add `finagent skill list` and `finagent skill search` commands. Wire SkillRegistry into existing `run` and `research` commands. Remove `FakeCtx` hack.

**New CLI commands**:
```python
from finagent.engine.skills.registry import SkillRegistry
from finagent.engine.orchestrator import create_lead_agent
from pathlib import Path

@cli.group()
def skill():
    """Manage FinAgent skills."""
    pass

@skill.command("list")
def skill_list():
    """List all available skills grouped by domain."""
    settings = get_settings()
    skills_path = Path(settings.skills_dir)
    if not skills_path.exists():
        click.echo("No skills directory found. Run convert_skills.py first.")
        return
    registry = SkillRegistry(skills_path)
    for s in registry.list_all():
        click.echo(f"  [{s.domain}] {s.id}: {s.name}")

@skill.command("search")
@click.argument("query")
def skill_search(query: str):
    """Search skills by keyword."""
    settings = get_settings()
    skills_path = Path(settings.skills_dir)
    if not skills_path.exists():
        click.echo("No skills directory found. Run convert_skills.py first.")
        return
    registry = SkillRegistry(skills_path)
    results = registry.search(query)
    if not results:
        click.echo(f"No skills matching '{query}'")
        return
    for s in results:
        click.echo(f"  {s.id}: {s.name}")
        click.echo(f"    {s.description[:120]}")
```

**Changes to existing commands** — unified helper + FakeCtx removal:
```python
def _build_runtime(model: str | None = None):
    """Shared setup for run/research commands. Returns (agent, deps)."""
    settings = get_settings()
    if model:
        settings = get_settings(model_name=model)
    settings.apply_api_keys()
    
    # Load skills if available
    skills_path = Path(settings.skills_dir)
    # NOTE: skills_dir is relative to cwd. P1a convention: always run from project root.
    registry = SkillRegistry(skills_path) if skills_path.exists() else None
    
    agent = create_lead_agent(settings, skill_registry=registry)
    cache = DataCache(settings.cache_db_path)
    data_layer = DataLayer(providers=[YFinanceProvider()], cache=cache)
    deps = FinAgentDeps(data_layer=data_layer, settings=settings, skill_runtime=registry)
    
    return agent, deps

@cli.command()
@click.argument("question")
@click.option("--model", default=None)
def run(question: str, model: str | None):
    """Ask a quick financial question (Mode A)."""
    agent, deps = _build_runtime(model)
    result = agent.run_sync(question, deps=deps)
    click.echo(result.output)

@cli.command()
@click.argument("ticker")
@click.option("--model", default=None)
def research(ticker: str, model: str | None):
    """Run equity research pipeline on a ticker (Mode B).
    
    Calls pipeline.execute() directly — does NOT rely on LLM tool selection.
    This is deterministic: the pipeline always runs all 5 steps regardless of model.
    """
    agent, deps = _build_runtime(model)
    
    # Direct pipeline invocation (deterministic, no LLM routing)
    from finagent.engine.pipelines.equity_research import create_equity_research_pipeline
    pipeline = create_equity_research_pipeline(agent)
    
    import asyncio
    result = asyncio.run(pipeline.execute(deps, ticker))
    click.echo(result.format_summary())
```

**⚠️ Pipeline.execute() signature change (P1a refactor)**:

P0's `pipeline.execute(ctx, ticker)` takes a `RunContext`. But `RunContext` is pydantic-ai internal — it's only available inside a tool call or `agent.run()`.

P1a changes `Pipeline.execute()` to accept `FinAgentDeps` directly instead of `RunContext`:

```python
# BEFORE (P0):
async def execute(self, ctx: RunContext[FinAgentDeps], ticker: str, **kwargs) -> PipelineResult:
    # accesses ctx.deps.data_layer, ctx.deps.skill_runtime

# AFTER (P1a):
async def execute(self, deps: FinAgentDeps, ticker: str, **kwargs) -> PipelineResult:
    # accesses deps.data_layer, deps.skill_runtime directly
```

This also simplifies the `run_equity_research` tool in orchestrator.py:
```python
@agent.tool
async def run_equity_research(ctx: RunContext[FinAgentDeps], ticker: str) -> str:
    result = await equity_pipeline.execute(ctx.deps, ticker)  # pass ctx.deps, not ctx
    return result.format_summary()
```

**Update `base.py` (File 6)** accordingly — change all `ctx.deps.X` references inside Pipeline to `deps.X`. This is a minor refactor of P0 code that must be done in File 18.

**Key details**:
- `FakeCtx` hack removed — `research` calls `pipeline.execute(deps, ticker)` directly
- `_build_runtime()` helper deduplicates setup between `run`, `research`, and future commands
- Skills path comes from `settings.skills_dir` (single source of truth, set in File 17)
- Skills path is relative to cwd — P1a convention: always run from project root (documented in comment)
- Graceful degradation: if skills dir doesn't exist, registry is None, agent works without skills (P0 behavior)
- `run` command goes through LLM (Mode A — conversational)
- `research` command bypasses LLM routing, calls pipeline directly (Mode B — deterministic)

**Tests** (`tests/unit/test_cli.py` — extend existing):
- `finagent skill list` prints skills (use test fixtures)
- `finagent skill search "comps"` prints matching skills
- `finagent skill search "nonexistent"` prints "No skills matching"
- `finagent run` with skills dir present loads registry (mock)
- `finagent run` without skills dir still works (P0 behavior)
- `finagent research AAPL` calls pipeline.execute() directly (no LLM routing)

**Dependencies**: Files 15, 17, 18

---

### File 20: `tests/integration/test_p1a_acceptance.py`

**Purpose**: P1a acceptance gate. Validates skill system works end-to-end.

```python
import pytest
from pathlib import Path
from finagent.config import get_settings
from finagent.engine.skills.registry import SkillRegistry

# Skills dir resolved from settings, same as runtime code
SKILLS_DIR = Path(get_settings().skills_dir)

@pytest.mark.skipif(not SKILLS_DIR.exists(), reason="Vendored skills not present")
class TestP1aAcceptance:
    
    def test_all_skills_loaded(self):
        """P1a acceptance: all 56 vendored skills load without error."""
        registry = SkillRegistry(SKILLS_DIR)
        assert registry.count == 56, f"Expected 56 skills, got {registry.count}"
    
    def test_skill_list_by_domain(self):
        """P1a acceptance: skills are organized by domain."""
        registry = SkillRegistry(SKILLS_DIR)
        domains = set(s.domain for s in registry.list_all())
        assert len(domains) >= 3, f"Expected at least 3 domains, got {domains}"
    
    def test_skill_search_comps(self):
        """P1a acceptance: searching 'comps' finds comps-analysis skill."""
        registry = SkillRegistry(SKILLS_DIR)
        results = registry.search("comps")
        ids = [s.id for s in results]
        assert any("comps" in id for id in ids), f"Expected comps skill in results: {ids}"
    
    def test_skill_content_not_empty(self):
        """P1a acceptance: every skill has non-empty full_content."""
        registry = SkillRegistry(SKILLS_DIR)
        for skill in registry.list_all():
            assert len(skill.full_content.strip()) > 100, \
                f"Skill {skill.id} has suspiciously short content ({len(skill.full_content)} chars)"
    
    def test_list_summary_fits_context(self):
        """P1a acceptance: list_summary for 56 skills is under 6000 chars (~1500 tokens)."""
        registry = SkillRegistry(SKILLS_DIR)
        summary = registry.list_summary()
        assert len(summary) < 6000, f"list_summary too long: {len(summary)} chars"
    
    def test_activate_skill_returns_content(self):
        """P1a acceptance: get() returns full skill content ready for injection."""
        registry = SkillRegistry(SKILLS_DIR)
        skill = registry.get("comps-analysis") or registry.list_all()[0]
        assert "##" in skill.full_content, "Skill content should have Markdown headers"

    @pytest.mark.integration
    @pytest.mark.slow
    def test_pipeline_with_skill_injection(self):
        """P1a acceptance: equity research pipeline with skill injection
        produces methodology-aware output.
        
        Validates that when skills are loaded, pipeline steps 2-4 produce
        output containing domain-specific methodology terms that would NOT
        appear without skill injection.
        
        Expected methodology keywords by step:
        - step 2 (peer_analysis, skill: comps-analysis): "EV/EBITDA", "trading multiples", or "comparable"
        - step 3 (financial_modeling, skill: dcf-model): "DCF", "discount rate", "WACC", or "terminal value"
        - step 4 (thesis, skill: initiating-coverage): "investment thesis", "catalyst", or "risk"
        """
        from finagent.engine.orchestrator import create_lead_agent
        from finagent.engine.deps import FinAgentDeps
        from finagent.engine.data.layer import DataLayer
        from finagent.engine.data.cache import DataCache
        from finagent.engine.data.providers.yfinance_provider import YFinanceProvider
        
        settings = get_settings()
        settings.apply_api_keys()
        registry = SkillRegistry(SKILLS_DIR)
        
        agent = create_lead_agent(settings, skill_registry=registry)
        cache = DataCache(":memory:")
        data_layer = DataLayer(providers=[YFinanceProvider()], cache=cache)
        deps = FinAgentDeps(data_layer=data_layer, settings=settings, skill_runtime=registry)
        
        result = agent.run_sync(
            "Write a comprehensive equity research report for AAPL. Use the run_equity_research tool.",
            deps=deps,
        )
        
        output = result.output.lower()
        methodology_keywords = ["ev/ebitda", "trading multiples", "dcf", "discount rate", 
                                "wacc", "terminal value", "investment thesis", "catalyst"]
        found = [kw for kw in methodology_keywords if kw in output]
        assert len(found) >= 2, \
            f"Expected methodology keywords in output, found only: {found}"
```

**Dependencies**: All P1a files + vendored skills in `skills/`

---

## Implementation Order Summary

| # | File | Type | Description |
|---|---|---|---|
| 13 | `finagent/engine/skills/spec.py` + `__init__.py` | New | Skill Pydantic model |
| 14 | `finagent/engine/skills/loader.py` | New | YAML frontmatter parser |
| 15 | `finagent/engine/skills/registry.py` | New | Load/search/list all skills |
| 16 | `scripts/convert_skills.py` | New | One-time upstream → native conversion |
| 17 | `finagent/engine/deps.py` + `config.py` | Modify | Wire SkillRegistry into deps, add skills_dir setting |
| 18 | `orchestrator.py` + `server.py` + P0 tests | Refactor | Factory function + skill injection + fix all callers |
| 19 | `finagent/cli.py` | Modify | `finagent skill list/search` + _build_runtime() + FakeCtx removed |
| 20 | `tests/integration/test_p1a_acceptance.py` | New | Acceptance gate |

**Order matters**: 13 → 14 → 15 → 16(run it) → 17 → 18 → 19 → 20

After File 16 runs, the `skills/` directory is populated. Files 17-19 wire it into the runtime. File 20 validates everything.

**File 18 is the riskiest** — it refactors orchestrator.py and cascades into server.py and P0 tests. Run full test suite after File 18 before proceeding.

---

## Things That Do NOT Exist in P1a

- Skill composition / dependency resolution (P3a)
- requires_data enforcement (P1b — validators use skill methodology)
- requires_tools enforcement (P2c)
- Skill install from git URL (P3a)
- Skill validation beyond frontmatter parsing (P3a)
- Section-level content extraction from skills (not needed — full injection)

If any code imports `SkillComposer` or tries to resolve `requires_skills`, you have a bug.

---

## Package Structure After P1a

```
finagent/
├── __init__.py
├── config.py                    # MODIFIED: added skills_dir setting
├── engine/
│   ├── __init__.py
│   ├── orchestrator.py          # REFACTORED: create_lead_agent() factory, scoped @agent.tool
│   ├── deps.py                  # MODIFIED: skill_runtime typed as SkillRegistry
│   ├── instructions.md
│   ├── data/                    # unchanged from P0
│   │   ├── __init__.py
│   │   ├── interface.py
│   │   ├── layer.py
│   │   ├── cache.py
│   │   └── providers/
│   │       ├── __init__.py
│   │       └── yfinance_provider.py
│   ├── pipelines/               # MODIFIED: base.py execute() takes deps instead of RunContext
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── equity_research.py
│   │   └── validators.py
│   └── skills/                  # NEW in P1a
│       ├── __init__.py          # DON'T FORGET THIS
│       ├── spec.py
│       ├── loader.py
│       └── registry.py
├── server.py                    # MODIFIED: lifespan init, no module-level agent import
├── cli.py                       # MODIFIED: skill subcommands + _build_runtime() + FakeCtx removed
│
├── skills/                      # NEW: vendored skills in PROJECT ROOT (not inside finagent/)
│   ├── equity-research/
│   │   ├── comps-analysis/
│   │   │   └── SKILL.md
│   │   ├── dcf-model/
│   │   │   └── SKILL.md
│   │   └── .../
│   ├── investment-banking/
│   │   └── .../
│   ├── financial-analysis/
│   │   └── .../
│   ├── private-equity/
│   │   └── .../
│   ├── wealth-management/
│   │   └── .../
│   └── UPSTREAM_VERSION.txt
│
├── scripts/
│   └── convert_skills.py        # NEW: one-time conversion script
│
└── tests/
    ├── unit/
    │   ├── test_skill_spec.py       # NEW
    │   ├── test_skill_loader.py     # NEW
    │   ├── test_skill_registry.py   # NEW
    │   ├── test_orchestrator.py     # REWRITTEN: uses create_lead_agent()
    │   ├── test_server.py           # UPDATED: tests lifespan pattern
    │   └── ... (other P0 tests unchanged)
    ├── fixtures/
    │   └── skills/                  # NEW: test fixtures
    │       ├── test-domain-a/
    │       │   └── test-skill-1/
    │       │       └── SKILL.md
    │       └── test-domain-b/
    │           └── test-skill-2/
    │               └── SKILL.md
    └── integration/
        ├── test_p0_acceptance.py
        └── test_p1a_acceptance.py   # NEW
```