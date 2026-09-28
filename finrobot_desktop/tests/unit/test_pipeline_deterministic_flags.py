"""Pin the PipelineStep.deterministic contract across every pipeline.

``deterministic=True`` short-circuits the validation-retry loop (BUG-059): the
runner assumes a re-run reproduces byte-identical output. A step whose executor
makes an LLM call anywhere in its call chain CAN legitimately produce different
(passing) output on retry — flagging it deterministic silently strips its retry
budget (catalyst_analysis shipped exactly this mislabel, 2026-06-10 audit).
Conversely, a pure-compute step WITHOUT the flag burns its whole budget
recomputing identical failures (ic_memo financial_analysis / earnings_data).

The checker below judges "contains an LLM call" mechanically: it walks the
executor's AST and recurses into every finrobot-package function it calls by
name, flagging ``agent.run(...)`` and ``Agent(...)`` / ``PydanticAgent(...)``
construction.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from collections.abc import Callable

from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.pipelines.comps import create_comps_pipeline
from finrobot.engine.pipelines.dcf import create_dcf_pipeline
from finrobot.engine.pipelines.ddm import create_ddm_pipeline
from finrobot.engine.pipelines.earnings_analysis import create_earnings_analysis_pipeline
from finrobot.engine.pipelines.equity_research import (
    _execute_catalyst_analysis,
    create_equity_research_pipeline,
)
from finrobot.engine.pipelines.ic_memo import create_ic_memo_pipeline
from finrobot.engine.pipelines.lbo import create_lbo_pipeline

_PIPELINE_FACTORIES = [
    create_comps_pipeline,
    create_dcf_pipeline,
    create_ddm_pipeline,
    create_earnings_analysis_pipeline,
    create_equity_research_pipeline,
    create_ic_memo_pipeline,
    create_lbo_pipeline,
]

_AGENT_CONSTRUCTORS = {"Agent", "PydanticAgent"}


class _AnyRoleAgents(dict):
    """Agents dict that materialises a TestModel agent for any role key."""

    def __missing__(self, key: str) -> Agent:
        agent: Agent = Agent(TestModel(), deps_type=FinRobotDeps, defer_model_check=True)
        self[key] = agent
        return agent


def _function_llm_sites(func: Callable[..., object], seen: set[str]) -> list[str]:
    """Recursively collect LLM call sites reachable from ``func``.

    Flags ``agent.run(...)`` (the injected pipeline agent) and any
    ``Agent(...)`` / ``PydanticAgent(...)`` construction, then recurses into
    finrobot-package functions referenced by bare name in call position.
    Non-finrobot callables and unresolvable names are skipped — the goal is
    catching first-party LLM usage, not auditing the stdlib.
    """
    qualname = f"{getattr(func, '__module__', '?')}.{getattr(func, '__qualname__', '?')}"
    if qualname in seen:
        return []
    seen.add(qualname)
    try:
        source = textwrap.dedent(inspect.getsource(func))
        tree = ast.parse(source)
    except (OSError, TypeError, SyntaxError):
        return []

    sites: list[str] = []
    callee_names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if isinstance(callee, ast.Attribute):
            if (
                callee.attr == "run"
                and isinstance(callee.value, ast.Name)
                and "agent" in callee.value.id
            ):
                sites.append(f"{qualname}: {callee.value.id}.run(...)")
        elif isinstance(callee, ast.Name):
            if callee.id in _AGENT_CONSTRUCTORS:
                sites.append(f"{qualname}: {callee.id}(...)")
            else:
                callee_names.append(callee.id)

    func_globals = getattr(func, "__globals__", {})
    for name in callee_names:
        target = func_globals.get(name)
        if not callable(target):
            continue
        module = inspect.getmodule(target)
        if module is None or not module.__name__.startswith("finrobot"):
            continue
        sites.extend(_function_llm_sites(target, seen))
    return sites


def test_checker_detects_llm_inside_catalyst_executor() -> None:
    """Meta-guard: if the AST checker goes blind, this fails before the
    invariant test silently passes. catalyst_analysis reaches an LLM one hop
    deep (classify_news constructs a PydanticAgent)."""
    sites = _function_llm_sites(_execute_catalyst_analysis, set())
    assert sites, "checker no longer sees the LLM call inside classify_news"


def test_no_deterministic_step_contains_llm_call() -> None:
    """A step flagged deterministic=True must have zero LLM calls in its
    executor's finrobot call chain — otherwise a validation retry could
    legitimately succeed and the flag wrongly strips that budget."""
    offenders: list[str] = []
    for factory in _PIPELINE_FACTORIES:
        pipeline = factory(_AnyRoleAgents())
        for step in pipeline.steps:
            if not step.deterministic:
                continue
            executor = step.executor
            func = executor if inspect.isfunction(executor) else type(executor).__call__
            sites = _function_llm_sites(func, set())
            if sites:
                offenders.append(f"{factory.__name__}/{step.name}: {sites}")
    assert not offenders, f"deterministic steps with LLM calls: {offenders}"


def test_audited_steps_carry_correct_flags() -> None:
    """Pin the three steps the 2026-06-10 audit corrected."""
    er = {s.name: s for s in create_equity_research_pipeline(_AnyRoleAgents()).steps}
    assert er["catalyst_analysis"].deterministic is False  # contains classify_news LLM

    ic = {s.name: s for s in create_ic_memo_pipeline(_AnyRoleAgents()).steps}
    assert ic["financial_analysis"].deterministic is True  # pure DCF+LBO compute
    assert ic["financial_analysis"].critical is True  # flag must not displace the abort

    ea = {s.name: s for s in create_earnings_analysis_pipeline(_AnyRoleAgents()).steps}
    assert ea["earnings_data"].deterministic is True  # pure surprise statistics
