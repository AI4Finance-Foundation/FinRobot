from __future__ import annotations

from datetime import datetime, timezone

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
