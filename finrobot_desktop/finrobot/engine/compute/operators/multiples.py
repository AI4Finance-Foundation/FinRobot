import math
from statistics import median, mean
from finrobot.engine.models.financial import CompanyFinancials, FinancialData, PeerComps


# Sanity bounds for peer multiples — a garbage filter, not a "meaningfulness"
# filter. The lower bounds catch currency-unit-mismatch artifacts (yfinance
# returning a foreign-listed ADR's EBITDA in local currency — TWD for TSM,
# EUR for ASML, JPY for Toyota — while market_cap comes through in USD,
# collapsing the ratio to sub-1x fractions). The upper bounds catch
# divide-by-near-zero garbage where EBITDA has already collapsed to a sliver.
#
# EV/EBITDA range rationale (0.5x – 300x): Damodaran (Investment Valuation,
# 3e, Ch.7; data.stern.nyu.edu industry trailing EV/EBITDA, updated annually)
# shows cyclical-trough sectors (shipping, steel, autos, oil services) reach
# 3-5x in genuine downturns; CFA Institute Equity Asset Valuation 4e Ch.7
# documents true sub-3x prints during 2008-09 and 2020 COVID-trough quarters
# but no credible sustained sub-1x outside of unit-conversion errors. We
# extend the floor to 0.5x as a conservative buffer for one-off distressed
# quarters; sub-0.5x is taken as evidence of FX / unit mismatch and dropped.
#
# EV/Revenue range rationale (0.1x – 100x): sub-0.1x is implausible for any
# publicly listed company — it implies market cap barely covers one month of
# revenue and is a reliable FX-mismatch signal. Upper 100x accommodates
# high-growth SaaS/biotech with near-zero revenue.
#
# P/E range rationale (1.0x – 300x): sub-1x P/E means the market prices the
# company at less than one year of earnings — never observed for a healthy
# going-concern (value traps typically trade 3-5x). Upper 300x covers extreme
# growth premiums (AMZN 2020 ~80x TTM; speculative prints can briefly exceed).
#
# Live evidence: artifact ``art_2026-05-27T09:29:31_NVDA_equity_research``
# surfaced TSM at EV/EBITDA=0.158x, PE=1.85 — exactly the failure mode this
# guards against.
#
# Both the compute layer (this module) and the pipeline validator
# (``validate_peer_comps``) reference the same constants so the two layers
# can never drift out of alignment. Compute returns None below the floor so
# ``calculate_peer_statistics`` excludes the row from median/mean.
PEER_EV_EBITDA_SANITY_MIN: float = 0.5
PEER_EV_EBITDA_SANITY_MAX: float = 300.0
PEER_EV_REVENUE_SANITY_MIN: float = 0.1
PEER_EV_REVENUE_SANITY_MAX: float = 100.0
PEER_PE_SANITY_MIN: float = 1.0
PEER_PE_SANITY_MAX: float = 300.0
# Price-to-book sanity band (the cyclical-comps multiple). Book equity is far more
# stable than cycle EPS, but a negative book (accumulated deficit / buyback-driven
# negative equity) makes P/B meaningless — so P/B is withheld (None) when book
# value ≤ 0, never computed as a negative ratio. Positive band [0.1x, 50x]: below
# 0.1x is a unit/FX artifact; above 50x is effectively a no-tangible-book firm
# whose P/B carries no value信息 (memory/storage peers run ~1–8x). Excluded from
# the median when out of band, same as the other multiples.
PEER_PB_SANITY_MIN: float = 0.1
PEER_PB_SANITY_MAX: float = 50.0

