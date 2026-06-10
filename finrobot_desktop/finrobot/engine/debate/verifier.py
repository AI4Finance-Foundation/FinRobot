"""Claim-entailment verifier for IC debate arguments.

verified=True requires all three:
1. the argument cites at least one evidence_id;
2. every cited id exists in the EvidenceSet;
3. every monetary amount written in the claim text restates a $-denominated
   deterministic value (or the current price) within the shared narrative
   tolerance — a real citation must not launder a fabricated number sitting
   next to it in prose (ADR-0007: Argument carries zero numeric fields, so any
   un-endorsed amount in the claim is contraband by construction).

Semantic NLI (does the prose direction follow from the evidence) is deferred.
"""

from __future__ import annotations

from typing import Literal

from finrobot.engine.compute.operators.report_drift import detect_report_drift
from finrobot.engine.debate.models import Argument, EvidenceSet, VerifiedArgument


def verify_arguments(
    side: Literal["bull", "bear"],
    arguments: list[Argument],
    evidence_set: EvidenceSet,
) -> list[VerifiedArgument]:
    """Check each argument's evidence citations against the EvidenceSet.

    Parameters
    ----------
    side:
        Which side produced these arguments ("bull" or "bear").
    arguments:
        Agent-generated arguments.  Each may cite zero or more evidence_ids.
    evidence_set:
        Deterministic evidence produced by engine/compute; the authoritative
        source of allowed evidence_ids and of every amount a claim may print.

    Returns
    -------
    list[VerifiedArgument]
        Same order as *arguments*, each annotated with ``verified`` and
        ``reason``.
    """
    known: set[str] = set(evidence_set.by_id())
    # $-amounts in claims may only restate $-denominated evidence (cited or
    # not — mis-attribution is sloppiness, fabrication is the contract breach)
    # or the current price. Unit-aware on purpose: a WACC of 16.6 (%) does not
    # endorse a "$16.6" in prose.
    dollar_leaves = [e.value for e in evidence_set.items if e.unit == "$"]
    dollar_leaves.append(evidence_set.current_price)
    results: list[VerifiedArgument] = []

    for arg in arguments:
        if not arg.evidence_ids:
            results.append(
                VerifiedArgument(
                    side=side,
                    claim=arg.claim,
                    evidence_ids=arg.evidence_ids,
                    verified=False,
                    reason="无证据引用：论点未挂任何已算数字",
                )
            )
            continue

        dangling = [eid for eid in arg.evidence_ids if eid not in known]
        if dangling:
            results.append(
                VerifiedArgument(
                    side=side,
                    claim=arg.claim,
                    evidence_ids=arg.evidence_ids,
                    verified=False,
                    reason=f"引用了不存在的证据 id: {', '.join(dangling)}",
                )
            )
            continue

        # Same matcher as the report-side drift sink: relative tolerance vs
        # any leaf, so display roundings ($173 vs 173.21) pass and inventions
        # ($999.99) flag.
        drift = detect_report_drift(arg.claim, dollar_leaves)
        if drift.unmatched_count:
            tokens = ", ".join(f.token for f in drift.unmatched)
            results.append(
                VerifiedArgument(
                    side=side,
                    claim=arg.claim,
                    evidence_ids=arg.evidence_ids,
                    verified=False,
                    reason=f"claim 文本含证据集未背书的金额: {tokens}",
                )
            )
            continue

        results.append(
            VerifiedArgument(
                side=side,
                claim=arg.claim,
                evidence_ids=arg.evidence_ids,
                verified=True,
                reason="引用证据均存在且 claim 金额均有证据背书",
            )
        )

    return results
