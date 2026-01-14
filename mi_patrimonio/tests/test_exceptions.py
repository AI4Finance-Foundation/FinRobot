"""
Unit tests for the exceptions module.

Tests cover all custom exception classes and their behavior.
"""
import sys
import os

# Add mi_patrimonio to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from core.exceptions import (
    FinRobotError,
    DataFetchError,
    ValidationError,
    ConfigurationError,
    PortfolioError,
    PriceServiceError,
)


class TestFinRobotError:
    """Tests for the base FinRobotError class."""

    def test_create_with_message_only(self):
        """Test creating error with just a message."""
        error = FinRobotError("Something went wrong")

        assert str(error) == "[FINROBOT_ERROR] Something went wrong"
        assert error.message == "Something went wrong"
        assert error.code == "FINROBOT_ERROR"
        assert error.details == {}

    def test_create_with_code(self):
        """Test creating error with custom code."""
        error = FinRobotError("Error message", code="CUSTOM_CODE")

        assert error.code == "CUSTOM_CODE"
        assert "[CUSTOM_CODE]" in str(error)

    def test_create_with_details(self):
        """Test creating error with details dict."""
        error = FinRobotError(
            "Error message",
            details={"ticker": "AAPL", "retry_count": 3}
        )

        assert error.details["ticker"] == "AAPL"
        assert error.details["retry_count"] == 3
        assert "AAPL" in str(error)

    def test_to_dict(self):
        """Test conversion to dictionary."""
        error = FinRobotError(
            "Test error",
            code="TEST_CODE",
            details={"key": "value"}
        )

        result = error.to_dict()

        assert result["error"] == "TEST_CODE"
        assert result["message"] == "Test error"
        assert result["details"]["key"] == "value"

    def test_inheritance_from_exception(self):
        """Test that FinRobotError inherits from Exception."""
        error = FinRobotError("Test")

        assert isinstance(error, Exception)

    def test_can_be_raised_and_caught(self):
        """Test that error can be raised and caught."""
        with pytest.raises(FinRobotError) as exc_info:
            raise FinRobotError("Test error")

        assert exc_info.value.message == "Test error"


class TestDataFetchError:
    """Tests for DataFetchError."""

    def test_create_with_source(self):
        """Test creating error with source parameter."""
        error = DataFetchError("Timeout", source="yahoo_finance")

        assert error.source == "yahoo_finance"
        assert error.code == "DATA_FETCH_ERROR"
        assert error.details["source"] == "yahoo_finance"

    def test_without_source(self):
        """Test creating error without source."""
        error = DataFetchError("Connection refused")

        assert error.source is None
        assert error.code == "DATA_FETCH_ERROR"

    def test_with_additional_details(self):
        """Test creating error with additional details."""
        error = DataFetchError(
            "Rate limited",
            source="api",
            details={"retry_after": 60}
        )

        assert error.details["source"] == "api"
        assert error.details["retry_after"] == 60

    def test_inherits_from_finrobot_error(self):
        """Test inheritance hierarchy."""
        error = DataFetchError("Test")

        assert isinstance(error, FinRobotError)
        assert isinstance(error, Exception)


class TestValidationError:
    """Tests for ValidationError."""

    def test_create_with_field_and_value(self):
        """Test creating error with field and value."""
        error = ValidationError(
            "Invalid ticker format",
            field="ticker",
            value="AAPL!!"
        )

        assert error.field == "ticker"
        assert error.value == "AAPL!!"
        assert error.code == "VALIDATION_ERROR"

    def test_without_field(self):
        """Test creating error without field info."""
        error = ValidationError("Invalid input")

        assert error.field is None
        assert error.value is None

    def test_to_dict_includes_field_info(self):
        """Test that to_dict includes validation details."""
        error = ValidationError("Invalid", field="price", value=-100)
        result = error.to_dict()

        assert result["details"]["field"] == "price"
        assert result["details"]["value"] == -100


class TestConfigurationError:
    """Tests for ConfigurationError."""

    def test_create_with_config_key(self):
        """Test creating error with config key."""
        error = ConfigurationError(
            "Missing API key",
            config_key="OPENAI_API_KEY"
        )

        assert error.config_key == "OPENAI_API_KEY"
        assert error.code == "CONFIGURATION_ERROR"

    def test_without_config_key(self):
        """Test creating error without config key."""
        error = ConfigurationError("Invalid configuration file")

        assert error.config_key is None


class TestPortfolioError:
    """Tests for PortfolioError."""

    def test_create_with_portfolio_id(self):
        """Test creating error with portfolio ID."""
        error = PortfolioError(
            "Portfolio not found",
            portfolio_id="carrillo_sanchez"
        )

        assert error.portfolio_id == "carrillo_sanchez"
        assert error.code == "PORTFOLIO_ERROR"

    def test_without_portfolio_id(self):
        """Test creating error without portfolio ID."""
        error = PortfolioError("Invalid allocation")

        assert error.portfolio_id is None


class TestPriceServiceError:
    """Tests for PriceServiceError."""

    def test_create_with_ticker(self):
        """Test creating error with ticker."""
        error = PriceServiceError(
            "Price data stale",
            ticker="AAPL"
        )

        assert error.ticker == "AAPL"
        assert error.code == "PRICE_SERVICE_ERROR"

    def test_with_additional_details(self):
        """Test creating error with additional details."""
        error = PriceServiceError(
            "Stale data",
            ticker="MSFT",
            details={"last_update": "2024-01-01", "age_hours": 48}
        )

        assert error.details["ticker"] == "MSFT"
        assert error.details["last_update"] == "2024-01-01"


class TestExceptionHierarchy:
    """Tests for the exception hierarchy behavior."""

    def test_catch_all_with_base_class(self):
        """Test catching all custom errors with base class."""
        errors = [
            DataFetchError("test"),
            ValidationError("test"),
            ConfigurationError("test"),
            PortfolioError("test"),
            PriceServiceError("test"),
        ]

        for error in errors:
            with pytest.raises(FinRobotError):
                raise error

    def test_specific_catch(self):
        """Test catching specific error types."""
        with pytest.raises(DataFetchError):
            raise DataFetchError("API timeout")

        # Should not catch wrong type
        with pytest.raises(DataFetchError):
            try:
                raise ValidationError("Bad input")
            except DataFetchError:
                pytest.fail("Should not catch ValidationError as DataFetchError")
            except ValidationError:
                raise DataFetchError("Re-raised as correct type")
