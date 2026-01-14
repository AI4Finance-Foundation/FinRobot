"""
Tests for the configuration module.
"""
import sys
import os

# Add parent directory for direct module imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch

from config import (
    ProviderConfig,
    DataSourceConfig,
    get_config,
    set_config,
    reset_config,
)


class TestProviderConfig:
    """Tests for ProviderConfig dataclass."""

    def test_default_config(self):
        config = ProviderConfig()
        assert config.api_key is None
        assert config.enabled is True
        assert config.timeout == 30
        assert config.max_retries == 3
        assert config.is_configured is False

    def test_configured_with_api_key(self):
        config = ProviderConfig(api_key="test-key")
        assert config.is_configured is True

    def test_empty_api_key_not_configured(self):
        config = ProviderConfig(api_key="")
        assert config.is_configured is False

    def test_extra_settings(self):
        config = ProviderConfig(
            api_key="key",
            extra={"rate_limit": 100}
        )
        assert config.extra["rate_limit"] == 100


class TestDataSourceConfig:
    """Tests for DataSourceConfig dataclass."""

    def test_default_config(self):
        config = DataSourceConfig()
        assert config.finnhub.api_key is None
        assert config.fmp.api_key is None
        assert config.yahoo.is_configured is True  # Yahoo doesn't need key

    def test_from_environment(self):
        with patch.dict(os.environ, {
            "FINNHUB_API_KEY": "finnhub-key",
            "FMP_API_KEY": "fmp-key",
        }):
            config = DataSourceConfig.from_environment()

            assert config.finnhub.api_key == "finnhub-key"
            assert config.finnhub.is_configured is True
            assert config.fmp.api_key == "fmp-key"
            assert config.fmp.is_configured is True

    def test_from_environment_missing_keys(self):
        with patch.dict(os.environ, {}, clear=True):
            # Ensure keys are not set
            for key in ["FINNHUB_API_KEY", "FMP_API_KEY", "SEC_API_KEY"]:
                os.environ.pop(key, None)

            config = DataSourceConfig.from_environment()

            assert config.finnhub.is_configured is False
            assert config.fmp.is_configured is False

    def test_get_provider_config(self):
        config = DataSourceConfig()
        config.finnhub = ProviderConfig(api_key="test")

        provider_config = config.get_provider_config("finnhub")
        assert provider_config.api_key == "test"

    def test_get_provider_config_unknown(self):
        config = DataSourceConfig()
        result = config.get_provider_config("unknown")
        assert result is None


class TestGlobalConfig:
    """Tests for global configuration functions."""

    def test_get_config_creates_default(self):
        reset_config()
        config = get_config()
        assert config is not None
        assert isinstance(config, DataSourceConfig)

    def test_get_config_returns_same_instance(self):
        reset_config()
        config1 = get_config()
        config2 = get_config()
        assert config1 is config2

    def test_set_config_overrides(self):
        custom_config = DataSourceConfig()
        custom_config.finnhub = ProviderConfig(api_key="custom-key")

        set_config(custom_config)

        retrieved = get_config()
        assert retrieved.finnhub.api_key == "custom-key"

    def test_reset_config(self):
        reset_config()
        config1 = get_config()

        reset_config()
        config2 = get_config()

        # Should be different instances after reset
        assert config1 is not config2
