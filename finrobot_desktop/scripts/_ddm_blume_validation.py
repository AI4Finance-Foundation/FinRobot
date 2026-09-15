"""Empirical validation: apply the asymmetric Blume beta adjustment to the DDM
seed, matching the DCF seed (lead-adjudicated 2026-06-22 — cost of equity is a
property of the equity, not the valuation method, so DCF and DDM must use the
same beta for the same stock).

CLAUDE.md 🔴 EMPIRICAL VALIDATION evidence for adding ``adjust_beta_blume`` to
``seed_ddm_inputs``. The change surface is exactly one line (ddm_seed.py beta
pick → Blume → clamp); MC/sensitivity inherit the DCF beta, so DDM is the only
gap. This script proves the change is safe and attributable, on LIVE data.

Five evidence pillars + one reverse-engineering signal:
1. Pick-replication faithfulness — our reconstructed pre-clamp raw beta, re-clamped,
   EQUALS the seed's current DDMInputs.beta (else our isolation is not faithful).
2. β≤1 safety — for raw beta ≤ 1.0 the Blume branch is a no-op, so the DDM value
   must NOT move by a cent (defensive low-β payers untouched — KO/PG/utilities).
3. No new degradation — every name valid under the current beta stays finite & >0
   under the Blume beta (lowering CoE can't blow up a Gordon spread).
4. Direction (β>1) — Blume lowers beta → lowers CoE → RAISES the DDM value
   (less bearish), the same correction the DCF already gets.
5. Inconsistency-was-real — for β>1 the DCF beta (Blume) already differs from the
   DDM beta (raw); we quantify the CoE gap the fix closes.
Reverse-engineering: market-implied beta (solve DDM == price). For β>1 names the
raw regression beta should sit ABOVE the market-implied beta, and Blume moves the
DDM beta TOWARD market-implied — the empirical case that raw is the noisy one.

Run: `python scripts/_ddm_blume_validation.py [TICKERS...]`
(uses the local FMP key via hydrate_settings_from_secrets — no backend needed).
"""

from __future__ import annotations

import asyncio
import math
import sys

from finrobot.config import get_settings
from finrobot.engine.compute.coordinators.extractor import extract_financial_data
from finrobot.engine.compute.coordinators.historical_extractor import fetch_historical_metrics
from finrobot.engine.compute.operators.dcf_seed import (
    _BETA_BAND_CEILING,
    _BETA_BAND_FLOOR,
    _BETA_IMPLAUSIBLY_LOW_REASON,
    _BETA_OUT_OF_BAND_REASON,
    _BETA_RELATIVE_FLOOR,
    _BETA_RELATIVE_INDUSTRY_MIN,
    _bank_beta_proxy,
    _pick_with_provenance,
    seed_dcf_inputs,
)
from finrobot.engine.compute.operators.ddm import calculate_ddm
from finrobot.engine.compute.operators.ddm_seed import _BETA_CAP, _BETA_FLOOR, seed_ddm_inputs
from finrobot.engine.compute.operators.wacc import adjust_beta_blume
from finrobot.engine.data.factory import build_data_layer
from finrobot.engine.data.industry_defaults import get_industry_default
from finrobot.engine.data.types import DataType
from finrobot.engine.models.financial import DDMInputs
from finrobot.engine.primitives.industry import is_bank
from finrobot.paths import SETTINGS_JSON
from finrobot.routes.settings import load_non_secret_settings
from finrobot.secret_store import create_secret_store
from finrobot.server import hydrate_settings_from_secrets

# Deliberate cross-sector dividend basket — LIVE beta decides who is β>1 vs β≤1,
# we do NOT pre-classify (stale-memory weight = 0 on live quants). Financials /
# energy / industrials skew high-β; staples / utilities / telecom skew low-β
# (the safety control). A couple of non-payers confirm DDM is structurally N/A
# (raises before beta even matters) — unaffected by the change.
BASKET = sys.argv[1:] or [
    # likely β>1 (the names the fix targets)
    "JPM",
    "GS",
    "MS",
    "BAC",
    "XOM",
    "CVX",
    "CAT",
    "MMM",
    "TXN",
    "QCOM",
    # likely β≤1 (defensive — the safety control, must NOT move)
    "KO",
    "PG",
    "JNJ",
    "SO",
    "DUK",
    "VZ",
    "MCD",
    # non-payers — DDM N/A, must stay N/A
    "TSLA",
    "AMZN",
]


