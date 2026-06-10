"""Tests for the ticker-symbol chokepoint (engine/data/ticker.py).

The share-class basket below is grounded in a live yfinance probe (2026-06-10):
the hyphen form (BRK-B / BF-B / BRK-A) returns prices while the dotted form
(BRK.B / BF.B / BRK.A) returns "no data / delisted"; foreign exchange suffixes —
including the single-letter RIO.L (London) and 7203.T (Tokyo) — resolve ONLY
dotted. validate_ticker canonicalizes the former and must never touch the latter.
"""

from __future__ import annotations

import pytest

from finrobot.engine.data.ticker import is_us_equity_ticker, validate_ticker


class TestValidateTickerBasics:
    def test_strips_and_uppercases(self):
        assert validate_ticker("  aapl ") == "AAPL"

    @pytest.mark.parametrize("bad", ["", "   ", "苹果", "AAPL;DROP", "$", "TOOLONGTICKER13"])
    def test_rejects_junk(self, bad):
        with pytest.raises(ValueError, match="Invalid ticker"):
            validate_ticker(bad)


class TestShareClassCanonicalization:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            # US class shares: yfinance needs the hyphen → canonicalize the dot.
            ("BRK.B", "BRK-B"),
            ("brk.b", "BRK-B"),  # case + class-share folded together
            (" BF.B ", "BF-B"),
            ("BRK.A", "BRK-A"),
            ("HEI.A", "HEI-A"),
            ("LEN.B", "LEN-B"),
            # Already-hyphen and plain US tickers are unchanged (idempotent).
            ("BRK-B", "BRK-B"),
            ("AAPL", "AAPL"),
            ("MSFT", "MSFT"),
        ],
    )
    def test_us_share_class_dot_folds_to_hyphen(self, raw, expected):
        assert validate_ticker(raw) == expected

    @pytest.mark.parametrize(
        "foreign",
        [
            "RIO.L",  # London — single-letter exchange suffix, MUST keep the dot
            "7203.T",  # Tokyo — single-letter exchange suffix, numeric root
            "600519.SS",  # Shanghai
            "0700.HK",  # Hong Kong
            "AIR.PA",  # Paris
            "BMW.DE",  # Frankfurt
        ],
    )
    def test_foreign_exchange_suffixes_are_untouched(self, foreign):
        # The probed trap: .L / .T are single-letter EXCHANGE codes, not class
        # letters — converting them to hyphen would break the (working) dotted form.
        assert validate_ticker(foreign) == foreign

    def test_canonicalization_is_idempotent(self):
        assert validate_ticker(validate_ticker("BRK.B")) == "BRK-B"

    def test_unprobed_class_letter_left_alone(self):
        # Conservative: only {A, B} are probed/allow-listed. A hypothetical .C is
        # left dotted rather than risk an unverified conversion (no regression —
        # same as before this fix).
        assert validate_ticker("FOO.C") == "FOO.C"

    def test_canonical_form_reads_as_us_equity(self):
        # The folded form has no foreign suffix, so the backtest US-equity gate
        # still admits it.
        assert is_us_equity_ticker(validate_ticker("BRK.B")) is True
