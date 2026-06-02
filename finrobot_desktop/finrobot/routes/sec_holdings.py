"""SEC 13F institutional-holdings cache: status + manual refresh.

The 13F reverse index (ticker → holders) is built by downloading an entire
quarter of 13F-HR filings — a heavy, multi-minute job that is OFF by default
(``sec_holdings_auto_refresh``) so a fresh install doesn't hammer SEC on first
launch. These endpoints let the desktop Settings page report cache state and
let the user trigger the build on demand.

``POST /refresh`` returns immediately; the parse runs in a tracked background
task (see ``sec_holdings_sync``). The frontend polls ``GET /status`` for
``populated`` / ``refresh.status`` to drive a progress indicator.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from starlette.requests import Request

from finrobot.config import get_settings
from finrobot.engine.data.providers.edgar_provider import _is_valid_identity
from finrobot.engine.data.sec_holdings_cache import cache_status
from finrobot.engine.data.sec_holdings_sync import get_state, start_refresh

router = APIRouter(prefix="/api/sec-holdings", tags=["sec-holdings"])


class RefreshRuntimeState(BaseModel):
    status: str  # idle | running | done | error
    period_end: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None


class SecHoldingsStatus(BaseModel):
    populated: bool
    row_count: int
    latest_period_end: str | None
    distinct_tickers: int
    identity_configured: bool
    """Whether a valid SEC User-Agent identity is set. Refresh is impossible
    without it — the UI greys out the 立即同步 button when this is False."""
    auto_refresh: bool
    """The ``sec_holdings_auto_refresh`` setting. When False, no background
    sync runs at startup — the 13F cache only ever populates via manual
    refresh or this flag being turned on."""
    refresh: RefreshRuntimeState


@router.get("/status", response_model=SecHoldingsStatus)
async def sec_holdings_status() -> SecHoldingsStatus:
    """Report 13F cache population + the most-recent/in-flight refresh state."""
    settings = get_settings()
    cache = await cache_status()
    return SecHoldingsStatus(
        populated=bool(cache["populated"]),
        row_count=int(cache["row_count"]),
        latest_period_end=cache["latest_period_end"],
        distinct_tickers=int(cache["distinct_tickers"]),
        identity_configured=_is_valid_identity(settings.sec_user_agent),
        auto_refresh=bool(settings.sec_holdings_auto_refresh),
        refresh=RefreshRuntimeState(**get_state()),
    )


@router.post("/refresh", response_model=SecHoldingsStatus)
async def sec_holdings_refresh(request: Request) -> SecHoldingsStatus:
    """Trigger a 13F refresh for the latest completed quarter (force=True).

    Idempotent: if a refresh is already running, returns the running state
    without starting a second one. If SEC identity is unconfigured, returns
    with ``refresh.error == "identity_missing"`` and does no work.
    """
    settings = get_settings()
    await start_refresh(request.app, settings, force=True)
    # Re-read full status so the response carries cache + identity + the
    # (possibly just-updated) refresh state in one round trip.
    return await sec_holdings_status()
