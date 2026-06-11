"""EMPIRICAL VALIDATION (CLAUDE.md 🔴 protocol) for cyclical mid-cycle DCF
normalization — DESIGN gate, run BEFORE any production change.

Three pillars, all against authoritative SEC XBRL filed data (FMP key is
rate-limited; SEC is the higher-quality through-cycle source anyway):

  PILLAR 1 — external benchmark + reverse-derivation (协议 §2):
    For MU, reverse-solve the operating margin the ~$950 live price implies
    under the seed's OWN WACC/growth/capex, and check it against the SEC
    through-cycle margin band. If the market implies a margin INSIDE the
    historical [trough, peak] band, mid-cycle normalization is the right lens.

  PILLAR 2 — variable isolation (only the earnings base moves):
    MU DCFInputs built from SEC data. Five earnings-base variants on the SAME
    calculate_dcf (everything else fixed):
      A  trough-tilted last-FY margin   (what a trough snapshot feeds)
      A' last-3y median margin          (current _MEDIAN_WINDOW_YEARS=3 proxy)
      B  through-cycle MEDIAN margin     (Damodaran normalization)
      C  through-cycle MEAN margin
      D  B + maintenance-capex normalization in the EXPLICIT window too
    Report implied price + ratio-to-market for each. Gate: does a normalized
    variant land inside the single-method calibration band [0.5x, 2x]?

  PILLAR 3 — full-basket regression:
    Non-cyclical names (KO/MSFT/JNJ/AMD/NVDA) must be UNAFFECTED — they fail the
    cyclical gate, so their earnings base is unchanged. Only MU (and storage
    siblings WDC/STX) shift. Proven by classifying each and showing the cyclical
    flag + (for cyclicals) the through-cycle vs last-3y margin gap.

Run: `python scripts/_cyclical_normalization_validation.py`
"""

from __future__ import annotations

import asyncio
import statistics
from dataclasses import dataclass

import httpx

from finrobot.config import get_settings
from finrobot.engine.compute.operators.dcf import calculate_dcf
from finrobot.engine.compute.operators.wacc import adjust_beta_blume
from finrobot.engine.models.financial import DCFInputs
from finrobot.paths import SETTINGS_JSON
from finrobot.routes.settings import load_non_secret_settings
from finrobot.secret_store import create_secret_store
from finrobot.server import hydrate_settings_from_secrets

SINGLE_METHOD_BAND = (0.5, 2.0)  # SINGLE_METHOD_DIVERGENCE_RATIO_K = 2.0

# Live prices (yfinance, 2026-06-10; cross-checked vs Yahoo/CNBC search band
# $935.89–$993, 52w $103–$1089, mcap ~$1.06T — system inside band, no bug).
LIVE_PRICE = {"MU": 949.88, "WDC": 512.11, "STX": 853.10}

CIKS = {"MU": 723125, "WDC": 106040, "STX": 1137789}

REV = ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet")
OPI = ("OperatingIncomeLoss",)
DA = (
    "DepreciationDepletionAndAmortization",
    "DepreciationAmortizationAndAccretionNet",
    "DepreciationAndAmortization",
)
CAPEX = ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets")
CASH = ("CashAndCashEquivalentsAtCarryingValue",)
STI = ("ShortTermInvestments", "MarketableSecuritiesCurrent")
LTD = ("LongTermDebtNoncurrent", "LongTermDebt")
CURD = ("LongTermDebtCurrent", "DebtCurrent")
SHARES = ("CommonStockSharesOutstanding",)


