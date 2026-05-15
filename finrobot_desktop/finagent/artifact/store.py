"""Artifact store: filesystem-backed JSON storage with per-ticker indexing.

Storage layout:
  ~/.finagent-desktop/artifacts/<ticker>/<artifact_id>.json   — full Artifact
  ~/.finagent-desktop/artifacts/<ticker>/index.json           — ArtifactSummary list
  ~/.finagent-desktop/artifacts/_cross/<artifact_id>.json     — cross-ticker artifacts
  ~/.finagent-desktop/artifacts/_cross/index.json

Atomic writes: write to <id>.json.tmp, then rename to <id>.json.
Per-ticker asyncio.Lock protects concurrent writes to the same ticker's index.
A global _index_lock is used for the full-store index rebuild needed by list_all.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from finagent.artifact.models import (
    Artifact,
    ArtifactSummary,
    ArtifactType,
)

logger = logging.getLogger(__name__)

_DEFAULT_BASE = Path.home() / ".finagent-desktop" / "artifacts"
_CROSS_DIR = "_cross"


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _ticker_dir(base: Path, ticker: str | None) -> Path:
    segment = _CROSS_DIR if ticker is None else ticker.upper()
    return base / segment


def _summary_from_artifact(artifact: Artifact) -> ArtifactSummary:
    """Build a lean ArtifactSummary from a full Artifact."""
    return ArtifactSummary(
        id=artifact.id,
        ticker=artifact.ticker,
        cross_tickers=artifact.cross_tickers,
        type=artifact.type,
        created_at=artifact.meta.created_at,
        headline=artifact.outputs.summary_text[:120] or artifact.id,
        source=artifact.meta.source,
        archived=artifact.meta.archived,
    )


class ArtifactStore:
    """Filesystem-backed store for computational artifact snapshots.

    One file per artifact, one index.json per ticker directory.
    All methods are async-safe within a single process.

    Args:
        base_dir: Root directory for artifact storage. Defaults to
            ``~/.finagent-desktop/artifacts``.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base = Path(base_dir) if base_dir is not None else _DEFAULT_BASE
        # Per-ticker write locks: ticker (str | "_cross") → asyncio.Lock
        self._ticker_locks: dict[str, asyncio.Lock] = {}
        self._ticker_locks_lock = asyncio.Lock()

    async def _get_ticker_lock(self, ticker_key: str) -> asyncio.Lock:
        """Return (creating if needed) the per-ticker write lock."""
        async with self._ticker_locks_lock:
            if ticker_key not in self._ticker_locks:
                self._ticker_locks[ticker_key] = asyncio.Lock()
            return self._ticker_locks[ticker_key]

    def _ticker_key(self, ticker: str | None) -> str:
        return _CROSS_DIR if ticker is None else ticker.upper()

    def _artifact_path(self, ticker: str | None, artifact_id: str) -> Path:
        return _ticker_dir(self._base, ticker) / f"{artifact_id}.json"

    def _index_path(self, ticker: str | None) -> Path:
        return _ticker_dir(self._base, ticker) / "index.json"

    def _ensure_dir(self, ticker: str | None) -> Path:
        d = _ticker_dir(self._base, ticker)
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ------------------------------------------------------------------
    # Internal: atomic write helpers
    # ------------------------------------------------------------------

    def _write_atomic(self, path: Path, data: str) -> None:
        """Write *data* to *path* atomically via a temp file + rename.

        Uses os.replace() which is atomic on POSIX and best-effort on Windows.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(data)
            os.replace(tmp_path, str(path))
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _read_json(self, path: Path) -> Any:
        """Read and parse a JSON file, returning None if it doesn't exist."""
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    # ------------------------------------------------------------------
    # Internal: index helpers (called under per-ticker lock)
    # ------------------------------------------------------------------

    def _load_index(self, ticker: str | None) -> list[dict[str, Any]]:
        raw = self._read_json(self._index_path(ticker))
        if isinstance(raw, list):
            return raw
        return []

    def _save_index(self, ticker: str | None, entries: list[dict[str, Any]]) -> None:
        self._write_atomic(self._index_path(ticker), json.dumps(entries, default=str))

    def _upsert_index(self, ticker: str | None, summary: ArtifactSummary) -> None:
        """Add or replace the summary entry in the ticker's index."""
        entries = self._load_index(ticker)
        # Remove existing entry for this id, then append new one
        entries = [e for e in entries if e.get("id") != summary.id]
        entries.append(json.loads(summary.model_dump_json()))
        self._save_index(ticker, entries)

    def _remove_from_index(self, ticker: str | None, artifact_id: str) -> bool:
        """Remove artifact_id from the ticker index. Returns True if it was found."""
        entries = self._load_index(ticker)
        new_entries = [e for e in entries if e.get("id") != artifact_id]
        if len(new_entries) == len(entries):
            return False
        self._save_index(ticker, new_entries)
        return True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def save(self, artifact: Artifact) -> str:
        """Persist an artifact to disk and update the ticker index.

        Writes are atomic (temp file + rename). The per-ticker lock prevents
        concurrent writes from corrupting index.json.

        Args:
            artifact: The Artifact to persist.

        Returns:
            The artifact's id.
        """
        ticker_key = self._ticker_key(artifact.ticker)
        lock = await self._get_ticker_lock(ticker_key)

        async with lock:
            # Run I/O in a thread to avoid blocking the event loop.
            def _write() -> None:
                self._ensure_dir(artifact.ticker)
                path = self._artifact_path(artifact.ticker, artifact.id)
                self._write_atomic(path, artifact.model_dump_json())
                summary = _summary_from_artifact(artifact)
                self._upsert_index(artifact.ticker, summary)

            await asyncio.to_thread(_write)

        logger.debug("Artifact saved: %s", artifact.id)
        return artifact.id

    async def get(self, artifact_id: str) -> Artifact | None:
        """Load a full Artifact by id.

        Searches across all ticker directories. O(tickers) on miss.

        Args:
            artifact_id: The artifact id (e.g. "art_2026-05-13T14:32:18_AAPL_dcf").

        Returns:
            The Artifact, or None if not found.
        """

        def _find() -> Artifact | None:
            # Search all subdirectories under self._base
            if not self._base.exists():
                return None
            for sub in self._base.iterdir():
                if not sub.is_dir():
                    continue
                path = sub / f"{artifact_id}.json"
                if path.exists():
                    raw = self._read_json(path)
                    if raw is not None:
                        try:
                            return Artifact.model_validate(raw)
                        except (ValueError, TypeError, KeyError):
                            logger.warning("Corrupt artifact file: %s", path)
                            return None
            return None

        return await asyncio.to_thread(_find)

    async def delete(self, artifact_id: str) -> bool:
        """Remove an artifact file and update the ticker index.

        Args:
            artifact_id: The artifact id to delete.

        Returns:
            True if the artifact was found and deleted, False if not found.
        """

        def _find_and_delete() -> tuple[bool, str | None]:
            """Returns (deleted, ticker_key)."""
            if not self._base.exists():
                return False, None
            for sub in self._base.iterdir():
                if not sub.is_dir():
                    continue
                path = sub / f"{artifact_id}.json"
                if path.exists():
                    raw = self._read_json(path)
                    ticker_key = sub.name
                    try:
                        path.unlink()
                    except OSError:
                        return False, None
                    # Determine ticker for index update
                    if raw is not None:
                        try:
                            art = Artifact.model_validate(raw)
                            return True, self._ticker_key(art.ticker)
                        except (ValueError, TypeError, KeyError):
                            return True, ticker_key
                    return True, ticker_key
            return False, None

        deleted, ticker_key = await asyncio.to_thread(_find_and_delete)
        if not deleted or ticker_key is None:
            return False

        # Update index under lock
        ticker: str | None = None if ticker_key == _CROSS_DIR else ticker_key
        lock = await self._get_ticker_lock(ticker_key)
        async with lock:
            await asyncio.to_thread(self._remove_from_index, ticker, artifact_id)

        return True

    async def list_by_ticker(
        self,
        ticker: str | None = None,
        type: ArtifactType | None = None,  # noqa: A002
        include_archived: bool = False,
        limit: int = 100,
    ) -> list[ArtifactSummary]:
        """Return summaries for a ticker (or all tickers if ticker is None).

        Results are sorted by created_at descending.

        Args:
            ticker: Ticker symbol to filter by, or None for all tickers.
            type: Artifact type to filter by.
            include_archived: Whether to include archived artifacts.
            limit: Maximum number of results to return.

        Returns:
            List of ArtifactSummary sorted by created_at descending.
        """

        def _load() -> list[ArtifactSummary]:
            summaries: list[ArtifactSummary] = []
            if not self._base.exists():
                return summaries

            if ticker is not None:
                dirs = [_ticker_dir(self._base, ticker)]
            else:
                dirs = [d for d in self._base.iterdir() if d.is_dir()]

            for d in dirs:
                idx_path = d / "index.json"
                raw = self._read_json(idx_path)
                if not isinstance(raw, list):
                    continue
                for entry in raw:
                    try:
                        s = ArtifactSummary.model_validate(entry)
                    except (ValueError, TypeError, KeyError):
                        continue
                    if not include_archived and s.archived:
                        continue
                    if type is not None and s.type != type:
                        continue
                    summaries.append(s)

            summaries.sort(key=lambda s: s.created_at, reverse=True)
            return summaries[:limit]

        return await asyncio.to_thread(_load)

    async def list_versions(
        self,
        ticker: str,
        type: ArtifactType,  # noqa: A002
    ) -> list[ArtifactSummary]:
        """Return all versions of a ticker+type combination, newest first.

        Args:
            ticker: The ticker symbol.
            type: The analysis type (e.g. "dcf").

        Returns:
            List of ArtifactSummary sorted by created_at descending.
        """
        return await self.list_by_ticker(
            ticker=ticker,
            type=type,
            include_archived=True,
            limit=1000,
        )

    async def mark_viewed(self, artifact_id: str) -> None:
        """Record that this artifact was viewed now.

        Loads the artifact, updates last_viewed_at, saves it back.
        Also refreshes the index entry so the summary reflects the change.

        Args:
            artifact_id: The artifact id to mark as viewed.
        """
        artifact = await self.get(artifact_id)
        if artifact is None:
            return

        ticker_key = self._ticker_key(artifact.ticker)
        lock = await self._get_ticker_lock(ticker_key)

        async with lock:

            def _update() -> None:
                artifact.meta.last_viewed_at = _now()
                artifact.meta.archived = False  # viewing un-archives
                self._ensure_dir(artifact.ticker)
                path = self._artifact_path(artifact.ticker, artifact.id)
                self._write_atomic(path, artifact.model_dump_json())
                summary = _summary_from_artifact(artifact)
                self._upsert_index(artifact.ticker, summary)

            await asyncio.to_thread(_update)

    async def archive_stale(self, hours: int = 24) -> int:
        """Mark artifacts unviewed for *hours* as archived.

        Intended to be called from a background task at server startup or
        on a periodic schedule (e.g. via FastAPI lifespan).

        Args:
            hours: Number of hours without a view before archiving.

        Returns:
            Number of artifacts that were newly archived.
        """
        cutoff = _now()
        archived_count = 0

        if not self._base.exists():
            return 0

        for sub in self._base.iterdir():
            if not sub.is_dir():
                continue
            for art_file in sub.glob("*.json"):
                if art_file.name == "index.json":
                    continue
                raw = self._read_json(art_file)
                if raw is None:
                    continue
                try:
                    artifact = Artifact.model_validate(raw)
                except (ValueError, TypeError, KeyError):
                    continue

                if artifact.meta.archived:
                    continue

                # Determine effective last-seen time
                last_seen = artifact.meta.last_viewed_at or artifact.meta.created_at
                age_hours = (cutoff - last_seen).total_seconds() / 3600
                if age_hours < hours:
                    continue

                ticker_key = self._ticker_key(artifact.ticker)
                lock = await self._get_ticker_lock(ticker_key)

                async with lock:

                    def _archive(art: Artifact = artifact, path: Path = art_file) -> None:
                        art.meta.archived = True
                        self._write_atomic(path, art.model_dump_json())
                        summary = _summary_from_artifact(art)
                        self._upsert_index(art.ticker, summary)

                    await asyncio.to_thread(_archive)

                archived_count += 1

        logger.info("archive_stale: archived %d artifacts (threshold=%dh)", archived_count, hours)
        return archived_count
