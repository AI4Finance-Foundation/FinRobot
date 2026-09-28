"""Protocol validation for the DCF recalibration (CLAUDE.md evidence protocol).

1. Variable isolation — each change (ERP / Blume / horizon / terminal) applied
   ALONE against the old baseline, per ticker, so the rebound attribution is
   explicit and side effects are visible.
2. Full-basket regression — growth mega-caps AND stable names (KO, JNJ): the
   stable names must stay sane (no Gordon blowup, no flip to absurd premium).
3. Reverse inference — what (constant growth | WACC) does the MARKET price
   imply under the old vs new parameter stack? If the old stack needs an absurd
   implied parameter to reach market and the new stack needs a plausible one,
   the recalibration is evidence-backed, not curve-fit.
"""

from __future__ import annotations

import asyncio
import sys

from finrobot.config import get_settings
from finrobot.engine.compute.coordinators.extractor import extract_financial_data
from finrobot.engine.compute.coordinators.historical_extractor import fetch_historical_metrics
from finrobot.engine.compute.operators.dcf import calculate_dcf, market_implied_check
from finrobot.engine.compute.operators.dcf_seed import seed_dcf_inputs
from finrobot.engine.data.factory import build_data_layer
from finrobot.engine.data.types import DataType
from finrobot.paths import SETTINGS_JSON
from finrobot.routes.settings import load_non_secret_settings
from finrobot.secret_store import create_secret_store
from finrobot.server import hydrate_settings_from_secrets

BASKET = sys.argv[1:] or ["MSFT", "NVDA", "AAPL", "AVGO", "GOOGL", "KO", "JNJ"]

OLD = dict(erp=0.055, blume=False, yrs=5, tg=0.025)
VARIANTS = [
    ("OLD-baseline", OLD),
    ("+ERP4.23only", dict(erp=0.0423, blume=False, yrs=5, tg=0.025)),
    ("+Blume-only ", dict(erp=0.055, blume=True, yrs=5, tg=0.025)),
    ("+10y-only   ", dict(erp=0.055, blume=False, yrs=10, tg=0.025)),
    ("+tg3.0-only ", dict(erp=0.055, blume=False, yrs=5, tg=0.030)),
    ("NEW-combined", dict(erp=0.0423, blume=True, yrs=10, tg=0.030)),
]


def un_blume(adjusted: float) -> float:
    """Invert adjust_beta_blume: raw = (adj − 1/3) × 3/2."""
    return (adjusted - 1.0 / 3.0) * 1.5


async def main() -> None:
    settings = get_settings(**load_non_secret_settings(SETTINGS_JSON))
    store, _ = create_secret_store()
    settings = await hydrate_settings_from_secrets(settings, store)
    dl = build_data_layer(settings)

    try:
        for t in BASKET:
            try:
                _fin = await dl.fetch_canonical(DataType.FINANCIALS, t)
                _price = await dl.fetch_canonical(DataType.PRICE, t)
                fin = extract_financial_data(_fin, _price)
                hist = await fetch_historical_metrics(dl, t)
            except Exception as e:  # noqa: BLE001
                print(f"\n{t}: data error {e}")
                continue
            price = fin.market.current_price
            print(f"\n=== {t}  market ${price:.2f} " + "=" * 40)

            # -- 1+2. variable isolation over the basket ------------------------
            for label, v in VARIANTS:
                inp = seed_dcf_inputs(
                    fin,
                    hist,
                    equity_risk_premium=float(v["erp"]),
                    projection_years=int(v["yrs"]),
                    terminal_growth_rate=float(v["tg"]),
                )
                if not v["blume"]:
                    # seed now always Blume-adjusts; invert to recover the raw beta
                    inp = inp.model_copy(update={"beta": max(0.3, min(2.5, un_blume(inp.beta)))})
                try:
                    r = calculate_dcf(inp)
                    print(
                        f"  {label}: WACC {r.wacc:6.2%}  fair ${r.implied_price:8.2f}"
                        f"  ({r.implied_price / price:4.0%} of mkt)"
                    )
                except ValueError as e:
                    print(f"  {label}: DCF degraded — {str(e)[:70]}")

            # -- 3. reverse inference: market-implied params, old vs new --------
            for label, v in (("OLD", OLD), ("NEW", VARIANTS[-1][1])):
                inp = seed_dcf_inputs(
                    fin,
                    hist,
                    equity_risk_premium=float(v["erp"]),
                    projection_years=int(v["yrs"]),
                    terminal_growth_rate=float(v["tg"]),
                )
                if not v["blume"]:
                    inp = inp.model_copy(update={"beta": max(0.3, min(2.5, un_blume(inp.beta)))})
                chk = market_implied_check(inp, price, horizon_years=v["yrs"])
                ig = (
                    f"{chk.implied_growth:.1%}" if chk.implied_growth is not None else "unreachable"
                )
                iw = f"{chk.implied_wacc:.2%}" if chk.implied_wacc is not None else "n/a"
                seeded_g = inp.revenue_growth_rates[0]
                print(
                    f"  [{label}] market implies: growth {ig} (seeded {seeded_g:.1%}) | WACC {iw}"
                )
    finally:
        # Non-server entrypoint: join the aiosqlite workers + checkpoint WAL so the
        # process exits cleanly instead of hanging on "Event loop is closed" (2026-06-24).
        from finrobot.engine.data.factory import shutdown_data_layer

        await shutdown_data_layer(dl)


if __name__ == "__main__":
    asyncio.run(main())
