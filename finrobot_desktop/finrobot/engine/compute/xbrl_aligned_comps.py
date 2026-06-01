"""XBRL-aligned peer-company helpers.

These functions keep peer comps deterministic while letting SEC XBRL facts
override yfinance/FMP fields when the standardized fact is available.
"""

from __future__ import annotations

from typing import Any

from finrobot.engine.compute.multiples import calculate_multiples
from finrobot.engine.models.financial import CompanyFinancials, FinancialData


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# Two TTM sources of the SAME caliber — SEC XBRL (concept-selected + structurally
# gated in edgar_provider, ADR-0008) and FMP's ``_build_ttm_data`` (sum of 4
# discrete quarters) — can legitimately differ by up to ~one quarter of timing or
# a restatement. For a fast grower like NVDA a one-quarter offset is ~15%. Beyond
# this tolerance the two disagree materially: either a degenerate XBRL window the
# provider gate failed to catch (this is the second line of defense) or a genuine
# source conflict we must NOT silently resolve. We keep the FMP TTM base and flag
# ``[待核]`` instead of overriding with a possibly-wrong XBRL value — the exact
# failure mode that put NVDA's $10.918B into the comps table.
_TTM_DIVERGENCE_TOLERANCE = 0.35


def _ttm_relative_divergence(a: float, b: float) -> float:
    """Symmetric relative gap ``|a-b| / max(|a|,|b|)``.

    ``abs`` in the denominator makes it sign-aware: a sign flip (e.g. an FY-annual
    +$5.879B masquerading next to a TTM -$6.105B — the 2026-05-28 Ford bug) yields
    a divergence > 1.0 and trips the gate rather than being averaged away.
    """
    scale = max(abs(a), abs(b))
    if scale == 0:
        return 0.0
    return abs(a - b) / scale


def _reconcile_ttm(
    xbrl_value: float | None, fmp_value: float, *, field: str
) -> tuple[float, str | None]:
    """Cross-check a validated XBRL TTM against the trusted FMP TTM base.

    Returns ``(chosen_value, note)``. FMP TTM is the base (a required model field,
    always present); XBRL is adopted as the more authoritative SEC figure ONLY
    when it agrees within ``_TTM_DIVERGENCE_TOLERANCE``. On material divergence we
    keep FMP and return a ``[待核]`` note (surfaced via PeerComps.warnings) instead
    of silently overriding. When XBRL is absent we keep FMP.
    """
    if xbrl_value is None:
        return fmp_value, None
    if _ttm_relative_divergence(xbrl_value, fmp_value) > _TTM_DIVERGENCE_TOLERANCE:
        note = (
            f"[待核] {field}: SEC XBRL TTM ({xbrl_value:,.0f}) diverges "
            f"{_ttm_relative_divergence(xbrl_value, fmp_value):.0%} from FMP TTM "
            f"({fmp_value:,.0f}); kept FMP. Verify against the latest 10-Q."
        )
        return fmp_value, note
    return xbrl_value, None


def _ttm_value(field: Any) -> float | None:
    """Extract the numeric value from an XBRL TTM concept dict.

    ``edgar_provider._fetch_xbrl`` returns ``ttm_revenue`` / ``ttm_net_income``
    as ``{"concept": ..., "value": ..., "periods": [...]}``. The downstream
    overriders need the bare float. Returns None when the field is absent or
    malformed — callers must then **skip** the override rather than fall
    through to ``latest_*``, which is the latest annual snapshot (10-K) and
    on most issuers lags the TTM caliber by 1-2 quarters; mixing FY-annual
    into a peer table built on TTM is the very bug this helper exists to
    prevent.
    """
    if not isinstance(field, dict):
        return None
    return _num(field.get("value"))