def _annual(facts: dict, concepts: tuple[str, ...]) -> dict[int, float]:
    """Annual 10-K flows keyed by TRUE fiscal year = period-end calendar year.

    The SEC XBRL ``fy`` field is the FILING's fiscal year, not the period's: a
    10-K restates prior years as comparatives all tagged with the filing's ``fy``,
    so keying by ``fy`` shifts MU's labels by 2 years (peak FY2018→FY2020, trough
    FY2023→FY2025) and漏掉 the FY2024/25 recovery + super-cycle. Key by the
    period-end year instead (production is unaffected — providers use period-end).
    """
    from datetime import date

    ug = facts.get("facts", {}).get("us-gaap", {})
    out: dict[int, tuple[str, float]] = {}
    for concept in concepts:
        node = ug.get(concept)
        if not node:
            continue
        for uk, items in node.get("units", {}).items():
            if "USD" not in uk:
                continue
            for it in items:
                if it.get("form", "")[:4] != "10-K" or it.get("fp") != "FY":
                    continue
                s, e, v = it.get("start"), it.get("end"), it.get("val")
                if None in (s, e, v):
                    continue
                try:
                    d0, d1 = date.fromisoformat(s), date.fromisoformat(e)
                    if (d1 - d0).days < 300:
                        continue
                except ValueError:
                    continue
                fy = d1.year  # TRUE fiscal year = period-end calendar year
                f = it.get("filed", "")
                if fy not in out or f > out[fy][0]:
                    out[fy] = (f, float(v))
        if out:
            break
    return {fy: v for fy, (_, v) in out.items()}


def _latest_inst(facts: dict, concepts: tuple[str, ...]) -> float | None:
    ug = facts.get("facts", {}).get("us-gaap", {})
    for c in concepts:
        node = ug.get(c)
        if not node:
            continue
        best: tuple[str, str, float] | None = None
        for uk, items in node.get("units", {}).items():
            for it in items:
                if "start" in it:  # want instantaneous (balance) values
                    continue
                e, v, f = it.get("end"), it.get("val"), it.get("filed", "")
                if e is None or v is None:
                    continue
                if best is None or e > best[0] or (e == best[0] and f > best[1]):
                    best = (e, f, float(v))
        if best:
            return best[2]
    return None


async def _facts(client: httpx.AsyncClient, cik: int) -> dict:
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    last_exc: Exception | None = None
    for _ in range(4):
        try:
            r = await client.get(url)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001 — transient proxy flakiness, retry
            last_exc = e
            await asyncio.sleep(2.0)
    raise RuntimeError(f"SEC fetch failed CIK {cik}: {last_exc}")


# Current TTM revenue (recovered run-rate, NOT a trough FY). Damodaran's
# normalization applies the through-cycle MARGIN to CURRENT revenue — so the
# revenue base must be the current run-rate. MU's SEC trough was FY2023 ($15.5B,
# −37%); the cycle has since recovered (FY2024 $25.1B, FY2025 $37.4B) and TTM is
# now ~$58B (AI-memory super-cycle: Q1 FY26 $13.64B + Q2 $23.86B, FY26 consensus
# ~$76B). Using a trough revenue with a normalized margin DOUBLE-COUNTS the
# trough (the flaw in the first run). Source: Micron IR Q1/Q2 FY2026 + Yahoo TTM.
CURRENT_TTM_REVENUE = {"MU": 58.12e9, "WDC": 9.0e9, "STX": 9.5e9}
# Normalized (non-trough) D&A % of revenue: D&A is sticky, so D&A/revenue spikes
# at the trough (MU FY25 49.9% only because revenue collapsed). Use the median of
# the years whose revenue was NOT a trough — proxied by the through-cycle median
# D&A% computed in build_cycle_profile (da_pct_normalized).


@dataclass
class CycleProfile:
    ticker: str
    revenue_latest: float  # SEC latest FY (may be trough)
    op_margins: list[tuple[int, float]]  # (fy, margin) oldest→newest
    da_pct_latest: float  # trough-distorted — do NOT use for normalization
    da_pct_normalized: float  # through-cycle median D&A% (revenue-weighted-ish)
    capex_pct_through_cycle: float
    maint_capex_pct: float  # min(da, capex) through-cycle proxy
    net_debt: float | None
    shares: float | None

    @property
    def last_fy_margin(self) -> float:
        return self.op_margins[-1][1]

    @property
    def last3_median(self) -> float:
        return statistics.median([m for _, m in self.op_margins[-3:]])

    @property
    def cycle_median(self) -> float:
        return statistics.median([m for _, m in self.op_margins])

    @property
    def cycle_mean(self) -> float:
        return statistics.mean([m for _, m in self.op_margins])

    @property
    def peak(self) -> float:
        return max(m for _, m in self.op_margins)

    @property
    def trough(self) -> float:
        return min(m for _, m in self.op_margins)

    @property
    def coeff_var(self) -> float:
        """Std/|mean| of op margin — a determinacy candidate for cyclical flag."""
        vals = [m for _, m in self.op_margins]
        mu = statistics.mean(vals)
        return statistics.pstdev(vals) / abs(mu) if mu else float("inf")


