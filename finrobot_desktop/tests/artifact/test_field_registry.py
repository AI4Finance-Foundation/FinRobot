"""Field caliber registry tests.

The registry is the backend SoT that replaces the frontend's path-substring unit
guessing. These tests pin the calibers and formatting against standard
equity-research conventions (the "external benchmark" here is domain practice:
EV/EBITDA is a multiple shown with x, book value per share is per-share currency,
WACC is a percent) and guard the specific bugs the old code shipped.
"""

from __future__ import annotations

import pytest

from finrobot.artifact.field_registry import (
    REGISTRY,
    FieldCaliber,
    format_caliber_value,
)

_CURRENCY_UNITS = {"currency_per_share", "currency_abs"}


class TestRegistryInvariants:
    def test_keys_match_their_entries(self) -> None:
        for key, caliber in REGISTRY.items():
            assert caliber.key == key

    def test_currency_source_present_iff_currency_unit(self) -> None:
        # The comparability gate relies on this: a currency unit without a
        # currency_source can't be checked for like-for-like; a non-currency
        # unit carrying a currency_source is a definition error.
        for caliber in REGISTRY.values():
            if caliber.unit in _CURRENCY_UNITS:
                assert caliber.currency_source is not None, caliber.key
            else:
                assert caliber.currency_source is None, caliber.key

    def test_decimals_non_negative(self) -> None:
        for caliber in REGISTRY.values():
            assert caliber.decimals >= 0, caliber.key


class TestBookValueRegression:
    """book_value_per_share撞过 the 'value' substring → rendered as $B. Pin it."""

    def test_unit_is_per_share_not_absolute(self) -> None:
        assert REGISTRY["book_value_per_share"].unit == "currency_per_share"

    def test_formats_as_per_share_dollars_not_billions(self) -> None:
        out = format_caliber_value(REGISTRY["book_value_per_share"], 12.5, currency="USD")
        assert out == "$12.50"
        assert "B" not in out


class TestMultiplesNotMoney:
    def test_ev_ebitda_is_multiple_with_x(self) -> None:
        cal = REGISTRY["ev_ebitda"]
        assert cal.unit == "multiple"
        out = format_caliber_value(cal, 12.5, currency="USD")
        assert out == "12.5x"
        assert "$" not in out

    def test_forward_pe_no_percent_scaling(self) -> None:
        # A 28x P/E must not be ×100'd into "2800%".
        out = format_caliber_value(REGISTRY["forward_pe"], 28.0)
        assert out == "28.0x"


class TestPercentFormatting:
    def test_wacc_decimal_to_percent(self) -> None:
        assert format_caliber_value(REGISTRY["wacc"], 0.082) == "8.2%"

    def test_irr_decimal_to_percent(self) -> None:
        assert format_caliber_value(REGISTRY["irr"], 0.235) == "23.5%"


class TestCurrencyNeverAssumesUSD:
    def test_quote_currency_respected(self) -> None:
        out = format_caliber_value(REGISTRY["target_price"], 180.0, currency="EUR")
        assert out == "€180.00"

    def test_unknown_currency_falls_back_to_code_prefix(self) -> None:
        out = format_caliber_value(REGISTRY["target_price"], 180.0, currency="XYZ")
        assert out == "XYZ 180.00"

    def test_no_currency_emits_no_symbol(self) -> None:
        # Never silently stamp "$" when the artifact didn't tell us the currency.
        out = format_caliber_value(REGISTRY["target_price"], 180.0, currency=None)
        assert out == "180.00"


class TestAbsoluteCurrencyMagnitude:
    def test_revenue_billions(self) -> None:
        assert format_caliber_value(REGISTRY["revenue"], 1.23e9, currency="USD") == "$1.2B"

    def test_negative_equity_value_sign(self) -> None:
        out = format_caliber_value(REGISTRY["equity_value"], -4.5e9, currency="USD")
        assert out == "-$4.5B"


class TestNoneHandling:
    @pytest.mark.parametrize("key", ["wacc", "target_price", "ev_ebitda", "revenue"])
    def test_none_renders_em_dash(self, key: str) -> None:
        assert format_caliber_value(REGISTRY[key], None) == "—"


class TestDirectionSemantics:
    def test_wacc_lower_better(self) -> None:
        assert REGISTRY["wacc"].direction_semantics == "lower_better"

    def test_net_income_sign_flip_sensitive(self) -> None:
        # EPS/net-income straddling zero must not be reported as a clean pct move.
        assert REGISTRY["net_income"].sign_flip_sensitive is True


def test_field_caliber_is_frozen_reference_data() -> None:
    # Sanity: building a caliber with an out-of-vocab unit is rejected by typing
    # at definition sites; here we just confirm the model validates a good one.
    cal = FieldCaliber(key="x", label_zh="x", label_en="x", unit="ratio")
    assert cal.currency_source is None
