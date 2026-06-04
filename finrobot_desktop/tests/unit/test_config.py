from pathlib import Path

import pytest

from finrobot.config import FinRobotSettings, get_settings


class TestDefaults:
    # Config is app-stored-only: FinRobotSettings reads ONLY constructor kwargs,
    # never env / .env (settings_customise_sources drops those sources). So a
    # bare FinRobotSettings() reflects the class defaults regardless of the
    # developer's shell or repo-root .env — no monkeypatch.delenv scaffolding
    # needed any more.
    def test_default_model_name(self):
        s = FinRobotSettings()
        assert s.model_name == "deepseek:deepseek-chat"

    def test_default_api_keys_empty(self):
        s = FinRobotSettings()
        assert s.anthropic_api_key == ""
        assert s.deepseek_api_key == ""
        assert s.openai_api_key == ""

    def test_env_var_is_ignored_for_user_config(self, monkeypatch):
        """A FINROBOT_* env var must NOT leak into user config — the whole point
        of the app-stored-only model (packaging safety + no source ambiguity)."""
        monkeypatch.setenv("FINROBOT_OPENAI_API_KEY", "sk-from-env")
        monkeypatch.setenv("FINROBOT_MODEL_NAME", "openai:gpt-4o")
        s = FinRobotSettings()
        assert s.openai_api_key == ""
        assert s.model_name == "deepseek:deepseek-chat"

    def test_default_cache_db_path(self):
        s = get_settings()
        # Resolved at runtime: legacy cwd ``finrobot_cache.db`` if present,
        # else unified ``~/.finrobot/data_cache.db`` from paths.py.
        assert s.cache_db_path  # non-empty after model_post_init
        assert s.cache_db_path.endswith("data_cache.db") or s.cache_db_path.endswith(
            "finrobot_cache.db"
        )

    def test_default_skills_dir(self):
        # skills_dir resolves at runtime to an absolute, bundle-aware path
        # (repo_root/skills in dev, sys._MEIPASS/skills in a frozen desktop
        # build) — never a bare "skills" relative to an arbitrary cwd.
        s = get_settings()
        assert s.skills_dir  # non-empty after model_post_init
        assert s.skills_dir.endswith("skills")
        assert Path(s.skills_dir).is_absolute()

    def test_sec_holdings_refresh_is_opt_in(self):
        s = FinRobotSettings()
        assert s.sec_holdings_auto_refresh is False


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

    def test_missing_llm_api_key_raises_value_error(self):
        s = FinRobotSettings(
            model_name="deepseek:deepseek-chat",
            fmp_api_key="fmp-test-key",
        )
        with pytest.raises(ValueError, match="No API key configured for provider 'deepseek'"):
            s.validate_runtime_config()

    def test_missing_fmp_api_key_emits_warning(self):
        """FMP key is optional — emits warning, never raises (analyst-grade fallback)."""
        import warnings

        s = FinRobotSettings(model_name="test")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            s.validate_runtime_config()
        fmp_warnings = [w for w in caught if "FMP" in str(w.message)]
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


class TestNoEnvReading:
    """Config is app-stored-only — neither a FINROBOT_* env var nor a .env file
    may feed user config. These guard the settings_customise_sources override
    that drops the env + dotenv sources (packaging safety + source clarity).

    The three pure-infra knobs (skills_dir / cache_db_path /
    backtest_strategy_module_prefixes) still read their own env var in
    model_post_init — covered by test_cli / test_backtrader_adapter."""

    def test_user_config_env_vars_ignored(self, monkeypatch):
        for var, val in {
            "FINROBOT_ANTHROPIC_API_KEY": "sk-ant",
            "FINROBOT_DEEPSEEK_API_KEY": "sk-ds",
            "FINROBOT_OPENAI_API_KEY": "sk-oai",
            "FINROBOT_FMP_API_KEY": "fmp",
            "FINROBOT_SEC_USER_AGENT": "Hacker evil@example.com",
            "FINROBOT_LOG_LEVEL": "DEBUG",
        }.items():
            monkeypatch.setenv(var, val)
        s = get_settings()
        assert s.anthropic_api_key == ""
        assert s.deepseek_api_key == ""
        assert s.openai_api_key == ""
        assert s.fmp_api_key == ""
        assert s.sec_user_agent == "FinRobot admin@example.com"  # class default
        assert s.log_level == "INFO"  # class default

    def test_dotenv_file_not_read(self, tmp_path, monkeypatch):
        """Even a .env sitting in the process cwd must be ignored."""
        env = tmp_path / ".env"
        env.write_text("FINROBOT_OPENAI_API_KEY=sk-from-dotenv\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        s = get_settings()
        assert s.openai_api_key == ""


def test_logging_defaults() -> None:
    from finrobot.config import FinRobotSettings

    s = FinRobotSettings()
    assert s.log_to_file is True
    assert s.log_retention_days == 7
    assert s.log_level == "INFO"
