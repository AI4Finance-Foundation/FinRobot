"""Audit: PRICE/FINANCIALS raw `.data.get(` must not appear in compute or services.

ADR-0006 Step 7 red-line: After migration, `finrobot/engine/compute` and
`finrobot/engine/services` must not directly parse raw provider dicts for
PRICE or FINANCIALS data. All PRICE/FINANCIALS consumption must flow through
`DataLayer.fetch_canonical` → `NormalizedPrice` / `NormalizedFinancials`.

Allowed exceptions (explicit allow-list):
- `normalize/` itself (the one place that legally reads raw dicts into canonical)
- `historical_extractor.py` — per-year slices from `fetch_historical` have no
  canonical cache slot; these use `normalize_financials(yr)` inline (documented
  in ADR-0006 §7). Their raw dict reads are `.data.get(` of yearly DataResult
  slices, NOT of live snapshot FINANCIALS.
- `extractor.py` — post-migration this file reads only `NormalizedFinancials`/
  `NormalizedPrice` typed fields; it must not contain `.data.get(`.

This grep-pin test catches drift: if a new file adds a raw `.data.get(` in
compute or services (outside the allow-list), the test fails immediately.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPUTE = ROOT / "finrobot" / "engine" / "compute"
SERVICES = ROOT / "finrobot" / "engine" / "services"

# Files that are legitimate exceptions to the raw `.data.get(` prohibition.
# `normalize/` is the single legal raw-dict consumer by design (ADR-0004/0006).
# `historical_extractor.py` uses `normalize_financials(yr)` on per-year slices
# from `fetch_historical` — these are not live snapshot reads; the yearly slices
# carry the same provider dict format but have no canonical cache slot.
_ALLOWED: set[Path] = {
    # normalize/ is the legitimate raw-dict-to-canonical boundary (all of it)
    ROOT / "finrobot" / "engine" / "data" / "normalize" / "financials.py",
    ROOT / "finrobot" / "engine" / "data" / "normalize" / "price.py",
    ROOT / "finrobot" / "engine" / "data" / "normalize" / "window.py",
    ROOT / "finrobot" / "engine" / "data" / "normalize" / "currency.py",
    # historical_extractor reads yearly DataResult slices (not live snapshots)
    COMPUTE / "coordinators" / "historical_extractor.py",
    # news.py parses DataType.NEWS (not PRICE/FINANCIALS) — no canonical contract
    # for NEWS by design (ADR-0006 §3 — only PRICE/FINANCIALS have contracts).
    COMPUTE / "coordinators" / "news.py",
    # segment_extractor.py parses the SOTP segment payload (FILINGS_10K
    # ``:segments`` slot — ASC 280 reportable segments, not PRICE/FINANCIALS).
    # Same footing as NEWS: no canonical contract by design (ADR-0006 §3).
    COMPUTE / "coordinators" / "segment_extractor.py",
}

_RAW_GET_PATTERN = re.compile(r"\.data\.get\(")


class TestNoRawDataGetInComputeOrServices:
    """Grep-pin: compute/ and services/ must not parse raw provider dicts."""

    def test_compute_no_raw_data_get(self) -> None:
        violations: list[str] = []
        for py in COMPUTE.rglob("*.py"):
            if py in _ALLOWED:
                continue
            text = py.read_text()
            for match in _RAW_GET_PATTERN.finditer(text):
                lineno = text[: match.start()].count("\n") + 1
                violations.append(f"  {py.relative_to(ROOT)}:{lineno} — raw .data.get(")
        assert not violations, (
            "Raw .data.get() found in compute/ — migrate to fetch_canonical + typed fields.\n"
            "Violations:\n" + "\n".join(violations)
        )

    def test_services_no_raw_data_get(self) -> None:
        violations: list[str] = []
        for py in SERVICES.rglob("*.py"):
            if py in _ALLOWED:
                continue
            text = py.read_text()
            for match in _RAW_GET_PATTERN.finditer(text):
                lineno = text[: match.start()].count("\n") + 1
                violations.append(f"  {py.relative_to(ROOT)}:{lineno} — raw .data.get(")
        assert not violations, (
            "Raw .data.get() found in services/ — migrate to fetch_canonical + typed fields.\n"
            "Violations:\n" + "\n".join(violations)
        )

    def test_extractor_no_raw_data_get(self) -> None:
        """extractor.py post-ADR-0006 must read only typed Normalized* fields."""
        extractor = COMPUTE / "coordinators" / "extractor.py"
        text = extractor.read_text()
        violations = [
            f"line {text[: m.start()].count(chr(10)) + 1}" for m in _RAW_GET_PATTERN.finditer(text)
        ]
        assert not violations, (
            "extractor.py still has raw .data.get() — ADR-0006 Step 4 not complete.\n"
            "Lines: " + ", ".join(violations)
        )
