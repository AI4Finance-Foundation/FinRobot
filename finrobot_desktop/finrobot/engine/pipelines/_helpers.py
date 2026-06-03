"""Shared execute_fn factories for pipeline steps that fetch + extract financial data."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.exceptions import AgentRunError
from pydantic import ValidationError

from finrobot.engine.compute.data_processor import forecast_financials
from finrobot.engine.compute.extractor import (
    extract_company_financials,
    extract_financial_data,
    normalize_peer_to_usd,
)
from finrobot.engine.compute.historical_extractor import fetch_historical_metrics
from finrobot.engine.compute.multiples import (
    calculate_core_pe,
    calculate_multiples,
    calculate_peer_statistics,
)
from finrobot.engine.compute.valuation_aggregator import aggregate_valuation
from finrobot.engine.compute.valuation_synthesis import synthesize_valuations
from finrobot.engine.compute.xbrl_aligned_comps import (
    build_xbrl_aligned_company,
    override_company_with_xbrl,
)
from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.types import DataType
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.models.financial import (
    CompanyFinancials,
    DCFResult,
    DDMResult,
    FinancialData,
    ForecastResult,
    HistoricalMetrics,
    LBOResult,
    MarginAssumptions,
    PeerComps,
    PeerSelection,
    StepOutput,
    ValuationMethod,
    ValuationSynthesis,
)

logger = logging.getLogger(__name__)

# Peer comp-set sizing. The LLM over-selects (6-8 ranked candidates) so that
# transient drops (a rate-limited financials fetch, a missing FX quote for a
# foreign ADR) thin the set instead of failing the whole report. MIN is the
# floor for a defensible median; MAX caps the published comp set.
_PEER_COMP_SET_MIN = 3
_PEER_COMP_SET_MAX = 6


def _find_target_financial_data(structured_context: dict[str, object]) -> FinancialData | None:
    """Locate the target's FinancialData regardless of which step produced it.

    equity_research names the data step ``data_collection``; comps names it
    ``target_data``. Search by type so the shared peer-analysis executor works
    in both pipelines without hard-coding a step key.
    """
    direct = structured_context.get("data_collection")
    if isinstance(direct, FinancialData):
        return direct
    for value in structured_context.values():
        if isinstance(value, FinancialData):
            return value
    return None


def _peer_override(raw: object) -> list[str] | None:
    """Validated custom peer tickers from the ``peers`` run kwarg, or None to
    fall back to LLM selection.

    Accepts a list/tuple of tickers or a comma-separated string; upper-cases,
    strips, dedupes (order-preserving), and drops blanks. Returns None for an
    absent/empty/unrecognized value so the caller runs the normal LLM path.
    """
    if isinstance(raw, str):
        items: list[str] = raw.split(",")
    elif isinstance(raw, (list, tuple)):
        items = [str(x) for x in raw]
    else:
        return None
    deduped: dict[str, None] = {}
    for item in items:
        sym = item.strip().upper()
        if sym:
            deduped.setdefault(sym, None)
    return list(deduped) or None


async def _llm_select_peers(deps: FinRobotDeps, prompt: str) -> PeerSelection:
    """LLM peer selection (ranked, same-industry judgment). Raises ValueError
    if the model fails to produce a valid selection."""
    peer_agent = Agent(
        deps.settings.create_model(),
        output_type=PeerSelection,
        instructions=(
            "Select 6-8 comparable publicly traded companies for peer analysis, "
            "RANKED most-comparable first. "
            "Choose companies in the same sector with similar business models and market cap. "
            "Return valid ticker symbols only (e.g. MSFT, GOOGL, not 'Microsoft').\n\n"
            "**为什么要 6-8 个（不是 3-5）**：下游只保留前几个能成功取到财报的，"
            "多出来的是冗余保险——任一 peer 的数据源被限流 / 取不到 FX 汇率时直接丢弃，"
            "靠排名靠后的候补补位，避免'少一个就整份研报失败'。所以宁多勿少。\n\n"
            "**优先美股上市 peer**：外国 ADR（如 BIDU/TSM）需要把本币财报按即期汇率"
            "归一到 USD，汇率源限流时该 peer 会被丢弃。同 industry 下优先选美股本币(USD)公司，"
            "外国 peer 可以放进列表但排在靠后位置当候补。\n\n"
            "**Peer 选择硬约束**：\n"
            "所有 peer 必须与 target 的 yfinance industry 字段完全一致（不是 sector，是 industry）。\n"
            "例：AAPL industry='Consumer Electronics' → peer 必须也是 Consumer Electronics。\n"
            "不允许跨 industry 选 peer（即使同 sector）。\n"
            "如果合规 peer 不足 6 个，按实际数量给（最少 3 个），不要补凑跨 industry 的。"
        ),
        defer_model_check=True,
    )
    try:
        peer_result = await peer_agent.run(prompt, deps=deps)  # type: ignore[call-overload]
        return peer_result.output  # type: ignore[no-any-return]
    except AgentRunError:
        # Recoverable by type (rate-limit / transient LLM error). base.py
        # retries these 3× with backoff — re-wrapping into ValueError would
        # mark it non-recoverable and abort the whole run with zero retries.
        raise
    except (ValidationError, ValueError) as e:
        # Structured-output schema failure is deterministically non-recoverable:
        # the same prompt yields the same invalid shape, so retrying is wasted
        # budget. Keep it wrapped as a non-recoverable ValueError.
        raise ValueError(f"Failed to select peer companies: {e}") from e


async def execute_peer_analysis(
    agent: Agent[Any, Any],
    deps: FinRobotDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
    **kwargs: object,
) -> StepOutput:
    """Select peer tickers, then fetch + compute multiples deterministically.

    Peers come from the LLM (ranked, same-industry judgment) UNLESS the caller
    passes ``peers=[...]`` (e.g. ``finrobot comps --peers AAPL,MSFT``), in which
    case the LLM selection is skipped and the user's set is used verbatim. Either
    path runs the identical fetch / FX-normalize / multiples / median math, so a
    custom peer set yields the same traceable multiples — only membership changes.
    Shared by equity_research and the standalone comps pipeline so BOTH emit
    deterministic, traceable multiples instead of LLM free text."""
    override = _peer_override(kwargs.get("peers"))
    if override is not None:
        if not _PEER_COMP_SET_MIN <= len(override) <= 10:
            raise ValueError(
                f"--peers needs {_PEER_COMP_SET_MIN}-10 tickers, got {len(override)}: {override}"
            )
        logger.info("Peer analysis using caller-supplied peers: %s", override)
        selection = PeerSelection(tickers=override, rationale="Caller-supplied peer set (--peers).")
    else:
        selection = await _llm_select_peers(deps, prompt)

    async def _fetch_one_peer(peer_ticker: str) -> CompanyFinancials | None:
        try:
            _fin = await deps.data_layer.fetch_canonical(DataType.FINANCIALS, peer_ticker)
            company = extract_company_financials(_fin)
            # Normalize foreign-listed ADRs / local listings to canonical USD
            # BEFORE multiples are computed — otherwise TSM (TWD financials,
            # USD market_cap) collapses EV/EBITDA to 0.158x. A failed FX lookup
            # falls through to the outer except and drops this peer; thinning
            # the set beats publishing a mixed-unit multiple.
            company = await normalize_peer_to_usd(
                company, fmp_api_key=getattr(deps.settings, "fmp_api_key", None)
            )
            company = calculate_multiples(company)
            xbrl_result = await deps.data_layer.fetch(DataType.XBRL_FACTS, peer_ticker)
            return override_company_with_xbrl(company, xbrl_result.data)
        except (ProviderError, ValueError, KeyError, ArithmeticError) as e:
            logger.warning(f"Skipping peer {peer_ticker}: {e}")
            return None

    # The LLM over-selects (6-8 ranked candidates); we fetch all concurrently and
    # keep the survivors in rank order, capped at PEER_COMP_SET_MAX. Extra
    # candidates are drop-insurance: a rate-limited financials fetch or a missing
    # FX quote drops that one peer instead of failing the whole report. gather +
    # the order-preserving comprehension keep best-first ranking, so the slice
    # retains the most-comparable survivors.
    peer_results = await asyncio.gather(*[_fetch_one_peer(t) for t in selection.tickers])
    survivors: list[CompanyFinancials] = [p for p in peer_results if p is not None]
    peers: list[CompanyFinancials] = survivors[:_PEER_COMP_SET_MAX]

    # A thin comp set is a QUALITY problem, not a crash. peer_analysis is a
    # non-critical step in both pipelines, and the step's validator
    # (validate_peer_comps / validate_has_peers, min_peers=3) already gates a thin
    # set — failing validation triggers a re-selection retry (the LLM may pick a
    # luckier, fully-fetchable set) and, if still thin after retries, degrades
    # best-effort instead of tanking the whole report.
    #
    # Two cases:
    #   • 1..MIN-1 survivors → build the thin PeerComps anyway, tag a warning so
    #     it surfaces in the artifact, and let the validator fail it (→ retry →
    #     degrade). NEVER raise on count here: recoverability is decided BY
    #     exception type, not by matching substrings in a message, so a raise
    #     would not be treated as retryable and would crash the run.
    #   • 0 survivors → PeerComps requires >=1 peer (Field min_length=1), so we
    #     can't build one at all. Raise ProviderError — recoverable BY TYPE (not
    #     by message text), so it retries with backoff then degrades on the
    #     non-critical step, never surfacing a raw pydantic ValidationError.
    if not peers:
        raise ProviderError(
            f"No comparable peers returned usable financials for {ticker} "
            f"(0 of {len(selection.tickers)} candidates: {selection.tickers}). "
            f"All peer financials/FX fetches failed — usually transient provider "
            f"rate-limiting; retry shortly."
        )
    thin_warning: str | None = None
    if len(peers) < _PEER_COMP_SET_MIN:
        thin_warning = (
            f"Thin comp set: only {len(survivors)} of {len(selection.tickers)} "
            f"candidate peers returned usable financials (target >="
            f"{_PEER_COMP_SET_MIN}). Candidates: {selection.tickers}. Usually "
            f"transient data-provider rate-limiting (yfinance 429) or a missing "
            f"FX quote for a foreign-listed peer — median multiples below are "
            f"less reliable; retry shortly for a fuller set."
        )
        logger.warning("%s (target=%s)", thin_warning, ticker)

    target_fin = _find_target_financial_data(structured_context)
    if target_fin is None:
        raise ValueError("target FinancialData not available in context; cannot build peer target.")
    raw_target_xbrl = structured_context.get("xbrl_facts_raw")
    target_xbrl = raw_target_xbrl if isinstance(raw_target_xbrl, dict) else None
    target = await build_xbrl_aligned_company(
        ticker=ticker,
        financial_data=target_fin,
        xbrl_data=target_xbrl,
        fmp_api_key=getattr(deps.settings, "fmp_api_key", None),
    )

    peer_comps = PeerComps(
        target=target,
        peers=peers,
        peer_justification=selection.rationale,
    )
    peer_comps = calculate_peer_statistics(peer_comps)
    # NOPAT core P/E (target + peers) so the comps_pe method pairs a core peer
    # median with the target's core EPS — one earnings caliber on both sides.
    peer_comps = calculate_core_pe(peer_comps)
    if thin_warning is not None and thin_warning not in peer_comps.warnings:
        peer_comps.warnings.insert(0, thin_warning)

    # Surface per-row XBRL-vs-FMP TTM divergence flags (ADR-0008) so a kept-FMP
    # [待核] doesn't stay buried on the CompanyFinancials row.
    for company in (peer_comps.target, *peer_comps.peers):
        note = company.ttm_divergence_note
        if note and note not in peer_comps.warnings:
            peer_comps.warnings.append(f"{company.ticker}: {note}")

    ev_ebitda_str = (
        f"{peer_comps.median_ev_ebitda:.1f}x" if peer_comps.median_ev_ebitda is not None else "N/A"
    )
    pe_str = f"{peer_comps.median_pe:.1f}x" if peer_comps.median_pe is not None else "N/A"
    narrative = (
        f"Peer set ({len(peers)} companies): {', '.join(p.ticker for p in peers)}. "
        f"Median EV/EBITDA: {ev_ebitda_str}. "
        f"Median P/E: {pe_str}. "
        f"{selection.rationale}"
    )
    return StepOutput(text=narrative, structured=peer_comps)


async def execute_financial_data_step(
    agent: Agent[Any, Any],
    deps: FinRobotDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
    **_kwargs: object,
) -> StepOutput:
    """Standard data-collection step: run agent + fetch financials/price + extract.

    Used by equity_research, dcf, lbo, comps pipelines.  Centralised here so
    changes to extraction logic propagate everywhere.

    Also builds HistoricalMetrics and ForecastResult from multi-year data
    and injects them into structured_context for chart generation.
    """
    step_result = await agent.run(prompt, deps=deps)
    _fin = await deps.data_layer.fetch_canonical(DataType.FINANCIALS, ticker)
    _price = await deps.data_layer.fetch_canonical(DataType.PRICE, ticker)
    financial_data = extract_financial_data(_fin, _price)
    # Cross-validation warnings are already carried on the canonical objects and
    # merged into FinancialData.warnings inside extract_financial_data — no
    # further merging needed here.

    # Build multi-year historical metrics + forecast for chart generation.
    # These are deterministic — no LLM call needed.
    # structured_context IS structured_results (same dict reference) so
    # writes here persist into PipelineResult.structured_data.
    hm = await _build_historical_metrics(deps, ticker)
    if hm is not None:
        structured_context["historical_metrics"] = hm
        logger.info(
            "HistoricalMetrics built for %s: %d years (%s)",
            ticker,
            len(hm.years),
            hm.years,
        )
        forecast = _build_forecast(hm)
        if forecast is not None:
            structured_context["forecast"] = forecast
            logger.info("ForecastResult built for %s: %d years", ticker, len(forecast.years))
    else:
        logger.info("HistoricalMetrics not available for %s — charts will be limited", ticker)

    logger.info(
        "structured_context keys after data_collection: %s",
        list(structured_context.keys()),
    )
    return StepOutput(text=step_result.output, structured=financial_data)


async def _build_historical_metrics(deps: FinRobotDeps, ticker: str) -> HistoricalMetrics | None:
    """Build multi-year HistoricalMetrics for charts + DCF seeding.

    Delegates to ``fetch_historical_metrics`` — the single canonical extractor
    every other pipeline/route already uses (dcf, lbo, ic_memo, equity_research's
    own modeling-step fallback, routes/compute, routes/data). It reads CapEx /
    D&A / ΔNWC straight from the raw per-year provider dicts.

    The previous FinancialData→``extract_historical_metrics`` path silently
    DROPPED those three cash-flow fields (they never round-tripped through
    FinancialData), so ``dcf_seed`` saw empty CapEx/D&A history and fell back to
    the Damodaran industry aggregate — for ``Software (Internet)`` that means
    CapEx = 31.8% of revenue (an aggregate skewed by cash-burning small-caps),
    which crushed a profitable mega-cap's projected FCF to ~0 and produced a
    NEGATIVE implied price (META: −$22, failing the DCF validator every run).
    Consuming the same complete extractor as everyone else removes that path
    split. Returns None when fewer than 2 usable years exist (caller skips
    chart/forecast generation).
    """
    try:
        hm = await fetch_historical_metrics(deps.data_layer, ticker, years=5)
    except (ValueError, KeyError, TypeError, RuntimeError, AttributeError, OSError) as e:
        logger.warning("Failed to build HistoricalMetrics for %s: %s", ticker, e)
        return None
    if len(hm.years) < 2:
        logger.info(
            "Only %d year(s) of data for %s — skipping HistoricalMetrics",
            len(hm.years),
            ticker,
        )
        return None
    return hm


def _build_forecast(hm: HistoricalMetrics) -> ForecastResult | None:
    """Build 3-year forecast from historical metrics with reasonable defaults."""
    try:
        # Use historical revenue growth trend, clamped to reasonable range
        growth_rates = []
        valid_growths = [g for g in hm.revenue_growth_yoy if g is not None]
        if valid_growths:
            avg_growth = sum(valid_growths) / len(valid_growths)
            # Clamp to [-10%, +30%] and fade toward long-term average
            base = max(-0.10, min(0.30, avg_growth))
            growth_rates = [base, base * 0.9, base * 0.8]  # fade down
        else:
            growth_rates = [0.05, 0.04, 0.03]  # conservative defaults

        return forecast_financials(
            historical=hm,
            revenue_growth_assumptions=growth_rates,
            margin_assumptions=MarginAssumptions(),  # use historical averages
        )
    except (ValueError, ZeroDivisionError, TypeError) as e:
        logger.warning("Failed to build ForecastResult: %s", e)
        return None


def build_sensitivity_ranges(
    discount_rate: float, terminal_growth: float
) -> tuple[list[float], list[float]]:
    """Build (discount-rate, terminal-growth) sweep ranges for sensitivity tables.

    Used by DCF (discount_rate=WACC) and DDM (discount_rate=cost of equity).
    Both apply a ±2% sweep around discount_rate paired with terminal-growth
    candidates filtered to stay strictly below min(discount_rate_range), so
    every cell in the resulting grid is a valid Gordon-growth denominator.

    The lower cells are floored at ``terminal_growth + 0.005`` (not a hardcoded
    3%) to keep every rate a valid Gordon denominator. Because that floor is
    below ``discount_rate`` for any sound DCF (WACC > terminal growth), the
    center cell (index 2) always equals ``discount_rate`` — so the sensitivity
    table's center matches the narrative's base-case implied price (BUG-013).
    The old absolute 3% floor clobbered the center whenever WACC < 3%, shifting
    it off the base case by a large margin. (For very low WACC the bottom cells
    may clamp to the floor and repeat; they stay valid, the center stays exact.)
    """
    rate_floor = terminal_growth + 0.005
    rate_range = [round(max(rate_floor, discount_rate - 0.02 + i * 0.01), 4) for i in range(5)]
    tg_candidates = [round(max(0.0, terminal_growth - 0.01 + i * 0.005), 4) for i in range(5)]

    min_rate = min(rate_range)
    tg_range = [g for g in tg_candidates if g < min_rate]

    if len(tg_range) < 2:
        tg_range = [round(0.005 + i * 0.005, 4) for i in range(5) if 0.005 + i * 0.005 < min_rate]

    return rate_range, tg_range


def build_valuation_synthesis(
    structured_context: dict[str, object],
    current_price: float,
    ticker: str,
) -> ValuationSynthesis | None:
    """Build ValuationSynthesis from pipeline structured_context via aggregate_valuation.

    Replaces the old 2-method (DCF + EV/EBITDA) hand-rolled logic with the
    canonical 6-method ``aggregate_valuation`` function used by the REST endpoint.
    Adapts ``ValuationAggregate`` → ``ValuationSynthesis`` so the thesis step
    contract (``ValuationSynthesis``) stays intact.

    When only one method resolves, ``weighted_price`` will be None and the
    thesis step will NOT inject an authoritative price target — the LLM narrates
    without a forced number rather than surfacing a spurious single-method "average".
    """
    dcf = structured_context.get("financial_modeling")
    peers = structured_context.get("peer_analysis")
    ddm = structured_context.get("ddm_calc")
    lbo = structured_context.get("lbo_calc")

    financial_data = structured_context.get("data_collection")
    shares: float | None = None
    if isinstance(financial_data, FinancialData):
        shares = financial_data.market.shares_outstanding
    # Fall back to DCFInputs.shares_outstanding when FinancialData is absent.
    # DCF seed always carries this value from the data-collection step, so this
    # keeps comps_pe functional in the common case where dcf resolved but
    # data_collection is not re-stored in the same dict slice.
    if shares is None and isinstance(dcf, DCFResult):
        shares = dcf.inputs.shares_outstanding

    agg = aggregate_valuation(
        ticker=ticker,
        current_price=current_price,
        dcf=dcf if isinstance(dcf, DCFResult) else None,
        peer_comps=peers if isinstance(peers, PeerComps) else None,
        ddm=ddm if isinstance(ddm, DDMResult) else None,
        lbo=lbo if isinstance(lbo, LBOResult) else None,
        shares_outstanding=shares,
    )

    if not agg.methods:
        return None

    for w in agg.warnings:
        logger.debug("valuation_synthesis: %s", w)

    # Convert ValuationMethodRange → ValuationMethod for the thesis contract.
    vm_list: list[ValuationMethod] = [
        ValuationMethod(
            name=r.method,
            low=r.low,
            mid=r.mid,
            high=r.high,
            confidence=r.confidence,
            source=r.source,
            assumptions=r.assumptions,
        )
        for r in agg.methods
    ]

    try:
        return synthesize_valuations(vm_list, current_price)
    except ValueError as e:
        logger.warning("Failed to build ValuationSynthesis: %s", e)
        return None
