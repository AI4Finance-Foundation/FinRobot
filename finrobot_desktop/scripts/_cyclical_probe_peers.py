"""T2/T3 probe for cyclical-normalization design — pull REAL payloads, never infer.

Three things the design hinges on, none assumed:
1. Live MU price (T3: my memory weight = 0 on live quants; re-probe).
2. MU's real PEER_CANDIDATES payload — confirm the all-logic-semis pool and
   whether the storage names (WDC/SNDK/STX) even appear in industry/stock_peers.
3. FMP /profile + /quote for MU, WDC, SNDK, STX — their REAL industry/sector
   labels and data availability (project's repeated trap: inferring peers).

Run: `python scripts/_cyclical_probe_peers.py`
(keychain FMP key via hydrate_settings_from_secrets — no backend needed).
"""

from __future__ import annotations

import asyncio

from finrobot.config import get_settings
from finrobot.engine.data.factory import build_data_layer
from finrobot.engine.data.types import DataType
from finrobot.paths import SETTINGS_JSON
from finrobot.routes.settings import load_non_secret_settings
from finrobot.secret_store import create_secret_store
from finrobot.server import hydrate_settings_from_secrets

STORAGE_CANDIDATES = ["MU", "WDC", "SNDK", "STX"]


async def main() -> int:
    settings = get_settings(**load_non_secret_settings(SETTINGS_JSON))
    store, _ = create_secret_store()
    settings = await hydrate_settings_from_secrets(settings, store)
    print(f"FMP key present: {bool(settings.fmp_api_key)}")
    dl = build_data_layer(settings)

    try:
        # ---- 1+3. Live quote + profile (industry/sector/data availability) ------
        print("\n" + "=" * 100)
        print("PROFILE + LIVE QUOTE — REAL FMP payload per ticker (industry tag is load-bearing)")
        print("=" * 100)
        for t in STORAGE_CANDIDATES:
            try:
                prof_res = await dl.fetch(DataType.PROFILE, t)
                prof = prof_res.data or {}
            except Exception as e:  # noqa: BLE001
                print(f"\n{t}: PROFILE fetch FAILED — {type(e).__name__}: {str(e)[:150]}")
                prof = {}
            try:
                q_res = await dl.fetch(DataType.QUOTE, t)
                q = q_res.data or {}
            except Exception as e:  # noqa: BLE001
                print(f"{t}: QUOTE fetch FAILED — {type(e).__name__}: {str(e)[:150]}")
                q = {}
            price = q.get("price") or q.get("current_price")
            mcap = q.get("market_cap") or prof.get("market_cap")
            print(f"\n--- {t} ---")
            print(f"  company   : {prof.get('company_name') or prof.get('companyName')}")
            print(f"  industry  : {prof.get('industry')!r}")
            print(f"  sector    : {prof.get('sector')!r}")
            print(f"  country   : {prof.get('country')!r}  currency: {prof.get('currency')!r}")
            print(f"  live price: {price}   market_cap: {mcap}")
            print(f"  pe(quote) : {q.get('pe')}   eps(quote): {q.get('eps')}")
            # description snippet — what the role-classifier text actually sees
            desc = (prof.get("description") or "")[:240]
            print(f"  desc[:240]: {desc}")

        # ---- 2. MU PEER_CANDIDATES — the actual pool the screen sees ------------
        print("\n" + "=" * 100)
        print("MU PEER_CANDIDATES — REAL pool (does any storage name appear?)")
        print("=" * 100)
        try:
            pc_res = await dl.fetch(DataType.PEER_CANDIDATES, "MU")
            pc = pc_res.data or {}
        except Exception as e:  # noqa: BLE001
            print(f"PEER_CANDIDATES fetch FAILED — {type(e).__name__}: {str(e)[:200]}")
            pc = {}
        if pc:
            prof = pc.get("profile") or {}
            print(
                f"target profile industry={prof.get('industry')!r} sector={prof.get('sector')!r} "
                f"mcap={prof.get('market_cap')}"
            )
            print(f"stock_peers     : {pc.get('stock_peers')}")
            print(f"industry_screen : {pc.get('industry_screen')}")
            print(f"sector_screen   : {pc.get('sector_screen')}")
            # per-candidate profile industry labels (the role/affinity inputs)
            profiles = pc.get("profiles") or {}
            print("\nper-candidate (sym → industry | sector | mcap):")
            for sym in sorted(profiles.keys()):
                p = profiles[sym]
                print(
                    f"  {sym:6} {str(p.get('industry'))[:34]:34} | "
                    f"{str(p.get('sector'))[:22]:22} | mcap={p.get('market_cap')}"
                )
            quotes = pc.get("quotes") or {}
            print(f"\nquotes keys present: {sorted(quotes.keys())}")
            # Is any of WDC/SNDK/STX in the candidate universe at all?
            universe = set()
            for key in ("stock_peers", "industry_screen", "sector_screen"):
                universe |= {str(s).upper() for s in (pc.get(key) or [])}
            for cand in ("WDC", "SNDK", "STX"):
                print(f"  {cand} in MU candidate universe? {cand in universe}")

        print("\nDONE")
        return 0
    finally:
        # Non-server entrypoint: join the aiosqlite workers + checkpoint WAL so the
        # process exits cleanly instead of hanging on "Event loop is closed" (2026-06-24).
        from finrobot.engine.data.factory import shutdown_data_layer

        await shutdown_data_layer(dl)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
