# ADR-0001: ArtifactSummary 新字段 + 信号灯放后端叶子层

| | |
|---|---|
| **版本** | v1.0 |
| **状态** | Proposed（待评审 → 阻塞 v5 PR1 + 后续 §6.14 我的研究 / §6.1 HERO 全部 P4 PR） |
| **日期** | 2026-05-21 |
| **作者** | finrobot-architect (Opus 4.7) |
| **触发** | v5 改版规格 §7.1 / §7.2 / §7.3，PR1 必发 |
| **依据** | 实地核对 `finrobot/artifact/store.py` 是 JSON 文件存储（不是 SQL）·`finrobot/artifact/models.py:120-131` 现版 ArtifactSummary 8 字段 ·`finrobot/models/journal.py:31-32` 已有 entry_price/target_price 语义 |

---

## 0. TL;DR

**ArtifactSummary 加 4 字段**：`entry_price` / `target_price` / `target_date` / `signal`，全部 `default None`。

**新建叶子层** `finrobot/engine/compute/signal.py`：纯函数 `compute_signal()` + `compute_hit_rate()`，是「我的研究」section 命中率 / 信号灯 / 平均超额收益的唯一计算入口。

**JSON 文件 store** 无需 migration script——Pydantic 反序列化老 artifact 时 4 字段自动为 None，UI 判 None 不渲染信号灯，永远向后兼容。

**红线核对**：信号判定是纯函数，无 LLM 介入；前端禁止重新计算命中率；compute/signal.py 是叶子层不 import agents/pipelines/orchestrator。

---

## 1. Context / Problem statement

### 1.1 业务需求来源

v5 规格 §6.14「我的研究」section 要求每条 artifact 展示：

- **当时 vs 现在的价格对比**：跑分析时 quote → 现在 quote
- **AI 给的目标价**：从 thesis step 落地
- **信号灯**：🟢 hit · 🟡 watching · 🔴 failed —— 帮散户一眼看出"我以前判断准不准"
- **命中率横幅**：N 次中 X 次命中（XX%）+ 平均超额收益 vs SP500

§7.3 进一步要求横幅显示规则消除 survivor bias：命中率分母用「已结案集合」（hit + failed），平均超额基于所有已结案 artifact（不只算 hit）。

### 1.2 现有 ArtifactSummary 的缺口

`finrobot/artifact/models.py:120-131` 当前 ArtifactSummary 8 字段：

```python
class ArtifactSummary(BaseModel):
    id: str
    ticker: str | None
    cross_tickers: list[str]
    type: ArtifactType
    created_at: datetime
    headline: str
    source: str
    archived: bool = False
```

**缺**：跑分析时的快照价 / AI 给的目标价 / 目标日期 / 当前信号。这 4 个字段不补，「我的研究」section 渲染不了任何信号灯。

### 1.3 早期 spec 漂移点（已纠正）

早期 spec 写"ALTER TABLE artifacts ADD COLUMN signal"是错的。实地核对 `finrobot/artifact/store.py:1-90` 后确认：

```
~/.finrobot-desktop/artifacts/<ticker>/<artifact_id>.json  ← 单 artifact JSON
~/.finrobot-desktop/artifacts/<ticker>/index.json          ← ArtifactSummary 列表 JSON
~/.finrobot-desktop/artifacts/_cross/...                   ← 跨 ticker 同结构
```

**实际是 JSON 文件存储**，写入走 `_write_atomic`（tempfile + os.replace），无 SQL schema。字段演化只需 Pydantic 模型加默认值字段，**无 migration script**。

### 1.4 与 journal model 的语义对位

`finrobot/models/journal.py:31-32` 已有：

```python
entry_price: float
target_price: float | None = None
```

journal 是「Decision Journal」（用户主动建仓登记），artifact 是「分析快照」（pipeline 产出审计链）。两者语义不同但「目标价 / 入场价」字段含义一致——v5 PR1 复用语义而非重新发明。v3 重启 journal UI 时（v5 砍掉了 journal menu），journal entry 通过 `source_artifact_id` 反向关联 artifact，不复制数据。

---

## 2. Decision

### 2.1 ArtifactSummary 加 4 字段（全部 default None）

