import asyncio
import logging

from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.exceptions import AgentRunError

from finagent.engine.data.interface import ProviderError
from finagent.engine.data.types import DataType
from finagent.engine.models.financial import (
    FinancialData,
    CompanyFinancials,
    PeerComps,
    PeerSelection,
    DCFInputs,
    DCFResult,
    ThesisResult,
    StepOutput,
)
from finagent.engine.compute.extractor import extract_financial_data, extract_company_financials
from finagent.engine.compute.multiples import calculate_multiples, calculate_peer_statistics
from finagent.engine.compute.dcf import calculate_dcf, calculate_sensitivity
from finagent.engine.pipelines.base import Pipeline, PipelineStep
from finagent.engine.pipelines.validators import (
    validate_has_fields,
    validate_has_peers,
    validate_has_thesis,
    validate_report_format,
    validate_is_non_empty,
    validate_financial_data,
    validate_peer_comps,
    validate_dcf_result,
    validate_thesis,
)

logger = logging.getLogger(__name__)


async def _execute_data_collection(agent, deps, prompt, structured_context, ticker):
    """Agent provides narrative; code extracts typed FinancialData from yfinance."""
    step_result = await agent.run(prompt, deps=deps)
    raw_text = step_result.output

    financials_result = await deps.data_layer.fetch(DataType.FINANCIALS, ticker)
    price_result = await deps.data_layer.fetch(DataType.PRICE, ticker)
    financial_data = extract_financial_data(financials_result, price_result)

    return StepOutput(text=raw_text, structured=financial_data)


async def _execute_peer_analysis(agent, deps, prompt, structured_context, ticker):
    """LLM selects peer tickers (structured output); code fetches and computes multiples."""
    peer_agent = Agent(
        deps.settings.model_name,
        output_type=PeerSelection,
        instructions=(
            "Select 3-5 comparable publicly traded companies for peer analysis. "
            "Choose companies in the same sector with similar business models and market cap. "
            "Return valid ticker symbols only (e.g. MSFT, GOOGL, not 'Microsoft')."
        ),
        defer_model_check=True,
    )
    try:
        peer_result = await peer_agent.run(prompt, deps=deps)
        selection = peer_result.output
    except (AgentRunError, ValidationError, ValueError) as e:
        raise ValueError(f"Failed to select peer companies: {e}") from e

    async def _fetch_one_peer(peer_ticker: str) -> CompanyFinancials | None:
        try:
            fin_result = await deps.data_layer.fetch(DataType.FINANCIALS, peer_ticker)
            company = extract_company_financials(fin_result)
            calculate_multiples(company)
            return company
        except (ProviderError, ValueError, KeyError, ArithmeticError) as e:
            logger.warning(f"Skipping peer {peer_ticker}: {e}")
            return None

    peer_results = await asyncio.gather(*[_fetch_one_peer(t) for t in selection.tickers])
    peers: list[CompanyFinancials] = [p for p in peer_results if p is not None]

    if len(peers) < 3:
        raise ValueError(
            f"Only {len(peers)} peers fetched successfully (need >=3). "
            f"Attempted: {selection.tickers}."
        )

    target_fin: FinancialData = structured_context.get("data_collection")
    if target_fin is None:
        raise ValueError(
            "data_collection structured output not available; cannot build peer target."
        )
    target = CompanyFinancials(
        ticker=ticker,
        revenue=target_fin.revenue,
        ebitda=target_fin.ebitda,
        net_income=target_fin.net_income,
        market_cap=target_fin.market_cap,
        total_debt=target_fin.total_debt,
        total_cash=target_fin.total_cash,
        gross_margin=target_fin.gross_margin,
        operating_margin=target_fin.operating_margin,
    )
    calculate_multiples(target)

    peer_comps = PeerComps(
        target=target,
        peers=peers,
        peer_justification=selection.rationale,
    )
    calculate_peer_statistics(peer_comps)

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


