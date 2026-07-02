"""Helpers for user-facing warning text."""

from __future__ import annotations

import re

# Internal upstream endpoints / httpx "for url '...'" tails are audit detail, not
# analyst-facing copy. APIs that return warnings verbatim should pass through this
# sanitizer before serializing responses.
_URL_TAIL_RE = re.compile(r"\s*for url\s+['\"]?https?://[^'\"\s]+['\"]?", re.IGNORECASE)
_BARE_URL_RE = re.compile(r"https?://\S+")


def humanize_warnings(warnings: list[str]) -> list[str]:
    """Strip raw upstream URLs out of provider warnings while keeping the lead text."""
    cleaned: list[str] = []
    for warning in warnings:
        # httpx renders "<msg> for url '<url>'\nFor more information check: <mdn>".
        # Keep the useful first line and strip endpoint details from it.
        text = warning.split("\n", 1)[0]
        text = _URL_TAIL_RE.sub("", text)
        text = _BARE_URL_RE.sub("", text)
        text = re.sub(r"\s{2,}", " ", text).strip()
        if text:
            cleaned.append(text)
    return cleaned
