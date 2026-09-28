"""External-truth × stock-basket × every-report-field verification harness.

Compares FinRobot's OWN compute output against the independent external-truth
anchor (``specs/外部真值锚-报告字段验证.json``, built by
``scripts/build_truth_anchor.py``). Four caliber-aware verifier paths, one row per
field — ``field | external_baseline | caliber | our_value | consistent?``:

  (a) LIVE quantities (price / market_cap) — our value is the live FINANCIALS
      market block; baseline is FMP /profile. Memory weight on a live quantity is
      0; the only legal bug signal is external-source vs system. 5% tolerance.
  (b) FUNDAMENTALS (revenue / net_income / shares) — our value is the served
      FINANCIALS (FMP TTM, SEC-cross-checked); baseline is SEC 10-K XBRL annual FY.
      The caliber differs ON PURPOSE (TTM vs annual FY); the 15% / 15% / 1% bands
      absorb up to a quarter of timing drift, so a within-band gap is a caliber
      offset, NOT a data error. Over-band → a candidate bug.
  (c) VALUATION — NO absolute truth. We do NOT assert price == anything. Instead we
      read the deterministic reverse-DCF the pipeline already computed
      (DCFResult.market_implied.implied_growth) and flag it only if financially
      absurd (sustained growth far outside any plausible range, or growth-
      unreachable = option-value). Plus the published price_target trap: when the
      audit gate withholds valuation, ThesisResult.price_target is None BY DESIGN
      (intended abstain, NOT a mismatch).
  (d) ENTITIES (CEO) — our value is compute_ownership_governance(...).ceo_name (the
      Form-4 officer-title override); baseline is the same Form-4 source pulled
      independently into the anchor. Both abstain (None) when no in-window Form-4
      carries a CEO title — None == None is PASS-by-abstain.

Two MANDATORY traps so we don't emit FALSE mismatches:
  * price_target None under a withholding gate = intended abstain → PASS.
  * cross-currency ADR (reporting != quote): EV / PE deliberately nulled → None is
    PASS-by-abstain, never "inconsistent".

Persists every run to ``specs/verify_field_basket_results.json`` so a future commit
cannot silently break an already-passing field (historical regression).

Run:  uv run python scripts/verify_report_field_basket.py
      uv run python scripts/verify_report_field_basket.py AAPL NVDA   # subset
      uv run python scripts/verify_report_field_basket.py --no-pipeline  # skip (c)

Economical: the pipeline + extract + ownership all ride DataLayer's per-ticker
canonical cache, so SEC/FMP are hit once per ticker. Live FMP /profile is read
from the anchor file (already pulled) — this harness makes 0 extra /profile calls.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from finrobot.config import get_settings
from finrobot.engine.agents.factory import create_sub_agents
from finrobot.engine.compute.coordinators.extractor import extract_financial_data
from finrobot.engine.compute.operators.ownership import compute_ownership_governance
from finrobot.engine.data.factory import build_data_layer
from finrobot.engine.data.types import DataType
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.models.financial import DCFResult, ThesisResult
from finrobot.engine.models.sec import OwnershipGovernanceAnalysis
from finrobot.engine.pipelines.registry import get_pipeline_factories
from finrobot.engine.skills.registry import SkillRegistry
from finrobot.paths import SETTINGS_JSON, ensure_home
from finrobot.routes.settings import load_non_secret_settings
from finrobot.secret_store import create_secret_store
from finrobot.server import hydrate_settings_from_secrets

_HERE = Path(__file__).resolve().parent.parent
ANCHOR_PATH = _HERE / "specs" / "外部真值锚-报告字段验证.json"
RESULTS_PATH = _HERE / "specs" / "verify_field_basket_results.json"

# Validator tolerances — copied from finrobot/engine/data/validator.py so the
# harness shares the system's own thresholds (no parallel tolerance definition).
_TOL = {
    "revenue": 0.15,
    "net_income": 0.15,
    "shares_outstanding": 0.05,  # cover-page vs price-consistent count (multi-class drift)
    "current_price": 0.05,
    "market_cap": 0.05,
}

# A flat constant annual revenue growth above this, SUSTAINED over the horizon, is
# the threshold at which the reverse-DCF implied growth is "financially absurd" for
# a mature/large issuer — a sanity flag, NOT an equality assertion. Calibrated to
# Damodaran's observation that >~40%/yr revenue CAGR over 5y is reached by a
# vanishing fraction of public companies.
_IMPLIED_GROWTH_ABSURD = 0.40
_LIVE_ANCHOR_MAX_AGE = timedelta(hours=6)
_SHARES_ANCHOR_MAX_AGE = timedelta(days=120)


@dataclass
class FieldRow:
    ticker: str
    path: str  # a | b | c | d
    field: str
    external_baseline: Any
    caliber: str
    our_value: Any
    consistent: bool | None  # None = abstain (intended-None / no baseline)
    rel_diff: float | None = None
    note: str | None = None
    needs_human: bool = False  # [金融待核]


def _rel(a: float, b: float) -> float:
    denom = max(abs(a), abs(b))
    return 0.0 if denom == 0 else abs(a - b) / denom


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        if abs(value) >= 1e9:
            return f"{value / 1e9:,.3f}B"
        if abs(value) >= 1e6:
            return f"{value / 1e6:,.3f}M"
        return f"{value:,.4g}"
    return str(value)


def _names_match(a: str | None, b: str | None) -> bool:
    """CEO-name equality ignoring order / case / middle-initial punctuation.

    SEC Form-4 names vary in surface form ("Musk Elon" vs "Elon Musk", "Jen Hsun
    Huang" vs "Jensen Huang"). We compare on the set of significant tokens so the
    same person isn't flagged a mismatch over field-order or punctuation. Returns
    True iff the smaller token set is a subset of the larger (handles middle-name
    presence/absence) and they share the surname.
    """
    if not a or not b:
        return False
    ta = {t.strip(".").lower() for t in a.replace(",", " ").split() if t.strip(".")}
    tb = {t.strip(".").lower() for t in b.replace(",", " ").split() if t.strip(".")}
    if not ta or not tb:
        return False
    small, large = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    # Require ≥2 shared tokens (given + family) OR a subset relationship.
    return small <= large or len(ta & tb) >= 2


# ── (a) live + (b) fundamentals: from the served FINANCIALS / PRICE ───────────


async def _financial_rows(
    deps: FinRobotDeps, ticker: str, anchor: dict[str, Any]
) -> tuple[list[FieldRow], dict[str, Any]]:
    fin = await deps.data_layer.fetch_canonical(DataType.FINANCIALS, ticker)
    price = await deps.data_layer.fetch_canonical(DataType.PRICE, ticker)
    fd = extract_financial_data(fin, price)
    sec_facts = await _safe_sec(deps, ticker, DataType.XBRL_FACTS)

    our = {
        "current_price": fd.market.current_price,
        "market_cap": fd.market.market_cap,
        "revenue": fd.income.revenue,
        "net_income": fd.income.net_income,
        "shares_outstanding": fd.market.shares_outstanding,
    }
    rows: list[FieldRow] = []

    # (a) LIVE — price / market_cap. Memory weight 0; baseline is FMP /profile.
    for field in ("current_price", "market_cap"):
        rows.append(_compare(ticker, "a", field, anchor.get(field), our[field]))
    # (b) FUNDAMENTALS — revenue / net_income prefer SEC TTM XBRL; fall back to
    # the static annual-FY anchor only as a coarse smoke signal.
    for field in ("revenue", "net_income", "shares_outstanding"):
        ttm_anchor = _sec_ttm_anchor(sec_facts, field)
        rows.append(
            _compare(
                ticker,
                "b",
                field,
                ttm_anchor or anchor.get(field),
                our[field],
                annual_fundamental_fallback=ttm_anchor is None
                and field in ("revenue", "net_income"),
            )
        )

    meta = {
        "reporting_currency": fd.reporting_currency,
        "quote_currency": fd.quote_currency,
    }
    return rows, meta


def _compare(
    ticker: str,
    path: str,
    field: str,
    anchor_field: dict[str, Any] | None,
    our: Any,
    *,
    annual_fundamental_fallback: bool = False,
) -> FieldRow:
    baseline = anchor_field.get("value") if anchor_field else None
    caliber = anchor_field.get("caliber") if anchor_field else "(no anchor)"
    note = anchor_field.get("note") if anchor_field else None
    as_of = _parse_anchor_as_of(anchor_field.get("as_of") if anchor_field else None)

    if path == "a" and _anchor_is_stale(as_of, _LIVE_ANCHOR_MAX_AGE):
        as_of_text = as_of.isoformat() if as_of else "missing"
        return FieldRow(
            ticker,
            path,
            field,
            baseline,
            caliber or "(none)",
            our,
            consistent=None,
            note=(
                f"abstain: static live anchor as_of={as_of_text} is older than "
                f"{_LIVE_ANCHOR_MAX_AGE}; refresh the anchor before validating a live {field}"
            ),
        )

    if baseline is None:
        # No external baseline (foreign 20-F has no us-gaap concept, etc.) → abstain.
        return FieldRow(
            ticker,
            path,
            field,
            None,
            caliber or "(none)",
            our,
            consistent=None,
            note=f"abstain: {note}" if note else "abstain: no baseline",
        )
    if our is None:
        return FieldRow(
            ticker,
            path,
            field,
            baseline,
            caliber or "(none)",
            None,
            consistent=False,
            note="our value is None but baseline exists",
        )
    try:
        rel = _rel(float(baseline), float(our))
    except (TypeError, ValueError):
        return FieldRow(
            ticker,
            path,
            field,
            baseline,
            caliber or "(none)",
            our,
            consistent=None,
            note="non-numeric — compared manually",
        )
    tol = _TOL.get(field, 0.10)
    caliber_note = None
    if path == "b" and field in ("revenue", "net_income"):
        caliber_note = "baseline=SEC XBRL TTM; our=TTM"
        if annual_fundamental_fallback:
            caliber_note = (
                "baseline=annual FY (SEC XBRL); our=TTM — no same-period SEC TTM "
                "baseline was available"
            )
    if annual_fundamental_fallback and rel > tol:
        return FieldRow(
            ticker,
            path,
            field,
            baseline,
            caliber or "(none)",
            our,
            consistent=None,
            rel_diff=round(rel, 4),
            note=(
                f"{caliber_note}; gap exceeds {tol:.0%}, so this is a human-review "
                "caliber offset, not an automatic bug"
            ),
            needs_human=True,
        )
    if (
        path == "b"
        and field == "shares_outstanding"
        and _anchor_is_stale(as_of, _SHARES_ANCHOR_MAX_AGE)
        and rel > tol
    ):
        as_of_text = as_of.date().isoformat() if as_of else "missing"
        return FieldRow(
            ticker,
            path,
            field,
            baseline,
            caliber or "(none)",
            our,
            consistent=None,
            rel_diff=round(rel, 4),
            note=(
                f"SEC share-count anchor as_of={as_of_text} is older than "
                f"{_SHARES_ANCHOR_MAX_AGE.days}d while our value is current-market; "
                "inspect manually, not an automatic bug"
            ),
            needs_human=True,
        )
    return FieldRow(
        ticker,
        path,
        field,
        baseline,
        caliber or "(none)",
        our,
        consistent=rel <= tol,
        rel_diff=round(rel, 4),
        note=caliber_note,
    )


def _sec_ttm_anchor(sec_facts: dict[str, Any], field: str) -> dict[str, Any] | None:
    key = {"revenue": "ttm_revenue", "net_income": "ttm_net_income"}.get(field)
    if key is None:
        return None
    fact = sec_facts.get(key)
    if not isinstance(fact, dict) or fact.get("value") is None:
        return None
    concept = fact.get("concept") or "SEC XBRL"
    period_end = fact.get("period_end")
    warning = fact.get("warning")
    return {
        "value": fact.get("value"),
        "caliber": f"SEC XBRL TTM ({concept})",
        "source_url": "edgartools:xbrl_facts",
        "as_of": period_end,
        "note": warning,
    }


def _parse_anchor_as_of(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    text = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(f"{text}T00:00:00+00:00")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _anchor_is_stale(as_of: datetime | None, max_age: timedelta) -> bool:
    if as_of is None:
        return True
    return datetime.now(tz=timezone.utc) - as_of > max_age


# ── (d) entities: CEO from the ownership operator ─────────────────────────────


async def _ceo_row(deps: FinRobotDeps, ticker: str, anchor: dict[str, Any]) -> FieldRow:
    insider = await _safe_sec(deps, ticker, DataType.INSIDER_TRADES, days=90)
    proxy = await _safe_sec(deps, ticker, DataType.PROXY_STATEMENT)
    analysis = compute_ownership_governance(
        insider_data=insider, institutional_data=None, proxy_data=proxy
    )
    our_ceo: str | None = None
    if isinstance(analysis, OwnershipGovernanceAnalysis) and analysis.proxy_compensation:
        our_ceo = analysis.proxy_compensation.ceo_name

    ceo_anchor = anchor.get("ceo") or {}
    baseline = ceo_anchor.get("value")
    caliber = ceo_anchor.get("caliber", "SEC Form-4 officer title")

    if baseline is None and our_ceo is None:
        # Both abstain — no in-window Form-4 with a CEO title (KO/F, or foreign).
        return FieldRow(
            ticker,
            "d",
            "ceo",
            None,
            caliber,
            None,
            consistent=None,
            note="abstain: no Form-4 CEO title in window (both None)",
        )
    if baseline is None:
        return FieldRow(
            ticker,
            "d",
            "ceo",
            None,
            caliber,
            our_ceo,
            consistent=None,
            note="anchor abstained (no Form-4 CEO title); our value from proxy fallback",
        )
    consistent = _names_match(baseline, our_ceo)
    return FieldRow(
        ticker,
        "d",
        "ceo",
        baseline,
        caliber,
        our_ceo,
        consistent=consistent,
        note=None if consistent else "Form-4 CEO name differs from our resolved name",
    )


async def _safe_sec(
    deps: FinRobotDeps, ticker: str, data_type: DataType, **kwargs: Any
) -> dict[str, Any]:
    try:
        result = await deps.data_layer.fetch(data_type, ticker, **kwargs)
        return result.data if result.data else {"available": False}
    except Exception as exc:  # noqa: BLE001 — optional SEC data, never fatal
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}


# ── (c) valuation: price_target trap + reverse-DCF implied growth sanity ───────


def _find(structured: dict[str, object], cls: type) -> Any:
    for v in structured.values():
        if isinstance(v, cls):
            return v
    return None


def _valuation_rows(ticker: str, structured: dict[str, object]) -> list[FieldRow]:
    rows: list[FieldRow] = []
    thesis = _find(structured, ThesisResult)
    dcf = _find(structured, DCFResult)

    # price_target trap: None under a withholding gate = intended abstain → PASS.
    if isinstance(thesis, ThesisResult):
        pt = thesis.price_target
        if pt is None:
            rows.append(
                FieldRow(
                    ticker,
                    "c",
                    "price_target",
                    "no-absolute-truth",
                    "published target",
                    None,
                    consistent=None,
                    note=f"abstain BY DESIGN: gate withheld valuation "
                    f"(recommendation={thesis.recommendation!r}) — None is intended, not a miss",
                )
            )
        else:
            # We do NOT assert price_target == any external number (there is no
            # truth for a forward target). We only record it + its basis.
            rows.append(
                FieldRow(
                    ticker,
                    "c",
                    "price_target",
                    "no-absolute-truth",
                    "published target",
                    round(pt, 2),
                    consistent=None,
                    note=f"recorded (no equality asserted); basis={thesis.price_target_basis!r}",
                )
            )

    # Reverse-DCF implied growth: flag ONLY if financially absurd. Never equality.
    if isinstance(dcf, DCFResult) and dcf.market_implied is not None:
        mi = dcf.market_implied
        if mi.growth_unreachable:
            rows.append(
                FieldRow(
                    ticker,
                    "c",
                    "implied_growth",
                    "reverse-DCF",
                    "market-implied (live price)",
                    None,
                    consistent=None,
                    note=f"option-value: price unreachable even at "
                    f"{(mi.growth_ceiling or 0) * 100:.0f}% growth (ceiling ${mi.ceiling_price}) "
                    f"— DCF cannot explain the price; intended, not a bug",
                )
            )
        elif mi.implied_growth is not None:
            absurd = mi.implied_growth > _IMPLIED_GROWTH_ABSURD
            rows.append(
                FieldRow(
                    ticker,
                    "c",
                    "implied_growth",
                    "reverse-DCF",
                    "market-implied (live price)",
                    f"{mi.implied_growth * 100:.1f}%",
                    consistent=not absurd,
                    note=(
                        f"ABSURD: market prices in >{_IMPLIED_GROWTH_ABSURD * 100:.0f}%/yr "
                        f"sustained revenue growth — implausible, inspect inputs"
                        if absurd
                        else f"plausible: market implies {mi.implied_growth * 100:.1f}%/yr growth"
                    ),
                    needs_human=absurd,
                )
            )
    return rows


# ── ADR EV/PE intended-None trap ──────────────────────────────────────────────


def _adr_abstain_row(ticker: str, meta: dict[str, Any]) -> FieldRow | None:
    rep = (meta.get("reporting_currency") or "").upper()
    quote = (meta.get("quote_currency") or "").upper()
    if rep and quote and rep != quote:
        return FieldRow(
            ticker,
            "c",
            "ev_ebitda/pe",
            "n/a (mixed currency)",
            f"reporting={rep} quote={quote}",
            None,
            consistent=None,
            note="cross-currency ADR: EV/PE deliberately nulled — None is PASS-by-abstain",
        )
    return None


# ── orchestration ─────────────────────────────────────────────────────────────


async def build_deps() -> FinRobotDeps:
    ensure_home()
    settings = get_settings(**load_non_secret_settings(SETTINGS_JSON))
    store, _ = create_secret_store()
    settings = await hydrate_settings_from_secrets(settings, store)
    settings.validate_runtime_config()
    skills_path = Path(settings.skills_dir)
    registry = SkillRegistry(skills_path) if skills_path.exists() else None
    return FinRobotDeps(
        data_layer=build_data_layer(settings), settings=settings, skill_runtime=registry
    )


async def verify_ticker(
    deps: FinRobotDeps, ticker: str, anchor: dict[str, Any], run_pipeline: bool
) -> list[FieldRow]:
    rows: list[FieldRow] = []
    fin_rows, meta = await _financial_rows(deps, ticker, anchor)
    rows.extend(fin_rows)
    rows.append(await _ceo_row(deps, ticker, anchor))

    adr_row = _adr_abstain_row(ticker, meta)
    if adr_row is not None:
        rows.append(adr_row)

    if run_pipeline:
        sub_agents = create_sub_agents(deps.settings, skill_registry=deps.skill_runtime)
        pipeline = get_pipeline_factories()["research"](sub_agents)
        try:
            result = await pipeline.execute(deps, ticker, lang="en")
            rows.extend(_valuation_rows(ticker, result.structured_data))
        except Exception as exc:  # noqa: BLE001
            rows.append(
                FieldRow(
                    ticker,
                    "c",
                    "pipeline",
                    "—",
                    "—",
                    None,
                    consistent=None,
                    note=f"pipeline error: {type(exc).__name__}: {exc}",
                )
            )
    return rows


def print_table(rows: list[FieldRow]) -> None:
    print("\n" + "=" * 118)
    print(
        f"  {'ticker':6s} {'p':2s} {'field':18s} {'baseline':>16s}  "
        f"{'our_value':>16s}  {'consistent':11s} caliber / note"
    )
    print("=" * 118)
    for r in rows:
        cons = "ABSTAIN" if r.consistent is None else ("PASS ✓" if r.consistent else "FAIL ✗")
        if r.needs_human:
            cons = "金融待核"
        rel = f" ({r.rel_diff:.2%})" if r.rel_diff is not None else ""
        cal = r.caliber if r.consistent is not None else (r.note or r.caliber)
        print(
            f"  {r.ticker:6s} {r.path:2s} {r.field:18s} {_fmt(r.external_baseline):>16s}  "
            f"{_fmt(r.our_value):>16s}  {cons:11s} {cal[:48]}{rel}"
        )
    print("=" * 118)


def summarize(rows: list[FieldRow]) -> dict[str, Any]:
    mismatches = [r for r in rows if r.consistent is False]
    needs_human = [r for r in rows if r.needs_human]
    return {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "total": len(rows),
        "pass": sum(1 for r in rows if r.consistent is True),
        "fail": len(mismatches),
        "abstain": sum(1 for r in rows if r.consistent is None),
        "needs_human": len(needs_human),
        "mismatches": [asdict(r) for r in mismatches],
        "needs_human_rows": [asdict(r) for r in needs_human],
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tickers", nargs="*", help="subset (default: whole anchor basket)")
    parser.add_argument("--no-pipeline", action="store_true", help="skip path (c) pipeline run")
    args = parser.parse_args()

    if not ANCHOR_PATH.exists():
        print(f"anchor missing: {ANCHOR_PATH} — run scripts/build_truth_anchor.py first")
        return 2
    anchor_all = json.loads(ANCHOR_PATH.read_text(encoding="utf-8"))
    basket = args.tickers or [t for t in anchor_all if not t.startswith("__")]

    deps = await build_deps()
    all_rows: list[FieldRow] = []
    try:
        for ticker in basket:
            ticker = ticker.upper()
            anchor = anchor_all.get(ticker)
            if anchor is None:
                print(f"{ticker}: not in anchor — skipped")
                continue
            print(f"\n--- verifying {ticker} ({anchor.get('__archetype__', '?')}) ---")
            rows = await verify_ticker(deps, ticker, anchor, run_pipeline=not args.no_pipeline)
            all_rows.extend(rows)
    finally:
        await deps.data_layer.close()

    print_table(all_rows)
    summary = summarize(all_rows)
    print(
        f"\nPASS={summary['pass']}  FAIL={summary['fail']}  "
        f"ABSTAIN={summary['abstain']}  金融待核={summary['needs_human']}  (total {summary['total']})"
    )
    if summary["mismatches"]:
        print("\n-- MISMATCHES (candidate bugs for the orchestrator) --")
        for m in summary["mismatches"]:
            print(
                f"  {m['ticker']:6s} [{m['path']}] {m['field']}: "
                f"baseline={_fmt(m['external_baseline'])} our={_fmt(m['our_value'])} "
                f"| {m['note']}"
            )

    RESULTS_PATH.write_text(
        json.dumps(
            {"summary": summary, "rows": [asdict(r) for r in all_rows]},
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nresults persisted: {RESULTS_PATH}")
    # Exit non-zero only on a genuine FAIL (abstain / 金融待核 are not failures).
    return 1 if summary["fail"] else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
