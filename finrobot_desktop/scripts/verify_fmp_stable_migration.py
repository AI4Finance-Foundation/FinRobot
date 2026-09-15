"""FMP v3→stable 迁移 live 复验探针(带宽限额恢复后跑)。

迁移(2026-06-11)的字段映射依据是 FMP 官方文档样例(Wayback 抽取),当时账号
30 天滚动带宽耗尽(429 "Bandwidth Limit Reach")拉不到真 payload。本脚本把全部
[金融待核] 项收敛成一次 ~15 请求的实拉验证,按「金融数据-开发前强制清单」T2#1
(禁止凭推断断言 payload)收口:

1. dividend-adjusted 历史价是否同时含拆股调整(AAPL 2020-08-31 4:1 拆股:
   拆股前 adjClose 必须 ≈ 1/4 名义价 ≈ 当时 yfinance auto_adjust 口径 ~125,
   而不是名义 ~129×4 域)。
2. 各端点响应字段与文档样例一致(逐消费字段断言非缺席)。
3. /shares-float outstandingShares 对外部基准(AAPL ~14.8-15.0B 区间粗检)。
4. 历史价排序方向(代码已显式排序,这里只记录 API 原生顺序供文档)。

用法:.venv/bin/python scripts/verify_fmp_stable_migration.py
key 从 keychain(FinRobot/fmp_api_key)读,绝不打印。
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date

import httpx
import keyring

from finrobot.engine.primitives.industry import is_bank, is_commodity_cyclical

BASE = "https://financialmodelingprep.com/stable"

# endpoint, params, 消费字段(fmp_provider 实际读取的)
CHECKS: list[tuple[str, dict[str, str | int], list[str]]] = [
    (
        "/profile",
        {"symbol": "AAPL"},
        ["marketCap", "price", "beta", "currency", "companyName", "industry", "sector", "country"],
    ),
    ("/quote", {"symbol": "AAPL"}, ["price", "exchange", "timestamp"]),
    ("/shares-float", {"symbol": "AAPL"}, ["outstandingShares"]),
    (
        "/income-statement",
        {"symbol": "AAPL", "period": "quarter", "limit": 4},
        [
            "revenue",
            "grossProfit",
            "operatingIncome",
            "netIncome",
            "depreciationAndAmortization",
            "researchAndDevelopmentExpenses",
            "sellingGeneralAndAdministrativeExpenses",
            "interestExpense",
            "incomeTaxExpense",
            "reportedCurrency",
            "date",
            "eps",
        ],
    ),
    (
        "/balance-sheet-statement",
        {"symbol": "AAPL", "period": "quarter", "limit": 1},
        [
            "totalDebt",
            "cashAndShortTermInvestments",
            "cashAndCashEquivalents",
            "preferredStock",
            "minorityInterest",
            "date",
        ],
    ),
    (
        "/cash-flow-statement",
        {"symbol": "AAPL", "period": "quarter", "limit": 4},
        [
            "operatingCashFlow",
            "capitalExpenditure",
            "changeInWorkingCapital",
            "depreciationAndAmortization",
            "netCashProvidedByInvestingActivities",
            "netCashProvidedByFinancingActivities",
            "date",
        ],
    ),
    # 拆股窗口:AAPL 2020-08-31 4:1。若 dividend-adjusted 同时含拆股调整,
    # 2020-08-28(拆前)的 adjClose 应在 ~121 域(124.81 名义 × 分红调整),
    # 绝不该在 ~499 域(未拆股调整 = 124.81×4)。
    (
        "/historical-price-eod/dividend-adjusted",
        {"symbol": "AAPL", "from": "2020-08-26", "to": "2020-09-02"},
        ["date", "adjOpen", "adjHigh", "adjLow", "adjClose", "volume"],
    ),
    (
        "/analyst-estimates",
        {"symbol": "AAPL", "period": "annual", "page": 0, "limit": 10},
        ["date", "revenueAvg", "epsAvg", "ebitdaAvg", "netIncomeAvg"],
    ),
    ("/stock-peers", {"symbol": "AAPL"}, ["symbol", "mktCap"]),
    ("/ratios-ttm", {"symbol": "AAPL"}, ["priceToEarningsRatioTTM"]),
    ("/quote", {"symbol": "EURUSD"}, ["price"]),
    # 以下在免费 plan 预期 403 plan-gate(也是有效信息:确认 ProviderPlanError 分型)
    ("/news/stock", {"symbols": "AAPL", "limit": 3}, ["title", "site", "publishedDate", "url"]),
    (
        "/company-screener",
        {"industry": "Consumer Electronics", "marketCapMoreThan": 1_000_000_000, "limit": 5},
        ["symbol", "marketCap"],
    ),
    ("/earning-call-transcript-dates", {"symbol": "AAPL"}, ["quarter", "fiscalYear", "date"]),
]


# Industry-classification drift guard (2026-06-15, after the v3→stable label rename
# silently de-classified the ENTIRE auto + oil-E&P cyclical sectors: "Auto Manufacturers"
# →"Auto - Manufacturers" (dash) and "Oil & Gas E&P"→"Oil & Gas Exploration & Production"
# (word rename); the exact-match whitelist matched neither). For each FMP-stable label we
# treat as commodity-cyclical, assert it (a) still exists in FMP's live /available-industries
# vocabulary (catches a future rename/drop) and (b) classifies cyclical via
# is_commodity_cyclical (catches a whitelist coverage gap). This is the mechanical backstop
# the industry.py whitelist comment points to — per-label against LIVE FMP, never a fixture
# that can drift in lockstep with the code it is supposed to check.
_FMP_CYCLICAL_LABELS = frozenset(
    {
        "Auto - Manufacturers",
        "Auto - Parts",
        "Steel",
        "Aluminum",
        "Copper",
        "Gold",
        "Silver",
        "Other Precious Metals",
        "Coal",
        "Marine Shipping",
        "Chemicals",
        "Chemicals - Specialty",
        "Oil & Gas Exploration & Production",
        "Oil & Gas Equipment & Services",
        "Oil & Gas Drilling",
        "Oil & Gas Refining & Marketing",
        "Oil & Gas Integrated",
    }
)
_FMP_NONCYCLICAL_LABELS = frozenset(
    {"Software - Application", "Drug Manufacturers - General", "Beverages - Non-Alcoholic"}
)


async def check_industry_whitelists(client: httpx.AsyncClient, key: str) -> int:
    """Assert the cyclical/bank whitelists still match FMP's live industry vocabulary."""
    r = await client.get(f"{BASE}/available-industries", params={"apikey": key})
    if r.status_code != 200:
        print(f"… /available-industries: HTTP {r.status_code} — 跳过行业漂移闸")
        return 0
    live = {str(x.get("industry")) for x in r.json() if isinstance(x, dict) and x.get("industry")}
    fails = 0
    for label in sorted(_FMP_CYCLICAL_LABELS):
        if label not in live:
            print(f"✗ 行业漂移:'{label}' 已不在 FMP live 列表(改名/下架?)— 更新 industry.py 白名单")
            fails += 1
        elif not is_commodity_cyclical(industry=label):
            print(f"✗ 白名单漏:FMP '{label}' 未判周期 — industry.py 未覆盖该 label")
            fails += 1
    for label in sorted(_FMP_NONCYCLICAL_LABELS):
        if label in live and is_commodity_cyclical(industry=label):
            print(f"✗ 假阳:FMP 非周期 '{label}' 被判周期")
            fails += 1
    if not is_bank(industry="Banks - Diversified", sector="Financial Services"):
        print("✗ is_bank 回归:FMP 'Banks - Diversified' 未判 bank")
        fails += 1
    n = len(_FMP_CYCLICAL_LABELS)
    print(
        f"{'✓' if fails == 0 else '✗'} 行业分类漂移闸:{n} 个 FMP 周期 label 对 live 核验,{fails} 失败"
    )
    return fails


