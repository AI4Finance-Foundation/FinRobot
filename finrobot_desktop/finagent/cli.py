from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from finagent.config import get_settings
from finagent.engine.analysis.prompts import ANALYSIS_TYPES

if TYPE_CHECKING:
    from finagent.engine.deps import FinAgentDeps

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

def _build_deps(model: str | None = None) -> "FinAgentDeps":
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

    # Runtime config validation is defined on FinAgentSettings (P3 audit D2)
    # so CLI and SDK share one definition of "coherent settings". The
    # settings method raises ValueError; we convert that into the
    # CLI-specific ClickException so click formats it correctly.
    try:
        settings.validate_runtime_config()
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    # Load skills if available
    skills_path = Path(settings.skills_dir)
    registry = SkillRegistry(skills_path) if skills_path.exists() else None

    # Build provider chain: FMP (if key) → Finnhub (if key) → yfinance (always) + SEC EDGAR
    from finagent.engine.data.providers.sec_provider import SECEdgarProvider

    providers: list[Any] = []
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


def _build_runtime(model: str | None = None) -> tuple[Any, "FinAgentDeps"]:
    """Build lead agent + deps. Used by `run` command (Mode A)."""
    from finagent.engine.orchestrator import create_lead_agent

    deps = _build_deps(model)
    agent = create_lead_agent(deps.settings, skill_registry=deps.skill_runtime)
    return agent, deps


def _should_use_ddm(deps: "FinAgentDeps", ticker: str) -> bool:
    """Check if ticker is a bank/financial that should use DDM.

    Fetches financials to get industry/sector, then uses the industry
    detection module. Returns False on any error (fail-open to DCF).
    """
    from finagent.engine.compute.industry import is_bank
    from finagent.engine.data.types import DataType

    try:
        result = asyncio.run(deps.data_layer.fetch(DataType.FINANCIALS, ticker))
        data = result.data
        industry = data.get("industry")
        sector = data.get("sector")
        return is_bank(industry=industry, sector=sector)
    except (ValueError, KeyError, TypeError, RuntimeError, AttributeError):
        return False


class CliProgress:
    """Print pipeline progress to the terminal.

    Implements the ProgressCallback Protocol from
    finagent.engine.pipelines.base. Writes to stdout so users see real-time
    step progress instead of waiting for the full pipeline to finish.
    """

    def __init__(self) -> None:
        self._total: int = 0

    async def on_step_start(
        self, step_index: int, total: int, step_name: str
    ) -> None:
        self._total = total
        label = step_name.replace("_", " ").title()
        click.echo(f"  [{step_index}/{total}] {label}...", nl=False)

    async def on_step_end(
        self, step_index: int, total: int, step_name: str, duration_s: float
    ) -> None:
        click.echo(f" done ({duration_s:.1f}s)")

    async def on_step_retry(
        self, step_index: int, step_name: str, attempt: int, error: str
    ) -> None:
        # Newline so the retry note is on its own line (the preceding start
        # line was written without a newline).
        click.echo(f" retry {attempt} ({error[:60]})")
        # Reprint the step label so the subsequent on_step_end has context.
        label = step_name.replace("_", " ").title()
        click.echo(f"  [{step_index}/{self._total}] {label}...", nl=False)


@click.group()
@click.version_option(version="0.1.0", prog_name="finagent")
def cli() -> None:
    """FinAgent — financial AI agent platform."""


# --- Skill subcommands ---


@cli.group()
def skill() -> None:
    """Manage FinAgent skills."""


