from pathlib import Path

from finrobot.engine.skills.registry import SkillRegistry

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "skills"


class TestRegistryLoading:
    def test_loads_skills_from_fixtures(self):
        registry = SkillRegistry(FIXTURES_DIR)
        # 4 skills: test-skill (test-domain), comps-analysis (test-domain-a),
        # dcf-model (test-domain-b), lbo-model (test-domain-b)
        assert registry.count == 4

    def test_skips_bad_skill_with_warning(self, tmp_path, caplog):
        good_dir = tmp_path / "domain" / "good-skill"
        good_dir.mkdir(parents=True)
        (good_dir / "SKILL.md").write_text("---\nid: good\nname: Good\n---\n# Good skill body\n")

        bad_dir = tmp_path / "domain" / "bad-skill"
        bad_dir.mkdir(parents=True)
        (bad_dir / "SKILL.md").write_text("Not valid frontmatter at all")

        registry = SkillRegistry(tmp_path)
        assert registry.count == 1
        assert "Skipping bad skill" in caplog.text

    def test_skips_skill_with_wrong_typed_field(self, tmp_path, caplog):
        # Frontmatter YAML is valid and has required fields, but `triggers` is a
        # bare string instead of a list — passes _parse_frontmatter but the
        # Skill(...) constructor raises pydantic ValidationError. The registry
        # must skip it, not crash __init__ (BUG-077).
        good_dir = tmp_path / "domain" / "good-skill"
        good_dir.mkdir(parents=True)
        (good_dir / "SKILL.md").write_text("---\nid: good\nname: Good\n---\n# Good skill body\n")

        bad_dir = tmp_path / "domain" / "bad-typed-skill"
        bad_dir.mkdir(parents=True)
        (bad_dir / "SKILL.md").write_text(
            "---\nid: bad\nname: Bad\ntriggers: comps-analysis\n---\n# Bad skill body\n"
        )

        registry = SkillRegistry(tmp_path)
        assert registry.count == 1
        assert registry.get("good") is not None
        assert registry.get("bad") is None
        assert "Skipping bad skill" in caplog.text


class TestGet:
    def test_returns_correct_skill_by_id(self):
        registry = SkillRegistry(FIXTURES_DIR)
        skill = registry.get("comps-analysis")
        assert skill is not None
        assert skill.name == "Comparable Company Analysis"

    def test_returns_none_for_unknown_id(self):
        registry = SkillRegistry(FIXTURES_DIR)
        assert registry.get("nonexistent") is None


class TestSearch:
    def test_finds_skills_with_comps_in_name_or_triggers(self):
        registry = SkillRegistry(FIXTURES_DIR)
        results = registry.search("comps")
        ids = [s.id for s in results]
        assert "comps-analysis" in ids

    def test_case_insensitive(self):
        registry = SkillRegistry(FIXTURES_DIR)
        results = registry.search("COMPS")
        ids = [s.id for s in results]
        assert "comps-analysis" in ids

    def test_returns_empty_list_for_no_match(self):
        registry = SkillRegistry(FIXTURES_DIR)
        results = registry.search("zzz_nonexistent_zzz")
        assert results == []

    def test_ranks_name_match_higher_than_description(self):
        registry = SkillRegistry(FIXTURES_DIR)
        # "LBO" appears in name of lbo-model and trigger, should rank high
        results = registry.search("lbo")
        assert len(results) > 0
        assert results[0].id == "lbo-model"


class TestListAll:
    def test_returns_all_skills_sorted_by_domain_then_id(self):
        registry = SkillRegistry(FIXTURES_DIR)
        skills = registry.list_all()
        assert len(skills) == 4
        # Check sorted by domain then id
        for i in range(len(skills) - 1):
            assert (skills[i].domain, skills[i].id) <= (skills[i + 1].domain, skills[i + 1].id)


class TestListSummary:
    def test_contains_all_skill_ids_grouped_by_domain(self):
        registry = SkillRegistry(FIXTURES_DIR)
        summary = registry.list_summary()
        assert "comps-analysis" in summary
        assert "dcf-model" in summary
        assert "lbo-model" in summary
        assert "test-domain-a" in summary
        assert "test-domain-b" in summary
        assert "activate_skill" in summary


class TestListIds:
    def test_returns_list_of_all_ids(self):
        registry = SkillRegistry(FIXTURES_DIR)
        ids = registry.list_ids()
        assert "comps-analysis" in ids
        assert "dcf-model" in ids
        assert "lbo-model" in ids
        assert "test-skill" in ids
        assert ids == sorted(ids)
