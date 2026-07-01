from __future__ import annotations

from datetime import date, datetime, timezone

import scripts.probe_derived_fields_truth as probe


def _instant(value: float, end: str) -> dict[str, object]:
    return {"units": {"USD": [{"val": value, "end": end}]}}


def test_sec_total_debt_candidates_include_lease_alternate() -> None:
    end = datetime.now(tz=timezone.utc).date().isoformat()
    facts = probe._CompanyFacts(
        {
            "LongTermDebtNoncurrent": _instant(7_470_000_000.0, end),
            "LongTermDebtCurrent": _instant(1_000_000_000.0, end),
            "OperatingLeaseLiability": _instant(4_344_000_000.0, end),
        },
        available=True,
    )

    candidates = probe._sec_total_debt_candidates(facts)

    assert [c.value for c in candidates] == [8_470_000_000.0, 12_814_000_000.0]
    assert candidates[1].concept == (
        "LongTermDebtNoncurrent+LongTermDebtCurrent+OperatingLeaseLiability"
    )


def test_best_sec_total_debt_chooses_nearest_accepted_caliber() -> None:
    end = datetime.now(tz=timezone.utc).date().isoformat()
    facts = probe._CompanyFacts(
        {
            "LongTermDebtNoncurrent": _instant(7_470_000_000.0, end),
            "LongTermDebtCurrent": _instant(1_000_000_000.0, end),
            "OperatingLeaseLiability": _instant(4_344_000_000.0, end),
        },
        available=True,
    )

    funded = probe._best_sec_total_debt_for_our(facts, 8_500_000_000.0)
    lease_inclusive = probe._best_sec_total_debt_for_our(facts, 12_800_000_000.0)

    assert funded is not None and funded.value == 8_470_000_000.0
    assert lease_inclusive is not None and lease_inclusive.value == 12_814_000_000.0


def test_fresh_ttm_vs_sec_fy_gap_is_abstain_context() -> None:
    note = probe._ttm_fy_mismatch_note(date(2026, 4, 26), "2026-01-25")

    assert note is not None
    assert "no same-caliber external TTM baseline" in note
    assert probe._ttm_fy_mismatch_note(date(2026, 2, 10), "2026-01-25") is None


def test_margin_over_band_with_ttm_fy_mismatch_abstains_not_candidate() -> None:
    row = probe._margin_row(
        "NVDA",
        "net_margin",
        0.6297,
        0.5560,
        "SEC annual NI/Rev [our TTM@2026-04-26 vs SEC FY]",
        caliber_mismatch_note="abstain: our TTM period_end 2026-04-26 is newer than SEC FY 2026-01-25",
    )

    assert row.over_band is True
    assert row.verdict == "abstain"


def test_total_debt_lease_caliber_gap_abstains_not_candidate() -> None:
    row = probe._magnitude_row(
        "RIVN",
        "total_debt",
        6_576_000_000.0,
        probe._SecFact(5_103_000_000.0, "2026-03-31", "LongTermDebtNoncurrent+Lease"),
        "balance instant",
        0.10,
        caliber_mismatch_note=probe._DEBT_LEASE_CALIBER_NOTE,
    )

    assert row.over_band is True
    assert row.verdict == "abstain"
