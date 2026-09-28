"""Aggregate target-price ranges across 4 valuation methods + 2 multiple reverses.

Powers ``GET /api/valuation/aggregate/{ticker}`` (the Football Field section in
v5 §6.4). Pure leaf-layer: takes already-fetched pipeline artifacts plus a few
numeric inputs, returns ``ValuationAggregate``. No provider SDKs, no LLM, no
upper-layer imports.

The hardest correctness rule is §6.4.2: **never re-run a full LBO sweep here.**
We reuse the entry × exit IRR/MOIC grid the LBO pipeline already saved on
``LBOResult.sensitivity`` and post-process it into a target-price band via a
single 5×5 division loop. Running ``calculate_lbo`` once per (entry, exit) cell
would 25× the cost of the endpoint with zero accuracy benefit.

EV/EBITDA and P/FCF rows are *multiple* methods — they reverse-engineer a band
from the company's own multi-year multiple distribution (P25/P75) times a profit
number. EV/EBITDA is a single-caliber RE-RATING ANCHOR: the band (own 5y trailing
EV/EBITDA multiples, ``historical_loaders.fetch_reverse_multiple_band``, threaded
in as ``historical_ev_ebitda_band``) is applied to the target's CURRENT TTM
operating EBITDA (``FinancialData.income.ebitda`` = OI + D&A — the SAME caliber the
trailing band is built on, so no forward/trailing caliber mix; the row no longer
rides on the FMP forward consensus). It fires whenever that band + a TTM EBITDA +
current net debt are all present (net debt stays None≠0-gated — a missing figure
hides the row rather than fabricating a debt-free bridge). The anchor gives no
forward-growth credit and is therefore conservative for a growth name — disclosed
on the method row. P/FCF stays omitted: FMP /analyst-estimates carries no
free-cash-flow figure, so ``forward_fcf`` is always None and band-wiring alone
cannot honestly revive it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any, Final

from finrobot.engine.models.financial import (
    DCFResult,
    DDMResult,
    LBOResult,
    PeerComps,
    RIResult,
    ValuationAggregate,
    ValuationMethodRange,
)
from finrobot.engine.models.valuation_thresholds import SPONSOR_IRR_HURDLE

_DCF_BAND_WIDTH = 0.20
"""Default ±20% band around DCFResult.implied_price when monte carlo is absent.

The DCF pipeline today does not persist a P10–P90 monte-carlo range on
DCFResult, so we approximate the implied band with the same ±20% rule used
historically by build_valuation_synthesis. When monte carlo lands the
``low`` / ``high`` come from real P10 / P90 percentiles.
"""

_DDM_BAND_WIDTH = 0.15
_RI_BAND_WIDTH = 0.15
"""Tighter band for DDM — dividend streams are less volatile than FCF."""

_COMPS_PE_BAND_WIDTH = 0.10
"""±1 std proxy when peer-PE std isn't recorded (PeerComps lacks std today)."""

_COMPS_PB_BAND_WIDTH = 0.15
"""P/B band — book equity is cycle-stable but the peer P/B dispersion across a
memory/storage cohort is wider than the trailing-P/E dispersion (re-rating during
the up-cycle), so a slightly wider placeholder spread than comps_pe."""

# Insurer comps ROE adjustment (2026-07-06). A flat peer-median P/B grants no quality
# premium, so it under-prices a high-ROE insurer and over-prices a low-ROE one (justified
# P/B ∝ ROE). We scale the median P/B by target/peer THROUGH-CYCLE ROE (own-history mean,
# so an underwriting-cycle peak doesn't inflate it), NOT residual income — a structurally
# low insurer beta (0.2-0.5) makes the RI/justified-P/B Gordon denominator (CoE−g) tiny and
# the value explode (PGR 8.5x vs market 4.5x); the peer group already embeds the sector CoE.
_TCROE_MIN_YEARS: Final[int] = 5
"""Minimum valid (positive-book) years to trust a through-cycle ROE mean; below this the
window doesn't span a cycle, so comps_pb keeps the flat median (disclosed)."""
_TCROE_MIN_PEER_MEDIAN: Final[float] = 0.02
"""Floor on the peer-median through-cycle ROE used as the scaling divisor. Below 2% the
ratio divisor is unstable/explosive (a near-zero denominator), so fall back to flat."""
_TCROE_SCALE_CAP: Final[float] = 2.6
"""Sanity band on the scaling ratio. Live 2026-07-06 the largest legitimate sample is PGR
(target/peer through-cycle ROE ≈ 1.9x → P/B ≈ 3.9x, matching its 4.0x market P/B); the cap
gives cycle headroom above that but keeps a data glitch from an unbounded multiple. Clamp
is disclosed in provenance (post-clamp value shown)."""


def through_cycle_roe(
    net_income: Sequence[float | None],
    shareholders_equity: Sequence[float | None],
    *,
    min_years: int = _TCROE_MIN_YEARS,
) -> float | None:
    """Mean annual ROE = net_income / shareholders_equity across the history window.

    Both are raw currency amounts from the same year's statements — deliberately NOT
    eps/book_value_per_share, which would divide a weighted-average-diluted share count
    (eps) by a period-end one (bvps) and drift ROE 1-3% in a heavy-buyback year; the
    raw NI/equity form carries no share count at all, so it is share-basis clean AND
    survives a historical year whose market-derived share count is missing. Minor
    caliber note (not a bug): net_income is bottom-line while shareholders_equity is
    parent-only (totalStockholdersEquity excludes minority interest); the two align for a
    low-NCI issuer and the residual is far below the underwriting-cycle swing this
    normalizes. Loss years are kept (a negative-ROE year is a real part of the cycle);
    only a non-positive-equity year is skipped (undefined ratio). Returns None when fewer
    than ``min_years`` valid years exist — the caller then keeps the flat peer-median
    P/B. Used to normalize an insurer's underwriting-cycle ROE swing for comps_pb.
    """
    roes = [
        n / e
        for n, e in zip(net_income, shareholders_equity, strict=False)
        if isinstance(n, (int, float))
        and not isinstance(n, bool)
        and isinstance(e, (int, float))
        and not isinstance(e, bool)
        and e > 0
    ]
    if len(roes) < min_years:
        return None
    return sum(roes) / len(roes)


_COMPS_MIN_MULTIPLE_SAMPLE = 3
"""Minimum surviving peers behind a multiple median before it may price the
target. NM caps / sanity bounds / missing consensus thin the contributing set
below the peer-SET floor (validate_peer_comps' ≥3 gates set membership, not
median membership): TSLA 2026-06-10 carried 2 peers of which only GM had a
forward P/E, and "peer median forward P/E 5.8x" — one company's multiple
wearing a median's authority — priced TSLA at $10.93. A sample of 0 means the
PeerComps was built without calculate_peer_statistics (hand-constructed /
pre-field cached payloads) — counts unknown, median trusted as before."""

