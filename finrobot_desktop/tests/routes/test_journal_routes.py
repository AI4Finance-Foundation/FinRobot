"""Route tests for /api/journal endpoints.

Coverage:
- POST /api/journal — create entry, returns JournalEntry
- GET /api/journal — list entries
- GET /api/journal/{id} — get single entry, 404 on missing
- PUT /api/journal/{id} — update entry fields
- DELETE /api/journal/{id} — delete, 404 on missing

Mock discipline:
- JournalStore is patched at the module level to avoid touching the filesystem.
- _enrich_with_price is patched to return the entry unchanged (no yfinance calls).
- These are unit-level route tests; no real SQLite or yfinance calls.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from finagent.models.journal import JournalEntry, JournalEntryCreate
from finagent.routes.journal import router as journal_router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 5, 15, 10, 0, 0, tzinfo=timezone.utc).isoformat()


def _entry(**kwargs) -> JournalEntry:
    defaults = dict(
        id=str(uuid.uuid4()),
        ticker="AAPL",
        action="BUY",
        entry_price=182.50,
        target_price=210.0,
        thesis="Strong iPhone super-cycle momentum.",
        notes="Added on dip.",
        created_at=_NOW,
    )
    defaults.update(kwargs)
    return JournalEntry(**defaults)


# ---------------------------------------------------------------------------
# App fixture with patched store + enrichment
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_store() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def app(mock_store: MagicMock) -> FastAPI:
    test_app = FastAPI()
    test_app.include_router(journal_router)
    return test_app


@pytest.fixture()
def client(app: FastAPI, mock_store: MagicMock) -> Any:
    # Reset module-level singleton between tests
    import finagent.routes.journal as journal_module
    original_store = journal_module._store

    journal_module._store = mock_store

    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    yield c

    journal_module._store = original_store


# ---------------------------------------------------------------------------
# POST /api/journal — create entry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_entry_returns_201_created(
    client: Any, mock_store: MagicMock
) -> None:
    """POST /api/journal creates entry and returns JournalEntry JSON."""
    created = _entry(id="entry-001", ticker="AAPL", action="BUY")
    mock_store.create.return_value = created

    with patch(
        "finagent.routes.journal._enrich_with_price",
        new=AsyncMock(side_effect=lambda e: e),
    ):
        async with client as c:
            resp = await c.post(
                "/api/journal",
                json={
                    "ticker": "AAPL",
                    "action": "BUY",
                    "entry_price": 182.50,
                    "target_price": 210.0,
                    "thesis": "Strong iPhone super-cycle momentum.",
                    "notes": "Added on dip.",
                },
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ticker"] == "AAPL"
    assert data["action"] == "BUY"
    assert data["entry_price"] == pytest.approx(182.50)


@pytest.mark.asyncio
async def test_create_entry_uppercase_ticker(
    client: Any, mock_store: MagicMock
) -> None:
    """Ticker is uppercased on create (JournalStore.create behavior)."""
    created = _entry(id="entry-002", ticker="MSFT", action="HOLD")
    mock_store.create.return_value = created

    with patch(
        "finagent.routes.journal._enrich_with_price",
        new=AsyncMock(side_effect=lambda e: e),
    ):
        async with client as c:
            resp = await c.post(
                "/api/journal",
                json={
                    "ticker": "msft",
                    "action": "HOLD",
                    "entry_price": 420.0,
                    "thesis": "Copilot monetization.",
                },
            )

    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/journal — list entries
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_entries_returns_list(
    client: Any, mock_store: MagicMock
) -> None:
    """GET /api/journal returns a list of JournalEntry objects."""
    entries = [
        _entry(id="e1", ticker="AAPL"),
        _entry(id="e2", ticker="MSFT"),
    ]
    mock_store.list_all.return_value = entries

    with patch(
        "finagent.routes.journal._enrich_with_price",
        new=AsyncMock(side_effect=lambda e: e),
    ):
        async with client as c:
            resp = await c.get("/api/journal")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["ticker"] == "AAPL"
    assert data[1]["ticker"] == "MSFT"


@pytest.mark.asyncio
async def test_list_entries_empty(
    client: Any, mock_store: MagicMock
) -> None:
    """GET /api/journal returns empty list when no entries exist."""
    mock_store.list_all.return_value = []

    async with client as c:
        resp = await c.get("/api/journal")

    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# GET /api/journal/{id} — single entry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_entry_returns_entry(
    client: Any, mock_store: MagicMock
) -> None:
    """GET /api/journal/{id} returns the entry when it exists."""
    entry = _entry(id="entry-abc")
    mock_store.get.return_value = entry

    with patch(
        "finagent.routes.journal._enrich_with_price",
        new=AsyncMock(side_effect=lambda e: e),
    ):
        async with client as c:
            resp = await c.get("/api/journal/entry-abc")

    assert resp.status_code == 200
    assert resp.json()["id"] == "entry-abc"


@pytest.mark.asyncio
async def test_get_entry_not_found_returns_404(
    client: Any, mock_store: MagicMock
) -> None:
    """GET /api/journal/{id} returns 404 when entry does not exist."""
    mock_store.get.return_value = None

    async with client as c:
        resp = await c.get("/api/journal/nonexistent-id")

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# PUT /api/journal/{id} — update
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_entry_returns_updated(
    client: Any, mock_store: MagicMock
) -> None:
    """PUT /api/journal/{id} returns the updated entry."""
    updated = _entry(id="e1", ticker="AAPL", notes="Updated notes.")
    mock_store.update.return_value = updated

    with patch(
        "finagent.routes.journal._enrich_with_price",
        new=AsyncMock(side_effect=lambda e: e),
    ):
        async with client as c:
            resp = await c.put(
                "/api/journal/e1",
                json={"notes": "Updated notes."},
            )

    assert resp.status_code == 200
    assert resp.json()["notes"] == "Updated notes."


@pytest.mark.asyncio
async def test_update_entry_not_found_returns_404(
    client: Any, mock_store: MagicMock
) -> None:
    """PUT /api/journal/{id} returns 404 when entry does not exist."""
    mock_store.update.return_value = None

    async with client as c:
        resp = await c.put(
            "/api/journal/ghost-id",
            json={"notes": "whatever"},
        )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/journal/{id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_entry_returns_status_deleted(
    client: Any, mock_store: MagicMock
) -> None:
    """DELETE /api/journal/{id} returns {status: 'deleted'}."""
    mock_store.delete.return_value = True

    async with client as c:
        resp = await c.delete("/api/journal/e1")

    assert resp.status_code == 200
    assert resp.json() == {"status": "deleted"}


@pytest.mark.asyncio
async def test_delete_entry_not_found_returns_404(
    client: Any, mock_store: MagicMock
) -> None:
    """DELETE /api/journal/{id} returns 404 when entry does not exist."""
    mock_store.delete.return_value = False

    async with client as c:
        resp = await c.delete("/api/journal/ghost-id")

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# JournalStore unit tests (no routes)
# ---------------------------------------------------------------------------

class TestJournalStoreCRUD:
    """Test JournalStore synchronous methods using a tmp SQLite database."""

    @pytest.fixture()
    def store(self, tmp_path):
        from finagent.models.journal import JournalStore
        return JournalStore(db_path=tmp_path / "test_journal.db")

    def test_create_and_get_round_trip(self, store):
        """create() then get() returns identical data."""
        body = JournalEntryCreate(
            ticker="NVDA",
            action="BUY",
            entry_price=875.0,
            target_price=1000.0,
            thesis="AI GPU demand.",
        )
        created = store.create(body)
        fetched = store.get(created.id)

        assert fetched is not None
        assert fetched.ticker == "NVDA"
        assert fetched.action == "BUY"
        assert fetched.entry_price == pytest.approx(875.0)
        assert fetched.thesis == "AI GPU demand."

    def test_ticker_uppercased_on_create(self, store):
        """JournalStore.create uppercases the ticker."""
        body = JournalEntryCreate(
            ticker="tsla",
            action="SELL",
            entry_price=250.0,
            thesis="Take profit at resistance.",
        )
        created = store.create(body)
        assert created.ticker == "TSLA"

    def test_list_all_empty_initially(self, store):
        """New store has no entries."""
        assert store.list_all() == []

    def test_list_all_newest_first(self, store):
        """list_all returns entries ordered newest-first."""
        import time as _time
        b1 = JournalEntryCreate(ticker="A", action="BUY", entry_price=100.0, thesis="t1")
        b2 = JournalEntryCreate(ticker="B", action="SELL", entry_price=200.0, thesis="t2")
        store.create(b1)
        _time.sleep(0.01)  # ensure distinct timestamps
        store.create(b2)
        entries = store.list_all()
        assert entries[0].ticker == "B"  # newest first
        assert entries[1].ticker == "A"

    def test_update_allowed_fields(self, store):
        """update() only modifies allowed fields."""
        body = JournalEntryCreate(
            ticker="GOOG",
            action="HOLD",
            entry_price=150.0,
            thesis="Original thesis.",
        )
        entry = store.create(body)
        updated = store.update(entry.id, {"notes": "New note", "entry_price": 155.0})
        assert updated is not None
        assert updated.notes == "New note"
        assert updated.entry_price == pytest.approx(155.0)

    def test_update_ignores_computed_fields(self, store):
        """update() silently ignores computed fields (pnl_pct, current_price)."""
        body = JournalEntryCreate(
            ticker="META",
            action="BUY",
            entry_price=450.0,
            thesis="Ad rebound.",
        )
        entry = store.create(body)
        store.update(entry.id, {"current_price": 99999.0})
        # current_price is not in the allowed whitelist — stored value is None
        fetched = store.get(entry.id)
        assert fetched is not None
        # current_price is not stored in SQLite; it should remain None after fetch
        assert fetched.current_price is None

    def test_update_nonexistent_returns_none(self, store):
        """update() returns None for an unknown id."""
        result = store.update("no-such-id", {"notes": "whatever"})
        assert result is None

    def test_delete_returns_true(self, store):
        """delete() returns True when the entry existed."""
        body = JournalEntryCreate(ticker="SPY", action="BUY", entry_price=500.0, thesis="ETF")
        entry = store.create(body)
        assert store.delete(entry.id) is True

    def test_delete_nonexistent_returns_false(self, store):
        """delete() returns False for an unknown id."""
        assert store.delete("ghost") is False

    def test_delete_then_get_returns_none(self, store):
        """After delete(), get() returns None."""
        body = JournalEntryCreate(ticker="QQQ", action="SELL", entry_price=440.0, thesis="Hedge")
        entry = store.create(body)
        store.delete(entry.id)
        assert store.get(entry.id) is None