```python
# finrobot/artifact/models.py:120 修订
from finrobot.engine.compute.signal import Signal  # Literal["hit", "watching", "failed"]


class ArtifactSummary(BaseModel):
    """Sidebar / Library view — strips heavy fields."""

    id: str
    ticker: str | None
    cross_tickers: list[str]
    type: ArtifactType
    created_at: datetime
    headline: str
    source: str
    archived: bool = False

    # ── v5 新增（语义沿用 journal model）─────────────────────────
    entry_price: float | None = None
    """触发 pipeline 时的 quote 快照（USD/股）。对应 journal.entry_price 语义。

    None 表示：老 artifact（v5 前创建）或本次 pipeline 未注入 quote
    （cross-ticker artifact 默认 None，无单一 entry price）。
    """

    target_price: float | None = None
    """thesis step LLM 给出的 12 个月目标价（USD/股）。对应 journal.target_price 语义。

    None 表示：老 artifact、thesis step 未产出（如 peer_research / ad_hoc 类型）、
    或 cross-ticker artifact。
    """

    target_date: datetime | None = None
    """目标价对应的目标日期。默认 created_at + 365 天，thesis step 可覆盖。

    None 表示：老 artifact 或 target_price 本身为 None。
    """

    signal: Signal | None = None
    """list 端点 lazy 计算的当前信号（hit / watching / failed）。

    由 finrobot/engine/compute/signal.py:compute_signal() 唯一计算。
    None 表示：缺少 entry_price / target_price / current_price 三者之一，
    UI 应判 None 不渲染信号灯且不计入命中率统计。
    """
```

`entry_date` **不单独加**——直接复用 `created_at`（artifact 不可变，创建时间就是入场时间）。

### 2.2 新建叶子层 `finrobot/engine/compute/signal.py`

```python
"""信号灯 + 命中率纯函数。

Leaf-layer rules: no imports from agents/pipelines/orchestrator/pydantic_ai/openai.
唯一 import：标准库 datetime/typing + pydantic（数据类型）+
finrobot.artifact.models（读 ArtifactSummary）。

注意：signal.py import artifact.models 不破红线——artifact/ 不是 agents/pipelines/
orchestrator，是审计链数据层。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

Signal = Literal["hit", "watching", "failed"]


def compute_signal(
    target_price: float,
    entry_price: float,
    current_price: float,
    entry_date: datetime,
    target_date: datetime | None = None,
    *,
    now: datetime | None = None,
) -> Signal:
    """根据价格演变 + 时间窗口判定信号。

    规则（v5 §7.1）：
    - hit:      现价已在目标价 ±10% 内 OR 朝目标方向已走超 50%
    - failed:   反方向走 >10% 且距入场 ≥7 天 OR 超过 target_date 未达成
    - watching: 其余（含跑分析 <7 天的所有情况）

    Args:
        now: 测试注入用，生产环境 default = datetime.now(UTC)
    """
    ...


def compute_hit_rate(summaries: list[ArtifactSummary]) -> HitRateStats:
    """聚合命中率统计（消除 survivor bias）。

    Returns:
        n_total           = len(summaries with signal != None)
        n_closed          = count of signal in {hit, failed}
        n_hit             = count of signal == hit
        hit_rate          = n_hit / n_closed（n_closed == 0 时为 None）
        avg_excess_return = mean(ticker_return - sp500_return) over closed
                            （n_closed == 0 时为 None）
    """
    ...
```

**唯一性约束**：「命中率 / 信号灯 / 平均超额收益」**只能**经 compute/signal.py 计算。CLI / SDK / route handler / 前端**全部**走此入口，前端**永不**重新计算。

### 2.3 JSON 文件 store 的字段演化策略

**核心赌注**：Pydantic + JSON 文件 = 字段演化零迁移成本。

| 场景 | 行为 |
|---|---|
| 新 artifact 写入 | 4 字段有值 → JSON 包含 4 个新 key |
| 老 artifact 读取（v5 前创建，JSON 缺 4 字段）| Pydantic default=None → 反序列化成功，4 字段全部 None |
| 老 index.json 读取（list_by_ticker 路径）| 同上，`ArtifactSummary.model_validate(entry)` 兜底 None |
| 反向回滚（删 4 字段）| 新 artifact 多余 key 由 Pydantic 默认忽略（`extra="ignore"`，BaseModel 默认行为）→ 永远可回滚 |

**不需要的工作**：
- ❌ migration script
- ❌ ALTER TABLE
- ❌ 升级数据库版本号
- ❌ 老用户数据备份

**唯一需要的写入侧适配**（§2.5）：thesis step 落 target_price / pipeline 触发处落 quote snapshot。

### 2.4 字段语义复用 journal model（一致性）