_COMPS_RELIABLE_MULTIPLE_SAMPLE = 4
"""At/above this many surviving peers a multiple median carries FULL method
confidence. Between the floor (``_COMPS_MIN_MULTIPLE_SAMPLE``) and here — i.e. a
3-firm median — the median is a REAL comp but rests on a thin sample, so its
confidence is DOWNWEIGHTED (never cut — contract ②「降权不砍方法」) so a thin
peer set can't dominate the confidence-weighted synthesis blend. TSM 2026-07-02:
its forward comps_pe rested on a 3-peer median (one of which was a value-chain-
misclassified equipment vendor) yet drove a +50% BUY headline; the role gate
keeps the bad peer out, and this keeps a genuinely-3-firm median from over-
weighting. A ≥4-firm median (KO=6, JPM=6) is untouched."""

_COMPS_THIN_SAMPLE_CONFIDENCE_FACTOR = 0.7
"""Confidence multiplier for a thin (3-firm) multiple median. ~0.7 keeps the
method a real contributor (not withheld) while demoting it a tier's-worth in the
blend — comps_pe 0.55 → 0.385, below dcf's 0.85 cash-flow confidence."""

_COMPS_MULTIPLE_MISMATCH_MAX = 10.0
"""Premise guard: comps prices the target AT the peer median, which presumes
the market would value it like its peers. A same-caliber target multiple ≥10x
away from the median (TSLA forward P/E 322x vs auto peers 5.8x = 55x) is the
market persistently rejecting that premise — applying the median manufactures
a number with no information content and poisons the synthesis spread.
Ordinary leader premia run 2–3x (AMD 63.6x vs semis 33x = 1.9x; MU 15.7x vs
37.3x = 2.4x — both must keep pricing), so 10x only trips the absurd."""

_RERATING_DISCLOSURE_THRESHOLD: Final[float] = 0.25
"""|implied-multiple-ratio − 1| beyond which a multiples method ALSO appends a re-rating
WARNING (on top of the always-on assumptions line). Pure DISCLOSURE reminder threshold: it
changes no mid/low/high/confidence and gates no method — it only decides when the implied
re-rating is large enough to also flag in the warnings section. Symmetric — fires for an
upward re-rate (ratio > 1.25) and a downward de-rate (ratio < 0.75) alike. NOT a financial
calibration; moving it re-rates no target and drops no row."""

RERATING_WARNING_MARKER: Final[str] = "judge independently whether that multiple shift is warranted"
"""Stable tail every re-rating warning ends with. _helpers.build_valuation_synthesis
matches on THIS constant to forward these warnings into ValuationSynthesis.warnings
(the report's warnings section). Single source: reword the warning text only through
this constant, or the forwarding silently breaks."""


def _comps_median_refusal(
    median_val: float,
    sample_n: int,
    target_multiple: float | None,
    label: str,
    method: str = "comps_pe",
) -> str | None:
    """None when the peer median may price the target; else the refusal reason.

    ``method`` tags the warning with the method that's退出 (``comps_pe`` /
    ``comps_pb``) so an analyst reading ``ValuationSynthesis.warnings`` sees which
    relative multiple refused — a P/B refusal must not masquerade as a P/E one.
    """
    if 0 < sample_n < _COMPS_MIN_MULTIPLE_SAMPLE:
        return (
            f"{method}: peer {label} sample is only {sample_n} firm(s) "
            f"(< {_COMPS_MIN_MULTIPLE_SAMPLE}); a single peer's multiple is not a median — method withheld"
        )
    if target_multiple is not None and target_multiple > 0:
        mismatch = max(target_multiple, median_val) / min(target_multiple, median_val)
        if mismatch > _COMPS_MULTIPLE_MISMATCH_MAX:
            return (
                f"{method}: the target's own {label} {target_multiple:.0f}x is {mismatch:.0f}x away from "
                f"the peer median {median_val:.1f}x "
                f"(> {_COMPS_MULTIPLE_MISMATCH_MAX:.0f}x) — the market has never priced this name "
                f"at the peer median, so the 'converge to peers' premise does not apply — method withheld"
            )
    return None


def _thin_sample_confidence(
    confidence: float,
    sample_n: int,
    method: str,
    label: str,
    warn: Callable[[str], None],
) -> float:
    """Downweight (never withhold) a multiple median that clears the ``n≥3`` floor
    but rests on a thin sample (``3 ≤ n < _COMPS_RELIABLE_MULTIPLE_SAMPLE``).

    ``_comps_median_refusal`` already withholds ``n < 3`` (a single/pair multiple is
    not a median). This is the SOFTER, complementary rule for the 3-firm median: it
    IS a real comp, so we keep the method and reduce its confidence — a thin peer set
    should not dominate the confidence-weighted synthesis blend nor stamp a
    high-confidence headline (contract ②:「降权不砍方法」). A ≥4-firm median is
    returned unchanged. ``sample_n == 0`` means counts are unknown (hand-built /
    pre-field cached payload) — trusted as before, no penalty."""
    if _COMPS_MIN_MULTIPLE_SAMPLE <= sample_n < _COMPS_RELIABLE_MULTIPLE_SAMPLE:
        warn(
            f"{method}: {label} median rests on only {sample_n} peers "
            f"(< {_COMPS_RELIABLE_MULTIPLE_SAMPLE}); a thin sample — confidence reduced "
            f"(method retained, downweighted in the synthesis blend)."
        )
        return round(confidence * _COMPS_THIN_SAMPLE_CONFIDENCE_FACTOR, 3)
    return confidence


