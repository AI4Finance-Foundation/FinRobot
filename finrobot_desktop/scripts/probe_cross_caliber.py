#!/usr/bin/env python3
"""跨口径一致性探针 — A 路成批 bug 猎杀 / 永久 golden 网种子。

对一个多样化真实 ticker 宇宙真打后端(:8321),断言「同一个数在所有渲染口
全等、可溯源到一个源」这一类必须恒成立的不变量。任一只违反即 candidate。

唯一合法 bug 信号 = 真实后端 payload vs 不变量;不依赖任何记忆里的 live 量。
跑法:后端 ./dev.sh 起在 :8321,然后 `python scripts/probe_cross_caliber.py`。
"""

from __future__ import annotations

import json
import math
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import TypeGuard

BASE = "http://127.0.0.1:8321"

UNIVERSE: list[str] = [
    # 美股大盘
    "AAPL",
    "MSFT",
    "NVDA",
    "GOOGL",
    "AMZN",
    "META",
    "TSLA",
    # 中小盘 / 亏损股
    "ROKU",
    "ETSY",
    "RIVN",
    "AFRM",
    "SNAP",
    "U",
    # 外资 ADR(原报告币种非 USD)
    "TSM",
    "ASML",
    "SAP",
    "TM",
    "SONY",
    "BABA",
    "NVO",
    "SE",
    "MELI",
    # 银行
    "JPM",
    "BAC",
    "GS",
    "WFC",
    # REIT
    "O",
    "PLD",
    "SPG",
    "AMT",
    # 高杠杆 / 周期
    "CCL",
    "BA",
    "CVNA",
    # 近期 IPO
    "ARM",
    "RDDT",
    "CART",
]

TOL_TIGHT = 0.005  # 0.5% — 同一个数跨口径
TOL_CALIBER = 0.02  # 2% — 同名口径(EV/EBITDA)跨端点

# 外部源已验真的极端倍数(ticker, field)——band 是启发式 candidate 滤网,
# 这些是查过外部基准确认"系统是对的"的真实极端值,不再重复报。
# ARM:stockanalysis.com 2026-06-09 EV/EBITDA=322.97(TTM EBITDA $1.06B,
# EV $343.87B),我们 297.8 同量级仅 EBITDA 细口径差 → 数字正确。
VERIFIED_EXTREMES: set[tuple[str, str]] = {("ARM", "ev_ebitda")}


