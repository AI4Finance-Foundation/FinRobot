from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_ai.models import Model
from pydantic_settings import BaseSettings


# Locate the .env relative to the source tree, not the process cwd. Tauri
# launches the Python sidecar from a different working directory (somewhere
# inside the .app bundle), so pydantic-settings' default env_file=".env"
# relative path silently misses every key in dev mode and leaves the user
# staring at "OPENAI_API_KEY must be set" while .env sits right there.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _REPO_ROOT / ".env"


# Valid providers and the settings field holding their API key. A provider
# listed here but absent from _PROVIDER_KEY_FIELD needs no key (e.g. "test").
_VALID_PROVIDERS: frozenset[str] = frozenset({"deepseek", "anthropic", "openai", "test"})
_PROVIDER_KEY_FIELD: dict[str, str] = {
    "deepseek": "deepseek_api_key",
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
}

# Sub-agent roles with per-role model_<role> overrides on FinAgentSettings.
# Used by get_model_for_role + validate_runtime_config; keep in sync with the
# model_data / model_analysis / ... fields declared on FinAgentSettings.
_AGENT_ROLES: tuple[str, ...] = ("data", "analysis", "modeling", "synthesis", "report")


class FinAgentSettings(BaseSettings):
    """FinAgent configuration.

    Resolution order (highest priority first):
    1. Constructor kwargs (code override)
    2. Environment variables (FINAGENT_* prefix)
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
    sec_user_agent: str = "FinAgent admin@example.com"

    # Infrastructure
    cache_db_path: str = ""  # resolved at runtime by paths.default_data_cache_db_path()
    skills_dir: str = "skills"  # path to vendored skills (relative to project root or absolute)
    log_level: str = "INFO"

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

    model_config = {"env_prefix": "FINAGENT_", "env_file": str(_ENV_FILE)}

    def model_post_init(self, __context: Any) -> None:
        """Resolve cache_db_path default after env/settings loading."""
        if not self.cache_db_path:
            from finagent.paths import default_data_cache_db_path

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
        - Data: FMP API key is OPTIONAL. Without it, FinAgent falls back to
          yfinance for financials (D&A uses simplified formula, no earnings
          surprises, no cross-validation), which is fine for casual use.
          A warning is emitted at startup so users know what they're missing.

        Called from ``cli._build_deps`` and ``sdk.FinAgent.__init__`` so
        users get an immediate error message instead of waiting 60 seconds
        for the first LLM call to fail. Raises ``ValueError`` on failure;
        CLI callers wrap that into ``click.ClickException``.
        """
        # FMP key is optional — yfinance handles fallback. Just warn.
        if not self.fmp_api_key:
            import warnings

            warnings.warn(
                "FINAGENT_FMP_API_KEY not set — falling back to yfinance. "
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
                env_var = f"FINAGENT_{key_field.upper()}"
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


def get_settings(**overrides: Any) -> FinAgentSettings:
    """Get settings. Pass overrides for testing."""
    return FinAgentSettings(**overrides)


def is_field_from_environ(field: str) -> bool:
    """True if FINAGENT_<FIELD> is set in the process environment.

    Lives in config.py so the os.environ peek does not leak into route
    code (audit red-line: only config.py + secret_store.py may touch
    os.environ). Note this does NOT distinguish a real env var from a
    value loaded out of .env — once pydantic-settings reads .env it
    populates pydantic state but does NOT set os.environ. So this
    function only fires for true OS-level env vars; .env-only values
    fall back to the "value present but no os env" inference path.
    """
    import os

    return bool(os.environ.get(f"FINAGENT_{field.upper()}"))