def aggregate_valuation(
    *,
    ticker: str,
    current_price: float | None,
    dcf: DCFResult | None = None,
    peer_comps: PeerComps | None = None,
    ddm: DDMResult | None = None,
    residual_income: RIResult | None = None,
    lbo: LBOResult | None = None,
    shares_outstanding: float | None = None,
    current_net_debt: float | None = None,
    forward_eps: float | None = None,
    ttm_ebitda: float | None = None,
    forward_fcf: float | None = None,
    forward_fiscal_period: str | None = None,
    forward_confidence: str | None = None,
    forward_source: str | None = None,
    historical_ev_ebitda_band: tuple[float, float] | None = None,
    historical_ev_ebitda_sample_n: int | None = None,
    historical_p_fcf_band: tuple[float, float] | None = None,
    cyclical: bool = False,
    financial_sector: bool = False,
    as_of: datetime | None = None,
) -> ValuationAggregate:
    """Build the Football Field payload for one ticker.

    Each artifact / number is optional. Missing methods drop out silently with
    a one-line warning. Caller (route layer) is responsible for fetching the
    inputs via DataLayer / ArtifactStore and assembling them.

    ``cyclical`` (``is_commodity_cyclical`` result, threaded by the caller) adds the
    P/B comps row as the PRIMARY relative multiple for a memory/storage / steel /
    oil&gas cyclical — book equity is cycle-stable, unlike trough/peak EPS. The
    through-cycle / forward P/E row still ships alongside it (football field shows
    both; synthesis weights the through-cycle anchor).

    ``financial_sector`` (``is_bank`` result, threaded by the caller) SUPPRESSES the
    cash-flow methods — DCF, EV/EBITDA, P/FCF — for a bank/insurer. They are category
    errors there: "free cash flow", "EBITDA" and the net-debt bridge are ill-defined
    when debt is the raw material, not financing (``is_bank`` itself documents "use
    DDM, not FCF-DCF"; numeric_audit independently blocks EV as
    ``financial_sector_ev_meaningless``). The football field instead leads with P/B
    (book equity / tangible book is the bank anchor) + P/E + DDM. Without this the
    report plotted a JPM DCF ~$719 against a ~$325 price — a meaningless 2.2x row that
    dragged the blend and the divergence gate.
    """
    methods: list[ValuationMethodRange] = []
    warnings: list[str] = []

    if financial_sector:
        # Cash-flow DCF withheld for a financial issuer (category error — see
        # docstring). Surfaced with the method-withheld marker so the synthesis
        # forwards the reason to the headline, never a silent drop.
        warnings.append(
            "dcf: financial-sector issuer — FCF-DCF does not apply (free cash flow and the "
            "net-debt bridge are ill-defined for banks; P/B · P/E · DDM are the bank methods) "
            "— method withheld"
        )
    elif (m := _dcf_method(dcf)) is not None:
        methods.append(m)
    elif dcf is None:
        warnings.append("dcf: no DCF artifact — this row appears after running the full AI report")
    else:
        # DCF resolved but implied price ≤ 0 — equity is negative/zero after the
        # net-debt bridge. A non-positive price can't be plotted; the row drops.
        # Surface WHY (with the marker so build_valuation_synthesis forwards it to
        # vs.warnings and the headline), rather than dropping it silently.
        warnings.append(
            f"dcf: implied share price ≤ 0 (${dcf.implied_price:,.2f}: equity is negative/zero "
            "after subtracting net debt from enterprise value) — DCF method does not apply — "
            "method withheld"
        )

    # P/B is the PRIMARY relative multiple for two regimes: a commodity-cyclical
    # (book equity is cycle-stable, unlike trough/peak EPS) AND a bank/insurer (book /
    # tangible book is THE financial anchor, since the suppressed DCF/EV can't price
    # it). Listed BEFORE comps_pe so the football field leads with it; the P/E row
    # still ships when available. Everyone else skips P/B entirely.
    if (cyclical or financial_sector) and (m := _comps_pb_method(peer_comps, warnings)) is not None:
        methods.append(m)

    if (
        m := _comps_pe_method(
            peer_comps,
            forward_eps,
            shares_outstanding,
            warnings,
            cyclical=cyclical,
            current_price=current_price,
        )
    ) is not None:
        methods.append(m)
    elif cyclical:
        # Suppressed by design for a commodity-cyclical: _comps_pe_method emitted
        # its own口径 warning (forward P/E × cycle-peak EPS is the $2199/$2974 MU
        # artifact). comps_pb is the primary multiple; the through-cycle P/E anchor
        # ships via the DCF row. Do NOT fall through to the data-quality diagnostics
        # below — the method didn't fail on data, it declined the forward-peak口径.
        pass
    elif peer_comps is None:
        warnings.append(
            "comps_pe: no peer_analysis artifact — this row appears after running the full AI report"
        )
    elif forward_eps is None:
        warnings.append(
            "comps_pe: forward EPS unavailable (no FMP analyst-estimates data / FMP key not configured) — "
            "degrading to trailing EPS"
        )
    else:
        # peer_comps present, method still returned None — diagnose why
        pe_n = sum(1 for p in peer_comps.peers if p.pe_ratio is not None)
        core_pe_n = sum(1 for p in peer_comps.peers if p.core_pe_ratio is not None)
        if pe_n == 0 and core_pe_n == 0:
            warnings.append(
                "comps_pe: peer P/E median is N/A — all peers' TTM net income ≤ 0 "
                "(pre-profitability peer set), so the P/E method cannot be applied. "
                "Suggest specifying a profitable peer set manually via --peers — method withheld"
            )
        elif peer_comps.target.net_income is None or peer_comps.target.net_income <= 0:
            warnings.append(
                "comps_pe: target TTM net income ≤ 0 — the target itself is loss-making, so the P/E method does not apply — method withheld"
            )

    if (m := _ddm_method(ddm)) is not None:
        methods.append(m)
    elif ddm is not None and ddm.equity_value_per_share <= 0:
        # DDM was provided but its per-share equity value is ≤ 0 (degenerate) — the
        # method drops. ``ddm is None`` is the normal non-dividend case and gets no
        # warning; only a provided-but-degenerate DDM surfaces a reason (with the
        # marker) instead of falling out silently.
        warnings.append(
            f"ddm: equity value per share ≤ 0 (${ddm.equity_value_per_share:,.2f}) — "
            "DDM method does not apply to this name — method withheld"
        )

    # Residual income (justified P/B) — the bank's ROE-coherent intrinsic anchor.
    # Threaded for banks only; supersedes the dividend-only DDM as the headline
    # anchor (see _confidence_dial). ROE-coherent and buyback-invariant.
    if (m := _ri_method(residual_income)) is not None:
        methods.append(m)

    if (m := _lbo_method(lbo, shares_outstanding)) is not None:
        methods.append(m)
    elif lbo is not None and shares_outstanding is None:
        warnings.append(
            "lbo: missing shares_outstanding — target-price reverse calculation skipped"
        )

    ev_inputs_present = (
        ttm_ebitda is not None
        and ttm_ebitda > 0
        and historical_ev_ebitda_band is not None
        and shares_outstanding is not None
        and shares_outstanding > 0
    )
    if financial_sector:
        # Enterprise value is a category error for a bank/insurer (debt is the raw
        # material, not financing) — the same reason numeric_audit blocks it as
        # ``financial_sector_ev_meaningless``. Suppress the row here too so it never
        # reaches the football field, not just the headline.
        warnings.append(
            "ev_ebitda: financial-sector issuer — enterprise value is a category error for "
            "banks (debt is raw material, not financing) — method withheld"
        )
    elif (
        m := _ev_ebitda_method(
            ttm_ebitda,
            historical_ev_ebitda_band,
            shares_outstanding,
            current_net_debt,
            band_sample_n=historical_ev_ebitda_sample_n,
            warnings=warnings,
            current_price=current_price,
        )
    ) is not None:
        methods.append(m)
    elif not ev_inputs_present:
        # Genuine input absence (band / TTM EBITDA / shares missing) — row hidden.
        warnings.append(
            "ev_ebitda: historical valuation band (PR3 not wired) or TTM EBITDA unavailable — multiple row degraded and hidden"
        )
    elif current_net_debt is None:
        # Inputs all present EXCEPT current net debt — refuse to bridge EV→equity on a
        # fabricated debt figure. EV/EBITDA is a *current* relative-multiple method;
        # without current net debt there is no honest bridge, so the row is hidden.
        warnings.append(
            "ev_ebitda: current net debt (total_debt − cash) unavailable — refusing to fabricate the "
            "EV→equity bridge with 0 or LBO's future ending_debt; this row is hidden "
            "(EV/EBITDA is a current-multiple method and must subtract current net debt)"
        )
    # else: inputs present + net debt present but the method still dropped (non-positive
    # band / negative implied equity) — _ev_ebitda_method already recorded the precise
    # reason (with the marker) into `warnings`, so we add no (mis-)diagnostic here.

    if financial_sector:
        # Free cash flow is ill-defined for a bank/insurer (no operating/financing
        # split on cash flows) — P/FCF is suppressed for the same reason as DCF.
        warnings.append(
            "p_fcf: financial-sector issuer — free cash flow ill-defined for banks — method withheld"
        )
    elif (m := _p_fcf_method(forward_fcf, historical_p_fcf_band, shares_outstanding)) is not None:
        methods.append(m)
    else:
        warnings.append(
            "p_fcf: historical valuation band (PR3 not wired) or forward FCF unavailable — multiple row degraded and hidden"
        )

    return ValuationAggregate(
        ticker=ticker.upper(),
        current_price=current_price,
        as_of=as_of if as_of is not None else datetime.now(tz=timezone.utc),
        methods=methods,
        warnings=warnings,
        forward_fiscal_period=forward_fiscal_period,
        forward_confidence=forward_confidence,
        forward_source=forward_source,
    )


