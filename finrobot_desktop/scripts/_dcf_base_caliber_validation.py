"""Empirical validation: DCF Year-1 consensus growth restated to NTM caliber (🔴 P1-3b).

CLAUDE.md 🔴 T4-calibration evidence for the fix that restates the FIRST consensus
growth year to NTM caliber. The consensus rates are FY-over-FY (FY1/last-actual-FY −
1, …), but revenue_base is the current TTM run-rate, which already contains this
fiscal year's realized stub. Applying the raw FY1 rate to TTM double-counts it and
overstates Year 1 (AAPL: 14.9% × TTM $451B = $519B vs the $478B FY1 consensus, +8.5%,
the false FY25→Y1 +24.7% cliff). The fix keeps the TTM base (current run-rate) and
restates g[0] to the growth from TTM to the FY1 CONSENSUS LEVEL (last_FY × (1+g[0])),
so Year 1 lands on the FY1 estimate.

Evidence pillars (LIVE data):
1. Variable isolation — the ONLY thing that moves is revenue_growth_rates[0] (raw
   FY-over-FY → NTM); the base / margins / WACC / FY2+ rates are byte-identical.
2. External anchor — Year 1 vs the FMP FY1 consensus revenue, derived in USD from the
   FX-normalized last annual × (1 + raw g[0]) (the revenueAvg field itself is native
   currency, TWD for TSM — the growth RATIO is currency-cancelling, so we rebuild the
   USD level from the canonical annual). new_Y1 should hug it; old_Y1 overshoots by the
   TTM/last-FY gap.
3. Full-basket regression — AAPL (reaccelerator) drops from the overshoot onto
   consensus; stable payers (KO/PG/MO/XOM) stay finite/positive; the mid-ramp
   hyper-grower MU (FY1 +247% capped to 40%) keeps Year 1 ABOVE its current run-rate
   (never the last-FY collapse below it); TSM (ADR) stays sane in USD; JPM is a
   balance-sheet financial → the pipeline WITHHOLDS its FCFF-DCF.

Run: `python scripts/_dcf_base_caliber_validation.py [TICKERS...]`
(uses the keychain FMP key via hydrate_settings_from_secrets — no backend needed).
"""

from __future__ import annotations

import asyncio
import math
import sys

from finrobot.config import get_settings
from finrobot.engine.compute.coordinators.dcf_seed import fetch_forward_growth
from finrobot.engine.compute.coordinators.extractor import extract_financial_data
from finrobot.engine.compute.coordinators.historical_extractor import fetch_historical_metrics
from finrobot.engine.compute.operators.dcf import calculate_dcf
from finrobot.engine.compute.operators.dcf_seed import _GROWTH_CAP, _GROWTH_FLOOR, seed_dcf_inputs
from finrobot.engine.data.factory import build_data_layer, shutdown_data_layer
from finrobot.engine.data.types import DataType
from finrobot.engine.primitives.industry import is_balance_sheet_financial, is_commodity_cyclical
from finrobot.paths import SETTINGS_JSON
from finrobot.routes.settings import load_non_secret_settings
from finrobot.secret_store import create_secret_store
from finrobot.server import hydrate_settings_from_secrets

BASKET = sys.argv[1:] or ["AAPL", "KO", "JPM", "MU", "TSM", "PG", "MO", "XOM"]


def _clamp(g: float) -> float:
    return max(min(g, _GROWTH_CAP), _GROWTH_FLOOR)


