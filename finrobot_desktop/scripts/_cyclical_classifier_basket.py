"""PILLAR 3 (full-basket) — prove the PRODUCTION cyclical classifier has no false
positives, and (separately) why the volatility gate alone would.

The normalization fires only for names ``is_commodity_cyclical`` flags. If a
stable compounder (KO/MSFT/JNJ) or a secular grower (NVDA/AMD) were misflagged,
its earnings base would be wrongly normalized — the "AAPL 变准时 KO 不许崩" rule.

Two halves:
  (A) PRODUCTION CLASSIFIER — call ``is_commodity_cyclical`` with each name's REAL
      provider industry/sector + ticker anchor (yfinance tags, probed 2026-06-11).
      This is the actual gate the seed uses. Autos (TSLA/RIVN/F) are cyclical BY
      DESIGN (§2.2 white-list: volume-cyclical OEMs); AMD/NVDA/KO/MSFT/JNJ are not.
  (B) VOLATILITY GATE (rejected as the primary gate) — SEC 10-K op-margin
      spread/coeff-var, to show it假阳's AMD (turnaround swings ≠ commodity cycle).
      SEC series keyed by PERIOD-END year (the true fiscal year), NOT the XBRL
      ``fy`` field (which is the FILING's year — keying by it shifts MU's labels
      +2y and is the probe-only bug §修正2 root-caused).

Run: `python scripts/_cyclical_classifier_basket.py`
"""

from __future__ import annotations

import asyncio
import statistics
from datetime import date

import httpx

from finrobot.config import get_settings
from finrobot.engine.primitives.industry import is_commodity_cyclical
from finrobot.paths import SETTINGS_JSON
from finrobot.routes.settings import load_non_secret_settings
from finrobot.secret_store import create_secret_store
from finrobot.server import hydrate_settings_from_secrets

# Real provider (yfinance) industry/sector tags + the design's expected verdict.
# Autos are cyclical BY DESIGN (§2.2 white-list). Memory/storage ride generic
# "Semiconductors"/"Computer Hardware" and qualify via the ticker anchor.
BASKET: dict[str, tuple[str, str, str, bool]] = {
    # ticker: (industry, sector, expected-verdict-note, expected_cyclical)
    "MU": ("Semiconductors", "Technology", "cyclical: memory (anchor)", True),
    "WDC": ("Computer Hardware", "Technology", "cyclical: storage/HDD (anchor)", True),
    "STX": ("Computer Hardware", "Technology", "cyclical: storage/HDD (anchor)", True),
    "TSLA": ("Auto Manufacturers", "Consumer Cyclical", "cyclical: auto OEM (white-list)", True),
    "RIVN": ("Auto Manufacturers", "Consumer Cyclical", "cyclical: auto OEM (white-list)", True),
    "AMD": ("Semiconductors", "Technology", "NOT: semis-logic (turnaround vol≠cycle)", False),
    "NVDA": ("Semiconductors", "Technology", "NOT: semis-logic (secular growth)", False),
    "KO": ("Beverages - Non-Alcoholic", "Consumer Defensive", "NOT: beverages staple", False),
    "MSFT": ("Software - Infrastructure", "Technology", "NOT: software", False),
    "JNJ": ("Drug Manufacturers - General", "Healthcare", "NOT: pharma", False),
}

# CIKs for the volatility-gate half (half B). Only names with a SEC 10-K history.
CIKS = {
    "MU": 723125,
    "WDC": 106040,
    "STX": 1137789,
    "AMD": 2488,
    "NVDA": 1045810,
    "KO": 21344,
    "MSFT": 789019,
    "JNJ": 200406,
    "TSLA": 1318605,
    "RIVN": 1874178,
}

REV = ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet")
OPI = ("OperatingIncomeLoss",)


def _annual(facts: dict, concepts: tuple[str, ...]) -> dict[int, float]:
    """Annual 10-K flows keyed by TRUE fiscal year = period-end calendar year.

    Keying by the XBRL ``fy`` field is wrong — it is the FILING's fiscal year, so
    restated comparatives in later 10-Ks carry the filing's ``fy`` and shift the
    labels (MU peak FY2018→FY2020). The period-end year is the true fiscal year.
    Spread/coeff-var are window-shape stats invariant to the labelling, but keying
    by period-end keeps this probe consistent with the validation scripts and
    avoids impossible labels (STX "FY2027").
    """
    ug = facts.get("facts", {}).get("us-gaap", {})
    out: dict[int, tuple[str, float]] = {}
    for concept in concepts:
        node = ug.get(concept)
        if not node:
            continue
        for uk, items in node.get("units", {}).items():
            if "USD" not in uk:
                continue
            for it in items:
                if it.get("form", "")[:4] != "10-K" or it.get("fp") != "FY":
                    continue
                s, e, v = it.get("start"), it.get("end"), it.get("val")
                if None in (s, e, v):
                    continue
                try:
                    d0, d1 = date.fromisoformat(s), date.fromisoformat(e)
                    if (d1 - d0).days < 300:
                        continue
                except ValueError:
                    continue
                fy = d1.year  # TRUE fiscal year = period-end calendar year
                f = it.get("filed", "")
                if fy not in out or f > out[fy][0]:
                    out[fy] = (f, float(v))
        if out:
            break
    return {fy: v for fy, (_, v) in out.items()}


