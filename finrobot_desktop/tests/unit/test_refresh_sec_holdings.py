from __future__ import annotations

import sys
import types
from datetime import date
from typing import Any

import pandas as pd
import pytest

from scripts.refresh_sec_holdings import _refresh_quarter

# This fixture mirrors the REAL edgartools 5.31.5 ThirteenF.holdings schema:
#   id_cols  = ['Issuer', 'Class', 'Cusip', 'Ticker']
#   sum_cols = ['SharesPrnAmount', 'Value', 'SoleVoting', 'SharedVoting', 'NonVoting']
# (confirmed via inspect.getsource(edgar.thirteenf.ThirteenF.holdings)).
# edgartools' Value column is ALREADY whole US dollars for every filing era.
EDGARTOOLS_VERSION_EXPECTATION = "5.31.x"

# A $250M position: 1,000,000 shares, Value reported in whole dollars.
_FIXTURE_VALUE_WHOLE_DOLLARS = 250_000_000
_FIXTURE_SHARES = 1_000_000


def _real_schema_holdings() -> pd.DataFrame:
    """A holdings DataFrame using edgartools 5.31.5 PascalCase columns."""
    return pd.DataFrame(
        [
            {
                "Issuer": "APPLE INC",
                "Class": "COM",
                "Cusip": "037833100",
                "Ticker": "AAPL",
                "SharesPrnAmount": _FIXTURE_SHARES,
                "Value": _FIXTURE_VALUE_WHOLE_DOLLARS,
                "SoleVoting": _FIXTURE_SHARES,
                "SharedVoting": 0,
                "NonVoting": 0,
                "Type": "Shares",
                "PutCall": "",
            }
        ]
    )


def _drifted_schema_holdings() -> pd.DataFrame:
    """A holdings DataFrame whose columns were renamed outright (not just
    recased) — the schema gate must skip it, not silently parse garbage."""
    return pd.DataFrame([{"issuerName": "APPLE INC", "shares": 1}])


class _FakeThirteenF:
    def __init__(self, df: pd.DataFrame) -> None:
        self.holdings = df


class _FakeFiling:
    period_of_report = date(2026, 3, 31)
    filing_date = date(2026, 5, 15)
    company = "Example Manager"
    cik = "0000000000"

    def __init__(self, accession_no: str, df: pd.DataFrame) -> None:
        self.accession_no = accession_no
        self._df = df

    def obj(self) -> _FakeThirteenF:
        return _FakeThirteenF(self._df)


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    filings: list[_FakeFiling],
    captured_rows: list[dict[str, Any]],
) -> list[tuple[Any, int]]:
    """Install fake edgar + cache modules. Returns the list that captures
    ``mark_period_complete`` calls so a test can assert completion behaviour."""
    fake_edgar = types.ModuleType("edgar")
    fake_edgar.get_filings = lambda form: list(filings)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "edgar", fake_edgar)

    async def _capture_bulk_upsert(rows: list[dict[str, Any]]) -> int:
        rows = list(rows)
        captured_rows.extend(rows)
        return len(rows)

    async def _fake_cache_status() -> dict[str, Any]:
        return {
            "populated": bool(captured_rows),
            "row_count": len(captured_rows),
            "latest_period_end": None,
            "distinct_tickers": 0,
        }

    marked: list[tuple[Any, int]] = []

    async def _fake_mark_complete(period_end: Any, filings_processed: int) -> None:
        marked.append((period_end, filings_processed))

    fake_cache = types.ModuleType("finrobot.engine.data.sec_holdings_cache")
    fake_cache.bulk_upsert_holdings = _capture_bulk_upsert  # type: ignore[attr-defined]
    fake_cache.cache_status = _fake_cache_status  # type: ignore[attr-defined]
    fake_cache.mark_period_complete = _fake_mark_complete  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "finrobot.engine.data.sec_holdings_cache", fake_cache)
    return marked


