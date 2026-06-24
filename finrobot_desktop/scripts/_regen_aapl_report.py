"""Regenerate a real equity_research artifact for one ticker (default AAPL).

Replicates server.lifespan's deps/sub_agents/artifact_store assembly in a fresh
process — so it runs the CURRENT code (B1/B2 fixes), not whatever the
long-running `finrobot serve` loaded at boot — and persists the artifact to the
same ~/.finrobot/artifacts.db the desktop app reads. Does NOT touch the running
server.

Usage: python scripts/_regen_aapl_report.py [TICKER] [zh|en]
"""

from __future__ import annotations

import asyncio
import sys

from finrobot.artifact.store import ArtifactStore
from finrobot.config import get_settings
from finrobot.engine.agents.factory import create_sub_agents
from finrobot.engine.data.factory import build_data_layer
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.pipelines.registry import get_pipeline_factories
from finrobot.engine.skills.registry import SkillRegistry
from finrobot.obs import setup_logging
from finrobot.paths import SETTINGS_JSON, ensure_home
from finrobot.routes.settings import load_non_secret_settings
from finrobot.secret_store import create_secret_store
from finrobot.server import hydrate_settings_from_secrets
from pathlib import Path

TICKER = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
LANG = sys.argv[2] if len(sys.argv) > 2 else None


class _Progress:
    async def on_step_start(self, i: int, total: int, name: str) -> None:
        print(f"  [{i}/{total}] {name} …", flush=True)

    async def on_step_end(
        self, i: int, total: int, name: str, duration_s: float, error: str | None = None
    ) -> None:
        tag = "DEGRADED" if error else "ok"
        print(f"  [{i}/{total}] {name} — {tag} ({duration_s:.1f}s)", flush=True)

    async def on_step_retry(self, i: int, name: str, attempt: int, error: str) -> None:
        print(f"  [{i}] {name} retry #{attempt}: {error[:120]}", flush=True)


async def main() -> int:
    ensure_home()
    settings = get_settings(**load_non_secret_settings(SETTINGS_JSON))
    secret_store, _ = create_secret_store()
    settings = await hydrate_settings_from_secrets(settings, secret_store)
    setup_logging(settings)
    settings.validate_runtime_config()  # raises if keys missing

    registry = (
        SkillRegistry(Path(settings.skills_dir)) if Path(settings.skills_dir).exists() else None
    )
    data_layer = build_data_layer(settings)
    artifact_store = ArtifactStore()
    sub_agents = create_sub_agents(settings, skill_registry=registry)
    deps = FinRobotDeps(
        data_layer=data_layer,
        settings=settings,
        skill_runtime=registry,
        artifact_store=artifact_store,
        run_semaphore=asyncio.Semaphore(2),
    )

    pipeline = get_pipeline_factories()["research"](sub_agents)
    print(f"Running research pipeline for {TICKER} (lang={LANG}) …", flush=True)
    try:
        result = await pipeline.execute(deps, TICKER, progress=_Progress(), lang=LANG)
        print("\n" + result.format_summary())
        print(f"\nartifact_id = {result.artifact_id}")
        return 0 if result.artifact_id else 1
    finally:
        # Non-server entrypoint: join the aiosqlite workers + checkpoint WAL so the
        # process exits cleanly instead of hanging on "Event loop is closed" (2026-06-24).
        from finrobot.engine.data.factory import shutdown_data_layer

        await shutdown_data_layer(data_layer)
        await artifact_store.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
