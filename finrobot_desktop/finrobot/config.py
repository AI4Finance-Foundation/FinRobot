from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from pydantic import Field
from pydantic_ai.models import Model
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource


logger = logging.getLogger(__name__)


# Valid providers and the settings field holding their API key. A provider
# listed here but absent from _PROVIDER_KEY_FIELD needs no key (e.g. "test").
_VALID_PROVIDERS: frozenset[str] = frozenset({"deepseek", "anthropic", "openai", "test"})
_PROVIDER_KEY_FIELD: dict[str, str] = {
    "deepseek": "deepseek_api_key",
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
}

# Sub-agent roles with per-role model_<role> overrides on FinRobotSettings.
# Used by get_model_for_role + validate_runtime_config; keep in sync with the
# model_data / model_analysis / ... fields declared on FinRobotSettings.
_AGENT_ROLES: tuple[str, ...] = ("data", "analysis", "modeling", "synthesis", "report")


class FinRobotSettings(BaseSettings):
    """FinRobot configuration.

    User configuration — API keys, model selection, SEC identity, output
    language, logging — comes ONLY from app storage: ``settings.json`` (loaded
    by the server and passed as constructor kwargs) and the OS keychain. It is
    NEVER read from process environment variables or a ``.env`` file. A packaged
    desktop app must not depend on a ``.env`` shipped in (or missing from) the
    bundle, and the user fills these in via the in-app Settings screen — there
    is no second, invisible source to disagree with what they typed.

    Resolution order for user config (highest priority first):
    1. Constructor kwargs (settings.json values, or test/code overrides)
    2. Defaults below

    The only fields that still consult the environment are pure infrastructure
    knobs set by the runtime / bundle / ops, never by the user in-app —
    resolved explicitly in ``model_post_init``: ``skills_dir``
    (``FINROBOT_SKILLS_DIR``), ``cache_db_path`` (``FINROBOT_CACHE_DB_PATH``),
    and ``backtest_strategy_module_prefixes``
    (``FINROBOT_BACKTEST_STRATEGY_MODULE_PREFIXES``).
    """

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Read ONLY from constructor kwargs — drop the env and .env sources.

        This is what makes user config app-stored-only: pydantic-settings would
        otherwise pull ``FINROBOT_*`` env vars and a ``.env`` file in ahead of
        the defaults, reintroducing the very ambiguity (and packaging fragility)
        we removed. Infra knobs that legitimately need the environment read it
        explicitly in ``model_post_init`` instead.
        """
        return (init_settings,)

    # Model
    model_name: str = "deepseek:deepseek-chat"

    # Per-role model overrides. None = use global model_name.
    # Lets users pick a cheap/fast model for data_agent (just transcribes
    # data) and a stronger model for modeling (needs reliable JSON output).
    model_data: str | None = None
    model_analysis: str | None = None
    model_modeling: str | None = None
    model_synthesis: str | None = None
    model_report: str | None = None

    # API Keys — only fill the one you use
    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    openai_api_key: str = ""

    # Data provider API keys (P2a)
    fmp_api_key: str = ""
    finnhub_api_key: str = ""
    alpha_vantage_api_key: str = ""
    adanos_api_key: str = ""
    sec_user_agent: str = "FinRobot admin@example.com"
    # 2026-05-27 (EdgarTools migration): Per SEC policy, automated tools
    # MUST declare a real identity in the User-Agent. The default above is
    # a placeholder — ``_is_valid_identity`` rejects it so EdgarToolsProvider
    # is NOT registered into the data layer until the user replaces it. The
    # landing page banner ("⚡ 解锁 FinRobot 一手 SEC 数据") points users at
    # Settings to fill this in. Dismissal of that banner is persisted here:
    sec_identity_dismissed_at: datetime | None = None
    sec_holdings_auto_refresh: bool = False

    # Infrastructure
    cache_db_path: str = ""  # resolved at runtime by paths.default_data_cache_db_path()
    skills_dir: str = ""  # resolved at runtime by paths.default_skills_dir() (bundle-aware)
    log_level: str = "INFO"
    log_to_file: bool = True
    log_retention_days: int = 7

    # Output language for LLM narrative. "en" = English, "zh" = Chinese (简体中文).
    # Only affects LLM-generated text — deterministic calculations are unchanged.
    language: str = Field(default="en", pattern=r"^(en|zh)$")

    # Backtest: dynamic ``module:ClassName`` strategy loading is OFF by default
    # (BUG-063). The built-in registry ("sma_crossover") always resolves without
    # any import. To load a custom Strategy class via "your.module:ClassName",
    # whitelist an import-path prefix here (comma-separated allowed). This is an
    # ops/security knob, never user-facing — it is NOT in the Settings UI, so it
    # is resolved from ``FINROBOT_BACKTEST_STRATEGY_MODULE_PREFIXES`` in
    # ``model_post_init`` rather than from app storage. The prefix is validated
    # BEFORE importlib.import_module runs, so an empty default means no string
    # can trigger an arbitrary module import.
    # Example: FINROBOT_BACKTEST_STRATEGY_MODULE_PREFIXES="mystrats,team.alpha"
    backtest_strategy_module_prefixes: str = ""

    def model_post_init(self, __context: Any) -> None:
        """Resolve infrastructure knobs that depend on the runtime, not the user.

        ``cache_db_path`` / ``skills_dir`` default to "" so the resolved value
        reflects *this* process's environment — a frozen desktop sidecar unpacks
        ``skills/`` under ``sys._MEIPASS`` while a dev checkout uses the repo
        tree. These three are the only fields that consult the environment: they
        are pure infra/ops knobs (never shown in the Settings UI, never filled by
        the user in-app), so reading a specific env var here is the right source
        — unlike API keys / model selection, which come from app storage only.
        Precedence stays kwarg > env var > runtime default.
        """
        if not self.cache_db_path:
            env_cache = os.environ.get("FINROBOT_CACHE_DB_PATH")
            if env_cache:
                object.__setattr__(self, "cache_db_path", env_cache)
            else:
                from finrobot.paths import default_data_cache_db_path

                object.__setattr__(self, "cache_db_path", default_data_cache_db_path())
        if not self.skills_dir:
            env_skills = os.environ.get("FINROBOT_SKILLS_DIR")
            if env_skills:
                object.__setattr__(self, "skills_dir", env_skills)
            else:
                from finrobot.paths import default_skills_dir

                object.__setattr__(self, "skills_dir", default_skills_dir())
        if not self.backtest_strategy_module_prefixes:
            env_prefixes = os.environ.get("FINROBOT_BACKTEST_STRATEGY_MODULE_PREFIXES")
            if env_prefixes:
                object.__setattr__(self, "backtest_strategy_module_prefixes", env_prefixes)

    def get_model_for_role(self, role: str) -> str:
        """Return the model name for a specific agent role.

        Falls back to the global ``model_name`` if no override is configured
        for this role or if the role is unknown. Roles currently used by the
        sub-agent factory: data, analysis, modeling, synthesis, report.
        """
        override = getattr(self, f"model_{role}", None)
        return override or self.model_name

    def validate_runtime_config(self) -> None:
        """Fail fast if the model configuration is incoherent.

        Checks:
        - LLM: provider prefix must be supported; API key must be set.
        - Data: FMP API key is OPTIONAL. Without it, FinRobot falls back to
          yfinance for financials (D&A uses simplified formula, no earnings
          surprises, no cross-validation), which is fine for casual use.
          A warning is emitted at startup so users know what they're missing.

        Called from ``cli._build_deps`` and ``sdk.FinRobot.__init__`` so
        users get an immediate error message instead of waiting 60 seconds
        for the first LLM call to fail. Raises ``ValueError`` on failure;
        CLI callers wrap that into ``click.ClickException``.
        """
        # FMP key is optional — yfinance handles fallback. Just warn.
        if not self.fmp_api_key:
            import warnings

            warnings.warn(
                "FMP API key not set — falling back to yfinance. "
                "DCF will use simplified D&A formula (10-20% deviation), and "
                "earnings surprises + cross-validation are unavailable. "
                "Add an FMP key in Settings → Data Sources for better data "
                "(free at https://financialmodelingprep.com/).",
                stacklevel=2,
            )
        names_to_check: list[str] = [self.model_name]
        for role in _AGENT_ROLES:
            override = getattr(self, f"model_{role}", None)
            if override:
                names_to_check.append(override)

        for name in names_to_check:
            provider, _, _model_id = name.partition(":")
            if provider not in _VALID_PROVIDERS:
                raise ValueError(
                    f"Unknown provider '{provider}' in model_name '{name}'. "
                    f"Valid providers: {', '.join(sorted(_VALID_PROVIDERS))}. "
                    f"Format: provider:model_id "
                    f"(e.g. anthropic:claude-sonnet-4-6)"
                )
            key_field = _PROVIDER_KEY_FIELD.get(provider)
            if key_field is None:
                continue  # "test" provider — no key required
            if not getattr(self, key_field, ""):
                raise ValueError(
                    f"No API key configured for provider '{provider}' "
                    f"(required by model '{name}'). "
                    f"Add it in Settings → AI Model."
                )

    def create_model(self, model_name: str | None = None) -> Model:
        """Create a PydanticAI Model with API key passed directly.

        Args:
            model_name: Optional per-call override. When omitted, uses
                ``self.model_name`` (the global default).

        No os.environ pollution. The API key is baked into the provider instance.
        """
        name = model_name or self.model_name  # e.g. "deepseek:deepseek-chat"
        provider, _, model_id = name.partition(":")

        if provider == "deepseek":
            from pydantic_ai.models.openai import OpenAIChatModel
            from pydantic_ai.providers.deepseek import DeepSeekProvider

            return OpenAIChatModel(
                model_id, provider=DeepSeekProvider(api_key=self.deepseek_api_key or None)
            )
        elif provider == "anthropic":
            from pydantic_ai.models.anthropic import AnthropicModel
            from pydantic_ai.providers.anthropic import AnthropicProvider

            return AnthropicModel(
                model_id, provider=AnthropicProvider(api_key=self.anthropic_api_key or None)
            )
        elif provider == "openai":
            from pydantic_ai.models.openai import OpenAIChatModel
            from pydantic_ai.providers.openai import OpenAIProvider

            return OpenAIChatModel(
                model_id, provider=OpenAIProvider(api_key=self.openai_api_key or None)
            )
        elif provider == "test":
            from pydantic_ai.models.test import TestModel

            return TestModel()
        else:
            raise ValueError(
                f"Unknown provider '{provider}' in model_name '{name}'. "
                f"Valid providers: deepseek, anthropic, openai, test. "
                f"Format: provider:model_id (e.g. anthropic:claude-sonnet-4-6)"
            )


def get_settings(**overrides: Any) -> FinRobotSettings:
    """Get settings. ``overrides`` carry the app-stored config values.

    The server loads ``settings.json`` and passes the non-secret fields here as
    kwargs; tests pass explicit values. There is no env / ``.env`` source — see
    ``FinRobotSettings`` for why user config is app-stored-only.
    """
    return FinRobotSettings(**overrides)


def console_color_enabled(stream: Any) -> bool:
    """Whether to emit ANSI color on a console stream.

    True when the stream is a TTY and the standard ``NO_COLOR`` env var
    (no-color.org) is unset/empty. Lives in config.py because it is the only
    module (besides secret_store) allowed to read os.environ — the obs
    formatters must not peek at the environment themselves (audit red-line).
    """
    is_tty = bool(getattr(stream, "isatty", lambda: False)())
    return is_tty and os.environ.get("NO_COLOR", "") == ""
