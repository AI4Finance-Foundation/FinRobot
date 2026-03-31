import asyncio
from pathlib import Path

import click

from finagent.config import get_settings


def _build_deps(model: str | None = None):
    """Build deps only. No agent creation.
    Used by pipeline commands that create their own sub-agents."""
    from finagent.engine.data.cache import DataCache
    from finagent.engine.data.layer import DataLayer
    from finagent.engine.data.providers.yfinance_provider import YFinanceProvider
    from finagent.engine.deps import FinAgentDeps
    from finagent.engine.skills.registry import SkillRegistry

    settings = get_settings()
    if model:
        settings = get_settings(model_name=model)
    settings.apply_api_keys()

    # Load skills if available
    skills_path = Path(settings.skills_dir)
    registry = SkillRegistry(skills_path) if skills_path.exists() else None

    cache = DataCache(settings.cache_db_path)
    data_layer = DataLayer(providers=[YFinanceProvider()], cache=cache)
    deps = FinAgentDeps(data_layer=data_layer, settings=settings, skill_runtime=registry)

    return deps


def _build_runtime(model: str | None = None):
    """Build lead agent + deps. Used by `run` command (Mode A)."""
    from finagent.engine.orchestrator import create_lead_agent

    deps = _build_deps(model)
    agent = create_lead_agent(deps.settings, skill_registry=deps.skill_runtime)
    return agent, deps


@click.group()
def cli() -> None:
    """FinAgent — financial AI agent platform."""


# --- Skill subcommands ---

@cli.group()
def skill():
    """Manage FinAgent skills."""


@skill.command("list")
def skill_list():
    """List all available skills grouped by domain."""
    from finagent.engine.skills.registry import SkillRegistry

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
    from finagent.engine.skills.registry import SkillRegistry

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


# --- Main commands ---

@cli.command()
@click.argument("question")
@click.option("--model", default=None, help="Override model, e.g. anthropic:claude-sonnet-4-6")
def run(question: str, model: str | None) -> None:
    """Ask a quick financial question (Mode A)."""
    agent, deps = _build_runtime(model)
    result = agent.run_sync(question, deps=deps)
    click.echo(result.output)


@cli.command()
@click.argument("ticker")
@click.option("--model", default=None, help="Override model, e.g. anthropic:claude-sonnet-4-6")
def research(ticker: str, model: str | None) -> None:
    """Run equity research pipeline on a ticker (Mode B).

    Calls pipeline.execute() directly — does NOT rely on LLM tool selection.
    This is deterministic: the pipeline always runs all 5 steps regardless of model.
    """
    deps = _build_deps(model)

    from finagent.engine.agents.factory import create_sub_agents
    from finagent.engine.pipelines.equity_research import create_equity_research_pipeline

    sub_agents = create_sub_agents(deps.settings, skill_registry=deps.skill_runtime)
    pipeline = create_equity_research_pipeline(sub_agents)

    result = asyncio.run(pipeline.execute(deps, ticker))
    click.echo(result.format_summary())


@cli.command()
@click.argument("ticker")
@click.option("--model", default=None, help="Override model, e.g. anthropic:claude-sonnet-4-6")
def comps(ticker: str, model: str | None) -> None:
    """Run comparable company analysis pipeline.

    # TODO(P2c): add --peers option when Pipeline.execute() supports kwargs forwarding
    """
    deps = _build_deps(model)

    from finagent.engine.agents.factory import create_sub_agents
    from finagent.engine.pipelines.comps import create_comps_pipeline

    sub_agents = create_sub_agents(deps.settings, skill_registry=deps.skill_runtime)
    pipeline = create_comps_pipeline(sub_agents)

    result = asyncio.run(pipeline.execute(deps, ticker))
    click.echo(result.format_summary())


@cli.command()
@click.argument("ticker")
@click.option("--model", default=None, help="Override model, e.g. anthropic:claude-sonnet-4-6")
def dcf(ticker: str, model: str | None) -> None:
    """Run DCF valuation pipeline."""
    deps = _build_deps(model)

    from finagent.engine.agents.factory import create_sub_agents
    from finagent.engine.pipelines.dcf import create_dcf_pipeline

    sub_agents = create_sub_agents(deps.settings, skill_registry=deps.skill_runtime)
    pipeline = create_dcf_pipeline(sub_agents)

    result = asyncio.run(pipeline.execute(deps, ticker))
    click.echo(result.format_summary())


@cli.command()
@click.option("--port", default=8000, show_default=True)
def serve(port: int) -> None:
    """Start the FinAgent server."""
    import uvicorn
    from finagent.server import app

    uvicorn.run(app, host="0.0.0.0", port=port)
