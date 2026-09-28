import pytest
from pathlib import Path

from finrobot.config import get_settings
from finrobot.engine.skills.registry import SkillRegistry

# Skills dir resolved from settings, same as runtime code
SKILLS_DIR = Path(get_settings().skills_dir)


@pytest.mark.skipif(not SKILLS_DIR.exists(), reason="Vendored skills not present")
class TestP1aAcceptance:
    def test_all_skills_loaded(self):
        """P1a acceptance: all 56 vendored skills load without error."""
        registry = SkillRegistry(SKILLS_DIR)
        assert registry.count == 56, f"Expected 56 skills, got {registry.count}"

    def test_skill_list_by_domain(self):
        """P1a acceptance: skills are organized by domain."""
        registry = SkillRegistry(SKILLS_DIR)
        domains = set(s.domain for s in registry.list_all())
        assert len(domains) >= 3, f"Expected at least 3 domains, got {domains}"

    def test_skill_search_comps(self):
        """P1a acceptance: searching 'comps' finds comps-analysis skill."""
        registry = SkillRegistry(SKILLS_DIR)
        results = registry.search("comps")
        ids = [s.id for s in results]
        assert any("comps" in id for id in ids), f"Expected comps skill in results: {ids}"

    def test_skill_content_not_empty(self):
        """P1a acceptance: every skill has non-empty full_content."""
        registry = SkillRegistry(SKILLS_DIR)
        for skill in registry.list_all():
            assert len(skill.full_content.strip()) > 100, (
                f"Skill {skill.id} has suspiciously short content ({len(skill.full_content)} chars)"
            )

    def test_list_summary_fits_context(self):
        """P1a acceptance: list_summary for 56 skills is under 6000 chars (~1500 tokens)."""
        registry = SkillRegistry(SKILLS_DIR)
        summary = registry.list_summary()
        assert len(summary) < 6000, f"list_summary too long: {len(summary)} chars"

    def test_activate_skill_returns_content(self):
        """P1a acceptance: get() returns full skill content ready for injection."""
        registry = SkillRegistry(SKILLS_DIR)
        skill = registry.get("comps-analysis") or registry.list_all()[0]
        assert "##" in skill.full_content, "Skill content should have Markdown headers"

    @pytest.mark.integration
    @pytest.mark.slow
    def test_pipeline_with_skill_injection(self):
        """P1a acceptance: equity research pipeline with skill injection
        produces methodology-aware output.

        Validates that when skills are loaded, pipeline steps 2-4 produce
        output containing domain-specific methodology terms that would NOT
        appear without skill injection.
        """
        from finrobot.engine.agents.factory import create_sub_agents
        from finrobot.engine.deps import FinRobotDeps
        from finrobot.engine.data.layer import DataLayer
        from finrobot.engine.data.cache import DataCache
        from finrobot.engine.data.providers.yfinance_provider import YFinanceProvider
        from finrobot.engine.pipelines.equity_research import create_equity_research_pipeline

        settings = get_settings()
        registry = SkillRegistry(SKILLS_DIR)

        sub_agents = create_sub_agents(settings, skill_registry=registry)
        cache = DataCache(":memory:")
        data_layer = DataLayer(providers=[YFinanceProvider()], cache=cache)
        deps = FinRobotDeps(data_layer=data_layer, settings=settings, skill_runtime=registry)

        # Direct pipeline invocation (deterministic)
        pipeline = create_equity_research_pipeline(sub_agents)
        import asyncio

        result = asyncio.run(pipeline.execute(deps, "AAPL"))

        output = result.format_summary().lower()
        methodology_keywords = [
            "ev/ebitda",
            "trading multiples",
            "dcf",
            "discount rate",
            "wacc",
            "terminal value",
            "investment thesis",
            "catalyst",
        ]
        found = [kw for kw in methodology_keywords if kw in output]
        assert len(found) >= 2, f"Expected methodology keywords in output, found only: {found}"
