"""Derived-field × stock-basket × SEC-XBRL external-truth probe.

The existing harness (``scripts/verify_report_field_basket.py``) only covers eight
BASE fields (price / market_cap / revenue / net_income / shares / ceo /
price_target / implied_growth) and they all PASS. The product moat lives in the
DERIVED / COMPUTED fields — margins, EV bridge components, EBITDA calibers, current
multiples — and those have never been checked against external truth. This probe
pulls every one of them out of our compute path and compares it, field by field,
against the as-reported SEC XBRL value (or a value reconstructed from SEC line
items), so a real data error in a derived field surfaces as a ``candidate_bug``.

This is a DISCOVERY / EVIDENCE tool. A ``candidate_bug`` verdict means only "does
not reconcile to external truth, worth a look" — NOT a confirmed bug. It changes no
production code; it just builds the evidence table the adversarial pass needs.

External authority, by field family:
  - Income line items (revenue / COGS / GrossProfit / OperatingIncomeLoss /
    NetIncomeLoss / D&A) → SEC EDGAR XBRL companyfacts (one free GET per ticker,
    all concepts at once). Annual FY (10-K / 20-F full-year window) caliber.
  - margins (gross / operating / net) → reconstructed FROM the SEC line items above
    (gross = GrossProfit/Rev or (Rev−COGS)/Rev; op = OI/Rev; net = NI/Rev). Margins
    are RATIOS — TTM-vs-annual barely drifts (<1-2pt) — so they are the sharpest
    discriminator: our margin off SEC annual margin by >3pt absolute = candidate bug.
  - EBITDA_operating → SEC OperatingIncomeLoss + D&A (annual). Flow caliber, 15%.
  - EV bridge components (total_cash / preferred / NCI) → SEC balance instants
    (freshest quarter/annual). Point values, 10% band. total_debt is recorded
    against the nearest funded/lease-inclusive SEC reconstruction, but over-band
    debt gaps abstain rather than candidate_bug because provider debt conventions
    differ on operating/capital lease capitalization.
  - current multiples (PE / EV-EBITDA / EV-Revenue) → recorded, no equality
    asserted (no external truth for a forward-looking live multiple); ADR / bank
    intended-None handled as PASS-by-abstain.

Traps built in so we don't emit FALSE candidate_bugs:
  - cross-currency ADR (reporting_currency≠quote_currency): our EV / PE / EV-EBITDA
    are deliberately None → abstain, never mismatch. Margins (same-currency ratios)
    still verified.
  - bank (JPM): gross_margin suppressed to None on purpose → abstain. operating
    margin still verified.
  - None ≠ 0: our component None while SEC also omits the concept → abstain; our None
    while SEC HAS a value → candidate "我们缺值".
  - foreign / IFRS filer with no us-gaap concept → abstain (no baseline).

Output:
  - JSON ``specs/probe_derived_fields_results.json`` — one row per (ticker, field):
    ticker, field, our_value, external_truth, caliber, abs_diff, rel_diff,
    over_band, verdict (pass / candidate_bug / abstain), note.
  - stdout: a candidate_bug summary + a per-field-family landscape.

Run:  uv run python scripts/probe_derived_fields_truth.py
      uv run python scripts/probe_derived_fields_truth.py AAPL NVDA   # subset

Economical: our compute side rides DataLayer's per-ticker canonical cache (SEC/FMP
hit at most once per ticker, cache-first). The external side is ONE free SEC
companyfacts GET per ticker — no FMP calls at all on the truth side.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from finrobot.config import get_settings
from finrobot.engine.compute.coordinators.extractor import extract_financial_data
from finrobot.engine.data.factory import build_data_layer
from finrobot.engine.data.types import DataType
from finrobot.engine.primitives.industry import is_balance_sheet_financial
from finrobot.paths import SETTINGS_JSON, ensure_home
from finrobot.routes.settings import load_non_secret_settings
from finrobot.secret_store import create_secret_store
from finrobot.server import hydrate_settings_from_secrets

_HERE = Path(__file__).resolve().parent.parent
RESULTS_PATH = _HERE / "specs" / "probe_derived_fields_results.json"

# (ticker, archetype) — five company classes + ADRs + multi-class + a bank, so the
# probe exercises every intended-None / suppression branch.
BASKET: tuple[tuple[str, str], ...] = (
    ("AAPL", "stable blue-chip"),
    ("NVDA", "high-growth"),
    ("KO", "stable blue-chip (consumer staple)"),
    ("F", "cyclical (auto OEM)"),
    ("TSLA", "heavy-asset growth"),
    ("RIVN", "loss-making cash-burner"),
    ("JPM", "bank (no gross margin)"),
    ("XOM", "integrated energy"),
    ("TSM", "foreign ADR (TWD reporting, cross-currency)"),
    ("GOOGL", "multi-class growth"),
)

_SEC_UA = "FinRobot 17696026747lrz@gmail.com"
_SSL = ssl.create_default_context()

# A balance instant whose period_end is older than this is an ABANDONED concept the
# filer stopped tagging (Ford's LongTermDebtNoncurrent froze at 2020, Tesla's at
# 2014, JPM PreferredStockValue at 2009) — its "freshest" row is years stale and
# must NOT be shipped as external truth, else our correct live value FAILs against
# an ancient anchor. Mirrors build_truth_anchor._STALE_FACT_DAYS. Abstain instead.
_STALE_INSTANT_DAYS = 450

# ── tolerances by field family (口径-aware, from the task spec) ────────────────
# margins are ratios → barely drift across TTM/annual → tight ABSOLUTE band in pp.
_MARGIN_ABS_BAND = 0.03  # 3 percentage points absolute
# Ceiling on what a TTM-vs-FY window offset can PLAUSIBLY explain for a margin.
# The offset abstain (no same-caliber external TTM baseline) is legitimate for
# a few pp of drift, but a blanket exemption also swallowed 30pp+ gaps — the
# exact magnitude of a real margin bug. Beyond this cap the row stays
# candidate_bug (human review queue): a genuine step-change (MU's memory
# supercycle: 33pp net-margin jump vs the pre-boom FY, externally verified
# real) costs one review; a silent pass on a real 33pp bug costs a shipped
# wrong number.
_MARGIN_OFFSET_ABSTAIN_CAP = 0.15  # 15 percentage points absolute
# EV bridge components are point values → should track SEC freshest instant closely.
_BALANCE_REL_BAND = 0.10
# flow magnitudes (revenue/NI/EBITDA) are TTM-vs-annual → wider band absorbs timing.
_FLOW_REL_BAND = 0.15
_TTM_FY_MISMATCH_DAYS = 45
_DEBT_LEASE_CALIBER_NOTE = (
    "abstain: provider total_debt lease capitalization is not a single SEC concept; "
    "nearest funded/lease-inclusive reconstruction recorded only"
)

# SEC us-gaap concept priority lists. First concept with a usable annual window
# wins WITHIN a family, but families that can double-count (debt) sum components.
# Totals first, ASC-606 contract-revenue subset last (mirrors the edgar_provider
# fix, 2026-06-29): a financial issuer reports BOTH total Revenues and the ASC-606
# subset at the SAME period_end, so the strict-`>` recency tie in flow_annual keeps
# the first-iterated = total (MET Revenues 77B, not the 2.4B fee subset). Recency
# still wins across periods (AAPL's live revenue is ASC-606, newer).
_REVENUE_CONCEPTS = (
    "Revenues",
    "SalesRevenueNet",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
)
_COGS_CONCEPTS = ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold")
_GROSS_PROFIT_CONCEPTS = ("GrossProfit",)
_OPERATING_INCOME_CONCEPTS = ("OperatingIncomeLoss",)
_NET_INCOME_CONCEPTS = ("NetIncomeLoss", "ProfitLoss")
_DA_CONCEPTS = (
    "DepreciationDepletionAndAmortization",
    "DepreciationAmortizationAndAccretionNet",
    "DepreciationAndAmortization",
    "DepreciationAmortizationAndAccretionNetMaximum",
)
# Balance-sheet (instant) concepts. Debt is summed across long+short components,
# with whole-line fallbacks tried in order.
_LONG_TERM_DEBT_NONCURRENT = ("LongTermDebtNoncurrent",)
_LONG_TERM_DEBT_CURRENT = ("LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent")
_SHORT_TERM_BORROWINGS = ("ShortTermBorrowings", "DebtCurrent", "ShortTermDebt")
_LONG_TERM_DEBT_WHOLE = ("LongTermDebt", "LongTermDebtAndCapitalLeaseObligations")
_OPERATING_LEASE_LIABILITY = ("OperatingLeaseLiability",)
_CASH_CONCEPTS = (
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
)
# Short-term / current marketable securities. The street nets TOTAL liquid assets
# (cash + ST investments) in the EV bridge, and the providers do too, so SEC pure
# cash alone is the WRONG truth for "total_cash" (AAPL: cash 45.6B but cash+STI
# 68.5B == our value). Add the freshest of these to the cash concept when present.
_SHORT_TERM_INVESTMENT_CONCEPTS = (
    "ShortTermInvestments",
    "MarketableSecuritiesCurrent",
    "AvailableForSaleSecuritiesCurrent",
)
_PREFERRED_CONCEPTS = ("PreferredStockValue", "PreferredStockValueOutstanding")
_NCI_CONCEPTS = ("MinorityInterest", "MinorityInterestInVariableInterestEntity")


def _http_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": _SEC_UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=40, context=_SSL) as resp:  # noqa: S310
        return json.loads(resp.read().decode())


_TICKER_CIK_CACHE: dict[str, int] | None = None


def _ticker_cik_map() -> dict[str, int]:
    global _TICKER_CIK_CACHE
    if _TICKER_CIK_CACHE is None:
        raw = _http_json("https://www.sec.gov/files/company_tickers.json")
        _TICKER_CIK_CACHE = {v["ticker"]: int(v["cik_str"]) for v in raw.values()}
    return _TICKER_CIK_CACHE


def _days_old(period_end: str) -> int | None:
    try:
        end = date.fromisoformat(period_end)
    except ValueError:
        return None
    return (datetime.now(tz=timezone.utc).date() - end).days


def _is_stale_instant(period_end: str) -> bool:
    """True iff a balance instant is older than ``_STALE_INSTANT_DAYS`` (abandoned
    concept). An unparseable date is treated as stale (don't trust it as truth)."""
    age = _days_old(period_end)
    return age is None or age > _STALE_INSTANT_DAYS


def _ttm_fy_mismatch_note(our_period_end: date | None, sec_fy_end: str | None) -> str | None:
    """Explain when our TTM contains a newer quarter than the SEC FY baseline.

    In that case a large margin/flow gap is useful evidence but not a confirmed
    data bug: the probe lacks a same-caliber external TTM truth row.
    """
    if our_period_end is None or not sec_fy_end:
        return None
    try:
        sec_end = date.fromisoformat(sec_fy_end)
    except ValueError:
        return None
    days = (our_period_end - sec_end).days
    if days <= _TTM_FY_MISMATCH_DAYS:
        return None
    return (
        f"abstain: our TTM period_end {our_period_end.isoformat()} is {days} days newer "
        f"than SEC FY {sec_end.isoformat()}; no same-caliber external TTM baseline"
    )


def _is_full_year(start: str | None, end: str | None) -> bool:
    """True iff the row spans a full fiscal year (~12 months), so a quarter or a
    half-year cumulative window is never mistaken for the annual figure."""
    if not start or not end:
        return False
    try:
        d0 = date.fromisoformat(start)
        d1 = date.fromisoformat(end)
    except ValueError:
        return False
    days = (d1 - d0).days
    return 330 <= days <= 400


@dataclass
class _SecFact:
    value: float
    period_end: str
    concept: str


class _CompanyFacts:
    """One ticker's full us-gaap fact set from a single SEC companyfacts GET.

    Selection rules, used by the family helpers below:
      - flow_annual: freshest row with fp==FY (10-K/20-F) AND a full-year window;
        falls back to the freshest full-year-duration row if no FY tag is present.
      - balance_instant: freshest point-in-time (instant) row regardless of fp —
        the latest reported balance is the right point value for the EV bridge.
    """

    def __init__(self, gaap: dict[str, Any], available: bool, note: str | None = None) -> None:
        self._gaap = gaap
        self.available = available
        self.note = note

    @classmethod
    def fetch(cls, cik: int | None) -> "_CompanyFacts":
        if cik is None:
            return cls({}, available=False, note="no SEC CIK for ticker")
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
        try:
            payload = _http_json(url)
        except urllib.error.HTTPError as exc:
            return cls({}, available=False, note=f"SEC companyfacts HTTP {exc.code}")
        except Exception as exc:  # noqa: BLE001
            return cls({}, available=False, note=f"SEC companyfacts error: {type(exc).__name__}")
        gaap = payload.get("facts", {}).get("us-gaap", {})
        if not gaap:
            return cls({}, available=False, note="no us-gaap facts (foreign / IFRS filer)")
        return cls(gaap, available=True)

    def _usd_rows(self, concept: str) -> list[dict[str, Any]]:
        units = self._gaap.get(concept, {}).get("units", {})
        return list(units.get("USD", []))

    def flow_annual(self, concepts: tuple[str, ...]) -> _SecFact | None:
        """Freshest full-fiscal-year value across a concept priority list.

        Per-concept we take the freshest FY-tagged full-year row (or, lacking an FY
        tag, the freshest full-year-duration row), then across concepts keep the one
        whose period ends NEWEST — so an abandoned concept frozen years ago never
        wins over the live one (NVDA Revenues vs RevenueFromContract... lesson).

        A WINNER whose period_end is itself older than ``_STALE_INSTANT_DAYS`` means
        EVERY candidate concept was abandoned (Tesla DepreciationDepletion... froze
        at 2017) — a current 10-K window is always <15 months old — so return None
        and let the caller abstain rather than anchor a 2025 metric to a 2017 flow."""
        best: _SecFact | None = None
        for concept in concepts:
            rows = self._usd_rows(concept)
            fy = [
                r
                for r in rows
                if r.get("fp") == "FY"
                and r.get("form") in ("10-K", "20-F")
                and _is_full_year(r.get("start"), r.get("end"))
            ]
            cand = fy or [r for r in rows if _is_full_year(r.get("start"), r.get("end"))]
            if not cand:
                continue
            row = max(cand, key=lambda r: str(r.get("end", "")))
            fact = _SecFact(float(row["val"]), str(row.get("end", "")), concept)
            if best is None or fact.period_end > best.period_end:
                best = fact
        if best is not None and _is_stale_instant(best.period_end):
            return None
        return best

    def balance_instant(self, concepts: tuple[str, ...]) -> _SecFact | None:
        """Freshest NON-STALE point-in-time (instant) value across a concept list.

        Instant rows carry no ``start``; we take the freshest ``end`` per concept,
        then the newest across concepts. A concept whose freshest row is older than
        ``_STALE_INSTANT_DAYS`` is an abandoned tag (Ford LongTermDebtNoncurrent
        froze 2020, JPM PreferredStockValue 2009) — skip it so the truth lands on a
        live concept, not a years-stale frozen one. Returns None if EVERY candidate
        is stale (→ the caller abstains rather than shipping a frozen anchor)."""
        best: _SecFact | None = None
        for concept in concepts:
            rows = [r for r in self._usd_rows(concept) if not r.get("start")]
            if not rows:
                continue
            row = max(rows, key=lambda r: str(r.get("end", "")))
            period_end = str(row.get("end", ""))
            if _is_stale_instant(period_end):
                continue
            fact = _SecFact(float(row["val"]), period_end, concept)
            if best is None or fact.period_end > best.period_end:
                best = fact
        return best


@dataclass
class FieldRow:
    ticker: str
    field: str
    our_value: Any
    external_truth: Any
    caliber: str
    abs_diff: float | None
    rel_diff: float | None
    over_band: bool | None
    verdict: str  # pass | candidate_bug | abstain
    note: str | None = None


def _rel(a: float, b: float) -> float:
    denom = max(abs(a), abs(b))
    return 0.0 if denom == 0 else abs(a - b) / denom


def _abstain(ticker: str, field: str, our: Any, truth: Any, caliber: str, note: str) -> FieldRow:
    return FieldRow(ticker, field, our, truth, caliber, None, None, None, "abstain", note)


# ── margin family (ratios, the sharpest discriminator) ────────────────────────


def _margin_row(
    ticker: str,
    field: str,
    our: float | None,
    truth: float | None,
    caliber: str,
    *,
    suppressed_note: str | None = None,
    caliber_mismatch_note: str | None = None,
) -> FieldRow:
    """Compare a margin (our vs SEC-reconstructed) on an ABSOLUTE pp band.

    suppressed_note set → our None is intentional (bank gross margin) → abstain even
    if SEC could compute one. our None unintentionally while SEC has a margin →
    candidate "我们缺值"."""
    if our is None:
        if suppressed_note is not None:
            return _abstain(ticker, field, None, truth, caliber, suppressed_note)
        if truth is None:
            return _abstain(ticker, field, None, None, caliber, "both None (no baseline)")
        return FieldRow(
            ticker,
            field,
            None,
            truth,
            caliber,
            None,
            None,
            True,
            "candidate_bug",
            "our margin is None but SEC line items yield one (我们缺值)",
        )
    if truth is None:
        return _abstain(
            ticker, field, our, None, caliber, "no SEC components to reconstruct margin"
        )
    abs_diff = abs(our - truth)
    over = abs_diff > _MARGIN_ABS_BAND
    note = (
        f"margin gap {abs_diff * 100:.2f}pp "
        f"({'over' if over else 'within'} {_MARGIN_ABS_BAND * 100:.0f}pp band)"
    )
    verdict = "candidate_bug" if over else "pass"
    if over and caliber_mismatch_note is not None:
        if abs_diff > _MARGIN_OFFSET_ABSTAIN_CAP:
            # Over the band AND beyond anything a TTM-vs-FY offset can explain:
            # keep candidate_bug so a 30pp+ real bug can't hide behind the
            # window-offset exemption. The note keeps the offset context.
            note = (
                f"{note}; exceeds the {_MARGIN_OFFSET_ABSTAIN_CAP * 100:.0f}pp cap a "
                f"TTM-vs-FY offset can plausibly explain — review "
                f"({caliber_mismatch_note.removeprefix('abstain: ')})"
            )
        else:
            verdict = "abstain"
            note = f"{note}; {caliber_mismatch_note}"
    return FieldRow(
        ticker,
        field,
        round(our, 4),
        round(truth, 4),
        caliber,
        round(abs_diff, 4),
        round(_rel(our, truth), 4),
        over,
        verdict,
        note,
    )


# ── magnitude family (flows + balances, relative band) ────────────────────────


def _magnitude_row(
    ticker: str,
    field: str,
    our: float | None,
    truth: _SecFact | None,
    caliber: str,
    band: float,
    *,
    our_none_is_intended: str | None = None,
    caliber_mismatch_note: str | None = None,
) -> FieldRow:
    if truth is None:
        # SEC didn't report the concept. our None → abstain; our value → record-only.
        if our is None:
            return _abstain(ticker, field, None, None, caliber, "both None (SEC omits concept)")
        return _abstain(
            ticker, field, our, None, caliber, "no SEC baseline for concept — recorded only"
        )
    truth_v = truth.value
    cal = f"{caliber} (SEC {truth.concept} @ {truth.period_end})"
    if our is None:
        if our_none_is_intended is not None:
            return _abstain(ticker, field, None, truth_v, cal, our_none_is_intended)
        return FieldRow(
            ticker,
            field,
            None,
            truth_v,
            cal,
            None,
            None,
            True,
            "candidate_bug",
            f"our value is None but SEC reports {truth.concept} (我们缺值)",
        )
    rel = _rel(our, truth_v)
    over = rel > band
    note = f"rel gap {rel * 100:.1f}% ({'over' if over else 'within'} {band * 100:.0f}% band)"
    verdict = "candidate_bug" if over else "pass"
    if over and caliber_mismatch_note is not None:
        verdict = "abstain"
        note = f"{note}; {caliber_mismatch_note}"
    return FieldRow(
        ticker,
        field,
        our,
        truth_v,
        cal,
        abs(our - truth_v),
        round(rel, 4),
        over,
        verdict,
        note,
    )


# ── SEC-side derived truths ───────────────────────────────────────────────────


def _sec_gross_margin(cf: _CompanyFacts, rev: _SecFact | None) -> tuple[float | None, str]:
    """SEC annual gross margin = GrossProfit/Rev (preferred) or (Rev−COGS)/Rev."""
    if rev is None or rev.value == 0:
        return None, "no revenue"
    gp = cf.flow_annual(_GROSS_PROFIT_CONCEPTS)
    if gp is not None:
        return gp.value / rev.value, f"GrossProfit/Rev ({gp.concept}@{gp.period_end})"
    cogs = cf.flow_annual(_COGS_CONCEPTS)
    if cogs is not None:
        return (rev.value - cogs.value) / rev.value, f"(Rev−COGS)/Rev ({cogs.concept})"
    return None, "no GrossProfit or COGS concept"


def _sec_total_cash(cf: _CompanyFacts) -> _SecFact | None:
    """SEC total cash = CashAndCashEquivalents + short-term investments.

    Providers (and the EV bridge) net TOTAL liquid assets, not pure cash — so the
    truth must add current marketable securities, else cash-rich issuers (AAPL, KO)
    false-positive on a pure-cash baseline that excludes the ~$23B in ST securities
    the EV netting correctly includes.

    Returns None (→ caller abstains) when an issuer reports a SEPARATE ST-investment
    leg whose balance date diverges from cash by more than a quarter (NVDA: cash
    @2026-04 but MarketableSecuritiesCurrent last tagged @2025-10). Summing those
    mismatched dates, OR shipping cash-only against a provider total that includes
    the ST leg, both fabricate a false candidate — so the honest truth is "cannot
    cleanly reconstruct total liquidity from XBRL concepts here"."""
    cash = cf.balance_instant(_CASH_CONCEPTS)
    if cash is None:
        return None
    sti = cf.balance_instant(_SHORT_TERM_INVESTMENT_CONCEPTS)
    if sti is None:
        # No separate ST-investment concept — cash concept is the whole liquidity line.
        return cash
    if sti.period_end == cash.period_end:
        return _SecFact(cash.value + sti.value, cash.period_end, f"{cash.concept}+{sti.concept}")
    # Same-quarter drift (≤95d) is fine to sum; a wider gap means the issuer stopped
    # tagging the ST leg on the latest date → reconstruction is incomplete → abstain.
    d_cash, d_sti = _days_old(cash.period_end), _days_old(sti.period_end)
    if d_cash is not None and d_sti is not None and abs(d_cash - d_sti) <= 95:
        return _SecFact(cash.value + sti.value, cash.period_end, f"{cash.concept}+{sti.concept}~")
    return None


def _sec_total_debt(cf: _CompanyFacts) -> _SecFact | None:
    """SEC total debt = LongTermDebtNoncurrent + (current LTD or short-term
    borrowings), falling back to a whole-line LongTermDebt concept."""
    candidates = _sec_total_debt_candidates(cf)
    return candidates[0] if candidates else None


def _sec_total_debt_candidates(cf: _CompanyFacts) -> list[_SecFact]:
    """Acceptable SEC reconstructions for provider ``totalDebt``.

    Providers are not fully consistent on whether ``totalDebt`` capitalizes
    operating leases. Compare against funded debt first, plus a lease-inclusive
    alternate when SEC reports the lease leg on a comparable date. Concrete
    examples:

    - AAPL/TSLA reconcile to funded debt (adding operating leases overstates).
    - NVDA reconciles to funded debt + OperatingLeaseLiability.
    - Ford lacks fresh standard funded-debt concepts for its finance-sub debt;
      a lease-only row is NOT a debt baseline, so the probe abstains.
    """
    ltn = cf.balance_instant(_LONG_TERM_DEBT_NONCURRENT)
    cur = cf.balance_instant(_LONG_TERM_DEBT_CURRENT) or cf.balance_instant(_SHORT_TERM_BORROWINGS)
    candidates: list[_SecFact] = []
    if ltn is not None:
        total = ltn.value + (cur.value if cur is not None else 0.0)
        parts = ltn.concept + (f"+{cur.concept}" if cur is not None else "")
        candidates.append(_SecFact(total, ltn.period_end, parts))
    else:
        whole = cf.balance_instant(_LONG_TERM_DEBT_WHOLE)
        if whole is not None:
            total = whole.value + (cur.value if cur is not None else 0.0)
            parts = whole.concept + (f"+{cur.concept}" if cur is not None else "")
            candidates.append(_SecFact(total, whole.period_end, parts))
        elif cur is not None:
            candidates.append(cur)

    lease = cf.balance_instant(_OPERATING_LEASE_LIABILITY)
    if candidates and lease is not None:
        base = candidates[0]
        d_base, d_lease = _days_old(base.period_end), _days_old(lease.period_end)
        if d_base is not None and d_lease is not None and abs(d_base - d_lease) <= 95:
            candidates.append(
                _SecFact(
                    base.value + lease.value,
                    base.period_end,
                    f"{base.concept}+{lease.concept}",
                )
            )
    return candidates


def _best_sec_total_debt_for_our(cf: _CompanyFacts, our_debt: float | None) -> _SecFact | None:
    candidates = _sec_total_debt_candidates(cf)
    if not candidates:
        return None
    if our_debt is None:
        return candidates[0]
    return min(candidates, key=lambda fact: _rel(our_debt, fact.value))


# ── per-ticker probe ──────────────────────────────────────────────────────────


async def probe_ticker(
    deps_layer: Any, ticker: str, archetype: str, cik_map: dict[str, int]
) -> list[FieldRow]:
    rows: list[FieldRow] = []

    # --- our compute side (cache-first via DataLayer) ---
    fin = await deps_layer.fetch_canonical(DataType.FINANCIALS, ticker)
    price = await deps_layer.fetch_canonical(DataType.PRICE, ticker)
    fd = extract_financial_data(fin, price)

    rep = (fd.reporting_currency or "").upper()
    quote = (fd.quote_currency or "").upper()
    cross_ccy = bool(rep and quote and rep != quote)
    adr_note = f"cross-currency ADR (reporting={rep} quote={quote}): nulled by design"
    balance_sheet_financial = is_balance_sheet_financial(
        industry=fd.market.industry,
        sector=fd.market.sector,
    )

    # our derived values
    our_gross = fd.income.gross_margin
    our_op_margin = fd.income.operating_margin
    our_net_margin = (
        fd.income.net_income / fd.income.revenue
        if fd.income.net_income is not None and fd.income.revenue
        else None
    )
    our_ebitda_op = fd.valuation.ebitda_operating
    our_debt = fd.balance.total_debt
    our_cash = fd.balance.total_cash
    our_pref = fd.balance.preferred_stock
    our_nci = fd.balance.noncontrolling_interest
    our_ev = fd.valuation.enterprise_value
    our_mcap = fd.market.market_cap

    # --- external truth from SEC companyfacts (one free GET) ---
    cf = _CompanyFacts.fetch(cik_map.get(ticker))

    if not cf.available:
        base_note = cf.note or "no SEC us-gaap facts"
        # Margins are same-currency ratios; everything else abstains with no baseline.
        for f, our in (
            ("gross_margin", our_gross),
            ("operating_margin", our_op_margin),
            ("net_margin", our_net_margin),
            ("ebitda_operating", our_ebitda_op),
            ("total_debt", our_debt),
            ("total_cash", our_cash),
            ("preferred_stock", our_pref),
            ("noncontrolling_interest", our_nci),
        ):
            rows.append(_abstain(ticker, f, our, None, "SEC us-gaap", f"abstain: {base_note}"))
        rows.extend(_multiple_rows(ticker, fd, cross_ccy, adr_note))
        return rows

    rev = cf.flow_annual(_REVENUE_CONCEPTS)
    oi = cf.flow_annual(_OPERATING_INCOME_CONCEPTS)
    ni = cf.flow_annual(_NET_INCOME_CONCEPTS)
    da = cf.flow_annual(_DA_CONCEPTS)

    # margins reconstructed from SEC line items. Tag both periods so a TTM-vs-FY gap
    # on a fast-growing / loss-transition name is self-evident in the evidence (our
    # TTM swaps in a fresher quarter than the latest SEC full year).
    sec_gross, gross_basis = _sec_gross_margin(cf, rev)
    sec_op = (oi.value / rev.value) if (oi is not None and rev and rev.value) else None
    sec_net = (ni.value / rev.value) if (ni is not None and rev and rev.value) else None
    our_end = fin.period_end.isoformat() if fin.period_end else "?"
    rev_end = rev.period_end if rev is not None else "?"
    oi_end = oi.period_end if oi is not None else "?"
    ni_end = ni.period_end if ni is not None else "?"
    cal_suffix = f" [our TTM@{our_end} vs SEC FY]"
    rev_mismatch_note = _ttm_fy_mismatch_note(fin.period_end, rev.period_end if rev else None)
    oi_mismatch_note = _ttm_fy_mismatch_note(fin.period_end, oi.period_end if oi else None)
    ni_mismatch_note = _ttm_fy_mismatch_note(fin.period_end, ni.period_end if ni else None)

    is_bank = "bank" in archetype.lower()
    rows.append(
        _margin_row(
            ticker,
            "gross_margin",
            our_gross,
            sec_gross,
            f"SEC annual {gross_basis}{cal_suffix}",
            suppressed_note="bank: gross margin suppressed by design (no COGS)"
            if is_bank
            else None,
            caliber_mismatch_note=rev_mismatch_note,
        )
    )
    rows.append(
        _margin_row(
            ticker,
            "operating_margin",
            our_op_margin,
            sec_op,
            f"SEC annual OI/Rev (OI@{oi_end} ÷ Rev@{rev_end}){cal_suffix}",
            caliber_mismatch_note=oi_mismatch_note or rev_mismatch_note,
        )
    )
    rows.append(
        _margin_row(
            ticker,
            "net_margin",
            our_net_margin,
            sec_net,
            f"SEC annual NI/Rev (NI@{ni_end} ÷ Rev@{rev_end}){cal_suffix}",
            caliber_mismatch_note=ni_mismatch_note or rev_mismatch_note,
        )
    )

    # EBITDA_operating = SEC OperatingIncomeLoss + D&A (annual flow)
    sec_ebitda_op: _SecFact | None = None
    if oi is not None and da is not None:
        sec_ebitda_op = _SecFact(oi.value + da.value, oi.period_end, "OperatingIncomeLoss+D&A")
    rows.append(
        _magnitude_row(
            ticker,
            "ebitda_operating",
            our_ebitda_op,
            sec_ebitda_op,
            f"annual flow{cal_suffix}",
            _FLOW_REL_BAND,
            caliber_mismatch_note=oi_mismatch_note,
        )
    )

    # EV bridge components (balance instants). On a cross-currency ADR our balance
    # items are FX-converted to quote ccy at the canonical gate while SEC reports
    # reporting ccy — so a magnitude compare would be apples-to-oranges → abstain.
    if cross_ccy:
        for f, our in (
            ("total_debt", our_debt),
            ("total_cash", our_cash),
            ("preferred_stock", our_pref),
            ("noncontrolling_interest", our_nci),
        ):
            rows.append(
                _abstain(
                    ticker,
                    f,
                    our,
                    None,
                    "SEC balance instant",
                    f"abstain: {adr_note} — SEC reports {rep}, our balance is {quote}",
                )
            )
    elif balance_sheet_financial:
        for f, our in (
            ("total_debt", our_debt),
            ("total_cash", our_cash),
            ("preferred_stock", our_pref),
            ("noncontrolling_interest", our_nci),
        ):
            rows.append(
                _abstain(
                    ticker,
                    f,
                    our,
                    None,
                    "SEC balance instant",
                    "abstain: balance-sheet financial — debt/cash/float are operating "
                    "raw material, not a non-financial EV bridge",
                )
            )
    else:
        sec_debt = _best_sec_total_debt_for_our(cf, our_debt)
        sec_cash = _sec_total_cash(cf)
        sec_pref = cf.balance_instant(_PREFERRED_CONCEPTS)
        sec_nci = cf.balance_instant(_NCI_CONCEPTS)
        rows.append(
            _magnitude_row(
                ticker,
                "total_debt",
                our_debt,
                sec_debt,
                "balance instant",
                _BALANCE_REL_BAND,
                caliber_mismatch_note=_DEBT_LEASE_CALIBER_NOTE,
            )
        )
        rows.append(
            _magnitude_row(
                ticker, "total_cash", our_cash, sec_cash, "balance instant", _BALANCE_REL_BAND
            )
        )
        # preferred / NCI: our None when SEC also omits = abstain; the ownership fix
        # (commit 30f1e5d0) means our None must align with SEC's absence.
        rows.append(
            _magnitude_row(
                ticker, "preferred_stock", our_pref, sec_pref, "balance instant", _BALANCE_REL_BAND
            )
        )
        rows.append(
            _magnitude_row(
                ticker,
                "noncontrolling_interest",
                our_nci,
                sec_nci,
                "balance instant",
                _BALANCE_REL_BAND,
            )
        )

    # EV total: cross-check our EV against the SEC-reconstructed bridge
    # (market_cap + debt − cash + preferred + NCI) only when single-currency and all
    # legs present, so the bridge isn't built on fabricated zeros.
    if not cross_ccy and our_ev is not None and our_mcap is not None:
        sec_debt2 = _best_sec_total_debt_for_our(cf, our_debt)
        sec_cash2 = _sec_total_cash(cf)
        if sec_debt2 is not None and sec_cash2 is not None:
            sec_pref2 = cf.balance_instant(_PREFERRED_CONCEPTS)
            sec_nci2 = cf.balance_instant(_NCI_CONCEPTS)
            sec_ev = (
                our_mcap
                + sec_debt2.value
                - sec_cash2.value
                + (sec_pref2.value if sec_pref2 else 0.0)
                + (sec_nci2.value if sec_nci2 else 0.0)
            )
            rel = _rel(our_ev, sec_ev)
            over = rel > _BALANCE_REL_BAND
            rows.append(
                FieldRow(
                    ticker,
                    "enterprise_value",
                    our_ev,
                    sec_ev,
                    "our_mcap + SEC(debt − cash + pref + NCI)",
                    abs(our_ev - sec_ev),
                    round(rel, 4),
                    over,
                    "candidate_bug" if over else "pass",
                    f"EV bridge rel gap {rel * 100:.1f}% (same mcap, SEC balance legs)",
                )
            )
    elif cross_ccy:
        rows.append(
            _abstain(ticker, "enterprise_value", our_ev, None, "EV bridge", f"abstain: {adr_note}")
        )

    rows.extend(_multiple_rows(ticker, fd, cross_ccy, adr_note))
    return rows


def _multiple_rows(ticker: str, fd: Any, cross_ccy: bool, adr_note: str) -> list[FieldRow]:
    """Current multiples (PE / EV-EBITDA / EV-Revenue): NO external equality truth.

    Record our value; flag only the intended-None traps. A live multiple has no
    as-reported SEC truth, so a numeric value is recorded as pass-by-record; None on
    an ADR is pass-by-abstain (intended), None on a non-ADR with the inputs present
    is a candidate (a multiple that should exist but is missing)."""
    rows: list[FieldRow] = []
    specs = (
        ("pe_ratio", fd.market.pe_ratio),
        ("ev_ebitda", fd.valuation.ev_ebitda),
        ("ev_revenue", fd.valuation.ev_revenue),
    )
    for field, val in specs:
        if val is None:
            note = (
                adr_note if cross_ccy else "None — inputs withheld upstream (no EV / cross-ccy PE)"
            )
            rows.append(_abstain(ticker, field, None, "no-absolute-truth", "live multiple", note))
        else:
            rows.append(
                FieldRow(
                    ticker,
                    field,
                    round(val, 3),
                    "no-absolute-truth",
                    "live multiple",
                    None,
                    None,
                    False,
                    "pass",
                    "recorded (no external equality asserted)",
                )
            )
    return rows


# ── orchestration ─────────────────────────────────────────────────────────────


async def build_layer() -> Any:
    ensure_home()
    settings = get_settings(**load_non_secret_settings(SETTINGS_JSON))
    store, _ = create_secret_store()
    settings = await hydrate_settings_from_secrets(settings, store)
    return build_data_layer(settings)


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        if abs(v) >= 1e9:
            return f"{v / 1e9:,.3f}B"
        if abs(v) >= 1e6:
            return f"{v / 1e6:,.2f}M"
        return f"{v:,.4g}"
    return str(v)


def summarize(rows: list[FieldRow]) -> dict[str, Any]:
    candidates = [r for r in rows if r.verdict == "candidate_bug"]
    return {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "total": len(rows),
        "pass": sum(1 for r in rows if r.verdict == "pass"),
        "candidate_bug": len(candidates),
        "abstain": sum(1 for r in rows if r.verdict == "abstain"),
        "candidates": [asdict(r) for r in candidates],
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tickers", nargs="*", help="subset (default: whole basket)")
    args = parser.parse_args()

    basket = [(t.upper(), "(cli subset)") for t in args.tickers] if args.tickers else list(BASKET)
    cik_map = _ticker_cik_map()
    layer = await build_layer()
    all_rows: list[FieldRow] = []
    try:
        for ticker, archetype in basket:
            print(f"--- probing {ticker} ({archetype}) ---")
            try:
                rows = await probe_ticker(layer, ticker, archetype, cik_map)
            except Exception as exc:  # noqa: BLE001 — record, never abort the basket
                rows = [
                    FieldRow(
                        ticker,
                        "(ticker)",
                        None,
                        None,
                        "—",
                        None,
                        None,
                        None,
                        "abstain",
                        f"probe error: {type(exc).__name__}: {exc}",
                    )
                ]
            all_rows.extend(rows)
    finally:
        # Non-server entrypoint: join the aiosqlite workers + checkpoint WAL so the
        # process exits cleanly instead of hanging on "Event loop is closed" (2026-06-24).
        from finrobot.engine.data.factory import shutdown_data_layer

        await shutdown_data_layer(layer)

    summary = summarize(all_rows)
    RESULTS_PATH.write_text(
        json.dumps(
            {"summary": summary, "rows": [asdict(r) for r in all_rows]},
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        f"\nPASS={summary['pass']}  CANDIDATE_BUG={summary['candidate_bug']}  "
        f"ABSTAIN={summary['abstain']}  (total {summary['total']})"
    )
    if summary["candidates"]:
        print("\n-- CANDIDATE BUGS (do not reconcile to SEC truth) --")
        print(f"  {'ticker':6s} {'field':22s} {'our':>14s} {'SEC truth':>14s}  note")
        for c in summary["candidates"]:
            print(
                f"  {c['ticker']:6s} {c['field']:22s} {_fmt(c['our_value']):>14s} "
                f"{_fmt(c['external_truth']):>14s}  {c['note']}"
            )
    print(f"\nresults persisted: {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
