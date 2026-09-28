import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool

from finrobot.artifact.models import ArtifactSummary
from finrobot.artifact.semantic_diff import DeltaItem, SemanticDelta, build_semantic_delta
from finrobot.config import FinRobotSettings
from finrobot.coverage.prompt import format_coverage_for_tool
from finrobot.coverage.service import build_overview
from finrobot.engine.agents.factory import create_sub_agents
from finrobot.engine.analysis.qa import run_qa
from finrobot.engine.backtest.backtrader_adapter import BackTraderAdapter
from finrobot.engine.backtest.engine import BacktestConfig
from finrobot.engine.compute.coordinators.dcf_seed import seed_dcf_inputs_for_ticker
from finrobot.engine.compute.coordinators.news import render_news_for_prompt
from finrobot.engine.compute.operators.monte_carlo import MonteCarloResult, deterministic_seed
from finrobot.engine.compute.operators.monte_carlo import run_monte_carlo as run_monte_carlo_sim
from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.normalize import NormalizedPrice
from finrobot.engine.data.ticker import validate_ticker
from finrobot.engine.data.types import DataType
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.pipelines.base import Pipeline
from finrobot.engine.pipelines.registry import PipelineSpec, iter_pipeline_specs
from finrobot.engine.skills.pipeline_methodology import render_pipeline_methodology
from finrobot.engine.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


async def _run_pipeline_tool(
    ctx: RunContext[FinRobotDeps], ticker: str, pipeline: Pipeline
) -> dict[str, Any] | str:
    """Execute a pipeline and return the tool summary dict.

    Shared dispatch for every @agent.tool that wraps a Pipeline — every result
    is persisted to ArtifactStore by the pipeline itself; the tool returns the
    artifact_id so the caller can route to the detail page.

    On a syntactically invalid ticker this RETURNS a plain error string rather
    than raising: a raised ValueError inside a tool propagates out of the
    PydanticAI run and crashes the live chat SSE stream. Returning lets the LLM
    see the error and ask the user to correct the symbol.
    """
    try:
        norm = validate_ticker(ticker)
    except ValueError:
        return f"Invalid ticker symbol: {ticker}"
    # Thread the chat request's UI locale (set per-request on deps) so the
    # generated report body matches the user's language. None → settings
    # fallback, identical to the old behaviour for any non-chat caller.
    result = await pipeline.execute(ctx.deps, norm, lang=ctx.deps.request_locale)
    return {
        "summary": result.format_summary(),
        "artifact_id": result.artifact_id,
        "ticker": norm,
    }


def _format_reports_for_tool(ticker: str, summaries: list[ArtifactSummary]) -> str:
    """Render saved-report summaries as one compact line each (newest first).

    Only populated fields render; the row carries the conclusion (verdict /
    target / entry) so the assistant can confirm a report exists and offer to
    open / compare / re-run it without re-running a pipeline just to "show" it.
    """
    lines = [f"Saved reports for {ticker} (newest first), {len(summaries)} shown:"]
    for s in summaries:
        parts = [f"- {s.id}", s.created_at.date().isoformat(), s.type]
        if s.verdict:
            parts.append(s.verdict)
        if s.target_price is not None:
            parts.append(f"target {s.target_price:,.2f}")
        if s.entry_price is not None:
            parts.append(f"entry {s.entry_price:,.2f}")
        lines.append(" | ".join(parts))
    lines.append("Reference an id to open it; say so to compare versions or re-run.")
    return "\n".join(lines)


def _format_delta_for_tool(delta: SemanticDelta) -> str:
    """Render a :class:`SemanticDelta` as compact text for the chat agent.

    English-only to match the shipped UI locale. Every number is already
    formatted by the backend (``formatted_*``); this only arranges them and
    surfaces the deterministic attribution summary verbatim — the agent narrates
    from this string and must never re-derive a number from it.
    """
    if delta.identical:
        return (
            f"{delta.a_label} and {delta.b_label} are identical — "
            "no material change between these two versions."
        )

    def _rows(items: list[DeltaItem]) -> list[str]:
        out: list[str] = []
        for it in items:
            if it.direction == "flat":
                continue  # an unchanged field is noise in a "what changed" answer
            pct = f" ({it.formatted_pct_change})" if it.formatted_pct_change else ""
            note = f" — {it.caliber_note}" if it.caliber_note else ""
            out.append(f"  - {it.label_en}: {it.formatted_old} → {it.formatted_new}{pct}{note}")
        return out

    lines = [f"Comparing {delta.a_label} → {delta.b_label} ({delta.report_type}):"]
    conclusion_rows = _rows(delta.conclusion)
    if conclusion_rows:
        lines.append("Conclusion:")
        lines.extend(conclusion_rows)
    driver_rows = _rows(delta.drivers)
    if driver_rows:
        lines.append("Assumption drivers:")
        lines.extend(driver_rows)
    attr = delta.attribution
    if attr.available and attr.summary_en:
        lines.append(f"Attribution: {attr.summary_en}")
    elif not attr.available:
        # Attribution is deliberately withheld (formula changed, missing DCF,
        # etc.); show the headline move and defer the "why" to the English
        # comparability notes below rather than the Chinese disabled_reason.
        move = f" Fair-value move: {attr.formatted_total}." if attr.formatted_total else ""
        lines.append(f"Attribution unavailable for this comparison.{move}")
    if delta.comparability:
        lines.append("Comparability notes:")
        for flag in delta.comparability:
            lines.append(f"  - {flag.message_en}")
    return "\n".join(lines)


