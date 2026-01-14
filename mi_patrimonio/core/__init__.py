"""
Core module for mi_patrimonio.

Contains domain models, exceptions, and utilities.
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
]