# ---------------------------------------------------------------------------
# Per-method extractors
# ---------------------------------------------------------------------------


def _dcf_method(dcf: DCFResult | None) -> ValuationMethodRange | None:
    if dcf is None or dcf.implied_price <= 0:
        return None
    mid = dcf.implied_price
    low, high, source = _dcf_band(mid)
    return ValuationMethodRange(
        method="dcf",
        method_type="valuation",
        low=low,
        mid=mid,
        high=high,
        confidence=0.85,
        source=source,
        assumptions=_dcf_assumptions(dcf),
    )


def _dcf_assumptions(dcf: DCFResult) -> str:
    """The load-bearing assumptions behind the DCF mid, in one line.

    These three do almost all the work in setting fair value — a DCF mid is an
    answer conditional on them, not a standalone number. The discount rate and
    the length/steepness of the growth fade are exactly the axes a reader argues
    over (an NVDA-style $73 is what a 16.6% WACC + 5y fade produces, not a claim
    the stock is worth $73).
    """
    rates = dcf.inputs.revenue_growth_rates
    tg = dcf.inputs.terminal_growth_rate
    if rates:
        g0 = rates[0]
        peak = max(rates)
        # A first-year dip below the path's peak (e.g. a slow FY1 consensus year
        # before the growth ramp) makes the two-point "g0→terminal" projection lie
        # about the curve: MSFT's [3.2%, 18.2%, …decay…, 3%] rendered as "3%→3.0%",
        # hiding the 18% peak entirely (2026-07-07 blind panoramic review). Show the
        # peak whenever it sits meaningfully above the first year.
        if peak - g0 > 0.01:
            growth = f"{len(rates)}yr growth {g0:.0%}↗{peak:.0%}→{tg:.1%}"
        else:
            growth = f"{len(rates)}yr growth {g0:.0%}→{tg:.1%}"
    else:
        growth = f"terminal growth {tg:.1%}"
    return f"WACC {dcf.wacc:.1%} · {growth} · β{dcf.inputs.beta:.2f}"


def _dcf_band(mid: float) -> tuple[float, float, str]:
    """A flat ±20% band around the DCF implied price.

    This is a deterministic placeholder spread, NOT a modelled distribution: no
    Monte Carlo P10/P90 is ever wired into the pipeline (sensitivity_table only
    ever holds the WACC×TG grid), so the band carries no real probability mass.
    The source label says so explicitly to avoid implying false precision on the
    Football Field chart.
    """
    return (
        mid * (1 - _DCF_BAND_WIDTH),
        mid * (1 + _DCF_BAND_WIDTH),
        "implied_price ± 20% (placeholder band, not a real distribution)",
    )


