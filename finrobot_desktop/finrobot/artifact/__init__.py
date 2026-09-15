"""4-element computational artifact snapshot store.

Every pipeline execution is persisted as an Artifact with five sections:
- inputs:          data source + fetched_at + raw_data snapshot (for replay)
- assumptions:     all parameters, user_overrides distinguished
- compute_version: package + version + formula_id + formula_warnings
- outputs:         structured result dump + summary + warnings
- meta:            created_at + source + user_id + tags

Storage: a single SQLite db at ``~/.finrobot/artifacts.db`` (since
2026-05-23). The ``ArtifactStore`` name is a thin shim that delegates
to :class:`finrobot.artifact.sqlite_store.SqliteArtifactStore`. Secondary
indexed columns (verdict, entry_price, target_price, …) are populated at
save time so dashboard aggregations don't N+1 the full payload.

This is FinRobot's core auditability differentiation vs "ask ChatGPT to
do DCF" — every number can be traced back to data snapshot + assumption
set + compute version + timestamp.
"""

from finrobot.artifact.models import (
    Artifact,
    ArtifactAssumptions,
    ArtifactComputeVersion,
    ArtifactInputs,
    ArtifactMeta,
    ArtifactOutputs,
    ArtifactSummary,
    ArtifactType,
)
from finrobot.artifact.semantic_diff import SemanticDelta, build_semantic_delta
from finrobot.artifact.store import ArtifactStore

__all__ = [
    "Artifact",
    "ArtifactAssumptions",
    "ArtifactComputeVersion",
    "ArtifactInputs",
    "ArtifactMeta",
    "ArtifactOutputs",
    "ArtifactStore",
    "ArtifactSummary",
    "ArtifactType",
    "SemanticDelta",
    "build_semantic_delta",
]
