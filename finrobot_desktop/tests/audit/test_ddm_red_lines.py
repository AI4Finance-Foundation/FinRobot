"""DDM determinism red-lines.

Mirrors ``test_dcf_red_lines.py`` for the Dividend Discount Model path. The
core invariant: every DDM number traces to ``seed_ddm_inputs`` (provider filings
→ Damodaran fallback), never to an LLM that hand-picks dividend growth / payout /
beta from a prompt. These guards fail if that path is reintroduced.

If you legitimately need to change the seed's field set, update the required
provenance keys here rather than dropping a field silently.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from finrobot.engine.compute.operators.ddm import calculate_ddm
from finrobot.engine.compute.operators.ddm_seed import seed_ddm_inputs
from finrobot.engine.data.normalize.contracts import NormalizedFinancials, Provenance
from finrobot.engine.models.financial import (
    BalanceSheet,
    FinancialData,
    IncomeStatement,
    MarketData,
    ValuationMetrics,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Minimal fixtures (JPM-shaped bank)
# ---------------------------------------------------------------------------


def _financials() -> FinancialData:
    return FinancialData(
        ticker="JPM",
        company_name="JPMorgan Chase & Co.",
        timestamp=datetime.now(tz=timezone.utc),
        income=IncomeStatement(
            revenue=1.6e11,
            ebitda=1.0e11,
            net_income=5.75e10,
            gross_margin=0.0,
            operating_margin=0.4,
        ),
        balance=BalanceSheet(),
        market=MarketData(
            market_cap=296.225 * 2_679_511_418,
            shares_outstanding=2_679_511_418,
            current_price=296.225,
            industry="Banks - Diversified",
            sector="Financial Services",
            beta=1.023,
        ),
        valuation=ValuationMetrics(),
    )


def _normalized() -> NormalizedFinancials:
    now = datetime.now(tz=timezone.utc)
    return NormalizedFinancials(
        ticker="JPM",
        revenue=1.6e11,
        market_cap=296.225 * 2_679_511_418,
        as_of=now,
        net_income=5.75e10,
        shares_outstanding=2_679_511_418,
        current_price=296.225,
        dividend_per_share=6.00,
        payout_ratio=0.2824,
        return_on_equity=0.16465,
        book_value_per_share=128.379,
        beta=1.023,
        industry="Banks - Diversified",
        sector="Financial Services",
        provenance=Provenance(provider="yfinance", as_of=now, fetched_at=now),
    )


# ---------------------------------------------------------------------------
# 1. Pipeline ddm_params step uses seed_ddm_inputs, not an LLM param agent
# ---------------------------------------------------------------------------


def test_ddm_params_step_uses_seed_not_llm() -> None:
    """The ddm_params step in pipelines/ddm.py must construct DDMInputs via
    ``seed_ddm_inputs`` — never via an LLM ``Agent(output_type=DDMInputs)``.

    Previously ``_execute_ddm_params`` ran a param_agent that let the LLM pick
    dividend growth ("typically 3-8%"), payout, beta and terminal growth from a
    prompt. CLAUDE.md's determinism red-line forbids that path for valuation
    numbers; this guard greps the source so it can't return.
    """
    src = (REPO_ROOT / "finrobot" / "engine" / "pipelines" / "ddm.py").read_text()

    # The deterministic executor must exist and be wired into the step.
    assert "async def _execute_ddm_seed(" in src, (
        "_execute_ddm_seed missing from pipelines/ddm.py — did you rename it?"
    )
    assert "executor=_execute_ddm_seed" in src, (
        "ddm_params step must use executor=_execute_ddm_seed."
    )
    assert "seed_ddm_inputs" in src, "pipelines/ddm.py must call seed_ddm_inputs()."

    # The banned LLM-selects-numbers path must be fully gone.
    banned = {
        "_execute_ddm_params": (
            "_execute_ddm_params is the removed LLM-picks-DDM-numbers executor. It must not return."
        ),
        "output_type=DDMInputs": (
            "Agent(output_type=DDMInputs) makes the LLM produce DDM parameters — "
            "forbidden by the determinism red-line. Use seed_ddm_inputs."
        ),
        "param_agent": (
            "param_agent reintroduces the LLM parameter-selection path. "
            "Route through seed_ddm_inputs instead."
        ),
    }
    offenders = [tok for tok in banned if tok in src]
    assert not offenders, "\n".join(
        f"pipelines/ddm.py contains banned token '{tok}': {banned[tok]}" for tok in offenders
    )


# ---------------------------------------------------------------------------
# 2. DDMInputs from seed are LLM-free and reproducible
# ---------------------------------------------------------------------------


def test_seed_is_deterministic() -> None:
    """Same snapshot ⇒ identical DDMInputs, no randomness or LLM call."""
    a = seed_ddm_inputs(_financials(), _normalized())
    b = seed_ddm_inputs(_financials(), _normalized())
    assert a.model_dump() == b.model_dump()


def test_seed_dividend_growth_is_sustainable_rate_not_narrative() -> None:
    """Year-1 growth must equal the sustainable rate ROE×(1−payout), proving the
    schedule is computed, not an LLM's "typically 3-8%" guess."""
    inputs = seed_ddm_inputs(_financials(), _normalized())
    assert inputs.dividend_growth_rates[0] == pytest.approx(0.16465 * (1 - 0.2824), abs=1e-6)


def test_seed_value_is_defensible_not_naive_undervaluation() -> None:
    """The seeded JPM must not reproduce the naive constant-payout DDM crash
    (~$102 / -66%). The terminal-payout normalization lands it near the
    residual-income cross-check (~$241)."""
    result = calculate_ddm(seed_ddm_inputs(_financials(), _normalized()))
    assert result.equity_value_per_share > 200.0, (
        "DDM collapsed toward the naive constant-payout value — terminal_payout "
        "normalization regressed."
    )


# ---------------------------------------------------------------------------
# 3. Provenance coverage (UI panel would render blank rows otherwise)
# ---------------------------------------------------------------------------


_REQUIRED_PROVENANCE_KEYS = {
    "dividend_per_share",
    "dividend_growth_rates",
    "payout_ratio",
    "terminal_payout_ratio",
    "beta",
    "risk_free_rate",
    "equity_risk_premium",
    "terminal_growth_rate",
    "shares_outstanding",
    "current_price",
}


def test_assumption_provenance_covers_every_seeded_field() -> None:
    inputs = seed_ddm_inputs(_financials(), _normalized())
    missing = _REQUIRED_PROVENANCE_KEYS - set(inputs.assumption_provenance.keys())
    assert not missing, f"Missing provenance for fields: {sorted(missing)}"


def test_assumption_provenance_messages_are_english() -> None:
    inputs = seed_ddm_inputs(_financials(), _normalized())
    offenders = [
        f"{k}: {msg}"
        for k, msg in inputs.assumption_provenance.items()
        if any("一" <= ch <= "鿿" for ch in msg)
        or not any(ch.isascii() and ch.isalpha() for ch in msg)
    ]
    assert not offenders, "Provenance messages must be readable English:\n" + "\n".join(offenders)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
