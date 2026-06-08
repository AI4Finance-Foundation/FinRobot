"""Nightly historical scan of the output-contract clauses over EVERY persisted
artifact (spec §6 step 5; §4.5 item 3 / Q3).

Walks the whole ~/.finrobot/artifacts.db, runs each contract clause's pure
``check()`` against every already-stored artifact, and reports — per clause — how
many artifacts in history today's clauses would flag for REVIEW. Two operational
uses:

  1. Before promoting a NEW clause to the live persist gate, quantify how much
     existing stock it would withhold — a clause that REVIEWs 40% of the back
     catalogue is over-broad and gets re-calibrated before it ever ships.
  2. Regression monitoring: a release that spikes the historical violation rate
     is an output-layer regression (the clause set drifted, or an extractor
     changed what the clause reads), caught here rather than in production.

READ-ONLY by construction. The artifact is fetched via the store's public read
API (``list_by_ticker`` + ``get``) and each clause's ``check(artifact)`` is a
PURE function (contract.py design contract: zero I/O, no mutation). The script
NEVER calls ``store.save`` / ``enforce_artifact_contract`` (which mutates) /
``delete`` / ``mark_viewed`` — nothing here writes the db back.

The per-flag rows are the human-review payload, shaped like a dbt
``store_failures`` table: one row per (clause, artifact) violation carrying the
identity + headline/basis snapshot + the clause's own evidence string, grouped
by clause so a reviewer reads one clause's full catch list at a time.

Usage:
    python scripts/scan_artifact_contract.py                # scan all, all clauses
    python scripts/scan_artifact_contract.py --clause C1    # only the C1 catch list
    python scripts/scan_artifact_contract.py --limit 50     # sample the newest 50
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass

from finrobot.artifact.contract import CONTRACT_CLAUSES, ContractClause
from finrobot.artifact.models import Artifact, ArtifactSummary
from finrobot.artifact.store import ArtifactStore
from finrobot.artifact.summary_extractor import (
    extract_entry_price,
    extract_target_price,
    extract_verdict,
)

# list_by_ticker caps at ``limit`` rows; an unbounded scan must lift that cap
# above the real row count. count() is itself uncapped, so we derive the page
# size from the live total plus a generous margin — never a bare magic literal
# that silently truncates once the store grows past it.
_LIMIT_MARGIN = 1000


@dataclass(frozen=True)
class Flag:
    """One (clause, artifact) violation — a dbt ``store_failures`` row."""

    clause_id: str
    severity: str
    artifact_id: str
    artifact_type: str
    ticker: str | None
    entry_price: float | None
    target_price: float | None
    verdict: str | None
    evidence: str


async def _enumerate_artifacts(store: ArtifactStore, limit: int | None) -> list[Artifact]:
    """Every persisted artifact, newest first, INCLUDING archived ones.

    A historical scan must see the full back catalogue, so ``include_archived``
    is always True (archive is a UI-staleness flag, not a deletion — an archived
    artifact still shipped a headline and still counts toward "how much stock a
    clause would have caught"). ``list_by_ticker`` returns the lean summaries;
    ``get`` rehydrates the full payload the clauses read. When ``limit`` is set
    we sample only the newest N (list_by_ticker already orders created_at DESC);
    otherwise we lift the page cap above the live total via count().
    """
    if limit is not None:
        page = limit
    else:
        # Uncapped scan: page must exceed the true row count or list_by_ticker
        # silently drops the oldest rows past its LIMIT.
        page = await store.count(include_archived=True) + _LIMIT_MARGIN

    summaries: list[ArtifactSummary] = await store.list_by_ticker(
        include_archived=True, limit=max(page, 1)
    )

    artifacts: list[Artifact] = []
    for summary in summaries:
        artifact = await store.get(summary.id)
        if artifact is None:
            # Corrupt / unparseable payload — store.get already logged it. Skip
            # rather than crash the whole scan on one bad row.
            print(f"  [skip] {summary.id}: payload unreadable", file=sys.stderr)
            continue
        artifacts.append(artifact)
    return artifacts


def _scan(artifacts: list[Artifact], clauses: list[ContractClause]) -> list[Flag]:
    """Run each clause's pure check over each artifact, collecting violations.

    Attributes every flag to the SPECIFIC clause that fired — which is why we
    call ``clause.check`` directly rather than ``enforce_artifact_contract``
    (the latter would (a) mutate and (b) collapse all hard violations into one
    withhold, losing per-clause attribution).
    """
    flags: list[Flag] = []
    for artifact in artifacts:
        for clause in clauses:
            finding = clause.check(artifact)
            if finding is None:
                continue
            flags.append(
                Flag(
                    clause_id=clause.id,
                    severity=clause.severity,
                    artifact_id=artifact.id,
                    artifact_type=artifact.type,
                    ticker=artifact.ticker,
                    entry_price=extract_entry_price(artifact),
                    target_price=extract_target_price(artifact),
                    verdict=extract_verdict(artifact),
                    evidence=finding.evidence,
                )
            )
    return flags


def _fmt_price(value: float | None) -> str:
    return f"${value:,.2f}" if value is not None else "—"


def _report(total: int, clauses: list[ContractClause], flags: list[Flag]) -> None:
    """Stdout report: scan summary, per-clause rate, then grouped catch lists."""
    print("=" * 78)
    print("Output-contract historical scan")
    print("=" * 78)
    print(f"artifacts scanned : {total}")
    print(f"clauses applied   : {', '.join(c.id for c in clauses) or '(none)'}")
    print(f"total flags       : {len(flags)}")
    print()

    if total == 0:
        print("No artifacts in store — nothing to scan.")
        return

    print("Per-clause flag rate")
    print("-" * 78)
    print(f"{'clause':<8}{'sev':<5}{'flags':>7}{'rate':>10}")
    for clause in clauses:
        count = sum(1 for f in flags if f.clause_id == clause.id)
        pct = 100.0 * count / total
        print(f"{clause.id:<8}{clause.severity:<5}{count:>7}{pct:>9.1f}%")
    print()

    if not flags:
        print("No clause flagged any artifact — the back catalogue is clean.")
        return

    print("Catch lists (human-review payload, grouped by clause)")
    print("=" * 78)
    for clause in clauses:
        clause_flags = [f for f in flags if f.clause_id == clause.id]
        if not clause_flags:
            continue
        print(f"\n── {clause.id} (severity {clause.severity}) — {len(clause_flags)} flag(s) ──")
        for flag in clause_flags:
            ticker = flag.ticker or "(cross)"
            print(f"  • {flag.artifact_id}")
            print(
                f"      type={flag.artifact_type}  ticker={ticker}  verdict={flag.verdict or '—'}"
            )
            print(
                f"      entry={_fmt_price(flag.entry_price)}  "
                f"target={_fmt_price(flag.target_price)}"
            )
            print(f"      evidence: {flag.evidence}")


def _select_clauses(clause_filter: str | None) -> list[ContractClause]:
    if clause_filter is None:
        return list(CONTRACT_CLAUSES)
    wanted = clause_filter.upper()
    selected = [c for c in CONTRACT_CLAUSES if c.id.upper() == wanted]
    if not selected:
        available = ", ".join(c.id for c in CONTRACT_CLAUSES)
        raise SystemExit(f"unknown clause {clause_filter!r}; available: {available}")
    return selected


async def _run(clause_filter: str | None, limit: int | None) -> int:
    clauses = _select_clauses(clause_filter)
    store = ArtifactStore()
    try:
        artifacts = await _enumerate_artifacts(store, limit)
    finally:
        await store.close()
    flags = _scan(artifacts, clauses)
    _report(len(artifacts), clauses, flags)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the output-contract clauses over every persisted artifact and "
            "report, per clause, how many would be flagged for REVIEW. READ-ONLY."
        )
    )
    parser.add_argument(
        "--clause",
        metavar="Cn",
        default=None,
        help="Restrict the scan to a single clause id (e.g. C1). Default: all clauses.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        metavar="N",
        default=None,
        help="Sample only the newest N artifacts. Default: scan the whole store.",
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be >= 1")
    return asyncio.run(_run(args.clause, args.limit))


if __name__ == "__main__":
    sys.exit(main())
