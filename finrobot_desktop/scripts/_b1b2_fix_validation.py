"""Empirical validation for B1 (sniper reliability gate) + B2 (EV/EBITDA口径).

Runs the REAL deterministic technical-analysis path on the SAME cached AAPL
data the flagged report used, with the SAME `reliable=False` the report's
valuation_synthesis produced, and asserts:

  B1: sniper is NEUTRAL (levels-only) — no SHORT cover anchored to the withheld
      DCF target.
  B2: the band's `current` EV/EBITDA equals the comps chapter's value
      (canonical TTM), so the report no longer shows two口径.

No mocks: prices + band financials come from the live data layer (cache).
DCF inputs are reconstructed from the flagged artifact's own parameters.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

from finrobot.config import get_settings
from finrobot.engine.compute.coordinators.technical_payload import build_technical_analysis
from finrobot.engine.data.factory import build_data_layer
from finrobot.engine.models.financial import DCFInputs
from finrobot.paths import SETTINGS_JSON
from finrobot.routes.settings import load_non_secret_settings
from finrobot.secret_store import create_secret_store
from finrobot.server import hydrate_settings_from_secrets

ARTIFACTS_DB = Path.home() / ".finrobot" / "artifacts.db"
TICKER = sys.argv[1] if len(sys.argv) > 1 else "AAPL"


def _latest_artifact_payload(ticker: str) -> dict:
    con = sqlite3.connect(f"file:{ARTIFACTS_DB}?mode=ro", uri=True)
    try:
        row = con.execute(
            "SELECT payload FROM artifacts WHERE ticker=? ORDER BY created_at DESC LIMIT 1",
            (ticker,),
        ).fetchone()
    finally:
        con.close()
    if row is None:
        raise SystemExit(f"no artifact found for {ticker} in {ARTIFACTS_DB}")
    return json.loads(row[0])


async def main() -> int:
    d = _latest_artifact_payload(TICKER)
    fm = d["outputs"]["structured"]["financial_modeling"]
    dcf_inputs = DCFInputs(**fm["inputs"])
    dcf_target = fm["implied_price"]

    target = d["outputs"]["structured"]["peer_analysis"]["target"]
    comps_ev_ebitda = target["ev_ebitda"]  # canonical TTM, from comps chapter
    # Reproduce the helper the pipeline uses: (market_cap + net_debt) / TTM EBITDA.
    current_ev_ebitda = (target["market_cap"] + dcf_inputs.net_debt) / target["ebitda"]

    vs = d["outputs"]["structured"]["valuation_synthesis"]
    reliable = bool(vs["reliable"])  # the flagged report: False
    current_price = vs["current_price"]

    print(f"reliable (from artifact synthesis) = {reliable}")
    print(f"comps target ev_ebitda           = {comps_ev_ebitda:.4f}")
    print(f"recomputed current_ev_ebitda     = {current_ev_ebitda:.4f}")

    settings = get_settings(**load_non_secret_settings(SETTINGS_JSON))
    store, _ = create_secret_store()
    settings = await hydrate_settings_from_secrets(settings, store)
    data_layer = build_data_layer(settings)

    try:
        payload = await build_technical_analysis(
            ticker=TICKER,
            dcf_inputs=dcf_inputs,
            dcf_target=dcf_target,
            current_price=current_price,
            data_layer=data_layer,
            reliable=reliable,
            current_ev_ebitda=current_ev_ebitda,
        )

        sn = payload.sniper
        band = payload.historical_bands
        print("\n--- B1: sniper ---")
        print(f"direction   = {sn.direction if sn else None}")
        print(f"take_profit = {sn.take_profit if sn else None}")
        print(
            f"support/res = {sn.support_level if sn else None} / {sn.resistance_level if sn else None}"
        )
        print("\n--- B2: historical band ---")
        print(f"band.current = {band.current if band else None}")
        print(f"comps        = {comps_ev_ebitda:.4f}")
        if band:
            for w in band.warnings:
                print(f"band.warning: {w}")

        ok = True
        # B1
        assert sn is not None, "sniper unexpectedly None"
        if sn.direction != "NEUTRAL":
            print("FAIL B1: expected NEUTRAL, got", sn.direction)
            ok = False
        if sn.take_profit is not None:
            print("FAIL B1: directional take_profit leaked:", sn.take_profit)
            ok = False
        # B2
        assert band is not None and band.current is not None, "band/current None"
        if abs(band.current - comps_ev_ebitda) > 0.01:
            print(f"FAIL B2: band.current {band.current:.4f} != comps {comps_ev_ebitda:.4f}")
            ok = False

        print("\nRESULT:", "PASS — both contradictions resolved" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        # Non-server entrypoint: join the aiosqlite workers + checkpoint WAL so the
        # process exits cleanly instead of hanging on "Event loop is closed" (2026-06-24).
        from finrobot.engine.data.factory import shutdown_data_layer

        await shutdown_data_layer(data_layer)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
