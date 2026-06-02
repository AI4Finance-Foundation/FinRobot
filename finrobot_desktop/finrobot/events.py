from __future__ import annotations

from typing import Any, Literal, TypeAlias

from typing_extensions import Required, TypedDict


class RunStarted(TypedDict):
    event: Literal["run.started"]
    run_id: str
    pipeline_type: str
    ticker: str
    total_steps: int


class StepStarted(TypedDict):
    event: Literal["step.started"]
    run_id: str
    step: int
    total: int
    name: str


class StepCompleted(TypedDict):
    event: Literal["step.completed"]
    run_id: str
    step: int
    total: int
    name: str
    duration_s: float


class StepRetry(TypedDict):
    event: Literal["step.retry"]
    run_id: str
    step: int
    total: int
    name: str
    attempt: int
    error: str


class ArtifactReady(TypedDict, total=False):
    event: Required[Literal["artifact.ready"]]
    run_id: Required[str]
    artifact_type: Required[str]
    format: Required[str]
    # The persisted artifact's own id (e.g. "art_..._AAPL_dcf"), so a consumer
    # can open THIS run's artifact by id instead of guessing the latest one for
    # the ticker. Optional for back-compat with older stored events that
    # predate this field; new emissions always populate it when an artifact was
    # persisted.
    artifact_id: str | None


class RunCompleted(TypedDict, total=False):
    event: Required[Literal["run.completed"]]
    run_id: Required[str]
    ticker: Required[str]
    duration_s: Required[float]
    result_url: Required[str]
    # Identity of the artifact this run produced. Mirrors ArtifactReady so a
    # completion CTA can navigate to the exact artifact (id + type) instead of
    # re-querying "latest equity_research for ticker", which silently opens the
    # wrong report on same-ticker re-runs or non-research pipelines. Both
    # optional for back-compat; None when the run produced no persisted
    # artifact.
    artifact_id: str | None
    artifact_type: str | None


class RunFailed(TypedDict):
    event: Literal["run.failed"]
    run_id: str
    error: str


class DebateEvidence(TypedDict):
    event: Literal["debate.evidence"]
    run_id: str
    ticker: str
    current_price: float
    reliable: bool
    items: list[dict[str, Any]]  # each item: {evidence_id, label, value, unit, formula_id}


class DebatePoint(TypedDict):
    event: Literal["debate.point"]
    run_id: str
    side: str
    claim: str
    evidence_ids: list[str]
    verified: bool
    reason: str


class DebateVerdict(TypedDict):
    event: Literal["debate.verdict"]
    run_id: str
    call: str
    conviction: float | None
    swing_factor: str
    change_my_mind: str


RunEvent: TypeAlias = (
    RunStarted
    | StepStarted
    | StepCompleted
    | StepRetry
    | ArtifactReady
    | RunCompleted
    | RunFailed
    | DebateEvidence
    | DebatePoint
    | DebateVerdict
)