# Not-meaningful (NM) P/E cap — the BANKER-CONVENTION threshold, distinct from the
# garbage/FX SANITY bounds above. A positive P/E above this is a real, computable
# number (not an FX artifact, so it stays on the peer's row and ships in the comp
# table for the competitive landscape) but carries no information about what a
# mature target's earnings are worth: a 156x trailing print is a temporary earnings
# trough, a 157x forward print is hyper-growth optionality. Such a multiple must
# therefore be excluded from the MEDIAN — the number that drives comps_pe — while
# the company stays in the SET. This is the touch-5 identity/multiple decoupling:
# peer_screen's MEMBER gate widened to pe>0 (loss-makers still out, AMD's 156x
# trailing now IN the set), and the NM cap moved here to the MEDIAN computation.
#
# Threshold calibration (live FMP, 2026-06-06, NVDA semiconductor universe):
#   forward P/E ladder — AVGO 31.8, MU 14.5, TXN 36.9, AMD 62.5, MRVL 66.8 |  INTC
#   91.8, ARM 157.2. The informative direct competitors (incl. AMD, the textbook
#   NVDA comp whose 156x TRAILING masked a 62.5x FORWARD) all sit below 75; the two
#   distorting names — INTC (loss-recovery turnaround, forward NI just turned
#   positive) and ARM (hyper-growth) — sit above. 75 cleanly separates the two
#   populations, so the same cap governs the trailing median, the core median, and
#   the forward median. (The standalone validator's per-peer [1,300] SANITY check
#   is a separate garbage/FX gate — AMD's 156x trailing is a sane number that
#   passes it and stays on the row, only the NM cap keeps it out of the median.)
PEER_PE_NM_CAP: float = 75.0

# Not-meaningful (NM) EV/EBITDA cap — the structural analog of PEER_PE_NM_CAP for the
# enterprise multiple. For a low-debt issuer EV/EBITDA ≈ 0.67 × P/E (EV ≈ equity value,
# EBITDA ≈ a pre-tax/pre-D&A proxy for earnings), so the 75x P/E cap maps to ≈ 50x here
# (75 × 0.67 ≈ 50). On the live basket 50 sits in the natural gap between premium-but-
# real multiples (SNPS 43.4x, AVGO 45.1x — all ≤ ~45) and genuine hyper-growth /
# sliver-EBITDA NM prints (TSEM 57.1x, AMD 106.7x, PANW 109.6x, PLTR 141.8x — all >
# ~55); any cap in [46, 57) yields identical exclusions on that basket, so 50 is the
# robust mid-gap choice. A multiple above it is still a real, computable number (it
# stays on the peer's row and ships in the comp table for the competitive landscape)
# but a tiny-EBITDA denominator makes it carry no information about what a mature
# target's cash flows are worth, so it must be excluded from the MEDIAN — the same
# SET-vs-MEDIAN decoupling the P/E cap applies.
PEER_EV_EBITDA_NM_CAP: float = 50.0

# NOPAT core-earnings effective-tax band. Own rates outside this are degenerate
# (tax holidays, credit/DTA releases — observed live: AMD 0.2%, AVGO 1.8% in the
# NVDA peer set) and would distort NOPAT comparability, so such rows fall back to
# the peer-set median in-band rate. If the whole set is degenerate, the US
# federal statutory 21% is the last resort.
CORE_TAX_RATE_MIN: float = 0.05
CORE_TAX_RATE_MAX: float = 0.35
CORE_TAX_RATE_FALLBACK: float = 0.21


def _sanity(value: float | None, lo: float, hi: float) -> float | None:
    """Return ``value`` if it falls within ``[lo, hi]``, else None.

    None input propagates as None (not-meaningful rather than range-violation).
    Used by ``calculate_multiples`` to gate each ratio independently.

    Non-finite (NaN/Inf) is rejected explicitly: ``NaN < lo`` and ``NaN > hi``
    are both False, so without this the garbage gate would pass the worst
    garbage it exists to catch straight into the peer medians.
    """
    if value is None or not math.isfinite(value) or value < lo or value > hi:
        return None
    return value