| ArtifactSummary 字段 | journal 对应 | 语义对位 |
|---|---|---|
| `entry_price: float \| None` | `JournalEntry.entry_price: float`（必填）| 入场价；artifact 允许 None（cross-ticker / 老数据），journal 必填 |
| `target_price: float \| None` | `JournalEntry.target_price: float \| None` | AI 目标价；都允许 None |
| `target_date: datetime \| None` | journal 无此字段（v3 evaluate）| artifact 默认 created_at + 365d |
| `signal: Signal \| None` | journal 无（journal 是用户主观登记，不算信号）| 仅 artifact 有 |

**Cross-reference**：`finrobot/models/journal.py:31-32`。v3 重启 journal UI 时 journal entry 加 `source_artifact_id: str | None` 反向关联，**不复制 entry_price / target_price**——一处更新即可同步。本 ADR 不动 journal schema。

### 2.5 写入侧约定

**thesis step（pipeline 内）**：

```python
# finrobot/engine/pipelines/<your_pipeline>.py thesis step 出口
artifact_summary.target_price = thesis_output.target_price_12m  # LLM 给出
artifact_summary.target_date = artifact.meta.created_at + timedelta(days=365)
# 如 thesis_output.target_date 显式提供（未来扩展），优先用 LLM 给的
```

**触发处（route handler / CLI / SDK）**：

```python
# finrobot/routes/runs.py 等 pipeline 触发入口
quote = await deps.data_layer.get_quote(ticker)  # DataProvider ABC
artifact_summary.entry_price = quote.current_price
```

**list 端点 signal lazy compute**：

```python
# finrobot/artifact/store.py:list_by_ticker 出口（或 routes 层）
async def list_by_ticker_with_signal(ticker, deps) -> list[ArtifactSummary]:
    summaries = await store.list_by_ticker(ticker)
    current = await deps.data_layer.get_quote(ticker)
    for s in summaries:
        if s.entry_price and s.target_price and current.current_price:
            s.signal = compute_signal(
                target_price=s.target_price,
                entry_price=s.entry_price,
                current_price=current.current_price,
                entry_date=s.created_at,
                target_date=s.target_date,
            )
    return summaries
```

`signal` 字段不持久化到 index.json（每次 list 时新算），避免"老 signal 跟着旧价格走"的脏数据。**实施期决策点**：是否每次 list 调用都 fetch quote = 1 次 yfinance hit。建议加 `signal_cached_at` + TTL=5min 短缓存到 ArtifactStore 内存层，但**这是实施细节不是 ADR 决议**。

### 2.6 信号灯规则放后端叶子层（架构红线）

**禁前端 hardcoded**：信号灯阈值（±10% / 50% / 7 天）不在 React 组件内。前端只渲染 `summary.signal` 字符串到 dot 颜色。

**禁 LLM 选数字**：compute_signal 是纯函数，输入是价格 + 日期，输出是 Literal。无 LLM 调用，无 prompt。架构师测试通过——"用一条好 prompt 调原始 LLM 能否得到同样结果？" → **不能**：因为这是确定性算出的判断，类别 (a)「确定性算出一个数字（或类别）」。

**叶子层守门**：

```bash
grep -rn "from finrobot.engine.\(pipelines\|agents\|orchestrator\)" finrobot/engine/compute/signal.py
grep -rn "pydantic_ai\|from openai\|import openai" finrobot/engine/compute/signal.py
```

两条 grep 必空——加进 `tests/audit/test_signal_rules.py` 守门。

---

## 3. Audit 测试 list（≥ 8 case）

新建 `tests/audit/test_signal_rules.py`，最少覆盖 8 个 case + 1 叶子层 grep + 反序列化兼容测试（放 `tests/unit/`）：

### 3.1 信号判定 8 case

| # | case | entry | target | current | 距入场天数 | target_date | 期望 signal | 触发的规则分支 |
|---|---|---|---|---|---|---|---|---|
| 1 | hit_in_band | 100 | 120 | 115 | 30 | None | `hit` | 现价在 target ±10% 内（\|115-120\|/120 = 4.2%）|
| 2 | hit_over_half | 100 | 120 | 112 | 30 | None | `hit` | 朝 target 方向涨 12，超过 expected_move(20) 的 50% |
| 3 | watching_early | 100 | 120 | 90 | 3 | None | `watching` | 距入场 <7 天，任何价格都 watching |
| 4 | watching_progress | 100 | 120 | 105 | 30 | None | `watching` | 朝 target 方向但 <50%（actual=5/expected=20=25%）|
| 5 | failed_reverse | 100 | 120 | 88 | 30 | None | `failed` | 反方向走 >10%（actual_move=-12，\|-12\|/100=12%）|
| 6 | failed_expired | 100 | 120 | 105 | 400 | created+365d | `failed` | 超过 target_date 未达成 |
| 7 | boundary_equal_target | 100 | 100 | 100 | 30 | None | `hit` | target_price == entry_price 时 expected_move=0，必须不 div0 |
| 8 | boundary_reverse_under_7d | 100 | 120 | 80 | 3 | None | `watching` | 反方向 >10% 但 <7 天，仍 watching（早期不熔断）|