def _money(v: float | None) -> str:
    return f"${v:,.2f}" if v is not None else "—"


def _format_monte_carlo_for_tool(
    ticker: str, current_price: float, result: MonteCarloResult
) -> str:
    """Render a :class:`MonteCarloResult` as compact text for the chat agent.

    The seed coordinator FX-normalizes a foreign issuer's financials to USD
    before the simulation, so every price here is USD and '$' is correct.
    """
    p = result.percentiles
    n_total = result.assumptions_used.get("n_simulations", result.n_valid)
    pct = result.current_price_percentile
    lines = [
        f"Monte Carlo DCF for {ticker} ({result.n_valid:,} valid of {n_total:,} simulations):",
        "Implied fair value per share:",
        f"  P5 {_money(p.get('5'))} · P25 {_money(p.get('25'))} · "
        f"Median {_money(p.get('50'))} · P75 {_money(p.get('75'))} · P95 {_money(p.get('95'))}",
        f"  Mean {_money(result.mean)} · Std {_money(result.std)}",
        f"Current price {_money(current_price)} sits at the {pct:.0f}th percentile "
        "of the simulated distribution.",
    ]
    # State the read factually; the band above is the evidence, this is the one-liner.
    if pct <= 25:
        lines.append(
            "  → The market is below most simulated fair values — the model implies "
            "upside under these assumptions."
        )
    elif pct >= 75:
        lines.append(
            "  → The market is above most simulated fair values — the model implies "
            "downside under these assumptions."
        )
    else:
        lines.append("  → The market price is within the model's central range.")
    return "\n".join(lines)


def _make_pipeline_tool(
    pipeline: Pipeline,
) -> Callable[[RunContext[FinRobotDeps], str], Awaitable[dict[str, Any] | str]]:
    """Build a Mode B tool closure that dispatches to ``pipeline``.

    One closure per :class:`PipelineSpec`, replacing the seven near-identical
    hand-written ``@agent.tool`` wrappers — every body was
    ``return await _run_pipeline_tool(ctx, ticker, X_pipeline)``. The tool name
    and the LLM-facing description come from the spec (see
    ``create_lead_agent``), so the only thing that varies per pipeline is the
    bound ``pipeline`` object captured here.
    """

    async def run_pipeline(ctx: RunContext[FinRobotDeps], ticker: str) -> dict[str, Any] | str:
        return await _run_pipeline_tool(ctx, ticker, pipeline)

    return run_pipeline


