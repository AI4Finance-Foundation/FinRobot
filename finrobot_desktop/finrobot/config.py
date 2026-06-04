from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, PrivateAttr
from pydantic_ai.models import Model
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource


logger = logging.getLogger(__name__)


ProviderKind = Literal["openai-compatible", "anthropic", "deepseek", "test"]


class ProviderConfig(BaseModel):
    """One LLM provider in the model registry.

    This is the data-driven replacement for the old hardcoded
    ``_VALID_PROVIDERS`` / ``_PROVIDER_KEY_FIELD`` / ``create_model`` if-elif:
    a provider is a row of data, not a code branch, so adding any
    OpenAI-compatible backend (Moonshot / Qwen / OpenRouter / a local vLLM)
    is a config edit, never a code change.

    NOTE: ``ProviderConfig`` is an **LLM model factory descriptor** — it is NOT
    the ``DataProvider`` ABC in ``engine/data/interface.py`` (which is the
    financial-data fetch contract). Two different axes; don't conflate them.

    The provider's API key is NEVER stored here — it lives in the OS keychain
    under ``provider_key:<id>`` and is hydrated into ``FinRobotSettings``'s
    private ``_provider_keys`` map at boot. ``models`` is a list of *suggested*
    model ids for the UI dropdown; the user may run any model id the provider
    accepts (validation checks the provider exists + has a key, not that the
    model is in this list).
    """

    id: str  # referenced by model_name's "<id>:<model>" prefix, e.g. "deepseek"
    label: str  # human-facing name shown in the UI, e.g. "DeepSeek"
    kind: ProviderKind
    # base_url is used by openai-compatible (and optionally anthropic) providers.
    # deepseek/anthropic built-ins leave it None and let their PydanticAI provider
    # class supply the canonical endpoint.
    base_url: str | None = None
    models: list[str] = Field(default_factory=list)