**实现要点**：
- 测试通过 `now=` 参数注入时间，不依赖 `datetime.now()` 真实时钟
- target == entry 时 expected_move = 0，`actual_move / expected_move` 必须先 guard（spec §7.1 公式直接除会 div0）

### 3.2 命中率聚合 case

| # | case | 输入 | 期望输出 |
|---|---|---|---|
| 9 | hit_rate_basic | 5 artifact: 2 hit / 1 failed / 2 watching | n_total=5, n_closed=3, n_hit=2, hit_rate=0.667 |
| 10 | hit_rate_zero_closed | 5 artifact: 全部 watching | n_total=5, n_closed=0, hit_rate=None, avg_excess=None |
| 11 | avg_excess_includes_failed | 2 hit (+10%/+15%, sp500 +5%/+5%) + 1 failed (-12%, sp500 +3%) | avg_excess = mean(0.05, 0.10, -0.15) = 0.0 |

### 3.3 红线 grep 测试

```python
def test_signal_module_no_leaf_violation():
    src = Path("finrobot/engine/compute/signal.py").read_text()
    forbidden = ["from finrobot.engine.pipelines",
                 "from finrobot.engine.agents",
                 "from finrobot.engine.orchestrator",
                 "pydantic_ai", "from openai", "import openai"]
    for pattern in forbidden:
        assert pattern not in src, f"signal.py leaks into {pattern}"
```

### 3.4 反序列化兼容测试（放 `tests/unit/test_artifact_summary_backcompat.py`，不是 audit）

```python
def test_legacy_artifact_summary_missing_v5_fields_loads_with_none():
    legacy_json = {
        "id": "art_2025-01-01_AAPL_dcf",
        "ticker": "AAPL", "cross_tickers": [],
        "type": "dcf", "created_at": "2025-01-01T00:00:00Z",
        "headline": "DCF implied $185", "source": "cli", "archived": False,
        # 故意缺 entry_price / target_price / target_date / signal
    }
    s = ArtifactSummary.model_validate(legacy_json)
    assert s.entry_price is None
    assert s.target_price is None
    assert s.target_date is None
    assert s.signal is None
```

**为什么 case 12 放 unit 而不是 audit**：audit 是「架构红线」，反序列化兼容是「数据契约」，性质不同。但 ADR 必须点明这个 case 必写——否则 PR 合进去 1 周后用户老 artifact 全炸。

---

## 4. 命中率 / 平均超额收益公式

### 4.1 公式定义（消除 survivor bias）

设 `S` = 该 ticker 所有 ArtifactSummary（含老数据），`S_signaled` = `{s ∈ S | s.signal is not None}`，`S_closed` = `{s ∈ S_signaled | s.signal in {hit, failed}}`。

```
n_total   = |S_signaled|
n_closed  = |S_closed|
n_hit     = |{s ∈ S_closed | s.signal == "hit"}|

hit_rate         = n_hit / n_closed                  if n_closed > 0 else None
avg_excess_return = mean({excess(s) | s ∈ S_closed}) if n_closed > 0 else None

where excess(s) = ticker_return(s) - sp500_return(s)
      ticker_return(s) = (current_price - s.entry_price) / s.entry_price
      sp500_return(s)  = (sp500_now - sp500_at(s.created_at)) / sp500_at(s.created_at)
```

### 4.2 为什么分母用 n_closed 不是 n_total

早期 spec 写 `hit_rate = n_hit / n_total` 会被未结案的 watching 稀释。例：5 个分析 1 hit 4 watching，"命中率 20%" 严重低估——4 个 watching 还没到判定时间。改用 n_closed 后，命中率只反映已结案样本，更诚实。

### 4.3 avg_excess_return 必须含 failed（否则 survivor bias）

早期 spec 漏算 failed → 只算 hit 的超额 → 平均超额永远偏正。正确做法：hit + failed 全部纳入，failed 是负 excess，自然把虚高拉下来。