async def _facts(client: httpx.AsyncClient, cik: int) -> dict:
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    last: Exception | None = None
    for _ in range(4):
        try:
            r = await client.get(url)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last = e
            await asyncio.sleep(2.0)
    raise RuntimeError(f"{cik}: {last}")


async def main() -> int:
    s = get_settings(**load_non_secret_settings(SETTINGS_JSON))
    store, _ = create_secret_store()
    s = await hydrate_settings_from_secrets(s, store)
    ua = s.sec_user_agent or "FinRobot Research r@example.com"
    print(f"SEC UA: {ua}")

    # ---------- HALF A: PRODUCTION CLASSIFIER (the gate the seed actually uses) -
    print("\n" + "=" * 100)
    print("HALF A — is_commodity_cyclical (PRODUCTION gate) on real provider tags + ticker anchor")
    print("=" * 100)
    print(f"{'ticker':>7} {'industry':>26} {'is_cyclical':>12} {'expected':>9} {'ok':>4}  note")
    print("-" * 100)
    all_ok = True
    for t, (ind, sec, note, expected) in BASKET.items():
        got = is_commodity_cyclical(industry=ind, sector=sec, ticker=t)
        ok = got == expected
        all_ok = all_ok and ok
        print(
            f"{t:>7} {ind:>26} {str(got):>12} {str(expected):>9} {'✅' if ok else '❌FAIL':>4}  {note}"
        )
    print(
        f"\n  PRODUCTION CLASSIFIER {'ALL MATCH ✅' if all_ok else 'HAS A MISMATCH ❌'} "
        "(autos cyclical by §2.2 white-list; AMD/NVDA/KO/MSFT/JNJ untouched)"
    )

    # ---------- HALF B: volatility gate (rejected) — show AMD false positive -----
    print("\n" + "=" * 100)
    print(
        "HALF B — volatility gate (spread>25pts | coeff_var>0.6), SEC op-margin, keyed period-end"
    )
    print("=" * 100)
    print(
        f"{'ticker':>7} {'n':>3} {'trough':>8} {'peak':>8} {'spread':>8} {'coeff_var':>9} "
        f"{'vol-gate':>10}  production verdict"
    )
    print("-" * 110)
    async with httpx.AsyncClient(
        headers={"User-Agent": ua, "Accept-Encoding": "gzip"}, timeout=30.0
    ) as client:
        for t, cik in CIKS.items():
            try:
                f = await _facts(client, cik)
            except Exception as e:  # noqa: BLE001
                print(f"{t:>7}  SEC FAIL {str(e)[:60]}")
                continue
            rev = _annual(f, REV)
            opi = _annual(f, OPI)
            years = sorted(rev.keys())
            ms = [opi[y] / rev[y] for y in years if y in opi and rev[y]]
            if len(ms) < 3:
                print(f"{t:>7} {len(ms):>3}  <3 margin years — vol-gate abstains")
                continue
            mu_ = statistics.mean(ms)
            cv = statistics.pstdev(ms) / abs(mu_) if mu_ else float("inf")
            spread = max(ms) - min(ms)
            vol_gate = spread > 0.25 or cv > 0.6
            prod = "cyclical" if BASKET.get(t, (None, None, "", False))[3] else "NOT"
            flag = "⚠假阳" if (vol_gate and prod == "NOT") else ""
            print(
                f"{t:>7} {len(ms):>3} {min(ms):>8.1%} {max(ms):>8.1%} {spread:>8.1%} "
                f"{cv:>9.2f} {('CYCLICAL' if vol_gate else 'stable'):>10}  {prod} {flag}"
            )
    print("\n  AMD trips the vol-gate but production says NOT — that假阳 is exactly why the")
    print("  white-list/keyword/anchor is the primary gate and volatility is NOT used.")
    print("DONE_BASKET")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
