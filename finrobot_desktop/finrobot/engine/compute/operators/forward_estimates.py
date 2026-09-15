"""Forward financial estimates — the one true entry point for forward EPS / EBITDA / FCF.

v5 PR4c. Spec §6.4.1 made this a red-line module: nothing else in the codebase
may compute or guess forward EPS / EBITDA / FCF. Football Field's multiple
rows (EV/EBITDA and P/FCF reverse-engineering, spec §6.4) read from here;
the audit test below grep-pins that no other call site shells out an analyst
consensus number on its own.

Two resolution paths:

  * FMP consensus (preferred) — when ``fmp_analyst_estimates`` is supplied
    (DataType.FORWARD_ESTIMATES via DataLayer), the FY1 row (nearest
    fiscal-year-end ≥ as_of) fills forward EPS / revenue / EBITDA from analyst
    consensus. FMP's analyst-estimates endpoint does NOT carry free cash flow,
    so forward_fcf stays None and the P/FCF reverse row stays hidden.
    confidence = ``high`` when consensus EBITDA is present (forward P/E AND
    EV/EBITDA both consensus-driven), else ``medium``. ``fiscal_period`` records
    the exact FYE used so the forward P/E denominator is auditable.
  * yfinance degraded path — when no FMP payload is available, forward_eps
    comes from yfinance ``info["forwardEps"]`` only; forward revenue / EBITDA
    / FCF stay None (no back-fill, per spec §6.4.1) and the aggregator hides
    those rows. confidence = ``low`` (or down-rated on >20% TTM-margin
    volatility), ``unavailable`` when even forward_eps is missing.

Spec §6.4.1 keeps this a red-line leaf: nothing else may compute or guess a
forward EPS / EBITDA / FCF number. The audit tests in
``tests/audit/test_forward_estimates_red_lines.py`` grep-pin that gate.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Literal

ConfidenceLevel = Literal["high", "medium", "low", "unavailable"]


@dataclass(frozen=True)
class ForwardFinancials:
    """All forward-looking numbers any caller is allowed to use.

    ``source`` describes provenance so downstream banners can render an
    accurate "this came from analyst consensus" / "this is derived from
    TTM × forecast revenue" label — every number stays traceable to its口径.
    ``fiscal_period`` records WHICH forecast fiscal-year-end these numbers
    belong to (e.g. "2026-09-30") so the forward P/E denominator is auditable
    and comps PE / EV-EBITDA / FCF-yield all share one fiscal-year口径.
    """

    ticker: str
    forward_eps: float | None
    forward_revenue: float | None
    forward_ebitda: float | None
    forward_fcf: float | None
    confidence: ConfidenceLevel
    source: str
    warnings: list[str]
    fiscal_period: str | None = None
    forward_net_income: float | None = None
    """FY1 consensus net income (FMP ``netIncomeAvg``), reporting currency.

    Lets a market-cap-centric consumer (the peer comps set, whose CompanyFinancials
    carries ``market_cap`` but no price/shares) compute forward P/E as
    ``market_cap / forward_net_income`` — algebraically the SAME caliber as the
    target side's ``price / forward_eps`` (market_cap = price × shares,
    forward_net_income = forward_eps × shares). None on the yfinance degraded path
    (consensus net income unavailable there)."""


_TTM_VOLATILITY_THRESHOLD = 0.20
"""TTM margin std/mean ratio above which we down-rate confidence to 'low'."""


_FX_MISMATCH_NI_RATIO = 6.0
"""Forward-NI / |trailing-NI| ratio above which the FMP consensus figure is
treated as a CURRENCY MISMATCH and abstained, not a real forecast.