async def _execute_financial_modeling(agent, deps, prompt, structured_context, ticker):
    """param_agent selects DCF assumptions; calculate_dcf() does all math."""
    param_agent = Agent(
        deps.settings.model_name,
        output_type=DCFInputs,
        instructions=(
            "Select DCF valuation parameters based on the financial data and peer analysis. "
            "Use conservative assumptions. Revenue growth rates must reflect realistic projections. "
            "WACC inputs must be internally consistent."
        ),
        defer_model_check=True,
    )
    try:
        param_result = await param_agent.run(prompt, deps=deps)
        dcf_inputs = param_result.output
    except (AgentRunError, ValidationError, ValueError) as e:
        raise ValueError(f"LLM failed to produce valid DCF parameters: {e}") from e

    try:
        dcf_result = calculate_dcf(dcf_inputs)
    except (ValueError, ArithmeticError) as e:
        raise ValueError(f"DCF calculation failed with provided parameters: {e}") from e
    wacc_range, tg_range = _build_sensitivity_ranges(dcf_result)
    sensitivity = calculate_sensitivity(dcf_inputs, wacc_range=wacc_range, tg_range=tg_range)
    dcf_result = dcf_result.model_copy(update={"sensitivity_table": sensitivity})

    valid_prices = [
        p for row in sensitivity["implied_prices"] for p in row if p is not None and p > 0
    ]
    price_range = f"${min(valid_prices):.0f}-${max(valid_prices):.0f}" if valid_prices else "N/A"
    narrative = (
        f"DCF base case implies ${dcf_result.implied_price:.2f} per share. "
        f"WACC: {dcf_result.wacc:.1%}, Terminal growth: {dcf_inputs.terminal_growth_rate:.1%}. "
        f"Enterprise value: ${dcf_result.enterprise_value / 1e9:.1f}B. "
        f"Sensitivity range: {price_range}."
    )
    return StepOutput(text=narrative, structured=dcf_result)


async def _execute_thesis(agent, deps, prompt, structured_context, ticker):
    """synthesis_agent writes thesis with structured output."""
    synthesis_agent = Agent(
        deps.settings.model_name,
        output_type=ThesisResult,
        instructions=(
            "Write an investment thesis based on the DCF valuation and peer analysis. "
            "Provide a recommendation (Buy/Hold/Sell), price target, catalysts, and risks."
        ),
        defer_model_check=True,
    )
    try:
        result = await synthesis_agent.run(prompt, deps=deps)
        thesis = result.output
    except (AgentRunError, ValidationError, ValueError) as e:
        raise ValueError(f"LLM failed to produce valid thesis: {e}") from e

    narrative = (
        f"Recommendation: {thesis.recommendation}. "
        f"Price target: ${thesis.price_target:.2f} ({thesis.price_target_basis}). "
        f"Catalysts: {', '.join(thesis.catalysts[:2])}. "
        f"Risks: {', '.join(thesis.risks[:2])}."
    )
    return StepOutput(text=narrative, structured=thesis)


def _build_sensitivity_ranges(dcf_result: DCFResult) -> tuple[list[float], list[float]]:
    """Build WACC and terminal growth ranges for sensitivity analysis."""
    wacc = dcf_result.wacc
    tg = dcf_result.inputs.terminal_growth_rate

    wacc_range = [round(max(0.03, wacc - 0.02 + i * 0.01), 4) for i in range(5)]
    tg_candidates = [round(max(0.0, tg - 0.01 + i * 0.005), 4) for i in range(5)]

    min_wacc = min(wacc_range)
    tg_range = [g for g in tg_candidates if g < min_wacc]

    if len(tg_range) < 2:
        tg_range = [round(0.005 + i * 0.005, 4) for i in range(5) if 0.005 + i * 0.005 < min_wacc]

    return wacc_range, tg_range


def create_equity_research_pipeline(agents: dict[str, Agent]) -> Pipeline:
    """Factory function. Accepts dict of sub-agents."""
    return Pipeline(
        steps=[
            PipelineStep(
                name="data_collection",
                skill_section=None,
                agent=agents["data"],
                required_data=[DataType.FINANCIALS, DataType.PRICE, DataType.NEWS],
                validate=lambda out: validate_has_fields(out, ["revenue", "ebitda"]),
                validate_structured=validate_financial_data,
                execute_fn=_execute_data_collection,
            ),
            PipelineStep(
                name="peer_analysis",
                skill_section="comps-analysis",
                agent=agents["analysis"],
                required_data=[],
                validate=lambda out: validate_has_peers(out, min_peers=3),
                validate_structured=validate_peer_comps,
                execute_fn=_execute_peer_analysis,
            ),
            PipelineStep(
                name="financial_modeling",
                skill_section="dcf-model",
                agent=agents["modeling"],
                required_data=[],
                validate=lambda out: validate_is_non_empty(out),
                validate_structured=validate_dcf_result,
                execute_fn=_execute_financial_modeling,
            ),
            PipelineStep(
                name="thesis",
                skill_section="initiating-coverage",
                agent=agents["synthesis"],
                required_data=[],
                validate=lambda out: validate_has_thesis(out),
                validate_structured=validate_thesis,
                execute_fn=_execute_thesis,
            ),
            PipelineStep(
                name="report",
                skill_section=None,
                agent=agents["report"],
                required_data=[],
                validate=lambda out: validate_report_format(out),
            ),
        ]
    )