def _comps_pe_method(
    peer_comps: PeerComps | None,
    forward_eps: float | None,
    shares_outstanding: float | None,
    warnings: list[str] | None = None,
    *,
    cyclical: bool = False,
    current_price: float | None = None,
) -> ValuationMethodRange | None:
    if peer_comps is None:
        return None

    def _warn(msg: str) -> None:
        if warnings is not None:
            warnings.append(msg)

    # Commodity-cyclical → SUPPRESS the forward / trailing P/E comps row entirely.
    # Per design §5.2 the comps_pe for a cyclical must price off a mid-cycle EPS
    # (= through-cycle net margin × current revenue / shares), NOT the analyst
    # forward (cycle-PEAK) EPS that prints MU at $2974 (peer forward P/E 36.9x ×
    # peak EPS) — the same two-sided-peak failure mode the $2199 artifact had.
    # The through-cycle net margin is not plumbed to this leaf (only the DCF seed's
    # through-cycle EBITDA margin exists, from which a clean net-income normalisation
    # would require re-modelling D&A / interest / tax here — out of scope and not
    # available at the call site), so we take the design's sanctioned fallback (b):
    # suppress forward comps_pe and rely on comps_pb (primary, cycle-stable book
    # value) + the through-cycle P/E that ships via the DCF anchor row. Non-cyclicals
    # are untouched — the entire path below runs exactly as before.
    if cyclical:
        _warn(
            # Qualitative only — this reason surfaces verbatim into price_target_basis
            # prose. NO ticker-specific naked $-figure here (the dev rationale, MU's
            # $2199/$2974 cycle-peak artifact, lives in the comments above): a naked
            # $-amount gets washed to "[target withheld]" on the withheld path AND a
            # hardcoded "MU $X" contaminates every other cyclical's report.
            "comps_pe: cyclical — suppressing the forward P/E × cycle-peak EPS basis "
            "(a growth-stock forward multiple applied to a commodity-cyclical's peak-cycle "
            "EPS overstates fair value); led instead by comps_pb (book value, cycle-stable) "
            "+ through-cycle P/E (DCF anchor) as fallback — method withheld"
        )
        return None

    used_forward = forward_eps is not None and forward_eps > 0
    has_shares = shares_outstanding is not None and shares_outstanding > 0
    mid: float | None = None
    source = ""
    multiple: float | None = None
    caliber = ""
    confidence = 0.55
    used_sample_n = 0  # peers behind the CHOSEN median → thin-sample confidence penalty
    # Short caliber tag for the re-rating disclosure, set ONLY on paths where the peer
    # anchor multiple and the target's own multiple sit on ONE earnings caliber (so a
    # "self × → peer ×" comparison is apples-to-apples). Left None on the degraded
    # fallback that applies a TRAILING peer median to a FORWARD EPS — mixing calibers
    # there would misstate the re-rating, so that path discloses nothing (绝不混口径).
    rerating_pe_kind: str | None = None

    if used_forward:
        # Forward EPS is analyst consensus — a normalised forward number. Prefer a
        # peer FORWARD median P/E (added per peer in _fetch_one_peer) so both sides
        # share one forward caliber; fall back to the as-reported trailing peer
        # median P/E only when no peer carried a forward multiple. Highest-confidence
        # path either way.
        if peer_comps.median_forward_pe is not None and peer_comps.median_forward_pe > 0:
            refusal = _comps_median_refusal(
                peer_comps.median_forward_pe,
                peer_comps.forward_pe_sample_n,
                peer_comps.target.forward_pe,
                "forward P/E",
            )
            if refusal is not None:
                _warn(refusal)
                return None
            # Fully forward: peer FORWARD median P/E × target forward EPS — ONE
            # forward caliber on both sides, resolving the BUG-029 mixed-caliber
            # caveat below (peers' forward P/E = market_cap / FY1 consensus net
            # income, set per peer in _fetch_one_peer). Slightly higher confidence
            # than the as-reported fallback because the calibers now agree.
            mid = peer_comps.median_forward_pe * forward_eps  # type: ignore[operator]
            source = "peer_median_forward_pe × forward_eps (peer forward P/E × target forward EPS, same caliber)"
            multiple = peer_comps.median_forward_pe
            caliber = "forward EPS (peer forward P/E, same caliber)"
            confidence = 0.80
            used_sample_n = peer_comps.forward_pe_sample_n
            rerating_pe_kind = (
                "forward P/E"  # peer FORWARD median vs self forward P/E — one caliber
            )
        elif peer_comps.median_pe is not None and peer_comps.median_pe > 0:
            refusal = _comps_median_refusal(
                peer_comps.median_pe,
                peer_comps.pe_sample_n,
                peer_comps.target.pe_ratio,
                "P/E",
            )
            if refusal is not None:
                _warn(refusal)
                return None
            # Fallback when no peer carried a forward P/E (foreign-only set, or no
            # analyst consensus): as-reported trailing peer median P/E × forward EPS.
            #
            # 口径 caveat (BUG-029): median_pe is the median of peers' AS-REPORTED P/E
            # (market_cap / net_income), which still carries peers' non-operating
            # income — a DIFFERENT earnings definition than the trailing path's
            # NOPAT-core median_core_pe. The label states the caliber explicitly
            # rather than silently mixing definitions.
            mid = peer_comps.median_pe * forward_eps  # type: ignore[operator]
            source = "peer_median_pe × forward_eps (as-reported peer P/E, includes non-operating income; no peer forward caliber)"
            multiple = peer_comps.median_pe
            caliber = "forward EPS (as-reported peer P/E)"
            confidence = 0.78
            used_sample_n = peer_comps.pe_sample_n
            # rerating_pe_kind stays None: this applies a TRAILING peer median to a
            # FORWARD EPS, so the peer anchor and a self forward P/E are different
            # calibers — no honest same-caliber re-rating disclosure exists here.
    else:
        # Trailing path: use the NOPAT core caliber so the target EPS and the
        # peer median P/E share ONE earnings definition — stripping the
        # non-operating items that differ across the set (the apples-to-oranges
        # that put NVDA's comps_pe at $341 on EPS inflated by ~$27B of TTM
        # investment gains). calculate_core_pe fills these in the pipeline.
        core_ni = peer_comps.target.core_net_income
        if (
            peer_comps.median_core_pe is not None
            and peer_comps.median_core_pe > 0
            and core_ni is not None
            and core_ni > 0
            and has_shares
        ):
            refusal = _comps_median_refusal(
                peer_comps.median_core_pe,
                peer_comps.core_pe_sample_n,
                peer_comps.target.core_pe_ratio,
                "core P/E",
            )
            if refusal is not None:
                _warn(refusal)
                return None
            core_eps = core_ni / shares_outstanding  # type: ignore[operator]
            mid = peer_comps.median_core_pe * core_eps
            source = (
                "peer_median_core_pe × core_eps (NOPAT core-earnings caliber; forward unavailable)"
            )
            multiple = peer_comps.median_core_pe
            caliber = "NOPAT core-earnings EPS"
            confidence = 0.55
            used_sample_n = peer_comps.core_pe_sample_n
            rerating_pe_kind = "core P/E"  # peer core median vs self core P/E — one caliber
        elif peer_comps.median_pe is not None and peer_comps.median_pe > 0 and has_shares:
            # Fallback: core caliber unavailable (provider omitted operating
            # margin / tax) — keep the as-reported trailing path rather than
            # dropping the method entirely.
            net_income = peer_comps.target.net_income
            if net_income is not None and net_income > 0:
                refusal = _comps_median_refusal(
                    peer_comps.median_pe,
                    peer_comps.pe_sample_n,
                    peer_comps.target.pe_ratio,
                    "P/E",
                )
                if refusal is not None:
                    _warn(refusal)
                    return None
                mid = peer_comps.median_pe * (net_income / shares_outstanding)  # type: ignore[operator]
                source = "peer_median_pe × trailing_eps (forward unavailable)"
                multiple = peer_comps.median_pe
                caliber = "trailing EPS"
                confidence = 0.55
                used_sample_n = peer_comps.pe_sample_n
                rerating_pe_kind = "P/E"  # peer trailing median vs self trailing P/E — one caliber

    if mid is None or mid <= 0:
        return None

    confidence = _thin_sample_confidence(confidence, used_sample_n, "comps_pe", "P/E", _warn)
    band = mid * _COMPS_PE_BAND_WIDTH
    assumptions = (
        f"anchored to peer median P/E {multiple:.1f}× × {caliber}" if multiple is not None else None
    )
    # Disclose the re-rating this method IMPLICITLY assumes: pricing the target AT the peer
    # median multiple presumes its OWN multiple converges from where it trades today to that
    # anchor. self_multiple = current_price / earnings-used, and earnings-used = mid / multiple,
    # so self_multiple is the target's own P/E on the SAME caliber as the peer anchor
    # (`multiple`) — apples-to-apples, and multiple / self_multiple ≡ mid / current_price (the
    # method's own implied upside). Always-on when disclosable; a warning is added only when
    # the shift is large. Changes NO mid/low/high/confidence — pure transparency, nothing is
    # gated on it. Skipped on the mixed-caliber fallback (rerating_pe_kind None) or no price.
    rerating_ratio: float | None = None
    if (
        current_price is not None
        and current_price > 0
        and multiple is not None
        and rerating_pe_kind is not None
    ):
        self_multiple = current_price * multiple / mid
        ratio = mid / current_price
        rerating_ratio = ratio  # structured twin — the dial GRADES on this
        rerating = (
            f"implied re-rating {self_multiple:.1f}× → {multiple:.1f}× "
            f"{rerating_pe_kind} ({ratio:.2f}×)"
        )
        assumptions = f"{assumptions}; {rerating}" if assumptions else rerating
        if abs(ratio - 1.0) > _RERATING_DISCLOSURE_THRESHOLD:
            shift = "expand" if ratio > 1.0 else "compress"
            _warn(
                f"comps_pe: pricing the target at the peer median implies its own "
                f"{rerating_pe_kind} must {shift} from {self_multiple:.1f}× to {multiple:.1f}× "
                f"({ratio:.2f}× the current multiple) — an unproven re-rating premise, not a "
                f"modelled convergence; {RERATING_WARNING_MARKER}."
            )
    return ValuationMethodRange(
        method="comps_pe",
        method_type="valuation",
        low=mid - band,
        mid=mid,
        high=mid + band,
        confidence=confidence,
        source=source,
        assumptions=assumptions,
        rerating_ratio=rerating_ratio,
    )