def calculate_ev(
    market_cap: float,
    total_debt: float,
    cash: float,
    preferred: float = 0.0,
    noncontrolling_interest: float = 0.0,
) -> float:
    """Enterprise Value = Market Cap + Total Debt + Preferred + NCI − Cash.

    The full EV bridge (Damodaran / CFA): preferred equity and noncontrolling
    (minority) interest are claims on the enterprise alongside / senior to common,
    so they belong in EV. The net-debt-only ``mc + debt − cash`` understates EV —
    and EV/EBITDA, EV/Revenue — for any issuer carrying them, invisibly to the
    identity which still closes to the dollar (live 2026-06-08: KO NCI 2.10B =
    0.56% of EV, SAP 0.28%). ``preferred``/``noncontrolling_interest`` default to
    0.0 so a caller without those components (or a pref=NCI=0 issuer) gets the
    net-debt special case unchanged.
    """
    return market_cap + total_debt - cash + preferred + noncontrolling_interest


def current_ev_ebitda(financial_data: FinancialData, net_debt: float) -> float | None:
    """Canonical current EV/EBITDA on TTM EBITDA — the single authoritative
    "current EV/EBITDA" every surface consumes: the report's comps target
    multiple, the technical chapter's historical-band ``current_override``, and
    the standalone ``GET /api/valuation/historical-bands`` route.

    EV = market_cap + net_debt + preferred + NCI — the full bridge ``calculate_ev``
    encodes, with ``net_debt`` already collapsed to total_debt − cash and the
    preferred/NCI components read off ``financial_data.balance``; divided by TTM
    EBITDA. Returns None when market_cap or TTM EBITDA is missing or
    non-positive: the caller then lets the historical band fall back to its
    trailing-annual basis (which discloses the口径). Routing every surface
    through this one function is what stops the route and the report from
    reporting two different "current EV/EBITDA" for the same ticker — the
    TTM-vs-annual signal flip (W1-C2). Canonical financials are single-currency
    at this point (FX normalised at the data chokepoint), so market_cap and
    EBITDA share a currency and the ratio is well-posed.

    The result passes through the SAME ``_sanity`` gate as the peer-comps path
    ([PEER_EV_EBITDA_SANITY_MIN, PEER_EV_EBITDA_SANITY_MAX]): a sub-0.5x or
    300x+ print — or a NaN net_debt component leaking through — is unit/FX/
    caliber garbage, and the single authoritative "current EV/EBITDA" must not
    be the one surface exempt from the garbage filter every peer row passes.
    Out-of-band → None → the caller's disclosed trailing-annual fallback.
    """
    market = getattr(financial_data, "market", None)
    income = getattr(financial_data, "income", None)
    balance = getattr(financial_data, "balance", None)
    market_cap = getattr(market, "market_cap", None) if market is not None else None
    ebitda = getattr(income, "ebitda", None) if income is not None else None
    if market_cap is None or ebitda is None:
        return None
    market_cap = float(market_cap)
    ebitda = float(ebitda)
    if market_cap <= 0 or ebitda <= 0:
        return None
    # EV-bridge completeness: preferred + NCI belong in EV (see calculate_ev). They
    # are read off the balance sheet the caller already passes; a None component
    # ("not carried") contributes 0 — the pref=NCI=0 case reduces to mc + net_debt.
    preferred = 0.0
    nci = 0.0
    if balance is not None:
        preferred = getattr(balance, "preferred_stock", None) or 0.0
        nci = getattr(balance, "noncontrolling_interest", None) or 0.0
    return _sanity(
        (market_cap + net_debt + preferred + nci) / ebitda,
        PEER_EV_EBITDA_SANITY_MIN,
        PEER_EV_EBITDA_SANITY_MAX,
    )


