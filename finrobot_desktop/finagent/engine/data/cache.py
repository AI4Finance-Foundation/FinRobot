import json
from datetime import datetime, timezone

import aiosqlite
from pydantic import BaseModel

from finagent.engine.data.interface import DataResult

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS cache (
    data_type TEXT NOT NULL,
    ticker    TEXT NOT NULL,
    data      TEXT NOT NULL,
    cached_at TIMESTAMP NOT NULL,
    PRIMARY KEY (data_type, ticker)
)
"""


class CachedResult(BaseModel):
    data: DataResult
    is_stale: bool
    cached_at: datetime


class DataCache:
    def __init__(self, db_path: str = "finagent_cache.db") -> None:
        self._db_path = db_path

    async def _init(self, conn: aiosqlite.Connection) -> None:
        await conn.execute(_CREATE_TABLE)
        await conn.commit()

    async def get(self, data_type: str, ticker: str, max_age_hours: int = 24) -> CachedResult | None:
        async with aiosqlite.connect(self._db_path) as conn:
            await self._init(conn)
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
        age_hours = (now - cached_at).total_seconds() / 3600
        is_stale = age_hours > max_age_hours

        result = DataResult.model_validate_json(raw_data)
        return CachedResult(data=result, is_stale=is_stale, cached_at=cached_at)

    async def set(self, data_type: str, ticker: str, result: DataResult) -> None:
        cached_at = datetime.now(tz=timezone.utc).isoformat()
        async with aiosqlite.connect(self._db_path) as conn:
            await self._init(conn)
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
        async with aiosqlite.connect(self._db_path) as conn:
            await self._init(conn)
            if ticker is None:
                await conn.execute("DELETE FROM cache")
            else:
                await conn.execute("DELETE FROM cache WHERE ticker = ?", (ticker,))
            await conn.commit()
