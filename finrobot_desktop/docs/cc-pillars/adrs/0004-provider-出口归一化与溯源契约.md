# ADR-0004: Provider 出口归一化与溯源契约

| | |
|---|---|
| **版本** | v1.0 |
| **状态** | Accepted |
| **日期** | 2026-05-28 |
| **作者** | finrobot-architect + finrobot-finance-auditor (Opus 4.7) |
| **触发** | TSLA 详情页一连串数字错误的根因诊断（52W 高低点、年涨幅、provider 标签撒谎、P/E/EV-EBITDA TTM 落后、freshness pill 撒谎、日涨跌读成昨日） |

---

## 0. TL;DR

在 `DataLayer.fetch()` 出口处新增 `finrobot/engine/data/normalize/` 强制归一化层：
provider 仍只吐"尽力而为的原始 dict"，归一化层把它压成 **typed canonical 结果**
（`NormalizedPrice` / `NormalizedFinancials`），每个结果自带 `Provenance`
（provider / as_of / fetched_at / degraded[]），每条价格 bar 自带 OHLC-或-降级标记，
币种/as_of/来源是**字段**不是约定。cache 存归一化后的 canonical，三个发散的 PRICE 缓存槽
收口成一份，compute/extractor 消费 typed 模型（删 30+ 处裸 `data.get()`），
provenance 一路流到 UI 的 `SourcedNumber` 组件。

这根治两个承重缺陷，不是补三个洞。

---

## 1. Context

### 1.1 两个承重根因

详情页 9 个数字错误收敛到两个独立根因：

**根因 #1 — provider 契约是假的，provenance 不流动。**
`finrobot/engine/data/keys.py` 自承 "Runtime enforcement is deferred — providers
still return untyped dicts"。`DataResult.data` 没有强制 schema，`extractor.py` 靠
30+ 处裸 `data.get()` 默认了"只对 yfinance 成立"的形状：数组=1 日历年 OHLC、首元素=1 年前、
带 `fetched_at`。FMP 主路径下这些假设全不成立（曾返回 365 个交易日≈17 月、`serietype=line`
只有收盘价、无 `fetched_at`、无币种字段），但 dict shape 看着一样，于是静默错。
爆炸半径 = 生产默认链（FMP→Finnhub→yfinance）下的**每一个 ticker**。

**根因 #2 — 同一数字多缓存槽/多公式重复推导，freshness 绑在"抓取动作"而非"数据时点"。**
PRICE 有三条取数路径各写各的缓存键：① `/price` route 写 `ticker:period`（直调
`fetch_price_history`）② provider 链写 `ticker`（`_provider_price_cache_payload` 再捞回）
③ `get_financials` 内部又 `fetch(DataType.PRICE)` 给 extractor 算 52W。三份可能不同步。
freshness pill 读 route "合成"的 `fetched_at`（= 抓取墙钟时刻），而非数据语义时点，
于是底层是昨日收盘价时仍显示"近实时·刚刚"。

### 1.2 审计员钉出的缺陷清单（TSLA 实测）

| # | 数字 | 缺陷类 | 根因 |
|---|---|---|---|
| A | TickerHero 日涨跌 = `closes[-1]-closes[-2]` = 昨日日间变动 | 窗口选择 | #2 |
| B | freshness pill "近实时·刚刚"，底层是昨日收盘 | freshness 脱节 | #2 |
| C | EV/EBITDA 157x 口径异常无 warning | 口径不传递 | #1 |
| D | P/E 两条公式路径（FMP profile pe vs mc/ΣNI）可发散 | 多公式 | #2 |
| E | 现价存 financials(24h) 与 price(15min) 两槽，隔天必发散 | 多缓存槽 | #2 |
| F | FMP financials 无 country/currency → ADR EV/EBITDA 币种错配不报警 | 契约缺字段 | #1 |
| G | `next_earnings_date` 仅 yfinance 路径设，FMP 路径永久 null | provenance 缺失 | #1 |
| H | 跨源校验只覆盖 FINANCIALS 双 provider；SEC XBRL 真值、price/52w/EV 零校验 | 校验缺口 | #1/#2 |
| I | 行情快照标签硬编码 `yfinance`/`SEC 10-K`，实为 FMP | provenance 撒谎 | #1 |

（52W 高低点、365D 涨幅已先打补丁修正，本 ADR 将其收敛进归一化层。）