FMP's /analyst-estimates endpoint returns ``epsAvg`` / ``netIncomeAvg`` in the
issuer's NATIVE reporting currency with NO currency field (live-verified across
UMC/TSM/AAPL/ASML 2026-06-14 — ``currency-ish fields in row: NONE``), and that
native currency is per-ticker INCONSISTENT even among the same exchange's ADRs:
UMC's row is native TWD (``netIncomeAvg`` 57.7B vs USD-canonical trailing 1.59B
= 36.4x) while TSM's same endpoint already returns USD (1.33x). The canonical
FINANCIALS snapshot the comps gate reads has been FX-normalized to USD by then
(``reporting_currency`` overwritten USD==USD), so the
``reporting_currency == quote_currency`` gate — and the ``fx_normalized``
marker, present on BOTH UMC and TSM — cannot tell a native-TWD forward payload
from a USD one. The ONLY reliable signal is the magnitude jump against a
currency-clean USD trailing anchor.

Calibration (live FMP basket, 2026-06-14):
  clean USD-vs-USD NI ratio — KO 1.03, MSFT 1.01, AAPL 1.07, NVDA 1.43, TSM
    1.33, ASML 1.09, WDC 0.57, MU 2.78 (cyclical memory upcycle, the widest
    legitimate jump) — all ≤ ~2.8.
  FX-mismatch NI ratio — UMC 36.4 (TWD), SONY 583 (JPY) — the smallest major
    reporting-currency spot (HKD ≈ 7.8, TWD ≈ 31, JPY ≈ 150, KRW ≈ 1350) sits
    far above the clean band.
6.0 cleanly separates the two populations: it clears MU's 2.78 cyclical jump
with headroom yet sits below even the tightest FX multiple. A forward NI > 6×
trailing implies a sustained >70%/yr CAGR — hyper-growth optionality the comps
median already withholds via the NM P/E cap, so abstaining there is safe too."""


_FX_MISMATCH_REV_RATIO = 3.0
"""Forward-NI / trailing-REVENUE(USD) ratio above which the FMP consensus is an
FX artifact — the second guard leg, covering the loss-maker hole the NI-ratio
leg can't (SONY's trailing NI is negative, so no NI ratio forms, yet its native
JPY forward NI 1249B vs USD revenue ~$79B = 16× is unmistakably cross-currency).

Net income can never exceed revenue, so for a currency-clean issuer this ratio
is bounded by the net margin (< 1). Revenue is always positive, so this leg
works even when trailing NI is ≤ 0. Calibration (live FMP basket, 2026-06-14):
clean fwdNI/Rev — SAP 0.20, AAPL 0.29, NVDA 0.90, MU 1.15 (cyclical: forward
upcycle NI vs trough-year revenue, the widest legitimate value) — all ≤ ~1.2;
FX-mismatch — UMC 7.58 (TWD), SONY 15.88 (JPY). 3.0 clears MU's 1.15 with margin
yet sits far below the smallest FX case."""


_FX_MISMATCH_EPS_RATIO = 6.0
"""Forward-EPS(native) / USD-trailing-EPS ratio above which the FMP consensus is a
CURRENCY MISMATCH — the THIRD guard leg, for the hole legs 1–2 can't see: a vendor
that UNDER-reports ``netIncomeAvg``.

Legs 1–2 assume "cross-currency ⇒ the native figure is BIG" (a native-TWD/JPY
``netIncomeAvg`` dwarfs the USD trailing anchor). That assumption breaks when FMP's
``netIncomeAvg`` is internally under-estimated: KOF's FY2026 row ships
``netIncomeAvg`` 2.54B MXN against ``revenueAvg`` 308B MXN — a 0.8% implied net
margin vs KOF's real ~8% (≈10× too low). So its ni_ratio is only 2.78 and rev_ratio
0.20 — both in-band — and the native-MXN forward EPS (120.98, a fwd P/E 8.7 =
USD market cap / MXN net income) leaks through. ``epsAvg`` is the reliable field on
that same row (120.98 MXN × the ~210M canonical ADR share count = ~25B MXN, matching
the real earnings), so comparing it against a currency-clean USD trailing EPS
(``trailing_net_income_usd / shares``) exposes the un-converted FX the NI legs missed.

