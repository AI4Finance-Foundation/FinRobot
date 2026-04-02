"""Tests for finagent.engine.compute.clean — financial data cleaning utilities."""

from __future__ import annotations

import pytest

from finagent.engine.compute.clean import (
    FIELD_ALIASES,
    clean_financial_number,
    normalize_field_names,
)


class TestCleanFinancialNumber:
    def test_plain_integer(self):
        assert clean_financial_number(1234) == 1234.0

    def test_plain_float(self):
        assert clean_financial_number(1234.56) == 1234.56

    def test_string_integer(self):
        assert clean_financial_number("1234") == 1234.0

    def test_commas(self):
        assert clean_financial_number("1,234,567") == 1_234_567.0

    def test_commas_with_decimals(self):
        assert clean_financial_number("1,234.56") == 1234.56

    def test_parentheses_negative(self):
        assert clean_financial_number("(1,234)") == -1234.0

    def test_parentheses_negative_with_decimals(self):
        assert clean_financial_number("(1,234.56)") == -1234.56

    def test_dollar_sign(self):
        assert clean_financial_number("$1,234") == 1234.0

    def test_dollar_sign_negative(self):
        assert clean_financial_number("$(1,234.56)") == -1234.56

    def test_percentage(self):
        assert clean_financial_number("12.5%") == 0.125

    def test_percentage_negative(self):
        assert clean_financial_number("-3.2%") == -0.032

    def test_none_returns_none(self):
        assert clean_financial_number(None) is None

    def test_empty_string_returns_none(self):
        assert clean_financial_number("") is None

    def test_na_returns_none(self):
        assert clean_financial_number("N/A") is None

    def test_na_lowercase(self):
        assert clean_financial_number("n/a") is None

    def test_dash_returns_none(self):
        assert clean_financial_number("-") is None

    def test_zero(self):
        assert clean_financial_number(0) == 0.0

    def test_negative_number(self):
        assert clean_financial_number(-500.25) == -500.25

    def test_string_negative(self):
        assert clean_financial_number("-500.25") == -500.25

    def test_whitespace_stripped(self):
        assert clean_financial_number("  1,234  ") == 1234.0


class TestNormalizeFieldNames:
    def test_maps_camel_case_to_canonical(self):
        data = {"costOfRevenue": 100, "sellingGeneralAndAdministrative": 50}
        result = normalize_field_names(data)
        assert result["cost_of_revenue"] == 100
        assert result["sga"] == 50

    def test_first_match_wins(self):
        data = {"costOfRevenue": 100, "costOfGoodsSold": 200}
        result = normalize_field_names(data)
        assert result["cost_of_revenue"] == 100

    def test_passthrough_unknown_keys(self):
        data = {"revenue": 500, "unknown_field": 42}
        result = normalize_field_names(data)
        assert result["revenue"] == 500
        assert result["unknown_field"] == 42

    def test_empty_dict(self):
        assert normalize_field_names({}) == {}
