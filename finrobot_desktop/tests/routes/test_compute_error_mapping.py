"""Compute routes must map operator/data exceptions to proper HTTP status.

Before this, the seed/operator routes called the pure operators (and, for the
seed routes, ``fetch_canonical``) with no try/except, so an operator
``ValueError`` (bad inputs / degenerate model) or a provider outage surfaced as
an opaque 500 instead of a 422 (invalid input) / 502 (upstream down) with a 中文
detail the desktop UI can show. ``/dcf`` already did this; the rest now mirror it
via the shared ``_compute_http_error`` handler.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from finrobot.engine.compute.operators.monte_carlo import MonteCarloRequest
from finrobot.engine.compute.operators.sniper import SniperRequest
from finrobot.engine.data.interface import ProviderError
from finrobot.engine.models.financial import DCFInputs
from finrobot.routes.compute import _compute_http_error, router as compute_router


def _client(*, with_deps: bool = False) -> TestClient:
    app = FastAPI()
    app.include_router(compute_router)
    if with_deps:
        app.state.deps = MagicMock()
    # Return 500 as a response (don't re-raise) so a still-broken route is a
    # visible assertion failure, not a test error.
    return TestClient(app, raise_server_exceptions=False)


def _dcf_inputs() -> DCFInputs:
    return DCFInputs(
        revenue_base=1_000_000_000,
        revenue_growth_rates=[0.05, 0.04, 0.03, 0.03, 0.02],
        ebitda_margin=0.30,
        capex_pct_revenue=0.04,
        nwc_pct_revenue=0.02,
        da_pct_revenue=0.03,
        tax_rate=0.21,
        risk_free_rate=0.04,
        beta=1.1,
        equity_risk_premium=0.055,
        cost_of_debt=0.05,
        debt_ratio=0.20,
        terminal_growth_rate=0.025,
        shares_outstanding=100_000_000,
        net_debt=50_000_000,
    )


_WACC_BODY = {
    "risk_free_rate": 0.04,
    "beta": 1.0,
    "equity_risk_premium": 0.05,
    "cost_of_debt": 0.06,
    "tax_rate": 0.21,
    "debt_ratio": 0.25,
}


# ── shared handler mapping ──────────────────────────────────────────────
def test_compute_http_error_value_error_is_422() -> None:
    err = _compute_http_error(ValueError("terminal growth >= wacc"), context="DCF calculation")
    assert err.status_code == 422
    assert "DCF calculation" in err.detail


def test_compute_http_error_provider_error_is_502() -> None:
    err = _compute_http_error(ProviderError("yfinance 429"), context="AAPL")
    assert err.status_code == 502
    assert "AAPL" in err.detail


def test_compute_http_error_strips_raw_provider_url() -> None:
    err = _compute_http_error(
        ProviderError(
            "FMP request failed for url "
            "'https://financialmodelingprep.com/api/v3/quote/AAPL?apikey=secret'"
            "\nFor more information check: https://developer.mozilla.org/"
        ),
        context="AAPL",
    )

    assert err.status_code == 502
    assert "apikey" not in err.detail
    assert "for url" not in err.detail
    assert "financialmodelingprep.com" not in err.detail


# ── pure-operator routes: operator ValueError → 422 (not 500) ───────────
def test_wacc_operator_value_error_maps_to_422() -> None:
    with patch("finrobot.routes.compute.calculate_wacc", side_effect=ValueError("bad")):
        resp = _client().post("/api/compute/wacc", json=_WACC_BODY)
    assert resp.status_code == 422, resp.text


def test_sniper_operator_value_error_maps_to_422() -> None:
    body = SniperRequest(
        ticker="AAPL",
        current_price=150.0,
        dcf_target=200.0,
        historical_prices=[150.0 + i for i in range(60)],
    ).model_dump(mode="json")
    with patch(
        "finrobot.routes.compute.calculate_sniper_points",
        side_effect=ValueError("degenerate levels"),
    ):
        resp = _client().post("/api/compute/sniper", json=body)
    assert resp.status_code == 422, resp.text


def test_monte_carlo_operator_value_error_maps_to_422() -> None:
    body = MonteCarloRequest(
        inputs=_dcf_inputs(), current_price=160.0, n_simulations=100
    ).model_dump(mode="json")
    with patch(
        "finrobot.routes.compute.run_monte_carlo",
        side_effect=ValueError("bad distribution"),
    ):
        resp = _client().post("/api/compute/monte-carlo", json=body)
    assert resp.status_code == 422, resp.text


def test_lbo_operator_value_error_maps_to_422() -> None:
    from finrobot.engine.models.financial import LBOInputs

    body = LBOInputs(
        ticker="AAPL",
        ltm_ebitda=500_000_000,
        entry_ev_ebitda=10.0,
        exit_ev_ebitda=10.0,
        leverage_multiple=5.0,
        holding_period_years=5,
        revenue_growth_rate=0.05,
        ebitda_margin=0.30,
        revenue_base=1_000_000_000,
        capex_pct_revenue=0.04,
        tax_rate=0.21,
        interest_rate=0.06,
    ).model_dump(mode="json")
    with patch("finrobot.routes.compute.calculate_lbo", side_effect=ValueError("neg equity")):
        resp = _client().post("/api/compute/lbo", json=body)
    assert resp.status_code == 422, resp.text


# ── fetch (seed) routes: ProviderError → 502, ValueError → 422 ──────────
def test_dcf_seed_provider_error_maps_to_502() -> None:
    with patch(
        "finrobot.routes.compute._seed_dcf_inputs_for_ticker",
        new=AsyncMock(side_effect=ProviderError("yfinance service down")),
    ):
        resp = _client(with_deps=True).post("/api/compute/dcf-seed", json={"ticker": "AAPL"})
    assert resp.status_code == 502, resp.text
    assert "Data source" in resp.json()["detail"]


def test_dcf_seed_value_error_maps_to_422() -> None:
    with patch(
        "finrobot.routes.compute._seed_dcf_inputs_for_ticker",
        new=AsyncMock(side_effect=ValueError("unknown ticker")),
    ):
        resp = _client(with_deps=True).post("/api/compute/dcf-seed", json={"ticker": "ZZZZ"})
    assert resp.status_code == 422, resp.text


def test_dcf_equivalence_line_provider_error_maps_to_502() -> None:
    with patch(
        "finrobot.routes.compute._seed_dcf_inputs_for_ticker",
        new=AsyncMock(side_effect=ProviderError("yfinance down")),
    ):
        resp = _client(with_deps=True).post(
            "/api/compute/dcf-equivalence-line", json={"ticker": "AAPL"}
        )
    assert resp.status_code == 502, resp.text


def test_lbo_seed_provider_error_maps_to_502() -> None:
    app = FastAPI()
    app.include_router(compute_router)
    deps = MagicMock()
    deps.data_layer.fetch_canonical = AsyncMock(side_effect=ProviderError("yfinance down"))
    app.state.deps = deps
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/api/compute/lbo-seed", json={"ticker": "AAPL"})
    assert resp.status_code == 502, resp.text
    assert "Data source" in resp.json()["detail"]
