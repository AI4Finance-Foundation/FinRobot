"""Pre-implementation validation: deterministic peer selection for comps_pe.

Evidence this produces (CLAUDE.md evidence protocol):
1. Determinism — run the candidate-pool builder + production multiples math
   twice per ticker; medians must be byte-identical (vs the LLM path's observed
   $487→$636 swing on MSFT within one day).
2. Sanity — resulting core-PE median and comps_pe per ticker, side by side with
   the observed LLM-run values and the as-reported external peer medians.
3. Set quality — print the chosen peers so business-comparability is reviewable.
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import MagicMock

from finrobot.config import get_settings
from finrobot.engine.compute.operators.peer_screen import screen_peers
from finrobot.engine.compute.coordinators.extractor import extract_financial_data
from finrobot.engine.data.factory import build_data_layer
from finrobot.engine.data.types import DataType
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.models.financial import PeerComps
from finrobot.engine.pipelines._helpers import execute_peer_analysis
from finrobot.paths import SETTINGS_JSON
from finrobot.routes.settings import load_non_secret_settings
from finrobot.secret_store import create_secret_store
from finrobot.server import hydrate_settings_from_secrets

TICKERS = sys.argv[1:] or ["MSFT", "KO", "NVDA"]


async def main() -> None:
    settings = get_settings(**load_non_secret_settings(SETTINGS_JSON))
    store, _ = create_secret_store()
    settings = await hydrate_settings_from_secrets(settings, store)
    data_layer = build_data_layer(settings)
    deps = FinRobotDeps(data_layer=data_layer, settings=settings, skill_runtime=None)

    try:
        for t in TICKERS:
            _fin = await deps.data_layer.fetch_canonical(DataType.FINANCIALS, t)
            _price = await deps.data_layer.fetch_canonical(DataType.PRICE, t)
            fin = extract_financial_data(_fin, _price)
            candidate_payload = await deps.data_layer.fetch(DataType.PEER_CANDIDATES, t)
            screen = screen_peers(candidate_payload.data, t)
            peers = screen.tickers
            print(f"\n=== {t} (industry: {fin.market.industry or ''}) ===")
            print(f"  deterministic peers: {peers}")
            print(f"  screen rationale: {screen.rationale}")

            medians = []
            for run in (1, 2):
                out = await execute_peer_analysis(
                    MagicMock(), deps, "", {"data_collection": fin}, t, peers=peers
                )
                pc = out.structured
                assert isinstance(pc, PeerComps)
                core_ni = pc.target.core_net_income
                shares = fin.market.shares_outstanding
                comps = (
                    pc.median_core_pe * (core_ni / shares)
                    if pc.median_core_pe and core_ni and core_ni > 0
                    else None
                )
                medians.append((pc.median_pe, pc.median_core_pe, comps))
                comps_str = f"${comps:.2f}" if comps else "n/a"
                mpe = f"{pc.median_pe:.2f}" if pc.median_pe else "n/a"
                cpe = f"{pc.median_core_pe:.2f}" if pc.median_core_pe else "n/a"
                print(f"  run{run}: median_pe {mpe} | median_core_pe {cpe} | comps_pe {comps_str}")
            same = medians[0] == medians[1]
            print(f"  determinism (run1 == run2): {same}")
    finally:
        # Non-server entrypoint: join the aiosqlite workers + checkpoint WAL so the
        # process exits cleanly instead of hanging on "Event loop is closed" (2026-06-24).
        from finrobot.engine.data.factory import shutdown_data_layer

        await shutdown_data_layer(data_layer)


if __name__ == "__main__":
    asyncio.run(main())
