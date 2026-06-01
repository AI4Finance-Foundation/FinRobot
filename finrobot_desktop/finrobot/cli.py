from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from finrobot.config import get_settings
from finrobot.engine.analysis.prompts import ANALYSIS_TYPES

if TYPE_CHECKING:
    from finrobot.engine.deps import FinRobotDeps


# Reminder appended to CLI pipeline output. HTML rendering lives in the
# server process; CLI runs are stand-alone and don't share state with it.
_HTML_REPORT_NOTE = (
    "\nNote: HTML reports require the server. Run 'finrobot serve', "
    "then trigger the analysis via the /chat API or Desktop app. "
    "CLI results are not shared with the server (separate processes)."
)


def _build_deps(model: str | None = None) -> "FinRobotDeps":
    """Build deps only. No agent creation.
    Used by pipeline commands that create their own sub-agents."""
    from finrobot.obs import setup_logging

    setup_logging(get_settings())

    from finrobot.data_layer_factory import build_data_layer
    from finrobot.engine.deps import FinRobotDeps
    from finrobot.engine.skills.registry import SkillRegistry

    settings = get_settings(model_name=model) if model else get_settings()

    # Runtime config validation: checks LLM key + FMP key (required).
    # Raises ValueError; we convert to ClickException for clean CLI output.
    try:
        settings.validate_runtime_config()
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    # Load skills if available
    skills_path = Path(settings.skills_dir)
    registry = SkillRegistry(skills_path) if skills_path.exists() else None

    # Build provider chain via shared factory (FMP primary → yfinance fallback)
    data_layer = build_data_layer(settings)
    deps = FinRobotDeps(data_layer=data_layer, settings=settings, skill_runtime=registry)

    return deps


def _build_runtime(model: str | None = None) -> tuple[Any, "FinRobotDeps"]:
    """Build lead agent + deps. Used by `run` command (Mode A)."""
    from finrobot.engine.orchestrator import create_lead_agent

    deps = _build_deps(model)
    agent = create_lead_agent(deps.settings, skill_registry=deps.skill_runtime)
    return agent, deps


