"""External-truth through-cycle probe via SEC XBRL companyfacts (NOT FMP — FMP
key is rate-limited). Authoritative filed annual line items, the basis for the
mid-cycle normalization window.

For MU / WDC / STX: full annual Revenue + OperatingIncome + EBITDA-ish + capex
history (FY-tagged, 10-K only) → through-cycle margin (mean / median) vs the
last-3y median the current seed uses. This is the empirical core: does a
peak-to-trough margin spread exist large enough that "last-3y median" misprices?

SEC companyfacts: https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json
Requires a descriptive User-Agent (settings.sec_user_agent). No API key.

Run: `python scripts/_cyclical_probe_sec.py`
"""

from __future__ import annotations

import asyncio
import statistics

import httpx

from finrobot.config import get_settings
from finrobot.paths import SETTINGS_JSON
from finrobot.routes.settings import load_non_secret_settings
from finrobot.secret_store import create_secret_store
from finrobot.server import hydrate_settings_from_secrets

# SEC CIKs (zero-padded to 10 in the URL).
CIKS = {
    "MU": 723125,
    "WDC": 106040,
    "STX": 1137789,  # Seagate Technology Holdings plc
    "SNDK": 2012603,  # Sandisk Corp (2025 spin from WDC)
}

REV_CONCEPTS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
)
OPINC_CONCEPTS = ("OperatingIncomeLoss",)
NI_CONCEPTS = ("NetIncomeLoss",)
DA_CONCEPTS = (
    "DepreciationDepletionAndAmortization",
    "DepreciationAmortizationAndAccretionNet",
    "DepreciationAndAmortization",
)
CAPEX_CONCEPTS = (
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
)


def _annual_series(facts: dict, concepts: tuple[str, ...]) -> dict[int, float]:
    """Annual (form 10-K, full-year duration) values keyed by TRUE fiscal year.

    Picks USD units, form=10-K, fp=FY, and a duration ~1 year (≥300 days) so we
    get annual flows, not quarterly. Latest filed value per fiscal year wins.

    ⚠ KEY-BY-PERIOD-END, NOT THE ``fy`` FIELD. The SEC XBRL ``fy`` field is the
    fiscal year of the *FILING*, not of the data period: a 10-K restates 2-3 prior
    years as comparatives, and SEC tags every one of them with the FILING's ``fy``.
    So the $30.39B peak (period 2017-09→2018-08, true FY2018) appears tagged
    fy=2019 and fy=2020 (as comparatives in those later 10-Ks), and keying by
    ``fy`` made the probe label it FY2020 and the $15.54B trough (period ending
    2023-08, true FY2023) FY2025 — an off-by-2-year shift that also produced
    impossible labels like STX "FY2027". Production code is unaffected (FMP/
    yfinance derive fiscal_year from the period-end date, not SEC ``fy``); this
    fix is probe-only. The true fiscal year = calendar year of the period END.
    """
    from datetime import date

    usgaap = facts.get("facts", {}).get("us-gaap", {})
    out: dict[int, tuple[str, float]] = {}  # period_end_year -> (filed, val)
    for concept in concepts:
        node = usgaap.get(concept)
        if not node:
            continue
        for unit_key, items in node.get("units", {}).items():
            if "USD" not in unit_key:
                continue
            for it in items:
                if it.get("form") not in ("10-K", "10-K/A"):
                    continue
                if it.get("fp") != "FY":
                    continue
                start, end = it.get("start"), it.get("end")
                val = it.get("val")
                if val is None or start is None or end is None:
                    continue
                try:
                    d0 = date.fromisoformat(start)
                    d1 = date.fromisoformat(end)
                except ValueError:
                    continue
                if (d1 - d0).days < 300:
                    continue
                fy = d1.year  # TRUE fiscal year = period-end calendar year
                filed = it.get("filed", "")
                prev = out.get(fy)
                if prev is None or filed > prev[0]:
                    out[fy] = (filed, float(val))
        if out:
            break  # first concept that yields data wins
    return {fy: v for fy, (_, v) in out.items()}


async def main() -> int:
    settings = get_settings(**load_non_secret_settings(SETTINGS_JSON))
    store, _ = create_secret_store()
    settings = await hydrate_settings_from_secrets(settings, store)
    ua = settings.sec_user_agent or "FinRobot Research research@example.com"
    print(f"SEC User-Agent: {ua}")

    async with httpx.AsyncClient(
        headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}, timeout=30.0
    ) as client:
        for tkr, cik in CIKS.items():
            url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
            print("\n" + "=" * 100)
            try:
                r = await client.get(url)
                r.raise_for_status()
                facts = r.json()
            except Exception as e:  # noqa: BLE001
                print(f"{tkr} (CIK {cik}): SEC fetch FAILED — {type(e).__name__}: {str(e)[:160]}")
                continue
            entity = facts.get("entityName", "?")
            rev = _annual_series(facts, REV_CONCEPTS)
            opi = _annual_series(facts, OPINC_CONCEPTS)
            ni = _annual_series(facts, NI_CONCEPTS)
            da = _annual_series(facts, DA_CONCEPTS)
            capex = _annual_series(facts, CAPEX_CONCEPTS)
            years = sorted(rev.keys())
            print(f"{tkr}  entityName={entity!r}  CIK={cik}  ({len(years)} FY of revenue)")
            print(
                f"  {'FY':>6} {'revenue':>14} {'op_income':>14} {'op_margin':>9} "
                f"{'net_income':>14} {'D&A':>13} {'capex':>13} {'capex/rev':>9}"
            )
            opm_series: list[tuple[int, float]] = []
            for y in years:
                rv = rev.get(y)
                oi = opi.get(y)
                n = ni.get(y)
                d = da.get(y)
                cx = capex.get(y)
                opm = (oi / rv) if (oi is not None and rv) else None
                cxr = (cx / rv) if (cx is not None and rv) else None
                if opm is not None:
                    opm_series.append((y, opm))
                print(
                    f"  {y:>6} {rv:>14,.0f} "
                    f"{(oi if oi is not None else float('nan')):>14,.0f} "
                    f"{(opm if opm is not None else float('nan')):>9.1%} "
                    f"{(n if n is not None else float('nan')):>14,.0f} "
                    f"{(d if d is not None else float('nan')):>13,.0f} "
                    f"{(cx if cx is not None else float('nan')):>13,.0f} "
                    f"{(cxr if cxr is not None else float('nan')):>9.1%}"
                )
            # Through-cycle margin: full window vs last-3y (the current seed window)
            if opm_series:
                vals = [m for _, m in opm_series]
                last3 = [m for _, m in opm_series[-3:]]
                full_mean = statistics.mean(vals)
                full_med = statistics.median(vals)
                l3_med = statistics.median(last3)
                print(
                    f"  → op_margin THROUGH-CYCLE ({len(vals)}y): mean={full_mean:.1%} "
                    f"median={full_med:.1%}  |  LAST-3Y median={l3_med:.1%}  |  "
                    f"peak={max(vals):.1%} trough={min(vals):.1%} "
                    f"spread={max(vals) - min(vals):.0%}pts"
                )
                if l3_med != 0:
                    print(
                        f"     last-3y vs through-cycle median ratio: {l3_med / full_med:.2f}x"
                        if full_med
                        else ""
                    )

    print("\nDONE_SEC")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