@pytest.mark.asyncio
async def test_refresh_quarter_parses_real_edgartools_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard for BUG-075 + BUG-086.

    The DataFrame uses real edgartools 5.31.5 PascalCase columns. Before the
    fix, the schema gate looked for raw-XML lowercase names → every filing was
    skipped as 'unexpected schema' → cache stayed empty. After the fix we
    rename(columns=str.lower) on ingest, so rows are parsed.
    """
    captured: list[dict[str, Any]] = []
    marked = _install_fakes(
        monkeypatch,
        [_FakeFiling("a1", _real_schema_holdings())],
        captured,
    )

    summary = await _refresh_quarter(date(2026, 3, 31))

    # BUG-075: rows are now actually parsed, not all dropped.
    assert summary["filings_skipped_schema"] == 0
    assert summary["filings_processed"] == 1
    assert summary["rows_inserted"] == 1
    assert len(captured) == 1

    row = captured[0]
    assert row["cusip"] == "037833100"
    assert row["name_of_issuer"] == "APPLE INC"
    assert row["title_of_class"] == "COM"
    assert row["shares"] == _FIXTURE_SHARES

    # BUG-086: edgartools' Value is already whole dollars — must NOT be ×1000.
    # A fixtured 250_000_000 stays 250_000_000, not 250_000_000_000.
    assert row["value_usd"] == float(_FIXTURE_VALUE_WHOLE_DOLLARS)
    assert row["value_usd"] != float(_FIXTURE_VALUE_WHOLE_DOLLARS) * 1000.0

    # A full (uncapped) run reached the end of the iterator → mark the quarter
    # complete so the freshness guard won't later mistake a partial cache for a
    # finished one (the missing-BlackRock root cause).
    assert summary["complete"] is True
    assert marked == [(date(2026, 3, 31), 1)]


@pytest.mark.asyncio
async def test_capped_run_does_not_mark_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    """A --max-filings-capped run is deliberately partial; it must NOT set the
    completion marker, or the guard would freeze the capped slice as 'done'."""
    captured: list[dict[str, Any]] = []
    marked = _install_fakes(
        monkeypatch,
        [_FakeFiling("a1", _real_schema_holdings())],
        captured,
    )

    summary = await _refresh_quarter(date(2026, 3, 31), max_filings=1)

    assert summary["complete"] is False
    assert marked == []


def _holdings_with_missing_value_and_shares() -> pd.DataFrame:
    """One complete row + two degenerate rows: a NaN Value and a footnote-only
    SharesPrnAmount. The schema columns are all present (so the filing-level
    gate passes); only the bad CELLS make these rows degenerate."""
    return pd.DataFrame(
        [
            {
                "Issuer": "APPLE INC",
                "Class": "COM",
                "Cusip": "037833100",
                "Ticker": "AAPL",
                "SharesPrnAmount": _FIXTURE_SHARES,
                "Value": _FIXTURE_VALUE_WHOLE_DOLLARS,
            },
            {
                # Value is NaN (parse gap) — drop, never store a $0 holding.
                "Issuer": "GHOST CORP",
                "Class": "COM",
                "Cusip": "111111111",
                "Ticker": "GHST",
                "SharesPrnAmount": 5000,
                "Value": float("nan"),
            },
            {
                # SharesPrnAmount is a footnote marker — drop, never 0 shares.
                "Issuer": "PHANTOM CO",
                "Class": "COM",
                "Cusip": "222222222",
                "Ticker": "PHTM",
                "SharesPrnAmount": "[F1]",
                "Value": 7_000_000,
            },
        ]
    )


@pytest.mark.asyncio
async def test_refresh_quarter_drops_rows_missing_shares_or_value(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """None ≠ 0: a 13F InfoTable row whose shares or value won't parse is a
    parse gap, not a real 0-share / $0 position. It must be DROPPED — coercing
    missing→0 would fabricate phantom $0 holders. Only the complete row stores."""
    captured: list[dict[str, Any]] = []
    _install_fakes(
        monkeypatch,
        [_FakeFiling("a1", _holdings_with_missing_value_and_shares())],
        captured,
    )

    caplog.set_level("WARNING", logger="refresh_sec_holdings")
    summary = await _refresh_quarter(date(2026, 3, 31))

    # Filing is processed (schema fine); 2 of its 3 rows are dropped as degenerate.
    assert summary["filings_skipped_schema"] == 0
    assert summary["filings_processed"] == 1
    assert summary["rows_inserted"] == 1
    assert len(captured) == 1
    assert captured[0]["cusip"] == "037833100"
    assert captured[0]["shares"] == _FIXTURE_SHARES
    assert captured[0]["value_usd"] == float(_FIXTURE_VALUE_WHOLE_DOLLARS)
    # No fabricated zeros leaked into the cache.
    assert all(r["shares"] != 0 and r["value_usd"] != 0 for r in captured)
    messages = [record.message for record in caplog.records]
    assert any("missing shares/value" in m for m in messages)


@pytest.mark.asyncio
async def test_refresh_quarter_skips_genuinely_drifted_schema(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A column rename that survives lowercasing (real drift) still skips."""
    captured: list[dict[str, Any]] = []
    _install_fakes(
        monkeypatch,
        [
            _FakeFiling("a1", _drifted_schema_holdings()),
            _FakeFiling("a2", _drifted_schema_holdings()),
        ],
        captured,
    )

    caplog.set_level("WARNING", logger="refresh_sec_holdings")
    summary = await _refresh_quarter(date(2026, 3, 31))

    assert summary["filings_skipped_schema"] == 2
    assert summary["rows_inserted"] == 0
    assert not captured
    messages = [record.message for record in caplog.records]
    assert any(
        "skipped 2 13F filings with unexpected holdings schema" in message for message in messages
    )