def compute_ttm_fcf(
    operating_cash_flow: float | None,
    capital_expenditure: float | None,
) -> float | None:
    """Trailing-12M free cash flow = OCF − CapEx (levered FCF).

    The analyst-standard *actual* cash figure (not a DCF projection): OCF already
    embeds working-capital swings, stock-comp add-backs and deferred taxes, so
    OCF − CapEx is more accurate than the textbook EBIT(1−t)+D&A−CapEx−ΔNWC
    approximation and exactly reproduces FMP's own reported freeCashFlow
    (verified live on AAPL TTM: OCF 140.2B − CapEx 11.0B = 129.2B).

    ``capital_expenditure`` is a positive magnitude (the provider sign-flip is
    normalised upstream). Returns None when either component is unavailable so
    the cashflow analysis cites a real number or explicitly says N/A — never an
    LLM-fabricated estimate (CLAUDE.md red-line 3).
    """
    if operating_cash_flow is None or capital_expenditure is None:
        return None
    result = operating_cash_flow - capital_expenditure
    # A NaN/Inf component (e.g. a corrupt provider row) must surface as N/A, not a
    # non-finite "cash figure" the cashflow analysis would then quote.
    return result if math.isfinite(result) else None


def fcf_yield(fcf: float | None, market_cap: float | None) -> float | None:
    """FCF yield = TTM FCF / market cap. None when either input is missing/≤0.

    ``not market_cap`` / ``market_cap <= 0`` are both False for NaN, so finiteness
    is checked explicitly — a NaN/Inf yield must never reach the screen.
    """
    if fcf is None or not market_cap or market_cap <= 0:
        return None
    if not math.isfinite(fcf) or not math.isfinite(market_cap):
        return None
    return fcf / market_cap


def calculate_multiples(company: CompanyFinancials) -> CompanyFinancials:
    """Compute EV/EBITDA, EV/Revenue, P/E for a single company.

    Uses company.total_debt and company.total_cash for EV calculation.
    Returns a new copy with computed fields set (input is not mutated).

    All three ratios are gated through ``_sanity`` with the published bounds:
    - EV/EBITDA: [0.5x, 300x]
    - EV/Revenue: [0.1x, 100x]
    - P/E: [1.0x, 300x]

    Values outside these bounds are returned as None so that
    ``calculate_peer_statistics`` excludes them from median/mean. Each such drop
    is recorded on ``result.sanity_drops`` (a multiple that HAD computable inputs
    but fell out of band) so ``validate_peer_comps`` can surface the thinned set
    instead of silently producing a smaller median — the old range check there
    could never fire, because the values it tested had already been nulled here.
    """
    result = company.model_copy(deep=True)
    # Idempotent: drops are recomputed from this call's gating, not accumulated
    # across copies.
    result.sanity_drops = []

    def _gate(label: str, raw: float | None, lo: float, hi: float) -> float | None:
        gated = _sanity(raw, lo, hi)
        if raw is not None and gated is None:
            result.sanity_drops.append(
                f"{label} {raw:.2f}x outside sanity bounds [{lo:g}, {hi:g}]x — "
                f"excluded from peer medians (likely unit / FX / caliber artifact)"
            )
        return gated

    # EV (and the EV-based multiples) only when BOTH net-debt components are
    # reported. A missing total_debt/total_cash leaves EV undefined rather than
    # assuming zero — mirrors extract_financial_data's target path and keeps a
    # debt/cash-less peer out of the EV/EBITDA and EV/Revenue medians instead of
    # contributing an EV=market_cap artifact.
    if result.total_debt is not None and result.total_cash is not None:
        ev = calculate_ev(
            result.market_cap,
            result.total_debt,
            result.total_cash,
            result.preferred_stock or 0.0,
            result.noncontrolling_interest or 0.0,
        )
        result.enterprise_value = ev

        raw_ev_ebitda = (
            ev / result.ebitda if result.ebitda is not None and result.ebitda > 0 else None
        )
        result.ev_ebitda = _gate(
            "EV/EBITDA", raw_ev_ebitda, PEER_EV_EBITDA_SANITY_MIN, PEER_EV_EBITDA_SANITY_MAX
        )

        raw_ev_revenue = ev / result.revenue if result.revenue > 0 else None
        result.ev_revenue = _gate(
            "EV/Revenue", raw_ev_revenue, PEER_EV_REVENUE_SANITY_MIN, PEER_EV_REVENUE_SANITY_MAX
        )
    else:
        result.enterprise_value = None
        result.ev_ebitda = None
        result.ev_revenue = None

    # P/E is equity-only and independent of net debt, so it survives a missing
    # balance sheet.
    raw_pe = (
        result.market_cap / result.net_income
        if result.net_income is not None and result.net_income > 0
        else None
    )
    result.pe_ratio = _gate("P/E", raw_pe, PEER_PE_SANITY_MIN, PEER_PE_SANITY_MAX)

    # P/B (cyclical comps multiple): pb_ratio was computed single-currency in
    # extract_company_financials (None for ADRs / non-positive book), so here it
    # only passes the sanity gate — an out-of-band P/B is nulled and recorded so it
    # never silently shrinks the median, symmetric with the other multiples.
    result.pb_ratio = _gate("P/B", result.pb_ratio, PEER_PB_SANITY_MIN, PEER_PB_SANITY_MAX)

    return result


