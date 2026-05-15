import asyncio
from datetime import datetime, timezone

import aiosqlite
from pydantic import BaseModel

from finagent.engine.data.interface import DataResult
from finagent.engine.data.types import DataType

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS cache (
    data_type TEXT NOT NULL,
    ticker    TEXT NOT NULL,
    data      TEXT NOT NULL,
    cached_at TIMESTAMP NOT NULL,
    PRIMARY KEY (data_type, ticker)
)
"""

# TTL (in seconds) per data type. Different financial data types have
# fundamentally different freshness requirements:
# - price: changes every trading second, 15 min is a reasonable compromise
# - news: semi-fresh, 30 min keeps context relevant without hammering APIs
# - financials: quarterly updates, 24h is plenty fresh
# - earnings_transcript: transcripts are immutable once published
# - default: 1 hour for anything not explicitly listed
_TTL_SECONDS: dict[str, int] = {
    DataType.PRICE: 900,  # 15 minutes
    DataType.NEWS: 1800,  # 30 minutes
    DataType.FINANCIALS: 86400,  # 24 hours
    DataType.EARNINGS: 86400,  # 24 hours (quarterly data)
    DataType.EARNINGS_TRANSCRIPT: 604800,  # 7 days
    DataType.FILINGS: 604800,  # 7 days (SEC filings don't change)
    DataType.RAG_10K: 604800,  # 7 days
    DataType.PROFILE: 86400,  # 24 hours
}
_DEFAULT_TTL_SECONDS: int = 3600  # 1 hour


def _get_ttl_seconds(data_type: str | DataType) -> int:
    """Return the TTL in seconds for a given data type."""
    return _TTL_SECONDS.get(str(data_type), _DEFAULT_TTL_SECONDS)


class CachedResult(BaseModel):
    data: DataResult
    is_stale: bool
    cached_at: datetime


class DataCache:
    def __init__(self, db_path: str = "") -> None:
        if not db_path:
            from finagent.config import _default_cache_db_path

            db_path = _default_cache_db_path()
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._conn_lock = asyncio.Lock()

    async def _ensure_connection(self) -> aiosqlite.Connection:
        """Lazily create connection and table on first use, then reuse.

        Lock prevents TOCTOU race when multiple coroutines call _ensure_connection
        simultaneously before the first connection is established.
        WAL mode is enabled on first open so concurrent set() calls don't SQLITE_BUSY.
        """
        async with self._conn_lock:
            if self._conn is None:
                self._conn = await aiosqlite.connect(self._db_path)
                await self._conn.execute("PRAGMA journal_mode=WAL")
                await self._conn.execute("PRAGMA synchronous=NORMAL")
                await self._conn.execute(_CREATE_TABLE)
                await self._conn.commit()
        return self._conn

    async def get(
        self,
        data_type: str | DataType,
        ticker: str,
        max_age_hours: int | None = None,
    ) -> CachedResult | None:
        """Retrieve cached data, marking it stale if older than the TTL.

        TTL is determined automatically from the data_type (see ``_TTL_SECONDS``).
        The ``max_age_hours`` parameter is kept for backwards compatibility and
        test convenience: when provided it overrides the data-type TTL.
        """
        conn = await self._ensure_connection()
        async with conn.execute(
            "SELECT data, cached_at FROM cache WHERE data_type = ? AND ticker = ?",
            (data_type, ticker),
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            return None

        raw_data, cached_at_str = row
        cached_at = datetime.fromisoformat(cached_at_str)
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)

        now = datetime.now(tz=timezone.utc)
        age_seconds = (now - cached_at).total_seconds()

        if max_age_hours is not None:
            # Explicit override — convert hours to seconds for comparison
            is_stale = age_seconds > max_age_hours * 3600
        else:
            # Use per-data-type TTL
            ttl = _get_ttl_seconds(data_type)
            is_stale = age_seconds > ttl

        result = DataResult.model_validate_json(raw_data)
        return CachedResult(data=result, is_stale=is_stale, cached_at=cached_at)

    async def set(self, data_type: str | DataType, ticker: str, result: DataResult) -> None:
        cached_at = datetime.now(tz=timezone.utc).isoformat()
        conn = await self._ensure_connection()
        await conn.execute(
            """
            INSERT INTO cache (data_type, ticker, data, cached_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(data_type, ticker) DO UPDATE SET
                data = excluded.data,
                cached_at = excluded.cached_at
            """,
            (data_type, ticker, result.model_dump_json(), cached_at),
        )
        await conn.commit()

    async def clear(self, ticker: str | None = None) -> None:
        conn = await self._ensure_connection()
        if ticker is None:
            await conn.execute("DELETE FROM cache")
        else:
            await conn.execute("DELETE FROM cache WHERE ticker = ?", (ticker,))
        await conn.commit()

    async def close(self) -> None:
        """Close the connection. Call during shutdown."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
