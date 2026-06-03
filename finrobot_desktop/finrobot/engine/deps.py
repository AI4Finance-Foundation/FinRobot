from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from finrobot.config import FinRobotSettings
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.skills.registry import SkillRegistry

if TYPE_CHECKING:
    from finrobot.artifact.store import ArtifactStore


@dataclass
class FinRobotDeps:
    data_layer: DataLayer
    settings: FinRobotSettings
    skill_runtime: SkillRegistry | None = None
    artifact_store: "ArtifactStore | None" = None
    """Artifact store for persisting computational snapshots. None = disabled."""
    run_semaphore: asyncio.Semaphore | None = None
    """App-wide concurrency cap shared by EVERY caller that runs a pipeline
    through these deps (chat orchestrator, REST runs, Coverage batch). When set,
    Pipeline.execute acquires it for the whole run so concurrent pipelines stay
    bounded (BUG-017). None = no cap — used by single-invocation CLI/SDK
    processes where there is nothing to contend with."""
