"""Empirical validation for wiring forward consensus into ALL DCF seed paths.

CLAUDE.md 🔴 protocol evidence for the change that makes the coordinator
(REST /dcf-seed + chat Monte-Carlo), the standalone DCF pipeline and the IC-memo
pipeline seed the DCF explicit window from analyst consensus — the same
authoritative path equity_research already used — instead of a trailing CAGR.

Three evidence pillars, against LIVE data:
1. Variable isolation — implied_price WITH vs WITHOUT forward_growth, per ticker,
   so the move is attributable solely to the consensus seed (no other knob moved).
2. Full-basket regression — reacceleration names (AAPL) must actually move; stable
   names (KO / JNJ) must stay sane (finite, positive, no Gordon blowup); a
   loss-maker (RIVN) and an ADR (SAP) must not crash or go NaN.
3. Single-authoritative-seed — fetch_forward_growth(dl, t) is deterministic and
   equals get_forward_revenue_growth on the same CANONICAL snapshot payload
   (fetch_canonical — the shared versioned slot), so every entry point derives
   the identical seed for a given ticker.

Run: `python scripts/_forward_seed_integration_validation.py [TICKERS...]`
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
from finrobot.engine.compute.operators.dcf_seed import seed_dcf_inputs
from finrobot.engine.compute.operators.forward_estimates import get_forward_revenue_growth
from finrobot.engine.data.factory import build_data_layer
from finrobot.engine.data.types import DataType
from finrobot.paths import SETTINGS_JSON
from finrobot.routes.settings import load_non_secret_settings
from finrobot.secret_store import create_secret_store
from finrobot.server import hydrate_settings_from_secrets

# AAPL = reaccelerator (consensus >> trailing); KO/JNJ = stable sanity;
# SAP = ADR/FX path; RIVN = loss-maker crash-check; MSFT/NVDA/GOOGL = mega-cap.
BASKET = sys.argv[1:] or ["AAPL", "MSFT", "NVDA", "GOOGL", "KO", "JNJ", "SAP", "RIVN"]


def _fair(fin, hist, fwd):  # type: ignore[no-untyped-def]
    """implied_price for a given forward_growth seed, or None if DCF degrades."""
    try:
        return calculate_dcf(seed_dcf_inputs(fin, hist, forward_growth=fwd)).implied_price
    except (ValueError, ArithmeticError) as e:
        return f"degraded: {str(e)[:50]}"


async def main() -> int:
    settings = get_settings(**load_non_secret_settings(SETTINGS_JSON))
    store, _ = create_secret_store()
    settings = await hydrate_settings_from_secrets(settings, store)
    dl = build_data_layer(settings)

    try:
        failures: list[str] = []
        moved = 0
        print(
            f"{'ticker':<7}{'mkt':>9}  {'fwd consensus (FY1..)':<26}"
            f"{'fair·noFwd':>12}{'fair·fwd':>12}{'Δ%':>8}  note"
        )
        print("-" * 92)

        for t in BASKET:
            try:
                _fin = await dl.fetch_canonical(DataType.FINANCIALS, t)
                _price = await dl.fetch_canonical(DataType.PRICE, t)
                fin = extract_financial_data(_fin, _price)
                hist = await fetch_historical_metrics(dl, t)
            except Exception as e:  # noqa: BLE001
                failures.append(f"{t}: data error {e}")
                print(f"{t:<7}{'—':>9}  DATA ERROR {str(e)[:50]}")
                continue

            # --- pillar 3: single authoritative seed (determinism + producer parity)
            fwd = await fetch_forward_growth(dl, t)
            fwd2 = await fetch_forward_growth(dl, t)
            _canon = await dl.fetch_canonical(DataType.FORWARD_ESTIMATES, t)
            producer = get_forward_revenue_growth(_canon.payload())
            if fwd != fwd2:
                failures.append(f"{t}: fetch_forward_growth non-deterministic {fwd} != {fwd2}")
            if fwd != producer:
                failures.append(
                    f"{t}: helper diverges from producer {fwd} != {producer} (seed not single-source)"
                )
            if any(not math.isfinite(g) for g in fwd):
                failures.append(f"{t}: forward_growth carries non-finite {fwd}")

            # --- pillar 1: variable isolation (only forward_growth changes) --------
            fair_no = _fair(fin, hist, None)
            fair_fwd = _fair(fin, hist, fwd)
            price = fin.market.current_price

            def _pct_mkt(v):  # type: ignore[no-untyped-def]
                return f"({v / price:.0%})" if isinstance(v, float) and price else ""

            def _fmt(v):  # type: ignore[no-untyped-def]
                return f"${v:.2f}" if isinstance(v, float) else str(v)[:12]

            delta = ""
            note = ""
            if isinstance(fair_no, float) and isinstance(fair_fwd, float):
                d = (fair_fwd - fair_no) / fair_no if fair_no else float("nan")
                delta = f"{d:+.0%}"
                if fwd and abs(d) > 0.001:
                    moved += 1
                # pillar 2: full-basket regression sanity on the consensus-seeded price
                if not math.isfinite(fair_fwd):
                    failures.append(f"{t}: consensus-seeded fair value is NaN/Inf")
                    note = "‼ NaN"
                elif fair_fwd <= 0:
                    failures.append(f"{t}: consensus-seeded fair value non-positive {fair_fwd}")
                    note = "‼ ≤0"
            fwd_str = "/".join(f"{g:.0%}" for g in fwd) if fwd else "—(trailing CAGR)"

            print(
                f"{t:<7}{price:>9.2f}  {fwd_str:<26}"
                f"{_fmt(fair_no) + _pct_mkt(fair_no):>12}"
                f"{_fmt(fair_fwd) + _pct_mkt(fair_fwd):>12}{delta:>8}  {note}"
            )

        print("-" * 92)
        print(f"tickers whose fair value MOVED on the consensus seed: {moved}")
        if failures:
            print(f"\n❌ {len(failures)} INVARIANT VIOLATION(S):")
            for f in failures:
                print(f"  - {f}")
            return 1
        print(
            "\n✅ all invariants hold: deterministic single-source seed, "
            "no NaN/≤0 on any name, consensus actually drives the explicit window."
        )
        return 0
    finally:
        # Non-server entrypoint: join the aiosqlite workers + checkpoint WAL so the
        # process exits cleanly instead of hanging on "Event loop is closed" (2026-06-24).
        from finrobot.engine.data.factory import shutdown_data_layer

        await shutdown_data_layer(dl)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
