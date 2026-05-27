import pytest
from pathlib import Path

from finrobot.engine.skills.loader import (
    load_skill,
    _parse_frontmatter,
    _extract_description,
    SkillLoadError,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "skills"
TEST_SKILL_PATH = FIXTURES_DIR / "test-domain" / "test-skill" / "SKILL.md"


class TestLoadSkill:
    def test_valid_skill_returns_correct_skill(self):
        skill = load_skill(TEST_SKILL_PATH)
        assert skill.id == "test-skill"
        assert skill.name == "Test Skill"
        assert skill.version == "1.0.0"
        assert skill.author == "anthropic"
        assert skill.domain == "test-domain"
        assert skill.description == "A test skill for unit testing."
        assert skill.triggers == ["test", "unit testing"]
        assert skill.source_path == str(TEST_SKILL_PATH)

    def test_extracts_frontmatter_and_body(self):
        skill = load_skill(TEST_SKILL_PATH)
        assert "# Test Skill" in skill.full_content
        assert "## Workflow" in skill.full_content
        # Frontmatter should NOT be in full_content
        assert "---" not in skill.full_content

    def test_missing_id_raises_skill_load_error(self, tmp_path):
        bad_file = tmp_path / "SKILL.md"
        bad_file.write_text("---\nname: No ID Skill\n---\n# Body\n")
        with pytest.raises(SkillLoadError, match="Missing required field 'id'"):
            load_skill(bad_file)

    def test_missing_name_raises_skill_load_error(self, tmp_path):
        bad_file = tmp_path / "SKILL.md"
        bad_file.write_text("---\nid: no-name\n---\n# Body\n")
        with pytest.raises(SkillLoadError, match="Missing required field 'name'"):
            load_skill(bad_file)

    def test_missing_optional_fields_uses_defaults(self, tmp_path):
        minimal = tmp_path / "SKILL.md"
        minimal.write_text(
            "---\nid: minimal\nname: Minimal Skill\n---\n# Body\nSome content here.\n"
        )
        skill = load_skill(minimal)
        assert skill.version == "1.0.0"
        assert skill.author == "unknown"
        assert skill.domain == "general"
        assert skill.triggers == []
        assert skill.requires_data == []


class TestParseFrontmatter:
    def test_correctly_splits_content(self):
        content = "---\nid: test\nname: Test\n---\n# Heading\nBody text."
        fm, body = _parse_frontmatter(content)
        assert fm == {"id": "test", "name": "Test"}
        assert body == "# Heading\nBody text."

    def test_no_frontmatter_raises_skill_load_error(self):
        with pytest.raises(SkillLoadError, match="No YAML frontmatter"):
            _parse_frontmatter("# Just Markdown\nNo frontmatter here.")

    def test_no_closing_delimiter_raises(self):
        with pytest.raises(SkillLoadError, match="No closing"):
            _parse_frontmatter("---\nid: broken\n# No closing delimiter")


class TestExtractDescription:
    def test_prefers_frontmatter_description(self):
        desc = _extract_description({"description": "From frontmatter"}, "First paragraph of body.")
        assert desc == "From frontmatter"

    def test_falls_back_to_first_paragraph_of_body(self):
        desc = _extract_description(
            {}, "# Heading\n\nFirst paragraph of body.\n\nSecond paragraph."
        )
        assert desc == "First paragraph of body."

    def test_skips_headings_in_body(self):
        desc = _extract_description({}, "# Heading\n\n## Subheading\n\nActual content here.")
        assert desc == "Actual content here."

    def test_empty_body_returns_empty_string(self):
        desc = _extract_description({}, "")
        assert desc == ""
