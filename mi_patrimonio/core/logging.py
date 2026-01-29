"""
Logging configuration for mi_patrimonio.

Provides structured logging with consistent formatting across all modules.

Usage:
    from mi_patrimonio.core.logging import get_logger

    logger = get_logger(__name__)
    logger.info("Starting price fetch", extra={"ticker": "AAPL"})
    logger.error("Failed to fetch", extra={"error": str(e)})
"""
import logging
import sys
from typing import Optional


# Custom formatter with structured output
class StructuredFormatter(logging.Formatter):
    """Formatter that includes extra fields in log output."""

    def format(self, record: logging.LogRecord) -> str:
        # Add any extra fields to the message
        extra_fields = {
            k: v
            for k, v in record.__dict__.items()
            if k not in logging.LogRecord.__dict__
            and not k.startswith("_")
            and k not in ("name", "msg", "args", "created", "filename", "funcName",
                         "levelname", "levelno", "lineno", "module", "msecs",
                         "pathname", "process", "processName", "relativeCreated",
                         "stack_info", "exc_info", "exc_text", "thread", "threadName",
                         "message", "asctime")
        }

        base_message = super().format(record)

        if extra_fields:
            extra_str = " ".join(f"{k}={v}" for k, v in extra_fields.items())
            return f"{base_message} | {extra_str}"

        return base_message


def get_logger(name: str, level: Optional[int] = None) -> logging.Logger:
    """
    Get a configured logger for the given module name.

    Args:
        name: Usually __name__ of the calling module
        level: Optional logging level (defaults to INFO)

    Returns:
        Configured logger instance

    Example:
        logger = get_logger(__name__)
        logger.info("Processing started")
    """
    logger = logging.getLogger(name)

    # Only configure if not already configured
    if not logger.handlers:
        logger.setLevel(level or logging.INFO)

        # Console handler with structured formatting
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level or logging.INFO)

        formatter = StructuredFormatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)

        logger.addHandler(handler)

        # Prevent propagation to root logger
        logger.propagate = False

    return logger


def configure_root_logger(level: int = logging.INFO) -> None:
    """
    Configure the root logger for the application.

    Call this once at application startup.

    Args:
        level: Logging level for the root logger
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add new handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    formatter = StructuredFormatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

    root_logger.addHandler(handler)
