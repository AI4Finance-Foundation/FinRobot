"""Fast deterministic FX-coherence probe for a foreign local-listed ticker.
No LLM narrative — just fetch + extract + (optionally) the FX-normalize step,
all under hard timeouts, to see if the data is fetchable and what currency the
market quantities are in. BUG-006 / cross-currency (T1#6) regression harness.
Run: uv run python scripts/probe_foreign_fx_end_to_end.py 2330.TW
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from finrobot.config import get_settings
from finrobot.engine.compute.coordinators.extractor import extract_financial_data
from finrobot.engine.data.factory import build_data_layer
from finrobot.engine.data.types import DataType
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.skills.registry import SkillRegistry
from finrobot.paths import SETTINGS_JSON
from finrobot.routes.settings import load_non_secret_settings
from finrobot.secret_store import create_secret_store
from finrobot.server import hydrate_settings_from_secrets

TICKER = sys.argv[1] if len(sys.argv) > 1 else "2330.TW"


async def build_deps() -> FinRobotDeps:
    settings = get_settings(**load_non_secret_settings(SETTINGS_JSON))
    store, _ = create_secret_store()
    settings = await hydrate_settings_from_secrets(settings, store)
    skills_path = Path(settings.skills_dir)
    registry = SkillRegistry(skills_path) if skills_path.exists() else None
    return FinRobotDeps(
        data_layer=build_data_layer(settings), settings=settings, skill_runtime=registry
    )


async def main() -> None:
    deps = await build_deps()
    try:
        print(f"[{TICKER}] deps built, fetching FINANCIALS (timeout 90s)...", flush=True)
        t0 = time.monotonic()
        try:
            fin = await asyncio.wait_for(
                deps.data_layer.fetch_canonical(DataType.FINANCIALS, TICKER), timeout=90
            )
        except asyncio.TimeoutError:
            print(
                f"[{TICKER}] !!! FINANCIALS fetch HUNG >90s — data-fetch is the hang source",
                flush=True,
            )
            return
        print(f"[{TICKER}] FINANCIALS ok in {time.monotonic() - t0:.1f}s", flush=True)

        t0 = time.monotonic()
        try:
            price = await asyncio.wait_for(
                deps.data_layer.fetch_canonical(DataType.PRICE, TICKER), timeout=90
            )
        except asyncio.TimeoutError:
            print(f"[{TICKER}] !!! PRICE fetch HUNG >90s", flush=True)
            return
        print(f"[{TICKER}] PRICE ok in {time.monotonic() - t0:.1f}s", flush=True)

        fd = extract_financial_data(fin, price)
        print("\n=== RAW (pre-pipeline-FX-normalize) ===", flush=True)
        print(f"  reporting_currency = {fd.reporting_currency}", flush=True)
        print(f"  quote_currency     = {fd.quote_currency}", flush=True)
        mk = fd.market
        print(
            f"  current_price      = {getattr(mk, 'current_price', getattr(mk, 'price', '?'))}",
            flush=True,
        )
        print(f"  market_cap         = {getattr(mk, 'market_cap', '?')}", flush=True)
        print(f"  pe_ratio           = {getattr(mk, 'pe_ratio', '?')}", flush=True)
        print(
            "  (locally-listed non-USD issuer → reporting==quote==native; pipeline FX-normalizes to USD)",
            flush=True,
        )

        # === Stage 2: run the REAL FX-normalize pipeline step on real 2330.TW data ===
        from unittest.mock import MagicMock

        from finrobot.engine.models.financial import DCFResult, HistoricalMetrics
        from finrobot.engine.pipelines.equity_research import _execute_financial_modeling

        hm = HistoricalMetrics(
            years=[],
            revenue=[],
            revenue_growth_yoy=[],
            cogs=[],
            gross_profit=[],
            gross_margin=[],
            sga=[],
            sga_ratio=[],
            ebitda=[],
            ebitda_margin=[],
            operating_income=[],
            operating_margin=[],
            net_income=[],
            eps=[],
            pe_ratio=[],
            cagr_revenue=None,
            ticker=TICKER,
        )
        ctx: dict[str, object] = {"data_collection": fd, "historical_metrics": hm}
        print("\n=== Stage 2: real _execute_financial_modeling (FX-normalize step) ===", flush=True)
        try:
            out = await asyncio.wait_for(
                _execute_financial_modeling(MagicMock(), deps, "p", ctx, TICKER), timeout=120
            )
        except asyncio.TimeoutError:
            print("  !!! _execute_financial_modeling HUNG >120s", flush=True)
            return
        except Exception as e:  # noqa: BLE001
            print(f"  step error: {type(e).__name__}: {e}", flush=True)
            return

        dc = ctx.get("data_collection")
        print(
            f"  AFTER data_collection.reporting_currency = {getattr(dc, 'reporting_currency', '?')}",
            flush=True,
        )
        print(
            f"  AFTER data_collection.quote_currency     = {getattr(dc, 'quote_currency', '?')}",
            flush=True,
        )
        dmk = getattr(dc, "market", None)
        cp = getattr(dmk, "current_price", getattr(dmk, "price", None))
        print(f"  AFTER current_price = {cp}   (expect USD ~72, NOT NT$2310)", flush=True)
        print(
            f"  AFTER market_cap    = {getattr(dmk, 'market_cap', None)}   (expect USD ~1.9T)",
            flush=True,
        )
        dcf = ctx.get("financial_modeling")
        if isinstance(dcf, DCFResult):
            ip = getattr(dcf, "implied_price", None)
            print(
                f"  DCF implied_price  = {ip}   (USD; compare to current_price above — SAME currency?)",
                flush=True,
            )
            mi = getattr(dcf, "market_implied", None)
            print(f"  market_implied     = {getattr(mi, 'implied_growth', mi)}", flush=True)
            # The smoking gun: USD DCF target vs current_price must be SAME-currency.
            if isinstance(cp, (int, float)) and isinstance(ip, (int, float)) and cp > 0:
                r = ip / cp
                verdict = (
                    "COHERENT (same-currency)"
                    if 0.1 <= r <= 10
                    else "!!! MIXED-CURRENCY (fabricated SHORT/LONG)"
                )
                print(f"  implied/current ratio = {r:.3f} → {verdict}", flush=True)
        else:
            print(
                f"  financial_modeling = {type(dcf).__name__} (DCF degraded; warnings={getattr(out, 'warnings', None)})",
                flush=True,
            )
        print(f"\n  warnings: {getattr(out, 'warnings', None)}", flush=True)
    finally:
        # Non-server entrypoint: join the aiosqlite workers + checkpoint WAL so the
        # process exits cleanly instead of hanging on "Event loop is closed" (2026-06-24).
        from finrobot.engine.data.factory import shutdown_data_layer

        await shutdown_data_layer(deps.data_layer)


if __name__ == "__main__":
    asyncio.run(main())
