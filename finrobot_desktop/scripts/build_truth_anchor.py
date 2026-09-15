"""Build the external-truth ANCHOR for the verification harness.

Pulls a handful of anchor fields per ticker DIRECTLY from external authorities —
NOT from FinRobot's own compute path — so the resulting file is an independent
baseline the harness (``scripts/verify_report_field_basket.py``) checks our system
against. Authorities, by field:

  - revenue / net_income / shares_outstanding → SEC EDGAR XBRL companyconcept JSON
    API (https://data.sec.gov/api/xbrl/companyconcept/...). Free, no key, the
    as-reported filing value. Annual (10-K FY) caliber — recorded as such so the
    harness compares it against our TTM with caliber awareness, not blindly.
  - live price / marketCap → FMP stable /profile (the live-quote authority; SEC has
    no live price). ONE call per ticker.
  - CEO name → SEC Form-4 officer title via edgartools (INSIDER_TRADES), the same
    authoritative source the production ownership operator trusts
    (engine/compute/operators/ownership.py::_ceo_name_from_insiders).

Foreign private issuers (20-F, e.g. SAP) report under IFRS and file no Form-4, so
SEC us-gaap concepts and Form-4 CEO are absent — those fields are written as null
with a reason. The harness treats an intended-null baseline as abstain, not a miss.

Output: ``specs/外部真值锚-报告字段验证.json`` (Chinese filename per project
convention). Schema: ``{ticker: {field: {value, caliber, source_url, as_of}}}``.

Run:  uv run python scripts/build_truth_anchor.py
Economical: 1 FMP /profile + 1 SEC company_tickers map (cached) + a few free SEC
XBRL JSON GETs + 1 edgartools Form-4 pull per ticker.
"""

from __future__ import annotations

import asyncio
import json
import ssl
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from finrobot.config import get_settings
from finrobot.engine.data.factory import build_data_layer
from finrobot.engine.data.types import DataType
from finrobot.paths import SETTINGS_JSON, ensure_home
from finrobot.routes.settings import load_non_secret_settings
from finrobot.secret_store import create_secret_store
from finrobot.server import hydrate_settings_from_secrets

ANCHOR_PATH = Path(__file__).resolve().parent.parent / "specs" / "外部真值锚-报告字段验证.json"

# (ticker, archetype) — the basket the harness covers. Kept modest to stay
# economical on the fresh FMP key. ≥1 of each of the five archetypes + ≥1 ADR.
BASKET: tuple[tuple[str, str], ...] = (
    ("AAPL", "stable blue-chip"),
    ("KO", "stable blue-chip (consumer staple)"),
    ("F", "cyclical (auto OEM)"),
    ("NVDA", "high-growth"),
    ("TSLA", "heavy-asset growth (capital-intensive manufacturing)"),
    ("RIVN", "loss-making cash-burner"),
    ("SAP", "foreign ADR (EUR reporting, cross-currency)"),
)

_SEC_UA = "FinRobot 17696026747lrz@gmail.com"
_SSL = ssl.create_default_context()

# A baseline fact whose period_end is older than this is an ABANDONED concept the
# filer stopped tagging (Ford's dei:EntityCommonStockSharesOutstanding froze at
# 2011 — only 8 rows, all 2010-2011 — even though Ford files current 10-Ks). A
# 15-year-old count is not a valid external truth, so we abstain rather than ship
# it and let the harness FAIL our correct live value against a stale anchor.
_STALE_FACT_DAYS = 450

# SEC us-gaap concept priority lists — first concept with annual facts wins.
# Mirrors the production edgar_provider concept lists (post-ASC-606 issuers key
# revenue under RevenueFromContractWithCustomerExcludingAssessedTax, not Revenues).
# Totals first, ASC-606 contract-revenue subset last (mirrors the edgar_provider
# fix, 2026-06-29): a financial issuer reports BOTH total Revenues and the ASC-606
# subset at the SAME period_end, so the strict-`>` recency tie in _sec_fundamental
# keeps the first-iterated = total (MET Revenues 77B, not the 2.4B fee subset).
# Recency still wins across periods (AAPL's live revenue is ASC-606, newer).
_REVENUE_CONCEPTS = (
    "Revenues",
    "SalesRevenueNet",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
)
_NET_INCOME_CONCEPTS = ("NetIncomeLoss", "ProfitLoss")
# Shares outstanding is a dei concept (cover-page fact), not us-gaap.
_SHARES_CONCEPT = ("dei", "EntityCommonStockSharesOutstanding")


