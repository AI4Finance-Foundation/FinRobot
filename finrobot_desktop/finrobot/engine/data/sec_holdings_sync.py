"""Shared 13F holdings refresh trigger — ONE code path for both the lifespan
auto-refresh and the user-triggered manual refresh (Settings → 立即同步).

Holds process-wide refresh runtime state (status / period / error / summary)
so ``GET /api/sec-holdings/status`` can report progress without re-deriving it.

Architectural red line (sealed in ``sec_holdings_cache`` module docstring):
the heavy ``get_filings(form="13F-HR")`` parse NEVER runs on the server event
loop or inside a request handler thread. Both callers off-load it to a worker
thread via ``asyncio.to_thread(asyncio.run, _refresh_quarter(...))``. The
manual endpoint spawns the work as a tracked background task and returns
immediately; the frontend polls ``status`` for completion.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


@dataclass
class RefreshState:
    """Process-wide snapshot of the most recent / in-flight refresh.

    ``status`` transitions: ``idle`` → ``running`` → ``done`` | ``error``.
    A new run resets ``error`` / ``summary`` and moves back to ``running``.
    """

    status: str = "idle"
    period_end: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None  # error CODE for the UI: "identity_missing" | free text
    summary: dict[str, Any] | None = None


_STATE = RefreshState()
_LOCK = asyncio.Lock()


def get_state() -> dict[str, Any]:
    """Return a JSON-serializable snapshot of the refresh state."""
    return asdict(_STATE)


def reset_state_for_test() -> None:
    """Test-only: clear refresh state back to idle."""
    global _STATE
    _STATE = RefreshState()


async def start_refresh(
    app: FastAPI,
    settings: Any,
    *,
    force: bool,
    period_end: date | None = None,
) -> dict[str, Any]:
    """Kick off a 13F refresh in a worker thread. Non-blocking.

    Returns the resulting state dict so the caller (route or lifespan) can
    react synchronously to the guard outcomes:

    - identity invalid → ``{"status": "error", "error": "identity_missing"}``
      (no work spawned; user must configure SEC identity first)
    - already running → current running state (idempotent — no double run)
    - ``force=False`` and cache fresh (latest period within 60 days) →
      ``{"status": "done", ...}`` (skip; nothing to do)
    - otherwise → ``{"status": "running", ...}`` and the parse proceeds in a
      tracked background task (registered into ``app.state.background_tasks``
      so lifespan shutdown cancels it cleanly — no leaked thread on quit)
    """
    from finrobot.engine.data.providers.edgar_provider import (
        _is_valid_identity,
        _sec_header_identity,
    )
    from finrobot.engine.data.sec_holdings_cache import cache_status, is_period_complete
    from scripts.refresh_sec_holdings import _latest_completed_quarter_end

    async with _LOCK:
        if _STATE.status == "running":
            return asdict(_STATE)

        header_identity = _sec_header_identity(settings.sec_user_agent)
        if not _is_valid_identity(settings.sec_user_agent) or header_identity is None:
            _STATE.status = "error"
            _STATE.error = "identity_missing"
            _STATE.finished_at = datetime.now(tz=timezone.utc).isoformat()
            logger.info("SEC 13F holdings refresh skipped: SEC identity not configured")
            return asdict(_STATE)

        target = period_end or _latest_completed_quarter_end()

        if not force:
            status = await cache_status()
            latest_raw = status.get("latest_period_end")
            if latest_raw:
                latest = date.fromisoformat(str(latest_raw))
                # Skip only when the cache already holds the newest quarter that
                # EXISTS *and that quarter's refresh actually FINISHED*. 13F-HR for
                # a quarter aren't filed until ~45 days after it ends, so for ~half
                # of every quarter the latest *available* quarter is already >60
                # days old. A naive "cache younger than 60 days" window therefore
                # re-pulls a quarter we hold in full on every boot (1-2h of wasted
                # SEC traffic). Compare against the latest *completed* quarter
                # instead: if we're not behind it, there is nothing newer to fetch.
                #
                # The completion-marker check is the second half: a quarter can be
                # PRESENT but PARTIAL (an interrupted / --max-filings-capped run
                # ingested only the newest-filed slice, dropping early filers like
                # BlackRock and the Vanguard sub-entities). Without it "has rows for
                # the latest quarter" was read as "complete" and the partial cache
                # froze forever. Re-fetch a present-but-incomplete quarter.
                if latest >= target and await is_period_complete(target):
                    _STATE.status = "done"
                    _STATE.summary = status
                    logger.info(
                        "SEC 13F holdings refresh skipped: cache already at "
                        "latest available quarter %s",
                        latest.isoformat(),
                    )
                    return asdict(_STATE)

        period = target

        # Transition to running under the lock BEFORE spawning so a racing
        # caller (manual click during startup auto-refresh) sees "running"
        # and bails at the guard above instead of starting a second parse.
        _STATE.status = "running"
        _STATE.period_end = period.isoformat()
        _STATE.started_at = datetime.now(tz=timezone.utc).isoformat()
        _STATE.finished_at = None
        _STATE.error = None
        _STATE.summary = None

        task = asyncio.create_task(_run(period, header_identity))
        # Register for cooperative cancellation at lifespan shutdown. Without
        # this the worker thread races the loop teardown and emits noisy
        # "Event loop is closed" warnings on every Tauri quit / pytest run.
        tasks = getattr(app.state, "background_tasks", None)
        if isinstance(tasks, list):
            tasks.append(task)

        return asdict(_STATE)


async def _run(period: date, header_identity: str) -> None:
    """Worker: set EDGAR identity, parse the quarter off-loop, record result."""
    from edgar import set_identity

    from scripts.refresh_sec_holdings import _refresh_quarter

    try:
        set_identity(header_identity)
        logger.info("SEC 13F holdings refresh starting: period_end=%s", period.isoformat())
        # _refresh_quarter is declared async but its core is a *synchronous*
        # edgartools parse of an entire quarter of 13F filings that blocks
        # between awaits. Running it on the server loop would freeze every
        # concurrent request. asyncio.to_thread(asyncio.run, ...) gives the
        # parse its own loop on a worker thread (red line: tests/audit/
        # test_architecture.py::TestEventLoopNotBlocked).
        summary = await asyncio.to_thread(asyncio.run, _refresh_quarter(period))
        _STATE.status = "done"
        _STATE.summary = summary
        logger.info("SEC 13F holdings refresh complete: %s", summary)
    except asyncio.CancelledError:
        _STATE.status = "idle"
        _STATE.error = None
        raise
    except (ImportError, OSError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
        _STATE.status = "error"
        _STATE.error = str(exc)
        logger.exception("SEC 13F holdings refresh failed — non-fatal")
    finally:
        _STATE.finished_at = datetime.now(tz=timezone.utc).isoformat()
