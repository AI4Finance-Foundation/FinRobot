from finrobot.engine.skills.spec import Skill


class TestSkillModel:
    def test_validates_with_all_required_fields(self):
        skill = Skill(
            id="comps-analysis",
            name="Comparable Company Analysis",
            version="1.0.0",
            author="anthropic",
            domain="equity-research",
            description="Builds a trading comps table with EV/EBITDA.",
            triggers=["comps", "peer analysis"],
            full_content="# Comparable Company Analysis\n## Workflow\n...",
            source_path="/skills/equity-research/comps-analysis/SKILL.md",
        )
        assert skill.id == "comps-analysis"
        assert skill.name == "Comparable Company Analysis"
        assert skill.triggers == ["comps", "peer analysis"]

    def test_validates_with_empty_optional_lists(self):
        skill = Skill(
            id="test-skill",
            name="Test Skill",
            version="1.0.0",
            author="unknown",
            domain="general",
            description="A test skill.",
            full_content="# Test\nBody content here.",
            source_path="/test/SKILL.md",
        )
        assert skill.triggers == []
        assert skill.requires_data == []
        assert skill.requires_tools == []
        assert skill.requires_skills == []
        assert skill.compatible_models == []


class TestSummary:
    def test_returns_expected_format(self):
        skill = Skill(
            id="comps-analysis",
            name="Comparable Company Analysis",
            version="1.0.0",
            author="anthropic",
            domain="equity-research",
            description="Builds a trading comps table.",
            full_content="# Body",
            source_path="/test/SKILL.md",
        )
        assert (
            skill.summary()
            == "comps-analysis: Comparable Company Analysis — Builds a trading comps table."
        )

    def test_truncates_long_descriptions_at_50_chars(self):
        long_desc = "A" * 120
        skill = Skill(
            id="test",
            name="Test",
            version="1.0.0",
            author="unknown",
            domain="general",
            description=long_desc,
            full_content="# Body",
            source_path="/test/SKILL.md",
        )
        result = skill.summary()
        assert result == f"test: Test — {'A' * 50}..."