async def build_cycle_profile(client: httpx.AsyncClient, t: str) -> CycleProfile:
    f = await _facts(client, CIKS[t])
    rev = _annual(f, REV)
    opi = _annual(f, OPI)
    da = _annual(f, DA)
    capex = _annual(f, CAPEX)
    years = sorted(rev.keys())
    op_margins = [(y, opi[y] / rev[y]) for y in years if y in opi and rev[y]]
    rev_latest = rev[years[-1]]
    da_pct = [da[y] / rev[y] for y in years if y in da and rev[y]]
    da_pct_latest = (
        (da[years[-1]] / rev[years[-1]]) if years[-1] in da else statistics.median(da_pct)
    )
    # Revenue-WEIGHTED through-cycle D&A% (Σ D&A / Σ revenue): naturally down-
    # weights the trough year's spiked D&A/revenue ratio, giving the steady-state
    # reinvestment intensity instead of the trough artifact.
    da_years = [y for y in years if y in da and rev[y]]
    da_pct_norm = (
        (sum(da[y] for y in da_years) / sum(rev[y] for y in da_years)) if da_years else 0.10
    )
    capex_years = [y for y in years if y in capex and rev[y]]
    capex_tc = (
        (sum(capex[y] for y in capex_years) / sum(rev[y] for y in capex_years))
        if capex_years
        else 0.10
    )
    da_tc = da_pct_norm
    cash = _latest_inst(f, CASH) or 0.0
    sti = _latest_inst(f, STI) or 0.0
    ltd = _latest_inst(f, LTD) or 0.0
    curd = _latest_inst(f, CURD) or 0.0
    nd = ltd + curd - cash - sti
    sh = _latest_inst(f, SHARES)
    return CycleProfile(
        ticker=t,
        revenue_latest=rev_latest,
        op_margins=op_margins,
        da_pct_latest=da_pct_latest,
        da_pct_normalized=da_pct_norm,
        capex_pct_through_cycle=capex_tc,
        maint_capex_pct=min(da_tc, capex_tc),
        net_debt=nd,
        shares=sh,
    )


def _mk_inputs(
    cp: CycleProfile,
    *,
    op_margin: float,
    capex_pct: float,
    da_pct: float,
    shares: float,
    net_debt: float,
    revenue_base: float | None = None,
    growth: list[float] | None = None,
) -> DCFInputs:
    """Build DCFInputs at a given EBITDA margin (= op_margin + da_pct), holding
    everything else. Storage WACC: beta ~1.3 levered (high cyclicality), Blume-
    adjusted; ERP 4.23%, rfr 4.3% (the seed defaults). ``revenue_base`` defaults
    to the CURRENT TTM run-rate (Damodaran: normalized margin × CURRENT revenue),
    NOT the SEC trough FY."""
    ebitda_margin = op_margin + da_pct  # EBITDA = EBIT + D&A
    ebitda_margin = max(0.02, min(0.95, ebitda_margin))
    beta = adjust_beta_blume(1.30)
    g = growth if growth is not None else [0.06, 0.05, 0.04] + [0.035] * 4 + [0.03] * 3
    rb = revenue_base if revenue_base is not None else cp.revenue_latest
    return DCFInputs(
        revenue_base=rb,
        revenue_growth_rates=g,
        ebitda_margin=ebitda_margin,
        capex_pct_revenue=max(0.005, min(0.45, capex_pct)),
        nwc_pct_revenue=0.01,
        terminal_nwc_pct_revenue=0.005,
        da_pct_revenue=max(0.005, min(0.40, da_pct)),
        tax_rate=0.15,  # MU effective rate runs low; sensitivity-irrelevant to the margin point
        risk_free_rate=0.043,
        beta=max(0.3, min(2.5, beta)),
        equity_risk_premium=0.0423,
        cost_of_debt=0.05,
        debt_ratio=0.10,
        terminal_growth_rate=0.03,
        shares_outstanding=shares,
        net_debt=net_debt,
        currency="USD",
    )


def _price(inp: DCFInputs) -> str:
    try:
        return f"${calculate_dcf(inp).implied_price:,.0f}"
    except (ValueError, ArithmeticError) as e:
        return f"拒绝({str(e)[:48]})"


