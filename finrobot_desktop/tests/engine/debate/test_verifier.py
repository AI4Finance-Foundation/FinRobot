"""Tests for claim-entailment verifier.

Verified=True requires all three: at least one evidence_id cited, every cited
id exists in the EvidenceSet, and every monetary amount written in the claim
text restates a $-denominated deterministic value (or the current price).
Semantic NLI stays deferred.
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
            ),
            Evidence(
                evidence_id="method.DCF.mid",
                label="DCF 中值估值",
                value=173.21,
                unit="$",
            ),
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


def test_fabricated_amount_with_real_citation_flagged() -> None:
    """A real evidence_id must not launder a fabricated number in the claim text."""
    args = [
        Argument(
            claim="DCF 中值高达 $999.99,严重高估",
            evidence_ids=["method.DCF.mid"],
        )
    ]
    out = verify_arguments("bear", args, _es())
    assert out[0].verified is False
    assert "$999.99" in out[0].reason


def test_amount_restating_cited_evidence_passes() -> None:
    args = [Argument(claim="DCF 中值 $173.21,上行充足", evidence_ids=["method.DCF.mid"])]
    out = verify_arguments("bull", args, _es())
    assert out[0].verified is True


def test_display_rounding_within_tolerance_passes() -> None:
    """$173 vs 173.21 is a display rounding (0.12%), not drift."""
    args = [Argument(claim="DCF 中值约 $173", evidence_ids=["method.DCF.mid"])]
    out = verify_arguments("bull", args, _es())
    assert out[0].verified is True


def test_current_price_amount_endorsed() -> None:
    args = [Argument(claim="现价 $200 已计入利好", evidence_ids=["method.DCF.mid"])]
    out = verify_arguments("bear", args, _es())
    assert out[0].verified is True


def test_percent_evidence_does_not_endorse_dollar_amount() -> None:
    """unit='%' value -0.18 must not back a '$0.18' claim — units are not fungible."""
    args = [
        Argument(
            claim="每股仅值 $0.18",
            evidence_ids=["synthesis.upside_downside"],
        )
    ]
    out = verify_arguments("bear", args, _es())
    assert out[0].verified is False


def test_suffixed_fabricated_amount_flagged() -> None:
    """'USD 150B' scales to 1.5e11 — nothing in the set endorses it."""
    args = [Argument(claim="市值将蒸发 USD 150B", evidence_ids=["method.DCF.mid"])]
    out = verify_arguments("bear", args, _es())
    assert out[0].verified is False


def test_suffixed_amount_matching_evidence_scales_and_passes() -> None:
    """'USD 150B' must scale to 1.5e11 BEFORE matching — a $-leaf at that
    magnitude endorses it; comparing the raw '150' against 1.5e11 would not."""
    es = _es()
    es.items.append(
        Evidence(evidence_id="synthesis.implied_ev", label="隐含 EV", value=1.5e11, unit="$")
    )
    args = [Argument(claim="隐含 EV 约 USD 150B", evidence_ids=["synthesis.implied_ev"])]
    out = verify_arguments("bull", args, es)
    assert out[0].verified is True


def test_negative_dollar_evidence_endorses_its_magnitude() -> None:
    """The amount regex captures sign-less digits, so a negative $-leaf
    (e.g. per-share net-debt drag of -15.33) must endorse '$15.33' via abs()."""
    es = _es()
    es.items.append(
        Evidence(evidence_id="method.NAV.net_debt_ps", label="每股净债", value=-15.33, unit="$")
    )
    args = [Argument(claim="每股净债拖累 $15.33", evidence_ids=["method.NAV.net_debt_ps"])]
    out = verify_arguments("bear", args, es)
    assert out[0].verified is True