def _http_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": _SEC_UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=40, context=_SSL) as resp:  # noqa: S310
        return json.loads(resp.read().decode())


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _is_stale(period_end: str) -> bool:
    """True iff an ISO date is older than ``_STALE_FACT_DAYS`` from today."""
    try:
        end = datetime.fromisoformat(period_end).date()
    except ValueError:
        return False
    return (datetime.now(tz=timezone.utc).date() - end).days > _STALE_FACT_DAYS


@dataclass(frozen=True)
class _Anchor:
    value: float | str | None
    caliber: str
    source_url: str
    as_of: str | None
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "value": self.value,
            "caliber": self.caliber,
            "source_url": self.source_url,
            "as_of": self.as_of,
        }
        if self.note is not None:
            out["note"] = self.note
        return out


_TICKER_CIK_CACHE: dict[str, int] | None = None


def _ticker_cik_map() -> dict[str, int]:
    global _TICKER_CIK_CACHE
    if _TICKER_CIK_CACHE is None:
        raw = _http_json("https://www.sec.gov/files/company_tickers.json")
        _TICKER_CIK_CACHE = {v["ticker"]: int(v["cik_str"]) for v in raw.values()}
    return _TICKER_CIK_CACHE


def _latest_annual_fact(cik: int, taxonomy: str, concept: str) -> tuple[float, str, str] | None:
    """Newest 10-K/20-F full-year (or point-in-time) fact for one concept.

    Returns (value, period_end, accession) or None. For flow concepts (revenue,
    NI) we restrict to FY full-year windows via the ``frame`` (CY####) marker so a
    quarter is never mistaken for a year. For the dei shares point fact there is no
    frame; we take the most recent reported value.
    """
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/{taxonomy}/{concept}.json"
    try:
        payload = _http_json(url)
    except Exception:  # noqa: BLE001 — concept absent for this filer → try next
        return None
    units = payload.get("units", {})
    rows: list[dict[str, Any]] = []
    for unit_rows in units.values():
        rows.extend(unit_rows)
    if not rows:
        return None
    if taxonomy == "us-gaap":
        # Annual flow: keep full-year frames (CY#### with no Q) from 10-K/20-F.
        annual = [
            r
            for r in rows
            if isinstance(r.get("frame"), str)
            and r["frame"].startswith("CY")
            and "Q" not in r["frame"]
        ]
        candidates = annual or [r for r in rows if r.get("form") in ("10-K", "20-F")]
    else:
        candidates = rows
    if not candidates:
        return None
    best = max(candidates, key=lambda r: str(r.get("end", "")))
    return float(best["val"]), str(best.get("end", "")), str(best.get("accn", ""))


def _sec_fundamental(cik: int, concepts: tuple[str, ...], field_label: str) -> _Anchor | None:
    """Pick the concept whose latest annual window ends NEWEST (ADR-0008 / BUG-009).

    NOT first-match-wins: a post-ASC-606 issuer can carry an ABANDONED concept that
    froze years ago (NVDA's RevenueFromContractWithCustomer... latched CY2021 $26.9B
    while live revenue lives under Revenues CY2025 $215.9B). First-match would ship
    the stale year as truth. We probe every candidate and keep the freshest period.
    """
    best: tuple[float, str, str, str] | None = None  # (value, end, accn, concept)
    for concept in concepts:
        hit = _latest_annual_fact(cik, "us-gaap", concept)
        if hit is None:
            continue
        value, period_end, accn = hit
        if best is None or period_end > best[1]:
            best = (value, period_end, accn, concept)
    if best is None:
        return None
    value, period_end, accn, concept = best
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/us-gaap/{concept}.json"
    return _Anchor(
        value=value,
        caliber=f"annual FY (10-K, us-gaap:{concept}, {field_label})",
        source_url=url,
        as_of=period_end,
        note=f"accession {accn}",
    )


