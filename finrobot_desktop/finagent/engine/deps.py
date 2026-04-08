from __future__ import annotations

from dataclasses import dataclass, field

from finagent.config import FinAgentSettings
from finagent.engine.data.layer import DataLayer
from finagent.engine.skills.registry import SkillRegistry


@dataclass
class FinAgentDeps:
    data_layer: DataLayer
    settings: FinAgentSettings
    skill_runtime: SkillRegistry | None = None  # P0: None → P1a: SkillRegistry instance
    report_cache: dict[str, dict] = field(default_factory=dict)
    """In-memory cache: ticker (upper) → report context dict. Written by pipeline tools, read by report endpoints."""
