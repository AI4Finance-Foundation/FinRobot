import asyncio
import logging
import sys
from pathlib import Path

import click

from finagent.config import get_settings

# Show pipeline progress on stderr so users see what's happening.
# This surfaces base.py's logger.info("Step 1/5: ...") to the terminal.
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(message)s",
)
# Silence noisy third-party loggers
for _quiet in ("httpx", "httpcore", "urllib3", "yfinance", "filelock"):
    logging.getLogger(_quiet).setLevel(logging.WARNING)

_VALID_PROVIDERS = {"deepseek", "anthropic", "openai", "test"}
_PROVIDER_KEY_MAP = {
    "deepseek": "FINAGENT_DEEPSEEK_API_KEY",
    "anthropic": "FINAGENT_ANTHROPIC_API_KEY",
    "openai": "FINAGENT_OPENAI_API_KEY",
}


def _validate_model_config(settings) -> None:
    """Fail fast if the model provider's API key is missing.

    Called at startup before any data fetching or LLM calls,
    so users don't wait 60 seconds only to hit an auth error.
    """
    name = settings.model_name
    provider, _, model_id = name.partition(":")

    if provider not in _VALID_PROVIDERS:
        raise click.ClickException(
            f"Unknown provider '{provider}' in model_name '{name}'. "
            f"Valid providers: {', '.join(sorted(_VALID_PROVIDERS))}. "
            f"Format: provider:model_id (e.g. anthropic:claude-sonnet-4-6)"
        )

    env_var = _PROVIDER_KEY_MAP.get(provider)
    if env_var is None:
        return  # "test" provider needs no key

    key_value = getattr(settings, env_var.replace("FINAGENT_", "").lower(), "")
    if not key_value:
        raise click.ClickException(
            f"{env_var} is not set. "
            f"Set it in .env or as an environment variable.\n"
            f"  export {env_var}=your-key-here"
        )


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

    _validate_model_config(settings)

    # Load skills if available
    skills_path = Path(settings.skills_dir)
    registry = SkillRegistry(skills_path) if skills_path.exists() else None

    # Build provider chain: FMP (if key) → Finnhub (if key) → yfinance (always) + SEC EDGAR
    from finagent.engine.data.providers.sec_provider import SECEdgarProvider

    providers: list = []
    if settings.fmp_api_key:
        from finagent.engine.data.providers.fmp_provider import FMPProvider

        providers.append(FMPProvider(api_key=settings.fmp_api_key))
    if settings.finnhub_api_key:
        from finagent.engine.data.providers.finnhub_provider import FinnhubProvider

        providers.append(FinnhubProvider(api_key=settings.finnhub_api_key))
    providers.append(YFinanceProvider())  # always last (free fallback)
    providers.append(SECEdgarProvider(user_agent=settings.sec_user_agent))  # filings only

    cache = DataCache(settings.cache_db_path)
    data_layer = DataLayer(providers=providers, cache=cache)
    deps = FinAgentDeps(data_layer=data_layer, settings=settings, skill_runtime=registry)

    return deps


def _build_runtime(model: str | None = None):
    """Build lead agent + deps. Used by `run` command (Mode A)."""
    from finagent.engine.orchestrator import create_lead_agent

    deps = _build_deps(model)
    agent = create_lead_agent(deps.settings, skill_registry=deps.skill_runtime)
    return agent, deps


@click.group()
@click.version_option(version="0.1.0", prog_name="finagent")
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
    click.echo(
        f"\nNote: HTML reports require the server. Run 'finagent serve', "
        f"then trigger the analysis via the /chat API or Desktop app. "
        f"CLI results are not shared with the server (separate processes)."
    )


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
    click.echo(
        f"\nNote: HTML reports require the server. Run 'finagent serve', "
        f"then trigger the analysis via the /chat API or Desktop app. "
        f"CLI results are not shared with the server (separate processes)."
    )


@cli.command()
@click.argument("ticker")
@click.option("--model", default=None, help="Override model, e.g. anthropic:claude-sonnet-4-6")
def lbo(ticker: str, model: str | None) -> None:
    """Run LBO (leveraged buyout) analysis pipeline.

    Deterministic IRR/MOIC arithmetic — LLM selects assumptions, code computes returns.
    """
    deps = _build_deps(model)

    from finagent.engine.agents.factory import create_sub_agents
    from finagent.engine.pipelines.lbo import create_lbo_pipeline

    sub_agents = create_sub_agents(deps.settings, skill_registry=deps.skill_runtime)
    pipeline = create_lbo_pipeline(sub_agents)

    result = asyncio.run(pipeline.execute(deps, ticker))
    click.echo(result.format_summary())
    click.echo(
        f"\nNote: HTML reports require the server. Run 'finagent serve', "
        f"then trigger the analysis via the /chat API or Desktop app. "
        f"CLI results are not shared with the server (separate processes)."
    )


@cli.command()
@click.argument("ticker")
@click.option("--model", default=None, help="Override model, e.g. anthropic:claude-sonnet-4-6")
def earnings(ticker: str, model: str | None) -> None:
    """Run earnings quality analysis pipeline.

    Requires FMP API key for earnings surprise data (set FINAGENT_FMP_API_KEY).
    """
    deps = _build_deps(model)

    from finagent.engine.agents.factory import create_sub_agents
    from finagent.engine.pipelines.earnings_analysis import create_earnings_analysis_pipeline

    sub_agents = create_sub_agents(deps.settings, skill_registry=deps.skill_runtime)
    pipeline = create_earnings_analysis_pipeline(sub_agents)

    result = asyncio.run(pipeline.execute(deps, ticker))
    click.echo(result.format_summary())


@cli.command(name="ic-memo")
@click.argument("ticker")
@click.option("--model", default=None, help="Override model, e.g. anthropic:claude-sonnet-4-6")
def ic_memo(ticker: str, model: str | None) -> None:
    """Run Investment Committee (IC) memo pipeline.

    Runs DCF + LBO inline and applies IRR hurdle gate (PASS if IRR < 15%).
    """
    deps = _build_deps(model)

    from finagent.engine.agents.factory import create_sub_agents
    from finagent.engine.pipelines.ic_memo import create_ic_memo_pipeline

    sub_agents = create_sub_agents(deps.settings, skill_registry=deps.skill_runtime)
    pipeline = create_ic_memo_pipeline(sub_agents)

    result = asyncio.run(pipeline.execute(deps, ticker))
    click.echo(result.format_summary())
    click.echo(
        f"\nNote: HTML reports require the server. Run 'finagent serve', "
        f"then trigger the analysis via the /chat API or Desktop app. "
        f"CLI results are not shared with the server (separate processes)."
    )


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind address")
@click.option("--port", default=8000, show_default=True)
def serve(host: str, port: int) -> None:
    """Start the FinAgent server."""
    import uvicorn
    from finagent.server import app

    uvicorn.run(app, host=host, port=port)
