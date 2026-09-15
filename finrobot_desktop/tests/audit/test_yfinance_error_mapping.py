"""Audit: lock _YFINANCE_SERVICE_DOWN_KEYWORDS contents.

Removing any keyword from the set changes how invalid-ticker vs service-down
errors are classified, which propagates to 422 vs 502 HTTP responses, which
drives TickerNotFoundView vs workspace-shell degradation in the UI. This audit forces a
reviewer to explicitly acknowledge that classification change.
"""

from __future__ import annotations

import pytest
from yfinance.exceptions import YFException

from finrobot.engine.services.market_data import (
    _YFINANCE_SERVICE_DOWN_KEYWORDS,
    _is_yfinance_service_down,
)


def test_keyword_set_locked():
    """Adding keywords is fine — removing requires explicit reviewer approval.

    If this fails after you intentionally trimmed the list, update the
    expected set below and document the rationale in the commit message.
    """
    expected = frozenset(
        {
            "429",
            "rate limit",
            "connection",
            "timeout",
            "http error 5",
            "too many requests",
        }
    )
    assert frozenset(_YFINANCE_SERVICE_DOWN_KEYWORDS) >= expected, (
        f"Service-down keyword set shrank. Expected superset: {expected}. "
        f"Actual: {set(_YFINANCE_SERVICE_DOWN_KEYWORDS)}. "
        "Removing a keyword reclassifies that error from ProviderError (502) to "
        "ValueError (422), changing UI behavior. Confirm intentional in PR."
    )


@pytest.mark.parametrize(
    "message",
    [
        "HTTP Error 429: Too Many Requests",
        "rate limit exceeded",
        "Connection reset",
        "Read timeout",
        "HTTP Error 500: Internal Server Error",
        "Too Many Requests",
    ],
)
def test_each_keyword_classifies_as_service_down(message: str):
    """Every keyword in the list must trigger _is_yfinance_service_down=True."""
    exc = YFException(message)
    assert _is_yfinance_service_down(exc), (
        f"Expected '{message}' to classify as service-down. "
        "Either the keyword list lost coverage or _is_yfinance_service_down has a bug."
    )


@pytest.mark.parametrize(
    "message",
    [
        "Symbol may be delisted",
        "No data found for symbol",
        "",
        "Some unrelated error",
    ],
)
def test_non_matching_messages_classify_as_invalid_ticker(message: str):
    """Messages outside the keyword list must NOT classify as service-down."""
    exc = YFException(message)
    assert not _is_yfinance_service_down(exc), (
        f"Expected '{message}' NOT to classify as service-down. "
        "Either the keyword list over-matches or _is_yfinance_service_down has a bug."
    )