async def main() -> int:
    key = keyring.get_password("FinRobot", "fmp_api_key")
    if not key:
        print("NO KEY in keychain (FinRobot/fmp_api_key)")
        return 2
    failures = 0
    async with httpx.AsyncClient(timeout=20.0) as client:
        for path, params, fields in CHECKS:
            p: dict[str, str | int] = {**params, "apikey": key}
            try:
                r = await client.get(f"{BASE}{path}", params=p)
            except httpx.HTTPError as e:
                print(f"✗ {path} {params}: {type(e).__name__}")
                failures += 1
                continue
            label = f"{path} {dict(params)}"
            if r.status_code == 429:
                print(f"… {label}: 429 带宽仍未恢复 — 改天再跑")
                return 3
            if r.status_code == 403:
                body = r.text[:120].replace(key, "***")
                print(f"○ {label}: 403 plan-gate(免费 plan 预期,ProviderPlanError 路径)— {body}")
                continue
            if r.status_code != 200:
                print(f"✗ {label}: HTTP {r.status_code} — {r.text[:150].replace(key, '***')}")
                failures += 1
                continue
            rows = r.json()
            row = rows[0] if isinstance(rows, list) and rows else None
            if not isinstance(row, dict):
                print(f"✗ {label}: 非数组/空响应(裸数组契约破坏?)→ {str(rows)[:120]}")
                failures += 1
                continue
            missing = [f for f in fields if f not in row]
            if missing:
                print(f"✗ {label}: 缺字段 {missing};实有 {sorted(row.keys())[:20]}")
                failures += 1
            else:
                print(f"✓ {label}: {len(rows)} 行,消费字段齐")
            # 专项断言
            if path == "/historical-price-eod/dividend-adjusted":
                pre_split = next((x for x in rows if x.get("date") == "2020-08-28"), None)
                if pre_split:
                    adj = float(pre_split["adjClose"])
                    if 100 < adj < 140:
                        print(
                            f"  ✓ 拆股调整确认:2020-08-28 adjClose={adj:.2f}(≈121 域,含拆股+分红调整)"
                        )
                    else:
                        print(
                            f"  ✗ [金融待核→实锤异常] 2020-08-28 adjClose={adj:.2f} 不在 ~121 域 — 口径不等价 yfinance auto_adjust,需改用其他变体组合!"
                        )
                        failures += 1
                api_order = [x.get("date") for x in rows[:3]]
                print(f"  · API 原生顺序前三: {api_order}(代码已显式升序排序,不依赖此)")
            if path == "/shares-float":
                shares = row.get("outstandingShares")
                if isinstance(shares, (int, float)) and 13e9 < shares < 17e9:
                    print(f"  ✓ AAPL outstandingShares={shares / 1e9:.2f}B(14-15B 外部基准域)")
                elif shares is not None:
                    print(f"  ✗ AAPL outstandingShares={shares} 偏离外部基准 14-15B 域,核口径")
                    failures += 1
            await asyncio.sleep(0.25)
        failures += await check_industry_whitelists(client, key)
    print(f"\n{'全部通过' if failures == 0 else f'{failures} 项失败'};今日({date.today()})实拉。")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
