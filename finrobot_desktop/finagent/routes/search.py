"""Global cmd+K search backend.

Routes:
  GET /api/search?q=<query>&limit=<int>
      → SearchResponse with typed results (ticker / slash_command / artifact / session)

  GET /api/search/sessions
      → list all sessions (newest first)

  GET /api/search/sessions/{session_id}/transcript
      → full JSONL event list for a single session

Routing logic for ``q``:
  - Looks like a ticker (``^[A-Z0-9.\\-]{1,10}$``) → emit ticker navigation suggestion
  - Starts with ``/``                               → parse as slash command (e.g. /dcf AAPL)
  - Otherwise                                        → substring search across artifacts + sessions
"""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

router = APIRouter()

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")

_SLASH_COMMANDS: dict[str, tuple[str, str]] = {
    "dcf": ("跑 DCF 估值", "需要 ticker"),
    "lbo": ("跑 LBO 分析", "需要 ticker"),
    "comps": ("跑同业对比", "需要 ticker"),
    "ddm": ("跑 DDM（银行）", "需要 ticker"),
    "earnings": ("分析财报质量", "需要 ticker"),
    "ic-memo": ("生成 IC Memo", "需要 ticker"),
    "skill": ("激活 Skill", "skill 名"),
}


class SearchResult(BaseModel):
    """A single search suggestion item."""

    kind: Literal["ticker", "slash_command", "artifact", "session"]
    title: str
    subtitle: str = ""
    action: str
    """Frontend action string:
      - ``navigate:/stocks/AAPL``
      - ``run:dcf:AAPL``
      - ``navigate:/library/AAPL?artifact=art_xxx``
      - ``navigate:/library?session=xxx``
    """
    score: float = 0.0


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _looks_like_ticker(q: str) -> bool:
    return bool(_TICKER_RE.match(q.upper()))


def _parse_slash_command(q: str) -> list[SearchResult]:
    """Parse ``/<cmd> [args]`` → SearchResult list."""
    parts = q[1:].split(maxsplit=1)
    if not parts:
        return []
    cmd = parts[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""
    if cmd not in _SLASH_COMMANDS:
        return []
    label, hint = _SLASH_COMMANDS[cmd]
    target_ticker = args.upper() if args else "??"
    subtitle = hint if not args else f"将运行 run_{cmd.replace('-', '_')}({target_ticker})"
    return [
        SearchResult(
            kind="slash_command",
            title=f"{label} {target_ticker}",
            subtitle=subtitle,
            action=f"run:{cmd}:{target_ticker}",
            score=8.0,
        )
    ]


def _matches(q: str, *fields: str) -> bool:
    """Case-insensitive substring match across any of the given fields."""
    ql = q.lower()
    return any(ql in (field or "").lower() for field in fields)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=SearchResponse)
async def search(
    request: Request,
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(20, ge=1, le=100),
) -> SearchResponse:
    """Global cmd+K search.

    Args:
        q: Search query.  Routing is based on shape of ``q`` (see module docstring).
        limit: Maximum number of results to return (1–100, default 20).

    Returns:
        ``SearchResponse`` with results sorted by descending score.
    """
    q_stripped = q.strip()
    results: list[SearchResult] = []

    # Branch 1: ticker pattern
    if _looks_like_ticker(q_stripped):
        results.append(
            SearchResult(
                kind="ticker",
                title=q_stripped.upper(),
                subtitle="打开 Stocks 页",
                action=f"navigate:/stocks/{q_stripped.upper()}",
                score=10.0,
            )
        )

    # Branch 2: slash command
    if q_stripped.startswith("/"):
        results.extend(_parse_slash_command(q_stripped))

    # Branch 3: free-text → artifacts + sessions
    artifact_store = getattr(request.app.state, "artifact_store", None)
    if artifact_store is not None:
        artifact_summaries = await artifact_store.list_by_ticker(
            ticker=None, limit=200, include_archived=False
        )
        for s in artifact_summaries:
            if _matches(q_stripped, s.ticker or "", str(s.type), s.headline):
                nav = (
                    f"navigate:/library/{s.ticker}?artifact={s.id}"
                    if s.ticker
                    else f"navigate:/library?artifact={s.id}"
                )
                results.append(
                    SearchResult(
                        kind="artifact",
                        title=f"{s.ticker or '跨ticker'} · {str(s.type).upper()}",
                        subtitle=s.headline,
                        action=nav,
                        score=2.0,
                    )
                )

    from finagent.audit.persistence import list_sessions

    sessions = list_sessions()
    for ss in sessions:
        if _matches(q_stripped, ss.title):
            results.append(
                SearchResult(
                    kind="session",
                    title=ss.title,
                    subtitle=f"{ss.turn_count} 条消息 · {ss.model}",
                    action=f"navigate:/library?session={ss.session_id}",
                    score=1.0,
                )
            )

    results.sort(key=lambda r: r.score, reverse=True)
    return SearchResponse(query=q_stripped, results=results[:limit])


