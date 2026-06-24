"""Tests for seed_ddm_inputs — deterministic DDMInputs builder.

Expected values are anchored to the JPM acceptance baseline pulled from live
yfinance on 2026-05-29 (written before the implementation):

    DPS=$6.00, payout=28.24%, ROE=16.465%, BVPS=$128.38, beta=1.023,
    shares=2.68B, price=$296.23, net income=$57.5B, industry "Banks - Diversified".

The seeded inputs, run through calculate_ddm, must land near the residual-income
cross-check (~$241), NOT the naive constant-payout DDM (~$102 / -66%).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from finrobot.engine.compute.operators.dcf_seed import (
    DEFAULT_EQUITY_RISK_PREMIUM,
    DEFAULT_RISK_FREE_RATE,
    DEFAULT_TERMINAL_GROWTH,
)
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

# --- JPM baseline (yfinance 2026-05-29) ------------------------------------
JPM_DPS = 6.00
JPM_PAYOUT = 0.2824
JPM_ROE = 0.16465
JPM_BVPS = 128.379
JPM_BETA = 1.023
JPM_SHARES = 2_679_511_418
JPM_PRICE = 296.225
JPM_NET_INCOME = 57_512_001_536.0


def _financials(
    *,
    beta: float | None = JPM_BETA,
    net_income: float | None = JPM_NET_INCOME,
    shares: float = JPM_SHARES,
    price: float = JPM_PRICE,
    industry: str | None = "Banks - Diversified",
) -> FinancialData:
    return FinancialData(
        ticker="JPM",
        company_name="JPMorgan Chase & Co.",
        timestamp=datetime.now(tz=timezone.utc),
        income=IncomeStatement(
            revenue=1.6e11,
            ebitda=1.0e11,
            net_income=net_income,
            gross_margin=0.0,
            operating_margin=0.4,
        ),
        balance=BalanceSheet(),
        market=MarketData(
            market_cap=price * shares,
            shares_outstanding=shares,
            current_price=price,
            industry=industry,
            sector="Financial Services",
            beta=beta,
        ),
        valuation=ValuationMetrics(),
    )


def _normalized(
    *,
    dividend_per_share: float | None = JPM_DPS,
    payout_ratio: float | None = JPM_PAYOUT,
    return_on_equity: float | None = JPM_ROE,
    book_value_per_share: float | None = JPM_BVPS,
    beta: float | None = JPM_BETA,
) -> NormalizedFinancials:
    now = datetime.now(tz=timezone.utc)
    return NormalizedFinancials(
        ticker="JPM",
        revenue=1.6e11,
        market_cap=JPM_PRICE * JPM_SHARES,
        as_of=now,
        net_income=JPM_NET_INCOME,
        shares_outstanding=JPM_SHARES,
        current_price=JPM_PRICE,
        dividend_per_share=dividend_per_share,
        payout_ratio=payout_ratio,
        return_on_equity=return_on_equity,
        book_value_per_share=book_value_per_share,
        beta=beta,
        industry="Banks - Diversified",
        sector="Financial Services",
        provenance=Provenance(provider="yfinance", as_of=now, fetched_at=now),
    )


class TestSeedHappyPath:
    """JPM baseline — the headline acceptance test."""

    def test_dividend_and_payout_from_provider(self) -> None:
        inputs = seed_ddm_inputs(_financials(), _normalized())
        assert inputs.dividend_per_share == pytest.approx(JPM_DPS)
        assert inputs.payout_ratio == pytest.approx(JPM_PAYOUT)

    def test_sustainable_growth_formula(self) -> None:
        """g = ROE × (1 − payout) = 16.465% × (1 − 28.24%) = 11.82%, year-1 of schedule."""
        inputs = seed_ddm_inputs(_financials(), _normalized())
        expected_g = JPM_ROE * (1 - JPM_PAYOUT)
        assert inputs.dividend_growth_rates[0] == pytest.approx(expected_g, abs=1e-6)

    def test_growth_decays_to_terminal(self) -> None:
        inputs = seed_ddm_inputs(_financials(), _normalized())
        rates = inputs.dividend_growth_rates
        assert rates == sorted(rates, reverse=True)  # monotone decreasing
        assert rates[-1] == pytest.approx(DEFAULT_TERMINAL_GROWTH, abs=1e-6)

    def test_terminal_payout_normalized(self) -> None:
        """terminal payout = 1 − tg/ROE = 1 − 2.5%/16.465% = 84.82%."""
        inputs = seed_ddm_inputs(_financials(), _normalized())
        expected = 1 - DEFAULT_TERMINAL_GROWTH / JPM_ROE
        assert inputs.terminal_payout_ratio == pytest.approx(expected, abs=1e-6)

    def test_beta_from_provider(self) -> None:
        # Beta now gets the SAME asymmetric Blume adjustment dcf_seed applies — cost
        # of equity is a property of the equity, not the valuation method, so DDM
        # and DCF must discount one stock at one beta (lead-adjudicated 2026-06-22).
        # JPM_BETA 1.023 > 1.0, so it mean-reverts toward 1.0. Expected value is the
        # Blume formula computed independently (not via the impl) to avoid a
        # same-source mock that would stay green if adjust_beta_blume regressed.
        expected_blume = 2.0 / 3.0 * JPM_BETA + 1.0 / 3.0
        inputs = seed_ddm_inputs(_financials(), _normalized())
        assert inputs.beta == pytest.approx(expected_blume)
        assert inputs.beta < JPM_BETA  # a high-β estimate was pulled toward 1.0
        assert "Blume-adjusted" in inputs.assumption_provenance["beta"]

    def test_macro_defaults(self) -> None:
        inputs = seed_ddm_inputs(_financials(), _normalized())
        assert inputs.risk_free_rate == pytest.approx(DEFAULT_RISK_FREE_RATE)
        assert inputs.equity_risk_premium == pytest.approx(DEFAULT_EQUITY_RISK_PREMIUM)
        assert inputs.terminal_growth_rate == pytest.approx(DEFAULT_TERMINAL_GROWTH)

    def test_end_to_end_value_is_defensible(self) -> None:
        """Seeded JPM lands ~$344 (+16%), not naive ~$158 (-46%).

        Bounds recalibrated after c18fe9a changed ERP 5.5%→4.23%, tg 2.5%→3.0%,
        and projection_years 5→10 (all three lift the DDM value). The normalization
        logic is unchanged; its effect (2.2× lift vs naive constant-payout) is
        still what this test guards.
        """
        inputs = seed_ddm_inputs(_financials(), _normalized())
        result = calculate_ddm(inputs)
        assert 310.0 < result.equity_value_per_share < 380.0
        assert 0.0 < result.upside < 0.35


class TestSeedFallbacks:
    def test_dps_derived_from_payout_when_missing(self) -> None:
        """No provider DPS ⇒ payout × net_income / shares."""
        inputs = seed_ddm_inputs(_financials(), _normalized(dividend_per_share=None))
        expected_dps = JPM_PAYOUT * JPM_NET_INCOME / JPM_SHARES
        assert inputs.dividend_per_share == pytest.approx(expected_dps)
        assert "payout ratio" in inputs.assumption_provenance["dividend_per_share"]

    def test_no_dividend_raises(self) -> None:
        """No DPS and no payout ⇒ DDM is inapplicable."""
        with pytest.raises(ValueError, match="positive dividend"):
            seed_ddm_inputs(
                _financials(),
                _normalized(dividend_per_share=None, payout_ratio=None),
            )

    def test_missing_net_income_with_provider_dps_still_seeds(self) -> None:
        """income.net_income None but provider reports DPS directly ⇒ the DPS
        path needs no net income, so DDM still seeds (no None arithmetic)."""
        inputs = seed_ddm_inputs(_financials(net_income=None), _normalized())
        assert inputs.dividend_per_share == pytest.approx(JPM_DPS)

    def test_missing_net_income_no_provider_dps_raises(self) -> None:
        """income.net_income None and no provider DPS ⇒ the payout-derived
        dividend can't be computed; DDM is inapplicable rather than crashing on
        a None × payout multiply."""
        with pytest.raises(ValueError, match="positive dividend"):
            seed_ddm_inputs(
                _financials(net_income=None),
                _normalized(dividend_per_share=None),
            )

    def test_payout_derived_from_dps_eps(self) -> None:
        """No provider payout ⇒ DPS / EPS, EPS = net_income / shares."""
        inputs = seed_ddm_inputs(_financials(), _normalized(payout_ratio=None))
        eps = JPM_NET_INCOME / JPM_SHARES
        assert inputs.payout_ratio == pytest.approx(JPM_DPS / eps)
        assert "EPS" in inputs.assumption_provenance["payout_ratio"]

    def test_roe_missing_uses_generic_growth(self) -> None:
        inputs = seed_ddm_inputs(_financials(), _normalized(return_on_equity=None))
        # Generic start = max(tg*2, 5%). With DEFAULT_TERMINAL_GROWTH=3.0%: max(6%,5%)=6%.
        expected_g = max(DEFAULT_TERMINAL_GROWTH * 2, 0.05)
        assert inputs.dividend_growth_rates[0] == pytest.approx(expected_g, abs=1e-6)
        assert inputs.terminal_payout_ratio is None
        assert "ROE unavailable" in inputs.assumption_provenance["terminal_payout_ratio"]

    def test_beta_falls_back_to_industry(self) -> None:
        """Provider beta missing ⇒ Damodaran bank levered beta (≠ default 1.0)."""
        inputs = seed_ddm_inputs(_financials(beta=None), _normalized(beta=None))
        assert 0.3 <= inputs.beta <= 2.5
        assert "industry" in inputs.assumption_provenance["beta"]


class TestSeedClamps:
    def test_growth_clamped_at_ceiling(self) -> None:
        """A 90% ROE with low payout would imply g far above the 40% ceiling."""
        inputs = seed_ddm_inputs(
            _financials(),
            _normalized(return_on_equity=0.90, payout_ratio=0.10),
        )
        assert inputs.dividend_growth_rates[0] == pytest.approx(0.40)

    def test_beta_clamped(self) -> None:
        inputs = seed_ddm_inputs(_financials(beta=4.5), _normalized(beta=4.5))
        assert inputs.beta == pytest.approx(2.5)

    def test_terminal_payout_floored_at_trailing(self) -> None:
        """Terminal payout never drops below the trailing payout."""
        # ROE low enough that 1 − tg/ROE < trailing payout ⇒ floor at trailing.
        # net_income set so EPS = DPS / 0.80 → the self-derived payout equals the
        # provider's 0.80 (else the DPS/EPS-disagreement guard would substitute the
        # derived ratio and this would no longer test the terminal floor at 0.80).
        inputs = seed_ddm_inputs(
            _financials(net_income=(6.0 / 0.80) * JPM_SHARES),
            _normalized(return_on_equity=0.05, payout_ratio=0.80),
        )
        assert inputs.terminal_payout_ratio is not None
        assert inputs.terminal_payout_ratio >= 0.80

    def test_payout_disagreement_prefers_self_derived(self) -> None:
        """Bug-2 (2026-06-24): a provider payout disagreeing with the issuer's own
        DPS/EPS by >10pp is replaced by the self-derived ratio (KO: provider 80.1% vs
        DPS $2.08 / EPS $3.18 = 65.3%). An inflated payout understates the sustainable
        g = ROE×(1−payout) for low-β dividend payers."""
        eps = 6.0 / 0.65  # DPS $6 / EPS → self-derived payout 0.65 vs an inflated 0.80
        inputs = seed_ddm_inputs(
            _financials(net_income=eps * JPM_SHARES),
            _normalized(return_on_equity=0.12, payout_ratio=0.80),
        )
        prov = inputs.assumption_provenance["payout_ratio"]
        assert "self-derived" in prov and "disagrees" in prov
        assert "65.0%" in prov  # the derived ratio, not the provider's 80.0%

    def test_payout_agreement_keeps_provider(self) -> None:
        """Provider payout within tolerance of DPS/EPS → keep the provider value (the
        JPM baseline DPS $6 / EPS ~$21.5 = 27.9% ≈ provider 28.2%, a 0.3pp gap)."""
        inputs = seed_ddm_inputs(_financials(), _normalized())
        assert "provider-reported" in inputs.assumption_provenance["payout_ratio"]


class TestSeedProvenance:
    _REQUIRED_KEYS = {
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

    def test_covers_every_required_field(self) -> None:
        inputs = seed_ddm_inputs(_financials(), _normalized())
        missing = self._REQUIRED_KEYS - set(inputs.assumption_provenance.keys())
        assert not missing, f"Missing provenance for: {sorted(missing)}"

    def test_messages_are_english(self) -> None:
        inputs = seed_ddm_inputs(_financials(), _normalized())
        offenders = [
            f"{k}: {msg}"
            for k, msg in inputs.assumption_provenance.items()
            if any("一" <= ch <= "鿿" for ch in msg)
            or not any(ch.isascii() and ch.isalpha() for ch in msg)
        ]
        assert not offenders, "Provenance must be readable English:\n" + "\n".join(offenders)


class TestDdmBetaBand:
    """DDM shares the same WACC-layer beta judge as DCF: an out-of-band vendor beta
    must not crash seed_ddm_inputs and must substitute the industry levered-beta
    proxy (then clamp to DDMInputs' [0.3, 2.5] band); in-band betas are kept raw.
    """

    @pytest.mark.parametrize("beta", [-0.248, -0.752, 0.0, 6.0])
    def test_out_of_band_beta_no_crash_uses_industry(self, beta) -> None:
        inputs = seed_ddm_inputs(_financials(beta=beta), _normalized())
        # DDMInputs.beta is bounded [0.3, 3]; the proxy (≥0.3) survives, never the
        # raw negative/>5 glitch. Provenance discloses the substitution.
        assert 0.3 <= inputs.beta <= 2.5
        prov = inputs.assumption_provenance["beta"]
        assert "industry levered beta" in prov
        assert "industry levered-beta proxy" in prov

    def test_in_band_normal_bank_beta_kept_raw(self) -> None:
        # A normal in-band bank beta (0.95) is kept verbatim — Blume is a no-op at ≤1.0,
        # and 0.95 is not implausibly low vs the bank industry, so the relative check does
        # not fire. Provenance shows the provider source.
        inputs = seed_ddm_inputs(_financials(beta=0.95), _normalized())
        assert inputs.beta == pytest.approx(0.95)
        prov = inputs.assumption_provenance["beta"]
        assert "provider-reported" in prov
        assert "industry levered-beta proxy" not in prov

    def test_implausibly_low_bank_beta_uses_industry_proxy(self) -> None:
        # A bank beta 0.354 is NOT a real defensive reading (banks are never low-beta
        # defensives) — it sits far below the bank industry levered beta, so it is treated
        # as a short-window vendor artifact and routes to the industry proxy (MTB-style).
        inputs = seed_ddm_inputs(_financials(beta=0.354), _normalized())
        assert inputs.beta > 0.354
        prov = inputs.assumption_provenance["beta"]
        assert "implausibly low" in prov