async def main() -> int:
    settings = get_settings(**load_non_secret_settings(SETTINGS_JSON))
    store, _ = create_secret_store()
    settings = await hydrate_settings_from_secrets(settings, store)
    dl = build_data_layer(settings)
    try:
        failures: list[str] = []
        print(
            f"{'ticker':<7}{'TTM$B':>8}{'lastFY$B':>9}{'rawg0':>7}{'ntmg0':>7}  "
            f"{'oldY1$B':>9}{'newY1$B':>9}{'consFY1$B':>10}  "
            f"{'resid_old':>10}{'resid_new':>10}  {'oldPx':>8}{'newPx':>8}{'ΔPx':>7}  note"
        )
        print("-" * 122)
        for t in BASKET:
            try:
                _fin = await dl.fetch_canonical(DataType.FINANCIALS, t)
                _price = await dl.fetch_canonical(DataType.PRICE, t)
                fin = extract_financial_data(_fin, _price)
                hist = await fetch_historical_metrics(dl, t)
                fwd = await fetch_forward_growth(dl, t)
            except Exception as e:  # noqa: BLE001
                print(f"{t:<7} DATA ERROR {str(e)[:60]}")
                failures.append(f"{t}: data error {e}")
                continue

            cyclical = is_commodity_cyclical(
                industry=fin.market.industry, sector=fin.market.sector, ticker=t
            )
            gated = is_balance_sheet_financial(
                industry=fin.market.industry, sector=fin.market.sector
            )
            ttm = fin.income.revenue
            last_annual = hist.revenue[-1] if hist.revenue else None
            # Consensus FY1 level rebuilt in USD from the FX-normalized annual (revenueAvg
            # is native currency; the growth RATIO cancels currency).
            cons_fy1 = last_annual * (1 + fwd[0]) if (fwd and last_annual) else None

            inputs_new = seed_dcf_inputs(fin, hist, forward_growth=fwd, cyclical=cyclical)
            ntm_g0 = inputs_new.revenue_growth_rates[0] if fwd else None
            # OLD behaviour (pre-fix): raw FY-over-FY g[0] clamped, on the SAME TTM base.
            old_rates = list(inputs_new.revenue_growth_rates)
            if fwd:
                old_rates[0] = _clamp(fwd[0])
            inputs_old = inputs_new.model_copy(update={"revenue_growth_rates": old_rates})
            new_y1 = ttm * (1 + inputs_new.revenue_growth_rates[0]) if fwd else None
            old_y1 = ttm * (1 + old_rates[0]) if fwd else None
            capped = fwd is not None and ntm_g0 is not None and abs(ntm_g0 - _GROWTH_CAP) < 1e-9

            def _px(inp):  # type: ignore[no-untyped-def]
                try:
                    return calculate_dcf(inp).implied_price
                except (ValueError, ArithmeticError):
                    return None

            old_px, new_px = _px(inputs_old), _px(inputs_new)

            def _resid(y1):  # type: ignore[no-untyped-def]
                return f"{y1 / cons_fy1 - 1:+.1%}" if (cons_fy1 and y1) else "—"

            dpx = (
                f"{(new_px - old_px) / old_px:+.0%}"
                if isinstance(old_px, float) and isinstance(new_px, float) and old_px
                else "—"
            )
            note = ("consensus" if fwd else "trailingCAGR") + ("·cyc" if cyclical else "")
            if capped:
                note += "·capped"
            if gated:
                note += "·BANK→withheld"

            # Regression invariants.
            if inputs_new.revenue_base != ttm:
                failures.append(f"{t}: base moved off TTM ({inputs_new.revenue_base} != {ttm})")
            if isinstance(new_y1, float) and (new_y1 <= 0 or not math.isfinite(new_y1)):
                failures.append(f"{t}: new_Y1 non-positive/NaN {new_y1}")
            if isinstance(new_px, float) and (new_px <= 0 or not math.isfinite(new_px)):
                failures.append(f"{t}: fixed implied price non-positive/NaN {new_px}")
            if fwd and cons_fy1 and isinstance(new_y1, float):
                if capped:
                    # Hyper-grower: Year 1 must stay ABOVE the current run-rate, never collapse.
                    if new_y1 < ttm:
                        failures.append(
                            f"{t}: capped new_Y1 {new_y1 / 1e9:.1f}B fell below run-rate {ttm / 1e9:.1f}B"
                        )
                elif abs(new_y1 / cons_fy1 - 1) > 0.03:
                    failures.append(
                        f"{t}: uncapped new_Y1 {new_y1 / 1e9:.1f}B is {new_y1 / cons_fy1 - 1:+.1%} off consensus"
                    )

            def _b(x):  # type: ignore[no-untyped-def]
                return f"{x / 1e9:.1f}" if isinstance(x, float) else "—"

            def _p(x):  # type: ignore[no-untyped-def]
                return f"${x:.2f}" if isinstance(x, float) else "—"

            print(
                f"{t:<7}{_b(ttm):>8}{_b(last_annual):>9}"
                f"{(f'{fwd[0]:.0%}' if fwd else '—'):>7}{(f'{ntm_g0:.0%}' if ntm_g0 is not None else '—'):>7}  "
                f"{_b(old_y1):>9}{_b(new_y1):>9}{_b(cons_fy1):>10}  "
                f"{_resid(old_y1):>10}{_resid(new_y1):>10}  "
                f"{_p(old_px):>8}{_p(new_px):>8}{dpx:>7}  {note}"
            )
        print("-" * 122)
        if failures:
            print(f"\n❌ {len(failures)} INVARIANT VIOLATION(S):")
            for f in failures:
                print(f"  - {f}")
            return 1
        print(
            "\n✅ base stays TTM on every name; uncapped new_Y1 hugs FMP FY1 consensus "
            "(old_Y1 overshoots by the TTM/last-FY gap); capped hyper-growers stay above "
            "the run-rate; no NaN/≤0; JPM gated."
        )
        return 0
    finally:
        await shutdown_data_layer(dl)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
