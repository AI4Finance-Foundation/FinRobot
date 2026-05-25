from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from finagent.config import FinAgentSettings
from finagent.engine.data.layer import DataLayer
from finagent.engine.skills.registry import SkillRegistry

if TYPE_CHECKING:
    from finagent.artifact.store import ArtifactStore


@dataclass
class FinAgentDeps:
    data_layer: DataLayer
    settings: FinAgentSettings
    skill_runtime: SkillRegistry | None = None
    artifact_store: "ArtifactStore | None" = None
    """Artifact store for persisting computational snapshots. None = disabled."""
