from __future__ import annotations

from pydantic_ai.models import Model
from pydantic_settings import BaseSettings


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

    def create_model(self) -> Model:
        """Create a PydanticAI Model with API key passed directly.

        No os.environ pollution. The API key is baked into the provider instance.
        """
        name = self.model_name  # e.g. "deepseek:deepseek-chat"
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
            raise ValueError(f"Unknown provider '{provider}' in model_name '{name}'")


def get_settings(**overrides) -> FinAgentSettings:
    """Get settings. Pass overrides for testing."""
    return FinAgentSettings(**overrides)