Calibration (live FMP basket, 2026-07-06 — fwd_eps × canonical_shares / trailing_NI_USD):
  clean USD-vs-USD — AAPL 1.05, KO 1.03, JPM 1.03 — all ≈ 1.0 (eps growth ≈ NI growth
    for a currency-clean, share-stable issuer, so the widest legit value tracks the
    NI leg's cyclical ceiling, MU 2.78).
  FX-mismatch — KOF 27.8 (MXN, the case legs 1–2 miss), UMC 37.3 (TWD), TSM 43.1
    (TWD — FMP flipped it back to native since the 2026-06-14 USD vintage).
6.0 mirrors ``_FX_MISMATCH_NI_RATIO`` deliberately: a currency-clean forward-EPS/
trailing-EPS ratio is bounded by the same earnings-growth logic as the NI ratio, so
the 6.0 that clears MU's 2.78 cyclical jump applies here too, and it sits 4.6× below
KOF's 27.8. Inert on a loss-maker (trailing EPS ≤ 0 forms no ratio — SONY, caught by
the revenue leg instead) and when no clean USD-trailing-EPS anchor is supplied."""


def get_forward_financials(
    *,
    ticker: str,
    yf_info: dict[str, Any] | None,
    historical_ebitda_margins: list[float] | None = None,
    historical_fcf_margins: list[float] | None = None,
    fmp_analyst_estimates: dict[str, Any] | None = None,
    as_of: date | None = None,
    trailing_net_income_usd: float | None = None,
    trailing_revenue_usd: float | None = None,
    trailing_eps_usd: float | None = None,
) -> ForwardFinancials:
    """Resolve every forward financial number for one ticker.

    Args:
        ticker: Uppercase ticker symbol.
        yf_info: yfinance Ticker.info dict (or the FinancialData.raw_data
            equivalent) — used for forward_eps / shares fallback.
        historical_ebitda_margins: 3-year EBITDA-margin list for volatility
            assessment and EBITDA derivation. Empty / None drops EBITDA
            confidence to 'low'.
        historical_fcf_margins: 3-year FCF-margin list (same role).
        fmp_analyst_estimates: FMP /v3/analyst-estimates payload, shape
            ``{"rows": [...]}`` (newest/farthest-future first). When present,
            FMP consensus is preferred over the yfinance forward_eps fallback.
        as_of: Reference date for forward-period selection. The leaf picks the
            nearest fiscal-year-end ≥ as_of (FY1). Defaults to today.
        trailing_net_income_usd: Currency-clean (USD-canonical) TTM/annual net
            income, used as the primary magnitude anchor for the FX-mismatch
            guard. FMP analyst-estimates carry NO currency field and may be in
            the issuer's native reporting currency (TWD/JPY/…) even when the
            canonical FINANCIALS snapshot has already been FX-normalized to USD —
            see ``_FX_MISMATCH_NI_RATIO``. When the FY1 consensus net income
            exceeds this anchor by that ratio, the forward NI / EPS / EBITDA are
            abstained (None) rather than shipped as a cross-currency artifact.
            None (the default) leaves the NI leg of the guard inert.
        trailing_revenue_usd: Currency-clean (USD-canonical) TTM/annual revenue,
            the SECOND guard anchor (see ``_FX_MISMATCH_REV_RATIO``). Always
            positive, so it catches the loss-maker case the NI ratio can't (a
            negative trailing NI forms no ratio). Net income can never exceed
            revenue, so a forward NI dwarfing trailing revenue is unambiguously
            cross-currency.
        trailing_eps_usd: Currency-clean (USD-canonical) TTM/annual EPS — the THIRD
            guard anchor (see ``_FX_MISMATCH_EPS_RATIO``). Callers derive it as
            ``trailing_net_income_usd / shares_outstanding`` (canonical shares,
            market-cap-consistent = per ADR). Needed because legs 1–2 read
            ``netIncomeAvg``, which FMP sometimes UNDER-reports (KOF ~10× low) so its
            NI/revenue ratios stay in-band while the native-currency ``epsAvg`` still
            leaks; ``epsAvg`` against a clean USD trailing EPS exposes the mismatch.
            None leaves the EPS leg inert (legacy callers, or a loss-making /
            share-less issuer).

    Returns:
        ForwardFinancials with whatever could be filled and a Chinese-language
        warning list explaining each None.
    """
    warnings: list[str] = []

    if fmp_analyst_estimates is not None:
        fmp_result = _from_fmp(ticker, fmp_analyst_estimates, warnings, as_of or date.today())
        fmp_result = _guard_fx_mismatch(
            fmp_result, trailing_net_income_usd, trailing_revenue_usd, trailing_eps_usd
        )
        if fmp_result.confidence != "unavailable" or not yf_info:
            return fmp_result
        return _from_yfinance(
            ticker,
            yf_info,
            historical_ebitda_margins,
            historical_fcf_margins,
            initial_warnings=[
                "FMP analyst-estimates unavailable: "
                + "; ".join(fmp_result.warnings)
                + " — degraded to yfinance forward EPS"
            ],
        )

    if not yf_info:
        return _unavailable(ticker, "no yfinance info — all forward figures unavailable")

    return _from_yfinance(
        ticker,
        yf_info,
        historical_ebitda_margins,
        historical_fcf_margins,
        initial_warnings=[],
    )


def _guard_fx_mismatch(
    result: ForwardFinancials,
    trailing_net_income_usd: float | None,
    trailing_revenue_usd: float | None,
    trailing_eps_usd: float | None = None,
) -> ForwardFinancials:
    """Abstain FMP consensus that is a currency mismatch, not a real forecast.

    FMP /analyst-estimates ships ``netIncomeAvg`` / ``epsAvg`` in the issuer's
    native reporting currency with no currency field, and that currency is
    per-ticker inconsistent even among the same exchange's ADRs (UMC native TWD,
    TSM has flipped between USD and native TWD across vintages). Neither the
    ``reporting_currency == quote_currency`` gate nor the ``fx_normalized`` marker
    can distinguish them (both fire for UMC and TSM), so the magnitude jump against
    a currency-clean USD trailing anchor is the only reliable signal. Three
    complementary legs:

    1. forward NI / trailing NI > ``_FX_MISMATCH_NI_RATIO`` (needs trailing NI > 0).
    2. forward NI / trailing REVENUE > ``_FX_MISMATCH_REV_RATIO`` — net income can
       never exceed revenue, and revenue is always positive so this leg fires even
       for a loss-maker (SONY: negative trailing NI, native-JPY forward NI 16×
       USD revenue) that leg 1 alone would miss.
    3. forward EPS / trailing EPS(USD) > ``_FX_MISMATCH_EPS_RATIO`` — for the hole
       legs 1–2 leave when FMP UNDER-reports ``netIncomeAvg`` (KOF ~10× low, so its
       NI/revenue ratios stay in-band) while ``epsAvg`` is still native. Uses the
       reliable per-share figure against a clean USD trailing EPS.

    On a trip the FMP figures are abstained to None — never converted with a
    guessed rate (we don't know the native currency code) and never shipped as a
    cross-currency forward P/E. Each leg is inert when its anchor is absent."""
    fwd_ni = result.forward_net_income
    fwd_eps = result.forward_eps
    if fwd_ni is None and fwd_eps is None:
        return result

    ni_ratio: float | None = None
    if (
        fwd_ni is not None
        and trailing_net_income_usd is not None
        and math.isfinite(trailing_net_income_usd)
        and trailing_net_income_usd > 0
    ):
        ni_ratio = fwd_ni / trailing_net_income_usd

    rev_ratio: float | None = None
    if (
        fwd_ni is not None
        and trailing_revenue_usd is not None
        and math.isfinite(trailing_revenue_usd)
        and trailing_revenue_usd > 0
    ):
        rev_ratio = fwd_ni / trailing_revenue_usd

    eps_ratio: float | None = None
    if (
        fwd_eps is not None
        and trailing_eps_usd is not None
        and math.isfinite(trailing_eps_usd)
        and trailing_eps_usd > 0
    ):
        eps_ratio = fwd_eps / trailing_eps_usd

    ni_trips = ni_ratio is not None and ni_ratio > _FX_MISMATCH_NI_RATIO
    rev_trips = rev_ratio is not None and rev_ratio > _FX_MISMATCH_REV_RATIO
    eps_trips = eps_ratio is not None and eps_ratio > _FX_MISMATCH_EPS_RATIO
    if not (ni_trips or rev_trips or eps_trips):
        return result

    if ni_trips and ni_ratio is not None:
        why = (
            f"is {ni_ratio:.0f}× trailing net income (USD) {trailing_net_income_usd / 1e9:.1f}B "  # type: ignore[operator]
            f"(>{_FX_MISMATCH_NI_RATIO:g}×)"
        )
    elif rev_trips and rev_ratio is not None:
        why = (
            f"is {rev_ratio:.1f}× trailing revenue (USD) {trailing_revenue_usd / 1e9:.1f}B "  # type: ignore[operator]
            f"(>{_FX_MISMATCH_REV_RATIO:g}×; net income cannot exceed revenue)"
        )
    else:
        why = (
            f"implies forward EPS {result.forward_eps:.2f} vs trailing EPS (USD) "
            f"{trailing_eps_usd:.2f} = {eps_ratio:.0f}× (>{_FX_MISMATCH_EPS_RATIO:g}×; "
            f"native-currency EPS while netIncomeAvg was under-reported)"
        )
    # netIncomeAvg can be under-reported (the very hole the EPS leg covers) or
    # absent, so lead the warning with net income only when it is present.
    ni_phrase = f"implied net income {fwd_ni / 1e9:.1f}B " if fwd_ni is not None else ""
    return replace(
        result,
        forward_eps=None,
        forward_net_income=None,
        forward_ebitda=None,
        # EPS / EBITDA are minted from the same native-currency row, so they are
        # equally cross-currency — abstain them together. Revenue is left as-is:
        # it feeds only the DCF growth ratio (FYn/FYn-1, currency-cancelling), so
        # a native-currency revenue path is still valid there.
        confidence="unavailable",
        warnings=[
            *result.warnings,
            f"forward NI/EPS abstained: FMP consensus {ni_phrase}{why}"
            f" — /analyst-estimates carries no currency field, likely native reporting currency (non-USD); "
            f"cross-currency forward P/E rejected, set to None",
        ],
    )


def _from_yfinance(
    ticker: str,
    yf_info: dict[str, Any],
    historical_ebitda_margins: list[float] | None,
    historical_fcf_margins: list[float] | None,
    *,
    initial_warnings: list[str],
) -> ForwardFinancials:
    warnings = list(initial_warnings)

    forward_eps = _coerce_positive_float(yf_info.get("forward_eps") or yf_info.get("forwardEps"))
    if forward_eps is None:
        warnings.append(
            "forward_eps unavailable — neither FMP analyst-estimates nor yfinance provided a usable value"
        )

    # Without FMP we have no consensus forward revenue, so forward EBITDA / FCF
    # can't be derived either. Stay honest rather than back-fill.
    forward_revenue: float | None = None
    forward_ebitda: float | None = None
    forward_fcf: float | None = None
    if forward_eps is not None:
        warnings.append(
            "forward_revenue / forward_ebitda / forward_fcf unavailable: "
            "yfinance only carries forward EPS; consensus revenue / earnings pending FMP analyst-estimates integration"
        )

    confidence: ConfidenceLevel = "low" if forward_eps is not None else "unavailable"

    margin_warning = _margin_volatility_warning(historical_ebitda_margins, historical_fcf_margins)
    if margin_warning is not None:
        warnings.append(margin_warning)
        confidence = "low"

    source = (
        "yfinance.info.forwardEps (degraded · FMP consensus unavailable)"
        if forward_eps is not None
        else "no available forward data source"
    )

    return ForwardFinancials(
        ticker=ticker.upper(),
        forward_eps=forward_eps,
        forward_revenue=forward_revenue,
        forward_ebitda=forward_ebitda,
        forward_fcf=forward_fcf,
        confidence=confidence,
        source=source,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# FMP path — wired-but-empty hook for PR4c.2
# ---------------------------------------------------------------------------


def get_forward_revenue_growth(
    fmp_analyst_estimates: dict[str, Any] | None,
    *,
    as_of: date | None = None,
    max_years: int = 3,
) -> list[float]:
    """Forward YoY revenue-growth path (FY1..FYn) from FMP analyst-estimates.

    Returns up to ``max_years`` consecutive consensus growth rates — FY1/last
    actual − 1, then FY2/FY1 − 1, … — for seeding the DCF explicit window so the
    model reflects analyst consensus instead of a backward-looking trailing CAGR.
    Returns ``[]`` (caller falls back to trailing-CAGR seeding) when the payload
    is absent, has no parseable rows, or carries no past-actual row to anchor the
    FY1 growth. Far-out rows (beyond ``max_years``) are dropped — FMP consensus
    past ~3 years is sparse and non-monotonic.

    Lives here, not in dcf_seed, because §6.4.1 makes this leaf the only place
    allowed to mint a forward-consensus number; dcf_seed consumes the plain rates.
    """
    rows = (
        fmp_analyst_estimates.get("rows")
        if isinstance(fmp_analyst_estimates, dict)
        else fmp_analyst_estimates
    )
    if not isinstance(rows, list) or not rows:
        return []
    ref = as_of or date.today()
    parsed: list[tuple[date, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        d = _parse_iso_date(row.get("date"))
        rev = _coerce_positive_float(row.get("revenueAvg"))
        if d is not None and rev is not None:
            parsed.append((d, rev))
    parsed.sort(key=lambda p: p[0])
    base = [p for p in parsed if p[0] < ref]
    forward = [p for p in parsed if p[0] >= ref][:max_years]
    if not base or not forward:
        return []
    seq = [base[-1][1]] + [p[1] for p in forward]
    return [seq[i] / seq[i - 1] - 1 for i in range(1, len(seq))]


def _from_fmp(
    ticker: str, fmp: dict[str, Any], warnings: list[str], as_of: date
) -> ForwardFinancials:
    """Parse the FMP stable /analyst-estimates response shape.

    Expected shape (FMP returns a list of fiscal years, farthest-future first;
    stable dropped v3's "estimated" prefix from every figure):
      [{
        "date": "2026-09-30",   # fiscal-year-end
        "revenueAvg": 1.2e11,   # absolute, reporting currency
        "ebitdaAvg": 4.5e10,    # absolute, reporting currency
        "epsAvg": 12.5,         # per-share, reporting currency
        ...
      }, ...]

    The "forward" period is FY1 — the nearest fiscal-year-end ≥ ``as_of`` —
    NOT ``rows[0]`` (which is the farthest-future year FMP returns). Using a
    FY+3 estimate as the forward P/E numerator would be a wrong number.
    """
    rows = fmp.get("rows") if isinstance(fmp, dict) else fmp
    if not isinstance(rows, list) or not rows:
        return _unavailable(
            ticker, "FMP analyst-estimates returned empty — degraded to yfinance forward EPS"
        )

    chosen, period_warning = _select_forward_row(rows, as_of)
    if chosen is None:
        return _unavailable(ticker, "FMP analyst-estimates row has a malformed format")
    if period_warning is not None:
        warnings.append(period_warning)

    forward_eps = _coerce_positive_float(chosen.get("epsAvg"))
    forward_revenue = _coerce_positive_float(chosen.get("revenueAvg"))
    forward_ebitda = _coerce_positive_float(chosen.get("ebitdaAvg"))
    forward_net_income = _coerce_positive_float(chosen.get("netIncomeAvg"))

    if forward_eps is None and forward_revenue is None:
        return _unavailable(ticker, "FMP row missing key fields (eps/revenue)")

    # FMP analyst-estimates supplies consensus EPS / revenue / EBITDA / net
    # income but NO free cash flow figure (true in v3 and stable alike) →
    # forward_fcf stays None, so the P/FCF reverse row stays hidden. Don't gate
    # 'high' on FCF or it's unreachable: 'high' = consensus EPS + EBITDA
    # (forward P/E AND forward EV/EBITDA both consensus-driven); 'medium' =
    # EPS / revenue only.
    if forward_eps is None:
        warnings.append("FMP row has no epsAvg — forward P/E unavailable")
    confidence: ConfidenceLevel = "high" if forward_ebitda is not None else "medium"

    fiscal_period = chosen.get("date") if isinstance(chosen.get("date"), str) else None

    return ForwardFinancials(
        ticker=ticker.upper(),
        forward_eps=forward_eps,
        forward_revenue=forward_revenue,
        forward_ebitda=forward_ebitda,
        forward_fcf=None,
        confidence=confidence,
        source="FMP stable/analyst-estimates consensus",
        warnings=warnings,
        fiscal_period=fiscal_period,
        forward_net_income=forward_net_income,
    )


def _select_forward_row(rows: list[Any], as_of: date) -> tuple[dict[str, Any] | None, str | None]:
    """Pick the FY1 estimate row: nearest fiscal-year-end ≥ as_of.

    Falls back to the most-recent past row (with a staleness warning) when no
    future fiscal year remains, and to the first usable row when no row carries
    a parseable date at all. Returns (row, warning_or_None).
    """
    dated: list[tuple[date, dict[str, Any]]] = []
    undated_first: dict[str, Any] | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        parsed = _parse_iso_date(row.get("date"))
        if parsed is not None:
            dated.append((parsed, row))
        elif undated_first is None:
            undated_first = row

    future = sorted((d for d in dated if d[0] >= as_of), key=lambda dr: dr[0])
    if future:
        return future[0][1], None

    if dated:
        latest = max(dated, key=lambda dr: dr[0])
        return latest[1], (
            f"FMP analyst-estimates latest forecast period {latest[0].isoformat()} is earlier than "
            f"{as_of.isoformat()} — forward data may be stale"
        )

    if undated_first is not None:
        return (
            undated_first,
            "FMP analyst-estimates row missing date — cannot confirm the forward fiscal-year caliber",
        )

    return None, None


def _parse_iso_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unavailable(ticker: str, reason: str) -> ForwardFinancials:
    return ForwardFinancials(
        ticker=ticker.upper(),
        forward_eps=None,
        forward_revenue=None,
        forward_ebitda=None,
        forward_fcf=None,
        confidence="unavailable",
        source="not integrated / data missing",
        warnings=[reason],
    )


def _margin_volatility_warning(
    ebitda_margins: list[float] | None, fcf_margins: list[float] | None
) -> str | None:
    """If TTM margins are too volatile to extrapolate, flag it."""
    for label, series in (("EBITDA", ebitda_margins), ("FCF", fcf_margins)):
        if not series or len(series) < 2:
            continue
        mean = statistics.fmean(series)
        if abs(mean) < 1e-9:
            continue
        stdev = statistics.pstdev(series)
        if stdev / abs(mean) > _TTM_VOLATILITY_THRESHOLD:
            return (
                f"TTM {label} margin volatility {stdev / abs(mean):.0%} > 20% — "
                "forward-estimate confidence lowered to low"
            )
    return None


def _coerce_positive_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    # `f > 0` drops NaN and -Inf but PASSES +Inf (inf > 0 is True) — an asymmetric
    # gate that leaked +Inf into avg_*_surprise_pct. Require finiteness too.
    return f if f > 0 and math.isfinite(f) else None