def create_lead_agent(
    settings: FinRobotSettings,
    skill_registry: SkillRegistry | None = None,
    sub_agents: dict[str, Agent] | None = None,
) -> Agent:
    """Factory: create lead agent with tools and instructions.

    ``sub_agents`` lets the caller share a single set of sub-agents with the
    pipeline dispatcher (``app.state.sub_agents``) so the LLM-side and the
    REST-side don't double-create connections. When None, builds its own.
    """
    instructions = (Path(__file__).parent / "instructions.md").read_text(encoding="utf-8")
    if skill_registry:
        instructions += "\n\n" + skill_registry.list_summary()

    # Live web search via PydanticAI's own common tool (keyless DuckDuckGo,
    # provider-agnostic). Closes the gap where "联网搜今天的 AI 新闻" had no web
    # tool and mis-fired query_financial_data(ticker="AI"). Swap to
    # tavily_search_tool(api_key=…) for cleaner finance-grade results when a key
    # is configured — same registration, better backend.
    agent: Agent[FinRobotDeps, str] = Agent(
        settings.create_model(),
        deps_type=FinRobotDeps,
        instructions=instructions,
        tools=[duckduckgo_search_tool(max_results=8)],
    )

    if sub_agents is None:
        sub_agents = create_sub_agents(settings, skill_registry)

    # --- Mode A tools: conversational, direct response ---

    @agent.tool
    async def query_financial_data(
        ctx: RunContext[FinRobotDeps], ticker: str, data_type: str | DataType
    ) -> str:
        """Fetch financial data for quick questions.
        data_type: one of the DataType values, commonly financials, price, quote,
        news, earnings, filings, profile, historical, quarterly, forward_estimates.
        For QUESTIONS about 10-K narrative (risks, MD&A, business) use ask_filings,
        not this tool — it grounds the answer in the filing text with citations."""
        # RETURN (not raise) on bad ticker — a raised ValueError here crashes
        # the live chat SSE stream; a returned string lets the LLM recover.
        try:
            norm = validate_ticker(ticker)
        except ValueError:
            return f"Invalid ticker symbol: {ticker}"
        # Coerce the enum up front: an unguarded DataType(bad) inside fetch()
        # raises ValueError that would tear down the SSE stream. ModelRetry feeds
        # the error back so the model self-corrects to a valid value.
        try:
            dt = DataType(data_type)
        except ValueError as exc:
            raise ModelRetry(
                f"Unknown data_type {data_type!r}. Valid values: {[d.value for d in DataType]}"
            ) from exc
        # PRICE / FINANCIALS MUST come through the canonical (validated,
        # provenance-stamped) contract — the SAME path the pipeline and the
        # sub-agent tool use (fetch_canonical, ADR-0006). Bare fetch() here was
        # a SECOND, un-validated quote source: chat could narrate a different
        # "current price" than the report for the same ticker (the exact
        # two-prices-in-one-artifact failure fixed in agents/factory.py — this
        # Mode A twin was the unsynced sibling).
        if dt in (DataType.PRICE, DataType.FINANCIALS):
            normalized = await ctx.deps.data_layer.fetch_canonical(dt, norm)
            if isinstance(normalized, NormalizedPrice):
                body = json.dumps(normalized.to_prompt_summary(), indent=2, default=str)
            else:
                body = normalized.model_dump_json(indent=2)
            return (
                f"[canonical] {dt.value} (normalized contract — the single "
                f"source of truth; quote these figures verbatim)\n"
                f"```json\n{body}\n```"
            )
        result = await ctx.deps.data_layer.fetch(dt, norm)
        if dt is DataType.NEWS:
            # Headlines are third-party text — flatten + untrusted-wrap before
            # they enter the chat context (BUG-087 choke point, mirror of the
            # sub-agent tool).
            return render_news_for_prompt(result)
        return result.to_context_string()

    @agent.tool
    async def ask_filings(ctx: RunContext[FinRobotDeps], ticker: str, question: str) -> str:
        """Answer a question about a company's latest SEC 10-K, grounded in the
        filing's actual text (BM25 retrieval over the filing + section citations).

        Use this for QUALITATIVE 10-K content the structured-data tools cannot
        answer: risk factors, business description, competition, legal
        proceedings, MD&A commentary, segment notes. The answer cites its source
        sections (e.g. [Item 1A]); if the filing lacks the information it says so
        rather than guessing. For numeric financials use query_financial_data.
        """
        # RETURN (not raise) on a bad ticker — a raised ValueError tears down the
        # live chat SSE stream; a returned string lets the LLM recover.
        try:
            norm = validate_ticker(ticker)
        except ValueError:
            return f"Invalid ticker symbol: {ticker}"
        # run_qa raises ValueError when EDGAR has no 10-K or no extractable
        # sections — RETURN that message for the same SSE-safety reason as above
        # (contract shared with query_financial_data / find_reports).
        try:
            return await run_qa(ctx.deps.data_layer, ctx.deps.settings, norm, question)
        except ValueError as exc:
            return str(exc)

    @agent.tool
    async def query_coverage_universe(ctx: RunContext[FinRobotDeps], refresh: bool = False) -> str:
        """List the user's watchlist (Studied Tickers) with each name's live snapshot.

        Most watchlist questions are already answerable from the "User's watchlist"
        block in your system context — it is injected EVERY turn. Call this tool
        only when you need data NOT in that block, or when the user explicitly asks
        for fresh/live numbers.

        refresh=False (default): instant, reads the local cache — cheap, but the
        prices may be the same last-known snapshot already in your context.
        refresh=True: triggers a live provider fetch for every name — SLOW; use it
        ONLY when the user explicitly wants real-time prices.

        Returns one compact line per name (ticker / price / 1d% / verdict / live
        upside / signal). Caliber: ``upside`` uses a LIVE-price denominator
        ((target − price) / price) — it is NOT the report's entry-based upside;
        never conflate them.
        """
        store = ctx.deps.coverage_store
        if store is None or ctx.deps.artifact_store is None:
            return (
                "The watchlist isn't available in this session (no Coverage Desk is "
                "wired up). Ask the user for a ticker and use query_financial_data."
            )
        group = await store.get_system_group()
        if group is None or not group.members:
            return "The user's watchlist is empty — no Studied Tickers yet."
        overview = await build_overview(
            group,
            artifact_store=ctx.deps.artifact_store,
            data_layer=ctx.deps.data_layer,
            cache_only=not refresh,
        )
        return format_coverage_for_tool(overview)

    @agent.tool
    async def find_reports(ctx: RunContext[FinRobotDeps], ticker: str, limit: int = 5) -> str:
        """Locate the user's previously-run reports for a ticker (newest first).

        Use when the user references a report they ALREADY ran ("the AAPL report I
        ran earlier", "my last analysis", "compare to the previous run") and it is
        not the one open in the ContextBar. Returns one line per saved artifact
        (id, date, type, verdict, target, entry) so you can confirm it exists and
        offer to open / compare / re-run it. Do NOT run a deep pipeline just to
        surface a report the user already has — that creates a duplicate; call
        this instead. This tool only locates; it never creates a report.
        """
        store = ctx.deps.artifact_store
        if store is None:
            return "Report history isn't available in this session (no artifact store)."
        # RETURN (not raise) on a bad ticker — a raised ValueError tears down the
        # live chat SSE stream; a returned string lets the LLM recover.
        try:
            norm = validate_ticker(ticker)
        except ValueError:
            return f"Invalid ticker symbol: {ticker}"
        summaries = await store.list_by_ticker(ticker=norm, limit=limit)
        if not summaries:
            return f"No saved reports for {norm} yet — run an analysis to create one."
        return _format_reports_for_tool(norm, summaries)

    @agent.tool
    async def diff_reports(ctx: RunContext[FinRobotDeps], a_id: str, b_id: str) -> str:
        """Compare two saved reports and explain what changed and WHY.

        ``a_id`` = the older/base version, ``b_id`` = the newer version. Returns
        the conclusion deltas (rating / target / upside), the assumption drivers
        (WACC, terminal growth, …), and a DETERMINISTIC single-factor attribution
        of the fair-value change (re-priced through the DCF, not guessed). Use
        when the user asks "what changed between my two AAPL reports", "why did
        the target move", or "diff these versions". Call find_reports first to
        get the two artifact ids. Both must already exist — this never creates a
        report.
        """
        store = ctx.deps.artifact_store
        if store is None:
            return "Report history isn't available in this session (no artifact store)."
        a = await store.get(a_id)
        b = await store.get(b_id)
        # RETURN (not raise) on a missing id — a raised error tears down the live
        # chat SSE stream; a returned string lets the LLM ask the user to confirm
        # the id (e.g. via find_reports). The explicit None-guard also narrows
        # both to Artifact for build_semantic_delta (mypy --strict).
        if a is None or b is None:
            missing = ", ".join(aid for aid, art in ((a_id, a), (b_id, b)) if art is None)
            return f"Report(s) not found: {missing}. Use find_reports to list valid ids."
        return _format_delta_for_tool(build_semantic_delta(a, b))

    @agent.tool
    async def run_monte_carlo(ctx: RunContext[FinRobotDeps], ticker: str) -> str:
        """Run a Monte Carlo DCF: thousands of randomized DCF valuations → a
        probability distribution of fair value per share.

        Returns the percentile band (P5 / P25 / median / P75 / P95), mean/std,
        and where the CURRENT price sits in that distribution — so the user sees
        how aggressive the market is versus the model. Deterministic NumPy
        simulation the model cannot replicate by guessing. Use when the user
        asks: monte carlo, fair-value distribution / range, valuation
        uncertainty, or the probability the stock is over/undervalued. The DCF is
        seeded automatically from live financials — no prior DCF run needed.
        """
        try:
            norm = validate_ticker(ticker)
        except ValueError:
            return f"Invalid ticker symbol: {ticker}"
        # Seed a fresh DCF from live data via the shared coordinator (same path as
        # the REST /compute/dcf-seed endpoint). RETURN provider/seed failures as a
        # string — a raised error tears down the live chat SSE stream.
        try:
            financial_data, dcf_inputs = await seed_dcf_inputs_for_ticker(
                ctx.deps.data_layer,
                norm,
                fmp_api_key=getattr(ctx.deps.settings, "fmp_api_key", None),
            )
        except (
            ProviderError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
        ) as exc:
            return f"Couldn't seed a DCF for {norm} to simulate: {exc}"
        current_price = financial_data.market.current_price
        try:
            # Deterministic seed (ticker + UTC day): re-asking in the same chat
            # session reproduces the same distribution instead of jittering.
            result = run_monte_carlo_sim(
                dcf_inputs, current_price=current_price, seed=deterministic_seed(norm)
            )
        except ValueError as exc:
            # The operator raises when too few simulations stay valid (degenerate
            # assumptions); surface it rather than crash the stream.
            return f"Monte Carlo could not converge for {norm}: {exc}"
        return _format_monte_carlo_for_tool(norm, current_price, result)

    @agent.tool
    async def run_backtest(
        ctx: RunContext[FinRobotDeps],
        ticker: str,
        start_date: str,
        end_date: str,
        fast: int = 10,
        slow: int = 30,
    ) -> str:
        """Backtest an SMA-crossover strategy on a US equity over a date window.

        Returns total & annualized return, Sharpe ratio, max drawdown, trade
        count and win rate. ``start_date`` / ``end_date`` are YYYY-MM-DD; ``fast``
        / ``slow`` are the moving-average window lengths (fast < slow; default
        10 / 30). Use when the user asks to backtest, test a moving-average
        crossover, or see how a simple rule would have performed historically.
        US equities only; assumes zero commission and zero slippage, so real-world
        returns would be lower (the result spells this out).
        """
        try:
            norm = validate_ticker(ticker)
        except ValueError:
            return f"Invalid ticker symbol: {ticker}"
        # BacktestConfig validates date format/order; a raised ValidationError
        # would tear down the live chat SSE stream, so RETURN it as a string.
        try:
            config = BacktestConfig(
                ticker=norm,
                start_date=start_date,
                end_date=end_date,
                strategy="sma_crossover",
                strategy_params={"fast": fast, "slow": slow},
            )
        except ValidationError as exc:
            return f"Invalid backtest request: {exc}"
        # The run touches the data layer + backtrader; surface every concrete
        # failure (backtrader missing, non-US ticker, empty price window) as a
        # string rather than crashing the stream.
        try:
            result = await BackTraderAdapter(ctx.deps.data_layer).run(config)
        except (ProviderError, ValueError, ImportError, RuntimeError, KeyError, OSError) as exc:
            return f"Backtest could not run for {norm}: {exc}"
        header = f"Backtest — {norm}, SMA {fast}/{slow} crossover, {start_date} → {end_date}:"
        return f"{header}\n{result.format_summary()}"

    @agent.tool
    async def activate_skill(ctx: RunContext[FinRobotDeps], skill_id: str) -> str:
        """Activate a skill for ad-hoc professional workflows.
        Use this for tasks that don't have a dedicated pipeline."""
        if not ctx.deps.skill_runtime:
            return "Skill system is not yet available. Use direct data queries or pipeline commands instead."
        skill = ctx.deps.skill_runtime.get(skill_id)
        if not skill:
            return f"Unknown skill. Available: {ctx.deps.skill_runtime.list_ids()}"
        # Render the pipeline-safe methodology, not the raw SKILL.md body. The raw
        # body carries interactive Claude-Code checkpoints ("wait for user
        # approval", "one task at a time") that, leaked into Mode A chat driving an
        # unattended report run, instruct the agent to stop and wait for a human.
        # This is the same distillation Mode B applies via _resolve_step_methodology
        # — Mode A and Mode B now consume one identical rendering path.
        return render_pipeline_methodology(skill)

    # --- Mode B tools: pipeline dispatch for deep analysis ---
    #
    # Generated from the pipeline registry (the single source of truth) instead
    # of seven hand-copied @agent.tool wrappers. Adding a pipeline is now a
    # one-line change to engine/pipelines/registry.py. The tool NAME and the
    # LLM-facing DESCRIPTION come verbatim from each PipelineSpec — the
    # description is the LLM's tool-selection signal, so it carries the original
    # docstrings unchanged. ``ctx.deps`` and behaviour are identical to the old
    # wrappers (each still dispatches through ``_run_pipeline_tool``).
    spec: PipelineSpec
    for spec in iter_pipeline_specs():
        # Decorator form (keyword-only name/description) — the positional-arg
        # overload of agent.tool does not accept name/description.
        agent.tool(name=spec.tool_name, description=spec.tool_description)(
            _make_pipeline_tool(spec.factory(sub_agents))
        )

    return agent  # type: ignore[return-value]
