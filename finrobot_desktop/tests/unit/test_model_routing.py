"""Tests for per-role model routing (Track 4 Tasks 11-12).

Verifies:
- get_model_for_role() falls back to global model_name when no override
- get_model_for_role() returns the role-specific override when set
- create_model(model_name=...) respects the override param
- factory.create_sub_agents wires per-role models via get_model_for_role
"""

from finrobot.config import get_settings


class TestGetModelForRole:
    def test_falls_back_to_global_when_no_override(self):
        settings = get_settings(model_name="test:test")
        assert settings.get_model_for_role("data") == "test:test"
        assert settings.get_model_for_role("modeling") == "test:test"

    def test_returns_role_specific_override(self):
        settings = get_settings(
            model_name="deepseek:deepseek-chat",
            model_modeling="anthropic:claude-sonnet-4-6",
            model_data="test:test",
        )
        assert settings.get_model_for_role("data") == "test:test"
        assert settings.get_model_for_role("modeling") == "anthropic:claude-sonnet-4-6"
        # unset roles fall back to global
        assert settings.get_model_for_role("analysis") == "deepseek:deepseek-chat"
        assert settings.get_model_for_role("synthesis") == "deepseek:deepseek-chat"
        assert settings.get_model_for_role("report") == "deepseek:deepseek-chat"

    def test_unknown_role_falls_back_to_global(self):
        """Unknown role names should return the global model, not crash."""
        settings = get_settings(model_name="test:test")
        assert settings.get_model_for_role("nonexistent") == "test:test"


class TestCreateModelWithOverride:
    def test_create_model_uses_override_name(self):
        """create_model(model_name=...) should build a model for the override
        rather than the global setting."""
        settings = get_settings(model_name="deepseek:deepseek-chat")
        # Override to 'test' — should succeed without needing deepseek API key
        model = settings.create_model(model_name="test:test")
        from pydantic_ai.models.test import TestModel

        assert isinstance(model, TestModel)

    def test_create_model_default_uses_global(self):
        """create_model() with no arg uses settings.model_name."""
        settings = get_settings(model_name="test:test")
        model = settings.create_model()
        from pydantic_ai.models.test import TestModel

        assert isinstance(model, TestModel)


class TestFactoryUsesRoleOverrides:
    def test_factory_creates_all_five_agents(self):
        """Regression: factory still returns all 5 role agents."""
        from finrobot.engine.agents.factory import create_sub_agents

        settings = get_settings(model_name="test:test")
        agents = create_sub_agents(settings)
        assert set(agents.keys()) == {
            "data",
            "analysis",
            "modeling",
            "synthesis",
            "report",
        }

    def test_factory_uses_per_role_model_when_set(self, monkeypatch):
        """When a role override is set, factory.create_sub_agents should call
        get_model_for_role (which returns the override) for that role."""
        from finrobot.engine.agents import factory

        seen: list[str] = []

        original_create = factory.FinRobotSettings.create_model

        def spy_create(self, model_name=None):
            seen.append(model_name or self.model_name)
            return original_create(self, model_name=model_name)

        monkeypatch.setattr(factory.FinRobotSettings, "create_model", spy_create)

        settings = get_settings(
            model_name="test:global",
            model_modeling="test:modeling",
        )
        factory.create_sub_agents(settings)

        # One call per role; modeling role must see the override
        assert "test:modeling" in seen
        # Other roles see the global
        assert seen.count("test:global") == 4