## 2. Decision

**新建 `finrobot/engine/data/normalize/` 包，作为 provider 与 cache/compute
之间的强制出口关卡，挂在 `DataLayer.fetch()`——所有取数路径（route、pipeline、
cross-validate）的唯一交汇点。**

```
finrobot/engine/data/normalize/
  __init__.py
  contracts.py      # canonical pydantic 模型
  price.py          # normalize_price(DataResult) -> NormalizedPrice
  financials.py     # normalize_financials(DataResult) -> NormalizedFinancials
  window.py         # 唯一的 trailing-52-周日历窗实现（收敛 extractor/fmp/前端三处补丁）
```

provider 职责不变（只吐原始 dict）；归一化在**一处**（强化红线 #3：DataProvider 抽象 +
归一化只在一个地方）；cache 存 canonical（解决发散：三槽存同一契约）；
compute 消费 typed（删 `data.get()`）。

`normalize/` 在 `engine/data/` 下，不在 `compute/`/`models/` 叶子层，可以 import
provider 的 `DataResult`；它不 import pipelines/agents/orchestrator/LLM —— 不违反叶子层红线。

### 2.1 契约 schema（pydantic）

```python
class Provenance(BaseModel):
    provider: str                 # 归一化层填的真实来源，杀死 ":provider-cache" 拼接谎言
    as_of: datetime               # 数据语义时点（最近 bar 日期 / period_end）
    fetched_at: datetime          # 网络抓取墙钟时间
    from_cache: bool = False
    degraded: list[str] = []      # ["close_only","ttm_lag_1q","ccy_inferred"]

class PriceBar(BaseModel):
    date: date
    close: float
    open: float | None = None     # None ⇒ 该 bar 仅收盘价
    high: float | None = None
    low: float | None = None
    volume: float | None = None

class NormalizedPrice(BaseModel):
    ticker: str
    quote_currency: str
    bars: list[PriceBar]          # 升序、已裁到 trailing-52-周日历窗
    current_price: float
    is_ohlc_complete: bool        # False ⇒ close-only，52W 用 close 兜底 + degraded
    exchange: str | None = None
    provenance: Provenance
    def fifty_two_week_high(self) -> float | None: ...
    def fifty_two_week_low(self) -> float | None: ...
    def trailing_1y_return_pct(self) -> float | None: ...   # 锚 365 日历日前 close
    def intraday_change(self) -> tuple[float|None, float|None]: ...  # 修审计 A

class NormalizedFinancials(BaseModel):
    ticker: str
    reporting_currency: str       # IS/BS 币种
    quote_currency: str           # 市值/价格币种（ADR 可不同）
    period_end: date | None       # TTM 最近季度截止
    period_basis: Literal["ttm","annual","quarterly"]
    as_of: datetime
    revenue: float
    ebitda: float | None
    pe_ratio: float | None
    pe_ttm_lag_quarters: int | None    # >0 → UI 标"TTM 截至 X，落后 N 季"
    # ... 现有 keys.py 字段，全部带类型，required 单一校验点
    provenance: Provenance
```

要点：`is_ohlc_complete=False`+`degraded=["close_only"]` 让"用 close 兜底算 52W"
**显式**；`pe_ttm_lag_quarters` 把"P/E 分母落后一季"变成可见数字；
`Provenance.provider` 杀死 `data.py` 的 `:provider-cache` 拼接谎言。

### 2.2 数据流

```
provider.fetch()  →  原始 DataResult.data (尽力而为 dict)
        ▼
DataLayer.fetch() ── normalize/{price,financials}.py  ← 唯一归一化关卡
        │   · 裁 trailing-52-周日历窗 (window.py 一处)
        │   · 判 OHLC 齐全 → is_ohlc_complete / degraded
        │   · 统一币种、填 Provenance、算 pe_ttm_lag_quarters
        ▼
   cache.set(canonical)   ← 三个发散槽收口成一份契约
        ├─→ routes/data.py  /price /financials   (删 fetch_price_history 旁路)
        ├─→ routes/compute.py  pipeline fetch      (复用同一 canonical)
        └─→ compute/extractor.py                   (消费 typed，删 data.get())
                  ▼  API 响应每个数字带 source{provider,as_of,currency,degraded}
            ui SourcedNumber  ← MarketDataZone 每个 Kv 单元格包裹
```

## 3. Alternatives Considered

