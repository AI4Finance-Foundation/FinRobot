"""Decision Journal CRUD endpoints.

All SQLite operations run inside asyncio.to_thread because JournalStore methods
are synchronous.  yfinance price enrichment also runs in to_thread for the
same reason.

Error handling:
- sqlite3.Error        — database I/O failures (OperationalError, IntegrityError, etc.)
- ImportError          — yfinance not installed (optional dep)
- AttributeError       — yfinance API surface mismatch
- ValueError           — bad price / arithmetic
Price-enrichment failures are logged and silently degraded (entry still
returned without P&L data) — acceptable because live price is advisory.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3

from fastapi import APIRouter, HTTPException

from finagent.models.journal import JournalEntry, JournalEntryCreate, JournalStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/journal", tags=["journal"])

# Module-level singleton: created once on first request, reused thereafter.
_store: JournalStore | None = None


def _get_store() -> JournalStore:
    global _store
    if _store is None:
        _store = JournalStore()
    return _store


def _fetch_current_price(ticker: str) -> float | None:
    """Synchronous yfinance price lookup — must be called inside to_thread.

    Returns the last traded price, or None if unavailable.
    """
    import yfinance as yf  # lazy import; yfinance is an optional enrichment dep

    info = yf.Ticker(ticker).fast_info
    # fast_info is a FastInfo object; attribute access, not dict .get()
    price: float | None = getattr(info, "last_price", None)
    if price is None:
        price = getattr(info, "lastPrice", None)
    return float(price) if price is not None else None


async def _enrich_with_price(entry: JournalEntry) -> JournalEntry:
    """Add current_price / pnl_pct / pnl_abs from yfinance (best-effort).

    Failures are logged and the entry is returned unchanged — callers must
    not assume enriched fields are populated.
    """
    try:
        current = await asyncio.to_thread(_fetch_current_price, entry.ticker)
        if current is not None and entry.entry_price > 0:
            entry.current_price = round(current, 2)
            if entry.action == "SELL":
                # Profit for SELL when price fell after entry
                entry.pnl_pct = round((entry.entry_price - current) / entry.entry_price * 100, 2)
                entry.pnl_abs = round(entry.entry_price - current, 2)
            else:
                entry.pnl_pct = round((current - entry.entry_price) / entry.entry_price * 100, 2)
                entry.pnl_abs = round(current - entry.entry_price, 2)
    except (ImportError, AttributeError, ValueError, TypeError, OSError):
        logger.exception("Price enrichment failed for %s — returning without P&L", entry.ticker)
    return entry


@router.post("", response_model=JournalEntry)
async def create_entry(body: JournalEntryCreate) -> JournalEntry:
    """Create a new journal entry and return it enriched with current price."""
    try:
        entry = await asyncio.to_thread(_get_store().create, body)
    except sqlite3.Error:
        logger.exception("JournalStore.create failed")
        raise HTTPException(status_code=500, detail="Failed to persist journal entry")
    return await _enrich_with_price(entry)


@router.get("", response_model=list[JournalEntry])
async def list_entries() -> list[JournalEntry]:
    """List all journal entries (newest first), enriched with live price (up to 20)."""
    try:
        entries = await asyncio.to_thread(_get_store().list_all)
    except sqlite3.Error:
        logger.exception("JournalStore.list_all failed")
        raise HTTPException(status_code=500, detail="Failed to read journal entries")
    # Enrich concurrently; limit to 20 to avoid hammering yfinance
    enriched_futures = [_enrich_with_price(e) for e in entries[:20]]
    enriched = await asyncio.gather(*enriched_futures)
    # Entries beyond 20 stay un-enriched (current_price / pnl will be None)
    return list(enriched) + entries[20:]


@router.get("/{entry_id}", response_model=JournalEntry)
async def get_entry(entry_id: str) -> JournalEntry:
    """Fetch a single journal entry enriched with current price."""
    try:
        entry = await asyncio.to_thread(_get_store().get, entry_id)
    except sqlite3.Error:
        logger.exception("JournalStore.get failed for id=%s", entry_id)
        raise HTTPException(status_code=500, detail="Failed to read journal entry")
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return await _enrich_with_price(entry)


@router.put("/{entry_id}", response_model=JournalEntry)
async def update_entry(entry_id: str, body: dict[str, object]) -> JournalEntry:
    """Partial-update a journal entry (ticker, action, entry_price, target_price, thesis, notes)."""
    try:
        entry = await asyncio.to_thread(_get_store().update, entry_id, body)
    except sqlite3.Error:
        logger.exception("JournalStore.update failed for id=%s", entry_id)
        raise HTTPException(status_code=500, detail="Failed to update journal entry")
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return await _enrich_with_price(entry)


@router.delete("/{entry_id}")
async def delete_entry(entry_id: str) -> dict[str, str]:
    """Delete a journal entry by id."""
    try:
        deleted = await asyncio.to_thread(_get_store().delete, entry_id)
    except sqlite3.Error:
        logger.exception("JournalStore.delete failed for id=%s", entry_id)
        raise HTTPException(status_code=500, detail="Failed to delete journal entry")
    if not deleted:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"status": "deleted"}