def xbrl_concept_snapshot(raw_xbrl: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Return artifact-ready fact lists keyed by us-gaap concept.

    NetIncomeLoss is split into disambiguated keys to avoid two records
    colliding under the same concept:
      - ``us-gaap:NetIncomeLoss:ttm``    ← rolling 4-quarter TTM value+periods
      - ``us-gaap:NetIncomeLoss:annual`` ← latest annual point (float only)
    Revenue is not yet ambiguous (no TTM alt concept clash) so it keeps the
    plain key.  If that changes, apply the same :ttm/:annual suffix pattern.
    """
    snapshot: dict[str, list[dict[str, Any]]] = {}

    # TTM revenue — concept is typically a non-NetIncomeLoss variant, so no
    # collision risk; keep plain concept key.
    ttm_revenue = raw_xbrl.get("ttm_revenue")
    if isinstance(ttm_revenue, dict) and ttm_revenue.get("concept"):
        snapshot.setdefault(str(ttm_revenue["concept"]), []).append(ttm_revenue)

    # TTM net income — use disambiguated key to avoid collision with annual.
    ttm_net_income = raw_xbrl.get("ttm_net_income")
    if isinstance(ttm_net_income, dict) and ttm_net_income.get("concept"):
        ttm_entry = dict(ttm_net_income)
        ttm_entry["concept"] = "us-gaap:NetIncomeLoss:ttm"
        snapshot.setdefault("us-gaap:NetIncomeLoss:ttm", []).append(ttm_entry)

    # Annual (latest period) point values.
    for key, concept in (
        ("latest_revenue", "us-gaap:Revenues"),
        ("latest_gross_profit", "us-gaap:GrossProfit"),
        ("latest_operating_income", "us-gaap:OperatingIncomeLoss"),
        ("latest_total_assets", "us-gaap:Assets"),
        ("latest_total_liabilities", "us-gaap:Liabilities"),
        ("latest_shareholders_equity", "us-gaap:StockholdersEquity"),
    ):
        value = _num(raw_xbrl.get(key))
        if value is not None:
            snapshot.setdefault(concept, []).append({"concept": concept, "value": value})

    # Annual net income — disambiguated key matches the TTM sibling above.
    annual_net_income = _num(raw_xbrl.get("latest_net_income"))
    if annual_net_income is not None:
        snapshot.setdefault("us-gaap:NetIncomeLoss:annual", []).append(
            {"concept": "us-gaap:NetIncomeLoss:annual", "value": annual_net_income}
        )

    return snapshot


def build_xbrl_aligned_company(
    *,
    ticker: str,
    financial_data: FinancialData,
    xbrl_data: dict[str, Any] | None,
) -> CompanyFinancials:
    """Create CompanyFinancials with SEC XBRL overriding core line items.

    XBRL preference order: ``ttm_*`` (rolling 4-quarter, caliber matches
    the FMP TTM that drives the rest of the report) → fall back to the FMP
    snapshot in ``financial_data``. ``latest_*`` (the latest 10-K annual
    point) is deliberately NOT consulted — surfacing FY-annual revenue/NI
    next to TTM EBITDA / TTM EV-multiples is what caused the 2026-05-28
    Ford peer-row P/E hallucination (artifact wrote FY2024 NI $5.879B
    instead of TTM NI -$6.105B and rendered a phantom P/E of 10.6x).
    """
    xbrl_data = xbrl_data or {}
    ttm_rev = _ttm_value(xbrl_data.get("ttm_revenue"))
    ttm_ni = _ttm_value(xbrl_data.get("ttm_net_income"))
    # Cross-check XBRL against the FMP TTM base instead of letting XBRL override
    # unconditionally (ADR-0008). ``_reconcile_ttm`` keeps FMP on material
    # divergence — the structural guard that stops a degenerate XBRL TTM (NVDA's
    # FY2020 $10.918B) from reaching the comps table even if the provider gate
    # missed it. Agreement → adopt the more authoritative SEC figure.
    revenue, rev_note = _reconcile_ttm(ttm_rev, financial_data.income.revenue, field="revenue")
    net_income, ni_note = _reconcile_ttm(
        ttm_ni, financial_data.income.net_income, field="net_income"
    )
    divergence_note = "; ".join(n for n in (rev_note, ni_note) if n) or None
    # income.ebitda is already the operating caliber (extract_financial_data),
    # matching the peer numerator now produced by extract_company_financials.
    ebitda = financial_data.income.ebitda
    gross_margin = financial_data.income.gross_margin
    operating_margin = financial_data.income.operating_margin

    # Preserve the "debt/cash not reported" signal: extract_financial_data leaves
    # valuation.enterprise_value None precisely when a net-debt component was
    # missing (and zero-filled balance.total_debt/total_cash). Passing None here
    # makes the target row withhold EV just like a peer would, instead of
    # comparing an EV=market_cap artifact against debt-aware peers.
    debt_cash_reported = financial_data.valuation.enterprise_value is not None
    total_debt = financial_data.balance.total_debt if debt_cash_reported else None
    total_cash = financial_data.balance.total_cash if debt_cash_reported else None

    company = CompanyFinancials(
        ticker=ticker.upper(),
        revenue=revenue,
        ebitda=ebitda,
        net_income=net_income,
        market_cap=financial_data.market.market_cap,
        total_debt=total_debt,
        total_cash=total_cash,
        gross_margin=gross_margin,
        operating_margin=operating_margin,
        income_tax_expense=financial_data.income.income_tax_expense,
        ttm_divergence_note=divergence_note,
    )
    return calculate_multiples(company)


def override_company_with_xbrl(
    company: CompanyFinancials,
    xbrl_data: dict[str, Any] | None,
) -> CompanyFinancials:
    """Cross-check a peer's FMP TTM against SEC XBRL TTM revenue / net income.

    Peers carry FMP TTM at entry. XBRL — concept-selected + structurally gated in
    the provider (ADR-0008) — is adopted only when it agrees with the FMP base
    within tolerance; on material divergence we keep FMP and tag ``[待核]`` rather
    than overriding (the guard that stops a degenerate XBRL TTM from poisoning a
    peer row). ``latest_*`` (10-K annual) is still never consulted: it lags the
    TTM caliber and silently re-introduces FY-annual numbers into a TTM peer
    table — the path that surfaced Ford's phantom P/E of 10.6x in the 2026-05-28
    TSLA artifact (FY2024 NI $5.879B overrode the real TTM NI of -$6.105B).
    """
    xbrl_data = xbrl_data or {}
    xbrl_revenue = _ttm_value(xbrl_data.get("ttm_revenue"))
    xbrl_net_income = _ttm_value(xbrl_data.get("ttm_net_income"))
    new_revenue, rev_note = _reconcile_ttm(xbrl_revenue, company.revenue, field="revenue")
    new_net_income, ni_note = _reconcile_ttm(
        xbrl_net_income, company.net_income, field="net_income"
    )
    updates: dict[str, Any] = {"revenue": new_revenue, "net_income": new_net_income}
    divergence_note = "; ".join(n for n in (rev_note, ni_note) if n) or None
    if divergence_note is not None:
        updates["ttm_divergence_note"] = divergence_note
    company = company.model_copy(update=updates)
    return calculate_multiples(company)
