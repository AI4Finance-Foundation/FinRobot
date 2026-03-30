import os

import pytest

from finagent.config import FinAgentSettings, get_settings


class TestDefaults:
    def test_default_model_name(self):
        s = get_settings()
        assert s.model_name == "deepseek:deepseek-chat"

    def test_default_api_keys_empty(self, monkeypatch):
        # Clear env vars + skip .env file so we test true defaults
        for key in ["FINAGENT_ANTHROPIC_API_KEY", "FINAGENT_DEEPSEEK_API_KEY", "FINAGENT_OPENAI_API_KEY"]:
            monkeypatch.delenv(key, raising=False)
        s = FinAgentSettings(_env_file=None)
        assert s.anthropic_api_key == ""
        assert s.deepseek_api_key == ""
        assert s.openai_api_key == ""

    def test_default_cache_db_path(self):
        s = get_settings()
        assert s.cache_db_path == "finagent_cache.db"


class TestConstructorOverride:
    def test_model_name_override(self):
        s = get_settings(model_name="anthropic:claude-sonnet-4-6")
        assert s.model_name == "anthropic:claude-sonnet-4-6"

    def test_multiple_overrides(self):
        s = get_settings(model_name="openai:gpt-4o", cache_db_path="/tmp/test.db")
        assert s.model_name == "openai:gpt-4o"
        assert s.cache_db_path == "/tmp/test.db"


class TestApplyApiKeys:
    def test_sets_env_var_when_value_nonempty_and_unset(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        s = get_settings(anthropic_api_key="sk-test-123")
        s.apply_api_keys()
        assert os.environ.get("ANTHROPIC_API_KEY") == "sk-test-123"

    def test_does_not_overwrite_existing_env_var(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "already-set")
        s = get_settings(anthropic_api_key="sk-should-not-win")
        s.apply_api_keys()
        assert os.environ.get("ANTHROPIC_API_KEY") == "already-set"

    def test_empty_api_key_not_written(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        s = get_settings(deepseek_api_key="")
        s.apply_api_keys()
        assert os.environ.get("DEEPSEEK_API_KEY") is None

    def test_sets_multiple_keys(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        s = get_settings(deepseek_api_key="ds-key", openai_api_key="oai-key")
        s.apply_api_keys()
        assert os.environ.get("DEEPSEEK_API_KEY") == "ds-key"
        assert os.environ.get("OPENAI_API_KEY") == "oai-key"
