from dataclasses import dataclass

from finagent.config import FinAgentSettings
from finagent.engine.data.layer import DataLayer


@dataclass
class FinAgentDeps:
    data_layer: DataLayer
    settings: FinAgentSettings
    skill_runtime: object | None = None   # P0: None. P1a: SkillRegistry
