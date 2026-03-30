import pytest

from finagent.engine.pipelines.validators import validate_has_fields, validate_is_non_empty


class TestValidateIsNonEmpty:
    def test_non_empty_string_passes(self):
        r = validate_is_non_empty("hello")
        assert r.passed is True
        assert r.error is None

    def test_empty_string_fails(self):
        r = validate_is_non_empty("")
        assert r.passed is False
        assert r.error is not None

    def test_whitespace_only_fails(self):
        r = validate_is_non_empty("   ")
        assert r.passed is False

    def test_newlines_only_fails(self):
        r = validate_is_non_empty("\n\n\t")
        assert r.passed is False

    def test_long_output_passes(self):
        r = validate_is_non_empty("Revenue: $100B\nEBITDA: $50B\n")
        assert r.passed is True


class TestValidateHasFields:
    def test_all_fields_present_passes(self):
        r = validate_has_fields("revenue is 100B, ebitda is 50B", ["revenue", "ebitda"])
        assert r.passed is True

    def test_missing_field_fails(self):
        r = validate_has_fields("revenue is 100B", ["revenue", "ebitda"])
        assert r.passed is False
        assert "ebitda" in r.error.lower()

    def test_all_missing_fails_with_all_in_error(self):
        r = validate_has_fields("nothing relevant here", ["revenue", "ebitda", "price_history"])
        assert r.passed is False
        assert "revenue" in r.error.lower()
        assert "ebitda" in r.error.lower()
        assert "price_history" in r.error.lower()

    def test_case_insensitive(self):
        r = validate_has_fields("REVENUE: $100B, EBITDA: $50B", ["revenue", "ebitda"])
        assert r.passed is True

    def test_underscore_matches_space(self):
        r = validate_has_fields("Price History: see chart below", ["price_history"])
        assert r.passed is True

    def test_underscore_matches_uppercase_spaced(self):
        r = validate_has_fields("PRICE HISTORY and NET INCOME shown", ["price_history", "net_income"])
        assert r.passed is True

    def test_empty_fields_list_passes(self):
        r = validate_has_fields("anything", [])
        assert r.passed is True