@skill.command("list")
def skill_list() -> None:
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
def skill_search(query: str) -> None:
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

    result = asyncio.run(pipeline.execute(deps, ticker, progress=CliProgress()))
    click.echo(result.format_summary())
    click.echo(
        "\nNote: HTML reports require the server. Run 'finagent serve', "
        "then trigger the analysis via the /chat API or Desktop app. "
        "CLI results are not shared with the server (separate processes)."
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

    result = asyncio.run(pipeline.execute(deps, ticker, progress=CliProgress()))
    click.echo(result.format_summary())


@cli.command()
@click.argument("ticker")
@click.option("--model", default=None, help="Override model, e.g. anthropic:claude-sonnet-4-6")
@click.option("--force-dcf", is_flag=True, default=False, help="Force FCF-DCF even for banks (skip DDM auto-detection)")
def dcf(ticker: str, model: str | None, force_dcf: bool) -> None:
    """Run DCF valuation pipeline.

    For banks (detected via industry/sector), automatically uses DDM
    (Dividend Discount Model) instead of FCF-DCF. Use --force-dcf to override.
    """
    deps = _build_deps(model)

    from finagent.engine.agents.factory import create_sub_agents

    sub_agents = create_sub_agents(deps.settings, skill_registry=deps.skill_runtime)

    if not force_dcf:
        # Check if ticker is a bank — if so, use DDM instead
        use_ddm = _should_use_ddm(deps, ticker)
        if use_ddm:
            click.echo(
                f"Detected {ticker.upper()} as a bank/financial institution. "
                "Using DDM (Dividend Discount Model) instead of FCF-DCF.\n"
                "Use --force-dcf to override.\n",
                err=True,
            )
            from finagent.engine.pipelines.ddm import create_ddm_pipeline

            pipeline = create_ddm_pipeline(sub_agents)
            result = asyncio.run(pipeline.execute(deps, ticker, progress=CliProgress()))
            click.echo(result.format_summary())
            click.echo(
                "\nNote: HTML reports require the server. Run 'finagent serve', "
                "then trigger the analysis via the /chat API or Desktop app. "
                "CLI results are not shared with the server (separate processes)."
            )
            return

    from finagent.engine.pipelines.dcf import create_dcf_pipeline

    pipeline = create_dcf_pipeline(sub_agents)

    result = asyncio.run(pipeline.execute(deps, ticker, progress=CliProgress()))
    click.echo(result.format_summary())
    click.echo(
        "\nNote: HTML reports require the server. Run 'finagent serve', "
        "then trigger the analysis via the /chat API or Desktop app. "
        "CLI results are not shared with the server (separate processes)."
    )


@cli.command()
@click.argument("ticker")
@click.option("--model", default=None, help="Override model, e.g. anthropic:claude-sonnet-4-6")
def ddm(ticker: str, model: str | None) -> None:
    """Run DDM (Dividend Discount Model) valuation pipeline.

    DDM values a company based on projected dividends discounted at cost of equity.
    Appropriate for banks, utilities, and dividend-paying stocks where
    traditional free cash flow is not meaningful.
    """
    deps = _build_deps(model)

    from finagent.engine.agents.factory import create_sub_agents
    from finagent.engine.pipelines.ddm import create_ddm_pipeline

    sub_agents = create_sub_agents(deps.settings, skill_registry=deps.skill_runtime)
    pipeline = create_ddm_pipeline(sub_agents)

    result = asyncio.run(pipeline.execute(deps, ticker, progress=CliProgress()))
    click.echo(result.format_summary())
    click.echo(
        "\nNote: HTML reports require the server. Run 'finagent serve', "
        "then trigger the analysis via the /chat API or Desktop app. "
        "CLI results are not shared with the server (separate processes)."
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

    result = asyncio.run(pipeline.execute(deps, ticker, progress=CliProgress()))
    click.echo(result.format_summary())
    click.echo(
        "\nNote: HTML reports require the server. Run 'finagent serve', "
        "then trigger the analysis via the /chat API or Desktop app. "
        "CLI results are not shared with the server (separate processes)."
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

    result = asyncio.run(pipeline.execute(deps, ticker, progress=CliProgress()))
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

    result = asyncio.run(pipeline.execute(deps, ticker, progress=CliProgress()))
    click.echo(result.format_summary())
    click.echo(
        "\nNote: HTML reports require the server. Run 'finagent serve', "
        "then trigger the analysis via the /chat API or Desktop app. "
        "CLI results are not shared with the server (separate processes)."
    )


@cli.command()
@click.argument("tickers", nargs=-1, required=True)
@click.option("--model", default=None, help="Override model, e.g. anthropic:claude-sonnet-4-6")
def compare(tickers: tuple[str, ...], model: str | None) -> None:
    """Compare DCF valuation across multiple companies.

    Runs the DCF pipeline for each ticker concurrently, then prints a
    side-by-side comparison table.

    Example:
        finagent compare AAPL MSFT GOOGL
    """
    if len(tickers) < 2:
        raise click.ClickException("At least 2 tickers required for comparison.")
    if len(tickers) > 10:
        raise click.ClickException("Maximum 10 tickers supported.")

    deps = _build_deps(model)

    from finagent.engine.compute.compare import (
        CompanyValuation,
        ComparisonResult,
        build_company_valuation,
        format_comparison_table,
    )
    from finagent.engine.models.financial import DCFResult, FinancialData
    from finagent.engine.agents.factory import create_sub_agents
    from finagent.engine.pipelines.dcf import create_dcf_pipeline

    sub_agents = create_sub_agents(deps.settings, skill_registry=deps.skill_runtime)

    async def _run_one(ticker: str) -> CompanyValuation:
        try:
            pipeline = create_dcf_pipeline(sub_agents)
            result = await pipeline.execute(deps, ticker, progress=CliProgress())

            dcf_result: DCFResult | None = None
            for value in result.structured_data.values():
                if isinstance(value, DCFResult):
                    dcf_result = value
                    break

            if dcf_result is None:
                return CompanyValuation(
                    ticker=ticker, error="DCF pipeline completed but no DCFResult found"
                )

            company_name = ""
            current_price: float | None = None
            ev_ebitda: float | None = None
            pe_ratio: float | None = None
            warnings: list[str] = []

            for value in result.structured_data.values():
                if isinstance(value, FinancialData):
                    company_name = value.company_name
                    current_price = value.market.current_price
                    ev_ebitda = value.valuation.ev_ebitda
                    pe_ratio = value.market.pe_ratio
                    warnings = list(value.warnings)
                    break

            return build_company_valuation(
                ticker=ticker,
                company_name=company_name,
                current_price=current_price,
                dcf_result=dcf_result,
                ev_ebitda=ev_ebitda,
                pe_ratio=pe_ratio,
                warnings=warnings,
            )
        except (ValueError, RuntimeError, KeyError, TypeError) as e:
            return CompanyValuation(ticker=ticker, error=str(e)[:200])

    async def _run_all() -> ComparisonResult:
        tasks = [_run_one(t.upper()) for t in tickers]
        companies = await asyncio.gather(*tasks)
        return ComparisonResult(companies=list(companies))

    comparison = asyncio.run(_run_all())
    click.echo("\n" + format_comparison_table(comparison))

    # Print warnings per company
    for c in comparison.companies:
        if c.warnings:
            click.echo(f"\n{c.ticker} warnings:")
            for w in c.warnings:
                click.echo(f"  - {w}")
        if c.error:
            click.echo(f"\n{c.ticker} ERROR: {c.error}")


@cli.command()
@click.argument("ticker")
@click.option("--strategy", default="sma_crossover", show_default=True, help="Strategy name or module:ClassName")
@click.option("--start", required=True, help="Start date (YYYY-MM-DD)")
@click.option("--end", required=True, help="End date (YYYY-MM-DD)")
@click.option("--cash", default=100_000.0, show_default=True, help="Initial cash")
@click.option("--params", default=None, help='Strategy params as JSON, e.g. \'{"fast":10,"slow":30}\'')
@click.option("--save-chart", default=None, type=click.Path(), help="Save equity curve PNG to this path")
@click.option("--auto", is_flag=True, default=False, help="LLM-guided strategy selection (iterative)")
@click.option("--model", default=None, help="Override model for --auto mode")
def backtest(
    ticker: str,
    strategy: str,
    start: str,
    end: str,
    cash: float,
    params: str | None,
    save_chart: str | None,
    auto: bool,
    model: str | None,
) -> None:
    """Run a backtest on a ticker with a given strategy.

    Example:
        finagent backtest AAPL --strategy sma_crossover --start 2023-01-01 --end 2024-01-01

    With --auto, the LLM picks and iteratively tunes strategy parameters:
        finagent backtest AAPL --start 2023-01-01 --end 2024-01-01 --auto
    """
    if auto:
        from finagent.engine.backtest.strategy_agent import run_strategy_selection

        settings = get_settings(model_name=model)
        result = asyncio.run(
            run_strategy_selection(settings, ticker, start, end, initial_cash=cash)
        )
        click.echo(result.format_summary())
    else:
        import json

        from finagent.engine.backtest.backtrader_adapter import BackTraderAdapter
        from finagent.engine.backtest.engine import BacktestConfig

        strategy_params: dict[str, float | int | str] = {}
        if params:
            try:
                strategy_params = json.loads(params)
            except json.JSONDecodeError as e:
                raise click.ClickException(f"Invalid --params JSON: {e}") from e

        config = BacktestConfig(
            ticker=ticker,
            start_date=start,
            end_date=end,
            strategy=strategy,
            strategy_params=strategy_params,
            initial_cash=cash,
        )

        engine = BackTraderAdapter()
        result = asyncio.run(engine.run(config))
        click.echo(result.format_summary())

    if save_chart and result.chart_base64:
        import base64

        chart_bytes = base64.b64decode(result.chart_base64)
        Path(save_chart).write_bytes(chart_bytes)
        click.echo(f"\nEquity curve saved to {save_chart}")


@cli.command()
@click.argument("ticker")
@click.argument("question")
@click.option("--model", default=None, help="Override model, e.g. anthropic:claude-sonnet-4-6")
@click.option("--top-k", default=5, show_default=True, help="Number of RAG chunks to retrieve")
def ask(ticker: str, question: str, model: str | None, top_k: int) -> None:
    """Ask a question about a company's 10-K filing using RAG.

    Fetches the latest 10-K from SEC EDGAR, retrieves relevant passages
    via BM25, and answers the question with source citations.
    """
    from finagent.engine.analysis.qa import run_qa

    deps = _build_deps(model)
    result = asyncio.run(
        run_qa(deps.data_layer, deps.settings, ticker, question, top_k=top_k)
    )
    click.echo(result)


@cli.command()
@click.argument("ticker")
@click.argument("analysis_type", type=click.Choice(
    sorted(ANALYSIS_TYPES),
    case_sensitive=False,
))
@click.option("--model", default=None, help="Override model, e.g. anthropic:claude-sonnet-4-6")
def analyze(ticker: str, analysis_type: str, model: str | None) -> None:
    """Run standalone financial analysis on a ticker.

    ANALYSIS_TYPE: balance | cashflow | competitors | income | overview | risk
    """
    from finagent.engine.analysis.prompts import run_analysis

    deps = _build_deps(model)
    result = asyncio.run(
        run_analysis(deps.data_layer, deps.settings, ticker, analysis_type.lower())
    )
    click.echo(result)


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind address")
@click.option("--port", default=8321, show_default=True)
def serve(host: str, port: int) -> None:
    """Start the FinAgent server."""
    import uvicorn
    from finagent.server import app

    uvicorn.run(app, host=host, port=port)