def _sec_shares(cik: int) -> _Anchor | None:
    taxonomy, concept = _SHARES_CONCEPT
    hit = _latest_annual_fact(cik, taxonomy, concept)
    if hit is None:
        return None
    value, period_end, accn = hit
    if _is_stale(period_end):
        # Abandoned concept (Ford froze dei shares at 2011) — abstain, never ship
        # a 15-year-old count as a baseline the harness would FAIL our live value on.
        return _Anchor(
            None,
            "cover-page shares (stale concept — abstained)",
            f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/{taxonomy}/{concept}.json",
            None,
            f"newest dei shares fact is {period_end} (>{_STALE_FACT_DAYS}d old) — "
            f"filer abandoned this concept; no current SEC shares truth",
        )
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/{taxonomy}/{concept}.json"
    return _Anchor(
        value=value,
        caliber=f"cover-page shares outstanding ({taxonomy}:{concept}, point-in-time)",
        source_url=url,
        as_of=period_end,
        note=f"accession {accn}",
    )


_CEO_TITLE_TOKENS = ("chief executive officer", "ceo")


def _ceo_from_form4(insider_payload: dict[str, Any]) -> tuple[str | None, str | None]:
    """Most-frequent current-CEO name from Form-4 officer titles + latest filing date.

    Mirrors engine/compute/operators/ownership.py::_ceo_name_from_insiders so the
    anchor's CEO truth is resolved the same way production trusts it, but pulled
    straight from the SEC INSIDER_TRADES payload (not our ownership operator).
    """
    txns = insider_payload.get("transactions") or insider_payload.get("insider_transactions")
    if not isinstance(txns, list):
        return None, None
    counts: dict[str, int] = {}
    latest: dict[str, str] = {}
    for tx in txns:
        if not isinstance(tx, dict):
            continue
        position = str(tx.get("insider_position") or tx.get("position") or "").lower()
        if "former" in position:
            continue
        if not any(tok in position for tok in _CEO_TITLE_TOKENS):
            continue
        name = str(tx.get("insider_name") or tx.get("name") or "").strip()
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
        fdate = str(tx.get("filing_date") or "")
        if name not in latest or fdate > latest[name]:
            latest[name] = fdate
    if not counts:
        return None, None
    winner = max(counts, key=lambda n: (counts[n], latest[n]))
    return winner, latest.get(winner)


def _fmp_profile(api_key: str, ticker: str) -> dict[str, Any] | None:
    """FMP stable /profile pulled DIRECTLY (external authority for live price/mcap).

    The FMP DataProvider does not expose a PROFILE DataType, and — more to the point
    — the anchor must be an INDEPENDENT external pull, not routed through our system.
    One live GET per ticker.
    """
    url = f"https://financialmodelingprep.com/stable/profile?symbol={ticker}&apikey={api_key}"
    try:
        payload = _http_json(url)
    except Exception:  # noqa: BLE001
        return None
    if isinstance(payload, list):
        return payload[0] if payload else None
    if isinstance(payload, dict):
        return payload
    return None


