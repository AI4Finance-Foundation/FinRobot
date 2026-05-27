import pytest

from finrobot.config import FinRobotSettings, get_settings


class TestDefaults:
    def test_default_model_name(self, monkeypatch):
        monkeypatch.delenv("FINROBOT_MODEL_NAME", raising=False)
        s = FinRobotSettings(_env_file=None)
        assert s.model_name == "deepseek:deepseek-chat"

    def test_default_api_keys_empty(self, monkeypatch):
        # Clear env vars + skip .env file so we test true defaults
        for key in [
            "FINROBOT_ANTHROPIC_API_KEY",
            "FINROBOT_DEEPSEEK_API_KEY",
            "FINROBOT_OPENAI_API_KEY",
        ]:
            monkeypatch.delenv(key, raising=False)
        s = FinRobotSettings(_env_file=None)
        assert s.anthropic_api_key == ""
        assert s.deepseek_api_key == ""
        assert s.openai_api_key == ""

    def test_default_cache_db_path(self):
        s = get_settings()
        # Resolved at runtime: legacy cwd ``finrobot_cache.db`` if present,
        # else unified ``~/.finrobot/data_cache.db`` from paths.py.
        assert s.cache_db_path  # non-empty after model_post_init
        assert s.cache_db_path.endswith("data_cache.db") or s.cache_db_path.endswith(
            "finrobot_cache.db"
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
        monkeypatch.delenv("FINROBOT_DEEPSEEK_API_KEY", raising=False)
        s = FinRobotSettings(
            _env_file=None,
            model_name="deepseek:deepseek-chat",
            fmp_api_key="fmp-test-key",
        )
        with pytest.raises(ValueError, match="FINROBOT_DEEPSEEK_API_KEY is not set"):
            s.validate_runtime_config()

    def test_missing_fmp_api_key_emits_warning(self, monkeypatch):
        """FMP key is optional — emits warning, never raises (散户优先：yfinance fallback)."""
        import warnings

        monkeypatch.delenv("FINROBOT_FMP_API_KEY", raising=False)
        s = FinRobotSettings(_env_file=None, model_name="test")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            s.validate_runtime_config()
        fmp_warnings = [w for w in caught if "FINROBOT_FMP_API_KEY" in str(w.message)]
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


class TestLegacyEnvMigration:
    """Users who set up pre-rename have FINAGENT_* keys in .env that
    pydantic-settings now rejects. _migrate_legacy_env_prefix rewrites the
    file in place when ``get_settings()`` is called — verify it's idempotent,
    lossless, fail-safe on OSError, and that ``get_settings()`` actually
    drives the migration (not a module-import side effect)."""

    def test_migrates_finagent_prefix_in_place(self, tmp_path, monkeypatch):
        from finrobot import config as config_module

        env_file = tmp_path / ".env"
        env_file.write_text(
            "FINAGENT_OPENAI_API_KEY=sk-real\n"
            "FINAGENT_DEEPSEEK_API_KEY=ds-real\n"
            "# FINAGENT_CACHE_DB_PATH=finagent_cache.db\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(config_module, "_ENV_FILE", env_file)
        config_module._migrate_legacy_env_prefix()
        content = env_file.read_text(encoding="utf-8")
        assert "FINAGENT_" not in content
        assert "FINROBOT_OPENAI_API_KEY=sk-real" in content
        assert "FINROBOT_DEEPSEEK_API_KEY=ds-real" in content
        assert "finrobot_cache.db" in content
        assert "finagent_cache" not in content

    def test_idempotent_when_already_migrated(self, tmp_path, monkeypatch):
        from finrobot import config as config_module

        env_file = tmp_path / ".env"
        original = "FINROBOT_OPENAI_API_KEY=sk-real\n"
        env_file.write_text(original, encoding="utf-8")
        env_file_mtime = env_file.stat().st_mtime
        monkeypatch.setattr(config_module, "_ENV_FILE", env_file)
        config_module._migrate_legacy_env_prefix()
        assert env_file.read_text(encoding="utf-8") == original
        # No-op should not even touch the file (preserves mtime → cheap check).
        assert env_file.stat().st_mtime == env_file_mtime

    def test_safe_when_no_env_file(self, tmp_path, monkeypatch):
        from finrobot import config as config_module

        env_file = tmp_path / "nonexistent.env"
        monkeypatch.setattr(config_module, "_ENV_FILE", env_file)
        # Must not raise; absence of .env is a valid state (CI, fresh clone).
        config_module._migrate_legacy_env_prefix()
        assert not env_file.exists()

    def test_read_oserror_logs_warning_not_silent(self, tmp_path, monkeypatch, caplog):
        """Disk-full / permission errors during the read step must surface as a
        warning rather than be swallowed. Pre-fix, OSError was caught and
        returned None, masking real failures from operators."""
        from finrobot import config as config_module

        env_file = tmp_path / ".env"
        env_file.write_text("FINAGENT_OPENAI_API_KEY=sk\n", encoding="utf-8")
        monkeypatch.setattr(config_module, "_ENV_FILE", env_file)

        def _explode(*_args, **_kwargs):
            raise OSError("simulated permission denied")

        monkeypatch.setattr(type(env_file), "read_text", _explode)
        with caplog.at_level("WARNING", logger="finrobot.config"):
            config_module._migrate_legacy_env_prefix()  # must not raise
        assert any("Could not read" in rec.message for rec in caplog.records)

    def test_write_oserror_logs_warning_not_silent(self, tmp_path, monkeypatch, caplog):
        """OSError during the write step must surface as a warning too — and
        the file must be left in its original state (no partial overwrite)."""
        from finrobot import config as config_module

        env_file = tmp_path / ".env"
        original = "FINAGENT_OPENAI_API_KEY=sk\n"
        env_file.write_text(original, encoding="utf-8")
        monkeypatch.setattr(config_module, "_ENV_FILE", env_file)

        def _explode(self, *_args, **_kwargs):
            raise OSError("simulated disk full")

        monkeypatch.setattr(type(env_file), "write_text", _explode)
        with caplog.at_level("WARNING", logger="finrobot.config"):
            config_module._migrate_legacy_env_prefix()
        assert any("Could not write" in rec.message for rec in caplog.records)
        assert env_file.read_text(encoding="utf-8") == original

    def test_get_settings_drives_migration(self, tmp_path, monkeypatch):
        """get_settings() must trigger the migration before constructing the
        pydantic model — module-import alone no longer does it. Guards against
        anyone deleting the call from get_settings() and quietly regressing."""
        from finrobot import config as config_module

        env_file = tmp_path / ".env"
        env_file.write_text("FINAGENT_OPENAI_API_KEY=sk-real\n", encoding="utf-8")
        monkeypatch.setattr(config_module, "_ENV_FILE", env_file)
        # Ensure the override is honored by FinRobotSettings too — otherwise
        # pydantic-settings would re-read the original repo-root .env.
        config_module.get_settings(_env_file=str(env_file))
        content = env_file.read_text(encoding="utf-8")
        assert "FINAGENT_" not in content
        assert "FINROBOT_OPENAI_API_KEY=sk-real" in content

    def test_module_body_has_no_top_level_migration_call(self):
        """Importing finrobot.config must NOT trigger I/O. Previously the
        migration ran at module import (a polluted CI .env would mutate on
        every test process startup → unreproducible results). Static check
        of the module AST: no top-level statement may call
        ``_migrate_legacy_env_prefix``."""
        import ast
        from pathlib import Path as _Path

        from finrobot import config as config_module

        source = _Path(config_module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        top_level_calls = [
            node
            for node in tree.body
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "_migrate_legacy_env_prefix"
        ]
        assert top_level_calls == [], (
            "_migrate_legacy_env_prefix() must not be called at module top level — "
            "this is a regression of the import-time side-effect removal."
        )