def _should_use_ddm(deps: "FinRobotDeps", ticker: str) -> bool:
    """Check if ticker is a bank/financial that should use DDM.

    Fetches financials to get industry/sector, then uses the industry
    detection module. Returns False on any error (fail-open to DCF).
    """
    from finrobot.engine.compute.industry import is_bank
    from finrobot.engine.data.types import DataType

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
    finrobot.engine.pipelines.base. Writes to stdout so users see real-time
    step progress instead of waiting for the full pipeline to finish.
    """

    def __init__(self) -> None:
        self._total: int = 0

    async def on_step_start(self, step_index: int, total: int, step_name: str) -> None:
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
@click.version_option(version="0.1.0", prog_name="finrobot")
def cli() -> None:
    """FinRobot — financial AI agent platform."""


# --- Skill subcommands ---


@cli.group()
def skill() -> None:
    """Manage FinRobot skills."""


@skill.command("list")
def skill_list() -> None:
    """List all available skills grouped by domain."""
    from finrobot.engine.skills.registry import SkillRegistry

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
    from finrobot.engine.skills.registry import SkillRegistry

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
@click.option(
    "--lang",
    default=None,
    type=click.Choice(["en", "zh"]),
    help="Output language (en=English, zh=Chinese)",
)
def research(ticker: str, model: str | None, lang: str | None) -> None:
    """Run equity research pipeline on a ticker (Mode B).

    Calls pipeline.execute() directly — does NOT rely on LLM tool selection.
    This is deterministic: the pipeline always runs all 5 steps regardless of model.
    """
    deps = _build_deps(model)

    from finrobot.engine.agents.factory import create_sub_agents
    from finrobot.engine.pipelines.equity_research import create_equity_research_pipeline

    sub_agents = create_sub_agents(deps.settings, skill_registry=deps.skill_runtime)
    pipeline = create_equity_research_pipeline(sub_agents)

    result = asyncio.run(pipeline.execute(deps, ticker, progress=CliProgress(), lang=lang))
    click.echo(result.format_summary())
    click.echo(_HTML_REPORT_NOTE)


@cli.command()
@click.argument("ticker")
@click.option("--model", default=None, help="Override model, e.g. anthropic:claude-sonnet-4-6")
@click.option(
    "--lang",
    default=None,
    type=click.Choice(["en", "zh"]),
    help="Output language (en=English, zh=Chinese)",
)
@click.option(
    "--peers",
    default=None,
    help="Comma-separated peer tickers (3-10), e.g. AAPL,MSFT,GOOGL. "
    "Overrides automatic LLM peer selection with your own comparable set.",
)
def comps(ticker: str, model: str | None, lang: str | None, peers: str | None) -> None:
    """Run comparable company analysis pipeline."""
    deps = _build_deps(model)

    from finrobot.engine.agents.factory import create_sub_agents
    from finrobot.engine.pipelines.comps import create_comps_pipeline

    sub_agents = create_sub_agents(deps.settings, skill_registry=deps.skill_runtime)
    pipeline = create_comps_pipeline(sub_agents)

    # Only forward `peers` when supplied, so the default path passes no run
    # kwargs and behaves byte-identically to before the override existed.
    # dict[str, Any] (not object) so the **unpack stays mypy-clean against
    # execute()'s typed keyword params (lang / source_artifact_id: str | None).
    extra: dict[str, Any] = {}
    if peers:
        extra["peers"] = [p.strip().upper() for p in peers.split(",") if p.strip()]

    result = asyncio.run(pipeline.execute(deps, ticker, progress=CliProgress(), lang=lang, **extra))
    click.echo(result.format_summary())


@cli.command()
@click.argument("ticker")
@click.option("--model", default=None, help="Override model, e.g. anthropic:claude-sonnet-4-6")
@click.option(
    "--force-dcf",
    is_flag=True,
    default=False,
    help="Force FCF-DCF even for banks (skip DDM auto-detection)",
)
@click.option(
    "--lang",
    default=None,
    type=click.Choice(["en", "zh"]),
    help="Output language (en=English, zh=Chinese)",
)
def dcf(ticker: str, model: str | None, force_dcf: bool, lang: str | None) -> None:
    """Run DCF valuation pipeline.

    For banks (detected via industry/sector), automatically uses DDM
    (Dividend Discount Model) instead of FCF-DCF. Use --force-dcf to override.
    """
    deps = _build_deps(model)

    from finrobot.engine.agents.factory import create_sub_agents

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
            from finrobot.engine.pipelines.ddm import create_ddm_pipeline

            pipeline = create_ddm_pipeline(sub_agents)
            result = asyncio.run(pipeline.execute(deps, ticker, progress=CliProgress(), lang=lang))
            click.echo(result.format_summary())
            click.echo(_HTML_REPORT_NOTE)
            return

    from finrobot.engine.pipelines.dcf import create_dcf_pipeline

    pipeline = create_dcf_pipeline(sub_agents)

    result = asyncio.run(pipeline.execute(deps, ticker, progress=CliProgress(), lang=lang))
    click.echo(result.format_summary())
    click.echo(_HTML_REPORT_NOTE)


@cli.command()
@click.argument("ticker")
@click.option("--model", default=None, help="Override model, e.g. anthropic:claude-sonnet-4-6")
@click.option(
    "--lang",
    default=None,
    type=click.Choice(["en", "zh"]),
    help="Output language (en=English, zh=Chinese)",
)
def ddm(ticker: str, model: str | None, lang: str | None) -> None:
    """Run DDM (Dividend Discount Model) valuation pipeline.

    DDM values a company based on projected dividends discounted at cost of equity.
    Appropriate for banks, utilities, and dividend-paying stocks where
    traditional free cash flow is not meaningful.
    """
    deps = _build_deps(model)

    from finrobot.engine.agents.factory import create_sub_agents
    from finrobot.engine.pipelines.ddm import create_ddm_pipeline

    sub_agents = create_sub_agents(deps.settings, skill_registry=deps.skill_runtime)
    pipeline = create_ddm_pipeline(sub_agents)

    result = asyncio.run(pipeline.execute(deps, ticker, progress=CliProgress(), lang=lang))
    click.echo(result.format_summary())
    click.echo(_HTML_REPORT_NOTE)


@cli.command()
@click.argument("ticker")
@click.option("--model", default=None, help="Override model, e.g. anthropic:claude-sonnet-4-6")
@click.option(
    "--lang",
    default=None,
    type=click.Choice(["en", "zh"]),
    help="Output language (en=English, zh=Chinese)",
)
def lbo(ticker: str, model: str | None, lang: str | None) -> None:
    """Run LBO (leveraged buyout) analysis pipeline.

    Deterministic IRR/MOIC arithmetic — LLM selects assumptions, code computes returns.
    """
    deps = _build_deps(model)

    from finrobot.engine.agents.factory import create_sub_agents
    from finrobot.engine.pipelines.lbo import create_lbo_pipeline

    sub_agents = create_sub_agents(deps.settings, skill_registry=deps.skill_runtime)
    pipeline = create_lbo_pipeline(sub_agents)

    result = asyncio.run(pipeline.execute(deps, ticker, progress=CliProgress(), lang=lang))
    click.echo(result.format_summary())
    click.echo(_HTML_REPORT_NOTE)


@cli.command()
@click.argument("ticker")
@click.option("--model", default=None, help="Override model, e.g. anthropic:claude-sonnet-4-6")
@click.option(
    "--lang",
    default=None,
    type=click.Choice(["en", "zh"]),
    help="Output language (en=English, zh=Chinese)",
)
def earnings(ticker: str, model: str | None, lang: str | None) -> None:
    """Run earnings quality analysis pipeline.

    Requires FMP API key for earnings surprise data (set FINROBOT_FMP_API_KEY).
    """
    deps = _build_deps(model)

    from finrobot.engine.agents.factory import create_sub_agents
    from finrobot.engine.pipelines.earnings_analysis import create_earnings_analysis_pipeline

    sub_agents = create_sub_agents(deps.settings, skill_registry=deps.skill_runtime)
    pipeline = create_earnings_analysis_pipeline(sub_agents)

    result = asyncio.run(pipeline.execute(deps, ticker, progress=CliProgress(), lang=lang))
    click.echo(result.format_summary())


@cli.command(name="ic-memo")
@click.argument("ticker")
@click.option("--model", default=None, help="Override model, e.g. anthropic:claude-sonnet-4-6")
@click.option(
    "--lang",
    default=None,
    type=click.Choice(["en", "zh"]),
    help="Output language (en=English, zh=Chinese)",
)
def ic_memo(ticker: str, model: str | None, lang: str | None) -> None:
    """Run Investment Committee (IC) memo pipeline.

    Runs DCF + LBO inline and applies IRR hurdle gate (PASS if IRR < 15%).
    """
    deps = _build_deps(model)

    from finrobot.engine.agents.factory import create_sub_agents
    from finrobot.engine.pipelines.ic_memo import create_ic_memo_pipeline

    sub_agents = create_sub_agents(deps.settings, skill_registry=deps.skill_runtime)
    pipeline = create_ic_memo_pipeline(sub_agents)

    result = asyncio.run(pipeline.execute(deps, ticker, progress=CliProgress(), lang=lang))
    click.echo(result.format_summary())
    click.echo(_HTML_REPORT_NOTE)


@cli.command()
@click.argument("tickers", nargs=-1, required=True)
@click.option("--model", default=None, help="Override model, e.g. anthropic:claude-sonnet-4-6")
def compare(tickers: tuple[str, ...], model: str | None) -> None:
    """Compare DCF valuation across multiple companies.

    Runs the DCF pipeline for each ticker concurrently, then prints a
    side-by-side comparison table.

    Example:
        finrobot compare AAPL MSFT GOOGL
    """
    if len(tickers) < 2:
        raise click.ClickException("At least 2 tickers required for comparison.")
    if len(tickers) > 10:
        raise click.ClickException("Maximum 10 tickers supported.")

    deps = _build_deps(model)

    from finrobot.engine.compute.compare import (
        CompanyValuation,
        ComparisonResult,
        build_company_valuation,
        format_comparison_table,
    )
    from finrobot.engine.models.financial import DCFResult, FinancialData
    from finrobot.engine.agents.factory import create_sub_agents
    from finrobot.engine.pipelines.dcf import create_dcf_pipeline

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
@click.option(
    "--strategy",
    default="sma_crossover",
    show_default=True,
    help="Strategy name or module:ClassName",
)
@click.option("--start", required=True, help="Start date (YYYY-MM-DD)")
@click.option("--end", required=True, help="End date (YYYY-MM-DD)")
@click.option("--cash", default=100_000.0, show_default=True, help="Initial cash")
@click.option(
    "--params", default=None, help='Strategy params as JSON, e.g. \'{"fast":10,"slow":30}\''
)
@click.option(
    "--save-chart", default=None, type=click.Path(), help="Save equity curve PNG to this path"
)
@click.option(
    "--auto", is_flag=True, default=False, help="LLM-guided strategy selection (iterative)"
)
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
        finrobot backtest AAPL --strategy sma_crossover --start 2023-01-01 --end 2024-01-01

    With --auto, the LLM picks and iteratively tunes strategy parameters:
        finrobot backtest AAPL --start 2023-01-01 --end 2024-01-01 --auto
    """
    if auto:
        from finrobot.engine.backtest.strategy_agent import run_strategy_selection

        settings = get_settings(model_name=model)
        result = asyncio.run(
            run_strategy_selection(settings, ticker, start, end, initial_cash=cash)
        )
        click.echo(result.format_summary())
    else:
        import json

        from finrobot.engine.backtest.backtrader_adapter import BackTraderAdapter
        from finrobot.engine.backtest.engine import BacktestConfig

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
    from finrobot.engine.analysis.qa import run_qa

    deps = _build_deps(model)
    result = asyncio.run(run_qa(deps.data_layer, deps.settings, ticker, question, top_k=top_k))
    click.echo(result)


