from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Final, Literal

import httpx
from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.exceptions import AgentRunError

from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.types import DataType
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.models.financial import (
    CatalystAnalysis,
    CatalystEvent,
    DCFResult,
    DDMInputs,
    FinancialData,
    HistoricalMetrics,
    ThesisResult,
    StepOutput,
    ValuationSynthesis,
)
from finrobot.engine.compute.operators.residual_income import calculate_residual_income
from finrobot.engine.compute.operators.audit import (
    audit_momentum_narrative_hedge,
    audit_narrative_numeric_grounding,
    compute_momentum_context,
)
from finrobot.engine.models.reconcile_tolerances import NARRATIVE_DRIFT_TOLERANCE
from finrobot.engine.compute.operators.catalyst import (
    extract_catalysts_from_news,
    cluster_near_duplicates,
    filter_fresh_news,
    compute_expected_impact,
    summarize_catalyst_outlook,
)
from finrobot.engine.compute.operators.dcf import (
    calculate_dcf,
    calculate_sensitivity,
    classify_market_implied_nature,
    margin_swing,
    market_implied_check,
)
from finrobot.engine.compute.coordinators.segment_extractor import (
    build_segment_overview,
    build_sotp_breakdown,
)
from finrobot.engine.compute.operators.dcf_seed import dcf_current_actuals, seed_dcf_inputs
from finrobot.engine.compute.operators.forward_estimates import (
    ForwardFinancials,
    get_forward_revenue_growth,
)
from finrobot.engine.compute.operators.multiples import current_ev_ebitda
from finrobot.engine.compute.operators.valuation_synthesis import (
    CanonicalThesis,
    resolve_canonical_thesis,
    street_range_disclosure,
)
from finrobot.engine.compute.coordinators.extractor import normalize_financials_to_usd
from finrobot.engine.compute.coordinators.historical_extractor import fetch_historical_metrics
from finrobot.engine.data.historical_loaders import (
    REPORT_BAND_WINDOW_YEARS,
    fetch_reverse_multiple_band,
)
from finrobot.engine.data.providers.fx import fetch_fx_rate_to_usd
from finrobot.engine.compute.operators.ownership import compute_ownership_governance
from finrobot.engine.compute.coordinators.technical_payload import (
    TECHNICAL_DCF_UNAVAILABLE_MARKER,
    TechnicalAnalysis,
    build_technical_analysis,
)
from finrobot.engine.compute.operators.xbrl_aligned_comps import (
    xbrl_concept_snapshot,
)
from finrobot.engine.analysis.news_classifier import classify_news
from finrobot.engine.compute.coordinators.news import fetch_news
from finrobot.engine.pipelines.base import (
    Pipeline,
    PipelineStep,
    StructuredValidator,
    TextValidator,
)
from finrobot.engine.pipelines._helpers import (
    build_sensitivity_ranges,
    execute_financial_data_step,
    execute_peer_analysis,
)
from finrobot.engine.pipelines._thesis_prompt import build_thesis_prompt
from finrobot.engine.pipelines.ddm import _execute_ddm_calc, _execute_ddm_seed
from finrobot.engine.primitives.industry import (
    is_balance_sheet_financial,
    is_bank,
    is_commodity_cyclical,
)
from finrobot.engine.pipelines.validators import (
    validate_catalyst_analysis,
    validate_has_fields,
    validate_has_peers,
    validate_has_thesis,
    validate_report_format,
    validate_is_non_empty,
    validate_financial_data,
    validate_ownership_governance,
    validate_peer_comps,
    validate_dcf_result,
    validate_technical_analysis,
    validate_thesis,
)

logger = logging.getLogger(__name__)

# Hard ceiling for a single optional SEC fetch. edgartools is a sync-blocking
# library with its OWN retry loop, run via asyncio.to_thread — so the provider's
# httpx _TIMEOUT does NOT bound it. Without this ceiling a flaky SEC (observed:
# 8-K SSL handshake timeouts under throttling) lets one edgartools call block
# the data_collection gather for minutes, freezing the whole run at step 1
# "数据收集" with no progress. SEC data is OPTIONAL (this is _fetch_optional_sec),
# so exceeding the ceiling degrades to "unavailable" instead of stalling.
_SEC_FETCH_TIMEOUT_S = 30.0


