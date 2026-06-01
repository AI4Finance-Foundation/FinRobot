from __future__ import annotations

from typing import Literal, TypeAlias

from typing_extensions import TypedDict


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


class ArtifactReady(TypedDict):
    event: Literal["artifact.ready"]
    run_id: str
    artifact_type: str
    format: str


class RunCompleted(TypedDict):
    event: Literal["run.completed"]
    run_id: str
    ticker: str
    duration_s: float
    result_url: str


class RunFailed(TypedDict):
    event: Literal["run.failed"]
    run_id: str
    error: str


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
    | DebatePoint
    | DebateVerdict
)
