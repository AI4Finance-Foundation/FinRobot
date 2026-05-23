import pytest

from finagent.config import FinAgentSettings, get_settings


class TestDefaults:
    def test_default_model_name(self, monkeypatch):
        monkeypatch.delenv("FINAGENT_MODEL_NAME", raising=False)
        s = FinAgentSettings(_env_file=None)
        assert s.model_name == "deepseek:deepseek-chat"

    def test_default_api_keys_empty(self, monkeypatch):
        # Clear env vars + skip .env file so we test true defaults
        for key in [
            "FINAGENT_ANTHROPIC_API_KEY",
            "FINAGENT_DEEPSEEK_API_KEY",
            "FINAGENT_OPENAI_API_KEY",
        ]:
            monkeypatch.delenv(key, raising=False)
        s = FinAgentSettings(_env_file=None)
        assert s.anthropic_api_key == ""
        assert s.deepseek_api_key == ""
        assert s.openai_api_key == ""

    def test_default_cache_db_path(self):
        s = get_settings()
        # Resolved at runtime: legacy cwd ``finagent_cache.db`` if present,
        # else unified ``~/.finagent/data_cache.db`` from paths.py.
        assert s.cache_db_path  # non-empty after model_post_init
        assert s.cache_db_path.endswith("data_cache.db") or s.cache_db_path.endswith(
            "finagent_cache.db"
        )

    def test_default_skills_dir(self):
        s = get_settings()
        assert s.skills_dir == "skills"


class TestConstructorOverride:
    def test_model_name_override(self):
        s = get_settings(model_name="anthropic:claude-sonnet-4-6")
        assert s.model_name == "anthropic:claude-sonnet-4-6"

    def test_multiple_overrides(self):
        s = get_settings(model_name="openai:gpt-4o", cache_db_path="/tmp/test.db")
        assert s.model_name == "openai:gpt-4o"
        assert s.cache_db_path == "/tmp/test.db"


class TestCreateModel:
    def test_deepseek_returns_openai_chat_model(self):
        from pydantic_ai.models.openai import OpenAIChatModel

        s = get_settings(model_name="deepseek:deepseek-chat", deepseek_api_key="sk-test")
        model = s.create_model()
        assert isinstance(model, OpenAIChatModel)

    def test_anthropic_returns_anthropic_model(self):
        from pydantic_ai.models.anthropic import AnthropicModel

        s = get_settings(model_name="anthropic:claude-sonnet-4-6", anthropic_api_key="sk-test")
        model = s.create_model()
        assert isinstance(model, AnthropicModel)

    def test_openai_returns_openai_chat_model(self):
        from pydantic_ai.models.openai import OpenAIChatModel

        s = get_settings(model_name="openai:gpt-4o", openai_api_key="sk-test")
        model = s.create_model()
        assert isinstance(model, OpenAIChatModel)

    def test_unknown_provider_raises(self):
        s = get_settings(model_name="unknown:model")
        with pytest.raises(ValueError, match="Unknown provider 'unknown'"):
            s.create_model()

    def test_does_not_pollute_environ(self, monkeypatch):
        import os

        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        s = get_settings(model_name="deepseek:deepseek-chat", deepseek_api_key="sk-secret")
        s.create_model()
        assert os.environ.get("DEEPSEEK_API_KEY") is None


class TestValidateRuntimeConfig:
    """P3 audit D2: single source of truth for model + data config validation,
    shared between CLI and SDK. Raises ValueError (not ClickException)."""

    def test_valid_config_passes(self):
        s = get_settings(
            model_name="deepseek:deepseek-chat",
            deepseek_api_key="sk-x",
            fmp_api_key="fmp-test-key",
        )
        s.validate_runtime_config()  # must not raise

    def test_test_provider_needs_no_key(self):
        s = get_settings(model_name="test", fmp_api_key="fmp-test-key")
        s.validate_runtime_config()

    def test_unknown_provider_raises_value_error(self):
        s = get_settings(model_name="bogus:model-x", fmp_api_key="fmp-test-key")
        with pytest.raises(ValueError, match="Unknown provider 'bogus'"):
            s.validate_runtime_config()

    def test_missing_llm_api_key_raises_value_error(self, monkeypatch):
        monkeypatch.delenv("FINAGENT_DEEPSEEK_API_KEY", raising=False)
        s = FinAgentSettings(
            _env_file=None,
            model_name="deepseek:deepseek-chat",
            fmp_api_key="fmp-test-key",
        )
        with pytest.raises(ValueError, match="FINAGENT_DEEPSEEK_API_KEY is not set"):
            s.validate_runtime_config()

    def test_missing_fmp_api_key_emits_warning(self, monkeypatch):
        """FMP key is optional — emits warning, never raises (散户优先：yfinance fallback)."""
        import warnings

        monkeypatch.delenv("FINAGENT_FMP_API_KEY", raising=False)
        s = FinAgentSettings(_env_file=None, model_name="test")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            s.validate_runtime_config()
        fmp_warnings = [w for w in caught if "FINAGENT_FMP_API_KEY" in str(w.message)]
        assert len(fmp_warnings) == 1
        assert "yfinance" in str(fmp_warnings[0].message)

    def test_bad_per_role_override_also_caught(self):
        """Per-role overrides must be validated too, not just model_name."""
        s = get_settings(
            model_name="test",
            model_modeling="bogus:x",
            fmp_api_key="fmp-test-key",
        )
        with pytest.raises(ValueError, match="Unknown provider 'bogus'"):
            s.validate_runtime_config()