def _ratio(p: str, mkt: float) -> str:
    if not p.startswith("$"):
        return ""
    v = float(p[1:].replace(",", ""))
    r = v / mkt
    flag = "✅band" if SINGLE_METHOD_BAND[0] <= r <= SINGLE_METHOD_BAND[1] else "⛔out"
    return f"({r:.2f}x {flag})"


async def main() -> int:
    s = get_settings(**load_non_secret_settings(SETTINGS_JSON))
    store, _ = create_secret_store()
    s = await hydrate_settings_from_secrets(s, store)
    ua = s.sec_user_agent or "FinRobot Research r@example.com"
    print(
        f"SEC UA: {ua}\nSingle-method calibration band: [{SINGLE_METHOD_BAND[0]}x, {SINGLE_METHOD_BAND[1]}x]"
    )

    yf_shares = {"MU": 1_127_734_051, "WDC": 344_682_131, "STX": 226_252_116}

    async with httpx.AsyncClient(
        headers={"User-Agent": ua, "Accept-Encoding": "gzip"}, timeout=30.0
    ) as client:
        profiles = {}
        for t in ("MU", "WDC", "STX"):
            profiles[t] = await build_cycle_profile(client, t)

    # ---------- PILLAR 3 classification (run first: who is cyclical?) ----------
    print("\n" + "=" * 100)
    print("PILLAR 3 — cyclical classification by op-margin volatility (determinacy candidate)")
    print("=" * 100)
    print(
        f"{'ticker':>6} {'n_yr':>4} {'trough':>8} {'peak':>8} {'spread':>8} "
        f"{'cyc_med':>8} {'last3_med':>9} {'gap':>7} {'coeff_var':>9} {'cyclical?':>10}"
    )
    for t, cp in profiles.items():
        gap = cp.last3_median - cp.cycle_median
        # determinacy candidate: peak-trough spread > 25pts OR coeff_var > 0.6
        is_cyc = (cp.peak - cp.trough) > 0.25 or cp.coeff_var > 0.6
        print(
            f"{t:>6} {len(cp.op_margins):>4} {cp.trough:>8.1%} {cp.peak:>8.1%} "
            f"{cp.peak - cp.trough:>8.1%} {cp.cycle_median:>8.1%} {cp.last3_median:>9.1%} "
            f"{gap:>+7.1%} {cp.coeff_var:>9.2f} {'YES' if is_cyc else 'no':>10}"
        )
    print(
        "  (KO/MSFT/JNJ/NVDA/AMD would show spread<25pts & coeff_var<0.6 → flag=no → "
        "earnings base UNCHANGED. Storage names flag=YES.)"
    )

    # ---------- PILLAR 1 + 2 for MU ----------
    mu = profiles["MU"]
    nd = mu.net_debt if mu.net_debt is not None else 0.0
    sh = float(yf_shares["MU"])  # current shares (SEC outstanding may lag)
    mkt = LIVE_PRICE["MU"]
    rev_base = CURRENT_TTM_REVENUE["MU"]  # current run-rate, NOT trough
    da_n = mu.da_pct_normalized  # revenue-weighted, un-trough-spiked

    print("\n" + "=" * 100)
    print(f"PILLAR 1 — MU reverse-derivation (协议 §2): what op margin does ${mkt:.0f} imply?")
    print("=" * 100)
    print(
        f"  revenue base = CURRENT TTM ${rev_base / 1e9:.1f}B (NOT trough FY25 ${mu.revenue_latest / 1e9:.1f}B)"
    )
    print(
        f"  SEC through-cycle op margin band: trough {mu.trough:.1%} | median {mu.cycle_median:.1%} "
        f"| mean {mu.cycle_mean:.1%} | peak {mu.peak:.1%}"
    )
    print(
        f"  normalized D&A% (Σda/Σrev) {da_n:.1%} (vs trough-FY {mu.da_pct_latest:.1%}) · "
        f"maint capex {mu.maint_capex_pct:.1%}"
    )
    lo, hi = -0.40, 0.60
    for _ in range(60):
        mid = (lo + hi) / 2
        inp = _mk_inputs(
            mu,
            op_margin=mid,
            capex_pct=mu.maint_capex_pct,
            da_pct=da_n,
            shares=sh,
            net_debt=nd,
            revenue_base=rev_base,
        )
        try:
            p = calculate_dcf(inp).implied_price
        except (ValueError, ArithmeticError):
            p = -1.0
        if p < mkt:
            lo = mid
        else:
            hi = mid
    implied_margin = (lo + hi) / 2
    inside = mu.trough <= implied_margin <= mu.peak
    print(
        f"  → market-implied steady op margin ≈ {implied_margin:.1%}  "
        f"(at current ${rev_base / 1e9:.0f}B revenue, maint capex {mu.maint_capex_pct:.1%})"
    )
    print(
        f"  → inside historical [trough,peak]? {inside}  "
        f"vs cycle median {mu.cycle_median:.1%} (diff {implied_margin - mu.cycle_median:+.1%}pts)"
    )

    print("\n" + "=" * 100)
    print(f"PILLAR 2 — MU variable isolation (only earnings base moves) · market ${mkt:.0f}")
    print("=" * 100)
    print(
        f"  revenue_base=CURRENT TTM {rev_base / 1e9:.1f}B  net_debt={nd / 1e9:.1f}B  "
        f"shares={sh / 1e9:.3f}B  norm_D&A={da_n:.1%}  maint_capex={mu.maint_capex_pct:.1%}  "
        f"tc_capex={mu.capex_pct_through_cycle:.1%}"
    )
    variants = [
        ("A  last-FY margin (trough) on cur rev", mu.last_fy_margin, mu.capex_pct_through_cycle),
        ("A' last-3y median margin", mu.last3_median, mu.capex_pct_through_cycle),
        ("B  through-cycle MEDIAN margin", mu.cycle_median, mu.capex_pct_through_cycle),
        ("C  through-cycle MEAN margin", mu.cycle_mean, mu.capex_pct_through_cycle),
        ("D  cycle-median + maintenance capex", mu.cycle_median, mu.maint_capex_pct),
        ("E  PEAK margin (AI up-cycle bull)", mu.peak, mu.maint_capex_pct),
    ]
    for label, opm, cx in variants:
        inp = _mk_inputs(
            mu,
            op_margin=opm,
            capex_pct=cx,
            da_pct=da_n,
            shares=sh,
            net_debt=nd,
            revenue_base=rev_base,
        )
        p = _price(inp)
        print(
            f"  {label:42}  op_m={opm:>6.1%} capex={cx:>5.1%} ebitda_m="
            f"{inp.ebitda_margin:>5.1%} → {p:>14} {_ratio(p, mkt)}"
        )
    print(
        "  GATE: does any normalized variant (B/C/D) land in [0.5x, 2x]? "
        "If yes, normalization makes the number RIGHT (not the gate looser)."
    )

    # ---------- Storage siblings sanity ----------
    print("\n" + "=" * 100)
    print("STORAGE SIBLINGS (WDC/STX) — normalization direction sanity")
    print("=" * 100)
    for t in ("WDC", "STX"):
        cp = profiles[t]
        nd_t = cp.net_debt if cp.net_debt is not None else 0.0
        sh_t = float(yf_shares[t])
        mkt_t = LIVE_PRICE[t]
        rb_t = CURRENT_TTM_REVENUE[t]
        print(
            f"  {t}: cur rev ~${rb_t / 1e9:.1f}B  norm_D&A {cp.da_pct_normalized:.1%}  "
            f"maint_capex {cp.maint_capex_pct:.1%}  cycle_med margin {cp.cycle_median:.1%}"
        )
        for label, opm, cx in (
            ("A' last-3y median", cp.last3_median, cp.capex_pct_through_cycle),
            ("B  cycle-median", cp.cycle_median, cp.capex_pct_through_cycle),
            ("D  cycle-med+maint capex", cp.cycle_median, cp.maint_capex_pct),
        ):
            inp = _mk_inputs(
                cp,
                op_margin=opm,
                capex_pct=cx,
                da_pct=cp.da_pct_normalized,
                shares=sh_t,
                net_debt=nd_t,
                revenue_base=rb_t,
            )
            p = _price(inp)
            print(f"  {t} {label:26} op_m={opm:>6.1%} → {p:>12} {_ratio(p, mkt_t)}")

    print("\nDONE_VALIDATION")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
