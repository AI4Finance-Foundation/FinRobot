"""One-shot backfill: rebuild valuation_synthesis on existing equity_research
artifacts and rewrite ``thesis.price_target`` + ``thesis.recommendation`` to
the deterministic values the new pipeline now enforces.

Before 2026-05-27 the thesis step let the LLM freelance both fields, so two
consecutive runs of the same TSLA pipeline returned $25.37 SELL one minute
and $57.96 SELL the next. The pipeline is now fixed (see
``_execute_thesis`` overrides) but existing artifacts on disk still carry
the drift. This script reads every equity_research artifact, recomputes
ValuationSynthesis from the persisted DCF + Comps inputs, and saves an
updated artifact in place.

Usage:
    uv run python -m scripts.backfill_thesis_deterministic [--dry-run]

Idempotent: artifacts that already match the deterministic values are
saved unchanged (no risk to re-run).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any

from finagent.artifact.store import ArtifactStore
from finagent.engine.compute.valuation_synthesis import synthesize_valuations
from finagent.engine.models.financial import (
    DCFResult,
    PeerComps,
    ThesisResult,
    ValuationMethod,
    ValuationSynthesis,
)
from finagent.engine.pipelines.equity_research import _verdict_from_upside

logger = logging.getLogger("backfill_thesis_deterministic")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def _rebuild_synthesis(
    structured: dict[str, Any],
    current_price: float,
) -> ValuationSynthesis | None:
    """Mirror of ``_helpers.build_valuation_synthesis`` but reads dicts.

    The pipeline-time helper takes typed Pydantic objects out of an in-
    memory pipeline context. Stored artifacts are JSON dicts so we re-hydrate
    via Pydantic ``model_validate`` and rerun the same code path.
    """
    methods: list[ValuationMethod] = []

    dcf_dict = structured.get("financial_modeling")
    if isinstance(dcf_dict, dict):
        try:
            dcf = DCFResult.model_validate(dcf_dict)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("  ↳ DCF revalidation failed: %s", exc)
        else:
            methods.append(
                ValuationMethod(
                    name="DCF",
                    low=dcf.implied_price * 0.8,
                    mid=dcf.implied_price,
                    high=dcf.implied_price * 1.2,
                    confidence=0.7,
                    source="Discounted Cash Flow model",
                )
            )

    peers_dict = structured.get("peer_analysis")
    if isinstance(peers_dict, dict):
        try:
            peers = PeerComps.model_validate(peers_dict)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("  ↳ PeerComps revalidation failed: %s", exc)
        else:
            if peers.median_ev_ebitda:
                target = peers.target
                if target.ebitda > 0 and target.market_cap > 0 and current_price > 0:
                    shares = target.market_cap / current_price
                    ev_from_peers = peers.median_ev_ebitda * target.ebitda
                    equity_from_peers = (
                        ev_from_peers - (target.total_debt - target.total_cash)
                    )
                    implied = equity_from_peers / shares if shares > 0 else 0
                    if implied > 0:
                        methods.append(
                            ValuationMethod(
                                name="EV/EBITDA Comps",
                                low=implied * 0.85,
                                mid=implied,
                                high=implied * 1.15,
                                confidence=0.5,
                                source=(
                                    f"Peer median EV/EBITDA "
                                    f"{peers.median_ev_ebitda:.1f}x"
                                ),
                            )
                        )

    if not methods or current_price <= 0:
        return None

    try:
        return synthesize_valuations(methods, current_price)
    except ValueError as exc:
        logger.warning("  ↳ synthesize_valuations failed: %s", exc)
        return None


async def backfill(*, dry_run: bool) -> None:
    store = ArtifactStore()
    summaries = await store.list_by_ticker(
        ticker=None, include_archived=True, limit=10_000
    )
    equity_summaries = [s for s in summaries if s.type == "equity_research"]
    logger.info(
        "Found %d equity_research artifacts (out of %d total)",
        len(equity_summaries),
        len(summaries),
    )

    n_rewritten = 0
    n_unchanged = 0
    n_skipped = 0

    for summary in equity_summaries:
        artifact = await store.get(summary.id)
        if artifact is None:
            logger.warning("%s: get() returned None — skipping", summary.id)
            n_skipped += 1
            continue
        structured = dict(artifact.outputs.structured)
        raw_market = artifact.inputs.raw_data.get("market", {})
        current_price = raw_market.get("current_price")
        if not isinstance(current_price, (int, float)) or current_price <= 0:
            logger.info("%s: no current_price in raw_data — skipping", summary.id)
            n_skipped += 1
            continue

        vs = _rebuild_synthesis(structured, float(current_price))
        if vs is None:
            logger.info("%s: could not build synthesis — skipping", summary.id)
            n_skipped += 1
            continue

        canonical_target = round(vs.weighted_price, 2)
        canonical_verdict = _verdict_from_upside(vs.upside_downside)
        method_breakdown = ", ".join(
            f"{m.name}=${m.mid:.2f}(c={m.confidence:.2f})" for m in vs.methods
        )
        canonical_basis = (
            f"Confidence-weighted mean of {len(vs.methods)} methods: "
            f"{method_breakdown} → ${canonical_target:.2f}"
        )

        # Compare with existing thesis to know whether anything actually changes.
        thesis_dict = structured.get("thesis")
        if not isinstance(thesis_dict, dict):
            logger.info("%s: no thesis block — skipping", summary.id)
            n_skipped += 1
            continue

        try:
            thesis = ThesisResult.model_validate(thesis_dict)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("%s: thesis revalidation failed (%s) — skipping", summary.id, exc)
            n_skipped += 1
            continue

        existing_synthesis = structured.get("valuation_synthesis")
        target_unchanged = abs(thesis.price_target - canonical_target) < 0.01
        verdict_unchanged = (
            thesis.recommendation.strip().upper() == canonical_verdict
        )
        synthesis_present = existing_synthesis is not None
        if target_unchanged and verdict_unchanged and synthesis_present:
            n_unchanged += 1
            continue

        # Build the updated artifact.
        updated_thesis = thesis.model_copy(
            update={
                "price_target": canonical_target,
                "price_target_basis": canonical_basis,
                "recommendation": canonical_verdict,
            }
        )
        structured["thesis"] = updated_thesis.model_dump(mode="json")
        structured["valuation_synthesis"] = vs.model_dump(mode="json")
        updated_outputs = artifact.outputs.model_copy(update={"structured": structured})
        updated_artifact = artifact.model_copy(update={"outputs": updated_outputs})

        logger.info(
            "%s [%s]: price_target %.2f→%.2f, verdict %s→%s, synthesis %s",
            summary.id,
            summary.ticker,
            thesis.price_target,
            canonical_target,
            thesis.recommendation,
            canonical_verdict,
            "added" if not synthesis_present else "refreshed",
        )

        if not dry_run:
            await store.save(updated_artifact)
        n_rewritten += 1

    logger.info(
        "Done. rewritten=%d unchanged=%d skipped=%d (dry_run=%s)",
        n_rewritten,
        n_unchanged,
        n_skipped,
        dry_run,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing to the SQLite store.",
    )
    args = parser.parse_args()
    asyncio.run(backfill(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