def _effective_tax_rate(net_income: float | None, income_tax_expense: float | None) -> float | None:
    """Own effective tax rate = tax / pretax, where pretax = net_income + tax.

    Returns None when net income or tax is unreported, or pretax ≤ 0 (loss-maker
    or degenerate), so the caller falls back to the peer-set median rate.
    """
    if net_income is None or income_tax_expense is None:
        return None
    pretax = net_income + income_tax_expense
    if pretax <= 0:
        return None
    return income_tax_expense / pretax


def calculate_core_pe(comps: PeerComps) -> PeerComps:
    """Compute the NOPAT core P/E for target + every peer, plus the peer median.

    P/E comparability requires one earnings caliber across the set. As-reported
    net income mixes in non-operating items that differ company-to-company —
    NVDA's TTM investment gains (~$27B), AMD/AVGO near-zero effective tax — so
    raw P/E compares apples to oranges. Core earnings normalise to after-tax
    operating profit:

        NOPAT = EBIT × (1 − t),   EBIT = operating_income (period-consistent;
                                  falls back to operating_margin × revenue)

    where ``t`` is each company's own effective rate when it falls in
    ``[CORE_TAX_RATE_MIN, CORE_TAX_RATE_MAX]``, else the peer-set median in-band
    rate (so one company's tax holiday can't distort the comp), else 21%
    statutory. ``core_pe = market_cap / NOPAT`` is gated by the same P/E sanity
    bounds as the as-reported ratio. Returns a new copy; input is not mutated.

    When the *target's* own rate is substituted (out of band or unreported), a
    warning is appended to ``warnings`` so the substitution that shapes the
    target's NOPAT — and thus the comps_pe price — is visible (BUG-049).
    """
    result = comps.model_copy(deep=True)

    # Pass 1 — peer-set median in-band rate, the fallback for degenerate rows.
    peer_rates = [
        r
        for p in result.peers
        if (r := _effective_tax_rate(p.net_income, p.income_tax_expense)) is not None
        and CORE_TAX_RATE_MIN <= r <= CORE_TAX_RATE_MAX
    ]
    fallback_rate = median(peer_rates) if peer_rates else CORE_TAX_RATE_FALLBACK

    # Pass 2 — assign each row its rate, NOPAT, and core P/E.
    def _apply(c: CompanyFinancials, *, is_target: bool = False) -> None:
        own = _effective_tax_rate(c.net_income, c.income_tax_expense)
        in_band = own is not None and CORE_TAX_RATE_MIN <= own <= CORE_TAX_RATE_MAX
        rate = own if (own is not None and in_band) else fallback_rate
        c.effective_tax_rate = rate
        # EBIT prefers the absolute operating_income (period-consistent with the
        # FMP base) over operating_margin × revenue: once revenue may be
        # XBRL-TTM-reconciled (override_company_with_xbrl), margin(FMP) ×
        # revenue(XBRL) mixes periods and lifts EBIT by the override divergence
        # (BUG-017). Fall back to margin × revenue only when operating_income is
        # absent; withhold (None) when neither is available rather than fabricate.
        if c.operating_income is not None:
            ebit = c.operating_income
        elif c.operating_margin is not None:
            ebit = c.operating_margin * c.revenue
        else:
            c.core_net_income = None
            c.core_pe_ratio = None
            return
        # When the target's own tax is out of band, its NOPAT (hence the comps_pe
        # target price) is built on a substitute rate, not the reported tax. The
        # substitution is a defensible normalisation, but it must be visible —
        # surface it so the user can judge whether the substitute caliber is fair
        # for this company (e.g. a real DTA-driven low-tax period; BUG-049).
        if is_target and not in_band:
            if own is not None:
                result.warnings.append(
                    f"Target effective tax rate {own:.1%} outside the core band "
                    f"[{CORE_TAX_RATE_MIN:.0%}, {CORE_TAX_RATE_MAX:.0%}]; "
                    f"core P/E uses substitute rate {rate:.1%}"
                )
            else:
                result.warnings.append(
                    f"Target effective tax rate unavailable; "
                    f"core P/E uses substitute rate {rate:.1%}"
                )
        nopat = ebit * (1 - rate)
        c.core_net_income = nopat
        c.core_pe_ratio = _sanity(
            c.market_cap / nopat if nopat > 0 else None,
            PEER_PE_SANITY_MIN,
            PEER_PE_SANITY_MAX,
        )

    _apply(result.target, is_target=True)
    for peer in result.peers:
        _apply(peer)

    # Same NM cap as the trailing/forward medians: a peer kept in the set for the
    # competitive landscape (widened member gate) whose core P/E is real but
    # distorting (> NM cap) must not skew the core median that feeds the trailing
    # comps_pe path. Loss-makers already produced core_pe_ratio None above.
    core_vals = [
        p.core_pe_ratio
        for p in result.peers
        if p.core_pe_ratio is not None and p.core_pe_ratio <= PEER_PE_NM_CAP
    ]
    result.median_core_pe = median(core_vals) if core_vals else None
    result.core_pe_sample_n = len(core_vals)
    return result


