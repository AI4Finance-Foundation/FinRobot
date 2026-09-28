"""DDM (Dividend Discount Model) pipeline — for banks and dividend-paying stocks.

4 steps:
  1. historical_data    — fetch financials/price, produce FinancialData
  2. ddm_params         — deterministic: seed_ddm_inputs derives DDMInputs from
                          provider dividend/payout/ROE/beta (no LLM parameter pick)
  3. ddm_calc           — deterministic calculate_ddm() + sensitivity
  4. ddm_narrative      — LLM generates narrative with valuation thesis

Banks don't have meaningful free cash flow, so FCF-DCF produces misleading results.
DDM values the company based on projected dividends discounted at cost of equity.

Previously ``ddm_params`` used a pydantic-ai agent typed to emit DDMInputs that
let the LLM hand-pick dividend growth ("typically 3-8%"), payout, beta, and
terminal growth from a prompt — the same source-less, unstable path DCF/LBO
already removed. Numbers now trace to the company's own filings (or Damodaran
industry medians) via ``seed_ddm_inputs``; the LLM only narrates them.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import Agent

from finrobot.engine.compute.operators.ddm import calculate_ddm, calculate_ddm_sensitivity
from finrobot.engine.compute.operators.ddm_seed import seed_ddm_inputs
from finrobot.engine.compute.operators.fx_normalize import normalize_financialdata_to_usd
from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.providers.fx import fetch_fx_rate_to_usd
from finrobot.engine.data.types import DataType
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.models.financial import DDMInputs, FinancialData, StepOutput
from finrobot.engine.primitives.book_value import reconcile_book_value_to_price_basis
from finrobot.engine.primitives.industry import is_non_life_insurer
from finrobot.engine.pipelines.base import (
    Pipeline,
    PipelineStep,
    StructuredValidator,
    TextValidator,
)
from finrobot.engine.pipelines._helpers import (
    build_sensitivity_ranges,
    execute_financial_data_step,
)
from finrobot.engine.pipelines.validators import (
    validate_ddm_inputs,
    validate_ddm_output,
    validate_ddm_result,
    validate_financial_data,
    validate_has_fields,
    validate_is_non_empty,
)

logger = logging.getLogger(__name__)


async def _execute_ddm_seed(
    agent: Agent[Any, Any],  # noqa: ARG001 — kept for executor signature; unused
    deps: FinRobotDeps,
    prompt: str,  # noqa: ARG001 — kept for executor signature; unused
    structured_context: dict[str, object],
    ticker: str,
    **_kwargs: object,
) -> StepOutput:
    """Deterministic DDMInputs: seed every assumption from real provider data.

    No LLM call. Dividend, payout, ROE and beta come from the provider snapshot;
    dividend growth is the textbook sustainable rate g = ROE×(1−payout) decayed
    to perpetuity, and the terminal payout is normalized to 1 − tg/ROE. See
    ``seed_ddm_inputs`` for the full precedence ladder; ``assumption_provenance``
    carries a Chinese explanation per field for the UI.

    FinancialData (from the historical_data step) supplies the validated market
    fields; the dividend-specific fields (DPS/payout/ROE/BVPS) are read from the
    same financials DataResult via ``normalize_financials`` — they aren't carried
    on FinancialData. The fetch is cache-served, so this re-fetch is free.
    """
    financial_data = structured_context.get("historical_data")
    if not isinstance(financial_data, FinancialData):
        raise ValueError(
            "ddm_params requires FinancialData from the historical_data step "
            "but received: " + type(financial_data).__name__
        )

    # Non-life insurers (P&C / diversified / reinsurance / specialty) degrade the
    # standalone DDM at source. Their underwriting-cycle ROE swings to a hard-market
    # peak that g = ROE×(1−payout) extrapolates as perpetual growth, and their low
    # (buyback-driven) dividend payout drives a large terminal-payout step-up — the
    # two compound to value the dividend stream at multiples of price even after
    # through-cycle ROE normalization (live 2026-07-06: ALL DDM +530% / TRV +177% /
    # HIG +229% / CB +115% at through-cycle ROE, residual = the low-payout step-up).
    # A LIFE insurer earns a stable spread and pays a high steady dividend, so its DDM
    # is legitimate and NOT suppressed; a BANK (is_bank) reaches DDM via the report
    # path, never here. Skip seeding, emit a machine-readable reason + P/B-comps
    # routing (ddm_calc passes it through; build_ddm_artifact tolerates the None
    # result) — a traceable degradation to relative valuation, not a refusal.
    if is_non_life_insurer(
        industry=financial_data.market.industry, sector=financial_data.market.sector
    ):
        logger.info("DDM not applicable for %s: non-life insurer (underwriting-cycle)", ticker)
        return StepOutput(
            text=(
                f"DDM not applicable: {ticker} is a non-life (property-casualty / diversified / "
                f"reinsurance) insurer. Its underwriting-cycle ROE and buyback-driven low dividend "
                f"payout make the dividend-discount model structurally unreliable (cyclical-peak "
                f"growth extrapolation + terminal-payout step-up). Value on P/B comps (ROE-adjusted) "
                f"instead; the dividend stream alone understates a buyback-heavy insurer."
            ),
            structured=None,
        )

    _fin = await deps.data_layer.fetch_canonical(DataType.FINANCIALS, ticker)

    # FX-normalize to canonical USD before seeding so a foreign issuer's
    # reporting-currency dividend / net income never mixes with its USD quote
    # price — otherwise the DDM equity_value_per_share (built from a TWD DPS) is
    # compared against a USD current_price and reads ~32x off (BUG-073). DPS and
    # book value per share live on the NormalizedFinancials snapshot (not
    # FinancialData), so they need the reporting rate applied alongside.
    fmp_api_key = getattr(deps.settings, "fmp_api_key", None)
    reporting_src = financial_data.reporting_currency.upper()
    quote_src = financial_data.quote_currency.upper()
    if reporting_src != "USD" or quote_src != "USD":
        reporting_rate = (
            1.0
            if reporting_src == "USD"
            else await fetch_fx_rate_to_usd(reporting_src, fmp_api_key=fmp_api_key)
        )
        if quote_src == "USD":
            quote_rate = 1.0
        elif quote_src == reporting_src:
            quote_rate = reporting_rate
        else:
            quote_rate = await fetch_fx_rate_to_usd(quote_src, fmp_api_key=fmp_api_key)
        financial_data = normalize_financialdata_to_usd(financial_data, reporting_rate, quote_rate)
        # NormalizedFinancials per-share dividend amounts are reporting-currency.
        _fin = _fin.model_copy(
            update={
                "dividend_per_share": (
                    _fin.dividend_per_share * reporting_rate
                    if _fin.dividend_per_share is not None
                    else None
                ),
                "book_value_per_share": (
                    _fin.book_value_per_share * reporting_rate
                    if _fin.book_value_per_share is not None
                    else None
                ),
                "reporting_currency": "USD",
                "quote_currency": "USD",
            }
        )

    # Book value per share on the quoted price's (per-ADR) basis before it seeds the
    # DDM P/B distortion guard and the residual-income justified-P/B (both compare
    # bvps against the per-ADR current_price / multiply it into a per-share value).
    # The canonical keeps bvps on the provider's raw share basis (so the comps
    # pb_ratio stays byte-identical); the DDM/RI seed needs the per-ADR figure, the
    # same reconciliation extract_financial_data applies for the displayed snapshot.
    # No-op for every current issuer (US, and the bank/insurer ADRs whose provider
    # share count already matches market_cap/price); guards a future off-basis ADR.
    reconciled_bvps, bvps_note = reconcile_book_value_to_price_basis(
        _fin.book_value_per_share, _fin.shares_outstanding, _fin.market_cap, _fin.current_price
    )
    if bvps_note is not None:
        _fin = _fin.model_copy(
            update={
                "book_value_per_share": reconciled_bvps,
                "warnings": [*_fin.warnings, bvps_note],
            }
        )

    # Write the USD-normalized snapshot BACK so build_ddm_artifact's raw_data
    # (→ entry_price) is the SAME currency as the USD equity_value_per_share —
    # same Critical-1 / BUG-073 caliber drift the DCF pipeline fixes. No-op for
    # US issuers (financial_data was never reassigned above).
    structured_context["historical_data"] = financial_data

    # Declared dividend history for the DDM growth seed. Used only for
    # buyback-distorted franchises (high P/B) where ROE×(1−payout) overstates
    # growth — seed_ddm_inputs grows their dividend at the issuer's own DPS CAGR
    # instead (see ddm_seed). A CAGR is a ratio, so the reporting-currency /
    # per-ADR-share caliber of the raw DPS cancels out — no FX normalization
    # needed here. Best-effort: a fetch failure leaves reasonable-P/B names on the
    # book-based growth (unchanged) and degrades a distorted name to nominal
    # growth rather than shipping an overstated rate.
    dividend_history: dict[str, float] | None = None
    try:
        _div = await deps.data_layer.fetch(DataType.DIVIDENDS, ticker)
        annual = _div.data.get("annual_dps") if isinstance(_div.data, dict) else None
        if isinstance(annual, dict):
            dividend_history = {str(k): float(v) for k, v in annual.items()}
    except (ProviderError, ValueError, KeyError, TypeError) as _div_err:
        # An auxiliary fetch must never fail the DDM (mirrors the forward-estimates
        # best-effort in execute_financial_data_step): a reasonable-P/B name is
        # unaffected, and a distorted name degrades to nominal growth.
        logger.debug("DIVIDENDS unavailable for %s: %s", ticker, _div_err)

    ddm_inputs = seed_ddm_inputs(financial_data, _fin, dividend_history=dividend_history)

    return StepOutput(text=ddm_inputs.model_dump_json(), structured=ddm_inputs)


async def _execute_ddm_calc(
    agent: Agent[Any, Any],
    deps: FinRobotDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
    **_kwargs: object,
) -> StepOutput:
    """Deterministic DDM calculation from DDMInputs + sensitivity table."""
    inputs = structured_context.get("ddm_params")
    if inputs is None:
        # ddm_params degraded upstream (non-life insurer → DDM not applicable). Pass
        # the not-applicable state through with structured=None; build_ddm_artifact
        # tolerates the missing DDMResult and the report falls back to P/B comps.
        return StepOutput(
            text="DDM not applicable for this issuer — see the ddm_params step.",
            structured=None,
        )
    if not isinstance(inputs, DDMInputs):
        raise ValueError("ddm_params step must produce DDMInputs structured output")

    ddm_result = calculate_ddm(inputs)

    coe_range, tg_range = build_sensitivity_ranges(
        ddm_result.cost_of_equity, inputs.terminal_growth_rate
    )
    sensitivity = calculate_ddm_sensitivity(inputs, coe_range=coe_range, tg_range=tg_range)

    # Extract price range from sensitivity
    all_prices = [
        p for row in sensitivity["implied_prices"] for p in row if p is not None and p > 0
    ]
    price_range = f"${min(all_prices):.0f}–${max(all_prices):.0f}" if all_prices else "N/A"

    # Build narrative
    upside = ddm_result.upside
    direction = "upside" if upside >= 0 else "downside"
    narrative = (
        f"DDM implies ${ddm_result.equity_value_per_share:.2f} per share "
        f"({abs(upside):.1%} {direction} vs ${inputs.current_price:.2f}). "
        f"Cost of equity: {ddm_result.cost_of_equity:.1%}. "
        f"Terminal growth: {inputs.terminal_growth_rate:.1%}. "
        f"Sensitivity range: {price_range}."
    )

    # Store sensitivity in a combined result for report context
    # (DDMResult is frozen, so we attach it via structured_context)
    structured_context["ddm_sensitivity"] = sensitivity

    return StepOutput(text=narrative, structured=ddm_result)


def create_ddm_pipeline(agents: dict[str, Agent]) -> Pipeline:
    """4-step DDM valuation pipeline factory.

    Used for banks and dividend-paying stocks where FCF-DCF is inappropriate.
    """
    from finrobot.artifact.builders import build_ddm_artifact

    return Pipeline(
        artifact_builder=build_ddm_artifact,
        steps=[
            PipelineStep(
                name="historical_data",
                skill_section=None,
                agent=agents["data"],
                required_data=[DataType.FINANCIALS, DataType.PRICE],
                validator=StructuredValidator(
                    validate_financial_data,
                    lambda out: validate_has_fields(out, ["revenue"]),
                ),
                executor=execute_financial_data_step,
                # ddm_params/ddm_calc read this FinancialData — abort if it fails.
                critical=True,
            ),
            PipelineStep(
                name="ddm_params",
                skill_section=None,
                agent=agents["modeling"],
                required_data=[],
                validator=StructuredValidator(validate_ddm_inputs, validate_is_non_empty),
                executor=_execute_ddm_seed,
                # Deterministic seed_ddm_inputs — ignores the re-prompt (BUG-059).
                deterministic=True,
            ),
            PipelineStep(
                name="ddm_calc",
                skill_section=None,
                agent=agents["modeling"],
                required_data=[],
                validator=StructuredValidator(validate_ddm_result, validate_is_non_empty),
                executor=_execute_ddm_calc,
                # Deterministic calculate_ddm — ignores the re-prompt (BUG-059).
                deterministic=True,
            ),
            PipelineStep(
                name="ddm_narrative",
                skill_section=None,
                agent=agents["report"],
                required_data=[],
                validator=TextValidator(validate_ddm_output),
            ),
        ],
    )
