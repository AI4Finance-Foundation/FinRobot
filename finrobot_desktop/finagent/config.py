import os

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

    # Infrastructure
    cache_db_path: str = "finagent_cache.db"
    log_level: str = "INFO"

    model_config = {"env_prefix": "FINAGENT_", "env_file": ".env"}

    def apply_api_keys(self) -> None:
        """Sync configured keys to env vars that pydantic-ai expects.
        Only sets env var if the value is non-empty AND the env var is not already set
        (explicit env vars always win over .env file values)."""
        key_map = {
            "anthropic_api_key": "ANTHROPIC_API_KEY",
            "deepseek_api_key": "DEEPSEEK_API_KEY",
            "openai_api_key": "OPENAI_API_KEY",
        }
        for attr, env_var in key_map.items():
            val = getattr(self, attr)
            if val and not os.environ.get(env_var):
                os.environ[env_var] = val


def get_settings(**overrides) -> FinAgentSettings:
    """Get settings. Pass overrides for testing."""
    return FinAgentSettings(**overrides)
