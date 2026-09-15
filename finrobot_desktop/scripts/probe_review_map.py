"""Basket REVIEW map: run the real pipeline per ticker, print recommendation +
WHY (price_target_basis) + valuation methods + reliability flag. Every REVIEW /
withheld row is a lead to a data/method bug to fix.

The confidence-dial validation harness cited by valuation_synthesis.py — runs the
full basket (MU/AAPL/KO/NVDA/TSLA/RIVN/F) through the real pipeline to confirm the
REVIEW→dial campaign holds (every verdict directional, no REVIEW) and to surface
residual punt / method-silencing leaks.
Run: uv run python scripts/probe_review_map.py AAPL NVDA KO MU TSLA F RIVN
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from finrobot.config import get_settings
from finrobot.engine.agents.factory import create_sub_agents
from finrobot.engine.data.factory import build_data_layer
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.models.financial import ThesisResult, ValuationSynthesis
from finrobot.engine.pipelines.registry import get_pipeline_factories
from finrobot.engine.skills.registry import SkillRegistry
from finrobot.paths import SETTINGS_JSON
from finrobot.routes.settings import load_non_secret_settings
from finrobot.secret_store import create_secret_store
from finrobot.server import hydrate_settings_from_secrets

TICKERS = sys.argv[1:] or ["AAPL", "NVDA", "KO", "MU", "TSLA", "F", "RIVN"]


async def build_deps() -> FinRobotDeps:
    settings = get_settings(**load_non_secret_settings(SETTINGS_JSON))
    store, _ = create_secret_store()
    settings = await hydrate_settings_from_secrets(settings, store)
    settings.validate_runtime_config()
    skills_path = Path(settings.skills_dir)
    registry = SkillRegistry(skills_path) if skills_path.exists() else None
    return FinRobotDeps(
        data_layer=build_data_layer(settings), settings=settings, skill_runtime=registry
    )


def _find(structured: dict[str, object], cls: type) -> object | None:
    for v in structured.values():
        if isinstance(v, cls):
            return v
    return None


async def main() -> None:
    deps = await build_deps()
    try:
        factories = get_pipeline_factories()
        print("=" * 100, flush=True)
        for ticker in TICKERS:
            sub_agents = create_sub_agents(deps.settings, skill_registry=deps.skill_runtime)
            pipeline = factories["research"](sub_agents)
            try:
                result = await asyncio.wait_for(
                    pipeline.execute(deps, ticker, lang="zh"), timeout=200
                )
            except asyncio.TimeoutError:
                print(f"  {ticker:8s} TIMEOUT >200s", flush=True)
                continue
            except Exception as e:  # noqa: BLE001
                print(f"  {ticker:8s} ERROR {type(e).__name__}: {e}", flush=True)
                continue
            vs = _find(result.structured_data, ValuationSynthesis)
            th = _find(result.structured_data, ThesisResult)
            rec = getattr(th, "recommendation", "?")
            tgt = getattr(th, "price_target", None)
            basis = getattr(th, "price_target_basis", "")
            methods = []
            cur = None
            reliable = None
            wpx = None
            if isinstance(vs, ValuationSynthesis):
                methods = [f"{m.name}=${m.mid:.0f}" for m in vs.methods]
                cur = getattr(vs, "current_price", None)
                reliable = getattr(vs, "reliable", None)
                wpx = getattr(vs, "weighted_price", None)
            tgts = f"${tgt:.2f}" if isinstance(tgt, (int, float)) else "WITHHELD"
            curs = f"${cur:.2f}" if isinstance(cur, (int, float)) else "?"
            flag = "🔴REVIEW" if rec == "REVIEW" else f"  {rec}"
            print(
                f"\n  {ticker:8s} {flag:10s} target={tgts:>10}  current={curs:>9}  reliable={reliable}",
                flush=True,
            )
            print(
                f"           methods: {'  '.join(methods) or '(none)'}   weighted={wpx}", flush=True
            )
            print(f"           basis: {basis[:240]}", flush=True)
        print("\n" + "=" * 100, flush=True)
    finally:
        # Non-server entrypoint: join the aiosqlite workers + checkpoint WAL so the
        # process exits cleanly instead of hanging on "Event loop is closed" (2026-06-24).
        from finrobot.engine.data.factory import shutdown_data_layer

        await shutdown_data_layer(deps.data_layer)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
