"""
Configuration management for data providers.

This module provides centralized configuration for API keys and provider settings,
supporting both environment variables and explicit configuration.
"""
import logging
import os
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class ProviderConfig:
    """
    Configuration for a single data provider.

    Attributes:
        api_key: API key for the provider
        enabled: Whether the provider is enabled
        timeout: Request timeout in seconds
        max_retries: Maximum number of retry attempts
        extra: Additional provider-specific settings
    """
    api_key: Optional[str] = None
    enabled: bool = True
    timeout: int = 30
    max_retries: int = 3
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_configured(self) -> bool:
        """Check if provider has required configuration."""
        return self.api_key is not None and len(self.api_key) > 0


@dataclass
class DataSourceConfig:
    """
    Complete configuration for all data sources.

    Supports loading from environment variables with optional overrides.
    """
    finnhub: ProviderConfig = field(default_factory=ProviderConfig)
    fmp: ProviderConfig = field(default_factory=ProviderConfig)
    sec_api: ProviderConfig = field(default_factory=ProviderConfig)
    openbb: ProviderConfig = field(default_factory=ProviderConfig)
    yahoo: ProviderConfig = field(default_factory=lambda: ProviderConfig(
        api_key="none",  # Yahoo doesn't require API key
        enabled=True
    ))

    @classmethod
    def from_environment(cls) -> "DataSourceConfig":
        """
        Create configuration from environment variables.

        Environment variables:
            - FINNHUB_API_KEY
            - FMP_API_KEY
            - SEC_API_KEY
            - OPENBB_TOKEN (optional)

        Returns:
            DataSourceConfig with values from environment
        """
        config = cls()

        # FinnHub
        finnhub_key = os.environ.get("FINNHUB_API_KEY")
        if finnhub_key:
            config.finnhub = ProviderConfig(api_key=finnhub_key)
            logger.debug("FinnHub API key loaded from environment")

        # Financial Modeling Prep
        fmp_key = os.environ.get("FMP_API_KEY")
        if fmp_key:
            config.fmp = ProviderConfig(api_key=fmp_key)
            logger.debug("FMP API key loaded from environment")

        # SEC API
        sec_key = os.environ.get("SEC_API_KEY")
        if sec_key:
            config.sec_api = ProviderConfig(api_key=sec_key)
            logger.debug("SEC API key loaded from environment")

        # OpenBB (optional)
        openbb_token = os.environ.get("OPENBB_TOKEN")
        if openbb_token:
            config.openbb = ProviderConfig(api_key=openbb_token)
            logger.debug("OpenBB token loaded from environment")

        return config

    def get_provider_config(self, provider_name: str) -> Optional[ProviderConfig]:
        """
        Get configuration for a specific provider.

        Args:
            provider_name: Name of the provider (finnhub, fmp, sec_api, etc.)

        Returns:
            ProviderConfig or None if provider not found
        """
        return getattr(self, provider_name.lower().replace("-", "_"), None)


# Singleton configuration instance
_config: Optional[DataSourceConfig] = None


def get_config() -> DataSourceConfig:
    """
    Get the global configuration instance.

    Creates configuration from environment on first call.

    Returns:
        DataSourceConfig instance
    """
    global _config
    if _config is None:
        _config = DataSourceConfig.from_environment()
    return _config


def set_config(config: DataSourceConfig) -> None:
    """
    Set the global configuration instance.

    Use this to override environment-based configuration
    or for testing with custom configuration.

    Args:
        config: Configuration to use globally
    """
    global _config
    _config = config
    logger.info("Global configuration updated")


def reset_config() -> None:
    """
    Reset configuration to reload from environment.

    Useful for testing or when environment variables change.
    """
    global _config
    _config = None
    logger.debug("Configuration reset")