def _comps_pb_method(
    peer_comps: PeerComps | None,
    warnings: list[str] | None = None,
) -> ValuationMethodRange | None:
    """Price-to-book comps — the PRIMARY multiple for a commodity-cyclical.

    Book equity is cycle-stable, so a memory/storage peer median P/B × the target's
    book value per share avoids the成长股 forward-P/E × cycle-peak-EPS artifact that
    prints $2199 for MU. Gated by the SAME _comps_median_refusal as comps_pe (n<3
    refusal + >10x premise mismatch) so a single peer's P/B never wears a median's
    authority, and the "market never priced this name at the peer median" premise
    guard still fires. None when no peer P/B median exists or the target carries no
    (single-currency, positive) book value per share.
    """

    def _warn(msg: str) -> None:
        if warnings is not None:
            warnings.append(msg)

    if peer_comps is None:
        return None
    median_pb = peer_comps.median_pb
    target_bvps = peer_comps.target.book_value_per_share
    if median_pb is None or median_pb <= 0:
        return None
    if target_bvps is None or target_bvps <= 0:
        _warn(
            "comps_pb: target book value per share unavailable (provider did not report / negative equity / cross-currency ADR) — "
            "cyclical P/B method degraded, falling back to P/E — method withheld"
        )
        return None
    refusal = _comps_median_refusal(
        median_pb, peer_comps.pb_sample_n, peer_comps.target.pb_ratio, "P/B", method="comps_pb"
    )
    if refusal is not None:
        _warn(refusal)
        return None

    # Insurer ROE quality adjustment: a flat peer-median P/B grants no quality premium,
    # so it under-prices a high-through-cycle-ROE insurer (PGR) and over-prices a low-ROE
    # one (CB). Scale the median P/B by the target's through-cycle ROE relative to the peer
    # median (justified P/B ∝ ROE). Both fields are set ONLY for the insurer cohort
    # (execute_peer_analysis), so banks / non-financials keep the flat median unchanged.
    effective_pb = median_pb
    roe_note = ""
    tgt_roe = peer_comps.target_through_cycle_roe
    peer_roe = peer_comps.peer_median_through_cycle_roe
    if tgt_roe is not None and peer_roe is not None:
        if peer_roe < _TCROE_MIN_PEER_MEDIAN or tgt_roe <= 0:
            # Divisor unstable (near-zero peer ROE) or target has no positive through-cycle
            # ROE → keep the flat median, disclose (dirty-value fallback, guardrail 1).
            _warn(
                f"comps_pb: through-cycle ROE adjustment skipped — peer-median ROE "
                f"{peer_roe:.1%} below the {_TCROE_MIN_PEER_MEDIAN:.0%} divisor floor or "
                f"target ROE {tgt_roe:.1%} non-positive; flat peer-median P/B used"
            )
        else:
            raw_scale = tgt_roe / peer_roe
            scale = max(1.0 / _TCROE_SCALE_CAP, min(_TCROE_SCALE_CAP, raw_scale))
            effective_pb = median_pb * scale
            clamp_note = (
                f" (clamped from {raw_scale:.2f}×)" if abs(scale - raw_scale) > 1e-9 else ""
            )
            roe_note = (
                f"; ROE-adjusted ×{scale:.2f}{clamp_note} (through-cycle ROE {tgt_roe:.1%} "
                f"÷ peer-median {peer_roe:.1%})"
            )

    mid = effective_pb * target_bvps
    if mid <= 0:
        return None
    band = mid * _COMPS_PB_BAND_WIDTH
    # Slightly above comps_pe's trailing confidence: for a cyclical, P/B is the more
    # reliable relative anchor than a cycle-distorted P/E — then downweighted for a
    # thin (3-firm) peer median just like comps_pe.
    confidence = _thin_sample_confidence(0.60, peer_comps.pb_sample_n, "comps_pb", "P/B", _warn)
    return ValuationMethodRange(
        method="comps_pb",
        method_type="valuation",
        low=mid - band,
        mid=mid,
        high=mid + band,
        confidence=confidence,
        source="peer_median_pb × target_book_value_per_share (cyclical book-value caliber, primary multiple)",
        assumptions=(
            f"anchored to peer median P/B {median_pb:.2f}× × book value per share "
            f"${target_bvps:,.2f}{roe_note}"
        ),
    )


def _ddm_method(ddm: DDMResult | None) -> ValuationMethodRange | None:
    if ddm is None or ddm.equity_value_per_share <= 0:
        return None
    mid = ddm.equity_value_per_share
    return ValuationMethodRange(
        method="ddm",
        method_type="valuation",
        low=mid * (1 - _DDM_BAND_WIDTH),
        mid=mid,
        high=mid * (1 + _DDM_BAND_WIDTH),
        confidence=0.55,
        source="perpetuity_growth ± 15%",
        assumptions=_ddm_assumptions(ddm),
    )


def _ddm_assumptions(ddm: DDMResult) -> str:
    """DDM's load-bearing assumptions: the equity discount rate (cost of equity,
    not WACC — dividends accrue to equity only) and the dividend growth path.
    """
    rates = ddm.inputs.dividend_growth_rates
    tg = ddm.inputs.terminal_growth_rate
    g0 = rates[0] if rates else tg
    return f"discount rate (cost of equity) {ddm.cost_of_equity:.1%} · dividend growth {g0:.0%}→terminal {tg:.1%}"


