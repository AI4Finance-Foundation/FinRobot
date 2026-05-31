from __future__ import annotations

import sys
import types
from datetime import date
from typing import Any

import pytest

from scripts.refresh_sec_holdings import _refresh_quarter


class _FakeHoldings:
    columns = ["issuerName"]


class _FakeThirteenF:
    holdings = _FakeHoldings()


class _FakeFiling:
    period_of_report = date(2026, 3, 31)
    filing_date = date(2026, 5, 15)
    company = "Example Manager"
    cik = "0000000000"

    def __init__(self, accession_no: str) -> None:
        self.accession_no = accession_no

    def obj(self) -> _FakeThirteenF:
        return _FakeThirteenF()


@pytest.mark.asyncio
async def test_refresh_quarter_aggregates_schema_warnings(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_edgar = types.ModuleType("edgar")
    fake_edgar.get_filings = lambda form: [_FakeFiling("a1"), _FakeFiling("a2")]  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "edgar", fake_edgar)

    fake_cache = types.ModuleType("finrobot.engine.data.sec_holdings_cache")
    fake_cache.bulk_upsert_holdings = _unused_bulk_upsert  # type: ignore[attr-defined]
    fake_cache.cache_status = _fake_cache_status  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "finrobot.engine.data.sec_holdings_cache", fake_cache)

    caplog.set_level("WARNING", logger="refresh_sec_holdings")
    summary = await _refresh_quarter(date(2026, 3, 31))

    assert summary["filings_skipped_schema"] == 2
    messages = [record.message for record in caplog.records]
    assert not any("13F a1 has unexpected schema" in message for message in messages)
    assert any("skipped 2 13F filings with unexpected holdings schema" in message for message in messages)


async def _unused_bulk_upsert(_rows: list[dict[str, Any]]) -> int:
    raise AssertionError("schema-skipped filings must not upsert rows")


async def _fake_cache_status() -> dict[str, Any]:
    return {
        "populated": False,
        "row_count": 0,
        "latest_period_end": None,
        "distinct_tickers": 0,
    }
