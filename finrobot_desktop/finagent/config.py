from __future__ import annotations

from typing import Any

from pydantic_ai.models import Model
from pydantic_settings import BaseSettings

# Valid providers and the settings field holding their API key. A provider
# listed here but absent from _PROVIDER_KEY_FIELD needs no key (e.g. "test").
_VALID_PROVIDERS: frozenset[str] = frozenset({"deepseek", "anthropic", "openai", "test"})
_PROVIDER_KEY_FIELD: dict[str, str] = {
    "deepseek": "deepseek_api_key",
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
}


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
    sec_user_agent: str = "FinAgent admin@example.com"

    # Infrastructure
    cache_db_path: str = "finagent_cache.db"
    skills_dir: str = "skills"  # path to vendored skills (relative to project root or absolute)
    log_level: str = "INFO"

    model_config = {"env_prefix": "FINAGENT_", "env_file": ".env"}

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

        Checks the global ``model_name`` and every per-role override:
        - provider prefix must be one of the supported backends;
        - the provider's API key field must be populated (except "test").

        Called from ``cli._build_deps`` and ``sdk.FinAgent.__init__`` so
        users get an immediate error message instead of waiting 60 seconds
        for the first LLM call to fail. Raises ``ValueError`` on failure;
        CLI callers wrap that into ``click.ClickException``.
        """
        names_to_check: list[str] = [self.model_name]
        for role in ("data", "analysis", "modeling", "synthesis", "report"):
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
