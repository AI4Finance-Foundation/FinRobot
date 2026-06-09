"""Project a :class:`CoverageOverview` into LLM-facing watchlist text.

Two render targets, one row vocabulary:

* :func:`format_coverage_snapshot` — the **per-turn system-context block** the
  chat handler injects every turn (header + caliber note + deterministically
  pre-computed movers). The assistant answers portfolio-level questions and
  surfaces anomalies from this without any tool call.
* :func:`format_coverage_for_tool` — the **on-demand tool result** returned by
  the orchestrator's ``query_coverage_universe`` (the user asked for it, so no
  framing preamble — just the listing).

Both share :func:`_format_row`, so the row caliber (live-upside denominator,
``[stale]`` marker, ``?`` for absent cells) is defined in exactly one place.
The anomaly call-outs are computed HERE in Python — the护城河 is deterministic
numbers; the LLM narrates them, it does not decide what counts as a "mover".
"""

from __future__ import annotations

from finrobot.coverage.models import CoverageOverview, CoverageRow

# How many rows to spell out line-by-line in the per-turn snapshot before
# truncating to a count, so the injected block stays bounded (≤ ~30 lines even
# for a 100-ticker desk). Movers flagged below are always listed, so a truncated
# tail never hides an anomaly. The on-demand tool listing is NOT capped — the
# user explicitly asked to see the universe.
_SNAPSHOT_MAX_ROWS = 20


def _fmt_price(price: float | None, currency: str | None) -> str:
    """A price with its quote currency, or ``?`` when absent (never a fake 0)."""
    if price is None:
        return "?"
    ccy = f" {currency}" if currency else ""
    return f"{price:,.2f}{ccy}"


def _fmt_pct_points(value: float | None) -> str:
    """Format a value already in percentage POINTS (e.g. 1.2 → ``+1.2%``).

    ``CoverageRow.change_pct_1d`` is produced by
    ``NormalizedPrices.latest_session_change`` as ``change / prev_close * 100``,
    so it is already a percentage — never multiply it again.
    """
    return f"{value:+.1f}%" if value is not None else "?"


def _fmt_fraction_pct(value: float | None) -> str:
    """Format a FRACTION (e.g. 0.153 → ``+15.3%``).

    Used for ``upside_to_target_live`` = ``(target − price) / price``, a raw ratio
    on the LIVE price — distinct from the report's entry-based ``upside``. The ×100
    happens here so the two are never confused at the call sites.
    """
    return f"{value * 100:+.1f}%" if value is not None else "?"


def _format_row(row: CoverageRow) -> str:
    """One compact watchlist line: ticker · price · 1d · verdict · target · upside · signal.

    Only populated fields render — a missing cell shows ``?`` rather than a
    fabricated value, and absent research (no verdict/target/upside/signal) is
    simply omitted so a never-researched name stays terse. ``[stale]`` marks a
    last-known cached price (not live).
    """
    stale = " [stale]" if row.market_stale else ""
    parts = [
        f"- {row.ticker}: {_fmt_price(row.price, row.currency)}{stale}",
        f"1d {_fmt_pct_points(row.change_pct_1d)}",
    ]
    if row.latest_verdict:
        parts.append(f"verdict {row.latest_verdict}")
    if row.target_price is not None:
        parts.append(f"target {row.target_price:,.2f}")
    if row.upside_to_target_live is not None:
        parts.append(f"upside {_fmt_fraction_pct(row.upside_to_target_live)}")
    if row.signal:
        parts.append(f"signal {row.signal}")
    if row.market_implied is not None:
        # The reverse-DCF *classification* of what the live price implies
        # (fundamental / option_value / near_ceiling) — just the kind; the full
        # implied-growth/WACC detail is for the desk UI, not the chat prompt.
        parts.append(f"implied {row.market_implied.kind}")
    return " · ".join(parts)


def _movers(rows: list[CoverageRow], change_threshold: float) -> list[CoverageRow]:
    """Names whose |1-day move| meets the threshold (both in percentage POINTS)."""
    return [
        r for r in rows if r.change_pct_1d is not None and abs(r.change_pct_1d) >= change_threshold
    ]


def _below_target(rows: list[CoverageRow]) -> list[CoverageRow]:
    """Names where the live price has passed the report's target (upside < 0)."""
    return [r for r in rows if r.upside_to_target_live is not None and r.upside_to_target_live < 0]


def format_coverage_snapshot(overview: CoverageOverview, *, change_threshold: float) -> str | None:
    """The per-turn system-context watchlist block (header + caliber + movers).

    Deterministic by construction: the mover / below-target call-outs are
    computed here (a name is a "mover" iff ``abs(change_pct_1d) >=
    change_threshold``; "below target" iff ``upside_to_target_live < 0``) — never
    delegated to the LLM. Returns ``None`` for an empty group so the caller
    injects nothing.
    """
    rows = overview.rows
    if not rows:
        return None

    lines: list[str] = [
        f"User's watchlist ({overview.group_name}) — system-supplied context this "
        "turn, deterministically computed, NOT from a tool call:",
        "Caliber: 1d = 1-day % move. upside = (target − live price) / live price "
        "(LIVE-price denominator; this is NOT the report's entry-based upside — "
        "never mix the two). [stale] = last-known cached price, not live; quote a "
        "live price before citing it as the current price.",
    ]

    for row in rows[:_SNAPSHOT_MAX_ROWS]:
        lines.append(_format_row(row))
    if len(rows) > _SNAPSHOT_MAX_ROWS:
        lines.append(f"… and {len(rows) - _SNAPSHOT_MAX_ROWS} more (ask to see all).")

    movers = _movers(rows, change_threshold)
    if movers:
        flagged = ", ".join(f"{r.ticker} {_fmt_pct_points(r.change_pct_1d)}" for r in movers)
        # Movers are listed as DATA only. The behavioural policy — surface these
        # in a conversational reply, NEVER woven into a single-ticker report body
        # — lives in engine/instructions.md. An unconditional "proactively call
        # these out" here leaked watchlist names (TSLA/AMD) into an AAPL deep-dive.
        lines.append(f"⚠ Movers today (|1d| ≥ {change_threshold:.0f}%): {flagged}.")
    below = _below_target(rows)
    if below:
        names = ", ".join(f"{r.ticker} {_fmt_fraction_pct(r.upside_to_target_live)}" for r in below)
        lines.append(
            f"⚠ Live price past target (negative live upside): {names} — thesis may need a re-look."
        )

    return "\n".join(lines)


def format_coverage_for_tool(overview: CoverageOverview) -> str:
    """The on-demand ``query_coverage_universe`` tool result — a plain listing.

    No framing preamble (the user asked for the universe), but the same row
    caliber and the same deterministic mover/below-target call-outs as the
    snapshot, since the tool's whole point is to surface them on a fresh pull.
    Not row-capped — an explicit query should see every name. ``cache_only`` vs
    live is the caller's choice (the tool's ``refresh`` flag); this only renders.
    """
    rows = overview.rows
    if not rows:
        return "The user's watchlist is empty — no Studied Tickers yet."
    freshness = "last-known cache" if overview.cache_only else "live"
    lines: list[str] = [
        f"Watchlist ({overview.group_name}), {len(rows)} name(s), {freshness} snapshot. "
        "upside = (target − live price) / live price (live denominator, ≠ report entry upside)."
    ]
    lines.extend(_format_row(row) for row in rows)
    below = _below_target(rows)
    if below:
        names = ", ".join(f"{r.ticker} {_fmt_fraction_pct(r.upside_to_target_live)}" for r in below)
        lines.append(f"Live price past target: {names}.")
    return "\n".join(lines)
