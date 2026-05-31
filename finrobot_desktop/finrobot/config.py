from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_ai.models import Model
from pydantic_settings import BaseSettings


logger = logging.getLogger(__name__)


# Locate the .env relative to the source tree, not the process cwd. Tauri
# launches the Python sidecar from a different working directory (somewhere
# inside the .app bundle), so pydantic-settings' default env_file=".env"
# relative path silently misses every key in dev mode and leaves the user
# staring at "OPENAI_API_KEY must be set" while .env sits right there.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _REPO_ROOT / ".env"


def _migrate_legacy_env_prefix() -> None:
    """One-time in-place migration of legacy FINAGENT_* keys in .env → FINROBOT_*.

    The project renamed FinAgent → FinRobot; the env prefix moved with it.
    Users who set up pre-rename have a .env full of FINAGENT_* keys that
    pydantic-settings now rejects because the matching fields don't exist.
    Rewrite the file in place — idempotent, lossless, no backup needed since
    .env is git-ignored.

    Called from ``get_settings()`` before constructing ``FinRobotSettings``;
    NOT a module-import side effect (a pollutted CI .env would otherwise
    silently mutate every test process). I/O failures are logged as warnings
    rather than swallowed — disk-full / permission errors must be visible.
    """
    if not _ENV_FILE.exists():
        return
    try:
        original = _ENV_FILE.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not read %s for legacy-prefix migration: %s", _ENV_FILE, exc)
        return
    if "FINAGENT_" not in original and "finagent_cache" not in original:
        return
    updated = original.replace("FINAGENT_", "FINROBOT_").replace("finagent_cache", "finrobot_cache")
    try:
        _ENV_FILE.write_text(updated, encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write %s during legacy-prefix migration: %s", _ENV_FILE, exc)
        return
    logger.info("Migrated legacy FINAGENT_* → FINROBOT_* keys in %s", _ENV_FILE)


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

    Resolution order (highest priority first):
    1. Constructor kwargs (code override)
    2. Environment variables (FINROBOT_* prefix)
    3. .env file in project root
    4. Defaults below
    """

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
    skills_dir: str = "skills"  # path to vendored skills (relative to project root or absolute)
    log_level: str = "INFO"
    log_to_file: bool = True
    log_retention_days: int = 7

    # Notification channels — all optional; empty string = channel disabled
    feishu_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook_url: str = ""
    email_smtp_host: str = ""
    email_smtp_port: int = 587
    email_smtp_user: str = ""
    email_smtp_pass: str = ""
    email_to: str = ""
    custom_webhook_url: str = ""
    notify_on_complete: bool = True  # auto-notify when pipeline completes

    # Output language for LLM narrative. "en" = English, "zh" = Chinese (简体中文).
    # Only affects LLM-generated text — deterministic calculations are unchanged.
    language: str = Field(default="en", pattern=r"^(en|zh)$")

    model_config = {"env_prefix": "FINROBOT_", "env_file": str(_ENV_FILE)}

    def model_post_init(self, __context: Any) -> None:
        """Resolve cache_db_path default after env/settings loading."""
        if not self.cache_db_path:
            from finrobot.paths import default_data_cache_db_path

            object.__setattr__(self, "cache_db_path", default_data_cache_db_path())

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
                "FINROBOT_FMP_API_KEY not set — falling back to yfinance. "
                "DCF will use simplified D&A formula (10-20% deviation), and "
                "earnings surprises + cross-validation are unavailable. "
                "Register free at https://financialmodelingprep.com/ for better data.",
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
                env_var = f"FINROBOT_{key_field.upper()}"
                raise ValueError(
                    f"{env_var} is not set but model_name '{name}' needs it. "
                    f"Set it in .env or as an environment variable.\n"
                    f"  export {env_var}=your-key-here"
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
    """Get settings. Pass overrides for testing.

    Triggers the legacy ``FINAGENT_*`` → ``FINROBOT_*`` .env migration before
    constructing the settings model — pydantic-settings would otherwise read
    a pre-rename .env and reject every legacy key. Migration is idempotent,
    so the per-call overhead is a single ``Path.exists()`` (and at most one
    small file read) once the rewrite has occurred.
    """
    _migrate_legacy_env_prefix()
    return FinRobotSettings(**overrides)


def is_field_from_environ(field: str) -> bool:
    """True if FINROBOT_<FIELD> is set in the process environment.

    Lives in config.py so the os.environ peek does not leak into route
    code (audit red-line: only config.py + secret_store.py may touch
    os.environ). Note this does NOT distinguish a real env var from a
    value loaded out of .env — once pydantic-settings reads .env it
    populates pydantic state but does NOT set os.environ. So this
    function only fires for true OS-level env vars; .env-only values
    fall back to the "value present but no os env" inference path.
    """
    import os

    return bool(os.environ.get(f"FINROBOT_{field.upper()}"))


def console_color_enabled(stream: Any) -> bool:
    """Whether to emit ANSI color on a console stream.

    True when the stream is a TTY and the standard ``NO_COLOR`` env var
    (no-color.org) is unset/empty. Lives in config.py because it is the only
    module (besides secret_store) allowed to read os.environ — the obs
    formatters must not peek at the environment themselves (audit red-line).
    """
    import os

    is_tty = bool(getattr(stream, "isatty", lambda: False)())
    return is_tty and os.environ.get("NO_COLOR", "") == ""
