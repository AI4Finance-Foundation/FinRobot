"""XBRL-aligned peer-company helpers.

These functions keep peer comps deterministic while letting SEC XBRL facts
override yfinance/FMP fields when the standardized fact is available.
"""

from __future__ import annotations

from typing import Any

from finrobot.engine.compute.coordinators.extractor import normalize_peer_to_usd
from finrobot.engine.compute.operators.multiples import calculate_multiples
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
    xbrl_value: float | None, fmp_value: float | None, *, field: str
) -> tuple[float | None, str | None]:
    """Cross-check a validated XBRL TTM against the trusted FMP TTM base.

    Returns ``(chosen_value, note)``. FMP TTM is the base; XBRL is adopted as the
    more authoritative SEC figure ONLY when it agrees within
    ``_TTM_DIVERGENCE_TOLERANCE``. On material divergence we keep FMP and return a
    ``[待核]`` note (surfaced via PeerComps.warnings) instead of silently
    overriding. When the FMP base is absent (provider omitted the figure) we adopt
    XBRL if present, else leave it unavailable (None). When XBRL is absent we keep FMP.
    """
    if fmp_value is None:
        return xbrl_value, None
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


def _latest_fact_entry(field: Any) -> dict[str, Any] | None:
    """Normalize a provider ``latest_*`` payload into a snapshot record.

    ``edgar_provider._select_latest_fact`` returns ``{concept, value, period_end,
    units}`` (the REAL matched us-gaap concept — BUG-009). We preserve every key
    so the artifact snapshot carries the true SEC provenance, not a hardcoded
    label. Legacy bare floats (or anything without a concept+value) are rejected
    rather than re-tagged with a guessed concept.
    """
    if not isinstance(field, dict):
        return None
    concept = field.get("concept")
    value = _num(field.get("value"))
    if not concept or value is None:
        return None
    entry = dict(field)
    entry["value"] = value
    return entry