### 4.4 SP500 价格 fetch 来源

`finrobot/engine/data/providers/yfinance_provider.py` 已有 quote 能力。`compute_hit_rate` 不直接调 yfinance（叶子层禁直接 import provider SDK），而是接受**已 fetch 好的 sp500 价格 dict**：

```python
def compute_hit_rate(
    summaries: list[ArtifactSummary],
    *,
    current_price: float | None,         # 该 ticker 现价
    sp500_now: float | None,             # SP500 现价
    sp500_at_entry: dict[str, float],    # {artifact_id: sp500 价格 at created_at}
) -> HitRateStats:
    ...
```

route 层负责 fetch SP500（走 DataProvider ABC），compute 层负责纯计算。**红线**：compute/signal.py 不 import yfinance / FMP / Finnhub 任何 provider。

---

## 5. 回滚策略

### 5.1 字段层

4 个新字段全部 `default None`：

- 删字段 → 新 artifact 写入时缺这 4 个 key
- 老 artifact（已含 4 字段）反序列化时 Pydantic `extra="ignore"`（BaseModel 默认）→ 多余 key 被忽略
- **不破坏任何老数据**，前向后向兼容

### 5.2 compute 层

`engine/compute/signal.py` 是新文件，整体回滚 = `git rm`：

- routes 层删 signal 计算调用
- UI 端 `summary.signal` 永远是 None → empty state 自动生效

### 5.3 唯一不可逆点

**写入侧落地的 entry_price / target_price 数据本身**——一旦 thesis step 上线，新 artifact 含真实值。回滚 schema 不会反推删数据（也不需要，老字段不读取就行）。

### 5.4 回滚 PR 模板

```
revert: ADR-A signal fields (PR1)
- finrobot/artifact/models.py    : remove 4 fields
- finrobot/engine/compute/signal.py : delete file
- tests/audit/test_signal_rules.py  : delete file
- finrobot/routes/<runs>.py      : remove entry_price snapshot
- finrobot/engine/pipelines/.../thesis.py : remove target_price/target_date writes
```

---

## 6. Consequences

### 6.1 正面

- **解锁 §6.14「我的研究」** section：信号灯 / 命中率横幅 / sparkline 全部依赖这 4 字段
- **解锁 §6.1 HERO**：HERO 顶部显示"AI 之前判断 NVDA：3 hit / 2 watching / 1 failed"需要 signal 字段
- **零迁移成本**：JSON 文件 store + Pydantic default = 老 artifact 零修改
- **唯一计算入口**：CLI / SDK / route / 前端共享 compute/signal.py，永不出现"前端算的命中率和后端不一致"
- **架构红线收紧**：信号判定规则代码化，未来散户/产品想改阈值必须改 compute/signal.py + 跑 audit 测试

### 6.2 负面

- **写入侧需在 thesis step 加 ~2 行**（落 target_price + target_date）+ **触发处加 quote snapshot ~1 行**（落 entry_price）
- **list 端点每次 lazy compute signal** = 多 1 次 quote fetch（建议加 5min 短缓存，留实施期决策）
- **新增 audit 测试文件 + ≥8 case**，CI 时间略增（估 <1 秒）
- **cross-ticker artifact**（如 peer_research）的 4 字段永远 None——UI 端必须有 empty state 兜底，否则 sparkline 渲染空白

### 6.3 中性

- v3 重启 journal UI 时需在 journal model 加 `source_artifact_id: str | None` 反向关联——本 ADR 不做，但点出。
- `target_date` 默认 created_at + 365d 是行业惯例（sell-side 12 个月目标价），未来如改成 24 个月也是改 thesis step 默认值，ADR 不锁死。

---

## 7. Alternatives Considered

### 7.1 字段放 Artifact 而非 ArtifactSummary

**拒绝原因**：ArtifactSummary 是 list 端点直接返回的轻量结构，「我的研究」section 渲染依赖 list 端点。如果放 Artifact，每条记录要再 fetch 一次 full Artifact (~10KB) → N+1 query。Summary 几百字节，加 4 个 optional 字段开销 <50 字节。

### 7.2 signal 持久化到 index.json

**拒绝原因**：signal 是「当前现价 vs 历史 target」的实时函数，持久化的 signal 会跟着旧价格走变脏。lazy compute 永远新鲜。代价是每次 list 多 1 次 quote fetch——5min 短缓存可控。

### 7.3 信号阈值前端可配置

