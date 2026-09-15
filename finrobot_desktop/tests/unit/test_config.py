from pathlib import Path

import pytest

from finrobot.config import BUILTIN_PROVIDERS, FinRobotSettings, ProviderConfig, get_settings


class TestDefaults:
    # Config is app-stored-only: FinRobotSettings reads ONLY constructor kwargs,
    # never env / .env (settings_customise_sources drops those sources). So a
    # bare FinRobotSettings() reflects the class defaults regardless of the
    # developer's shell or repo-root .env — no monkeypatch.delenv scaffolding
    # needed any more.
    def test_default_model_name_is_empty(self):
        # Empty on purpose: a fresh install has no LLM key, so a baked-in default
        # forced every first boot into a startup_error banner that read like the
        # product demanded OpenAI. Empty = "no model chosen yet" (onboarding).
        s = FinRobotSettings()
        assert s.model_name == ""
        assert s.is_model_configured is False

    def test_default_has_no_provider_keys(self):
        s = FinRobotSettings()
        # LLM keys live in the keychain (provider_key:<id>), never in defaults.
        assert s.provider_key("openai") is None
        assert s.provider_key("anthropic") is None
        assert s.custom_providers == []

    def test_default_providers_are_the_builtins(self):
        s = FinRobotSettings()
        ids = [p.id for p in s.providers]
        # Only the two majors are built in; everything else is a custom provider.
        assert ids == ["anthropic", "openai"]
        openai = s.provider_by_id("openai")
        assert openai is not None and openai.kind == "openai-compatible"

    def test_custom_providers_extend_the_registry(self):
        s = get_settings(
            custom_providers=[
                {
                    "id": "myhost",
                    "label": "My vLLM",
                    "kind": "openai-compatible",
                    "base_url": "https://h/v1",
                    "models": ["local-7b"],
                }
            ]
        )
        ids = [p.id for p in s.providers]
        assert ids[: len(BUILTIN_PROVIDERS)] == [p.id for p in BUILTIN_PROVIDERS]
        assert ids[-1] == "myhost"
        myhost = s.provider_by_id("myhost")
        assert myhost is not None and myhost.base_url == "https://h/v1"

    def test_env_var_is_ignored_for_user_config(self, monkeypatch):
        """A FINROBOT_* env var must NOT leak into user config — the whole point
        of the app-stored-only model (packaging safety + no source ambiguity)."""
        monkeypatch.setenv("FINROBOT_OPENAI_API_KEY", "sk-from-env")
        monkeypatch.setenv("FINROBOT_MODEL_NAME", "anthropic:claude-sonnet-4-6")
        s = FinRobotSettings()
        assert s.provider_key("openai") is None
        assert s.model_name == ""

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

    def test_peer_sticky_window_defaults_to_one_week(self):
        s = FinRobotSettings()
        assert s.peer_sticky_max_age_days == 7


class TestProviderKeyPrivacy:
    """Provider API keys are a PrivateAttr — they must never leak into
    model_dump() / settings.json / a debug repr (ADR-0013)."""

    def test_keys_absent_from_model_dump(self):
        s = get_settings(provider_keys={"openai": "sk-secret-xyz"})
        dump = str(s.model_dump())
        assert "sk-secret-xyz" not in dump
        assert "_provider_keys" not in s.model_dump()

    def test_with_provider_keys_returns_copy(self):
        base = FinRobotSettings()
        keyed = base.with_provider_keys({"openai": "sk-x"})
        assert base.provider_key("openai") is None  # original untouched
        assert keyed.provider_key("openai") == "sk-x"

    def test_blank_keys_are_dropped(self):
        s = FinRobotSettings().with_provider_keys({"openai": "", "anthropic": "sk-a"})
        assert s.provider_key("openai") is None
        assert s.provider_key("anthropic") == "sk-a"


class TestConstructorOverride:
    def test_model_name_override(self):
        s = get_settings(model_name="anthropic:claude-sonnet-4-6")
        assert s.model_name == "anthropic:claude-sonnet-4-6"

    def test_multiple_overrides(self):
        s = get_settings(model_name="openai:gpt-4o", cache_db_path="/tmp/test.db")
        assert s.model_name == "openai:gpt-4o"
        assert s.cache_db_path == "/tmp/test.db"

    def test_peer_sticky_window_override(self):
        s = get_settings(peer_sticky_max_age_days=0)
        assert s.peer_sticky_max_age_days == 0


