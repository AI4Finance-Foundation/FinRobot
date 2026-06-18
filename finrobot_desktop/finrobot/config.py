from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

import httpx
from pydantic import BaseModel, Field, PrivateAttr, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

if TYPE_CHECKING:
    # Annotation-only (create_model's return type). Importing pydantic_ai.models
    # at runtime pulls the pydantic_ai stack onto the cold-start path, and config
    # is imported by nearly everything (auth → server, every route) — so this one
    # edge gated the whole sidecar boot. create_model() imports the concrete
    # Model subclass lazily at call time. See tests/unit/test_cold_import.py.
    from pydantic_ai.models import Model


logger = logging.getLogger(__name__)


# httpx `read` is the per-chunk GAP timeout (max wait between received chunks),
# NOT the total-generation budget — a streaming response resets it on every
# chunk. So it only ever fires on time-to-first-token or a mid-stream STALL;
# continuous token streams (sub-second gaps) and long report generations are
# unaffected, and a long chat tool call runs *between* separate OpenAI calls, not
# within one read. The old 300s made a stalled connection (common through the
# user's flaky Clash proxy — silently-dropped sockets, see keepalive below) hang
# for a full 5 minutes before failing over to the non-streaming fallback, which
# read as "still waiting…" forever. 120s bounds that stall while still leaving
# generous headroom for a slow first token (gpt-4o first-byte is ~1-4s warm; a
# reasoning model with a long silent think phase would need this raised).
# connect stays short so a dead proxy fails fast.
_LLM_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)

# One shared httpx.AsyncClient reused process-wide for every LLM provider —
# mirrors how Claude Code keeps a single shared dispatcher with a warm
# connection pool. The win is amortising the TLS handshake: through the user's
# Clash proxy the OpenAI handshake costs ~3.3s and is otherwise paid on EVERY
# turn, because httpx's default keepalive_expiry=5s drops the idle socket
# during the tens-of-seconds gap between turns. Raising keepalive_expiry to
# 90s keeps the socket alive across normal turn gaps (read→type→send is well
# under that) so it gets reused — first-byte drops from ~4.4s to ~1.2s on a warm
# connection. It is deliberately NOT the old 300s: through the flaky Clash proxy
# a socket idle for minutes is likely already dead, and httpx would blindly reuse
# it and then block on the read timeout above before discovering the corpse —
# turning a warm-pool optimisation into a stall. 90s bounds that staleness window
# to roughly one human turn-gap while keeping the warm-reuse win during an active
# back-and-forth. (A socket that dies mid-window still stalls until the read
# timeout, then errors and is dropped from the pool — not reused again.)
#
# trust_env defaults to True, so httpx honours HTTP_PROXY/HTTPS_PROXY/NO_PROXY
# from the environment — the same proxy the rest of the process uses.
#
# Lazily constructed on first use (NOT at import) so no event loop is required
# at import time; bound to the server's running loop on first create_model().
_llm_http_client: httpx.AsyncClient | None = None


def _shared_llm_http_client() -> httpx.AsyncClient:
    """Return the process-wide LLM httpx client, building it on first use.

    Reused across all agents/providers so the proxied TLS connection stays warm
    between chat turns instead of being re-handshaked each turn. See module-level
    ``_llm_http_client`` for the keepalive rationale.
    """
    global _llm_http_client
    if _llm_http_client is None:
        _llm_http_client = httpx.AsyncClient(
            timeout=_LLM_TIMEOUT,
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=100,
                keepalive_expiry=90.0,
            ),
        )
    return _llm_http_client