def _ri_method(ri: RIResult | None) -> ValuationMethodRange | None:
    if ri is None or ri.equity_value_per_share <= 0:
        return None
    trailing = ri.equity_value_per_share
    forward = (
        ri.forward_value if (ri.forward_value is not None and ri.forward_value > 0) else trailing
    )
    lo, hi = sorted((trailing, forward))
    # Band = [RI at trailing ROE (our realized return — the independent low end), RI at
    # forward consensus ROE (the recovery boundary)], widened to a MINIMUM of the standard
    # ±15% method width (NOT a new constant). The floor's job is to pin a stable bank
    # (trailing ≈ forward) to HOLD under price micro-moves — never to manufacture a
    # BUY/SELL signal; the realized→forward range widens it for a cyclical name. The band
    # IS the bank's value range; the verdict is price-vs-band (_confidence_dial), refusing
    # to extrapolate a single point in the cycle to a perpetuity ROE.
    centre = (lo + hi) / 2
    band_low = min(lo, centre * (1 - _RI_BAND_WIDTH))
    band_high = max(hi, centre * (1 + _RI_BAND_WIDTH))
    return ValuationMethodRange(
        method="residual_income",
        method_type="valuation",
        low=band_low,
        # The displayed anchor is the TRAILING value — our own realized-return number, an
        # accounting fact — never a forward-biased centre that would let consensus reclaim
        # the rating.
        mid=trailing,
        high=band_high,
        confidence=0.6,
        source="justified P/B (residual income), trailing→forward ROE band",
        assumptions=_ri_assumptions(ri),
    )


def _ri_assumptions(ri: RIResult) -> str:
    """RI's load-bearing assumptions: cost of equity, the realized ROE−CoE excess spread,
    and (when available) the FY1 consensus recovery ROE that sets the band's high end."""
    base = (
        f"cost of equity {ri.cost_of_equity:.1%} · trailing ROE {ri.return_on_equity:.1%} "
        f"(excess {ri.excess_return:+.1%}) · justified P/B {ri.justified_pb:.2f}× book "
        f"${ri.book_value_per_share:.2f}"
    )
    if ri.forward_return_on_equity is not None:
        base += f" · forward (FY1 consensus) ROE {ri.forward_return_on_equity:.1%} → recovery band"
    return base


