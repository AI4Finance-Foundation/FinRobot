"""4-element computational artifact snapshot store.

Every pipeline execution is persisted as an Artifact with five sections:
- inputs:          data source + fetched_at + raw_data snapshot (for replay)
- assumptions:     all parameters, user_overrides distinguished
- compute_version: package + version + formula_id + formula_warnings
- outputs:         structured result dump + summary + warnings
- meta:            created_at + source + user_id + tags

Storage: ~/.finagent-desktop/artifacts/<ticker>/<id>.json + index.json
per ticker. Atomic writes via temp-file + rename.

This is FinAgent's core auditability differentiation vs "ask ChatGPT to
do DCF" — every number can be traced back to data snapshot + assumption
set + compute version + timestamp.
"""

from finagent.artifact.diff import FieldDiff, diff_artifacts
from finagent.artifact.models import (
    Artifact,
    ArtifactAssumptions,
    ArtifactComputeVersion,
    ArtifactInputs,
    ArtifactMeta,
    ArtifactOutputs,
    ArtifactSummary,
    ArtifactType,
)
from finagent.artifact.store import ArtifactStore

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
    "FieldDiff",
    "diff_artifacts",
]
