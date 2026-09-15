from __future__ import annotations

from pathlib import Path

import pytest

from finrobot.engine.pipelines.runner import _resolve_step_methodology
from finrobot.engine.pipelines.step import PipelineStep, iter_skill_sections
from finrobot.engine.skills.pipeline_methodology import render_pipeline_methodology
from finrobot.engine.skills.registry import SkillRegistry
from finrobot.engine.skills.spec import Skill

# The repo's real skills tree (skills/**/SKILL.md) — the same one the orchestrator
# and pipeline runner load at runtime via SkillRegistry(settings.skills_dir).
_REAL_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

# Interactive / checkpoint phrases that must NEVER survive into a pipeline-rendered
# methodology block. Raw Claude-Code SKILL.md bodies use these to tell the agent to
# stop and wait for a human ("one task at a time", "wait for explicit user
# approval"). In the unattended report pipeline — or Mode A chat driving it — that
# halts the run. render_pipeline_methodology() must strip them for every loadable
# skill: a skill that trips one needs a distilled entry in _PIPELINE_SAFE_METHODOLOGY.
#
# Substring match, case-insensitive. Phrases are deliberately multi-word so the test
# does not false-positive on legitimate code (e.g. a JS `await sharp(...)` snippet)
# or the word "review" used analytically ("reviewing scenario logic").
INTERACTIVE_CHECKPOINT_PHRASES: tuple[str, ...] = (
    "wait for",
    "user review",
    "for user review",
    "reviews outputs",
    "one task per request",
    "one task at a time",
    "one slide at a time",
    "approve before",
    "approval before",
    "stop and wait",
    "do not proceed until",
    "next user request",
    "get user approval",
    "explicit user approval",
    "present the shortlist for user review",
    "presents drafts for user review",
    "review and approve before",
)


def _skill(skill_id: str, body: str) -> Skill:
    return Skill(
        id=skill_id,
        name=skill_id,
        version="1.0.0",
        author="test",
        domain="test",
        description="desc",
        full_content=body,
        source_path=f"/tmp/{skill_id}/SKILL.md",
    )


class _SkillRuntime:
    def __init__(self, *skills: Skill) -> None:
        self._skills = {skill.id: skill for skill in skills}

    def get(self, skill_id: str) -> Skill | None:
        return self._skills.get(skill_id)


def test_iter_skill_sections_keeps_legacy_single_id() -> None:
    assert iter_skill_sections(None) == ()
    assert iter_skill_sections("dcf-model") == ("dcf-model",)
    assert iter_skill_sections(("initiating-coverage", "competitive-analysis")) == (
        "initiating-coverage",
        "competitive-analysis",
    )


def test_known_interactive_skill_is_rendered_as_pipeline_safe_methodology() -> None:
    skill = _skill(
        "competitive-analysis",
        "Use ask_user_question, get outline approval, then create a .pptx deck.",
    )

    rendered = render_pipeline_methodology(skill)

    assert "Pipeline-safe competitive landscape framework" in rendered
    assert "ask_user_question" not in rendered
    assert ".pptx" not in rendered
    assert "do not invent" in rendered
    assert "market share, segment share, company margin" in rendered
    assert "subject company's own comparable multiple" in rendered


def test_known_compute_skill_is_reduced_to_narrative_checklist() -> None:
    skill = _skill(
        "dcf-model",
        "Formulas Over Hardcodes. Build an Excel model and compute WACC formulas.",
    )

    rendered = render_pipeline_methodology(skill)

    assert "Pipeline-safe DCF framework" in rendered
    assert "All DCF inputs, WACC" in rendered
    assert "Formulas Over Hardcodes" not in rendered
    assert "compute formulas in the LLM step" in rendered


def test_report_snapshot_skill_is_pipeline_safe() -> None:
    skill = _skill(
        "equity-research",
        "Call qa_ibes_consensus, browse tools, and compute forward P/E.",
    )

    rendered = render_pipeline_methodology(skill)

    assert "Pipeline-safe research snapshot framework" in rendered
    assert "Connect every table and metric to the investment thesis" in rendered
    assert "Call qa_ibes_consensus" not in rendered
    assert "compute forward P/E" not in rendered