### 3.1 在 provider 基类后置钩子归一化
**Rejected.** 会让每个 provider 子类各自承担归一化，等于把"yfinance 假设"换成
"每 provider 各归一化"，发散问题换个地方复发；且基类钩子要 import pydantic 模型，
模糊 provider "只取原始数据" 的职责。

### 3.2 在 route 层归一化
**Rejected.** 三个 route + pipeline 内部 fetch 都要消费，放 route 会重复三遍，
且 `compute.py` 的 pipeline fetch 绕过 route。归一化必须在比 route 更靠近数据源的共享点。

### 3.3 维持 keys.py 的 TypedDict 文档契约
**Rejected.** TypedDict 是文档不是契约，运行时零强制——正是病根。canonical 必须是
运行时强制的 pydantic 模型。

## 4. Consequences

### Positive
- provider 契约从"文档"升级为"运行时强制"；新 provider 必须过契约才能进 compute。
- 三个 PRICE 缓存槽收口成一份 canonical，杀死隔天发散。
- provenance（来源/截至日/币种/降级）成为一等公民，一路流到 UI，不再硬编码撒谎。
- TTM 落后、close-only 降级对用户**可见**而非静默。
- extractor 删 30+ 处 `data.get()`，"字段缺失"与"字段为 0"不再混淆。

### Negative
- cache 存储形状改变 → 必须清旧 sqlite（建设期零风险，直接重建）。
- 一次性触及 ~10 个后端文件 + UI，分 7 步降低单步风险。

### Out of scope（防 scope 蔓延）
- 断路器 / provider 熔断（BACKLOG:512）。
- provider 限速归一（各 provider 各自为政的债，独立处理）。
- A 股/港股新数据源（本契约为其铺路，本次不实现）。

## 5. Implementation Notes

### 5.1 构建顺序（每步独立可提交）
1. `normalize/contracts.py` 契约模型（纯新增零行为改动）。
2. `normalize/window.py` 收敛 extractor 的 52 周窗口逻辑（纯搬家）。
3. `normalize_price` + `normalize_financials`（5 fixture 单测，仍无人调用）。
4. `DataLayer.fetch` 接归一化 + cache 存 canonical + 清旧缓存。
5. 收口 3 个 PRICE 槽：删 `_provider_price_cache_payload` /
   `_enrich_price_payload_from_financial_cache` / `_price_change_from_history` /
   `fetch_price_history` 旁路；日涨跌改用真实当日 quote（修审计 A）。
6. extractor 消费 typed；`MarketData`/`ValuationMetrics`/`PriceHistory` 加 provenance + period_end。
7. API 带 provenance + UI 接 `SourcedNumber`；freshness pill 绑数据 `as_of`（修审计 B）。

### 5.2 被取代/删除
- `routes/data.py`: `_provider_price_cache_payload`、`_enrich_price_payload_from_financial_cache`、`_price_change_from_history`、`fetch_price_history` 旁路。
- `extractor.py`: `_FIFTY_TWO_WEEK_DAYS`/`_bar_date`/`_bar_extreme`/`_trailing_52w_high_low` → 移入 `window.py`。
- `fmp_provider.py:_PRICE_HISTORY_DAYS` 与 `MarketDataZone.tsx` 的 -365 锚 → 收敛，日历窗只在 `window.py` 定义。
- `layer.py:_is_cache_contract_current` 的 fmp-only `period_basis` 兜底 → canonical 后删除。
- `keys.py` REQUIRED_KEYS 执行点统一到 normalize。

### 5.3 BACKLOG 对账
- `specs/BACKLOG.md:509`「DataSourceFactory 统一归一化」= 本 ADR 的落地，升级为带契约的硬条目。
- `:247 A2`「/price 等接缓存」标 [x] 是**半真**：缓存接了、canonical 单源没接 —— 本 ADR step 5 收口。

### 5.4 Roll back
1-3 纯新增，`git rm normalize/` 即可。4 是 cache 迁移临界点（清缓存可重建）。
5-7 逐路径切换，每步独立 revert。

---

## 6. Open Questions
- 跨源校验是否扩到 price/52w（审计 H）？本次先把 SEC XBRL 纳入 FINANCIALS 校验链，price 校验留后。
- `degraded` 标记在 UI 的呈现密度（每个数字一个角标 vs 卡级汇总）——交 frontend 落地时定。
