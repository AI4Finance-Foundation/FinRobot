from __future__ import annotations

from datetime import date, datetime, timezone

from finrobot.artifact.builders import build_equity_research_artifact
from finrobot.engine.models.sec import (
    FilingProvenance,
    InsiderTransaction,
    InstitutionalHolding,
    OwnershipGovernanceAnalysis,
    ProxyCompensation,
)
from finrobot.engine.pipelines.base import PipelineResult


def _prov(form: str) -> FilingProvenance:
    return FilingProvenance(
        form=form,
        filing_date=date(2026, 5, 15),
        accession_no="0000000000-26-000001",
        source_url="https://www.sec.gov/Archives/example",
    )


def test_equity_research_artifact_persists_sec_top_level_keys() -> None:
    ownership = OwnershipGovernanceAnalysis(
        insider_transactions=[
            InsiderTransaction(
                filing_date=date(2026, 5, 15),
                accession_no="0000000000-26-000001",
                insider_name="Jane Doe",
                insider_position="CFO",
                transaction_type="sale",
                code="S",
                shares=1000,
                value=100_000,
                price_per_share=100,
                provenance=_prov("4"),
            )
        ],
        institutional_holdings=[
            InstitutionalHolding(
                holder_name="Bridgewater",
                holder_cik="1350694",
                cusip="67066G104",
                name_of_issuer="NVIDIA CORP",
                shares=30_000_000,
                value_usd=5.5e9,
                period_end=date(2026, 3, 31),
                provenance=_prov("13F-HR"),
            )
        ],
        proxy_compensation=ProxyCompensation(
            filing_date=date(2026, 1, 8),
            accession_no="0000000000-26-000002",
            ceo_total_compensation=51_800_000,
            provenance=_prov("DEF 14A"),
        ),
        generated_at=datetime.now(tz=timezone.utc),
    )
    result = PipelineResult(
        steps={"ownership_governance_analysis": "done"},
        structured_data={
            "sec_filings": {"10k": {"accession_no": "000"}},
            "xbrl_facts_snapshot": {"us-gaap:Revenues": [{"value": 100.0}]},
            "ownership_governance_analysis": ownership,
        },
    )

    artifact = build_equity_research_artifact(result, "NVDA", deps=object())  # type: ignore[arg-type]

    structured = artifact.outputs.structured
    assert "sec_filings" in structured
    assert "xbrl_facts_snapshot" in structured
    assert "ownership_governance" in structured
    ownership_dump = structured["ownership_governance"]
    assert ownership_dump["insider_transactions"][0]["provenance"]["form"] == "4"
    assert ownership_dump["institutional_holdings"][0]["provenance"]["form"] == "13F-HR"
    assert ownership_dump["proxy_compensation"]["provenance"]["form"] == "DEF 14A"