def test_unknown_skill_falls_back_to_original_body() -> None:
    skill = _skill("custom-sop", "Custom house style body.")

    rendered = render_pipeline_methodology(skill)

    assert "### custom-sop: custom-sop" in rendered
    assert "Custom house style body." in rendered


def test_runner_resolves_multiple_skills_in_order_with_safe_rendering() -> None:
    step = PipelineStep(
        name="thesis",
        skill_section=("initiating-coverage", "competitive-analysis", "missing"),
        agent=object(),  # type: ignore[arg-type]
        validator=lambda output: (True, None),
    )
    runtime = _SkillRuntime(
        _skill("initiating-coverage", "One Task at a Time; ask which task."),
        _skill("competitive-analysis", "Build a 20-slide deck."),
    )

    methodology = _resolve_step_methodology(step, runtime)

    assert methodology.index("Pipeline-safe initiating-coverage framework") < methodology.index(
        "Pipeline-safe competitive landscape framework"
    )
    assert "One Task at a Time" not in methodology
    assert "20-slide deck" not in methodology
    assert "missing" not in methodology


def test_runner_resolves_report_methodology_stack() -> None:
    step = PipelineStep(
        name="report",
        skill_section=("initiating-coverage", "tear-sheet", "equity-research"),
        agent=object(),  # type: ignore[arg-type]
        validator=lambda output: (True, None),
    )
    runtime = _SkillRuntime(
        _skill("initiating-coverage", "Create DOCX."),
        _skill("tear-sheet", "Use S&P tools."),
        _skill("equity-research", "Call LSEG tools."),
    )

    methodology = _resolve_step_methodology(step, runtime)

    assert "Pipeline-safe initiating-coverage framework" in methodology
    assert "Pipeline-safe tear sheet framework" in methodology
    assert "Pipeline-safe research snapshot framework" in methodology
    assert "Create DOCX" not in methodology
    assert "Call LSEG tools" not in methodology


# ---------------------------------------------------------------------------
# Mechanical anti-recurrence gate
# ---------------------------------------------------------------------------


def _all_real_skill_ids() -> list[str]:
    if not _REAL_SKILLS_DIR.is_dir():
        return []
    registry = SkillRegistry(_REAL_SKILLS_DIR)
    return registry.list_ids()


@pytest.mark.parametrize("skill_id", _all_real_skill_ids())
def test_every_loadable_skill_renders_checkpoint_free(skill_id: str) -> None:
    """Anti-recurrence gate: every skill the runtime can load must render a
    pipeline-safe methodology free of interactive checkpoint language.

    render_pipeline_methodology() falls back to the raw SKILL.md body for any
    skill missing a _PIPELINE_SAFE_METHODOLOGY entry. So an interactive skill
    added (or one whose body grows a new "wait for the user" directive) without a
    distilled entry would leak that directive into the unattended pipeline. This
    parametrized test fails CI the moment that happens, forcing the author to add
    a safe entry rather than silently regressing Mode A/Mode B symmetry.
    """
    registry = SkillRegistry(_REAL_SKILLS_DIR)
    skill = registry.get(skill_id)
    assert skill is not None, f"{skill_id} no longer loadable"

    rendered = render_pipeline_methodology(skill).lower()

    leaked = [phrase for phrase in INTERACTIVE_CHECKPOINT_PHRASES if phrase in rendered]
    assert not leaked, (
        f"skill {skill_id!r} leaks interactive checkpoint phrases {leaked} into its "
        f"pipeline-rendered methodology. Add a distilled, narrative-only entry to "
        f"_PIPELINE_SAFE_METHODOLOGY in finrobot/engine/skills/pipeline_methodology.py "
        f"that captures the method and drops every 'wait for user' / checkpoint / "
        f"file-generation directive."
    )


def test_real_skills_dir_is_populated() -> None:
    """Guard the guard: if the skills tree moved or failed to load, the
    parametrized gate above would silently expand to zero cases and pass
    vacuously. Pin a floor so an empty registry is itself a failure."""
    assert len(_all_real_skill_ids()) >= 50
