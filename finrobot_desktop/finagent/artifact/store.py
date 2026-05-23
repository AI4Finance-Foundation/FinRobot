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
from typing import Any

from finagent.artifact.sqlite_store import SqliteArtifactStore, summary_from_artifact

# Backwards-compat alias: the legacy filesystem implementation exposed
# ``_summary_from_artifact`` as a private helper that tests + audit tools
# imported. New code should use the public ``summary_from_artifact``.
_summary_from_artifact = summary_from_artifact


class ArtifactStore:
    """Thin shim delegating to :class:`SqliteArtifactStore`."""

    def __init__(self, base_dir: Path | None = None) -> None:
        db_path: Path | None = None
        if base_dir is not None:
            db_path = Path(base_dir) / "artifacts.db"
        self._impl = SqliteArtifactStore(db_path=db_path)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._impl, name)