def _lbo_method(
    lbo: LBOResult | None, shares_outstanding: float | None
) -> ValuationMethodRange | None:
    """Build the LBO ability-to-pay band by reusing the saved exit sensitivity grid.

    Per spec §6.4.2: we never re-run ``calculate_lbo`` per cell. Read the grid,
    compute the t+N exit equity (exit_multiple × exit_ebitda − remaining_debt)
    per cell, then discount it to TODAY at the sponsor hurdle:
    ``price = exit_equity / shares / (1 + SPONSOR_IRR_HURDLE)^N``.

    The discounting is load-bearing: exit equity is a FUTURE value at the end
    of the hold. Plotting it undiscounted on the football field next to PV
    methods (DCF) and the current price overstated the LBO row ~2x over a 5y
    hold — FV and PV must never share an axis. The discounted figure is the
    classic ability-to-pay reading (Rosenbaum & Pearl Ch.8): the most a
    sponsor can pay per share today and still clear its hurdle at that exit.
    """
    if lbo is None or shares_outstanding is None or shares_outstanding <= 0:
        return None

    grid = lbo.sensitivity or {}
    exit_multiples = grid.get("exit_multiples") if isinstance(grid, dict) else None
    if not isinstance(exit_multiples, list) or not exit_multiples:
        return None

    remaining_debt = lbo.schedule[-1].ending_debt if lbo.schedule else 0.0
    exit_ebitda = lbo.exit_ebitda
    if exit_ebitda <= 0:
        return None

    holding_years = len(lbo.schedule)
    target_prices = _lbo_target_grid(
        exit_multiples, exit_ebitda, remaining_debt, shares_outstanding, holding_years
    )
    if not target_prices:
        return None

    target_prices.sort()
    return ValuationMethodRange(
        method="lbo",
        method_type="valuation",
        low=target_prices[0],
        mid=target_prices[len(target_prices) // 2],
        high=target_prices[-1],
        confidence=0.60,
        source=(
            f"ability-to-pay: (exit_multiple × exit_ebitda − remaining_debt) "
            f"discounted at the sponsor hurdle {SPONSOR_IRR_HURDLE:.0%} over {holding_years}yr "
            f"(reusing the sensitivity grid)"
        ),
        assumptions=_lbo_assumptions(exit_multiples, lbo.schedule),
    )


def _lbo_assumptions(exit_multiples: list[Any], schedule: list[Any]) -> str | None:
    """LBO target-price band is driven by the exit EV/EBITDA range and the hold
    period — the assumptions a sponsor actually argues over. Built from the same
    grid/schedule the band itself reads, so it can never drift from the number.
    """
    mults = [float(m) for m in exit_multiples if _is_floatable(m)]
    if not mults:
        return None
    return f"exit EV/EBITDA {min(mults):.1f}–{max(mults):.1f}× · hold {len(schedule)}yr"


def _is_floatable(v: Any) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _lbo_target_grid(
    exit_multiples: list[Any],
    exit_ebitda: float,
    remaining_debt: float,
    shares: float,
    holding_years: int,
) -> list[float]:
    # exit_equity is a t+N future value — discount at the sponsor hurdle so the
    # band is comparable to the PV methods and the current price on one axis.
    discount = (1 + SPONSOR_IRR_HURDLE) ** max(holding_years, 0)
    out: list[float] = []
    for raw in exit_multiples:
        try:
            mult = float(raw)
        except (TypeError, ValueError):
            continue
        if mult <= 0:
            continue
        exit_equity = mult * exit_ebitda - remaining_debt
        if exit_equity <= 0:
            continue
        price = exit_equity / shares / discount
        if price > 0:
            out.append(price)
    return out


def _ev_ebitda_method(
    ttm_ebitda: float | None,
    band: tuple[float, float] | None,
    shares: float | None,
    current_net_debt: float | None,
    *,
    band_sample_n: int | None = None,
    warnings: list[str] | None = None,
    current_price: float | None = None,
) -> ValuationMethodRange | None:
    if ttm_ebitda is None or ttm_ebitda <= 0 or band is None or shares is None or shares <= 0:
        return None
    # EV/EBITDA is a CURRENT relative-multiple method, so the EV→equity bridge
    # MUST subtract CURRENT net debt (total_debt − cash, same口径 as dcf_seed).
    # A missing net-debt figure means there is no honest bridge — hide the row
    # rather than (a) assume net_debt = 0, which values a levered firm as
    # debt-free, or (b) borrow LBO's post-paydown ending_debt, a *future*
    # simulated debt at exit (t+hold) — a time-point mismatch that
    # systematically overstates the target. ``current_net_debt`` may be negative
    # (net cash), which correctly lifts the implied equity value.
    # current_net_debt None is an input-absence case the caller (aggregate_valuation)
    # diagnoses with its own caliber-explicit note — drop silently here.
    if current_net_debt is None:
        return None
    p25, p75 = band
    if p25 <= 0 or p75 <= 0:
        # The band itself is degenerate (non-positive percentile) — no valid
        # historical multiple range. Record WHY (with the marker) so it surfaces.
        if warnings is not None:
            warnings.append(
                "ev_ebitda: historical EV/EBITDA percentile band is non-positive (p25/p75 ≤ 0) — "
                "no valid historical range for the multiple, this row is hidden — method withheld"
            )
        return None
    raw_low = (p25 * ttm_ebitda - current_net_debt) / shares
    raw_high = (p75 * ttm_ebitda - current_net_debt) / shares
    # Debt exceeds the implied EV even at the OPTIMISTIC p75 multiple (p75 ≥ p25 ⇒
    # raw_high ≥ raw_low): implied equity is negative across the whole band, so
    # EV/EBITDA equity is undefined. Drop the row — mirroring the LBO grid's
    # per-cell drop — instead of flooring to a fabricated $0.01 that would enter
    # the football field as a real method. (raw_low < 0 < raw_high is a legitimate
    # near-wipeout: floor the low end to ~0 but keep the real p75 upside.)
    if raw_high <= 0:
        # All inputs present but the bridge yields non-positive equity across the
        # whole band — record the precise reason (with the marker) so aggregate does
        # NOT mis-report it as "band/forward unavailable" (they ARE present).
        if warnings is not None:
            warnings.append(
                "ev_ebitda: even at the optimistic p75 multiple the implied equity is ≤ 0 "
                "(current net debt exceeds the implied EV) — multiple method does not apply, "
                "this row is hidden — method withheld"
            )
        return None
    low = max(0.01, raw_low)
    high = max(low, raw_high)
    mid = (low + high) / 2
    # Method self-description (condition i): frame this row for what it now is — a
    # RE-RATING ANCHOR (own 5y trailing band × current TTM operating EBITDA − net debt),
    # single-caliber (a trailing-year band applied to a trailing-earnings denominator, so
    # NO caliber gap) and carrying NO forward-growth credit. band_sample_n lets the analyst
    # (and the confidence dial reading method spread) tell a band built on a full multi-year
    # history from a thin one; every input is a reported figure, not a corroborated point.
    method_warnings: list[str] = []
    if band_sample_n is not None:
        method_warnings.append(
            f"ev_ebitda: own 5-year trailing EV/EBITDA percentile band ({band_sample_n} samples) × "
            f"current TTM operating EBITDA − current net debt — a re-rating anchor to the target's "
            f"own historical multiple (not peers), single-caliber and carrying NO forward-growth "
            f"credit; a degraded relative-valuation method."
        )
    # Symmetric disclosure of this anchor's directional bias (condition ii, 对称披露向下偏差):
    # the denominator is trailing TTM earnings, NOT the next-twelve-months consensus, so the
    # anchor gives no credit for expected earnings growth. For a fast-growing issuer whose
    # forward EBITDA runs materially above trailing, it is therefore systematically CONSERVATIVE
    # (biased low). Stated qualitatively — no $ / no ticker — so it is narrative-scrubber-safe and
    # never fabricates the omitted growth. This is the method's own (non-basis) face.
    method_warnings.append(
        "ev_ebitda: this re-rating anchor prices trailing TTM earnings only — for a growth issuer "
        "whose next-twelve-month EBITDA exceeds trailing, it excludes forward growth and is "
        "systematically conservative (biased low)."
    )
    # Disclose the mean-reversion this method IMPLICITLY assumes: reverting the target to its own
    # historical multiple mid presumes today's price-implied multiple converges there. Both the
    # band and the denominator are now the SAME caliber — the band is trailing-year multiples
    # (fetch_reverse_multiple_band) and the denominator is TTM operating EBITDA (income.ebitda,
    # OI + D&A) — so the whole comparison is single-caliber and the price-implied EV/TTM-EBITDA
    # label matches the data page's EV/TTM-EBITDA figure exactly (no same-metric double value).
    # The gap is pure mean-reversion, not caliber. current_net_debt may be negative (net cash),
    # which correctly lifts EV. Skipped when the price is missing or the current EV is ≤ 0 (net
    # cash exceeds market cap). Changes NO mid/low/high/confidence — pure transparency, nothing gated.
    assumptions: str | None = None
    rerating_ratio: float | None = None
    if current_price is not None and current_price > 0:
        current_ev = current_price * shares + current_net_debt
        if current_ev > 0:
            current_implied = current_ev / ttm_ebitda
            band_mid = (p25 + p75) / 2
            ratio = band_mid / current_implied
            rerating_ratio = ratio  # structured twin — the dial GRADES on this
            assumptions = (
                f"implied re-rating: price-implied EV/TTM-EBITDA {current_implied:.1f}× → "
                f"own 5y trailing band mid {band_mid:.1f}× ({ratio:.2f}×)"
            )
            if abs(ratio - 1.0) > _RERATING_DISCLOSURE_THRESHOLD and warnings is not None:
                shift = "expand" if ratio > 1.0 else "compress"
                warnings.append(
                    f"ev_ebitda: reverting the target to its own 5-year historical multiple "
                    f"implies its price-implied EV/TTM-EBITDA must {shift} from "
                    f"{current_implied:.1f}× to the trailing band mid {band_mid:.1f}× "
                    f"({ratio:.2f}×) — an unproven mean-reversion premise (band and denominator "
                    f"are the same trailing caliber, so the gap is not a caliber artifact); "
                    f"{RERATING_WARNING_MARKER}."
                )
    return ValuationMethodRange(
        method="ev_ebitda",
        method_type="multiple",
        low=low,
        mid=mid,
        high=high,
        confidence=0.72,
        # Window mirrors fetch_reverse_multiple_band(years=5) — the requested band
        # window (all callers use that default); actual sample depth is disclosed
        # separately via band_sample_n. Keep this label in sync if the default changes.
        source="self_5y_p25_p75 × ttm_ebitda − current_net_debt",
        assumptions=assumptions,
        rerating_ratio=rerating_ratio,
        warnings=method_warnings,
    )


def _p_fcf_method(
    forward_fcf: float | None,
    band: tuple[float, float] | None,
    shares: float | None,
) -> ValuationMethodRange | None:
    if forward_fcf is None or forward_fcf <= 0 or band is None or shares is None or shares <= 0:
        return None
    p25, p75 = band
    if p25 <= 0 or p75 <= 0:
        return None
    low = (p25 * forward_fcf) / shares
    high = (p75 * forward_fcf) / shares
    mid = (low + high) / 2
    return ValuationMethodRange(
        method="p_fcf",
        method_type="multiple",
        low=low,
        mid=mid,
        high=high,
        confidence=0.65,
        # Window mirrors fetch_reverse_multiple_band(years=5) — see _ev_ebitda_method.
        source="self_5y_p25_p75 × forward_fcf",
    )