class TestCreateModel:
    def test_anthropic_returns_anthropic_model(self):
        from pydantic_ai.models.anthropic import AnthropicModel

        s = get_settings(
            model_name="anthropic:claude-sonnet-4-6", provider_keys={"anthropic": "sk-test"}
        )
        model = s.create_model()
        assert isinstance(model, AnthropicModel)

    def test_openai_returns_openai_chat_model(self):
        from pydantic_ai.models.openai import OpenAIChatModel

        s = get_settings(model_name="openai:gpt-4o", provider_keys={"openai": "sk-test"})
        model = s.create_model()
        assert isinstance(model, OpenAIChatModel)

    def test_custom_openai_compatible_uses_base_url(self):
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        s = get_settings(
            model_name="myhost:local-7b",
            custom_providers=[
                ProviderConfig(
                    id="myhost",
                    label="My vLLM",
                    kind="openai-compatible",
                    base_url="https://my-host/v1",
                )
            ],
            provider_keys={"myhost": "sk-local"},
        )
        model = s.create_model()
        assert isinstance(model, OpenAIChatModel)
        assert isinstance(model._provider, OpenAIProvider)
        # base_url is normalised with a trailing slash by the OpenAI client.
        assert model._provider.base_url.rstrip("/") == "https://my-host/v1"

    def test_test_provider_returns_test_model(self):
        from pydantic_ai.models.test import TestModel

        s = get_settings(model_name="test:test")
        assert isinstance(s.create_model(), TestModel)

    def test_unknown_provider_raises(self):
        s = get_settings(model_name="unknown:model")
        with pytest.raises(ValueError, match="Unknown provider 'unknown'"):
            s.create_model()

    def test_empty_model_id_raises(self):
        s = get_settings(model_name="openai:", provider_keys={"openai": "sk-test"})
        with pytest.raises(ValueError, match="Model id must not be empty"):
            s.create_model()

    def test_does_not_pollute_environ(self, monkeypatch):
        import os

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        s = get_settings(model_name="openai:gpt-4o", provider_keys={"openai": "sk-secret"})
        s.create_model()
        assert os.environ.get("OPENAI_API_KEY") is None

    def test_shared_llm_http_client_is_warm_and_proxy_aware(self):
        """The shared LLM client keeps the proxied TLS socket warm across turns
        while bounding stalls on a flaky proxy.

        Guards the TTFT fix: a keepalive_expiry well above httpx's default 5s (which
        drops the idle socket between turns and forces a ~3.3s re-handshake) and
        trust_env=True so HTTP(S)_PROXY from the environment is honoured. Also
        guards the stall-ceiling fix: keepalive and read are deliberately NOT 300s
        — through a flaky Clash proxy a long-idle socket is likely dead and httpx
        would reuse it then block on `read` before noticing, so both are bounded so
        a stalled turn fails over in ~2min instead of hanging 5min as "still
        waiting…".
        """
        import httpx

        from finrobot.config import _shared_llm_http_client

        client = _shared_llm_http_client()
        assert isinstance(client, httpx.AsyncClient)
        # trust_env defaults to True -> httpx reads HTTP_PROXY/HTTPS_PROXY/NO_PROXY.
        assert client.trust_env is True
        # Warm across normal turn gaps, but not so long a dead proxy socket lingers.
        pool = client._transport._pool
        assert pool._keepalive_expiry == 90.0
        assert pool._max_keepalive_connections == 20
        # read is the per-chunk GAP ceiling (not total generation) — bounds a stall.
        assert client.timeout.read == 120.0
        assert client.timeout.connect == 10.0

    def test_passes_shared_http_client_to_provider(self, monkeypatch):
        """create_model hands the process-wide shared client to the LLM provider,
        reusing the SAME object across calls (mirrors Claude Code's single shared
        dispatcher — a fresh client per call would reintroduce the per-turn TLS
        handshake the fix exists to kill).
        """
        from finrobot.config import _shared_llm_http_client

        captured: list[object] = []

        def _fake_openai_provider(*, base_url, api_key, http_client):
            captured.append(http_client)
            return object()

        monkeypatch.setattr("pydantic_ai.providers.openai.OpenAIProvider", _fake_openai_provider)
        monkeypatch.setattr(
            "pydantic_ai.models.openai.OpenAIChatModel",
            lambda model_id, provider: object(),
        )

        s = get_settings(model_name="openai:gpt-4o", provider_keys={"openai": "sk-test"})
        s.create_model()
        s.create_model()
        assert len(captured) == 2
        # Same shared client every call, and it is the module singleton.
        assert captured[0] is captured[1]
        assert captured[0] is _shared_llm_http_client()


