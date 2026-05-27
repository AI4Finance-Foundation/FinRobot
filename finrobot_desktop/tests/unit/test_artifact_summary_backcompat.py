"""Legacy ArtifactSummary JSON must deserialize cleanly after v5 ADR-0001.

ArtifactSummary added entry_price / target_price / target_date / signal in
v5. Existing artifacts on disk (written by older versions) lack these keys.
Pydantic must accept the legacy shape with defaults == None, so the JSON
file store keeps working without a migration script.
"""

from __future__ import annotations

import json

from finrobot.artifact.models import ArtifactSummary


def test_legacy_summary_missing_v5_fields_loads_with_none() -> None:
    legacy_json = {
        "id": "art_2025-01-01T00:00:00_AAPL_dcf",
        "ticker": "AAPL",
        "cross_tickers": [],
        "type": "dcf",
        "created_at": "2025-01-01T00:00:00Z",
        "headline": "DCF implied $185 / WACC 8.2%",
        "source": "cli",
        "archived": False,
    }
    s = ArtifactSummary.model_validate(legacy_json)
    assert s.entry_price is None
    assert s.target_price is None
    assert s.target_date is None
    assert s.signal is None


def test_v5_summary_roundtrips_with_new_fields() -> None:
    payload = {
        "id": "art_2026-05-21T00:00:00_NVDA_equity_research",
        "ticker": "NVDA",
        "cross_tickers": [],
        "type": "equity_research",
        "created_at": "2026-05-21T00:00:00Z",
        "headline": "BUY · target $920",
        "source": "stocks_page_button",
        "archived": False,
        "entry_price": 876.42,
        "target_price": 920.0,
        "target_date": "2027-05-21T00:00:00Z",
        "signal": "watching",
    }
    s = ArtifactSummary.model_validate(payload)
    assert s.entry_price == 876.42
    assert s.target_price == 920.0
    assert s.signal == "watching"

    # Round-trip via JSON — the on-disk path the store uses
    redumped = json.loads(s.model_dump_json())
    assert redumped["entry_price"] == 876.42
    assert redumped["signal"] == "watching"
    s2 = ArtifactSummary.model_validate(redumped)
    assert s2 == s


def test_extra_unknown_fields_are_ignored() -> None:
    # Forward compatibility: if v6 adds fields and we downgrade, summary still loads.
    payload = {
        "id": "art_foo",
        "ticker": "NVDA",
        "cross_tickers": [],
        "type": "dcf",
        "created_at": "2026-05-21T00:00:00Z",
        "headline": "x",
        "source": "cli",
        "archived": False,
        "future_field_v6": "ignored",
    }
    # BaseModel default behaviour: extra fields silently ignored.
    s = ArtifactSummary.model_validate(payload)
    assert s.id == "art_foo"
