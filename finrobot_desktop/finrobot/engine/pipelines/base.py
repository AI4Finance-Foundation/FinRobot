"""Compatibility facade for the pipeline base layer.

The pipeline base was split into focused modules to keep each one readable:

- ``protocols`` — strategy/callback Protocols + concrete strategy classes
  (``ProgressCallback``, ``StepExecutor``, ``StepValidator``, ``ArtifactBuilder``,
  ``DefaultAgentExecutor``, ``TextValidator``, ``StructuredValidator``).
- ``step`` — the ``PipelineStep`` abstraction and ``PipelineStepError``.
- ``runner`` — the ``Pipeline`` runner: prompt assembly, retry loop, execution.
- ``result`` — the ``PipelineResult`` output model.

Every name that callers historically imported from
``finrobot.engine.pipelines.base`` is re-exported here, so existing import sites
keep working unchanged. The two private symbols (``_PROMPT_MAX_STEP_DATA_CHARS``,
``_is_recoverable_exception``) are re-exported because the unit tests target them
through this module path.
"""

from __future__ import annotations

from finrobot.engine.pipelines.protocols import (
    ArtifactBuilder,
    DefaultAgentExecutor,
    ProgressCallback,
    StepExecutor,
    StepValidator,
    StructuredValidator,
    TextValidator,
)
from finrobot.engine.pipelines.result import PipelineResult
from finrobot.engine.pipelines.runner import (
    Pipeline,
    _is_recoverable_exception,
    _PROMPT_MAX_STEP_DATA_CHARS,
)
from finrobot.engine.pipelines.step import PipelineStep, PipelineStepError

__all__ = [
    "ArtifactBuilder",
    "DefaultAgentExecutor",
    "Pipeline",
    "PipelineResult",
    "PipelineStep",
    "PipelineStepError",
    "ProgressCallback",
    "StepExecutor",
    "StepValidator",
    "StructuredValidator",
    "TextValidator",
    "_PROMPT_MAX_STEP_DATA_CHARS",
    "_is_recoverable_exception",
]
