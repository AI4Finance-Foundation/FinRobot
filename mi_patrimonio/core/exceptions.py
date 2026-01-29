"""
Custom exception hierarchy for mi_patrimonio.

All custom exceptions inherit from FinRobotError to enable
catching all application-specific errors with a single except clause.

Example:
    try:
        price = data_provider.get_quote("AAPL")
    except DataFetchError as e:
        logger.error(f"Failed to fetch price: {e}")
    except FinRobotError as e:
        logger.error(f"Application error: {e}")
"""
from typing import Optional


class FinRobotError(Exception):
    """
    Base exception for all FinRobot application errors.

    Attributes:
        message: Human-readable error description
        code: Machine-readable error code for programmatic handling
        details: Optional additional context about the error
    """

    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code or "FINROBOT_ERROR"
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"[{self.code}] {self.message} - {self.details}"
        return f"[{self.code}] {self.message}"

    def to_dict(self) -> dict:
        """Convert exception to dictionary for JSON responses."""
        return {
            "error": self.code,
            "message": self.message,
            "details": self.details,
        }


class DataFetchError(FinRobotError):
    """
    Raised when fetching data from an external source fails.

    Examples:
        - API request timeout
        - Invalid response format
        - Rate limiting
        - Network connectivity issues
    """

    def __init__(
        self,
        message: str,
        source: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        super().__init__(
            message=message,
            code="DATA_FETCH_ERROR",
            details={"source": source, **(details or {})},
        )
        self.source = source


class ValidationError(FinRobotError):
    """
    Raised when input validation fails.

    Examples:
        - Invalid ticker symbol format
        - Out-of-range numerical values
        - Missing required fields
    """

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        value: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        super().__init__(
            message=message,
            code="VALIDATION_ERROR",
            details={"field": field, "value": value, **(details or {})},
        )
        self.field = field
        self.value = value


class ConfigurationError(FinRobotError):
    """
    Raised when configuration is missing or invalid.

    Examples:
        - Missing API key
        - Invalid environment variable
        - Malformed configuration file
    """

    def __init__(
        self,
        message: str,
        config_key: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        super().__init__(
            message=message,
            code="CONFIGURATION_ERROR",
            details={"config_key": config_key, **(details or {})},
        )
        self.config_key = config_key


class PortfolioError(FinRobotError):
    """
    Raised for portfolio-specific errors.

    Examples:
        - Invalid portfolio ID
        - Position not found
        - Allocation validation failure
    """

    def __init__(
        self,
        message: str,
        portfolio_id: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        super().__init__(
            message=message,
            code="PORTFOLIO_ERROR",
            details={"portfolio_id": portfolio_id, **(details or {})},
        )
        self.portfolio_id = portfolio_id


class PriceServiceError(FinRobotError):
    """
    Raised for price service specific errors.

    Examples:
        - Price server unavailable
        - Invalid ticker response
        - Stale price data
    """

    def __init__(
        self,
        message: str,
        ticker: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        super().__init__(
            message=message,
            code="PRICE_SERVICE_ERROR",
            details={"ticker": ticker, **(details or {})},
        )
        self.ticker = ticker