# Built-in providers shipped with FinRobot. These are code-owned and evolve with
# releases (new model ids land here), so they are NOT persisted to settings.json
# — only the user's own ``custom_providers`` are. ``deepseek`` keeps kind
# "deepseek" (not "openai-compatible") on purpose: PydanticAI's DeepSeekProvider
# sets a custom model profile (reasoning_content thinking field, send-back-thinking,
# and tool_choice=required disabled for deepseek-reasoner) that a bare
# OpenAIProvider+base_url would silently drop — collapsing it would break
# deepseek-reasoner under forced-JSON pipelines. See ADR-0013.
BUILTIN_PROVIDERS: tuple[ProviderConfig, ...] = (
    ProviderConfig(
        id="deepseek",
        label="DeepSeek",
        kind="deepseek",
        models=["deepseek-chat", "deepseek-reasoner"],
    ),
    ProviderConfig(
        id="anthropic",
        label="Anthropic",
        kind="anthropic",
        models=["claude-sonnet-4-6", "claude-opus-4-8", "claude-haiku-4-5-20251001"],
    ),
    ProviderConfig(
        id="openai",
        label="OpenAI",
        kind="openai-compatible",
        base_url="https://api.openai.com/v1",
        models=["gpt-4o", "gpt-4o-mini"],
    ),
    ProviderConfig(
        id="moonshot",
        label="Moonshot (Kimi)",
        kind="openai-compatible",
        base_url="https://api.moonshot.cn/v1",
        models=["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
    ),
    ProviderConfig(
        id="qwen",
        label="Qwen (DashScope)",
        kind="openai-compatible",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        models=["qwen-plus", "qwen-max", "qwen-turbo"],
    ),
    ProviderConfig(
        id="openrouter",
        label="OpenRouter",
        kind="openai-compatible",
        base_url="https://openrouter.ai/api/v1",
        # OpenRouter exposes hundreds of namespaced ids; the user types theirs.
        models=[],
    ),
)

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

    # Model — "<provider_id>:<model_id>", e.g. "deepseek:deepseek-chat".
    model_name: str = "deepseek:deepseek-chat"

    # Per-role model overrides. None = use global model_name.
    # Lets users pick a cheap/fast model for data_agent (just transcribes
    # data) and a stronger model for modeling (needs reliable JSON output).
    model_data: str | None = None
    model_analysis: str | None = None
    model_modeling: str | None = None
    model_synthesis: str | None = None
    model_report: str | None = None

    # User-added LLM providers (OpenAI-compatible endpoints the user wires up in
    # Settings). Persisted to settings.json; merged AFTER BUILTIN_PROVIDERS by the
    # ``providers`` property. Built-ins are code-owned and intentionally NOT stored
    # here so new built-in model ids land via a release, never frozen in a user's
    # settings.json. A custom provider's API key lives in the keychain under
    # ``provider_key:<id>``, never in this list.
    custom_providers: list[ProviderConfig] = Field(default_factory=list)

    # LLM provider API keys, keyed by provider id. PrivateAttr (not a field) so it
    # is NEVER serialized by model_dump() / written to settings.json / leaked into
    # a debug log — keys are hydrated from the keychain (provider_key:<id>) at boot
    # via ``with_provider_keys``. See ADR-0013.
    _provider_keys: dict[str, str] = PrivateAttr(default_factory=dict)

    # Data provider API keys (P2a). These are DataProvider secrets, not LLM
    # provider keys, so they stay as fixed fields hydrated by their own names.
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

    @property
    def providers(self) -> list[ProviderConfig]:
        """Effective provider registry: built-ins first, then user customs.

        ``create_model`` / ``validate_runtime_config`` / the settings route all
        resolve a provider id against this list.
        """
        return [*BUILTIN_PROVIDERS, *self.custom_providers]

    def provider_by_id(self, provider_id: str) -> ProviderConfig | None:
        for provider in self.providers:
            if provider.id == provider_id:
                return provider
        return None

    def with_provider_keys(self, keys: dict[str, str]) -> FinRobotSettings:
        """Return a copy with LLM provider API keys injected (runtime-only).

        Keys are merged into the private ``_provider_keys`` map and never touch
        settings.json or model_dump(). Called by ``hydrate_settings_from_secrets``
        at boot with the keychain-stored ``provider_key:<id>`` values.
        """
        clone = self.model_copy()
        merged = {**self._provider_keys, **{k: v for k, v in keys.items() if v}}
        object.__setattr__(clone, "_provider_keys", merged)
        return clone

    def provider_key(self, provider_id: str) -> str | None:
        """The configured API key for a provider id, or None."""
        return self._provider_keys.get(provider_id) or None

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

        valid_ids = ", ".join(p.id for p in self.providers)
        for name in names_to_check:
            provider_id, _, _model_id = name.partition(":")
            if provider_id == "test":
                continue  # built-in test harness provider — no key required
            cfg = self.provider_by_id(provider_id)
            if cfg is None:
                raise ValueError(
                    f"Unknown provider '{provider_id}' in model_name '{name}'. "
                    f"Configured providers: {valid_ids}. "
                    f"Format: provider:model_id "
                    f"(e.g. anthropic:claude-sonnet-4-6)"
                )
            if cfg.kind == "test":
                continue  # a provider explicitly declared as a test stub
            if not self.provider_key(provider_id):
                raise ValueError(
                    f"No API key configured for provider '{provider_id}' "
                    f"(required by model '{name}'). "
                    f"Add it in Settings → AI Model."
                )

    def create_model(self, model_name: str | None = None) -> Model:
        """Create a PydanticAI Model for ``<provider_id>:<model_id>``.

        Resolves the provider id against the registry (``providers``) and
        constructs the matching PydanticAI provider, with the API key (from the
        private ``_provider_keys`` map) baked into the provider instance — no
        os.environ pollution.

        Args:
            model_name: Optional per-call override. When omitted, uses
                ``self.model_name`` (the global default).
        """
        name = model_name or self.model_name  # e.g. "deepseek:deepseek-chat"
        provider_id, _, model_id = name.partition(":")

        if provider_id == "test":
            from pydantic_ai.models.test import TestModel

            return TestModel()

        cfg = self.provider_by_id(provider_id)
        if cfg is None:
            raise ValueError(
                f"Unknown provider '{provider_id}' in model_name '{name}'. "
                f"Configured providers: {', '.join(p.id for p in self.providers)}. "
                f"Format: provider:model_id (e.g. anthropic:claude-sonnet-4-6)"
            )
        api_key = self.provider_key(provider_id)

        if cfg.kind == "deepseek":
            # DeepSeekProvider supplies a custom model profile (reasoning_content,
            # send-back-thinking, reasoner tool_choice handling) a bare
            # OpenAIProvider would drop — keep it. See ADR-0013.
            from pydantic_ai.models.openai import OpenAIChatModel
            from pydantic_ai.providers.deepseek import DeepSeekProvider

            return OpenAIChatModel(model_id, provider=DeepSeekProvider(api_key=api_key))
        elif cfg.kind == "anthropic":
            from pydantic_ai.models.anthropic import AnthropicModel
            from pydantic_ai.providers.anthropic import AnthropicProvider

            return AnthropicModel(
                model_id, provider=AnthropicProvider(api_key=api_key, base_url=cfg.base_url)
            )
        elif cfg.kind == "openai-compatible":
            # The universal底座: deepseek-clones, Moonshot, Qwen, OpenRouter, local
            # vLLM — anything that speaks the OpenAI chat API at a base_url.
            from pydantic_ai.models.openai import OpenAIChatModel
            from pydantic_ai.providers.openai import OpenAIProvider

            return OpenAIChatModel(
                model_id, provider=OpenAIProvider(base_url=cfg.base_url, api_key=api_key)
            )
        elif cfg.kind == "test":
            from pydantic_ai.models.test import TestModel

            return TestModel()
        else:  # pragma: no cover - exhaustive over ProviderKind
            raise ValueError(f"Unsupported provider kind '{cfg.kind}' for '{name}'.")


def get_settings(
    *, provider_keys: dict[str, str] | None = None, **overrides: Any
) -> FinRobotSettings:
    """Get settings. ``overrides`` carry the app-stored config values.

    The server loads ``settings.json`` and passes the non-secret fields here as
    kwargs; tests pass explicit values. There is no env / ``.env`` source — see
    ``FinRobotSettings`` for why user config is app-stored-only.

    ``provider_keys`` injects LLM provider API keys (``{provider_id: key}``) into
    the runtime-only ``_provider_keys`` map — used by tests and by callers that
    already hold the keychain values. They are never persisted.
    """
    settings = FinRobotSettings(**overrides)
    if provider_keys:
        settings = settings.with_provider_keys(provider_keys)
    return settings


def console_color_enabled(stream: Any) -> bool:
    """Whether to emit ANSI color on a console stream.

    True when the stream is a TTY and the standard ``NO_COLOR`` env var
    (no-color.org) is unset/empty. Lives in config.py because it is the only
    module (besides secret_store) allowed to read os.environ — the obs
    formatters must not peek at the environment themselves (audit red-line).
    """
    is_tty = bool(getattr(stream, "isatty", lambda: False)())
    return is_tty and os.environ.get("NO_COLOR", "") == ""
