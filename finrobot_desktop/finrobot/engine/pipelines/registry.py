"""Pipeline registry — the single source of truth for the pipeline set.

Extracted from server.py (Fix 4.4) to break the circular import:
  server → web → tasks → server

Every execution path now reads the pipeline set from here instead of
hardcoding its own copy:
  - routes/runs.py        → get_pipeline_factories() (REST run dispatch)
  - engine/orchestrator.py → iter_pipeline_specs()    (Mode A chat tools)
  - cli.py                → get_pipeline_factories()   (CLI subcommands)
  - sdk.py                → get_pipeline_factories()   (programmatic API)

Adding or renaming a pipeline is now a one-line change to ``_PIPELINE_SPECS``;
the four call sites above pick it up automatically.

LAZY IMPORT (do not break): the factory for each spec is imported only when
``factory`` is first accessed (``PipelineSpec.factory`` is a cached property
backed by an ``import_path``). This is the whole reason this module exists — it
must NOT eager-import the pipeline modules at import time, or the
server → web → tasks → server cycle returns.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from functools import cached_property
from typing import Any, Callable


@dataclass(frozen=True)
class PipelineSpec:
    """Tool/CLI/SDK metadata for one pipeline, plus a lazy factory handle.

    Attributes:
        key: Registry key used by REST (``pipeline_type``) and SDK lookups,
            e.g. ``"research"``, ``"ic-memo"``.
        import_path: ``"module:attr"`` of the ``create_*_pipeline`` factory.
            Imported lazily on first ``.factory`` access to preserve the
            no-eager-import contract that this module exists to enforce.
        tool_name: PydanticAI tool name for the Mode A chat agent. Kept as an
            explicit field because it does NOT mechanically derive from ``key``
            (``"ic-memo"`` → ``"run_ic_memo"``: the hyphen would be illegal in a
            tool identifier).
        tool_description: The LLM's tool-selection signal — carried VERBATIM
            from the original ``@agent.tool`` docstrings. Do not paraphrase.
    """

    key: str
    import_path: str
    tool_name: str
    tool_description: str

    @cached_property
    def factory(self) -> Callable[..., Any]:
        """Import and return the ``create_*_pipeline`` factory (lazy)."""
        module_path, _, attr = self.import_path.partition(":")
        module = importlib.import_module(module_path)
        return getattr(module, attr)  # type: ignore[no-any-return]


# Single source of truth for the pipeline set. The tool_description values are
# the original orchestrator @agent.tool docstrings, carried verbatim — they are
# what the LLM reads to choose a pipeline, so they must not drift.
_PIPELINE_SPECS: tuple[PipelineSpec, ...] = (
    PipelineSpec(
        key="research",
        import_path="finrobot.engine.pipelines.equity_research:create_equity_research_pipeline",
        tool_name="run_equity_research",
        tool_description=(
            "Generate a comprehensive equity research report.\n"
            "Uses a multi-step enforced pipeline. Takes 30-120 seconds.\n"
            "Use this when the user asks for: equity research, initiating coverage,\n"
            "stock analysis report, investment thesis, or deep-dive analysis."
        ),
    ),
    PipelineSpec(
        key="comps",
        import_path="finrobot.engine.pipelines.comps:create_comps_pipeline",
        tool_name="run_comps_analysis",
        tool_description=(
            "Build a comparable company analysis.\n"
            "Uses a multi-step enforced pipeline.\n"
            "Use when user asks for: comps, comparable companies, peer analysis,\n"
            "trading multiples comparison."
        ),
    ),
    PipelineSpec(
        key="dcf",
        import_path="finrobot.engine.pipelines.dcf:create_dcf_pipeline",
        tool_name="run_dcf_valuation",
        tool_description=(
            "Run a DCF valuation model.\n"
            "Uses a multi-step enforced pipeline.\n"
            "Use when user asks for: DCF, discounted cash flow, intrinsic value,\n"
            "valuation model."
        ),
    ),
    PipelineSpec(
        key="lbo",
        import_path="finrobot.engine.pipelines.lbo:create_lbo_pipeline",
        tool_name="run_lbo_analysis",
        tool_description=(
            "Run an LBO (leveraged buyout) analysis.\n"
            "Uses a multi-step enforced pipeline with deterministic IRR/MOIC math.\n"
            "Use when user asks for: LBO, leveraged buyout, private equity analysis,\n"
            "buyout returns, IRR analysis, MOIC."
        ),
    ),
    PipelineSpec(
        key="ddm",
        import_path="finrobot.engine.pipelines.ddm:create_ddm_pipeline",
        tool_name="run_ddm_valuation",
        tool_description=(
            "Run a DDM (Dividend Discount Model) valuation.\n"
            "Uses a multi-step enforced pipeline with deterministic dividend-based math.\n"
            "Use when user asks for: DDM, dividend discount model, bank valuation,\n"
            "or when the company is a bank/financial institution.\n"
            "Also auto-selected when 'finrobot dcf' detects a bank."
        ),
    ),
    PipelineSpec(
        key="earnings",
        import_path="finrobot.engine.pipelines.earnings_analysis:create_earnings_analysis_pipeline",
        tool_name="run_earnings_analysis",
        tool_description=(
            "Run an earnings quality analysis (beat rate, surprise trends, streak).\n"
            "Uses a multi-step enforced pipeline with deterministic beat/miss classification.\n"
            "Use when user asks for: earnings analysis, earnings quality, beat rate,\n"
            "earnings surprise, EPS trend."
        ),
    ),
    PipelineSpec(
        key="ic-memo",
        import_path="finrobot.engine.pipelines.ic_memo:create_ic_memo_pipeline",
        tool_name="run_ic_memo",
        tool_description=(
            "Generate an Investment Committee (IC) memo with DCF + LBO analysis.\n"
            "Uses a multi-step pipeline with IRR hurdle gate (PASS if IRR < 15%).\n"
            "Use when user asks for: IC memo, investment committee memo, PE analysis,\n"
            "buyout memo, invest/pass recommendation."
        ),
    ),
)


def iter_pipeline_specs() -> tuple[PipelineSpec, ...]:
    """Return every :class:`PipelineSpec` in registration order.

    The factory inside each spec is still imported lazily (on first
    ``spec.factory`` access), so iterating the specs does not eager-import any
    pipeline module — safe to call at agent-build time.
    """
    return _PIPELINE_SPECS


def get_pipeline_spec(key: str) -> PipelineSpec:
    """Return the spec for ``key`` or raise ``KeyError``."""
    for spec in _PIPELINE_SPECS:
        if spec.key == key:
            return spec
    raise KeyError(key)


# Lazy-loaded key→factory map, derived from the specs. Each factory takes a
# sub_agents dict and returns a Pipeline. Populated on first call, then cached.
_PIPELINE_FACTORIES: dict[str, Callable[..., Any]] | None = None


def get_pipeline_factories() -> dict[str, Callable[..., Any]]:
    """Return the key→factory map, importing factories lazily on first call.

    Backward-compatible view over :func:`iter_pipeline_specs` for the REST
    (runs.py), CLI, and SDK call sites that only need the factory by key.
    """
    global _PIPELINE_FACTORIES
    if _PIPELINE_FACTORIES is not None:
        return _PIPELINE_FACTORIES
    _PIPELINE_FACTORIES = {spec.key: spec.factory for spec in _PIPELINE_SPECS}
    return _PIPELINE_FACTORIES
