from dataclasses import dataclass

from finagent.engine.data.layer import DataLayer


@dataclass
class FinAgentDeps:
    data_layer: DataLayer
    skill_runtime: object | None = None   # P0: None. P1a: SkillRegistry
    model_name: str = "anthropic:claude-sonnet-4-6"