@cli.command()
@click.argument("ticker")
@click.argument(
    "analysis_type",
    type=click.Choice(
        sorted(ANALYSIS_TYPES),
        case_sensitive=False,
    ),
)
@click.option("--model", default=None, help="Override model, e.g. anthropic:claude-sonnet-4-6")
def analyze(ticker: str, analysis_type: str, model: str | None) -> None:
    """Run standalone financial analysis on a ticker.

    ANALYSIS_TYPE: balance | cashflow | competitors | income | overview | risk
    """
    from finrobot.engine.analysis.prompts import run_analysis

    deps = _build_deps(model)
    result = asyncio.run(
        run_analysis(deps.data_layer, deps.settings, ticker, analysis_type.lower())
    )
    click.echo(result)


def _start_parent_death_watchdog(parent_pid: int) -> None:
    """Terminate this server when ``parent_pid`` (the desktop shell) is gone.

    The desktop sidecar is a PyInstaller one-file binary: Tauri spawns a
    bootloader that forks the real server, and Tauri kills the bootloader with
    SIGKILL on quit. SIGKILL is uncatchable, so the bootloader cannot forward it
    and this uvicorn process would be reparented to launchd and keep holding
    127.0.0.1:8321 — a stale orphan the next launch then talks to by mistake.

    Polling the *Tauri* pid directly (not ``os.getppid()``, which the bootloader
    masks) lets the server self-terminate on app quit or crash. Gated on an
    explicit ``--parent-pid`` so a standalone ``finrobot serve`` under
    systemd/nohup (real parent pid 1) never trips it.
    """
    import os
    import threading
    import time

    def _watch() -> None:
        while True:
            time.sleep(2)
            try:
                os.kill(parent_pid, 0)  # signal 0 = liveness probe, sends nothing
            except ProcessLookupError:
                os._exit(0)  # parent gone — exit hard, no clients left to drain
            except PermissionError:
                continue  # parent alive but owned by another uid

    threading.Thread(target=_watch, name="parent-death-watchdog", daemon=True).start()


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind address")
@click.option("--port", default=8321, show_default=True)
@click.option(
    "--reload",
    is_flag=True,
    default=False,
    help="Auto-restart on code changes (dev mode). Watches finrobot/.",
)
@click.option(
    "--log-level",
    default="info",
    show_default=True,
    type=click.Choice(["critical", "error", "warning", "info", "debug", "trace"]),
)
@click.option(
    "--parent-pid",
    type=int,
    default=None,
    help=(
        "Exit when this process disappears (the desktop shell's PID). Used by "
        "the Tauri sidecar so the server never orphans on 127.0.0.1; omit for "
        "standalone runs."
    ),
)
def serve(host: str, port: int, reload: bool, log_level: str, parent_pid: int | None) -> None:
    """Start the FinRobot server.

    Use ``--reload`` during development so editing Python files
    auto-restarts the worker — avoids stale-process 500s after edits.
    """
    from finrobot.obs import setup_logging

    setup_logging(get_settings())

    if parent_pid is not None:
        _start_parent_death_watchdog(parent_pid)

    import uvicorn

    if reload:
        # reload mode requires an import string (not the app object) so the
        # worker can re-import after file changes.
        uvicorn.run(
            "finrobot.server:app",
            host=host,
            port=port,
            reload=True,
            reload_dirs=["finrobot"],
            log_level=log_level,
            log_config=None,
        )
    else:
        from finrobot.server import app

        uvicorn.run(app, host=host, port=port, log_level=log_level, log_config=None)
