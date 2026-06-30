from __future__ import annotations

import scripts.verify_report_field_basket as verify


def test_stale_live_anchor_abstains_instead_of_failing() -> None:
    row = verify._compare(
        "TSLA",
        "a",
        "current_price",
        {"value": 381.61, "caliber": "live quote (USD)", "as_of": "2000-01-01T00:00:00Z"},
        416.35,
    )

    assert row.consistent is None
    assert row.needs_human is False
    assert row.note is not None and "static live anchor" in row.note


def test_sec_ttm_anchor_keeps_fundamentals_same_period() -> None:
    anchor = verify._sec_ttm_anchor(
        {
            "ttm_net_income": {
                "concept": "us-gaap:NetIncomeLoss",
                "value": 159_613_000_000.0,
                "period_end": "2026-04-26",
                "warning": "calculated quarters",
            }
        },
        "net_income",
    )

    row = verify._compare("NVDA", "b", "net_income", anchor, 159_613_000_000.0)

    assert row.consistent is True
    assert row.note == "baseline=SEC XBRL TTM; our=TTM"


def test_annual_fundamental_fallback_over_band_is_human_review() -> None:
    row = verify._compare(
        "F",
        "b",
        "net_income",
        {
            "value": -8_162_000_000.0,
            "caliber": "annual FY (10-K, us-gaap:ProfitLoss)",
            "as_of": "2025-12-31",
        },
        -6_105_000_000.0,
        annual_fundamental_fallback=True,
    )

    assert row.consistent is None
    assert row.needs_human is True
    assert row.note is not None and "not an automatic bug" in row.note


def test_stale_share_count_anchor_over_band_is_human_review() -> None:
    row = verify._compare(
        "SAP",
        "b",
        "shares_outstanding",
        {
            "value": 1_228_504_232.0,
            "caliber": "cover-page shares outstanding",
            "as_of": "2025-01-01",
        },
        1_165_235_164.0,
    )

    assert row.consistent is None
    assert row.needs_human is True
    assert row.note is not None and "SEC share-count anchor" in row.note
