from __future__ import annotations

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
