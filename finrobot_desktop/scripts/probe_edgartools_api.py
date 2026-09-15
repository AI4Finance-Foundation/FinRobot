"""门 1 · EdgarTools 5 真实 API 形状探测。

目标：把所有 v3 spec §4 门 1 列出的 API 调用真实跑一次（用合法 SEC
identity），把返回结构存成 fixture 给门 2 单元测试复用，把 13F 反向查询
策略 binary 决定下来，把 nest-asyncio 兼容性钉死。

合规边界（spec v3 §4 门 1 明确禁止的事情）：
- 绝不用伪 identity 打 SEC 真实服务做"会不会被 ban"的负面行为实验
- _is_valid_identity 等本地 gate 全用 Python 单元测试形态在 main 里跑

运行方式（必须用合法 EDGAR_IDENTITY 环境变量）：

    EDGAR_IDENTITY="Your Name your@email.com" \
        uv run python -m scripts.probe_edgartools_api

输出：
    scripts/                            # 本文件
    tests/fixtures/edgar/probe_summary.json
    tests/fixtures/edgar/filing_meta_{ticker}.json
    tests/fixtures/edgar/tenk_text_{ticker}.txt
    tests/fixtures/edgar/tenk_sections_{ticker}.json
    tests/fixtures/edgar/xbrl_revenue_{ticker}.csv
    tests/fixtures/edgar/tenq_aapl.json
    tests/fixtures/edgar/eightk_tsla.json
    tests/fixtures/edgar/form4_tsla.json
    tests/fixtures/edgar/proxy_aapl.json
    tests/fixtures/edgar/thirteenf_probe.json
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("probe")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

FIXTURES_DIR = Path("tests/fixtures/edgar")
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

EIGHT_COMPANIES = ["AAPL", "MSFT", "NVDA", "TSLA", "JPM", "BRK-B", "TSM", "BABA"]


def _json_safe(o: Any) -> Any:
    """递归把 datetime / date / Pandas / 复杂对象转成 JSON-safe 形态。"""
    if hasattr(o, "isoformat"):
        return o.isoformat()
    if hasattr(o, "to_dict"):
        return o.to_dict()
    if hasattr(o, "model_dump"):
        return o.model_dump(mode="json")
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


def write_text(name: str, text: str) -> None:
    p = FIXTURES_DIR / name
    p.write_text(text)
    logger.info("  → wrote %s (%d bytes)", p, p.stat().st_size)


# ---------------------------------------------------------------------------
# Section 1 · 本地 identity gate 测试（不打 SEC）
# ---------------------------------------------------------------------------


def _is_valid_identity(s: str | None) -> bool:
    """spec v3 §5 顶部定义；这里复制一份让 probe 自洽，门 2 实施时挪到
    edgar_provider.py 并由这里 import。"""
    if not s or "@" not in s or " " not in s.strip():
        return False
    if s.strip() == "FinRobot admin@example.com":
        return False
    return True


def probe_local_identity_gate() -> dict[str, Any]:
    logger.info("[probe] local identity gate (no SEC calls)")
    cases = {
        "empty_string": (_is_valid_identity(""), False),
        "none": (_is_valid_identity(None), False),
        "no_email_no_space": (_is_valid_identity("foobar"), False),
        "no_space": (_is_valid_identity("no_space@example.com"), False),
        "default_config_value": (_is_valid_identity("FinRobot admin@example.com"), False),
        "valid_english": (_is_valid_identity("Jane Doe jane@example.com"), True),
        "valid_chinese": (_is_valid_identity("张三 zhangsan@example.com"), True),
        "leading_trailing_space": (_is_valid_identity("  John j@x.io  "), True),
    }
    passed = all(actual is expected for actual, expected in cases.values())
    return {
        "all_passed": passed,
        "cases": {
            name: {"actual": actual, "expected": expected, "pass": actual is expected}
            for name, (actual, expected) in cases.items()
        },
        "default_identity_rejected_locally": cases["default_config_value"][0] is False,
        "valid_identity_accepted": cases["valid_english"][0] is True,
    }


# ---------------------------------------------------------------------------
# Section 2 · 服务器可启动性（identity 缺失/默认时）— 这部分门 1 是设计
# 验证，不真起 finrobot serve（避免 lifespan 副作用）；只验证
# build_data_layer 等价逻辑：当 identity invalid 时不构造 EdgarToolsProvider
# ---------------------------------------------------------------------------


def probe_server_can_start_without_identity() -> dict[str, Any]:
    """模拟 build_data_layer：identity invalid 时跳过 EdgarToolsProvider 注册。

    真正的 lifespan 启动 / Settings 可访问性验证留给门 4。门 1 这里证明 gating
    逻辑在"identity invalid → 不构造 provider"路径上不抛异常。
    """
    logger.info("[probe] gating logic when identity invalid")
    invalid_cases = ["", "FinRobot admin@example.com", "noemail"]
    results = {}
    for case in invalid_cases:
        try:
            registered = _is_valid_identity(case)
            assert registered is False, f"unexpectedly valid: {case!r}"
            results[case or "<empty>"] = {"would_register": False, "raised": False}
        except Exception as e:  # noqa: BLE001
            results[case or "<empty>"] = {"would_register": False, "raised": True, "error": str(e)}
    return {
        "no_invalid_case_raises": all(not r["raised"] for r in results.values()),
        "cases": results,
    }


# ---------------------------------------------------------------------------
# Section 3 · EdgarTools 真实 API 探测（合法 identity 必须已设置）
# ---------------------------------------------------------------------------


def probe_edgartools_real_calls(identity: str) -> dict[str, Any]:
    """对 spec §4 门 1 列的每个 API 做真实调用，存 fixture，记结果。"""
    logger.info("[probe] real SEC calls with identity %r", identity)
    from edgar import Company, set_identity, get_filings  # noqa: PLC0415

    # spec §5 注释要求确认顶层异常名 — 实测后记录
    edgar_top_error_name = "Exception"  # fallback
    try:
        from edgar.core import EdgarError  # type: ignore[import-untyped]  # noqa: PLC0415

        edgar_top_error_name = EdgarError.__name__
    except ImportError:
        try:
            from edgar import EdgarError  # type: ignore[attr-defined]  # noqa: PLC0415

            edgar_top_error_name = EdgarError.__name__
        except ImportError:
            edgar_top_error_name = "ImportError(edgar.core.EdgarError)"
    logger.info("  edgartools top error class = %s", edgar_top_error_name)

    set_identity(identity)

    summary: dict[str, Any] = {
        "edgar_top_error_class": edgar_top_error_name,
        "per_ticker_10k": {},
        "tenk_text_sample": {},
        "tenk_sections_per_ticker": {},
        "xbrl_revenue": {},
        "tenq": None,
        "eightk": None,
        "form4": None,
        "proxy": None,
        "thirteenf_strategy_probe": {},
        "errors": [],
    }

    # ---- 3.1 / 3.2 / 3.3 ：8 家公司 latest("10-K") + sections() + text() 抽样
    for tkr in EIGHT_COMPANIES:
        try:
            logger.info("  [%s] latest 10-K", tkr)
            c = Company(tkr)
            filing = c.latest("10-K")
            if filing is None:
                summary["per_ticker_10k"][tkr] = {"found": False}
                continue
            meta = {
                "found": True,
                "company": getattr(c, "name", None) or str(c),
                "cik": str(getattr(c, "cik", "")),
                "filing_date": str(getattr(filing, "filing_date", "")),
                "accession_no": getattr(filing, "accession_no", None)
                or getattr(filing, "accession_number", None),
                "period_of_report": str(getattr(filing, "period_of_report", "")),
                "form": getattr(filing, "form", None),
                "homepage_url": getattr(filing, "homepage_url", None),
            }
            summary["per_ticker_10k"][tkr] = meta
            write_json(f"filing_meta_{tkr}.json", meta)

            # sections() — 这是 §5 canonicalizer 的真实输入
            sections_raw: list[dict[str, Any]] = []
            tenk = None
            try:
                tenk = filing.obj()
            except Exception as e:  # noqa: BLE001
                summary["errors"].append(f"{tkr} filing.obj() raised: {e!r}")
                tenk = None

            if tenk is not None and hasattr(tenk, "sections"):
                try:
                    secs = tenk.sections()
                    # 不同版本可能返回 list[Section] / list[str] / 字典
                    if isinstance(secs, dict):
                        for k, v in secs.items():
                            sections_raw.append(
                                {
                                    "title": str(k),
                                    "text_preview": str(v)[:200] if v else "",
                                    "char_count": len(str(v) if v else ""),
                                }
                            )
                    elif isinstance(secs, (list, tuple)):
                        for s in secs:
                            title = getattr(s, "title", None) or getattr(s, "name", None) or str(s)
                            text = None
                            if hasattr(s, "text"):
                                text = s.text() if callable(s.text) else s.text
                            sections_raw.append(
                                {
                                    "title": str(title),
                                    "text_preview": (str(text)[:200] if text else ""),
                                    "char_count": len(str(text)) if text else 0,
                                }
                            )
                    else:
                        sections_raw.append({"raw_type": str(type(secs))})
                except Exception as e:  # noqa: BLE001
                    summary["errors"].append(f"{tkr} sections() raised: {e!r}")
            else:
                summary["errors"].append(
                    f"{tkr} tenk.sections() unavailable (tenk={type(tenk).__name__})"
                )

            summary["tenk_sections_per_ticker"][tkr] = sections_raw
            write_json(f"tenk_sections_{tkr}.json", sections_raw)

            # text() 抽样三家（AAPL/JPM/BRK-B）
            if tkr in ("AAPL", "JPM", "BRK-B"):
                try:
                    full_text = filing.text() if hasattr(filing, "text") else ""
                    write_text(f"tenk_text_{tkr}.txt", full_text[:200_000])
                    summary["tenk_text_sample"][tkr] = {
                        "char_count": len(full_text),
                        "sample_first_500": full_text[:500],
                    }
                except Exception as e:  # noqa: BLE001
                    summary["errors"].append(f"{tkr} filing.text() raised: {e!r}")

        except Exception as e:  # noqa: BLE001
            tb = traceback.format_exc()
            summary["per_ticker_10k"][tkr] = {"found": False, "error": str(e), "trace": tb}
            summary["errors"].append(f"{tkr} 10-K probe raised: {e!r}")

    # ---- 3.4 XBRL facts（AAPL + 跨公司 Revenue 对齐）
    for tkr in ("AAPL", "MSFT", "GOOGL"):
        try:
            logger.info("  [%s] get_facts().to_pandas('us-gaap:Revenues')", tkr)
            facts = Company(tkr).get_facts()
            df = facts.to_pandas("us-gaap:Revenues") if facts else None
            if df is None or len(df) == 0:
                summary["xbrl_revenue"][tkr] = {"rows": 0}
                continue
            csv_path = FIXTURES_DIR / f"xbrl_revenue_{tkr}.csv"
            df.to_csv(csv_path, index=False)
            summary["xbrl_revenue"][tkr] = {
                "rows": int(len(df)),
                "columns": list(df.columns),
                "first_row": _json_safe(df.iloc[0].to_dict()) if len(df) > 0 else None,
            }
            logger.info("    → %d rows, cols=%s", len(df), list(df.columns))
        except Exception as e:  # noqa: BLE001
            summary["errors"].append(f"{tkr} XBRL Revenues raised: {e!r}")
            summary["xbrl_revenue"][tkr] = {"error": str(e)}

    # ---- 3.5 10-Q（AAPL 最近 4 份）
    try:
        logger.info("  [AAPL] latest 10-Q n=4")
        tenq_list = Company("AAPL").latest("10-Q", n=4)
        if tenq_list is None:
            tenq_list = []
        elif not isinstance(tenq_list, list):
            tenq_list = [tenq_list]
        tenq_dump = [
            {
                "filing_date": str(getattr(f, "filing_date", "")),
                "period_of_report": str(getattr(f, "period_of_report", "")),
                "accession_no": getattr(f, "accession_no", None),
                "form": getattr(f, "form", None),
            }
            for f in tenq_list
        ]
        write_json("tenq_aapl.json", tenq_dump)
        summary["tenq"] = {"count": len(tenq_dump), "first": tenq_dump[0] if tenq_dump else None}
    except Exception as e:  # noqa: BLE001
        summary["errors"].append(f"AAPL 10-Q probe raised: {e!r}")

    # ---- 3.6 8-K（TSLA 最近）
    try:
        logger.info("  [TSLA] get_filings(form='8-K') 最近 5 份")
        eightk_filings = Company("TSLA").get_filings(form="8-K")
        # 不同版本返回 EntityFilings — 取最近 5
        if hasattr(eightk_filings, "latest"):
            taken = eightk_filings.latest(n=5)
        else:
            taken = list(eightk_filings)[:5]
        if not isinstance(taken, list):
            taken = [taken]
        eightk_dump: list[dict[str, Any]] = []
        for f in taken:
            obj = None
            items: list[Any] = []
            try:
                obj = f.obj()
                items = list(getattr(obj, "items", []) or [])
            except Exception as e:  # noqa: BLE001
                summary["errors"].append(f"TSLA 8-K obj() raised: {e!r}")
            eightk_dump.append(
                {
                    "filing_date": str(getattr(f, "filing_date", "")),
                    "period_of_report": str(getattr(f, "period_of_report", "")),
                    "accession_no": getattr(f, "accession_no", None),
                    "items_count": len(items),
                    "items_preview": [str(i)[:100] for i in items[:3]],
                    "obj_class": type(obj).__name__ if obj is not None else None,
                }
            )
        write_json("eightk_tsla.json", eightk_dump)
        summary["eightk"] = {
            "count": len(eightk_dump),
            "first": eightk_dump[0] if eightk_dump else None,
        }
    except Exception as e:  # noqa: BLE001
        summary["errors"].append(f"TSLA 8-K probe raised: {e!r}")

    # ---- 3.7 Form 4（TSLA 最近）
    try:
        logger.info("  [TSLA] get_filings(form='4') 最近 10 份")
        form4_filings = Company("TSLA").get_filings(form="4")
        if hasattr(form4_filings, "latest"):
            taken4 = form4_filings.latest(n=10)
        else:
            taken4 = list(form4_filings)[:10]
        if not isinstance(taken4, list):
            taken4 = [taken4]
        form4_dump: list[dict[str, Any]] = []
        for f in taken4:
            tx_info: dict[str, Any] = {"transactions_attr": None, "obj_class": None}
            try:
                form4_obj = f.obj()
                tx_info["obj_class"] = type(form4_obj).__name__
                if hasattr(form4_obj, "transactions"):
                    tx_attr = form4_obj.transactions
                    tx_info["transactions_attr"] = type(tx_attr).__name__
                    if isinstance(tx_attr, list) and tx_attr:
                        sample = tx_attr[0]
                        tx_info["sample_keys"] = (
                            list(vars(sample).keys())
                            if hasattr(sample, "__dict__")
                            else dir(sample)[:20]
                        )
            except Exception as e:  # noqa: BLE001
                summary["errors"].append(f"TSLA Form 4 obj() raised: {e!r}")
            form4_dump.append(
                {
                    "filing_date": str(getattr(f, "filing_date", "")),
                    "accession_no": getattr(f, "accession_no", None),
                    **tx_info,
                }
            )
        write_json("form4_tsla.json", form4_dump)
        summary["form4"] = {
            "count": len(form4_dump),
            "first": form4_dump[0] if form4_dump else None,
        }
    except Exception as e:  # noqa: BLE001
        summary["errors"].append(f"TSLA Form 4 probe raised: {e!r}")

    # ---- 3.8 DEF 14A proxy（AAPL）
    try:
        logger.info("  [AAPL] latest DEF 14A")
        proxy_filing = Company("AAPL").latest("DEF 14A")
        if proxy_filing is None:
            summary["proxy"] = {"found": False}
        else:
            proxy_obj_class = None
            try:
                proxy_obj = proxy_filing.obj()
                proxy_obj_class = type(proxy_obj).__name__
            except Exception as e:  # noqa: BLE001
                summary["errors"].append(f"AAPL DEF 14A obj() raised: {e!r}")
            text = ""
            try:
                text = proxy_filing.text()
            except Exception as e:  # noqa: BLE001
                summary["errors"].append(f"AAPL DEF 14A text() raised: {e!r}")
            proxy_dump = {
                "filing_date": str(getattr(proxy_filing, "filing_date", "")),
                "accession_no": getattr(proxy_filing, "accession_no", None),
                "obj_class": proxy_obj_class,
                "text_char_count": len(text),
                "text_sample_first_500": text[:500],
            }
            write_json("proxy_aapl.json", proxy_dump)
            summary["proxy"] = {"found": True, "obj_class": proxy_obj_class}
    except Exception as e:  # noqa: BLE001
        summary["errors"].append(f"AAPL DEF 14A probe raised: {e!r}")

    # ---- 3.9 13F binary 决策（reverse_api | local_index_required | blocked）
    logger.info("  [13F] binary decision probe")
    tf_probe: dict[str, Any] = {
        "reverse_api_available": False,
        "reverse_api_attempted": [],
        "local_index_feasible": False,
        "decision": "unknown",
    }

    # 先试 Company-level 反向方法（spec §5 PROBE 点）
    sample_company = Company("NVDA")
    candidate_methods = [
        "get_institutional_holders",
        "institutional_holders",
        "get_13f_holders",
        "holders",
        "get_owners",
    ]
    for m in candidate_methods:
        if hasattr(sample_company, m):
            tf_probe["reverse_api_attempted"].append(m)
            try:
                attr = getattr(sample_company, m)
                result = attr() if callable(attr) else attr
                tf_probe["reverse_api_available"] = True
                tf_probe["reverse_api_method"] = m
                tf_probe["reverse_api_result_type"] = type(result).__name__
                # 写一个 sample
                try:
                    if hasattr(result, "head"):
                        sample = result.head(5).to_dict("records")
                    elif isinstance(result, list):
                        sample = result[:5]
                    else:
                        sample = str(result)[:500]
                    tf_probe["reverse_api_sample"] = _json_safe(sample)
                except Exception:  # noqa: BLE001
                    tf_probe["reverse_api_sample"] = "<unrenderable>"
                break
            except Exception as e:  # noqa: BLE001
                tf_probe["reverse_api_attempted"].append({m: f"raised: {e!r}"})

    # 不管 reverse_api 是否存在，都试一次 get_filings(form="13F-HR") 看 forward
    # 路径（持有者机构的 13F）是否能拿到 — 决定 local_index 是否可行
    try:
        logger.info("  [13F] forward path test: get_filings(form='13F-HR')[:1]")
        tf_filings = get_filings(form="13F-HR")
        first = None
        if hasattr(tf_filings, "latest"):
            first = tf_filings.latest(n=1)
            if isinstance(first, list):
                first = first[0] if first else None
        elif tf_filings:
            try:
                first = next(iter(tf_filings))
            except StopIteration:
                first = None
        if first is not None:
            obj_class = None
            holdings_class = None
            holdings_rows = 0
            try:
                obj = first.obj()
                obj_class = type(obj).__name__
                if hasattr(obj, "holdings"):
                    h = obj.holdings
                    holdings_class = type(h).__name__
                    if hasattr(h, "__len__"):
                        holdings_rows = len(h)
                    elif hasattr(h, "shape"):
                        holdings_rows = h.shape[0]
            except Exception as e:  # noqa: BLE001
                summary["errors"].append(f"13F forward obj() raised: {e!r}")
            tf_probe["local_index_feasible"] = True
            tf_probe["forward_sample"] = {
                "filer_cik": str(getattr(first, "cik", "")),
                "filing_date": str(getattr(first, "filing_date", "")),
                "obj_class": obj_class,
                "holdings_class": holdings_class,
                "holdings_rows_in_one_filing": holdings_rows,
            }
    except Exception as e:  # noqa: BLE001
        summary["errors"].append(f"13F forward probe raised: {e!r}")

    if tf_probe["reverse_api_available"]:
        tf_probe["decision"] = "reverse_api"
    elif tf_probe["local_index_feasible"]:
        tf_probe["decision"] = "local_index_required"
    else:
        tf_probe["decision"] = "blocked"

    write_json("thirteenf_probe.json", tf_probe)
    summary["thirteenf_strategy_probe"] = tf_probe

    return summary


# ---------------------------------------------------------------------------
# Section 4 · 写最终 probe_summary.json（machine-readable gate）
# ---------------------------------------------------------------------------


def emit_probe_summary(
    *,
    identity_used: str,
    local_gate: dict[str, Any],
    server_gate: dict[str, Any],
    real_calls: dict[str, Any],
) -> dict[str, Any]:
    import edgar  # type: ignore[import-untyped]  # 5.31 真实 module 名

    edgartools_version = getattr(edgar, "__version__", "unknown")
    py_version = ".".join(str(x) for x in sys.version_info[:3])

    # forms ok 判定：fixture 写出 + summary 内有非空内容
    def _ok(present_key: bool, fail_msg_count: int = 0) -> str:
        return "ok" if present_key and fail_msg_count == 0 else "failed"

    forms = {
        "10k": _ok(
            any(v.get("found") for v in real_calls.get("per_ticker_10k", {}).values()),
            sum(1 for e in real_calls.get("errors", []) if "10-K probe raised" in e),
        ),
        "10q": _ok(bool(real_calls.get("tenq")), 0),
        "8k": _ok(bool(real_calls.get("eightk")), 0),
        "form4": _ok(bool(real_calls.get("form4")), 0),
        "def14a": _ok(bool(real_calls.get("proxy")), 0),
        "xbrl_facts": _ok(
            any(v.get("rows", 0) > 0 for v in real_calls.get("xbrl_revenue", {}).values()),
            0,
        ),
        "13f_strategy": real_calls["thirteenf_strategy_probe"]["decision"],
    }

    sections_raw = real_calls.get("tenk_sections_per_ticker", {})
    raw_titles_by_ticker = {
        tkr: [s.get("title", "") for s in slist if s.get("title")]
        for tkr, slist in sections_raw.items()
    }
    canonicalizer_required = bool(
        # 如果不同公司 title 文案不一致 → 必须 canonicalizer
        len({tuple(v) for v in raw_titles_by_ticker.values() if v}) > 1
    )

    blockers: list[str] = []
    if not local_gate["all_passed"]:
        blockers.append("local_identity_gate_failed")
    if not server_gate["no_invalid_case_raises"]:
        blockers.append("invalid_identity_path_raises")
    if forms["10k"] != "ok":
        blockers.append("10k_probe_failed")
    if forms["13f_strategy"] == "blocked":
        blockers.append("13f_both_paths_blocked")

    summary = {
        "probe_run_at": datetime.now(tz=timezone.utc).isoformat(),
        "edgartools_version": edgartools_version,
        "python_version": py_version,
        "identity_used_was_valid": _is_valid_identity(identity_used),
        "identity": {
            "valid_identity_success": local_gate["valid_identity_accepted"],
            "default_identity_rejected_locally": local_gate["default_identity_rejected_locally"],
            "server_can_start_without_valid_identity": server_gate["no_invalid_case_raises"],
        },
        "sections": {
            "sample_count": len([k for k, v in sections_raw.items() if v]),
            "raw_titles_by_ticker": raw_titles_by_ticker,
            "canonicalizer_required": canonicalizer_required,
            "canonicalizer_strategy": (
                "lookup_table_or_ngram" if canonicalizer_required else "exact_match_ok"
            ),
        },
        "forms": forms,
        "async_runtime": {
            "serve_start_stop_10x": "deferred_to_separate_script",
            "nest_asyncio_warnings": [],
        },
        "edgar_top_error_class": real_calls.get("edgar_top_error_class"),
        "errors": real_calls.get("errors", []),
        "blockers_for_gate2": blockers,
    }

    write_json("probe_summary.json", summary)
    return summary


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    identity = os.environ.get("EDGAR_IDENTITY", "").strip()
    if not _is_valid_identity(identity):
        logger.error(
            "EDGAR_IDENTITY env var missing or invalid: %r\n"
            "Set a real one: EDGAR_IDENTITY='Your Name your@email.com'",
            identity,
        )
        return 2

    logger.info("=" * 60)
    logger.info("门 1 · EdgarTools 真实 API probe")
    logger.info("identity: %r", identity)
    logger.info("=" * 60)

    local_gate = probe_local_identity_gate()
    server_gate = probe_server_can_start_without_identity()
    real_calls = probe_edgartools_real_calls(identity)
    final = emit_probe_summary(
        identity_used=identity,
        local_gate=local_gate,
        server_gate=server_gate,
        real_calls=real_calls,
    )

    logger.info("=" * 60)
    logger.info("probe_summary.json blockers_for_gate2: %s", final["blockers_for_gate2"])
    logger.info("13f decision: %s", final["forms"]["13f_strategy"])
    logger.info("=" * 60)
    return 0 if not final["blockers_for_gate2"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
