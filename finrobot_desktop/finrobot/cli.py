from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from finrobot import __version__
from finrobot.config import get_settings
from finrobot.engine.analysis.prompts import ANALYSIS_TYPES
from finrobot.engine.data.ticker import validate_ticker

if TYPE_CHECKING:
    from finrobot.engine.deps import FinRobotDeps
    from finrobot.engine.pipelines.base import Pipeline


# Reminder appended to CLI pipeline output. HTML rendering lives in the
# server process; CLI runs are stand-alone and don't share state with it.
_HTML_REPORT_NOTE = (
    "\nNote: HTML reports require the server. Run 'finrobot serve', "
    "then trigger the analysis via the /chat API or Desktop app. "
    "CLI results are not shared with the server (separate processes)."
)


def _validate_ticker_arg(raw: str) -> str:
    """Normalise a CLI ``ticker`` argument or abort with a clean CLI error.

    Wraps the shared :func:`validate_ticker` so cache keys stay consistent and
    junk symbols are rejected before a pipeline ever runs. A raised ValueError
    becomes a ``ClickException`` (clean one-line stderr, exit 1) instead of a
    traceback.
    """
    try:
        return validate_ticker(raw)
    except ValueError as e:
        raise click.ClickException(str(e)) from e


def _build_deps(model: str | None = None) -> "FinRobotDeps":
    """Build deps only. No agent creation.
    Used by pipeline commands that create their own sub-agents."""
    from finrobot.obs import setup_logging

    setup_logging(get_settings())

    from finrobot.engine.data.factory import build_data_layer
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


def _build_pipeline(key: str, deps: "FinRobotDeps") -> "Pipeline":
    """Build the pipeline registered under ``key`` for a CLI subcommand.

    Looks the factory up in the pipeline registry (the single source of truth)
    instead of each subcommand inlining its own
    ``create_*_pipeline`` import — adding a pipeline no longer means touching
    the CLI. Builds the shared sub-agents the factory needs.
    """
    from finrobot.engine.agents.factory import create_sub_agents
    from finrobot.engine.pipelines.registry import get_pipeline_factories

    sub_agents = create_sub_agents(deps.settings, skill_registry=deps.skill_runtime)
    pipeline: Pipeline = get_pipeline_factories()[key](sub_agents)
    return pipeline


