"""
Core module for mi_patrimonio.

Contains domain models, exceptions, utilities, and dependency injection.
"""
from .exceptions import (
    FinRobotError,
    DataFetchError,
    ValidationError,
    ConfigurationError,
    PortfolioError,
    PriceServiceError,
)
from .logging import get_logger, configure_root_logger
from .container import (
    ServiceContainer,
    get_container,
    reset_container,
    get_data_provider,
    get_risk_analyzer,
    get_ai_advisor,
    get_finrobot_advisor,
)

__all__ = [
    # Exceptions
    "FinRobotError",
    "DataFetchError",
    "ValidationError",
    "ConfigurationError",
    "PortfolioError",
    "PriceServiceError",
    # Logging
    "get_logger",
    "configure_root_logger",
    # Dependency Injection
    "ServiceContainer",
    "get_container",
    "reset_container",
    "get_data_provider",
    "get_risk_analyzer",
    "get_ai_advisor",
    "get_finrobot_advisor",
]
