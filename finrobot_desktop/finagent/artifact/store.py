"""Backwards-compatible ArtifactStore facade.

The real implementation now lives in
:class:`finagent.artifact.sqlite_store.SqliteArtifactStore`. This module
keeps the public ``ArtifactStore`` name so the ~20 existing imports in
routes / pipelines / tests don't churn.

For new code prefer importing ``SqliteArtifactStore`` directly.

Args:
    base_dir: When provided, the legacy ``base_dir / artifacts.db`` is
        used (so tests that hand-roll a tmp dir keep isolation). When
        omitted, the unified path from :mod:`finagent.paths` applies.
"""

from __future__ import annotations

from pathlib import Path

from finagent.artifact.models import Artifact, ArtifactSummary, ArtifactType
from finagent.artifact.sqlite_store import SqliteArtifactStore, summary_from_artifact

# Backwards-compat alias: the legacy filesystem implementation exposed
# ``_summary_from_artifact`` as a private helper that tests + audit tools
# imported. New code should use the public ``summary_from_artifact``.
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

    async def delete(self, artifact_id: str) -> bool:
        return await self._impl.delete(artifact_id)

    async def list_by_ticker(
        self,
        ticker: str | None = None,
        type: ArtifactType | None = None,  # noqa: A002
        include_archived: bool = False,
        limit: int = 100,
    ) -> list[ArtifactSummary]:
        return await self._impl.list_by_ticker(
            ticker=ticker, type=type, include_archived=include_archived, limit=limit
        )

    async def list_versions(self, ticker: str, type: ArtifactType) -> list[ArtifactSummary]:  # noqa: A002
        return await self._impl.list_versions(ticker, type)

    async def mark_viewed(self, artifact_id: str) -> None:
        await self._impl.mark_viewed(artifact_id)

    async def archive_stale(self, hours: int = 24) -> int:
        return await self._impl.archive_stale(hours)

    async def rebuild_summaries(self) -> int:
        return await self._impl.rebuild_summaries()

    async def close(self) -> None:
        await self._impl.close()