async def _should_use_ddm(deps: "FinRobotDeps", ticker: str) -> bool:
    """Check if ticker is a bank/financial that should use DDM.

    Fetches financials to get industry/sector, then uses the industry
    detection module. Returns False on any error (fail-open to DCF).

    BUG-082: this MUST be ``await``-ed inside the SAME ``asyncio.run`` as the
    pipeline execution. Wrapping the ``fetch`` in its own ``asyncio.run`` opened
    the shared DataCache aiosqlite connection on a throwaway loop; the next
    ``asyncio.run`` reused that connection, leaving its aiosqlite worker thread
    bound to the destroyed loop → the interpreter hung forever joining the
    orphan thread at shutdown. Keeping everything on one loop avoids that.
    """
    from finrobot.engine.primitives.industry import is_bank
    from finrobot.engine.data.types import DataType

    try:
        result = await deps.data_layer.fetch(DataType.FINANCIALS, ticker)
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
        self,
        step_index: int,
        total: int,
        step_name: str,
        duration_s: float,
        error: str | None = None,
    ) -> None:
        # A non-None error means the step DEGRADED (finished but failed
        # validation after all retries on a non-critical step, BUG-058) — say so
        # instead of printing a clean "done" that hides the failure.
        if error is not None:
            click.echo(f" degraded ({duration_s:.1f}s): {error[:80]}")
        else:
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
@click.version_option(version=__version__, prog_name="finrobot")
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
    ticker = _validate_ticker_arg(ticker)
    deps = _build_deps(model)

    pipeline = _build_pipeline("research", deps)

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
    "Overrides automatic peer selection with your own comparable set.",
)
def comps(ticker: str, model: str | None, lang: str | None, peers: str | None) -> None:
    """Run comparable company analysis pipeline."""
    ticker = _validate_ticker_arg(ticker)
    deps = _build_deps(model)

    pipeline = _build_pipeline("comps", deps)

    # Only forward `peers` when supplied, so the default path passes no run
    # kwargs and behaves byte-identically to before the override existed.
    # dict[str, Any] (not object) so the **unpack stays mypy-clean against
    # execute()'s typed keyword params (lang / source_artifact_id: str | None).
    extra: dict[str, Any] = {}
    if peers:
        # BUG-047: validate format AND count at the CLI entry, before the
        # ~30s data_collection step, so a bad --peers fails in 0s with a clean
        # ClickException instead of a bare ValueError traceback from deep in
        # the pipeline. Reuses the shared validate_ticker (rejects CJK / junk
        # like '苹果,!!!') and the same bounds the runtime check enforces
        # (_helpers.py keeps its check as defense-in-depth for SDK/route paths).
        from finrobot.engine.pipelines._helpers import (
            _PEER_COMP_INPUT_MAX,
            _PEER_COMP_SET_MIN,
        )

        peers_list = [_validate_ticker_arg(p) for p in peers.split(",") if p.strip()]
        if not _PEER_COMP_SET_MIN <= len(peers_list) <= _PEER_COMP_INPUT_MAX:
            raise click.ClickException(
                f"--peers needs {_PEER_COMP_SET_MIN}-{_PEER_COMP_INPUT_MAX} tickers, "
                f"got {len(peers_list)}."
            )
        extra["peers"] = peers_list

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
    ticker = _validate_ticker_arg(ticker)
    deps = _build_deps(model)

    from finrobot.engine.agents.factory import create_sub_agents
    from finrobot.engine.pipelines.registry import get_pipeline_factories

    sub_agents = create_sub_agents(deps.settings, skill_registry=deps.skill_runtime)
    factories = get_pipeline_factories()

    from finrobot.engine.pipelines.base import PipelineResult

    async def _dcf_or_ddm() -> PipelineResult:
        """BUG-082: bank detection + pipeline run on ONE event loop.

        Folding ``_should_use_ddm``'s FINANCIALS fetch into this single
        ``asyncio.run`` keeps the shared DataCache aiosqlite connection bound to
        the live loop, so it is never reused across a destroyed loop (which
        deadlocked the interpreter at shutdown).
        """
        if not force_dcf and await _should_use_ddm(deps, ticker):
            click.echo(
                f"Detected {ticker.upper()} as a bank/financial institution. "
                "Using DDM (Dividend Discount Model) instead of FCF-DCF.\n"
                "Use --force-dcf to override.\n",
                err=True,
            )
            ddm_pipeline: Pipeline = factories["ddm"](sub_agents)
            return await ddm_pipeline.execute(deps, ticker, progress=CliProgress(), lang=lang)

        dcf_pipeline: Pipeline = factories["dcf"](sub_agents)
        return await dcf_pipeline.execute(deps, ticker, progress=CliProgress(), lang=lang)

    result = asyncio.run(_dcf_or_ddm())
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
    ticker = _validate_ticker_arg(ticker)
    deps = _build_deps(model)

    pipeline = _build_pipeline("ddm", deps)

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
    ticker = _validate_ticker_arg(ticker)
    deps = _build_deps(model)

    pipeline = _build_pipeline("lbo", deps)

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
    ticker = _validate_ticker_arg(ticker)
    deps = _build_deps(model)

    pipeline = _build_pipeline("earnings", deps)

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
    ticker = _validate_ticker_arg(ticker)
    deps = _build_deps(model)

    pipeline = _build_pipeline("ic-memo", deps)

    result = asyncio.run(pipeline.execute(deps, ticker, progress=CliProgress(), lang=lang))
    click.echo(result.format_summary())
    click.echo(_HTML_REPORT_NOTE)