async def _fetch_optional_sec(
    deps: FinRobotDeps,
    ticker: str,
    data_type: DataType,
    **kwargs: Any,
) -> dict[str, Any]:
    # Optional data must never freeze (slow edgartools) or kill (raised
    # ConnectTimeout) the research run: bound the wait and swallow failures
    # into a degraded payload. Note asyncio.wait_for cancels OUR await but
    # cannot cancel the underlying to_thread worker — that thread finishes on
    # its own; the run proceeds without waiting for it.
    try:
        result = await asyncio.wait_for(
            deps.data_layer.fetch(data_type, ticker, **kwargs),
            timeout=_SEC_FETCH_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        msg = f"SEC {data_type.name} fetch exceeded {_SEC_FETCH_TIMEOUT_S:.0f}s — SEC slow/unreachable, skipped"
        logger.warning("%s (%s)", msg, ticker)
        return {"available": False, "error": msg, "warnings": [msg]}
    except (
        ProviderError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        httpx.HTTPError,
    ) as exc:
        # provider/network error on optional SEC data — non-fatal. httpx.HTTPError
        # is belt-and-suspenders: edgar_provider now wraps its httpx failures into
        # ProviderError at the boundary, but this guard's contract ("optional SEC
        # data must never kill the run") means we catch a raw transport error from
        # ANY future provider path too. Concrete types only: a bare `except
        # Exception` would swallow CancelledError and break client-disconnect
        # cleanup (test_no_bare_except_exception_in_finrobot).
        msg = f"SEC {data_type.name} fetch failed: {type(exc).__name__}"
        logger.warning("%s for %s: %s", msg, ticker, exc)
        return {"available": False, "error": msg, "warnings": [msg]}
    if result.data.get("error"):
        return {"available": False, "error": result.data["error"], "warnings": result.warnings}
    return {**result.data, "warnings": result.warnings, "provider": result.provider}


async def _execute_data_collection_with_sec(
    agent: Agent[Any, Any],
    deps: FinRobotDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
    **_kwargs: object,
) -> StepOutput:
    """Collect standard financials plus SEC filing/XBRL context."""
    financial_output = await execute_financial_data_step(
        agent,
        deps,
        prompt,
        structured_context,
        ticker,
    )

    tenk_task = _fetch_optional_sec(deps, ticker, DataType.FILINGS_10K)
    tenq_task = _fetch_optional_sec(deps, ticker, DataType.FILINGS_10Q, n=4)
    eightk_task = _fetch_optional_sec(deps, ticker, DataType.FILINGS_8K, n=10)
    xbrl_task = _fetch_optional_sec(deps, ticker, DataType.XBRL_FACTS)
    tenk, tenq, eightk, xbrl = await asyncio.gather(
        tenk_task,
        tenq_task,
        eightk_task,
        xbrl_task,
    )

    structured_context["sec_filings"] = {
        "10k": tenk,
        "10q_history": tenq.get("quarterly_filings", []),
        "8k_events": eightk.get("events", []),
    }
    structured_context["xbrl_facts_raw"] = xbrl
    structured_context["xbrl_facts_snapshot"] = xbrl_concept_snapshot(xbrl)

    sec_warnings = [
        warning for payload in (tenk, tenq, eightk, xbrl) for warning in payload.get("warnings", [])
    ]
    if isinstance(financial_output.structured, FinancialData):
        for warning in sec_warnings:
            if warning not in financial_output.structured.warnings:
                financial_output.structured.warnings.append(warning)

    return financial_output


# 8-K item codes that are filing mechanics / recurring disclosures, not discrete
# catalysts: Item 2.02 (earnings-release filing), 5.07 (annual-meeting vote
# results), 7.01 (Reg FD slides/PR), 9.01 (exhibits, attached to almost every
# 8-K). An 8-K whose items are ALL routine carries no forward catalyst signal —
# the 2026-06-09 TSLA report surfaced 8 identical content-free "Item 2.02,
# Item 9.01" stubs as catalysts. An 8-K is kept only when ≥1 item is non-routine.
_ROUTINE_8K_ITEMS: frozenset[str] = frozenset({"2.02", "5.07", "7.01", "9.01"})

# Plain-language labels for the material item codes we surface — a bare item
# number tells a reader nothing; "Executive / director change" does.
_8K_ITEM_LABELS: dict[str, str] = {
    "1.01": "Material agreement entered",
    "1.02": "Material agreement terminated",
    "1.03": "Bankruptcy or receivership",
    "2.01": "Acquisition or disposition completed",
    "2.03": "Material financial obligation created",
    "2.04": "Debt acceleration / triggering event",
    "2.05": "Exit or disposal costs",
    "2.06": "Material asset impairment",
    "3.01": "Delisting / listing-rule notice",
    "3.03": "Securityholder rights modified",
    "4.01": "Auditor change",
    "4.02": "Financial restatement (non-reliance)",
    "5.01": "Change in control",
    "5.02": "Executive / director change",
    "5.03": "Charter / bylaw amendment",
    "8.01": "Other material event",
}

# Cap on 8-K-derived catalysts so a busy filer can't crowd out genuine news
# catalysts. Material 8-Ks are rare; 5 most-recent is ample context.
_MAX_8K_CATALYSTS: Final[int] = 5


def _normalize_8k_items(items: list[str]) -> list[str]:
    """``'Item 5.02'`` → ``'5.02'`` (tolerate already-bare codes)."""
    return [str(raw).replace("Item", "").strip() for raw in items]


def _material_8k_codes(items: list[str]) -> list[str]:
    """Non-routine item codes — filing mechanics (2.02/5.07/7.01/9.01) dropped."""
    return [c for c in _normalize_8k_items(items) if c and c not in _ROUTINE_8K_ITEMS]


def _sec_8k_to_catalyst(event: dict[str, Any]) -> CatalystEvent:
    items = [str(i) for i in event.get("items", [])]
    material = _material_8k_codes(items)
    category: Literal[
        "product_launch",
        "earnings",
        "regulatory",
        "acquisition",
        "management",
        "market",
    ] = "regulatory"
    if any(c == "5.02" for c in material):
        category = "management"
    elif any(c in ("1.01", "1.02", "2.01") for c in material):
        category = "acquisition"

    labels = [_8K_ITEM_LABELS.get(c, f"8-K Item {c}") for c in material]
    headline = "SEC 8-K: " + "; ".join(labels) if labels else f"SEC 8-K filed: {', '.join(items)}"

    # Inject filing date and SEC URL for traceability
    raw_date = event.get("filing_date") or event.get("filed_at")
    published: datetime | None = None
    if raw_date:
        try:
            dt = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            published = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            published = None

    source_url: str | None = event.get("source_url") or None
    if source_url is None:
        accession_no = event.get("accession_no")
        if accession_no:
            source_url = (
                f"https://www.sec.gov/cgi-bin/browse-edgar"
                f"?action=getcompany&accession-number={accession_no}"
            )

    return CatalystEvent(
        category=category,
        headline=headline,
        sentiment="neutral",
        impact_score=3,
        # Internal weight (see extract_catalysts_from_news): a company-filed 8-K is a
        # primary-source fact, weighted 1.0 (> news 0.7) in the expected-impact aggregate.
        # CatalystEvent.probability is exclude=True, so this never leaks a fake "100%
        # probability" into any export/response — an 8-K is a past event, not a forecast.
        probability=1.0,
        reasoning=(
            "Source is a company-filed SEC 8-K current report; treated as "
            "primary-source catalyst context."
        ),
        published=published,
        url=source_url,
    )


async def _execute_catalyst_analysis(
    agent: Agent[Any, Any],
    deps: FinRobotDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
    **_kwargs: object,
) -> StepOutput:
    """Fetch news, classify, extract catalysts, compute impact, summarize.

    What this code does that raw LLM cannot:
    - Deterministic extraction of catalyst events from classified news
    - Quantitative expected-impact scoring with sentiment multiplier
    - Structured summary with net sentiment, category breakdown, top events
    - All computation is reproducible -- no LLM randomness in scoring
    """
    # Fetch and classify news. Pass the ticker so importance is scored for
    # relevance to THIS company — a ticker-blind classifier rated "Musk net worth
    # could top $1T" and "Nasdaq bounces" as top Tesla catalysts (2026-06-09).
    raw_news = await fetch_news(deps.data_layer, ticker)
    news_items = await classify_news(raw_news, deps, ticker=ticker)

    # Drop stale news (> 30 days old) before catalyst extraction
    fresh_news, stale_count = filter_fresh_news(news_items, max_age_days=30)
    if stale_count > 0:
        logger.debug("Dropped %d stale news items (>30 days) for %s", stale_count, ticker)

    # Extract catalysts from high-importance news
    catalysts = extract_catalysts_from_news(fresh_news)
    sec_filings = structured_context.get("sec_filings")
    if isinstance(sec_filings, dict):
        # Only MATERIAL 8-Ks become catalysts — a bare earnings-release filing
        # (Item 2.02/9.01) is filing mechanics, not a discrete catalyst. Keep the
        # most-recent few so a busy filer can't crowd out genuine news catalysts.
        material_8ks = [
            event
            for event in sec_filings.get("8k_events", [])
            if isinstance(event, dict)
            and _material_8k_codes([str(i) for i in event.get("items", [])])
        ]
        for event in material_8ks[:_MAX_8K_CATALYSTS]:
            catalysts.append(_sec_8k_to_catalyst(event))
    # Collapse near-duplicate coverage (one lawsuit across multiple law-firm
    # press releases = ONE catalyst) BEFORE scoring, so total_catalysts and
    # net_sentiment (which divides by len) aren't inflated by the same fact
    # repeated N times. Conservative clustering — never false-merges distinct
    # events. Runs after the 8-K append so SEC events are deduped against news too.
    catalysts = cluster_near_duplicates(catalysts)
    catalysts = compute_expected_impact(catalysts)
    summary = summarize_catalyst_outlook(catalysts)

    # Fetch retail sentiment (optional — Adanos provider may not be registered)
    sentiment_snapshot: dict[str, Any] | None = None
    try:
        sentiment_result = await deps.data_layer.fetch(DataType.SENTIMENT, ticker)
        if sentiment_result.data and not sentiment_result.data.get("error"):
            sentiment_snapshot = sentiment_result.data
    except (ProviderError, ValueError, KeyError):
        logger.debug("Retail sentiment not available for %s", ticker)

    # Build CatalystAnalysis
    net = summary["net_sentiment"]
    overall: Literal["bullish", "bearish", "neutral"]
    if net > 0.5:
        overall = "bullish"
    elif net < -0.5:
        overall = "bearish"
    else:
        overall = "neutral"

    top_pos = summary["top_positive"]
    analysis = CatalystAnalysis(
        events=catalysts,
        overall_sentiment=overall,
        key_catalysts=[e.headline for e in top_pos[:3]],
        net_sentiment=net,
        category_breakdown=summary["category_breakdown"],
        top_positive=summary["top_positive"],
        top_negative=summary["top_negative"],
    )

    # Build narrative
    cat_labels = ", ".join(f"{cat}({cnt})" for cat, cnt in summary["category_breakdown"].items())
    narrative = (
        f"Catalyst analysis: {summary['total_catalysts']} events identified. "
        f"Net sentiment: {net:+.2f} ({overall}). "
        f"Categories: {cat_labels or 'none'}."
    )
    if top_pos:
        narrative += f" Top catalyst: {top_pos[0].headline}."

    if sentiment_snapshot and sentiment_snapshot.get("average_buzz") is not None:
        narrative += (
            f" Retail sentiment: buzz {sentiment_snapshot['average_buzz']}/100, "
            f"bullish {sentiment_snapshot.get('bullish_avg', 'N/A')}%, "
            f"{sentiment_snapshot['source_alignment'].lower()} "
            f"({sentiment_snapshot['coverage']})."
        )

    if sentiment_snapshot:
        structured_context["retail_sentiment"] = sentiment_snapshot

    return StepOutput(text=narrative, structured=analysis)


async def _execute_ownership_governance_analysis(
    agent: Agent[Any, Any],  # noqa: ARG001
    deps: FinRobotDeps,
    prompt: str,  # noqa: ARG001
    structured_context: dict[str, object],
    ticker: str,
    **_kwargs: object,
) -> StepOutput:
    insider_task = _fetch_optional_sec(deps, ticker, DataType.INSIDER_TRADES, days=90)
    holdings_task = _fetch_optional_sec(deps, ticker, DataType.INSTITUTIONAL_HOLDINGS)
    proxy_task = _fetch_optional_sec(deps, ticker, DataType.PROXY_STATEMENT)
    schedule13_task = _fetch_optional_sec(deps, ticker, DataType.SCHEDULE_13)
    # SOX-302 CEO cert (Ex-31.1 of the latest 10-Q/10-K): the authoritative
    # current-CEO name, fresher than the annual proxy after a succession.
    cert_task = _fetch_optional_sec(deps, ticker, DataType.CEO_CERTIFICATION)
    insider, holdings, proxy, schedule13, cert = await asyncio.gather(
        insider_task, holdings_task, proxy_task, schedule13_task, cert_task
    )

    analysis = compute_ownership_governance(
        insider_data=insider,
        institutional_data=holdings,
        proxy_data=proxy,
        schedule13_data=schedule13,
        cert_data=cert,
    )

    # Populate degraded_reasons based on what _fetch_optional_sec returned.
    # "available": False means the provider returned an error payload.
    # Empty list/None after a successful fetch means no recent filings exist.
    if "insider_transactions" in analysis.degraded_sections:
        if insider.get("available") is False:
            error_str = str(insider.get("error", "")).lower()
            if "identity" in error_str or "cik" in error_str or "not found" in error_str:
                analysis.degraded_reasons["insider_transactions"] = "identity_missing"
            else:
                analysis.degraded_reasons["insider_transactions"] = "fetch_error"
        else:
            analysis.degraded_reasons["insider_transactions"] = "no_recent_filings"

    if "proxy_compensation" in analysis.degraded_sections:
        if proxy.get("available") is False:
            analysis.degraded_reasons["proxy_compensation"] = "fetch_error"
        else:
            # Either no filing returned or fields parsed to None (garbage in).
            analysis.degraded_reasons["proxy_compensation"] = "parse_failed"

    narrative = (
        f"Ownership & Governance: {len(analysis.insider_transactions)} insider "
        f"transactions, {len(analysis.institutional_holdings)} institutional holders, "
        f"proxy compensation {'available' if analysis.proxy_compensation else 'unavailable'}."
    )
    if analysis.degraded_sections:
        narrative += f" Degraded sections: {', '.join(analysis.degraded_sections)}."
    return StepOutput(text=narrative, structured=analysis)


def _forward_roe(
    ddm_inputs: DDMInputs,
    financial_data: FinancialData,
    fwd: object,
) -> float | None:
    """FY1 consensus ROE = trailing ROE × (consensus NI / trailing NI).

    The consensus NI is the FMP analyst FY1 MEAN (``netIncomeAvg``, same caliber as
    trailing net income). Both operands are USD: ``trail_ni`` is the FX-normalized
    canonical snapshot (execute_financial_data_step records income.net_income as
    "currency-clean USD"; forward_estimates likewise calls it the "USD-canonical
    trailing"), and ``fwd_ni`` is kept only when it passes get_forward_financials'
    ``_guard_fx_mismatch`` — a native-currency consensus (UMC's TWD) is abstained to
    None there, never divided against a USD trailing. So the NI-growth RATIO is unitless
    USD/USD (the FX guard, NOT a native-currency cancellation, is what makes the
    cross-currency case safe) with no book-caliber drift. The equity base is held at
    trailing — one year out the retained-book growth would lower the recovery ROE
    slightly, a mild conservative-toward-HOLD bias we accept and disclose rather than
    patch. Returns None when no usable forward estimate exists (the band falls back to
    single-stage trailing ± the method floor).
    """
    troe = ddm_inputs.return_on_equity
    if troe is None or troe <= 0 or not isinstance(fwd, ForwardFinancials):
        return None
    fwd_ni = fwd.forward_net_income
    trail_ni = financial_data.income.net_income
    if not fwd_ni or fwd_ni <= 0 or not trail_ni or trail_ni <= 0:
        return None
    return troe * (fwd_ni / trail_ni)


async def _execute_financial_modeling(
    agent: Agent[Any, Any],  # noqa: ARG001 — kept for executor signature; unused
    deps: FinRobotDeps,
    prompt: str,  # noqa: ARG001 — kept for executor signature; unused
    structured_context: dict[str, object],
    ticker: str,
    **_kwargs: object,
) -> StepOutput:
    """Deterministic DCF: seed inputs from real filings, compute, sensitivity.

    DCFInputs is constructed exclusively via ``seed_dcf_inputs`` (CLAUDE.md
    architecture red-line #5). The LLM does not pick any numbers here — its
    role is reduced to narrating the seeded result downstream (the thesis +
    report steps). Every field traces to either the ticker's 3y historical
    median or a Damodaran industry median, with provenance recorded in
    DCFInputs.assumption_provenance for the UI's "展开专家详情" panel.

    Previously this step ran a ``param_agent`` (LLM) that produced DCFInputs
    from the prompt — that path is gone. Resurrecting it would walk back the
    P0 reconfiguration audited by ``tests/audit/test_dcf_red_lines.py``.
    """
    financial_data = structured_context.get("data_collection")
    if not isinstance(financial_data, FinancialData):
        raise ValueError(
            "financial_modeling requires FinancialData from the data_collection "
            "step but received: " + type(financial_data).__name__
        )

    # Prefer historical_metrics already built by execute_financial_data_step;
    # fall back to a fresh yfinance fetch when the pipeline ran in a mode that
    # skipped multi-year extraction.
    historical = structured_context.get("historical_metrics")
    if not isinstance(historical, HistoricalMetrics):
        try:
            historical = await fetch_historical_metrics(deps.data_layer, ticker)
        except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as exc:
            logger.warning(
                "Historical extraction failed for %s: %s — falling back to "
                "Damodaran industry medians via seed_dcf_inputs.",
                ticker,
                exc,
            )
            historical = HistoricalMetrics(
                years=[],
                revenue=[],
                revenue_growth_yoy=[],
                cogs=[],
                gross_profit=[],
                gross_margin=[],
                sga=[],
                sga_ratio=[],
                ebitda=[],
                ebitda_margin=[],
                operating_income=[],
                operating_margin=[],
                net_income=[],
                eps=[],
                pe_ratio=[],
                cagr_revenue=None,
                ticker=ticker,
            )
    # Persist so build_valuation_synthesis (below) sees it even when this step
    # fetched it as a fallback — it reads structured_context["historical_metrics"]
    # to detect a post-acquisition share-count break (M&A-transition gate).
    structured_context["historical_metrics"] = historical

    # Bank → compute DDM, the bank's LEAD valuation method. ``is_bank`` itself
    # documents "use DDM, not FCF-DCF": DCF / EV / P-FCF are category errors for a
    # deposit-funded balance sheet, and aggregate_valuation already suppresses those
    # rows for a financial-sector issuer — so without DDM a bank leads on peer P/B + P/E
    # alone, which UNDERPRICES a quality leader (peer-median multiples grant no quality
    # premium; same root cause as the KO comps-underprice re-anchor). Reuse the
    # standalone DDM pipeline's deterministic seed + calc executors VERBATIM. They
    # FX-normalize off the snapshot's ORIGINAL reporting/quote currency (a foreign bank's
    # native-ccy DPS must never mix with a USD quote — BUG-073), so run them HERE, BEFORE
    # this step normalizes data_collection to USD, feeding the un-normalized snapshot via
    # the ``historical_data`` key they read (nothing else in this pipeline reads it). The
    # DDMResult lands in structured_context["ddm_calc"], which build_valuation_synthesis
    # (below) picks up as the intrinsic bank anchor. Gated to banks: a non-bank never
    # populates ddm_calc, so its football field is byte-identical (zero regression). DDM
    # augments the report — a degenerate/failed DDM must never crash it (the bank then
    # leads on P/B + P/E, the remaining bank methods).
    if is_bank(industry=financial_data.market.industry, sector=financial_data.market.sector):
        structured_context["historical_data"] = financial_data
        try:
            ddm_seed_out = await _execute_ddm_seed(agent, deps, prompt, structured_context, ticker)
            structured_context["ddm_params"] = ddm_seed_out.structured
            ddm_calc_out = await _execute_ddm_calc(agent, deps, prompt, structured_context, ticker)
            structured_context["ddm_calc"] = ddm_calc_out.structured
            # Residual income (justified P/B) from the SAME seed inputs — the bank's
            # ROE-coherent, buyback-invariant intrinsic anchor that supersedes the
            # dividend-only DDM as the headline (see _confidence_dial). Own try so a
            # degenerate RI (ROE far below CoE / negative book) just drops without
            # disturbing the DDM the football field still shows.
            ddm_inputs = ddm_seed_out.structured
            if isinstance(ddm_inputs, DDMInputs):
                # Forward (recovery) ROE = trailing ROE × consensus NI growth — the FY1
                # analyst MEAN (FMP netIncomeAvg). A unitless NI-growth RATIO: both ends
                # are USD (trailing = the canonical-USD snapshot; the consensus NI is kept
                # only past _forward_roe's FX-mismatch guard), so no currency or book-
                # caliber drift. The [trailing, forward] RI band then brackets a cyclical
                # bank's trough→normalized uncertainty; the synthesis rates price-vs-band,
                # never extrapolating a single trough/peak ROE to a point.
                forward_roe = _forward_roe(
                    ddm_inputs, financial_data, structured_context.get("forward_financials")
                )
                try:
                    structured_context["ri_calc"] = calculate_residual_income(
                        ddm_inputs, forward_roe=forward_roe
                    )
                except ValueError as ri_err:
                    logger.info("Residual income not applicable for %s: %s", ticker, ri_err)
        except (
            ProviderError,
            ValidationError,
            ValueError,
            ArithmeticError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
        ) as e:
            logger.warning(
                "DDM not applicable for bank %s: %s — bank valuation leads on P/B + P/E",
                ticker,
                e,
            )

    # FX-normalize a foreign issuer's financials to canonical USD before seeding
    # so a TWD numerator (revenue/net_income/debt) never mixes with the USD
    # market_cap — the cross-currency garbage that prints a TWD-per-share implied
    # price as USD and corrupts the WACC debt-weight (BUG-073). No-op for US issuers.
    _orig_quote_currency = financial_data.quote_currency
    financial_data = await normalize_financials_to_usd(
        financial_data, fmp_api_key=getattr(deps.settings, "fmp_api_key", None)
    )
    # The quote→USD spot factor used above, so technical_analysis can scale the
    # raw native-currency price history (which it re-fetches straight from the
    # data layer via load_price_history) into the SAME USD as current_price /
    # dcf_target. Without it the sniper would build support/resistance off TWD
    # closes while comparing them to a USD current_price — the second leg of the
    # same BUG-073 caliber drift the snapshot normalization above doesn't reach.
    # 1.0 for a USD quote (US issuers, foreign ADRs) → no-op. Cache-hot: the rate
    # was just fetched inside normalize_financials_to_usd (15-min FX TTL).
    structured_context["price_fx_to_usd"] = (
        1.0
        if _orig_quote_currency.upper() == "USD"
        else await fetch_fx_rate_to_usd(
            _orig_quote_currency, fmp_api_key=getattr(deps.settings, "fmp_api_key", None)
        )
    )
    # Write the USD-normalized copy BACK into structured_context so EVERY later
    # step reads single-currency USD — not the un-normalized native-currency
    # snapshot the data step stored once (BUG-073 caliber drift). Without this,
    # technical_analysis re-read data_collection and compared a TWD current_price
    # (~NT$1000) against this step's USD dcf.implied_price (~US$31): a fabricated
    # SHORT, nonsensical sniper levels, and current_price in the far tail of the
    # USD-seeded Monte Carlo. valuation_synthesis (current_net_debt / forward_eps)
    # and current_ev_ebitda (market_cap vs USD net_debt) mixed the same way. This
    # is the single chokepoint that makes the whole downstream pipeline — and the
    # artifact builder that dumps data_collection — currency-consistent, honoring
    # the multiples.py "single-currency at the data chokepoint" contract.
    # For a foreign issuer the artifact now reports price/market_cap in USD with
    # quote_currency=USD (was the native quote): the report becomes internally
    # USD-consistent rather than mixing a USD DCF target with a native-ccy quote.
    structured_context["data_collection"] = financial_data

    # Balance-sheet financial (bank / risk-carrying insurer) → withhold the ENTIRE
    # FCFF-DCF at the SOURCE, not just its football-field row. Free cash flow, EBITDA
    # and the net-debt bridge are all category errors when deposits / float / reserves
    # ARE the operating raw material, not capital structure (is_balance_sheet_financial
    # is the single authority; is_bank documents "use DDM, not FCF-DCF"). The synthesis
    # already suppressed the DCF/EV/P-FCF METHOD rows, but a computed DCFResult still
    # leaked its projection into the financial chapter (10y EBITDA trajectory, terminal
    # value, EV, equity, implied price), seeded the technical chapter's Monte Carlo (the
    # DCF distribution) and drew an EV/EBITDA historical band — every one the same
    # category error (JPM: net_debt −$630B treated as net cash → $805 vs a ~$334 price).
    # Skipping seed/calculate here means _execute_technical_analysis finds no DCFResult
    # and degrades its overlays too. The bank still leads on DDM / residual income
    # (computed above for is_bank) + P/B + P/E; build that football field now. No
    # EV/EBITDA band is fetched (enterprise value is the same category error). Mirrors
    # the standalone _execute_dcf_calc gate (dcf.py) and aggregate_valuation's
    # financial_sector row suppression — this is the report-path sibling that was still
    # computing the trajectory.
    if is_balance_sheet_financial(
        industry=financial_data.market.industry, sector=financial_data.market.sector
    ):
        logger.info(
            "FCFF-DCF withheld for %s: balance-sheet financial issuer (category error) — "
            "valued on P/B · P/E · residual income · DDM",
            ticker,
        )
        current_price = (
            financial_data.market.current_price if hasattr(financial_data, "market") else 0
        )
        if current_price > 0:
            from finrobot.engine.pipelines._helpers import build_valuation_synthesis

            vs = build_valuation_synthesis(
                structured_context,
                current_price,
                ticker=ticker,
                # No EV/EBITDA band — enterprise value is a category error for a
                # balance-sheet financial; aggregate_valuation suppresses the row anyway.
                historical_ev_ebitda_band=None,
                historical_ev_ebitda_sample_n=None,
            )
            if vs is not None:
                structured_context["valuation_synthesis"] = vs
        return StepOutput(
            text=(
                f"FCFF-DCF withheld: {ticker} is a balance-sheet financial (bank / insurer). "
                f"Free cash flow, EBITDA and the net-debt bridge are ill-defined when deposits / "
                f"float / reserves are operating raw material, not capital structure — the entire "
                f"cash-flow projection (EBITDA / FCF trajectory, terminal value, enterprise value, "
                f"implied price), its Monte-Carlo distribution and the EV/EBITDA band are category "
                f"errors here. This name is valued on P/B · P/E · residual income · DDM instead."
            ),
            structured=None,
            warnings=[
                f"financial_modeling withheld: FCFF-DCF is a category error for balance-sheet "
                f"financial {ticker} — no EBITDA/FCF trajectory, terminal value, EV, implied "
                f"price, Monte-Carlo or EV/EBITDA band produced; valued on P/B · P/E · RI · DDM "
                f"— method withheld"
            ],
        )

    # Stage-1 growth seed: prefer analyst consensus (the multi-year forward path
    # the data step already fetched) over a backward-looking trailing CAGR, so
    # the DCF stops contradicting the pipeline's own forward projection — the
    # AAPL 3.3%-trailing vs +14.9%-consensus gap that printed a $138 fair value.
    # Best-effort: any miss → [] → seed_dcf_inputs falls back to trailing CAGR.
    forward_raw = structured_context.get("forward_estimates_raw")
    forward_growth = (
        get_forward_revenue_growth(forward_raw) if isinstance(forward_raw, dict) else []
    )
    # Commodity-cyclical (memory/storage/steel/oil…) → through-cycle earnings
    # normalization in the seed so the DCF anchors on normalized through-cycle
    # earnings power, not whatever phase the cycle is in now. Ticker anchor covers
    # memory under the generic "Semiconductors" tag; industry covers the rest.
    cyclical = is_commodity_cyclical(
        industry=financial_data.market.industry,
        sector=financial_data.market.sector,
        ticker=ticker,
    )
    dcf_inputs = seed_dcf_inputs(
        financial_data, historical, forward_growth=forward_growth, cyclical=cyclical
    )
    try:
        dcf_result = calculate_dcf(dcf_inputs)
    except (ValueError, ArithmeticError) as e:
        # The DCF is not applicable when the Gordon terminal value is undefined
        # (terminal growth >= WACC — very low-WACC profiles: low-beta, high-leverage
        # utilities / REITs) OR when the terminal-year FCF is non-positive, which
        # would capitalize a trough cash flow into a perpetual negative value and a
        # negative implied price per share (BUG-074). Degrade gracefully — skip the
        # DCF chapter instead of crashing the whole report (and instead of printing a
        # nonsense negative fair value), and still build the valuation synthesis from
        # the remaining (relative) methods so the football field renders.
        logger.warning("DCF chapter not applicable for %s: %s", ticker, e)
        current_price = (
            financial_data.market.current_price if hasattr(financial_data, "market") else 0
        )
        if current_price > 0:
            from finrobot.engine.pipelines._helpers import build_valuation_synthesis

            ev_band = await fetch_reverse_multiple_band(ticker, "ev_ebitda", deps.data_layer)
            vs = build_valuation_synthesis(
                structured_context,
                current_price,
                ticker=ticker,
                historical_ev_ebitda_band=(ev_band.p25, ev_band.p75) if ev_band else None,
                historical_ev_ebitda_sample_n=ev_band.sample_count if ev_band else None,
            )
            if vs is not None:
                structured_context["valuation_synthesis"] = vs
        return StepOutput(
            text=(
                f"DCF not applicable: given this issuer's cost of capital, terminal growth "
                f"rate, and final-year free-cash-flow assumptions, the Gordon perpetual-"
                f"growth model cannot produce a meaningful positive valuation ({e}). This "
                f"chapter skips the DCF valuation; the valuation conclusion relies on "
                f"relative valuation (peer multiples, historical valuation range)."
            ),
            structured=None,
            # The artifact-visible reason. Without it the degrade lived only in
            # server logs: the UI showed "DCF FAIR VALUE —" plus the downstream
            # technical_analysis marker, and the user could never see WHY the
            # DCF was missing (MU run_5dd152487973, 2026-06-10).
            warnings=[f"financial_modeling skipped: DCF not applicable — {e}"],
        )
    wacc_range, tg_range = build_sensitivity_ranges(
        dcf_result.wacc, dcf_result.inputs.terminal_growth_rate
    )
    sensitivity = calculate_sensitivity(dcf_inputs, wacc_range=wacc_range, tg_range=tg_range)

    # Reverse-DCF reality check: what growth / WACC does the market price imply,
    # over the SAME horizon the forward DCF used? This is the honest companion to
    # the fair-value point — a DCF mid far from market is meaningless alone, but
    # "the market prices in X% growth (or: even 50% growth can't reach today's
    # price — option-value stock)" is checkable and user-understandable. Computed
    # deterministically; the thesis LLM cites it, never invents it.
    current_price = financial_data.market.current_price if hasattr(financial_data, "market") else 0
    market_implied = (
        market_implied_check(dcf_inputs, current_price, horizon_years=dcf_result.projection_years)
        if current_price > 0
        else None
    )
    # ±2pp EBITDA-margin swing (the load-bearing terminal-margin sensitivity the
    # WACC×TG grid never shows) and the latest-year driver actuals (the "current"
    # column of the report's model-vs-current assumptions reconciliation). Both
    # deterministic, both degrade to None per-end / per-driver — never crash.
    current_actuals, capex_is_ttm = dcf_current_actuals(financial_data, historical)
    dcf_result = dcf_result.model_copy(
        update={
            "sensitivity_table": sensitivity,
            "market_implied": market_implied,
            "margin_swing": margin_swing(dcf_inputs),
            "assumption_current_actuals": current_actuals,
            "assumption_current_actuals_fy": (historical.years[-1] if historical.years else None),
            "assumption_current_actuals_capex_ttm": capex_is_ttm,
        }
    )

    valid_prices = [
        p for row in sensitivity["implied_prices"] for p in row if p is not None and p > 0
    ]
    price_range = f"${min(valid_prices):.0f}-${max(valid_prices):.0f}" if valid_prices else "N/A"
    if market_implied is not None and market_implied.growth_unreachable:
        implied_str = (
            f"Market-implied growth: UNREACHABLE — even "
            f"{market_implied.growth_ceiling:.0%}/yr growth implies only "
            f"${market_implied.ceiling_price:.2f} vs ${current_price:.2f} market "
            f"(price is option value the DCF cannot model)."
        )
    elif market_implied is not None and market_implied.implied_growth is not None:
        implied_str = (
            f"Market-implied growth: {market_implied.implied_growth:.1%}/yr over "
            f"{market_implied.horizon_years}y (vs seeded "
            f"{dcf_inputs.revenue_growth_rates[0]:.1%})."
        )
    else:
        implied_str = ""
    narrative = (
        f"DCF base case implies ${dcf_result.implied_price:.2f} per share. "
        f"WACC: {dcf_result.wacc:.1%}, Terminal growth: {dcf_inputs.terminal_growth_rate:.1%}. "
        f"Enterprise value: ${dcf_result.enterprise_value / 1e9:.1f}B. "
        f"Sensitivity range: {price_range}. {implied_str}".rstrip()
    )

    # Write DCFResult into structured_context BEFORE build_valuation_synthesis:
    # aggregate_valuation reads it from here, so it must land before the synthesis
    # runs. Writing later (e.g. via _store_output after the executor returns)
    # leaves isinstance(dcf, DCFResult) False and silently drops DCF.
    structured_context["financial_modeling"] = dcf_result

    # Scenario SOTP (Batch 3B v1) — the option-value CHANNEL for names a DCF point
    # target can't honestly capture. Gated DETERMINISTICALLY on
    # ``classify_market_implied_nature().kind == "option_value"`` (the same
    # reverse-DCF classifier the Coverage desk uses — no growth in the bracket
    # reaches the price AND that survives the most favourable WACC). For such a
    # name we publish a SOURCEABLE decomposition instead of a fabricated target:
    # a deterministic cash-flow floor (SEC-filed segments × conservative multiples)
    # and the pure-subtraction market-implied option value above it. This is an
    # INDEPENDENT channel — it lands in structured_context["sotp_breakdown"], NOT
    # in the confidence-weighted point synthesis, so it never trips the
    # method-corroboration span gate (METHOD_CORROBORATION_SPAN_K) against the
    # DCF floor. The synthesis withholds its POINT target (valuation_withheld)
    # while the directional verdict still ships.
    if current_price > 0:
        nature = classify_market_implied_nature(
            dcf_inputs, current_price, horizon_years=dcf_result.projection_years
        )
        if nature.kind == "option_value":
            try:
                sotp = await build_sotp_breakdown(
                    deps.data_layer,
                    ticker,
                    net_debt=dcf_inputs.net_debt,
                    shares_outstanding=dcf_inputs.shares_outstanding,
                    current_price=current_price,
                )
            except (
                ProviderError,
                ValidationError,
                ValueError,
                KeyError,
                TypeError,
                AttributeError,
                RuntimeError,
                OSError,
            ) as e:
                # SOTP is augmentation; never crash the seed. Concrete types only
                # (red line D1) — CancelledError must propagate.
                logger.warning("SOTP breakdown failed for %s: %s", ticker, e)
                sotp = None
            if sotp is not None:
                structured_context["sotp_breakdown"] = sotp
        else:
            # Light non-SOTP segment overview (BACKLOG A4, 2026-07-09): for every
            # OTHER ticker (the SOTP gate above did NOT fire — no reverse-decomp
            # valuation channel for it), fetch the SAME SEC XBRL reportable
            # segments SOTP uses (falling back to FMP's product mix when XBRL has
            # nothing) and hand a display-only breakdown to the Company Overview
            # chapter + the thesis prompt's numeric whitelist. This is the fetch
            # that replaces the stale "SEC XBRL does not currently expose segment
            # data" prompt instruction — that assertion (2026-05-28) was disproven
            # by SOTP's own segment fetch (2026-07-06); this wires the SAME data
            # into the path that was still telling the LLM it doesn't exist.
            try:
                segment_overview = await build_segment_overview(deps.data_layer, ticker)
            except (
                ProviderError,
                ValidationError,
                ValueError,
                KeyError,
                TypeError,
                AttributeError,
                RuntimeError,
                OSError,
            ) as e:
                # Augmentation; never crash the seed. Concrete types only (red
                # line D1) — CancelledError must propagate.
                logger.warning("Segment overview failed for %s: %s", ticker, e)
                segment_overview = None
            if segment_overview is not None:
                structured_context["segment_overview"] = segment_overview

    # Build ValuationSynthesis from all available methods for the football field
    # chart. current_price was resolved above for the reverse-DCF check.
    if current_price > 0:
        from finrobot.engine.pipelines._helpers import build_valuation_synthesis

        # Self historical EV/EBITDA band → revives the EV/EBITDA reverse-multiple
        # row (band P25/P75 × forward consensus EBITDA − current net debt). Without
        # this the row was structurally dead in the report — both callers passed
        # band=None, so the football field lost a whole real method and the
        # synthesis ran on fewer corroborating methods (lower confidence). Every
        # input is a reported figure; net debt stays None≠0-gated downstream.
        ev_band = await fetch_reverse_multiple_band(ticker, "ev_ebitda", deps.data_layer)
        vs = build_valuation_synthesis(
            structured_context,
            current_price,
            ticker=ticker,
            historical_ev_ebitda_band=(ev_band.p25, ev_band.p75) if ev_band else None,
            historical_ev_ebitda_sample_n=ev_band.sample_count if ev_band else None,
        )
        if vs is not None:
            structured_context["valuation_synthesis"] = vs

    return StepOutput(text=narrative, structured=dcf_result)


async def _execute_technical_analysis(
    agent: Agent[Any, Any],  # noqa: ARG001 — kept for executor signature; unused
    deps: FinRobotDeps,
    prompt: str,  # noqa: ARG001 — kept for executor signature; unused
    structured_context: dict[str, object],
    ticker: str,
    **_kwargs: object,
) -> StepOutput:
    """Run Monte Carlo + Sniper + Historical Bands → chapter 09 payload.

    Deterministic: every number traces back to seeded DCF inputs and the
    data layer's price/financials cache. The LLM contributes nothing here —
    it would only narrate downstream if the thesis step chose to.
    """
    dcf = structured_context.get("financial_modeling")
    financial_data = structured_context.get("data_collection")
    if not isinstance(dcf, DCFResult):
        # financial_modeling produced no DCFResult. Two disjoint reasons, one
        # degraded outcome: (a) a balance-sheet financial (bank / insurer) whose
        # FCFF-DCF is withheld at the source as a category error, or (b) a
        # non-financial whose Gordon terminal value is undefined (terminal_growth ≥
        # WACC — low-WACC utilities / REITs). Either way the quant overlays (Monte
        # Carlo / Sniper / Bands) all seed off DCF inputs, so chapter 09 has nothing
        # to compute — an expected degrade, NOT a run-ending error. Emit a degraded
        # payload with all branches None and the marker the validator recognizes.
        # For a financial the Monte Carlo (a DCF distribution) and the EV/EBITDA band
        # are themselves the category error, so say so — never frame it as a re-run.
        is_financial = isinstance(financial_data, FinancialData) and is_balance_sheet_financial(
            industry=financial_data.market.industry, sector=financial_data.market.sector
        )
        if is_financial:
            text = (
                "Technical / quant overlays (Monte Carlo, sniper entries, historical "
                "valuation bands) not applicable: this is a balance-sheet financial "
                "(bank / insurer). The Monte Carlo is a DCF distribution and the EV/EBITDA "
                "band an enterprise-value multiple — both category errors when free cash "
                "flow and enterprise value are ill-defined for a deposit / float funded "
                "balance sheet. The valuation relies on P/B · P/E · residual income · DDM."
            )
            reason_warnings = [
                TECHNICAL_DCF_UNAVAILABLE_MARKER,
                "technical_analysis withheld: Monte Carlo and the EV/EBITDA band are "
                "DCF / enterprise-value derived — category errors for a balance-sheet "
                "financial; no cash-flow overlays produced — method withheld",
            ]
        else:
            text = (
                "Technical / quant overlays (Monte Carlo, sniper entries, historical "
                "valuation bands) skipped: every metric in this chapter is seeded from "
                "DCF inputs, and the DCF valuation is not applicable to this issuer "
                "(the cost-of-capital and terminal-growth assumptions leave the Gordon "
                "perpetual-growth model undefined). The valuation conclusion relies on "
                "relative valuation."
            )
            reason_warnings = [TECHNICAL_DCF_UNAVAILABLE_MARKER]
        return StepOutput(
            text=text,
            structured=TechnicalAnalysis(
                monte_carlo=None,
                sniper=None,
                historical_bands=None,
                warnings=reason_warnings,
            ),
        )
    if not isinstance(financial_data, FinancialData):
        raise ValueError(
            "technical_analysis requires FinancialData from data_collection step "
            "but received: " + type(financial_data).__name__
        )

    current_price = (
        financial_data.market.current_price if hasattr(financial_data, "market") else 0.0
    )

    # B1: when the valuation synthesis honestly withheld its POINT target (the
    # only number available would be fabricated — methods agree far off-market /
    # a lone method way off-market), the sniper has no publishable target to
    # anchor a directional trade on, so it drops to levels-only. When a target
    # publishes (even low confidence), the sniper anchors it. Keyed on the
    # explicit valuation_withheld flag (the deleted REVIEW sentinel's successor).
    vs = structured_context.get("valuation_synthesis")
    has_anchor_target = not (isinstance(vs, ValuationSynthesis) and vs.valuation_withheld)

    # B2: hand the band the canonical TTM EV/EBITDA so the "current" multiple
    # matches the comps chapter exactly — (market_cap + net_debt) / TTM_EBITDA,
    # the same formula the comps target uses. None when any leg is missing/≤0
    # (band then falls back to trailing-annual EBITDA).
    current_ev_ebitda_value = current_ev_ebitda(financial_data, dcf.inputs.net_debt)

    # quote→USD factor stamped at the FX chokepoint in financial_modeling, so the
    # raw native-currency price history build_technical_analysis re-fetches scales
    # into the SAME USD as current_price / dcf_target (BUG-073 second leg). 1.0 for
    # USD-quoted issuers; defaults to 1.0 when financial_modeling degraded before
    # stamping it (then the only price source is already-USD anyway).
    price_fx = structured_context.get("price_fx_to_usd")
    price_fx_to_usd = float(price_fx) if isinstance(price_fx, (int, float)) else 1.0

    # Unify the report's two EV/EBITDA bands on ONE trailing window: the technical
    # chapter used to default to 3y while the valuation-method band
    # (fetch_reverse_multiple_band, labelled "self_5y_…") ran 5y, so the same report
    # showed two windows whose cheap/fair/expensive verdicts could disagree (GOOGL:
    # 3y P25/med/P75 16.9/19.0/23.1 vs 5y method mid 17.6). Both now read
    # REPORT_BAND_WINDOW_YEARS.
    payload = await build_technical_analysis(
        ticker=ticker,
        dcf_inputs=dcf.inputs,
        dcf_target=dcf.implied_price,
        current_price=current_price,
        data_layer=deps.data_layer,
        band_years=REPORT_BAND_WINDOW_YEARS,
        has_anchor_target=has_anchor_target,
        current_ev_ebitda=current_ev_ebitda_value,
        price_fx_to_usd=price_fx_to_usd,
    )

    summary_parts: list[str] = []
    if payload.monte_carlo is not None:
        mc = payload.monte_carlo
        summary_parts.append(
            f"Monte Carlo ({mc.n_valid:,} sims): mean ${mc.mean:.2f}, "
            f"P5–P95 ${mc.percentiles['5']:.2f}–${mc.percentiles['95']:.2f}, "
            f"current at {mc.current_price_percentile:.0f}th pct."
        )
    if payload.sniper is not None:
        sn = payload.sniper
        # Label entry / target side per trade direction. SHORT trades cover
        # below entry; rendering them as "buy / target" reads as a long.
        # NEUTRAL (B1): point target withheld → no anchor for a directional
        # trade, only levels.
        if sn.direction == "NEUTRAL":
            summary_parts.append(
                f"Sniper levels-only (directional trade withheld — no publishable "
                f"price target to anchor): support ${sn.support_level:.2f}, "
                f"resistance ${sn.resistance_level:.2f}."
            )
        elif (
            sn.direction == "SHORT"
            and sn.ideal_buy is not None
            and sn.stop_loss is not None
            and sn.take_profit is not None
            and sn.risk_reward_ratio is not None
        ):
            summary_parts.append(
                f"Sniper SHORT levels: short ${sn.ideal_buy:.2f}, "
                f"stop ${sn.stop_loss:.2f}, cover ${sn.take_profit:.2f} "
                f"(R/R {sn.risk_reward_ratio:.1f})."
            )
        elif (
            sn.ideal_buy is not None
            and sn.stop_loss is not None
            and sn.take_profit is not None
            and sn.risk_reward_ratio is not None
        ):
            summary_parts.append(
                f"Sniper levels: buy ${sn.ideal_buy:.2f}, "
                f"stop ${sn.stop_loss:.2f}, target ${sn.take_profit:.2f} "
                f"(R/R {sn.risk_reward_ratio:.1f})."
            )
    if payload.historical_bands is not None:
        hb = payload.historical_bands
        cur = f"{hb.current:.1f}x" if hb.current is not None else "n/a"
        med = f"{hb.median:.1f}x" if hb.median is not None else "n/a"
        summary_parts.append(
            f"EV/EBITDA band ({hb.sample_count} pts): current {cur} vs median {med} "
            f"→ {hb.classification}."
        )
    if not summary_parts:
        summary_parts.append("Technical analysis skipped — all branches unavailable.")

    return StepOutput(text=" ".join(summary_parts), structured=payload)


# Matches a $-prefixed dollar figure: $276, $276.43, $1,234.50, $2172.06, $280.
# Group 1 is the numeric body (with optional thousands separators / decimals).
# Group 2 is an optional magnitude suffix ($3.41T, $391.0B, $3.4 billion).
#
# The separated alternative requires AT LEAST ONE comma group (``+``, not ``*``):
# with ``*`` it also matched a bare 4+ digit number's FIRST THREE digits and
# stopped (``$2172.06`` → ``$217``, since regex alternation is ordered and the
# first branch's partial match wins), so the reconciler below saw 217 ≠ 2172.06 =
# drift and rewrote ``$217`` → ``$2172.06``, leaving the orphan tail → the
# ``$2172.062.06`` garbage shipped in the MU 2026-06-07 basis. With ``+`` the
# separated branch only matches comma-grouped numbers and bare runs of digits
# (any length) fall through to the second branch and match in full.
#
# The suffix MUST be consumed by the match: without it, "$3.41T" (a peer
# market cap the thesis prompt itself injects via fmt_market_cap) matched as
# "$3.41", failed the whitelist, and was rewritten to the canonical target —
# producing "$276.43T". A magnitude-suffixed amount is categorically not a
# per-share target, so the reconciler skips it entirely; fabricated big
# amounts are the report-level drift scanner's job (operators/report_drift),
# which parses the same suffixes and compares against all numeric leaves.
# The optional leading-minus group ([-−]\s?, ASCII or U+2212) exists to be
# SKIPPED, mirroring the suffix rule above: "-$1.20" (loss-quarter EPS, negative
# FCF/share) is categorically not a restatement of the positive canonical price
# target, and rewriting just the "$1.20" span used to print the sign-corrupted
# "-$276.43". ("$-1.20" never matched — the digit class rejects the inner minus.
# Sign-aware validation of negative amounts against ALL leaves is the report-
# level drift scanner's job; this reconciler only guards the target.)
_DOLLAR_RE = re.compile(
    r"([-−]\s?)?"
    r"\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(\s?(?:[KMBT]\b|million\b|billion\b|trillion\b|bn\b|mn\b|tn\b))?",
    re.IGNORECASE,
)

# A prose $-amount may legitimately differ from the canonical weighted target
# when it is quoting a *per-method* mid (e.g. "DCF says $5.88, comps say $19.54").
# Anything outside this band that is NOT a whitelisted per-method mid is drift.
# The relative tolerance ``NARRATIVE_DRIFT_TOLERANCE`` is the shared leaf constant
# (engine/models/reconcile_tolerances) so the output contract's C3 (basis
# conclusion == headline) and this reconcile speak the same "same number" rule.


def _reconcile_narrative_targets(
    thesis: ThesisResult,
    canonical_target: float | None,
    allowed_mids: list[float],
    current_price: float | None = None,
) -> tuple[ThesisResult, bool]:
    """Code-only guard: neutralize prose $-amounts that contradict the canonical target.

    Two modes:
      · ``canonical_target`` is a number (point published) → rewrite any drifting
        prose $-amount to the canonical "$Y" in place.
      · ``canonical_target`` is None (POINT withheld) → there is no headline value
        to rewrite TO, so a smuggled point target must be ERASED: any prose
        $-amount that is not a whitelisted per-method mid or the market price is
        replaced with a ``[target withheld]`` marker. This stops the LLM from
        printing "fair value ≈ $X" in prose when the structured target is null.

    After the deterministic override forces ``price_target`` to the canonical
    weighted value, the headline-bearing free-text fields from the *same* LLM
    call (``valuation_overview`` / ``tagline`` / ``key_takeaways``) can still
    print a contradicting $ amount — e.g. the table says $276.43 while the prose
    says "约 $280". This scans those fields for $-amounts that deviate
    > ``NARRATIVE_DRIFT_TOLERANCE`` from the canonical target AND do not match
    any whitelisted per-method mid, then rewrites the offending "$X" token to the
    canonical "$Y" in place (least-invasive neutralization — the sentence
    structure is preserved). No second LLM call is made.

    ``current_price`` is a legitimately-citable reference (the narrative now
    states the real market price; whitelisting it stops this guard from
    rewriting "市场价 $425" → the target "$306.59" — which would re-create the
    very mislabel the market-price injection fixes).

    Returns the (possibly model_copied) thesis and whether any drift was found.
    """
    # Point published → rewrite drift to the canonical "$Y". Point withheld
    # (canonical_target is None) → there is nothing to rewrite TO, so erase the
    # smuggled amount to an explicit withheld marker.
    canonical_token = (
        "[target withheld]" if canonical_target is None else f"${canonical_target:.2f}"
    )

    def _is_allowed(value: float) -> bool:
        if (
            canonical_target is not None
            and abs(value - canonical_target) <= abs(canonical_target) * NARRATIVE_DRIFT_TOLERANCE
        ):
            return True
        # The current market price is a legitimate reference number, not drift.
        if (
            current_price is not None
            and current_price > 0
            and abs(value - current_price) <= abs(current_price) * NARRATIVE_DRIFT_TOLERANCE
        ):
            return True
        # A per-method mid is legitimately citable even if far from the target
        # ("DCF $5.88 vs comps $19.54, they disagree" is the honest narrative).
        return any(abs(value - mid) <= abs(mid) * NARRATIVE_DRIFT_TOLERANCE for mid in allowed_mids)

    drift_found = False

    def _scan_text(text: str) -> str:
        nonlocal drift_found

        def _sub(match: re.Match[str]) -> str:
            nonlocal drift_found
            # Minus-prefixed amounts (-$1.20 loss-quarter EPS) are never the
            # positive canonical target; rewriting the "$1.20" span alone would
            # ship the sign-corrupted "-$276.43". Skip, like suffixed amounts.
            if match.group(1):
                return match.group(0)
            # Magnitude-suffixed amounts ($3.41T market cap, $391.0B EV) are
            # never per-share targets — out of scope for target reconciliation.
            if match.group(3):
                return match.group(0)
            try:
                value = float(match.group(2).replace(",", ""))
            except ValueError:
                return match.group(0)
            if _is_allowed(value):
                return match.group(0)
            drift_found = True
            logger.warning(
                "narrative target drift: prose %s vs canonical %s — neutralizing",
                match.group(0),
                canonical_token,
            )
            return canonical_token

        return _DOLLAR_RE.sub(_sub, text)

    updates: dict[str, Any] = {}

    # Every free-text narrative slot that can carry a $-amount is scanned — not
    # just the headline three. company_overview / competitor_analysis /
    # news_summary / narrative are exactly the fields where an injected fake
    # number (BUG-087) used to survive into the artifact pushed to analysts.
    # price_target_basis is included so the *basis* line can't contradict the
    # forced canonical target either.
    _STRING_NARRATIVE_FIELDS = (
        "narrative",
        "price_target_basis",
        "tagline",
        "company_overview",
        "valuation_overview",
        "competitor_analysis",
        "news_summary",
        "momentum_divergence_note",
    )
    for field_name in _STRING_NARRATIVE_FIELDS:
        original = getattr(thesis, field_name)
        if not isinstance(original, str):
            continue
        scanned = _scan_text(original)
        if scanned != original:
            updates[field_name] = scanned

    if thesis.key_takeaways is not None:
        scanned_list = [_scan_text(item) for item in thesis.key_takeaways]
        if scanned_list != thesis.key_takeaways:
            updates["key_takeaways"] = scanned_list

    if updates:
        thesis = thesis.model_copy(update=updates)

    return thesis, drift_found


def apply_canonical_override(
    thesis: ThesisResult, canonical: CanonicalThesis, vs: object
) -> ThesisResult:
    """Force the LLM's headline fields onto the canonical (deterministic) values.

    The LLM is asked to copy the injected AUTHORITATIVE numbers, but a
    non-cooperative model can drift — so we overwrite ``price_target`` /
    ``recommendation`` / ``price_target_basis`` post-run, log any divergence for
    prompt-fidelity evals, and (on the publish path) neutralize drifting $-amounts
    in the free-text narrative against the canonical target. Pure: no I/O, no LLM.
    ``vs`` is the "valuation_synthesis" structured-context value (per-method mids
    + market price feed the narrative reconciliation).
    """
    canonical_basis = canonical.basis
    canonical_target = canonical.target
    canonical_verdict = canonical.verdict
    # The verdict is ALWAYS directional now (BUY/HOLD/SELL — REVIEW deleted); the
    # POINT target may be honestly withheld (valuation_withheld) while the verdict
    # still ships. Hard-enforce both — same inputs always produce the same numbers;
    # if the LLM drifted, log it for prompt-fidelity evals.
    allowed_mids = [m.mid for m in vs.methods] if isinstance(vs, ValuationSynthesis) else []
    # The published value-band bounds (target_low/high — e.g. a bank's residual-income
    # band [RI@trailing, RI@forward]) are legitimate published numbers the deterministic
    # canonical basis prints, but they are NOT per-method mids. Without whitelisting them
    # the withheld-path scrubber (canonical_target=None) erases them to "[target withheld]"
    # and silently reverts 撤点≠撤区间 — washing the very band the basis is meant to show
    # (JPM "value band [[target withheld], [target withheld]]"). They are published values,
    # so prose citing them is citation, not a smuggled fabricated point.
    if isinstance(vs, ValuationSynthesis):
        allowed_mids += [b for b in (vs.target_low, vs.target_high) if b is not None]
    market_price = vs.current_price if isinstance(vs, ValuationSynthesis) else None

    if canonical_target is not None and canonical_basis is not None:
        # Point published (verdict + a defensible target).
        if thesis.price_target is None or abs(thesis.price_target - canonical_target) > 0.01:
            logger.warning(
                "Thesis LLM price_target drift: llm=%s, canonical=%s — overriding",
                thesis.price_target,
                canonical_target,
            )
        if (
            canonical_verdict is not None
            and thesis.recommendation.strip().upper() != canonical_verdict
        ):
            logger.warning(
                "Thesis LLM recommendation drift: llm=%s, canonical=%s — overriding",
                thesis.recommendation,
                canonical_verdict,
            )
        updates: dict[str, Any] = {
            "price_target": canonical_target,
            "price_target_basis": canonical_basis,
        }
        if canonical_verdict is not None:
            updates["recommendation"] = canonical_verdict
        thesis = thesis.model_copy(update=updates)

        # Free-text fields from the SAME LLM call are accepted verbatim and
        # mirrored into outputs.llm_narrative — so prose can print a $ amount
        # that contradicts the just-overwritten canonical target ("table $276.43,
        # prose ~$280"). Scan the headline-bearing fields and neutralize any
        # drifting $-amount to the canonical value (code only, no second LLM call).
        thesis, _ = _reconcile_narrative_targets(
            thesis, canonical_target, allowed_mids, current_price=market_price
        )
    else:
        # POINT withheld (valuation_withheld) OR no usable synthesis at all. Either
        # way the verdict is still directional and the price_target is forced None
        # so the LLM's own number — a fact field with zero code backing — cannot
        # pass through (summary_extractor treats thesis.price_target as the
        # coverage signal). canonical_verdict is always set on a real synthesis;
        # the empty no-synthesis branch returns verdict="HOLD".
        if thesis.price_target is not None or (
            canonical_verdict is not None
            and thesis.recommendation.strip().upper() != canonical_verdict
        ):
            logger.warning(
                "Thesis LLM drift on withheld-point path (rec=%s, target=%s) — forcing "
                "verdict=%s / withholding target",
                thesis.recommendation,
                thesis.price_target,
                canonical_verdict,
            )
        thesis = thesis.model_copy(
            update={
                "recommendation": canonical_verdict or "HOLD",
                "price_target": None,
                "price_target_basis": canonical_basis
                or (
                    "No deterministic valuation point available — "
                    "target withheld (nothing to cross-validate the model against)."
                ),
            }
        )
        # CRITICAL: the publish path scrubs drifting prose $-amounts against the
        # canonical target; the withheld path must do the SAME so an LLM cannot
        # smuggle a $-amount into prose when the structured target is null. With
        # no canonical target to rewrite TO, _reconcile_narrative_targets (called
        # with canonical_target=None) strips any prose $-amount that is not a
        # whitelisted per-method mid or the market price to a [withheld] marker.
        thesis, _ = _reconcile_narrative_targets(
            thesis, None, allowed_mids, current_price=market_price
        )
    return thesis


_SYNTHESIS_AGENT_INSTRUCTIONS = (
    "Write an investment thesis based on the DCF valuation, peer analysis, "
    "and catalyst analysis. "
    "Reference specific catalysts from the catalyst analysis when discussing "
    "upside drivers and risks. "
    "Provide a recommendation (Buy/Hold/Sell), price target, catalysts, and risks. "
    "When the prompt supplies an AUTHORITATIVE PRICE TARGET, copy it exactly into "
    "the `price_target` field — that number is computed by deterministic code and "
    "is the contract you are narrating, not negotiating."
    "\n\n"
    "NUMERIC GROUNDING (applies to every argument field — `narrative`, "
    "`catalysts`, `risks`, and every other prose field below): every paragraph "
    "or bullet must cite at least one number from the prompt's numeric-"
    "discipline whitelist. Verdict-only rhetoric with no backing figure — "
    "'attractively valued', 'a resilient moat', 'well-positioned for growth' — "
    "with nothing quantifying it is not acceptable analyst prose; state the P/E, "
    "margin, multiple, growth rate, or momentum figure that makes the claim, "
    "and cite it. `catalysts` entries specifically must ALSO be either a real "
    "event from the injected catalyst-analysis data or a whitelisted number — "
    "never an invented forward-looking event (product launch, approval, M&A) "
    "that was not supplied to you."
    "\n\n"
    "ALSO produce the following analyst-grade narrative fields "
    "(investment-bank tone, no retail simplification; write in the language "
    "set by the step prompt's language instruction):\n"
    "  - tagline:           a single sentence ≤ 60 characters that captures the "
    "trade thesis in one line; works as a share-card subtitle.\n"
    "  - key_takeaways:     3-5 bullet points the analyst reader should walk away "
    "with. NOT future events (those are `catalysts`) and NOT downsides (those are "
    "`risks`) — present-tense conclusions about why this is a Buy/Hold/Sell now.\n"
    "  - company_overview:  200-300 word Company Overview (8th synthesis slot). "
    "Cover (a) the core business model and what the firm sells, (b) the reportable "
    "segments — but ONLY cite segment revenue percentages that appear in the injected "
    "segment_overview whitelist entry below; if segment_overview was NOT supplied "
    "(single-segment issuer, or no segment data sourceable from SEC XBRL or FMP for "
    "this ticker), state explicitly that a segment breakdown is unavailable and do "
    "NOT fabricate figures, (c) geographic exposure — same rule: cite only data "
    "present in xbrl_facts_snapshot or state it is unavailable, and (d) the durable "
    "competitive moat. Investment-bank tone — write as if introducing the issuer in "
    "an initiating-coverage report.\n"
    "  - valuation_overview: 150-200 word explanation — why DCF vs Comps vs DDM give the "
    "implied prices they do, and how the weighted target was reached. "
    "Only cite numbers present in the whitelist injected in the prompt.\n"
    "  - competitor_analysis: 3-4 sentences on the market-share / growth / "
    "valuation-multiple differences vs peers. Only cite peer multiples from "
    "peer_analysis fields listed in the whitelist.\n"
    "  - news_summary:      3-5 sentences summarizing the overall sentiment of the "
    "last 30 days of key news and how it supports/challenges the thesis."
)


async def _execute_thesis(
    agent: Agent[Any, Any],
    deps: FinRobotDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
    **_kwargs: object,
) -> StepOutput:
    """synthesis_agent writes thesis with structured output."""
    # CLAUDE.md core contract: "LLM 永远不产出无法追溯到函数调用的数字".
    # The target price MUST trace to ``synthesize_valuations`` (deterministic
    # confidence-weighted average across DCF / Comps / …), and ``recommendation``
    # (Buy/Hold/Sell) MUST classify off ``upside_downside`` with documented
    # thresholds — never the LLM's free choice, which drifts run-to-run.
    # So we (a) inject canonical values into the prompt for a consistent
    # narrative and (b) force-override the fields after the run, so even a
    # non-cooperative LLM can't desync the contract.
    # Both halves are PURE + independently tested: the canonical headline by
    # ``resolve_canonical_thesis`` (test_valuation_synthesis.py), the prompt
    # assembly (catalyst context, market-implied line, gate/target block, numeric
    # whitelist, segment grounding) by ``build_thesis_prompt`` (test_thesis_prompt.py).
    # The async work here is only to run the agent and enforce the canonical fields.
    vs = structured_context.get("valuation_synthesis")
    canonical = resolve_canonical_thesis(vs, ticker)
    thesis_prompt = build_thesis_prompt(prompt, structured_context, canonical)

    # Standing street-context fact line (boss-approved 2026-07-08, widened
    # 2026-07-09 — BACKLOG A9/B1): whenever the sell-side 12-month target
    # distribution is available, say so on the step's warnings (→ artifact
    # warnings → the report's compute-warnings section, routed by the frontend
    # into the cover valuation box). When the canonical target sits ENTIRELY
    # outside the sell-side range, the humility clause rides the SAME marker
    # line. Never a gate: verdict / confidence / numbers stay untouched, and a
    # fetch miss silently drops the line (the explicit augmentation route
    # raises ProviderError → fetch_price_target returns None; a missing street
    # band must not degrade the thesis step).
    street_note: str | None = None
    if canonical.target is not None and canonical.target > 0:
        pt = await deps.data_layer.fetch_price_target(ticker)
        d = pt.data if pt is not None and isinstance(pt.data, dict) else {}
        low, high, cnt = d.get("low"), d.get("high"), d.get("analyst_count")
        consensus = d.get("consensus")
        street_note = street_range_disclosure(
            canonical.target,
            float(low) if isinstance(low, (int, float)) else None,
            float(high) if isinstance(high, (int, float)) else None,
            int(cnt) if isinstance(cnt, (int, float)) else None,
            float(consensus) if isinstance(consensus, (int, float)) else None,
        )

    synthesis_agent = Agent(
        deps.settings.create_model(),
        output_type=ThesisResult,
        instructions=_SYNTHESIS_AGENT_INSTRUCTIONS,
        defer_model_check=True,
    )
    try:
        result = await synthesis_agent.run(thesis_prompt, deps=deps)  # type: ignore[call-overload]
        thesis = result.output
    except AgentRunError:
        # Recoverable by type (rate-limit / transient LLM error). base.py
        # retries these 3× with backoff — re-wrapping into ValueError would
        # mark it non-recoverable and abort the whole run with zero retries.
        raise
    except (ValidationError, ValueError) as e:
        # Structured-output schema failure is deterministically non-recoverable:
        # the same prompt yields the same invalid shape, so retrying is wasted
        # budget. Keep it wrapped as a non-recoverable ValueError.
        raise ValueError(f"LLM failed to produce valid thesis: {e}") from e

    # Hard-enforce the deterministic target + verdict onto the LLM output (pure;
    # logs any drift, neutralizes drifting $-amounts in the narrative). Same
    # inputs always produce the same numbers — see apply_canonical_override.
    thesis = apply_canonical_override(thesis, canonical, vs)

    # Momentum-vs-verdict narrative backstop (BACKLOG A2/P1-1): the prompt above
    # (build_thesis_prompt) MANDATES a momentum_divergence_note whenever the
    # verdict strongly disagrees with the stock's own trailing-1y price action —
    # this is the deterministic check that catches a non-cooperative LLM that
    # skipped it. compute_momentum_context is the SAME function build_thesis_prompt
    # called, so this reads the identical numbers the prompt instructed on. Never
    # gates verdict/target/confidence — a missing hedge paragraph degrades the
    # READ, not the call (core contract②), and routes through the same plain-string
    # StepOutput.warnings channel as the street-range disclosure below (never a new
    # machine code).
    fd_for_momentum = structured_context.get("data_collection")
    momentum_ctx = compute_momentum_context(
        fd_for_momentum if isinstance(fd_for_momentum, FinancialData) else None
    )
    momentum_warning = audit_momentum_narrative_hedge(
        canonical.verdict, momentum_ctx.one_year_return_pct, thesis.momentum_divergence_note
    )

    # Numeric-grounding narrative backstop (BACKLOG A3/P1-2): the prompt's
    # NARRATIVE ARGUMENT RULE (build_thesis_prompt) instructs the LLM that every
    # narrative paragraph and every catalysts/risks entry must cite a whitelisted
    # number; this is the deterministic check that catches a non-cooperative LLM
    # that shipped templated, verdict-only rhetoric instead (the GOOGL/MSFT/KO
    # blind-audit finding). Same non-blocking StepOutput.warnings channel as the
    # momentum hedge above — never gates verdict/target/confidence (contract②).
    numeric_grounding_warning = audit_narrative_numeric_grounding(thesis)

    target_str = (
        f"${thesis.price_target:.2f}" if thesis.price_target is not None else "N/A (under review)"
    )
    narrative = (
        f"Recommendation: {thesis.recommendation}. "
        f"Price target: {target_str} ({thesis.price_target_basis}). "
        f"Catalysts: {', '.join(thesis.catalysts[:2])}. "
        f"Risks: {', '.join(thesis.risks[:2])}."
    )
    return StepOutput(
        text=narrative,
        structured=thesis,
        warnings=[w for w in (street_note, momentum_warning, numeric_grounding_warning) if w],
    )


def create_equity_research_pipeline(agents: dict[str, Agent]) -> Pipeline:
    """Factory function. Accepts dict of sub-agents."""
    from finrobot.artifact.builders import build_equity_research_artifact

    return Pipeline(
        artifact_builder=build_equity_research_artifact,
        steps=[
            PipelineStep(
                name="data_collection",
                skill_section=None,
                agent=agents["data"],
                # Only FINANCIALS + PRICE feed the narrative prompt. The SEC
                # filings (10-K/10-Q/8-K/XBRL) are fetched separately by the
                # executor (_execute_data_collection_with_sec, bounded + degraded
                # into structured_context) — listing them here ALSO dumped their
                # full raw text into the LLM prompt via _gather_data. A single
                # 10-K carries Business + Risk Factors + MD&A tripled across
                # items/sections/mdna_text; for META that pushed the prompt to
                # 146,840 tokens > gpt-4o's 128k ceiling, failing every retry of
                # step 1 and crashing peer_analysis with "target FinancialData
                # not available". The LLM does not compute these numbers
                # (extract_financial_data is deterministic), so the raw text was
                # pure overhead. NEWS is dropped too — it is the catalyst_analysis
                # step's job and was redundant here.
                required_data=[
                    DataType.FINANCIALS,
                    DataType.PRICE,
                ],
                validator=StructuredValidator(
                    validate_financial_data,
                    lambda out: validate_has_fields(out, ["revenue", "ebitda"]),
                ),
                executor=_execute_data_collection_with_sec,
                # Every downstream step reads this FinancialData — abort if it
                # fails rather than crash later (e.g. peer_analysis).
                critical=True,
            ),
            PipelineStep(
                name="catalyst_analysis",
                skill_section=None,
                agent=agents["data"],
                required_data=[],
                validator=StructuredValidator(
                    validate_catalyst_analysis,
                    validate_is_non_empty,
                ),
                executor=_execute_catalyst_analysis,
                # NOT deterministic: the executor calls classify_news, an LLM
                # classification whose re-run can legitimately produce
                # different (passing) output — a validation retry has a real
                # chance of success, unlike the pure-compute steps below. The
                # deterministic flag is reserved for executors with zero LLM
                # calls (see PipelineStep.deterministic docstring).
            ),
            PipelineStep(
                name="peer_analysis",
                skill_section="comps-analysis",
                agent=agents["analysis"],
                required_data=[],
                validator=StructuredValidator(
                    validate_peer_comps,
                    lambda out: validate_has_peers(out, min_peers=3),
                ),
                executor=execute_peer_analysis,
            ),
            PipelineStep(
                name="financial_modeling",
                skill_section="dcf-model",
                agent=agents["modeling"],
                required_data=[],
                validator=StructuredValidator(validate_dcf_result, validate_is_non_empty),
                executor=_execute_financial_modeling,
                # Deterministic DCF compute — ignores the re-prompt (BUG-059).
                deterministic=True,
                # The executor builds valuation_synthesis FROM the DCFResult
                # before it is validated; if validate_dcf_result rejects the DCF
                # (e.g. WACC < 0.03), the synthesis embedding it must roll back
                # too — else the rejected number reaches the published target
                # via resolve_canonical_thesis (Critical-2). sotp_breakdown is
                # built from dcf_INPUTS (not the rejected result), so it is NOT
                # listed; data_collection / price_fx_to_usd are input refreshes.
                derived_keys=("valuation_synthesis",),
            ),
            PipelineStep(
                name="ownership_governance_analysis",
                skill_section=None,
                agent=agents["analysis"],
                required_data=[],
                validator=StructuredValidator(
                    validate_ownership_governance,
                    validate_is_non_empty,
                ),
                executor=_execute_ownership_governance_analysis,
                # Deterministic governance compute — ignores the re-prompt (BUG-059).
                deterministic=True,
            ),
            PipelineStep(
                name="technical_analysis",
                skill_section=None,
                agent=agents["modeling"],
                required_data=[],
                validator=StructuredValidator(
                    validate_technical_analysis,
                    validate_is_non_empty,
                ),
                executor=_execute_technical_analysis,
                # Deterministic indicator compute — ignores the re-prompt (BUG-059).
                deterministic=True,
            ),
            PipelineStep(
                name="thesis",
                skill_section=("initiating-coverage", "competitive-analysis", "thesis-tracker"),
                agent=agents["synthesis"],
                required_data=[],
                validator=StructuredValidator(
                    validate_thesis,
                    lambda out: validate_has_thesis(out),
                ),
                executor=_execute_thesis,
            ),
            PipelineStep(
                name="report",
                skill_section=("initiating-coverage", "tear-sheet", "equity-research"),
                agent=agents["report"],
                required_data=[],
                validator=TextValidator(validate_report_format),
            ),
        ],
    )
