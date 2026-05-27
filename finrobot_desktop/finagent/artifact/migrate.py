"""One-shot migration: filesystem JSON → SQLite ArtifactStore.

Called from the server lifespan on every startup; idempotent — re-running
on an empty legacy dir or an already-migrated dir is a no-op.

Legacy layout (pre-2026-05-23):
    ~/.finagent-desktop/artifacts/<TICKER or _cross>/<id>.json
    ~/.finagent-desktop/artifacts/<TICKER or _cross>/index.json

After migration the JSON files stay on disk as a backup until the user
deletes them manually. We never destroy data without an explicit user
action — the new SQLite db at ~/.finagent/artifacts.db has its own copy.
"""

from __future__ import annotations

import logging
from pathlib import Path

from typing import Any

from finagent.artifact.models import Artifact
from finagent.artifact.sqlite_store import SqliteArtifactStore

logger = logging.getLogger(__name__)

LEGACY_ARTIFACTS_ROOT = Path.home() / ".finagent-desktop" / "artifacts"


async def migrate_filesystem_to_sqlite(
    legacy_root: Path | None = None,
    store: Any = None,
) -> int:
    """Walk *legacy_root* for ``*.json`` artifact files and save each to *store*.

    Returns the count of artifacts ingested (insert-only — see below).

    2026-05-27: migration is **insert-only**, not upsert. Previously the
    server lifespan happily overwrote in-place SQL edits (verdict backfills,
    user annotations, anything) with whatever stale data the legacy JSON
    still carried. With backfill scripts running between upgrades that
    behaviour silently un-did every fix. We now skip any legacy file whose
    id already lives in SQLite — once an artifact is in the new store it
    is authoritative, and the JSON is treated as a one-way historical
    backup only.

    Args:
        legacy_root: Defaults to ``~/.finagent-desktop/artifacts``.
        store: Anything exposing ``async save(artifact)`` + ``async get(id)``.
            Both :class:`SqliteArtifactStore` and the :class:`ArtifactStore`
            shim qualify. Defaults to a fresh ``SqliteArtifactStore()``.
    """
    root = legacy_root if legacy_root is not None else LEGACY_ARTIFACTS_ROOT
    if not root.exists():
        return 0

    target = store if store is not None else SqliteArtifactStore()
    count = 0
    skipped = 0
    for sub in root.iterdir():
        if not sub.is_dir():
            continue
        for art_file in sub.glob("*.json"):
            if art_file.name == "index.json":
                continue
            try:
                payload = art_file.read_text(encoding="utf-8")
                artifact = Artifact.model_validate_json(payload)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                logger.warning("Skip corrupt artifact %s: %s", art_file, exc)
                continue
            # Insert-only: never clobber data already in SQLite. The first
            # boot after upgrading from the JSON store imports everything;
            # every subsequent boot is a near-zero-cost no-op.
            existing = await target.get(artifact.id)
            if existing is not None:
                skipped += 1
                continue
            await target.save(artifact)
            count += 1

    if count or skipped:
        logger.info(
            "Legacy artifact migration: %d new, %d already in SQLite (skipped)",
            count,
            skipped,
        )
    return count
