"""FMP silent-fallback disclosure on live-data responses (P2 audit 2026-06-10).

build_data_layer puts FMP first whenever a key is configured, so for an
FMP-served type a response whose ``data_source`` is yfinance DESPITE a
configured key means the layer silently fell back (bad/expired key, outage).
The fallback is correct; its invisibility was the bug. The route layer appends
a user-visible warning so the desktop can show why the source isn't the one
the user configured — layer.py stays policy-free.
"""

from __future__ import annotations

from types import SimpleNamespace

from finrobot.routes.data import _fmp_degradation_warning, _with_fmp_degradation_note


def _request(fmp_key: str) -> SimpleNamespace:
    settings = SimpleNamespace(fmp_api_key=fmp_key)
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(deps=SimpleNamespace(settings=settings)))
    )


def test_warning_only_when_fmp_configured_and_yfinance_served() -> None:
    # FMP configured + yfinance served → degradation note (both bare provider
    # name and the provider-cache suffix form).
    assert _fmp_degradation_warning(_request("fmp-key"), "yfinance") is not None
    assert _fmp_degradation_warning(_request("fmp-key"), "yfinance:provider-cache") is not None
    # FMP actually served → no note.
    assert _fmp_degradation_warning(_request("fmp-key"), "fmp") is None
    # No FMP key → yfinance is the configured primary, not a degradation.
    assert _fmp_degradation_warning(_request(""), "yfinance") is None
    # Unknown source → say nothing rather than guess.
    assert _fmp_degradation_warning(_request("fmp-key"), None) is None


def test_price_payload_note_appended_once_and_list_coerced() -> None:
    req = _request("fmp-key")
    payload = {"data_source": "yfinance", "warnings": ["existing"]}
    out = _with_fmp_degradation_note(req, payload)
    assert out is payload
    assert out["warnings"][0] == "existing"
    assert any("yfinance 降级" in w for w in out["warnings"])

    # Idempotent — re-running the note never duplicates it.
    n = len(out["warnings"])
    _with_fmp_degradation_note(req, payload)
    assert len(payload["warnings"]) == n

    # Non-list warnings field is replaced, not crashed on.
    weird = {"data_source": "yfinance", "warnings": "oops"}
    out2 = _with_fmp_degradation_note(req, weird)
    assert isinstance(out2["warnings"], list) and out2["warnings"]

    # FMP-served payload is untouched.
    clean = {"data_source": "fmp", "warnings": []}
    assert _with_fmp_degradation_note(req, clean)["warnings"] == []


def test_historical_metrics_payload_roundtrips_through_note() -> None:
    """/historical appends the note to the cached dict and re-validates it —
    the HistoricalMetrics model must carry data_source + warnings through."""
    from finrobot.engine.models.financial import HistoricalMetrics

    metrics = HistoricalMetrics(
        data_source="yfinance",
        years=[2022],
        revenue=[1e9],
        revenue_growth_yoy=[None],
        cogs=[None],
        gross_profit=[None],
        gross_margin=[None],
        sga=[0.0],
        sga_ratio=[None],
        ebitda=[1e8],
        ebitda_margin=[0.1],
        operating_income=[1e8],
        operating_margin=[0.1],
        net_income=[5e7],
        eps=[1.0],
        pe_ratio=[None],
        cagr_revenue=None,
        ticker="AAPL",
    )
    payload = metrics.model_dump(mode="json")
    out = _with_fmp_degradation_note(_request("fmp-key"), payload)
    revalidated = HistoricalMetrics.model_validate(out)
    assert revalidated.data_source == "yfinance"
    assert any("yfinance 降级" in w for w in revalidated.warnings)