def calculate_peer_statistics(comps: PeerComps) -> PeerComps:
    """Compute median and mean multiples across the peer set.

    Returns a new copy with statistics set (input is not mutated).
    Ignores None values. Guards against empty list before calling statistics.median/mean.

    Appends a sample-size warning to ``result.warnings`` for each multiple
    where one or more peers were excluded due to None (data-quality drop).
    Callers and the pipeline validator surface these so operators see the
    effective sample size rather than assuming all peers contributed.
    """
    result = comps.model_copy(deep=True)
    total = len(result.peers)

    # `is not None` alone admits a NaN multiple (one corrupt peer poisons the
    # whole median); the pe / forward_pe lists are already NaN-safe via their
    # band bounds, so finiteness only needs adding to the two range-free lists.
    # Trailing EV/EBITDA median applies the NM cap (not just the upstream SANITY
    # floor), exactly as the trailing P/E median does: a real, computable multiple
    # above PEER_EV_EBITDA_NM_CAP is a hyper-growth / sliver-EBITDA peer (PLTR, PANW)
    # that says nothing about a mature target's worth, so it must not skew the median
    # that feeds the comp display and the thesis prompt. The peer stays IN the set for
    # the competitive landscape; only its median contribution is NM. (finiteness is
    # still load-bearing: −Inf < cap would otherwise slip past the upper bound.)
    ev_ebitda_vals = [
        p.ev_ebitda
        for p in result.peers
        if p.ev_ebitda is not None
        and math.isfinite(p.ev_ebitda)
        and p.ev_ebitda <= PEER_EV_EBITDA_NM_CAP
    ]
    # Trailing P/E median applies the NM cap (not just the SANITY floor): with the
    # touch-5 widened member gate a real-but-distorting trailing print (AMD 156x)
    # now sits IN the set and on the peer row, but it carries no information about
    # fair value, so it must not skew the trailing median that feeds comps_pe. The
    # peer stays for the competitive landscape; only its median contribution is NM.
    pe_vals = [
        p.pe_ratio
        for p in result.peers
        if p.pe_ratio is not None and PEER_PE_SANITY_MIN <= p.pe_ratio <= PEER_PE_NM_CAP
    ]
    ev_revenue_vals = [
        p.ev_revenue
        for p in result.peers
        if p.ev_revenue is not None and math.isfinite(p.ev_revenue)
    ]

    # Forward P/E median uses the SAME NM cap: AMD's 62.5x forward is informative
    # and stays in; INTC's 91.8x (turnaround) and ARM's 157x (hyper-growth) are NM.
    # A peer keeps its raw forward_pe for display; only the median excludes them.
    forward_pe_vals = [
        p.forward_pe
        for p in result.peers
        if p.forward_pe is not None and PEER_PE_SANITY_MIN <= p.forward_pe <= PEER_PE_NM_CAP
    ]

    # P/B median (cyclical comps): already sanity-gated in calculate_multiples, so
    # only finiteness needs re-checking here. A short-history cyclical (SNDK: 1y)
    # MAY contribute its P/B — book value is a current balance-sheet figure, not a
    # through-cycle series, so the 1y-history exclusion that applies to through-cycle
    # medians does NOT apply to P/B.
    pb_vals = [
        p.pb_ratio for p in result.peers if p.pb_ratio is not None and math.isfinite(p.pb_ratio)
    ]

    result.median_ev_ebitda = median(ev_ebitda_vals) if ev_ebitda_vals else None
    result.mean_ev_ebitda = mean(ev_ebitda_vals) if ev_ebitda_vals else None
    result.median_pe = median(pe_vals) if pe_vals else None
    result.mean_pe = mean(pe_vals) if pe_vals else None
    result.median_ev_revenue = median(ev_revenue_vals) if ev_revenue_vals else None
    result.median_forward_pe = median(forward_pe_vals) if forward_pe_vals else None
    result.median_pb = median(pb_vals) if pb_vals else None
    result.pe_sample_n = len(pe_vals)
    result.forward_pe_sample_n = len(forward_pe_vals)
    result.pb_sample_n = len(pb_vals)

    ev_ebitda_n = len(ev_ebitda_vals)
    if ev_ebitda_n < total:
        result.warnings.append(
            f"EV/EBITDA based on {ev_ebitda_n} of {total} peers"
            f" — {total - ev_ebitda_n} excluded (data quality, or an NM EV/EBITDA above"
            f" {PEER_EV_EBITDA_NM_CAP:.0f}x — kept in the set, out of the median)"
        )
    pe_n = len(pe_vals)
    if pe_n < total:
        result.warnings.append(
            f"P/E based on {pe_n} of {total} peers"
            f" — {total - pe_n} excluded (loss-making, or an NM trailing P/E above"
            f" {PEER_PE_NM_CAP:.0f}x — kept in the set, out of the median)"
        )
    ev_revenue_n = len(ev_revenue_vals)
    if ev_revenue_n < total:
        result.warnings.append(
            f"EV/Revenue based on {ev_revenue_n} of {total} peers"
            f" — {total - ev_revenue_n} dropped for data quality"
        )
    # Forward is legitimately sparse (foreign peers + names without analyst
    # consensus carry no forward P/E), so warn only when SOME but not all peers
    # contributed — a fully-absent forward set is the normal degraded path, not a
    # data-quality drop worth flagging.
    forward_pe_n = len(forward_pe_vals)
    if 0 < forward_pe_n < total:
        result.warnings.append(
            f"Forward P/E based on {forward_pe_n} of {total} peers"
            f" — {total - forward_pe_n} without USD-denominated analyst consensus, or"
            f" with an NM forward P/E above {PEER_PE_NM_CAP:.0f}x (kept in the set,"
            f" out of the median)"
        )

    return result