class TestValidateRuntimeConfig:
    """P3 audit D2: single source of truth for model + data config validation,
    shared between CLI and SDK. Raises ValueError (not ClickException)."""

    def test_valid_config_passes(self):
        s = get_settings(
            model_name="openai:gpt-4o",
            provider_keys={"openai": "sk-x"},
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

    def test_empty_model_id_raises_value_error(self):
        s = get_settings(
            model_name="openai:",
            provider_keys={"openai": "sk-x"},
            fmp_api_key="fmp-test-key",
        )
        with pytest.raises(ValueError, match="Model id must not be empty"):
            s.validate_runtime_config()

    def test_missing_llm_api_key_raises_value_error(self):
        s = get_settings(
            model_name="anthropic:claude-sonnet-4-6",
            fmp_api_key="fmp-test-key",
        )
        with pytest.raises(ValueError, match="No API key configured for provider 'anthropic'"):
            s.validate_runtime_config()

    def test_custom_provider_validates_against_registry(self):
        s = get_settings(
            model_name="myhost:local-7b",
            custom_providers=[
                ProviderConfig(
                    id="myhost", label="My", kind="openai-compatible", base_url="https://h/v1"
                )
            ],
            provider_keys={"myhost": "sk-local"},
            fmp_api_key="fmp-test-key",
        )
        s.validate_runtime_config()  # registered + keyed → passes

    def test_missing_fmp_api_key_emits_warning(self):
        """FMP key is optional — emits warning, never raises (analyst-grade fallback)."""
        import warnings

        s = get_settings(model_name="test")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            s.validate_runtime_config()
        fmp_warnings = [w for w in caught if "FMP" in str(w.message)]
        assert len(fmp_warnings) == 1
        assert "yfinance" in str(fmp_warnings[0].message)


class TestEmptyModelOnboarding:
    """The first-run contract: an empty model_name is onboarding, not an error.

    validate_runtime_config (CLI/SDK) hard-fails with an actionable message;
    runtime_config_error (desktop server) returns None so no banner shows; and
    is_model_configured gates agent construction across both paths.
    """

    def test_empty_model_validate_raises_actionable(self):
        s = get_settings(model_name="", fmp_api_key="fmp-test-key")
        with pytest.raises(ValueError, match="No AI model configured"):
            s.validate_runtime_config()

    def test_whitespace_only_model_treated_as_empty(self):
        s = get_settings(model_name="   ", fmp_api_key="fmp-test-key")
        assert s.is_model_configured is False
        with pytest.raises(ValueError, match="No AI model configured"):
            s.validate_runtime_config()

    def test_empty_model_is_not_a_banner_error(self):
        # The desktop boot/PUT path: empty model surfaces NO startup_error.
        s = get_settings(model_name="")
        assert s.runtime_config_error() is None
        assert s.is_model_configured is False

    def test_chosen_but_keyless_model_is_not_a_banner_error(self):
        # Picking a provider/model before pasting the key is normal onboarding —
        # surfaced as the friendly "add a key" notice + a 503, NOT a red banner.
        # (Regression: it used to fire "Startup configuration error" the instant
        # the user selected a provider, before they could type the key.)
        s = get_settings(model_name="anthropic:claude-sonnet-4-6")
        assert s.runtime_config_error() is None
        assert s.is_model_configured is False

    def test_half_typed_model_id_is_not_a_banner_error(self):
        # "openai:" — provider picked, model not chosen yet. Mid-setup, not error.
        s = get_settings(model_name="openai:")
        assert s.runtime_config_error() is None
        assert s.is_model_configured is False

    def test_fully_configured_model_is_ready(self):
        s = get_settings(
            model_name="anthropic:claude-sonnet-4-6",
            provider_keys={"anthropic": "sk-x"},
        )
        assert s.is_model_configured is True
        assert s.runtime_config_error() is None

    def test_test_provider_is_configured_without_key(self):
        s = get_settings(model_name="test:test")
        assert s.is_model_configured is True

    def test_unknown_provider_is_not_configured(self):
        s = get_settings(model_name="bogus:model-x")
        assert s.is_model_configured is False
        assert s.runtime_config_error() is not None


class TestNoEnvReading:
    """Config is app-stored-only — neither a FINROBOT_* env var nor a .env file
    may feed user config. These guard the settings_customise_sources override
    that drops the env + dotenv sources (packaging safety + source clarity).

    The three pure-infra knobs (skills_dir / cache_db_path /
    backtest_strategy_module_prefixes) still read their own env var in
    model_post_init — covered by test_cli / test_backtrader_adapter."""

    def test_user_config_env_vars_ignored(self, monkeypatch):
        for var, val in {
            "FINROBOT_OPENAI_API_KEY": "sk-oai",
            "FINROBOT_FMP_API_KEY": "fmp",
            "FINROBOT_SEC_USER_AGENT": "Hacker evil@example.com",
            "FINROBOT_LOG_LEVEL": "DEBUG",
        }.items():
            monkeypatch.setenv(var, val)
        s = get_settings()
        assert s.provider_key("openai") is None
        assert s.fmp_api_key == ""
        assert s.sec_user_agent == "FinRobot admin@example.com"  # class default
        assert s.log_level == "INFO"  # class default

    def test_dotenv_file_not_read(self, tmp_path, monkeypatch):
        """Even a .env sitting in the process cwd must be ignored."""
        env = tmp_path / ".env"
        env.write_text("FINROBOT_OPENAI_API_KEY=sk-from-dotenv\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        s = get_settings()
        assert s.provider_key("openai") is None


def test_logging_defaults() -> None:
    from finrobot.config import FinRobotSettings

    s = FinRobotSettings()
    assert s.log_to_file is True
    assert s.log_retention_days == 7
    assert s.log_level == "INFO"


def test_log_retention_days_rejects_negative_values() -> None:
    with pytest.raises(ValueError):
        get_settings(log_retention_days=-1)


def test_log_level_normalizes_to_uppercase() -> None:
    settings = get_settings(log_level="debug")
    assert settings.log_level == "DEBUG"


def test_log_level_rejects_unknown_values() -> None:
    with pytest.raises(ValueError):
        get_settings(log_level="TRACE")
