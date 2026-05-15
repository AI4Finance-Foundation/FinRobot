"""Tests for NormalizedFinancialKeys and canonical key definitions."""

from finagent.engine.data.keys import (
    NormalizedFinancialKeys,
    REQUIRED_KEYS,
    OPTIONAL_KEYS,
    ALL_KEYS,
)


def test_required_keys_defined():
    """Verify all required keys are in REQUIRED_KEYS."""
    assert "revenue" in REQUIRED_KEYS
    assert "ebitda" in REQUIRED_KEYS
    assert "net_income" in REQUIRED_KEYS
    assert "market_cap" in REQUIRED_KEYS
    assert "shares_outstanding" in REQUIRED_KEYS
    assert "current_price" in REQUIRED_KEYS
    assert "gross_margin" in REQUIRED_KEYS
    assert "operating_margin" in REQUIRED_KEYS


def test_optional_keys_defined():
    """Verify all optional keys are in OPTIONAL_KEYS."""
    assert "total_debt" in OPTIONAL_KEYS
    assert "total_cash" in OPTIONAL_KEYS
    assert "pe_ratio" in OPTIONAL_KEYS
    assert "depreciation_amortization" in OPTIONAL_KEYS
    assert "rd_expense" in OPTIONAL_KEYS
    assert "sga_expense" in OPTIONAL_KEYS
    assert "interest_expense" in OPTIONAL_KEYS


def test_all_keys_union():
    """Verify ALL_KEYS is the union of REQUIRED and OPTIONAL."""
    assert ALL_KEYS == REQUIRED_KEYS | OPTIONAL_KEYS
    assert len(ALL_KEYS) == len(REQUIRED_KEYS) + len(OPTIONAL_KEYS)


def test_no_overlap_between_required_and_optional():
    """Verify REQUIRED_KEYS and OPTIONAL_KEYS have no overlap."""
    assert REQUIRED_KEYS.isdisjoint(OPTIONAL_KEYS)


def test_typed_dict_accepts_valid_full_data():
    """Verify TypedDict accepts a fully populated data dict."""
    data: NormalizedFinancialKeys = {
        "revenue": 1e9,
        "ebitda": 2e8,
        "net_income": 1e8,
        "market_cap": 5e9,
        "shares_outstanding": 1e8,
        "current_price": 50.0,
        "gross_margin": 0.4,
        "operating_margin": 0.15,
        "total_debt": 1e8,
        "total_cash": 5e7,
        "pe_ratio": 15.0,
        "depreciation_amortization": 2e7,
        "rd_expense": 1e8,
        "sga_expense": 5e7,
        "interest_expense": 1e7,
    }
    assert data["revenue"] == 1e9
    assert data["market_cap"] == 5e9
    assert data["total_debt"] == 1e8


def test_typed_dict_accepts_required_only():
    """Verify TypedDict accepts dict with only required keys."""
    data: NormalizedFinancialKeys = {
        "revenue": 1e9,
        "ebitda": 2e8,
        "net_income": 1e8,
        "market_cap": 5e9,
        "shares_outstanding": 1e8,
        "current_price": 50.0,
        "gross_margin": 0.4,
        "operating_margin": 0.15,
    }
    assert data["revenue"] == 1e9
    assert len(data) == 8


def test_keyset_immutability():
    """Verify key sets are frozen and immutable."""
    assert isinstance(REQUIRED_KEYS, frozenset)
    assert isinstance(OPTIONAL_KEYS, frozenset)
    assert isinstance(ALL_KEYS, frozenset)
