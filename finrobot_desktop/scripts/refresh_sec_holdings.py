"""13F holdings reverse-index refresh job.

Downloads every 13F-HR filed in a quarter, normalises each filer's
holdings DataFrame, writes rows into ``~/.finrobot/sec_holdings_cache.db``
keyed by (cusip, holder_cik, period_end, title_of_class).

Run cadence:
  13F-HR are due 45 days after quarter end. The lifespan background task
  (``finrobot.server.py`` ``_refresh_sec_holdings_background``) calls this
  for the most recent completed quarter, and a quarterly cron / manual run
  refreshes when needed.

Usage:
    EDGAR_IDENTITY="Name email@domain" \
        uv run python -m scripts.refresh_sec_holdings --period 2026-03-31

    uv run python -m scripts.refresh_sec_holdings \
        --period 2026-03-31 --identity "Name email@domain"

    # latest completed quarter:
    uv run python -m scripts.refresh_sec_holdings --latest

Idempotent: PRIMARY KEY upsert in sec_holdings_cache.bulk_upsert_holdings.

NOTE: This script's 13F XML parsing path depends on edgartools 5.31.5's
``ThirteenF.holdings`` DataFrame schema, which emits **PascalCase** columns
``['Issuer', 'Class', 'Cusip', 'Ticker', 'SharesPrnAmount', 'Value', ...]``
(confirmed by inspecting ``edgar.thirteenf.ThirteenF.holdings`` source).
We lowercase the columns on ingest (``rename(columns=str.lower)``) so the
rest of the code is casing-agnostic, then read the lowercased names. If a
future edgartools renames a column outright (not just recases it), the
schema gate logs + skips and emits a structured warning so the cache stays
consistent until the mapping is fixed.

edgartools' ``holdings.Value`` is already in **whole US dollars** for every
filing era: ``ThirteenF.infotable`` internally converts pre-Q4-2022
thousands values to dollars (``if self._value_in_thousands: Value *= 1000``).
So we do NOT multiply by 1000 here — doing so would overstate every position
1000x (verified: Berkshire's Apple stake reads 57,843,260,493 = $57.8B, not
$57.8T).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from datetime import date
from typing import Any

logger = logging.getLogger("refresh_sec_holdings")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _opt_number(value: Any) -> float | None:
    """Parse a 13F numeric cell to float; missing/NaN/unparseable → None.

    The holdings DataFrame can surface a cell as None, an empty string, a
    pandas/numpy NaN, or a comma-formatted string. ``float("nan")`` succeeds and
    ``int(nan)`` raises, so a bare ``float(... or 0)`` both masked NaN as a real
    number and fabricated 0 for genuinely-missing cells. None ≠ 0: a missing
    share count or value is a parse gap the caller must drop, not a $0 holding.
    """
    if value is None or value == "":
        return None
    try:
        num = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    if num != num:  # NaN (NaN is the only value not equal to itself)
        return None
    return num


# edgartools 5.31.5 ThirteenF.holdings emits PascalCase columns
# ['Issuer', 'Class', 'Cusip', 'Ticker', 'SharesPrnAmount', 'Value', ...].
# We rename(columns=str.lower) on ingest, so the gate checks the LOWERCASED
# names below. If a column is missing we log + skip the filing (don't crash).
_EXPECTED_COLUMNS = {
    "cusip",
    "issuer",
    "class",
    "sharesprnamount",
    "value",
}


def _latest_completed_quarter_end(today: date | None = None) -> date:
    """13F-HR are filed 45 days after quarter end. We pull whatever
    quarter is fully reported by the time this runs."""
    today = today or date.today()
    # If today is at least 46 days past most recent quarter end, that quarter is ready.
    candidates = [
        date(today.year, 3, 31),
        date(today.year, 6, 30),
        date(today.year, 9, 30),
        date(today.year, 12, 31),
        date(today.year - 1, 12, 31),
    ]
    candidates = [q for q in candidates if q < today and (today - q).days >= 46]
    return max(candidates) if candidates else date(today.year - 1, 12, 31)


def _normalise_holding_row(
    df_row: dict[str, Any],
    *,
    filer_name: str,
    filer_cik: str | None,
    filing_date: date,
    accession_no: str,
    period_end: date,
) -> dict[str, Any] | None:
    """Map a single ThirteenF.holdings DataFrame row to our cache schema.

    Returns None when required columns are missing (logged, not crashed).
    """
    try:
        cusip = str(df_row.get("cusip") or "").strip()
        if not cusip:
            return None
        # None ≠ 0 (CLAUDE.md invariant): a 13F InfoTable row missing its share
        # count or its value is a parse gap, NOT a real 0-share / $0 position.
        # Per SEC 13F-HR rules every reported security carries both SHARES (or
        # principal amount) and VALUE > 0; a 0 in either field never describes a
        # genuine holding. Coercing missing→0 would fabricate phantom $0 holders
        # that sort to the bottom and pollute the ownership table. The cache
        # schema requires non-null shares/value_usd (and the model
        # InstitutionalHolding has no None branch for them), so the only honest
        # handling of a degenerate row is to drop it rather than store a 0.
        shares = _opt_number(df_row.get("sharesprnamount"))
        value = _opt_number(df_row.get("value"))
        if shares is None or value is None:
            logger.warning(
                "skip 13F row with missing shares/value (cusip=%s holder=%s): shares=%r value=%r",
                cusip,
                filer_name,
                df_row.get("sharesprnamount"),
                df_row.get("value"),
            )
            return None
        return {
            # ticker stays nullable because SEC 13F XML identifies securities
            # by CUSIP + issuer name, not ticker. The cache lookup uses ticker
            # first, then issuer-name normalisation against the company's SEC
            # legal name, so rows remain queryable without a licensed CUSIP map.
            "ticker": None,
            "cusip": cusip,
            # Lowercased edgartools names: Issuer->issuer, Class->class,
            # SharesPrnAmount->sharesprnamount, Value->value.
            "name_of_issuer": str(df_row.get("issuer") or ""),
            "title_of_class": str(df_row.get("class") or "COM"),
            "holder_name": filer_name,
            "holder_cik": filer_cik,
            "shares": int(shares),
            # edgartools' Value is already whole US dollars (it normalises
            # pre-Q4-2022 thousands internally). NO ×1000 here — that would
            # overstate every position 1000x.
            "value_usd": float(value),
            "period_end": period_end,
            "filing_date": filing_date,
            "accession_no": accession_no,
        }
    except (ValueError, TypeError, KeyError) as e:
        logger.warning("skip malformed 13F row (%s): %r", e, df_row)
        return None


async def _refresh_quarter(period_end: date, *, max_filings: int | None = None) -> dict[str, Any]:
    """Pull all 13F-HR filed in the quarter and upsert rows into cache.

    ``max_filings`` caps total filers processed (useful for first-time
    bootstrap or rate-limit-sensitive dev runs). None = process all.
    """
    from edgar import get_filings  # local import: scripts shouldn't fail to load
    from finrobot.engine.data.sec_holdings_cache import (
        bulk_upsert_holdings,
        cache_status,
        mark_period_complete,
    )

    logger.info(
        "refreshing 13F holdings for period_end=%s (max_filings=%s)", period_end, max_filings
    )

    # 13F-HR filings whose period_of_report == this quarter end. EdgarTools
    # exposes `get_filings(form="13F-HR")` — we filter by period_of_report
    # after the fact since the API doesn't support that filter directly.
    filings_iter = get_filings(form="13F-HR")
    rows_inserted = 0
    filings_processed = 0
    filings_skipped_schema = 0
    skipped_schema_examples: list[str] = []

    for f in filings_iter:
        if max_filings is not None and filings_processed >= max_filings:
            break

        # Filter to target period (filings reporting other quarters are skipped)
        f_period = getattr(f, "period_of_report", None)
        if f_period is None:
            continue
        if isinstance(f_period, str):
            try:
                f_period_d = date.fromisoformat(f_period)
            except ValueError:
                continue
        else:
            f_period_d = f_period
        if f_period_d != period_end:
            continue

        try:
            thirteenf = f.obj()
            holdings_df = getattr(thirteenf, "holdings", None)
            if holdings_df is None:
                continue
            # edgartools 5.31.5 emits PascalCase columns (Issuer, Cusip,
            # SharesPrnAmount, Value, ...). Lowercase them so the rest of the
            # code is casing-agnostic and the schema gate / row mapping below
            # read stable lowercased names.
            holdings_df = holdings_df.rename(columns=str.lower)
            cols = set(getattr(holdings_df, "columns", []))
            missing = _EXPECTED_COLUMNS - cols
            if missing:
                filings_skipped_schema += 1
                if len(skipped_schema_examples) < 5:
                    skipped_schema_examples.append(f"{f.accession_no} missing {sorted(missing)}")
                continue
            normalised_rows: list[dict[str, Any]] = []
            for record in holdings_df.to_dict("records"):
                row = _normalise_holding_row(
                    record,
                    filer_name=str(getattr(f, "company", "") or ""),
                    filer_cik=str(getattr(f, "cik", "")) or None,
                    filing_date=f.filing_date,
                    accession_no=f.accession_no,
                    period_end=period_end,
                )
                if row is not None:
                    normalised_rows.append(row)
            if normalised_rows:
                rows_inserted += await bulk_upsert_holdings(normalised_rows)
            filings_processed += 1
            if filings_processed % 50 == 0:
                logger.info(
                    "processed %d filings, %d rows inserted so far",
                    filings_processed,
                    rows_inserted,
                )
        except (OSError, RuntimeError, ValueError, TypeError, AttributeError, KeyError) as e:
            logger.exception("13F %s failed: %s", getattr(f, "accession_no", "?"), e)

    if filings_skipped_schema:
        logger.warning(
            "skipped %d 13F filings with unexpected holdings schema; examples=%s",
            filings_skipped_schema,
            skipped_schema_examples,
        )

    # Mark the quarter complete ONLY on a full (uncapped) run that reached the end
    # of the filings iterator. A ``max_filings`` dev/bootstrap run is deliberately
    # partial, so it must NOT set the marker — otherwise the freshness guard would
    # treat a capped slice as the full quarter and never backfill the early filers
    # (BlackRock / Vanguard sub-entities file on/near the deadline day).
    if max_filings is None:
        await mark_period_complete(period_end, filings_processed)

    status = await cache_status()
    return {
        "period_end": period_end.isoformat(),
        "filings_processed": filings_processed,
        "filings_skipped_schema": filings_skipped_schema,
        "rows_inserted": rows_inserted,
        "complete": max_filings is None,
        "cache_status_after": status,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--period", help="Quarter end ISO date, e.g. 2026-03-31")
    group.add_argument(
        "--latest",
        action="store_true",
        help="Most recent completed quarter (45+ days past period end)",
    )
    parser.add_argument(
        "--max-filings", type=int, default=None, help="Cap total 13F filings processed (dev only)"
    )
    parser.add_argument(
        "--identity",
        default=None,
        help="SEC EDGAR identity. Overrides EDGAR_IDENTITY when provided.",
    )
    args = parser.parse_args()

    identity = (args.identity or os.environ.get("EDGAR_IDENTITY", "")).strip()
    if not identity or " " not in identity or "@" not in identity:
        logger.error("EDGAR_IDENTITY env var required (format: 'Name email@domain')")
        return 2

    from edgar import set_identity

    set_identity(identity)

    if args.latest:
        period = _latest_completed_quarter_end()
    else:
        period = date.fromisoformat(args.period)

    summary = asyncio.run(_refresh_quarter(period, max_filings=args.max_filings))
    logger.info("done: %s", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