@cli.command()
@click.argument("ticker")
@click.option(
    "--strategy",
    default="sma_crossover",
    show_default=True,
    help=(
        "Built-in strategy name (sma_crossover) or, if you have whitelisted an "
        "import-path prefix in FINROBOT_BACKTEST_STRATEGY_MODULE_PREFIXES, a "
        "module:ClassName that loads a custom bt.Strategy. NOTE: module:ClassName "
        "executes that module's top-level code on import; it is disabled by default."
    ),
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
    ticker = _validate_ticker_arg(ticker)

    from finrobot.engine.data.factory import build_data_layer
    from finrobot.engine.backtest.engine import BacktestConfig, BacktestResult

    if auto:
        from finrobot.engine.backtest.strategy_agent import run_strategy_selection

        settings = get_settings(model_name=model)

        # Catch a missing/invalid LLM key up front (same check _build_deps runs)
        # so --auto fails with a clean message instead of a late traceback from
        # the first LLM call. Mirrors _build_deps' ValueError -> ClickException.
        try:
            settings.validate_runtime_config()
        except ValueError as e:
            raise click.ClickException(str(e)) from e

        async def _run_auto() -> BacktestResult:
            data_layer = build_data_layer(settings)
            try:
                return await run_strategy_selection(
                    settings, ticker, start, end, data_layer, initial_cash=cash
                )
            finally:
                await data_layer.close()

        result = asyncio.run(_run_auto())
        click.echo(result.format_summary())
    else:
        import json

        from finrobot.engine.backtest.backtrader_adapter import BackTraderAdapter

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

        settings = get_settings()

        async def _run_manual() -> BacktestResult:
            data_layer = build_data_layer(settings)
            try:
                return await BackTraderAdapter(data_layer).run(config)
            finally:
                await data_layer.close()

        result = asyncio.run(_run_manual())
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
    ticker = _validate_ticker_arg(ticker)

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
    ticker = _validate_ticker_arg(ticker)

    from finrobot.engine.analysis.prompts import run_analysis

    deps = _build_deps(model)
    result = asyncio.run(
        run_analysis(deps.data_layer, deps.settings, ticker, analysis_type.lower())
    )
    click.echo(result)


def _start_parent_death_watchdog(parent_pid: int) -> threading.Event:
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

    Returns the stop ``Event`` so callers (notably tests) can shut the daemon
    thread down deterministically — ``stop.set()`` breaks the poll loop on its
    next tick. Without this the loop is unstoppable: a test that leaves it
    running keeps calling ``os._exit(0)`` every 2s once the watched pid is gone,
    hard-killing the whole pytest session at a random later test (BUG-050).
    ``serve`` ignores the return — in production the watchdog runs for the
    process lifetime and exits via ``os._exit`` on real parent death.
    """
    import os
    import sys

    stop = threading.Event()

    def _parent_alive() -> bool:
        # POSIX: signal 0 sends nothing — it just probes existence + our right to
        # signal (ProcessLookupError = gone; PermissionError = alive, other uid).
        # Windows: NEVER os.kill here — CPython maps os.kill(pid, sig) for any sig
        # other than CTRL_C/CTRL_BREAK to TerminateProcess, so os.kill(parent, 0)
        # would *kill the shell we guard*. Probe via OpenProcess(SYNCHRONIZE) +
        # WaitForSingleObject: a 0-timeout wait returns WAIT_TIMEOUT (0x102) while
        # the process runs, WAIT_OBJECT_0 (0) once it exits; OpenProcess failing
        # means the pid is already gone. [Runtime-verify on real Windows — Phase 2.]
        if sys.platform == "win32":
            import ctypes

            synchronize, wait_timeout = 0x00100000, 0x00000102
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(synchronize, False, parent_pid)
            if not handle:
                return False
            try:
                return bool(kernel32.WaitForSingleObject(handle, 0) == wait_timeout)
            finally:
                kernel32.CloseHandle(handle)
        try:
            os.kill(parent_pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            pass  # parent alive but owned by another uid
        return True

    def _watch() -> None:
        # Event.wait doubles as the poll interval *and* an interruptible
        # shutdown signal: returns True the instant stop is set, False on the
        # 2s timeout (the normal poll tick).
        while not stop.wait(2.0):
            if not _parent_alive():
                os._exit(0)  # parent gone — exit hard, no clients left to drain

    threading.Thread(target=_watch, name="parent-death-watchdog", daemon=True).start()
    return stop


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
