"""Cold-start readiness gate for routes that need the live data-provider chain.

The sidecar wires the provider chain in a post-yield background task (see
``server.lifespan`` / ``_build_data_layer_background``), so for a beat after boot
``app.state.engine_ready`` is False and ``deps.data_layer`` carries no providers.

Live-data routes (price / financials / valuation seeds) call ``ensure_engine_ready``
to return a clean 503 "starting" — a *pending* signal the desktop retries — instead
of fetching against an empty chain. They must never fabricate a number during the
warming window; 503 is the honest answer when there is no local fallback.

Routes that read only local SQLite (artifacts / coverage / the dashboard's research
list) deliberately do NOT call this — serving them immediately, without waiting on
the provider chain, is the whole point of the cold-start split.
"""

from __future__ import annotations

from fastapi import HTTPException
from starlette.requests import Request


def is_engine_ready(request: Request) -> bool:
    """True once the data-provider chain is wired (or no lifespan ran, e.g. tests).

    Defaults True via ``getattr`` so a test harness that sets ``app.state`` by hand
    without booting the lifespan — and so never sets ``engine_ready`` — behaves
    exactly as before this split (it injects its own ready data_layer)."""
    return bool(getattr(request.app.state, "engine_ready", True))


def ensure_engine_ready(request: Request) -> None:
    """Raise 503 "starting" if the live data-provider chain is still warming up."""
    if not is_engine_ready(request):
        raise HTTPException(
            status_code=503,
            detail="Data engine is still starting — retry in a moment.",
        )