def xbrl_concept_snapshot(raw_xbrl: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Return artifact-ready fact lists keyed by us-gaap concept.

    Every record carries the REAL matched concept the provider recovered from
    edgartools (BUG-009): a post-ASC-606 issuer's revenue is keyed under
    ``us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax``, not a
    hardcoded ``us-gaap:Revenues`` — so the SEC concept the LLM sees is honest.

    NetIncomeLoss is split into disambiguated keys to avoid two records
    colliding under the same concept:
      - ``us-gaap:NetIncomeLoss:ttm``    ← rolling 4-quarter TTM value+periods
      - ``us-gaap:NetIncomeLoss:annual`` ← latest annual point
    """
    snapshot: dict[str, list[dict[str, Any]]] = {}

    # TTM revenue — concept is typically a non-NetIncomeLoss variant, so no
    # collision risk; keep the provider's real concept key.
    ttm_revenue = raw_xbrl.get("ttm_revenue")
    if isinstance(ttm_revenue, dict) and ttm_revenue.get("concept"):
        snapshot.setdefault(str(ttm_revenue["concept"]), []).append(ttm_revenue)

    # TTM net income — use disambiguated key to avoid collision with annual.
    ttm_net_income = raw_xbrl.get("ttm_net_income")
    if isinstance(ttm_net_income, dict) and ttm_net_income.get("concept"):
        ttm_entry = dict(ttm_net_income)
        ttm_entry["concept"] = "us-gaap:NetIncomeLoss:ttm"
        snapshot.setdefault("us-gaap:NetIncomeLoss:ttm", []).append(ttm_entry)

    # Annual (latest period) point values — keyed by the provider's real concept.
    for key in (
        "latest_revenue",
        "latest_gross_profit",
        "latest_operating_income",
        "latest_total_assets",
        "latest_total_liabilities",
        "latest_shareholders_equity",
    ):
        entry = _latest_fact_entry(raw_xbrl.get(key))
        if entry is not None:
            snapshot.setdefault(str(entry["concept"]), []).append(entry)

    # Annual net income — disambiguated key matches the TTM sibling above. The
    # real concept is preserved inside the record (provenance field) while the
    # snapshot KEY stays the stable :annual suffix so it never collides with the
    # TTM record under the same us-gaap concept.
    annual_ni = _latest_fact_entry(raw_xbrl.get("latest_net_income"))
    if annual_ni is not None:
        annual_ni["matched_concept"] = annual_ni["concept"]
        annual_ni["concept"] = "us-gaap:NetIncomeLoss:annual"
        snapshot.setdefault("us-gaap:NetIncomeLoss:annual", []).append(annual_ni)

    return snapshot


async def build_xbrl_aligned_company(
    *,
    ticker: str,
    financial_data: FinancialData,
    xbrl_data: dict[str, Any] | None,
    fmp_api_key: str | None = None,
) -> CompanyFinancials:
    """Create the comps target CompanyFinancials, FX-normalized then XBRL-aligned.

    Runs the SAME recipe as a peer row (``_helpers._fetch_one_peer``) so the
    target and peers are produced by one path, never two:

      1. Build the FMP-base row from ``financial_data`` in its reported currency.
      2. ``normalize_peer_to_usd`` → canonical USD BEFORE any multiple, so a
         foreign-listed target (TSM: TWD financials, USD market_cap) doesn't
         collapse core_pe the way an un-normalized peer collapses EV/EBITDA to
         0.158x (BUG-018). US targets hit the no-op FX fast path.
      3. ``override_company_with_xbrl`` cross-checks the now-USD base against SEC
         XBRL TTM (ADR-0008): adopt XBRL only within tolerance, else keep FMP and
         flag ``[待核]``; ``latest_*`` (10-K annual) is never consulted — that is
         the path that surfaced Ford's phantom P/E of 10.6x (FY2024 NI $5.879B
         over the real TTM NI -$6.105B).
    """
    # income.ebitda is already the operating caliber (extract_financial_data),
    # matching the peer numerator produced by extract_company_financials.
    #
    # Preserve the "debt/cash not reported" signal: balance.total_debt/total_cash
    # are now None (not 0) when unreported, in lockstep with
    # valuation.enterprise_value. Withhold EV for the target row just like a peer
    # would, instead of comparing an EV=market_cap artifact against debt-aware
    # peers.
    debt_cash_reported = (
        financial_data.balance.total_debt is not None
        and financial_data.balance.total_cash is not None
    )
    # Target P/B = market_cap / (bvps × shares), single-currency only (reporting ==
    # quote) and book > 0 — the same gate the peer path (extract_company_financials)
    # applies, so the target row's pb_ratio is currency-clean and comparable to the
    # peer medians. None for an ADR / non-positive book → P/B method falls back.
    bvps = financial_data.valuation.book_value_per_share
    shares = financial_data.market.shares_outstanding
    mcap = financial_data.market.market_cap
    target_pb: float | None = None
    if (
        financial_data.reporting_currency == financial_data.quote_currency
        and bvps is not None
        and bvps > 0
        and shares > 0
        and mcap > 0
    ):
        target_pb = mcap / (bvps * shares)
    base = CompanyFinancials(
        ticker=ticker.upper(),
        revenue=financial_data.income.revenue,
        ebitda=financial_data.income.ebitda,
        net_income=financial_data.income.net_income,
        market_cap=financial_data.market.market_cap,
        total_debt=financial_data.balance.total_debt if debt_cash_reported else None,
        total_cash=financial_data.balance.total_cash if debt_cash_reported else None,
        # EV-bridge completeness: preferred + NCI fold into this peer's EV when its
        # debt/cash are present (calculate_multiples). Not gated on debt_cash_reported
        # — they only contribute inside that EV branch anyway. None ≠ 0.
        preferred_stock=financial_data.balance.preferred_stock,
        noncontrolling_interest=financial_data.balance.noncontrolling_interest,
        gross_margin=financial_data.income.gross_margin,
        operating_margin=financial_data.income.operating_margin,
        # Period-consistent EBIT for core_pe — immune to the XBRL revenue
        # reconcile below (BUG-017).
        operating_income=financial_data.income.operating_income,
        income_tax_expense=financial_data.income.income_tax_expense,
        # Cyclical comps P/B: bvps (reporting-ccy, FX-scaled by normalize_peer_to_usd)
        # + the single-currency pb_ratio computed above. calculate_multiples (called
        # inside override_company_with_xbrl) sanity-gates pb_ratio.
        book_value_per_share=bvps,
        pb_ratio=target_pb,
        reporting_currency=financial_data.reporting_currency,
        quote_currency=financial_data.quote_currency,
    )
    base = await normalize_peer_to_usd(base, fmp_api_key=fmp_api_key)
    return override_company_with_xbrl(base, xbrl_data)


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
