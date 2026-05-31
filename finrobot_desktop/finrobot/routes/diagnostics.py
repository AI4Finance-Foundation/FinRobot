"""Diagnostics: bundle runtime logs for one-click export from the desktop UI."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import Response

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


def _logs_dir(request: Request) -> Path:
    override = getattr(request.app.state, "logs_dir", None)
    if override is not None:
        return Path(override)
    from finrobot.paths import LOGS_DIR

    return LOGS_DIR


@router.get("/logs/export")
async def export_logs(request: Request) -> Response:
    """Return a zip of every file in the logs directory (empty zip if none)."""
    logs_dir = _logs_dir(request)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if logs_dir.is_dir():
            for f in sorted(logs_dir.iterdir()):
                if f.is_file():
                    zf.write(f, arcname=f.name)
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="finrobot-logs.zip"'},
    )
