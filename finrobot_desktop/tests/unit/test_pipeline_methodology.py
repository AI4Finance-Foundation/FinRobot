from __future__ import annotations

from finrobot.engine.pipelines.runner import _resolve_step_methodology
from finrobot.engine.pipelines.step import PipelineStep, iter_skill_sections
from finrobot.engine.skills.pipeline_methodology import render_pipeline_methodology
from finrobot.engine.skills.spec import Skill


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