async def build_ticker_anchor(
    data_layer: Any,
    fmp_api_key: str,
    ticker: str,
    archetype: str,
    cik_map: dict[str, int],
) -> tuple[dict[str, Any], int]:
    """Return ({field: anchor_dict}, fmp_call_count) for one ticker."""
    fields: dict[str, Any] = {"__archetype__": archetype}
    fmp_calls = 0
    cik = cik_map.get(ticker)

    # --- SEC XBRL fundamentals (free) ---
    if cik is not None:
        rev = _sec_fundamental(cik, _REVENUE_CONCEPTS, "revenue")
        ni = _sec_fundamental(cik, _NET_INCOME_CONCEPTS, "net_income")
        shares = _sec_shares(cik)
        is_foreign = rev is None and ni is None
        fields["revenue"] = (
            rev.as_dict()
            if rev is not None
            else _Anchor(
                None,
                "annual FY",
                f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/",
                None,
                "no us-gaap revenue concept (foreign 20-F / IFRS filer)"
                if is_foreign
                else "no us-gaap revenue concept matched",
            ).as_dict()
        )
        fields["net_income"] = (
            ni.as_dict()
            if ni is not None
            else _Anchor(
                None,
                "annual FY",
                f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/",
                None,
                "no us-gaap net-income concept (foreign 20-F / IFRS filer)"
                if is_foreign
                else "no us-gaap net-income concept matched",
            ).as_dict()
        )
        fields["shares_outstanding"] = (
            shares.as_dict()
            if shares is not None
            else _Anchor(
                None,
                "cover-page shares",
                f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/",
                None,
                "no dei shares-outstanding fact (foreign filer or unmapped)",
            ).as_dict()
        )
    else:
        for f in ("revenue", "net_income", "shares_outstanding"):
            fields[f] = _Anchor(
                None, "annual FY", "https://data.sec.gov/", None, "no SEC CIK for ticker"
            ).as_dict()

    # --- CEO from SEC Form-4 (free, via edgartools INSIDER_TRADES) ---
    ceo_name: str | None = None
    ceo_as_of: str | None = None
    ceo_note: str | None = None
    try:
        # INSIDER_TRADES has no canonical contract → raw fetch(); payload in .data.
        insider_result = await data_layer.fetch(DataType.INSIDER_TRADES, ticker)
        payload = getattr(insider_result, "data", None)
        if isinstance(payload, dict):
            ceo_name, ceo_as_of = _ceo_from_form4(payload)
    except Exception as exc:  # noqa: BLE001 — foreign filers have no Form-4
        ceo_note = f"Form-4 fetch failed: {type(exc).__name__}: {exc}"
    if ceo_name is None and ceo_note is None:
        ceo_note = "no Form-4 with a current-CEO officer title (foreign 20-F filer has no Form-4)"
    fields["ceo"] = _Anchor(
        value=ceo_name,
        caliber="SEC Form-4 officer title (current CEO)",
        source_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=4&CIK={ticker}",
        as_of=ceo_as_of,
        note=ceo_note,
    ).as_dict()

    # --- live price / marketCap from FMP /profile (one live call) ---
    profile = _fmp_profile(fmp_api_key, ticker)
    fmp_calls += 1
    profile_url = f"https://financialmodelingprep.com/stable/profile?symbol={ticker}"
    if profile is not None:
        price = profile.get("price") or profile.get("current_price")
        mcap = profile.get("marketCap") or profile.get("market_cap")
        ccy = profile.get("currency")
        fields["current_price"] = _Anchor(
            value=float(price) if price is not None else None,
            caliber=f"live quote ({ccy or 'quote ccy'})",
            source_url=profile_url,
            as_of=_now_iso(),
        ).as_dict()
        fields["market_cap"] = _Anchor(
            value=float(mcap) if mcap is not None else None,
            caliber=f"live market cap ({ccy or 'quote ccy'})",
            source_url=profile_url,
            as_of=_now_iso(),
        ).as_dict()
    else:
        for f in ("current_price", "market_cap"):
            fields[f] = _Anchor(
                None, "live", profile_url, _now_iso(), "FMP /profile returned no row"
            ).as_dict()

    return fields, fmp_calls


async def main() -> int:
    ensure_home()
    settings = get_settings(**load_non_secret_settings(SETTINGS_JSON))
    store, _ = create_secret_store()
    settings = await hydrate_settings_from_secrets(settings, store)
    data_layer = build_data_layer(settings)
    cik_map = _ticker_cik_map()

    total_fmp = 0
    anchor: dict[str, Any] = {
        "__meta__": {
            "generated_at": _now_iso(),
            "purpose": "external-truth baseline for scripts/verify_report_field_basket.py",
            "authorities": {
                "revenue/net_income/shares": "SEC EDGAR XBRL companyconcept (annual FY)",
                "current_price/market_cap": "FMP stable /profile (live)",
                "ceo": "SEC Form-4 officer title",
            },
        }
    }
    try:
        fmp_api_key = settings.fmp_api_key or ""
        for ticker, archetype in BASKET:
            fields, fmp_calls = await build_ticker_anchor(
                data_layer, fmp_api_key, ticker, archetype, cik_map
            )
            anchor[ticker] = fields
            total_fmp += fmp_calls
            rev = fields["revenue"]["value"]
            ceo = fields["ceo"]["value"]
            price = fields["current_price"]["value"]
            print(f"{ticker:5s} rev={rev} ceo={ceo} price={price}")
    finally:
        await data_layer.close()

    ANCHOR_PATH.parent.mkdir(parents=True, exist_ok=True)
    ANCHOR_PATH.write_text(
        json.dumps(anchor, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\nanchor written: {ANCHOR_PATH}")
    print(f"FMP /profile live calls: {total_fmp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
