from __future__ import annotations


from finrobot.engine.compute.ownership import compute_ownership_governance


def test_compute_ownership_governance_builds_typed_models_with_provenance() -> None:
    analysis = compute_ownership_governance(
        insider_data={
            "transactions": [
                {
                    "filing_date": "2026-05-15",
                    "accession_no": "0001104659-26-062860",
                    "insider_name": "Vaibhav Taneja",
                    "insider_position": "CFO",
                    "transaction_type": "sale",
                    "code": "S",
                    "shares": 3000,
                    "value": 1_350_000,
                    "price_per_share": 450,
                    "security_type": "non-derivative",
                    "security_title": "Common Stock",
                }
            ]
        },
        institutional_data={
            "holders": [
                {
                    "holder_name": "Bridgewater",
                    "holder_cik": "1350694",
                    "cusip": "67066G104",
                    "name_of_issuer": "NVIDIA CORP",
                    "title_of_class": "COM",
                    "shares": 30_000_000,
                    "value_usd": 5.5e9,
                    "period_end": "2026-03-31",
                    "filing_date": "2026-05-15",
                    "accession_no": "0001350694-26-000001",
                }
            ]
        },
        proxy_data={
            "filing_date": "2026-01-08",
            "accession_no": "0001308179-26-000008",
            "text": "CEO pay ratio was 1,447 to 1. Total CEO compensation was $51.8 million.",
            "source_url": "https://www.sec.gov/Archives/example",
        },
    )

    assert analysis.degraded_sections == []
    assert analysis.insider_transactions[0].provenance.form == "4"
    assert analysis.institutional_holdings[0].provenance.form == "13F-HR"
    assert analysis.proxy_compensation is not None
    assert analysis.proxy_compensation.provenance.form == "DEF 14A"
    assert analysis.proxy_compensation.ceo_pay_ratio == 1447
    assert analysis.proxy_compensation.ceo_total_compensation == 51_800_000


def test_compute_ownership_governance_marks_empty_sections_degraded() -> None:
    analysis = compute_ownership_governance(
        insider_data={"transactions": []},
        institutional_data={"holders": []},
        proxy_data={"proxy": None},
    )

    assert analysis.insider_transactions == []
    assert analysis.institutional_holdings == []
    assert analysis.proxy_compensation is None
    assert analysis.degraded_sections == [
        "insider_transactions",
        "institutional_holdings",
        "proxy_compensation",
    ]
