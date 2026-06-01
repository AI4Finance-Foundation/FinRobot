"""Tests for claim-entailment verifier (Task 3).

Verifier v1: evidence reference-existence only (no semantic NLI).
An argument is verified=True iff every cited evidence_id exists in the
EvidenceSet AND at least one is cited.
"""

from finrobot.engine.debate.models import Argument, Evidence, EvidenceSet
from finrobot.engine.debate.verifier import verify_arguments


def _es() -> EvidenceSet:
    return EvidenceSet(
        ticker="NVDA",
        artifact_id="r1",
        current_price=200,
        reliable=True,
        items=[
            Evidence(
                evidence_id="synthesis.upside_downside",
                label="x",
                value=-0.18,
                unit="%",
            )
        ],
    )


def test_grounded_argument_verified() -> None:
    args = [Argument(claim="隐含下行 18%", evidence_ids=["synthesis.upside_downside"])]
    out = verify_arguments("bear", args, _es())
    assert out[0].verified is True


def test_unsupported_claim_flagged_unverified() -> None:
    args = [Argument(claim="护城河无可撼动", evidence_ids=[])]
    out = verify_arguments("bull", args, _es())
    assert out[0].verified is False
    assert "无证据" in out[0].reason


def test_dangling_evidence_id_flagged() -> None:
    args = [Argument(claim="P/E 仅 10x", evidence_ids=["method.PE.mid"])]
    out = verify_arguments("bull", args, _es())
    assert out[0].verified is False
    assert "method.PE.mid" in out[0].reason