ProviderKind = Literal["openai-compatible", "anthropic", "test"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


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

    id: str  # referenced by model_name's "<id>:<model>" prefix, e.g. "openai"
    label: str  # human-facing name shown in the UI, e.g. "OpenAI"
    kind: ProviderKind
    # base_url is used by openai-compatible providers. The anthropic built-in
    # leaves it None and lets AnthropicProvider supply the canonical endpoint.
    base_url: str | None = None
    models: list[str] = Field(default_factory=list)


# Built-in providers shipped with FinRobot. Kept deliberately to the two majors
# (Anthropic + OpenAI); anything else (DeepSeek / Moonshot / Qwen / OpenRouter /
# a local vLLM) the user wires up as a custom OpenAI-compatible provider. These
# are code-owned and NOT persisted to settings.json — only ``custom_providers`` are.
#
# ``models`` is a short list of *suggestions* only — the model id field in the UI
# is free text, so the user can run any model the provider exposes (we can't keep
# a complete, current list of every model id, and don't pretend to).
BUILTIN_PROVIDERS: tuple[ProviderConfig, ...] = (
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
)

# DataProvider secrets stored as fixed keychain keys + fixed FinRobotSettings
# fields (these are financial-data API keys, NOT LLM provider keys — those use
# the dynamic provider_key:<id> scheme). Single source of truth shared by the
# server's hydrate step and the settings route, so the two can't drift apart.
DATA_PROVIDER_SECRET_FIELDS: tuple[str, ...] = (
    "fmp_api_key",
    "finnhub_api_key",
    "alpha_vantage_api_key",
    "adanos_api_key",
)


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

    # Model — "<provider_id>:<model_id>", e.g. "anthropic:claude-sonnet-4-6". One
    # model for the whole pipeline; there are no per-role overrides ("配的是啥就是啥").
    #
    # Default is EMPTY on purpose: a brand-new install has no LLM key, so any
    # baked-in default (the old "openai:gpt-4o") forced every fresh boot into a
    # startup_error state and a banner that read like the product *demands*
    # OpenAI. Empty = "no model chosen yet" — a normal first-run onboarding
    # state, NOT an error: the deterministic data layer (prices/financials/DCF)
    # runs without any LLM key; only AI report/chat need a model. The
    # server distinguishes empty (onboarding) from set-but-broken (real error)
    # via ``runtime_config_error`` / ``is_model_configured``.
    model_name: str = ""

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
    log_level: LogLevel = "INFO"
    log_to_file: bool = True
    log_retention_days: int = Field(default=7, ge=0)
    peer_sticky_max_age_days: int = Field(
        default=7,
        ge=0,
        description=(
            "Maximum age of a parent artifact whose peer set may be reused during "
            "a same-ticker re-run. 0 disables peer-set stickiness."
        ),
    )

    # Output language for LLM narrative. "en" = English, "zh" = Chinese (简体中文).
    # Only affects LLM-generated text — deterministic calculations are unchanged.
    language: str = Field(default="en", pattern=r"^(en|zh)$")

    # Coverage watchlist anomaly threshold — a 1-day move whose magnitude meets
    # or exceeds this is pre-flagged (deterministically, in Python) in the chat
    # snapshot the LLM sees, so the assistant calls out the move rather than
    # judging "big" itself. UNIT = percentage POINTS, matching
    # ``CoverageRow.change_pct_1d`` (NormalizedPrices.latest_session_change
    # returns ``change / prev_close * 100`` — e.g. 3.0 == ±3 %). 3 % is a ~2σ
    # daily move for a typical large-cap, the desk's "worth a glance" bar.
    coverage_anomaly_change_threshold: float = Field(
        default=3.0,
        gt=0,
        description=(
            "Absolute 1-day % move (in percentage points) at/above which a "
            "watchlist name is pre-flagged as a mover in the chat snapshot."
        ),
    )

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

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().upper()
        return value

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

    @staticmethod
    def _parse_model_name(name: str) -> tuple[str, str]:
        provider_id, sep, model_id = name.partition(":")
        provider_id = provider_id.strip()
        model_id = model_id.strip()
        if not provider_id:
            raise ValueError(
                f"Invalid model_name '{name}'. Format: provider:model_id "
                f"(e.g. anthropic:claude-sonnet-4-6)"
            )
        if provider_id == "test" and not sep:
            return provider_id, "test"
        if not sep or not model_id:
            raise ValueError(
                f"Invalid model_name '{name}'. Model id must not be empty. "
                f"Format: provider:model_id (e.g. anthropic:claude-sonnet-4-6)"
            )
        return provider_id, model_id

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
        name = self.model_name.strip()
        if not name:
            # No model chosen. For CLI/SDK callers this IS a hard error (they
            # exist to run analysis), so raise with an actionable message. The
            # desktop server does NOT route through here for the empty case —
            # it calls ``runtime_config_error`` (returns None for empty) so a
            # first-run user gets onboarding, not a 503 banner.
            raise ValueError(
                "No AI model configured. Choose one in Settings → AI Model "
                "(e.g. anthropic:claude-sonnet-4-6)."
            )
        provider_id, _model_id = self._parse_model_name(name)
        if provider_id == "test":
            return  # built-in test harness provider — no key required
        cfg = self.provider_by_id(provider_id)
        if cfg is None:
            valid_ids = ", ".join(p.id for p in self.providers)
            raise ValueError(
                f"Unknown provider '{provider_id}' in model_name '{name}'. "
                f"Configured providers: {valid_ids}. "
                f"Format: provider:model_id "
                f"(e.g. anthropic:claude-sonnet-4-6)"
            )
        if cfg.kind == "test":
            return  # a provider explicitly declared as a test stub
        if not self.provider_key(provider_id):
            raise ValueError(
                f"No API key configured for provider '{provider_id}' "
                f"(required by model '{name}'). "
                f"Add it in Settings → AI Model."
            )

    @property
    def is_model_configured(self) -> bool:
        """True when a usable LLM is selected: a model is chosen AND its
        provider has a key (or is a test stub).

        This is the gate for building agents and for AI-route readiness — every
        false branch (no model / unknown provider / missing key) would crash
        ``create_model``, so callers MUST check this before constructing agents.
        Pure (no warnings, no side effects) so per-request route guards can call
        it freely, unlike ``validate_runtime_config``.
        """
        name = self.model_name.strip()
        if not name:
            return False
        try:
            provider_id, _model_id = self._parse_model_name(name)
        except ValueError:
            return False
        if provider_id == "test":
            return True
        cfg = self.provider_by_id(provider_id)
        if cfg is None:
            return False
        if cfg.kind == "test":
            return True
        return bool(self.provider_key(provider_id))

    def runtime_config_error(self) -> str | None:
        """The startup_error banner string for a STRUCTURALLY broken config,
        else None. Use on the server boot/PUT paths (NOT validate_runtime_config,
        which hard-fails on any incompleteness — right for CLI/SDK, wrong here).

        Incomplete setup is NOT an error and must never raise the red banner:
        - no model chosen yet (empty),
        - a half-typed model id mid-setup (e.g. "openai:" right after picking a
          provider, before choosing a model),
        - a chosen model whose API key hasn't been pasted yet.
        All three are the normal onboarding path — surfaced as the friendly
        "add a key" notice + a 503 on AI routes (via ``is_model_configured``),
        never an alarming "Startup configuration error". The user picking a
        provider must not be punished with a red error before they can type the
        key (a real complaint: it read like the app was broken / demanded a
        specific model).

        The ONLY thing worth alarming on is a model_name pointing at a provider
        that doesn't exist — only reachable via a corrupt/hand-edited
        settings.json, a genuine boot error.
        """
        name = self.model_name.strip()
        if not name:
            return None
        try:
            provider_id, _model_id = self._parse_model_name(name)
        except ValueError:
            # Half-typed during setup (e.g. "openai:") — onboarding, not an error.
            return None
        if provider_id == "test":
            return None
        cfg = self.provider_by_id(provider_id)
        if cfg is None:
            valid = ", ".join(p.id for p in self.providers)
            return (
                f"Model '{name}' references unknown provider '{provider_id}'. "
                f"Configured providers: {valid}."
            )
        # Missing key reaches here → return None: it's onboarding, not a banner.
        return None

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
        name = model_name or self.model_name  # e.g. "openai:gpt-4o"
        provider_id, model_id = self._parse_model_name(name)

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

        # One shared, warm-pooled httpx client for every provider (see
        # _shared_llm_http_client) so the proxied TLS connection survives the
        # gap between turns instead of being re-handshaked each turn.
        http_client = _shared_llm_http_client()

        if cfg.kind == "anthropic":
            from pydantic_ai.models.anthropic import AnthropicModel
            from pydantic_ai.providers.anthropic import AnthropicProvider

            return AnthropicModel(
                model_id,
                provider=AnthropicProvider(
                    api_key=api_key, base_url=cfg.base_url, http_client=http_client
                ),
            )
        elif cfg.kind == "openai-compatible":
            # The universal base: OpenAI itself, DeepSeek, Moonshot, Qwen,
            # OpenRouter, a local vLLM — anything speaking the OpenAI chat API
            # at a base_url. Custom providers always land here.
            from pydantic_ai.models.openai import OpenAIChatModel
            from pydantic_ai.providers.openai import OpenAIProvider

            return OpenAIChatModel(
                model_id,
                provider=OpenAIProvider(
                    base_url=cfg.base_url, api_key=api_key, http_client=http_client
                ),
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


# Per-launch capability token. Set by the Tauri shell on the sidecar's env (see
# desktop/src-tauri); read here (not in auth.py) because config.py is the only
# module — besides secret_store — allowed to touch os.environ (audit red-line).
CAPABILITY_TOKEN_ENV = "FINROBOT_CAPABILITY_TOKEN"


def get_capability_token() -> str | None:
    """Return the per-launch capability token, or None when auth is disabled.

    Read live from the environment on each call (not cached) so the desktop
    sidecar — which receives it via env at spawn — enforces it, while the
    browser dev loop and the test harness (no env) stay auth-free, and tests
    can toggle enforcement with ``monkeypatch.setenv``.
    """
    token = os.environ.get(CAPABILITY_TOKEN_ENV)
    return token or None
