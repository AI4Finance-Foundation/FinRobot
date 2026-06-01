"""Claim-entailment verifier for IC debate arguments (v1).

v1 rule: an argument is verified=True iff it cites at least one evidence_id
AND every cited id exists in the EvidenceSet.  Semantic NLI is deferred to v1.1.
"""

from __future__ import annotations

from typing import Literal

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
        source of allowed evidence_ids.

    Returns
    -------
    list[VerifiedArgument]
        Same order as *arguments*, each annotated with ``verified`` and
        ``reason``.
    """
    known: set[str] = set(evidence_set.by_id())
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
        else:
            results.append(
                VerifiedArgument(
                    side=side,
                    claim=arg.claim,
                    evidence_ids=arg.evidence_ids,
                    verified=True,
                    reason="引用证据均存在于确定性证据集",
                )
            )

    return results
