"""``ArtifactStore`` facade.

The implementation lives in
:class:`finrobot.artifact.sqlite_store.SqliteArtifactStore`. This module
re-exports the ``ArtifactStore`` name so the ~20 imports across
routes / pipelines / tests share one entry point; new code may import
``SqliteArtifactStore`` directly.

Args:
    base_dir: When provided, ``base_dir / artifacts.db`` is used (so tests
        that hand-roll a tmp dir keep isolation). When omitted, the unified
        path from :mod:`finrobot.paths` applies.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from finrobot.artifact.models import Artifact, ArtifactSummary, ArtifactType
from finrobot.artifact.sqlite_store import SqliteArtifactStore, summary_from_artifact

# Alias kept so tests + audit tools importing the private
# ``_summary_from_artifact`` keep working; new code uses the public name.
_summary_from_artifact = summary_from_artifact


class ArtifactStore:
    """Thin shim delegating to :class:`SqliteArtifactStore`.

    Common methods are explicitly forwarded with typed signatures so
    callers get type-checked returns instead of Any. Less-used
    SqliteArtifactStore methods fall through via ``__getattr__``.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        db_path: Path | None = None
        if base_dir is not None:
            db_path = Path(base_dir) / "artifacts.db"
        self._impl = SqliteArtifactStore(db_path=db_path)

    async def save(self, artifact: Artifact) -> str:
        return await self._impl.save(artifact)

    async def get(self, artifact_id: str) -> Artifact | None:
        return await self._impl.get(artifact_id)

    async def exists(self, artifact_id: str) -> bool:
        return await self._impl.exists(artifact_id)

    async def delete(self, artifact_id: str) -> bool:
        return await self._impl.delete(artifact_id)

    async def list_by_ticker(
        self,
        ticker: str | None = None,
        type: ArtifactType | None = None,  # noqa: A002
        include_archived: bool = False,
        limit: int = 100,
        tickers: set[str] | None = None,
    ) -> list[ArtifactSummary]:
        return await self._impl.list_by_ticker(
            ticker=ticker,
            type=type,
            include_archived=include_archived,
            limit=limit,
            tickers=tickers,
        )

    async def count(
        self,
        *,
        include_archived: bool = False,
        tickers: set[str] | None = None,
        created_after: datetime | None = None,
    ) -> int:
        return await self._impl.count(
            include_archived=include_archived,
            tickers=tickers,
            created_after=created_after,
        )

    async def distinct_ticker_count(self, *, include_archived: bool = False) -> int:
        return await self._impl.distinct_ticker_count(include_archived=include_archived)

    async def list_versions(self, ticker: str, type: ArtifactType) -> list[ArtifactSummary]:  # noqa: A002
        return await self._impl.list_versions(ticker, type)

    async def mark_viewed(self, artifact_id: str) -> None:
        await self._impl.mark_viewed(artifact_id)

    async def archive_stale(self, hours: int = 24) -> int:
        return await self._impl.archive_stale(hours)

    async def rebuild_summaries(self) -> int:
        return await self._impl.rebuild_summaries()

    async def rebuild_summaries_if_outdated(self) -> int:
        return await self._impl.rebuild_summaries_if_outdated()

    async def close(self) -> None:
        await self._impl.close()