def _clamp_ddm(b: float) -> float:
    return max(_BETA_FLOOR, min(_BETA_CAP, b))


def _ddm_value(inputs: DDMInputs, beta: float) -> float:
    """DDM equity value per share at a given beta, or +inf if the low-beta CoE
    falls below the Gordon spread floor (an unbounded value, not a real one)."""
    try:
        return calculate_ddm(inputs.model_copy(update={"beta": beta})).equity_value_per_share
    except ValueError:
        return float("inf")


def _implied_beta(inputs: DDMInputs, price: float) -> float | str:
    """Beta at which DDM value == market price (DDM value is monotone decreasing
    in beta). Bounded to the DDMInputs Field domain [0, 3]."""
    lo, hi = 0.0, 3.0
    if _ddm_value(inputs, hi) > price:
        return ">3"
    if _ddm_value(inputs, lo) < price:
        return "<0"
    for _ in range(60):
        mid = (lo + hi) / 2
        if _ddm_value(inputs, mid) > price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


async def main() -> int:
    settings = get_settings(**load_non_secret_settings(SETTINGS_JSON))
    store, _ = create_secret_store()
    settings = await hydrate_settings_from_secrets(settings, store)
    dl = build_data_layer(settings)

    try:
        failures: list[str] = []
        hdr = (
            f"{'tkr':<6}{'price':>8}{'rawβ':>7}{'DCFβ':>7}{'DDMβnow':>8}{'DDMβfix':>8}"
            f"{'CoEnow':>8}{'CoEfix':>8}{'DDMnow':>9}{'DDMfix':>9}{'Δ%':>7}{'implβ':>7}  grp"
        )
        print(hdr)
        print("-" * len(hdr))

        for t in BASKET:
            try:
                _fin = await dl.fetch_canonical(DataType.FINANCIALS, t)
                _price = await dl.fetch_canonical(DataType.PRICE, t)
                fin = extract_financial_data(_fin, _price)
            except Exception as e:  # noqa: BLE001
                failures.append(f"{t}: data error {e}")
                print(f"{t:<6}  DATA ERROR {str(e)[:60]}")
                continue

            price = fin.market.current_price

            # Reconstruct the DDM beta pick exactly as seed_ddm_inputs does:
            # provider beta when valid, else the industry proxy; for banks, the
            # relative low-beta glitch check uses the bank beta proxy floor.
            industry = get_industry_default(fin.market.industry)
            bank_issuer = is_bank(industry=fin.market.industry, sector=fin.market.sector)
            beta_proxy, beta_proxy_label = _bank_beta_proxy(industry, is_bank_issuer=bank_issuer)
            raw_picked, beta_source = _pick_with_provenance(
                ticker_value=fin.market.beta,
                ticker_label="provider-reported 5y beta",
                industry_value=beta_proxy,
                industry_label=beta_proxy_label,
                floor=_BETA_BAND_FLOOR,
                ceiling=_BETA_BAND_CEILING,
                rejected_ticker_reason=_BETA_OUT_OF_BAND_REASON,
                reject_value_fmt="{:.2f}",
                relative_floor=_BETA_RELATIVE_FLOOR if bank_issuer else None,
                relative_floor_industry_min=_BETA_RELATIVE_INDUSTRY_MIN,
                relative_reject_reason=_BETA_IMPLAUSIBLY_LOW_REASON,
            )
            provider_beta_used = beta_source == "provider-reported 5y beta"

            beta_now = _clamp_ddm(raw_picked)
            beta_fix = _clamp_ddm(
                adjust_beta_blume(raw_picked) if provider_beta_used else raw_picked
            )

            # DCF beta for the SAME stock (already Blume-adjusted) — proves the gap.
            try:
                hist = await fetch_historical_metrics(dl, t)
                dcf_beta: float | None = seed_dcf_inputs(fin, hist).beta
            except Exception:  # noqa: BLE001
                dcf_beta = None

            # DDM seed (current path). Non-payers raise here → structurally N/A.
            try:
                ddm_inputs = seed_ddm_inputs(fin, _fin)
            except ValueError:
                print(
                    f"{t:<6}{price:>8.2f}{raw_picked:>7.2f}"
                    f"{(f'{dcf_beta:.2f}' if dcf_beta is not None else '—'):>7}"
                    f"{'—':>8}{'—':>8}{'—':>8}{'—':>8}{'—':>9}{'—':>9}{'—':>7}{'—':>7}  no-div (DDM N/A — unaffected)"
                )
                continue

            # PILLAR 1 — POST-IMPLEMENTATION: the seed now applies the asymmetric Blume,
            # so its beta must equal beta_fix (our reconstructed pick → Blume → clamp).
            # beta_now is the pre-fix reconstruction, kept for the before/after columns.
            if abs(beta_fix - ddm_inputs.beta) > 1e-9:
                failures.append(
                    f"{t}: seed beta {ddm_inputs.beta:.4f} != expected Blume-adjusted {beta_fix:.4f}"
                )

            erp = ddm_inputs.equity_risk_premium
            coe_now = ddm_inputs.risk_free_rate + beta_now * erp
            coe_fix = ddm_inputs.risk_free_rate + beta_fix * erp

            v_now = _ddm_value(ddm_inputs, beta_now)
            v_fix = _ddm_value(ddm_inputs, beta_fix)
            implied = _implied_beta(ddm_inputs, price) if price else "—"

            grp = ("β>1" if raw_picked > 1.0 else "β≤1") if provider_beta_used else "proxy"
            note = ""

            # PILLAR 2 — β≤1 must not move at all.
            if (not provider_beta_used or raw_picked <= 1.0) and (
                abs(beta_fix - beta_now) > 1e-12
                or (math.isfinite(v_now) and math.isfinite(v_fix) and abs(v_fix - v_now) > 1e-6)
            ):
                failures.append(
                    f"{t}: no-Blume beta branch moved (beta {beta_now}->{beta_fix}, value {v_now}->{v_fix})"
                )
                note = "‼ no-Blume moved"

            # PILLAR 3 — no new degradation.
            if math.isfinite(v_now) and v_now > 0 and not (math.isfinite(v_fix) and v_fix > 0):
                failures.append(f"{t}: valid-now became invalid-fix ({v_fix})")
                note = "‼ new degrade"

            # PILLAR 4 — β>1 direction: Blume lowers beta → value rises.
            if (
                provider_beta_used
                and raw_picked > 1.0
                and math.isfinite(v_now)
                and math.isfinite(v_fix)
            ):
                if not (beta_fix < beta_now - 1e-9 and coe_fix < coe_now and v_fix > v_now - 1e-9):
                    failures.append(
                        f"{t}: β>1 wrong direction (β {beta_now}->{beta_fix}, val {v_now:.2f}->{v_fix:.2f})"
                    )
                    note = "‼ wrong dir"

            delta = (v_fix - v_now) / v_now if (math.isfinite(v_now) and v_now) else float("nan")
            implied_s = f"{implied:.2f}" if isinstance(implied, float) else str(implied)
            print(
                f"{t:<6}{price:>8.2f}{raw_picked:>7.2f}"
                f"{(f'{dcf_beta:.2f}' if dcf_beta is not None else '—'):>7}"
                f"{beta_now:>8.2f}{beta_fix:>8.2f}{coe_now:>8.1%}{coe_fix:>8.1%}"
                f"{_fmt_money(v_now):>9}{_fmt_money(v_fix):>9}"
                f"{(f'{delta:+.1%}' if math.isfinite(delta) else '—'):>7}{implied_s:>7}  {grp} {note}"
            )

        print("-" * len(hdr))
        if failures:
            print(f"\n❌ {len(failures)} INVARIANT VIOLATION(S):")
            for f in failures:
                print(f"  - {f}")
            return 1
        print(
            "\n✅ all pillars hold: pick replication faithful; β≤1 defensive payers "
            "unmoved; no new degradation; β>1 names move the right way (CoE down, "
            "value up) — the same correction DCF already applies."
        )
        return 0
    finally:
        # Non-server entrypoint: join the aiosqlite workers + checkpoint WAL so the
        # process exits cleanly instead of hanging on "Event loop is closed" (2026-06-24).
        from finrobot.engine.data.factory import shutdown_data_layer

        await shutdown_data_layer(dl)


def _fmt_money(v: float) -> str:
    if not math.isfinite(v):
        return "∞"
    return f"${v:.2f}"


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
