from finrobot.engine.debate.models import Evidence, EvidenceSet, Argument


def test_argument_has_no_numeric_field():
    a = Argument(claim="估值偏贵", evidence_ids=["synthesis.upside_downside"])
    assert a.evidence_ids == ["synthesis.upside_downside"]
    assert not any(
        f.annotation in (float, int) for f in Argument.model_fields.values()
    ), "Argument 不得有任何数值字段——数字只能经 evidence_id 引用"


def test_evidence_set_by_id_lookup():
    es = EvidenceSet(
        ticker="NVDA",
        artifact_id="run-1",
        current_price=200.0,
        confidence="high",
        items=[
            Evidence(
                evidence_id="synthesis.upside_downside",
                label="加权隐含上行",
                value=-0.18,
                unit="%",
                formula_id="valuation_synthesis@v3",
                provenance={"provider": "computed"},
                period_basis="TTM",
            )
        ],
    )
    assert es.by_id()["synthesis.upside_downside"].value == -0.18
