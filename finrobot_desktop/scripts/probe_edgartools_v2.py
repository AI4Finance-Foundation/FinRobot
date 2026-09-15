"""门 1 二轮 probe — 用 deep introspection 找到的真实 API 补齐 fixture。

v1 probe 发现 spec §5 大量 API 假设错的。本脚本用正确 API：
  - 章节走 .business / .risk_factors / .management_discussion attribute
  - 10-Q 用 c.get_filings(form="10-Q").latest(N)
  - 8-K obj() 返回 CurrentReport（不是 EightK），.items 是 list[str]
  - Form 4 .common_stock_sales / .get_transaction_activities()
  - XBRL 用 .get_revenue() / .get_concept(tag) typed getter

运行：
    EDGAR_IDENTITY="..." uv run python -m scripts.probe_edgartools_v2
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("probe_v2")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

FIXTURES_DIR = Path("tests/fixtures/edgar")
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)


def _json_safe(o: Any) -> Any:
    if hasattr(o, "isoformat"):
        return o.isoformat()
    if hasattr(o, "model_dump"):
        return o.model_dump(mode="json")
    if hasattr(o, "to_dict"):
        return o.to_dict()
    if isinstance(o, dict):
        return {k: _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    if hasattr(o, "__dict__"):
        return {k: _json_safe(v) for k, v in o.__dict__.items() if not k.startswith("_")}
    return o


def write_json(name: str, data: Any) -> None:
    p = FIXTURES_DIR / name
    p.write_text(json.dumps(_json_safe(data), indent=2, ensure_ascii=False, default=str))
    logger.info("  → wrote %s (%d bytes)", p, p.stat().st_size)


def main() -> int:
    identity = os.environ.get("EDGAR_IDENTITY", "").strip()
    if " " not in identity or "@" not in identity:
        logger.error("set EDGAR_IDENTITY='Name email@domain'")
        return 2

    from edgar import Company, set_identity

    set_identity(identity)

    # ---- 章节正确 API ----
    logger.info("[v2] 章节正确 API: AAPL/MSFT/NVDA/JPM/BRK-B/TSLA")
    sections_real: dict[str, Any] = {}
    for tkr in ["AAPL", "MSFT", "NVDA", "JPM", "BRK-B", "TSLA"]:
        try:
            tenk = Company(tkr).latest("10-K").obj()
            sec = {
                "business_chars": len(getattr(tenk, "business", "") or ""),
                "risk_factors_chars": len(getattr(tenk, "risk_factors", "") or ""),
                "management_discussion_chars": len(
                    getattr(tenk, "management_discussion", "") or ""
                ),
                "directors_officers_chars": len(
                    getattr(tenk, "directors_officers_and_governance", "") or ""
                ),
                "items_list": getattr(tenk, "items", []),
                "auditor": str(getattr(tenk, "auditor", ""))[:200],
                "has_financials": hasattr(tenk, "financials"),
                "has_income_statement": hasattr(tenk, "income_statement"),
            }
            sections_real[tkr] = sec
            logger.info(
                f"  {tkr}: biz={sec['business_chars']} risk={sec['risk_factors_chars']} mdna={sec['management_discussion_chars']}"
            )
        except Exception as e:  # noqa: BLE001
            sections_real[tkr] = {"error": repr(e)}
    write_json("tenk_attributes_real.json", sections_real)

    # ---- 10-Q 正确 API ----
    logger.info("[v2] 10-Q 正确 API: AAPL")
    try:
        tenq_filings = Company("AAPL").get_filings(form="10-Q").latest(4)
        tenq_list = []
        for f in tenq_filings:
            obj = f.obj()
            tenq_list.append(
                {
                    "form": f.form,
                    "filing_date": str(f.filing_date),
                    "period_of_report": str(f.period_of_report),
                    "accession_no": f.accession_no,
                    "obj_class": type(obj).__name__,
                    "has_management_discussion": hasattr(obj, "management_discussion"),
                    "mdna_chars": len(getattr(obj, "management_discussion", "") or ""),
                    "has_income_statement": hasattr(obj, "income_statement"),
                }
            )
        write_json("tenq_aapl_v2.json", tenq_list)
    except Exception as e:  # noqa: BLE001
        write_json("tenq_aapl_v2.json", {"error": repr(e)})

    # ---- 8-K 正确 API（CurrentReport 不是 EightK） ----
    logger.info("[v2] 8-K (CurrentReport): TSLA")
    try:
        eightk_filings = Company("TSLA").get_filings(form="8-K").latest(5)
        eightk_list = []
        for f in eightk_filings:
            obj = f.obj()
            eightk_list.append(
                {
                    "filing_date": str(f.filing_date),
                    "period_of_report": str(f.period_of_report),
                    "accession_no": f.accession_no,
                    "obj_class": type(obj).__name__,
                    "items": list(getattr(obj, "items", []) or []),
                    "text_chars": len(f.text() if hasattr(f, "text") else "") if f else 0,
                    "obj_attrs_sample": [a for a in dir(obj) if not a.startswith("_")][:30],
                }
            )
        write_json("eightk_tsla_v2.json", eightk_list)
    except Exception as e:  # noqa: BLE001
        write_json("eightk_tsla_v2.json", {"error": repr(e)})

    # ---- Form 4 正确 API ----
    logger.info("[v2] Form 4 (transactions): TSLA")
    try:
        form4_filings = Company("TSLA").get_filings(form="4").latest(5)
        form4_list = []
        for f in form4_filings:
            obj = f.obj()
            entry = {
                "filing_date": str(f.filing_date),
                "accession_no": f.accession_no,
                "insider_name": getattr(obj, "insider_name", None),
                "issuer": str(getattr(obj, "issuer", ""))[:100],
                "reporting_owners": str(getattr(obj, "reporting_owners", ""))[:200],
                "position": str(getattr(obj, "position", ""))[:200],
                "common_stock_sales_attr_type": type(
                    getattr(obj, "common_stock_sales", None)
                ).__name__,
                "common_stock_purchases_attr_type": type(
                    getattr(obj, "common_stock_purchases", None)
                ).__name__,
            }
            try:
                summary = (
                    obj.get_ownership_summary() if hasattr(obj, "get_ownership_summary") else None
                )
                entry["ownership_summary"] = str(summary)[:500] if summary else None
            except Exception:  # noqa: BLE001
                entry["ownership_summary"] = "<error>"
            try:
                activities = (
                    obj.get_transaction_activities()
                    if hasattr(obj, "get_transaction_activities")
                    else None
                )
                entry["transaction_activities"] = str(activities)[:500] if activities else None
            except Exception:  # noqa: BLE001
                entry["transaction_activities"] = "<error>"
            form4_list.append(entry)
        write_json("form4_tsla_v2.json", form4_list)
    except Exception as e:  # noqa: BLE001
        write_json("form4_tsla_v2.json", {"error": repr(e)})

    # ---- XBRL EntityFacts 正确 API ----
    logger.info("[v2] XBRL EntityFacts.get_revenue() etc")
    xbrl_real: dict[str, Any] = {}
    for tkr in ["AAPL", "MSFT", "GOOGL"]:
        try:
            facts = Company(tkr).get_facts()
            rev = facts.get_revenue() if facts else None
            ni = facts.get_net_income() if facts else None
            ttm_rev = facts.get_ttm_revenue() if facts else None
            entry = {
                "ttm_revenue_type": type(ttm_rev).__name__,
                "ttm_revenue_value": str(ttm_rev)[:200],
                "get_revenue_type": type(rev).__name__,
                "get_revenue_str_sample": str(rev)[:300],
                "get_net_income_type": type(ni).__name__,
                "available_periods_count": (
                    len(facts.available_periods)
                    if hasattr(facts, "available_periods")
                    and hasattr(facts.available_periods, "__len__")
                    else "?"
                ),
            }
            xbrl_real[tkr] = entry
            logger.info(f"  {tkr}: ttm_rev={entry['ttm_revenue_value'][:50]}")
        except Exception as e:  # noqa: BLE001
            xbrl_real[tkr] = {"error": repr(e)}
    write_json("xbrl_facts_real.json", xbrl_real)

    # ---- 顶层异常类（不是 EdgarError） ----
    logger.info("[v2] 顶层异常类")
    import edgar

    edgar_exceptions = [
        name
        for name in dir(edgar)
        if "Error" in name or "Exception" in name and not name.startswith("_")
    ]
    write_json(
        "edgar_top_exceptions.json",
        {
            "available_exception_classes": edgar_exceptions,
            "recommended_catch": "DataObjectException, CompanyNotFoundError",
            "edgartools_version": getattr(edgar, "__version__", "unknown"),
            "python_version": ".".join(str(x) for x in sys.version_info[:3]),
            "probe_run_at": datetime.now(tz=timezone.utc).isoformat(),
        },
    )

    logger.info("[v2] done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