**拒绝原因**：散户调阈值的产品价值≈0，但风险=破坏「唯一计算入口」红线。如果未来产品需要 A/B 测不同阈值，应该后端加 `signal_profile: Literal["lenient", "strict"]` 字段而非把规则散到前端。

### 7.4 ALTER TABLE artifacts ADD COLUMN signal

**拒绝原因**：实地核对 store.py 后确认 artifact 存储是 JSON 文件不是 SQL，根本不存在 table 可以 ALTER。早期 spec 漂移，本 ADR 纠正。

### 7.5 LLM 给信号判定

**拒绝原因**：直接违反核心赌注「数字由代码算出，判断由 LLM 给出」。信号灯不是「判断」是「事实分类」（涨了 50% 是事实不是观点），必须代码确定性算出。架构师测试硬性 fail。

---

## 8. Implementation Notes（给 PR1 实施者）

### 8.1 文件改动清单

| 文件 | 改动 | 估行数 |
|---|---|---|
| `finrobot/engine/compute/signal.py` | 新建：Signal Literal + compute_signal + compute_hit_rate + HitRateStats | ~120 |
| `finrobot/artifact/models.py` | +4 字段 + import Signal | +15 |
| `finrobot/artifact/store.py` | 无需改 — Pydantic 自动兼容；list_by_ticker 出口可选 lazy compute（建议在 routes 层做不污染 store）| 0 |
| `finrobot/routes/artifacts.py`（或类似） | list 端点加 signal lazy compute + SP500 fetch | ~40 |
| `finrobot/engine/pipelines/<thesis 所在>.py` | thesis step 落 target_price + target_date | ~5 |
| `finrobot/routes/runs.py`（pipeline 触发处）| 落 entry_price quote snapshot | ~3 |
| `tests/audit/test_signal_rules.py` | 8 case + 红线 grep | ~150 |
| `tests/unit/test_artifact_summary_backcompat.py` | 老 JSON 反序列化兼容 | ~30 |
| **合计** | | **~363** ≈ spec §13 估算 ~400 LoC |

### 8.2 不在本 PR 做的事

- ❌ 前端 sparkline 组件（PR15）
- ❌ HERO 顶部判断卡（PR9）
- ❌ journal 重启 / source_artifact_id（v3）
- ❌ signal 持久化（永远 lazy）
- ❌ 多 ticker 命中率汇总（聚合页 v2.1）

### 8.3 PR1 验收标准（对应 spec §15）

1. `pytest tests/audit/test_signal_rules.py -v` 全过（≥8 case + 红线 grep）
2. `pytest tests/unit/test_artifact_summary_backcompat.py` 通过
3. 老 artifact JSON（v5 前的真实样本）能正常 list 出来且 signal=None
4. 触发一次 DCF pipeline → 新 artifact 4 字段全部有值（target_price 来自 thesis，entry_price 来自触发 quote）
5. `ruff check finrobot/engine/compute/signal.py` 通过
6. `mypy finrobot/engine/compute/signal.py` 通过
7. `pytest tests/audit/` 全部红线测试不破

---

## 9. 评审 Checklist

- [ ] 4 个新字段全部 default None（向后兼容前提）
- [ ] compute/signal.py 是叶子层（grep 守门测试入 audit）
- [ ] 信号阈值（±10% / 50% / 7 天）只在 compute/signal.py 一处定义
- [ ] 命中率公式分母 = n_closed 不是 n_total（消除 survivor bias）
- [ ] avg_excess_return 含 failed（消除 survivor bias）
- [ ] target_date 默认 created_at + 365d 在 thesis step 实现，不写死在前端
- [ ] 老 artifact JSON 反序列化兼容 case 入 tests/unit/
- [ ] cross-ticker artifact 4 字段 None → UI 有 empty state（非本 PR，记入 PR15 验收）
- [ ] 回滚 PR 模板 §5.4 可执行（git rm + 字段删除一次性）

---

## 10. 参考

- v5 改版完整规格 §7.1 / §7.2 / §7.3 / §13 / §14
- `finrobot/artifact/models.py:120-131`（现 ArtifactSummary）
- `finrobot/artifact/store.py:1-90, 269-340`（JSON 文件 store + list_by_ticker）
- `finrobot/models/journal.py:31-32`（entry_price / target_price 语义来源）
- `finrobot/engine/compute/market.py:11`（叶子层规则注释模板）
- CLAUDE.md 红线 #1 / #2 / #5
- 核心赌注：「数字由代码算出，判断由 LLM 给出」