def _get(path: str, timeout: int = 30) -> dict | None:
    try:
        req = urllib.request.Request(BASE + path, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:  # noqa: BLE001
        return {"__error__": f"{type(e).__name__}: {e}"}


def _finite(x: object) -> TypeGuard[float]:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _rel(a: float, b: float) -> float:
    base = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / base


def probe(ticker: str) -> list[dict]:
    """返回该 ticker 的违反列表(空=全绿)。"""
    out: list[dict] = []

    def viol(inv: str, detail: str, **vals: object) -> None:
        out.append({"ticker": ticker, "invariant": inv, "detail": detail, **vals})

    price = _get(f"/api/data/{ticker}/price")
    fin = _get(f"/api/data/{ticker}/financials")
    bands = _get(f"/api/valuation/historical-bands/{ticker}")

    if not price or price.get("__error__"):
        viol("FETCH", f"/price failed: {price and price.get('__error__')}")
        return out
    if not fin or fin.get("__error__"):
        viol("FETCH", f"/financials failed: {fin and fin.get('__error__')}")
        return out

    market = fin.get("market") or {}
    val = fin.get("valuation") or {}
    bal = fin.get("balance") or {}
    rep_ccy = fin.get("reporting_currency")
    quote_ccy = fin.get("quote_currency")

    p_mc = price.get("market_cap")
    f_mc = market.get("market_cap")
    f_px = market.get("current_price")
    p_px = price.get("current_price")
    shares = market.get("shares_outstanding")

    # ── INV-MC-CROSS:/price 与 /financials 的 market_cap 必须全等 ──
    if _finite(p_mc) and _finite(f_mc):
        if _rel(p_mc, f_mc) > TOL_TIGHT:
            viol(
                "MC-CROSS",
                "/price.market_cap != /financials.market.market_cap",
                price_mc=p_mc,
                fin_mc=f_mc,
                rel=round(_rel(p_mc, f_mc), 4),
            )

    # ── INV-MC-IDENTITY:market_cap == shares × current_price ──
    if _finite(f_mc) and _finite(shares) and _finite(f_px) and shares > 0:
        implied = shares * f_px
        if _rel(f_mc, implied) > TOL_TIGHT:
            viol(
                "MC-IDENTITY",
                "market_cap != shares_outstanding × current_price",
                market_cap=f_mc,
                shares=shares,
                px=f_px,
                implied=round(implied, 2),
                rel=round(_rel(f_mc, implied), 4),
            )

    # ── INV-PX-CROSS:同一时刻 /price 与 /financials 的现价必须全等 ──
    if _finite(p_px) and _finite(f_px) and _rel(p_px, f_px) > TOL_TIGHT:
        viol(
            "PX-CROSS",
            "/price.current_price != /financials.market.current_price",
            price_px=p_px,
            fin_px=f_px,
            rel=round(_rel(p_px, f_px), 4),
        )

    ev = val.get("enterprise_value")
    ev_ebitda = val.get("ev_ebitda")
    ev_rev = val.get("ev_revenue")
    pe = market.get("pe_ratio")

    # ── INV-MIXEDCCY-NONE:reporting!=quote → EV/倍数/pe 必须 None ──
    if rep_ccy and quote_ccy and rep_ccy != quote_ccy:
        for name, v in (
            ("enterprise_value", ev),
            ("ev_ebitda", ev_ebitda),
            ("ev_revenue", ev_rev),
            ("pe_ratio", pe),
        ):
            if v is not None:
                viol(
                    "MIXEDCCY-NONE",
                    f"混币(rep={rep_ccy} quote={quote_ccy})却给出 {name}",
                    field=name,
                    value=v,
                )

    # ── INV-EV-SIGN:EV 给出即应 > 0(净现金盈利企业不可能负 EV;负 EV 标 needs-human)──
    if _finite(ev) and ev <= 0:
        viol("EV-SIGN", "enterprise_value <= 0", ev=ev, market_cap=f_mc)

    # ── INV-EV-IDENTITY:EV ≈ mc + debt + preferred + nci − cash ──
    debt = bal.get("total_debt")
    cash = bal.get("total_cash")
    pref = bal.get("preferred_stock") or 0
    nci = bal.get("noncontrolling_interest") or 0
    if _finite(ev) and _finite(f_mc) and _finite(debt) and _finite(cash):
        implied_ev = f_mc + debt + pref + nci - cash
        if _rel(ev, implied_ev) > 0.01:
            viol(
                "EV-IDENTITY",
                "EV != mc + debt + preferred + nci − cash",
                ev=ev,
                implied_ev=round(implied_ev, 2),
                mc=f_mc,
                debt=debt,
                cash=cash,
                rel=round(_rel(ev, implied_ev), 4),
            )

    # ── INV-MULT-FINITE:倍数不许 NaN/Inf;给出即应在合理 band ──
    for name, v, lo, hi in (
        ("ev_ebitda", ev_ebitda, 0, 200),
        ("ev_revenue", ev_rev, 0, 100),
        ("pe_ratio", pe, 0, 1500),
    ):
        if v is None:
            continue
        if not _finite(v):
            viol("MULT-FINITE", f"{name} 非有限值", field=name, value=str(v))
        elif not (lo < v <= hi):
            # 负 PE(亏损)可接受 → 仅当被算成给出值才看;这里 lo=0 会抓负 PE
            if name == "pe_ratio" and v <= 0:
                continue  # 亏损股 PE 可能负/None,不算违反
            if (ticker, name) in VERIFIED_EXTREMES:
                continue  # 外部源已验真的极端值,见 VERIFIED_EXTREMES
            viol("MULT-BAND", f"{name}={v} 超出合理 band ({lo},{hi}]", field=name, value=v)

    # ── INV-EVEBITDA-CALIBER:/financials.ev_ebitda 与 historical-bands.current 同口径 ──
    if bands and not bands.get("__error__") and bands.get("metric") == "ev_ebitda":
        b_current = bands.get("current")
        if _finite(ev_ebitda) and _finite(b_current):
            if _rel(ev_ebitda, b_current) > TOL_CALIBER:
                viol(
                    "EVEBITDA-CALIBER",
                    "同名 current EV/EBITDA 跨端点口径不一致(/financials TTM vs bands)",
                    fin_ev_ebitda=round(ev_ebitda, 3),
                    bands_current=round(b_current, 3),
                    rel=round(_rel(ev_ebitda, b_current), 4),
                    bands_classification=bands.get("classification"),
                )

    return out


def main() -> int:
    print(f"探针宇宙:{len(UNIVERSE)} 只 → {BASE}\n")
    all_viol: list[dict] = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        for res in ex.map(probe, UNIVERSE):
            all_viol.extend(res)

    by_inv: dict[str, list[dict]] = {}
    for v in all_viol:
        by_inv.setdefault(v["invariant"], []).append(v)

    if not all_viol:
        print("✅ 全宇宙零违反")
        return 0

    print(f"⚠️  {len(all_viol)} 处违反,分 {len(by_inv)} 类不变量:\n")
    for inv in sorted(by_inv, key=lambda k: -len(by_inv[k])):
        rows = by_inv[inv]
        print(f"━━ {inv}  ({len(rows)} 只) ━━")
        for r in rows:
            extra = {k: v for k, v in r.items() if k not in ("ticker", "invariant", "detail")}
            print(f"  {r['ticker']:6s} {r['detail']}")
            print(f"         {json.dumps(extra, default=str, ensure_ascii=False)}")
        print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
