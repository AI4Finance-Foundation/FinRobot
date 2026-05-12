# SPEC-desktop-v1.md — FinAgent Desktop V1 Product & Protocol Specification

> **Status**: Final — 三方讨论共识（用户 + Codex + 独立监督者），2026-05-08
>
> **约束**: 本文件是 Desktop V1 所有实现的唯一边界。不在此文件中的功能不做。
>
> **技术决策已锁定（§9）：** OS keychain、SQLite runs、openapi-typescript + openapi-fetch、Zustand + React Query、7x7 sensitivity。

---

## 1. Product Scope

### 1.1 目标用户

**V1 只服务一类人：** 小基金投资经理、独立分析师、严肃个人研究者。

他们的共同特征：
- 懂金融建模（DCF、comps、LBO 不需要解释）
- 没有 Bloomberg Terminal 预算（$24K/年）
- 用过 ChatGPT 做分析但不信任 LLM 的数字
- 有能力判断假设是否合理，但不想从零搭 Excel 模型

**V1 不服务：** 个人散户（需要太多教育）、量化开发者（用 SDK/CLI）、内容创作者（需要分享/社交功能）。

### 1.2 核心定位

> **当用户要认真分析一家公司时，FinAgent 能比 ChatGPT 更可信、比 Excel 更快、比 FinRobot 更工程化。**

产品灵魂：**代码保证数字是算出来的，不是编出来的。**

### 1.3 V1 成功标准

用户打开一个 ticker，能完成：
1. 看到结构化的公司财务数据（来源明确、warnings 可见）
2. 获得 AI 生成的初始估值假设（LLM 负责判断）
3. 手动调整任何假设，实时看到估值变化（代码负责计算）
4. 导出专业报告（HTML/PDF/Excel）

**整个流程在本地完成，无云依赖。**

### 1.4 V1 不做（显式排除）

| 功能 | 排除理由 |
|---|---|
| Watchlist / 持仓跟踪 | 需要实时数据管道 + 后台服务，V1 数据源不支持 |
| 新闻 / 异动提醒 | 需要新闻 API + 推送机制 |
| 每日看板 / Dashboard | V1 是按需分析工具，不是信息消费工具 |
| 多 ticker 对比视图 | V2，先把单 ticker 做到极致 |
| Skills 执行引擎 | 56 个 skills 暂为方法论素材，不是可执行功能 |
| 社交/分享/协作 | V3+ |

---

## 2. Killer Workflow — 交互式 DCF

这是 V1 的杀手级工作流，也是桌面端存在的理由。CLI 做不到这个。

```
[Step 1] 输入 Ticker
  用户输入 AAPL
  → 桌面端调用 GET /api/data/AAPL/financials
  → 2-5 秒，从 provider chain 拉数据
  → 展示公司基本面：收入、EBITDA、margin、市值、debt/cash
  → 数据来源标签（yfinance/FMP/Finnhub）
  → 数据缺失 warnings 明确展示

[Step 2] 生成初始模型（LLM 参与的唯一步骤）
  用户点击 "Run DCF Analysis"
  → 桌面端调用 POST /api/runs
  → 后端启动 DCF pipeline，SSE 推送进度
  → 30-60 秒，LLM 生成 DCFInputs（revenue growth、margin、WACC 组件等）
  → 返回 DCFResult：implied price、sensitivity matrix、FCF projections
  → 桌面端渲染：估值卡片 + sensitivity heatmap + waterfall chart + FCF bar chart

[Step 3] 交互式假设调整（杀手级体验）
  用户拖 WACC slider（比如从 10% 调到 12%）
  → 桌面端调用 POST /api/compute/dcf，传入修改后的 DCFInputs
  → <100ms 返回新的 DCFResult
  → 估值、sensitivity matrix、waterfall 实时更新
  → 无 LLM、无等待、纯前端交互
  
  用户可调整的参数：
  - Revenue growth rates（每年独立）
  - EBITDA margin
  - WACC 组件（risk-free rate、beta、ERP、cost of debt、debt ratio）
  - Terminal growth rate
  - Capex % / NWC %
  - Tax rate

[Step 4] 导出
  → "Export Excel" → GET /api/export/excel/dcf/AAPL → 下载 .xlsx
  → "Export PDF"  → GET /api/report/pdf?ticker=AAPL → 下载 .pdf
  → "View Report"  → GET /api/report/html?ticker=AAPL → 内嵌预览
```

**关键架构决策：** LLM 只在 Step 2 参与一次。Step 3 的所有重计算走纯函数 compute API，亚秒响应。这就是"代码保证数字是算出来的"的产品化。

---

## 3. API Contract

### 3.1 端点总览

所有端点以 FastAPI 实现，OpenAPI schema 自动生成，桌面端从 schema 生成 TypeScript 类型。

#### Settings（配置同步）

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/settings` | 获取当前配置（API keys 脱敏返回） |
| `PUT` | `/api/settings` | 更新配置（支持部分更新） |

#### Data（数据查询，无 LLM）

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/data/{ticker}/financials` | 从 provider chain 拉结构化财务数据 |
| `GET` | `/api/data/{ticker}/price` | 当前价格 + 历史价格 |

#### Compute（纯函数计算，无 LLM，无 I/O）

| 方法 | 路径 | 输入 | 输出 | 延迟 |
|---|---|---|---|---|
| `POST` | `/api/compute/wacc` | 6 个 float | `{cost_of_equity, wacc}` | <1ms |
| `POST` | `/api/compute/dcf` | `DCFInputs` | `DCFResult` | <100ms |
| `POST` | `/api/compute/dcf-sensitivity` | `DCFInputs` + `wacc_range` + `tg_range` | sensitivity grid | <1s |
| `POST` | `/api/compute/lbo` | `LBOInputs` | `LBOResult` | <50ms |
| `POST` | `/api/compute/lbo-sensitivity` | `LBOInputs` + ranges | IRR/MOIC grid | <2s |
| `POST` | `/api/compute/multiples` | `CompanyFinancials` | enriched with ratios | <5ms |
| `POST` | `/api/compute/peer-stats` | `PeerComps` | stats (mean/median) | <5ms |

#### Runs（Pipeline 执行，含 LLM）

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/runs` | 创建并启动 pipeline run，返回 `run_id` |
| `GET` | `/api/runs/{run_id}/events` | SSE 流，推送 run 进度 |
| `GET` | `/api/runs/{run_id}` | 获取 run 状态和结果 |
| `GET` | `/api/runs` | 列出历史 runs |

#### Export（报告导出）

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/export/excel/{type}/{ticker}` | 下载 .xlsx（type: dcf/lbo/comps） |
| `GET` | `/api/report/html?ticker={ticker}` | 获取 HTML 报告 |
| `GET` | `/api/report/pdf?ticker={ticker}` | 下载 PDF 报告 |

#### System

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/health` | 健康检查 |

---

### 3.2 Settings 端点详细设计

**`GET /api/settings`**

响应（API keys 脱敏）：
```json
{
  "model_name": "deepseek:deepseek-chat",
  "model_data": null,
  "model_analysis": null,
  "model_modeling": null,
  "model_synthesis": null,
  "model_report": null,
  "anthropic_api_key_set": true,
  "deepseek_api_key_set": false,
  "openai_api_key_set": false,
  "fmp_api_key_set": true,
  "finnhub_api_key_set": false,
  "sec_user_agent": "FinAgent admin@example.com",
  "log_level": "INFO",
  "available_providers": ["fmp", "yfinance", "sec_edgar"],
  "valid_model_providers": ["deepseek", "anthropic", "openai"]
}
```

**`PUT /api/settings`**

请求（部分更新，只传要改的字段）：
```json
{
  "model_name": "anthropic:claude-sonnet-4-6",
  "anthropic_api_key": "sk-ant-...",
  "fmp_api_key": "abc123"
}
```

响应：同 GET 格式（更新后的状态）。

**实现要求：**
- PUT 后必须重新初始化受影响的 provider（如新增 FMP key → 创建 FMPProvider 加入 data_layer）
- PUT 后必须调用 `validate_runtime_config()` 做 fail-fast 检查
- **API keys 通过 `SecretStore` 持久化**（生产用 OS keychain，dev 用加密文件）。见 §10。
- **非敏感配置**（model_name、log_level 等）写 `~/.finagent/settings.json`
- GET 永远不返回 API key 原文，只返回 `*_set: bool`
- 前端填写 key 后立即 PUT，不在 Zustand/localStorage 中保存原文

---

### 3.3 Data 端点详细设计

**`GET /api/data/{ticker}/financials`**

响应：
```json
{
  "ticker": "AAPL",
  "company_name": "Apple Inc.",
  "timestamp": "2026-05-08T10:30:00Z",
  "income": {
    "revenue": 385603000000,
    "ebitda": 134000000000,
    "net_income": 96995000000,
    "gross_margin": 0.462,
    "operating_margin": 0.302,
    "depreciation_amortization": 11100000000,
    "rd_expense": 29900000000,
    "sga_expense": null,
    "interest_expense": 3700000000
  },
  "balance": {
    "total_debt": 108000000000,
    "total_cash": 29965000000
  },
  "market": {
    "market_cap": 3200000000000,
    "shares_outstanding": 15400000000,
    "current_price": 207.79,
    "pe_ratio": 33.0,
    "price_52w_high": 260.10,
    "price_52w_low": 169.21
  },
  "valuation": {
    "enterprise_value": 3278035000000,
    "ev_ebitda": 24.46,
    "ev_revenue": 8.50
  },
  "data_source": "fmp",
  "warnings": []
}
```

**实现要求：**
- 内部调用 `data_layer.fetch(DataType.FINANCIALS, ticker)` + `extractor.extract_financial_data()`
- 返回类型就是现有 `FinancialData` 模型，Pydantic 直接序列化
- 如果 provider 返回数据有缺失字段，`warnings` 数组必须说明
- cache 策略：首次拉取走 provider chain，后续 5 分钟内走 cache

**`GET /api/data/{ticker}/price`**

响应：
```json
{
  "ticker": "AAPL",
  "period": "5y",
  "data_points": 1260,
  "current_price": 207.79,
  "high_52w": 260.10,
  "low_52w": 169.21,
  "avg_price": 198.50,
  "history": [
    {"date": "2021-05-08", "close": 129.74},
    {"date": "2021-05-09", "close": 130.21}
  ]
}
```

---

### 3.4 Compute 端点详细设计

所有 compute 端点：
- **无 LLM 调用**
- **无 I/O**
- **无认证要求**（本地服务）
- **幂等**：相同输入 → 相同输出
- 输入/输出直接使用现有 Pydantic 模型

**`POST /api/compute/dcf`**

请求体 = `DCFInputs` JSON（现有模型，零改动）：
```json
{
  "revenue_base": 385603000000,
  "revenue_growth_rates": [0.05, 0.05, 0.04, 0.04, 0.03],
  "ebitda_margin": 0.35,
  "capex_pct_revenue": 0.04,
  "nwc_pct_revenue": 0.02,
  "da_pct_revenue": 0.03,
  "tax_rate": 0.21,
  "risk_free_rate": 0.043,
  "beta": 1.24,
  "equity_risk_premium": 0.055,
  "cost_of_debt": 0.035,
  "debt_ratio": 0.15,
  "terminal_growth_rate": 0.025,
  "shares_outstanding": 15400000000,
  "net_debt": 78035000000
}
```

响应体 = `DCFResult` JSON（现有模型，零改动）：
```json
{
  "cost_of_equity": 0.1112,
  "wacc": 0.0987,
  "projection_years": 5,
  "projected_revenue": [404883150000, 425127307500, ...],
  "projected_ebitda": [141709102500, 148794457625, ...],
  "projected_fcf": [88286513975, 92700839674, ...],
  "terminal_value": 1234567890000,
  "pv_terminal": 789012345000,
  "pv_fcf_total": 345678901234,
  "enterprise_value": 1134691246234,
  "equity_value": 1056656246234,
  "implied_price": 68.61,
  "sensitivity_table": null,
  "inputs": { "...same as request..." },
  "fcf_formula": "standard_with_da",
  "fcf_formula_warning": null
}
```

**`POST /api/compute/dcf-sensitivity`**

请求体：
```json
{
  "inputs": { "...DCFInputs..." },
  "wacc_range": [0.08, 0.09, 0.10, 0.11, 0.12],
  "tg_range": [0.015, 0.020, 0.025, 0.030, 0.035]
}
```

响应体：
```json
{
  "wacc_values": [0.08, 0.09, 0.10, 0.11, 0.12],
  "tg_values": [0.015, 0.020, 0.025, 0.030, 0.035],
  "implied_prices": [
    [95.2, 102.3, 110.5, 120.1, null],
    [78.4, 84.1, 90.3, 97.2, 105.0],
    [65.1, 69.8, 74.9, 80.5, 86.7],
    [54.3, 58.1, 62.2, 66.7, 71.6],
    [45.6, 48.7, 52.0, 55.6, 59.5]
  ]
}
```

`null` = terminal growth >= wacc（数学上不成立）。

**`POST /api/compute/wacc`**

请求体：
```json
{
  "risk_free_rate": 0.043,
  "beta": 1.24,
  "equity_risk_premium": 0.055,
  "cost_of_debt": 0.035,
  "tax_rate": 0.21,
  "debt_ratio": 0.15
}
```

响应体：
```json
{
  "cost_of_equity": 0.1112,
  "wacc": 0.0987
}
```

---

### 3.5 Runs 端点详细设计（替代当前 `/api/pipeline/stream/`）

**`POST /api/runs`**

请求体：
```json
{
  "pipeline_type": "dcf",
  "ticker": "AAPL"
}
```

响应体：
```json
{
  "run_id": "run_abc123",
  "status": "created",
  "pipeline_type": "dcf",
  "ticker": "AAPL",
  "created_at": "2026-05-08T10:30:00Z"
}
```

**`GET /api/runs/{run_id}/events`** (SSE)

见下方 §4 SSE Event Protocol。

**`GET /api/runs/{run_id}`**

响应体：
```json
{
  "run_id": "run_abc123",
  "status": "completed",
  "pipeline_type": "dcf",
  "ticker": "AAPL",
  "created_at": "2026-05-08T10:30:00Z",
  "completed_at": "2026-05-08T10:30:45Z",
  "duration_s": 45.2,
  "result": {
    "text": "...narrative summary...",
    "structured": { "...DCFResult JSON..." }
  },
  "artifacts": [
    {"type": "dcf_result", "format": "json"},
    {"type": "report", "format": "html", "url": "/api/report/html?ticker=AAPL"}
  ],
  "warnings": ["D&A not available from yfinance; simplified FCF formula used"],
  "failed_validations": []
}
```

**`GET /api/runs`**

响应体：
```json
{
  "runs": [
    {
      "run_id": "run_abc123",
      "status": "completed",
      "pipeline_type": "dcf",
      "ticker": "AAPL",
      "created_at": "2026-05-08T10:30:00Z",
      "duration_s": 45.2
    }
  ]
}
```

---

## 4. SSE Event Protocol

统一事件格式。前后端共用同一份类型定义。

### 4.1 事件类型

```typescript
// 桌面端 TypeScript 定义（从 OpenAPI schema 生成）
type RunEvent =
  | { event: "run.started"; run_id: string; pipeline_type: string; ticker: string; total_steps: number }
  | { event: "step.started"; run_id: string; step: number; total: number; name: string }
  | { event: "step.completed"; run_id: string; step: number; total: number; name: string; duration_s: number }
  | { event: "step.retry"; run_id: string; step: number; name: string; attempt: number; error: string }
  | { event: "artifact.ready"; run_id: string; artifact_type: string; format: string }
  | { event: "run.completed"; run_id: string; ticker: string; duration_s: number; result_url: string }
  | { event: "run.failed"; run_id: string; error: string }
```

```python
# 后端 Python 定义（TypedDict）
from typing import TypedDict, Literal

class RunStarted(TypedDict):
    event: Literal["run.started"]
    run_id: str
    pipeline_type: str
    ticker: str
    total_steps: int

class StepStarted(TypedDict):
    event: Literal["step.started"]
    run_id: str
    step: int
    total: int
    name: str

class StepCompleted(TypedDict):
    event: Literal["step.completed"]
    run_id: str
    step: int
    total: int
    name: str
    duration_s: float

class StepRetry(TypedDict):
    event: Literal["step.retry"]
    run_id: str
    step: int
    name: str
    attempt: int
    error: str

class ArtifactReady(TypedDict):
    event: Literal["artifact.ready"]
    run_id: str
    artifact_type: str
    format: str

class RunCompleted(TypedDict):
    event: Literal["run.completed"]
    run_id: str
    ticker: str
    duration_s: float
    result_url: str

class RunFailed(TypedDict):
    event: Literal["run.failed"]
    run_id: str
    error: str

RunEvent = RunStarted | StepStarted | StepCompleted | StepRetry | ArtifactReady | RunCompleted | RunFailed
```

### 4.2 SSE 传输格式

```
event: step.started
data: {"event":"step.started","run_id":"run_abc","step":1,"total":4,"name":"Financial Data Extraction"}

event: step.completed
data: {"event":"step.completed","run_id":"run_abc","step":1,"total":4,"name":"Financial Data Extraction","duration_s":3.2}

event: run.completed
data: {"event":"run.completed","run_id":"run_abc","ticker":"AAPL","duration_s":45.2,"result_url":"/api/runs/run_abc"}
```

每个 SSE frame 使用 `event:` 字段做事件类型路由，`data:` 字段承载 JSON payload。

---

## 5. Desktop MVP Scope

### 5.1 视图结构

```
App
├── Settings View（首次使用引导 + 后续配置）
└── Ticker Workspace（核心）
    ├── Data Panel（公司基本面）
    ├── DCF Analysis Panel
    │   ├── Pipeline Progress（SSE 进度条）
    │   ├── Assumptions Editor（sliders + inputs）
    │   ├── Valuation Card（implied price + upside/downside）
    │   ├── Sensitivity Heatmap
    │   ├── Waterfall Chart（DCF bridge）
    │   └── FCF Projection Chart
    ├── Report Preview（内嵌 HTML）
    └── Export Bar（Excel / PDF / HTML 下载按钮）
```

**不做的视图（V1 排除）：**
- LBO Workspace（V2）
- Comps Workspace（V2）
- Earnings Review（V2）
- IC Memo Builder（V2）
- 10-K Q&A（V2）
- Watchlist（V3+，需要实时数据管道）
- 每日看板（V3+）
- History / Versions（V2）

### 5.2 交互式假设调整细节

**Slider 参数和范围（来自 DCFInputs Pydantic 验证）：**

| 参数 | 控件 | 范围 | 步长 | 来源 |
|---|---|---|---|---|
| WACC（计算值） | 只读显示 | — | — | 由下方组件计算 |
| Risk-free rate | Slider | 0% - 15% | 0.1% | `DCFInputs.risk_free_rate` Field(ge=0, le=0.15) |
| Beta | Slider | 0 - 5 | 0.01 | `DCFInputs.beta` Field(ge=0, le=5) |
| Equity risk premium | Slider | 0% - 15% | 0.1% | `DCFInputs.equity_risk_premium` Field(ge=0, le=0.15) |
| Cost of debt | Slider | 0% - 20% | 0.1% | `DCFInputs.cost_of_debt` Field(ge=0, le=0.20) |
| Debt ratio | Slider | 0% - 100% | 1% | `DCFInputs.debt_ratio` Field(ge=0, le=1) |
| Terminal growth rate | Slider | 0% - 5% | 0.1% | `DCFInputs.terminal_growth_rate` Field(ge=0, le=0.05) |
| EBITDA margin | Slider | 0% - 100% | 0.5% | `DCFInputs.ebitda_margin` Field(ge=0, le=1) |
| Tax rate | Slider | 0% - 100% | 1% | `DCFInputs.tax_rate` Field(ge=0, le=1) |
| Capex % revenue | Slider | 0% - 100% | 0.5% | `DCFInputs.capex_pct_revenue` Field(ge=0, le=1) |
| NWC % revenue | Slider | -20% - 50% | 0.5% | `DCFInputs.nwc_pct_revenue` Field(ge=-0.2, le=0.5) |
| Revenue growth (per year) | 输入框数组 | 自由 | — | `DCFInputs.revenue_growth_rates` list[float] |

**交互行为：**
- 用户调整任何 slider → 立即构造新的 `DCFInputs` → `POST /api/compute/dcf` → 更新所有图表
- debounce 策略：slider 拖动中每 100ms 最多发一次请求（<100ms 响应，不会积压）
- 如果 terminal_growth_rate >= wacc，sensitivity heatmap 对应 cell 显示 "N/A"（后端返回 null）
- WACC 不是独立输入，是从 risk_free_rate + beta + ERP + cost_of_debt + debt_ratio 实时计算的显示值

### 5.3 数据来源与 Warning 展示

**设计原则：** 用户必须能判断每个数字的可信度。

- 每个数据字段旁边显示来源标签：`yfinance` / `fmp` / `finnhub` / `derived`
- 如果字段是推导出来的（如 shares_outstanding = market_cap / price），标签改为 `derived` 并附 tooltip 说明推导公式
- 如果数据来自过期缓存，显示缓存时间："Cached 2h ago"
- `warnings` 数组中的每一条在 Data Panel 顶部以黄色 banner 展示
- DCF 计算的 `fcf_formula_warning`（"Simplified FCF formula used"）在 Valuation Card 中显示

---

## 6. Implementation Phases

### Phase 1: Protocol Layer（预计 2-3 周）

**后端改动（FinAgent 仓库）：**
1. 新增 `finagent/secret_store.py` — SecretStore ABC + KeychainSecretStore + FileSecretStore
2. 新增 `finagent/run_store.py` — SQLite RunStore（runs/events/artifacts CRUD）
3. 新增 `finagent/events.py` — SSE 事件 TypedDict 定义
4. 新增 `finagent/routes/compute.py` — 6 个 compute 端点，直接调用 `compute/` 层纯函数
5. 新增 `finagent/routes/data.py` — 2 个 data 端点，封装 DataLayer
6. 新增 `finagent/routes/settings.py` — GET/PUT settings 端点，集成 SecretStore
7. 新增 `finagent/routes/runs.py` — POST/GET runs + SSE with replay buffer from RunStore
8. 修改 `server.py` — 挂载新 router，初始化 SecretStore + RunStore，保留 `/health`
9. 生成 OpenAPI schema JSON — 桌面端从此 schema 生成 TypeScript 类型

**验收标准：**
- `curl POST /api/compute/dcf` 能返回正确结果
- `curl GET /api/data/AAPL/financials` 能返回结构化数据
- `curl PUT /api/settings` 能更新配置（key 进 keychain，非敏感进 json）且后续请求生效
- `curl POST /api/runs` + `curl GET /api/runs/{id}/events` 能收到完整 SSE 流
- SSE 断线后 `Last-Event-ID` 能补发遗漏事件
- 服务重启后 `GET /api/runs` 仍返回历史 runs
- `GET /openapi.json` 返回完整 schema

### Phase 2: Desktop Rewrite（预计 3-4 周）

**桌面端改动（desktop/ 目录）：**
1. 从 OpenAPI schema 生成 TypeScript 类型（openapi-typescript）+ API client（openapi-fetch）
2. 重写 Settings View — 调用 `/api/settings`，首次启动引导流程
3. 实现 Ticker Workspace — 输入 ticker → 拉数据 → 展示
4. 实现 Pipeline Runner — `POST /api/runs` + SSE 进度显示
5. 实现 Assumptions Editor — slider 组件 + debounce
6. 实现 Compute Loop — slider 变化 → `/api/compute/dcf` → 更新图表
7. 复用/修复现有 chart 组件 — SensitivityHeatmap, FootballField, WaterfallChart, etc.
8. 实现 Report Preview — 内嵌 HTML 报告
9. 实现 Export — Excel/PDF/HTML 下载
10. 修复 electron-builder 打包 — 加入 skills/、确保 Python sidecar 可启动

**验收标准：**
从空安装开始：
- [ ] 首次启动 → Settings → 填 API key → 保存 → 后端生效
- [ ] 输入 AAPL → 看到财务数据 + 来源标签 + warnings
- [ ] 点击 "Run DCF" → 看到 SSE 进度条 → 45 秒内完成
- [ ] 看到 implied price + sensitivity heatmap + waterfall + FCF chart
- [ ] 拖 WACC slider → 所有图表 <200ms 内更新
- [ ] 导出 Excel → 打开验证数字一致
- [ ] 导出 PDF → 打开验证报告完整
- [ ] 数据缺失时 → 看到明确 warning，不是空白或 0

### Phase 3: Polish & Expand（Phase 2 完成后再规划）

优先级排序（待定）：
1. LBO workspace（复用 compute/lbo.py，同样模式）
2. Comps workspace
3. Run history + version 对比
4. 10-K Q&A（RAG）
5. Earnings review
6. IC memo builder

---

## 7. Technical Constraints

### 7.1 已确认可直接使用的后端资产

| 资产 | 文件 | 状态 |
|---|---|---|
| DCF 纯计算 | `compute/dcf.py` | 纯函数，零改动可暴露为 API |
| WACC 纯计算 | `compute/wacc.py` | 纯函数 |
| LBO 纯计算 | `compute/lbo.py` | 纯函数 |
| Multiples 纯计算 | `compute/multiples.py` | 纯函数 |
| Sensitivity 计算 | `compute/dcf.py:calculate_sensitivity` | 纯函数 |
| DCFInputs/DCFResult 模型 | `models/financial.py:139-218` | Pydantic，带完整验证 |
| LBOInputs/LBOResult 模型 | `models/financial.py:360-419` | Pydantic，带完整验证 |
| FinancialData 模型 | `models/financial.py:52-71` | 已拆为 4 子模型，结构清晰 |
| DataLayer + Provider chain | `data/layer.py` | 可直接封装为 HTTP 端点 |
| FinAgentSettings | `config.py:18-55` | Pydantic BaseSettings，可序列化 |
| HTML/PDF/Excel 报告 | `engine/reports/` | 已有 |
| 18 种图表组件 | `desktop/src/charts/` | 已有但未连通数据 |

### 7.2 需要新建的后端代码

见 §12 更新后的估算。总计 ~760 行，包含 SecretStore + SQLite RunStore。

### 7.3 打包修复清单

| 问题 | 修复 |
|---|---|
| `skills/` 未打包 | electron-builder extraResources 加入 `skills/` |
| Python sidecar 启动不确定 | 加健康检查轮询：桌面启动后 poll `/health` 直到 200 |
| 首次安装无 `.env` | Settings 引导流程替代，不依赖 .env |

---

## 8. 不变量（Invariants）

以下是实现过程中不可违反的约束：

1. **Compute 端点永不调用 LLM。** 如果有人在 compute route 里 import agent 或 LLM，这是 bug。
2. **Data 端点永不调用 LLM。** 数据来自 provider chain，不来自 LLM 推理。
3. **所有 compute 端点是幂等的。** 相同输入必须返回相同输出。
4. **桌面端的类型定义从 OpenAPI schema 生成。** 不手写 TypeScript 接口。
5. **任何数据缺失必须有用户可见的 warning。** 不能用默认值静默替代。
6. **API keys 永不以明文出现在 GET 响应、日志、或前端 state 中。** 业务代码只通过 `SecretStore` 接口访问。
7. **SSE 事件格式以 §4 定义为准。** 前后端不各自发明格式。SSE frame 必须带 `id:` 字段支持断线重连。
8. **Run 数据持久化到 SQLite。** 不用内存 dict。服务重启后 runs 仍可查询。
9. **Server 绑定 127.0.0.1。** V1 是 local-only 产品。远程访问是 V3+ 话题。

---

## 9. Technical Decisions（已拍板，不再讨论）

> 原则：V1 可以少功能，但底座不能是一次性的。已知 V2 一定要改的东西，现在就做对。

| 问题 | 决策 | 理由 |
|---|---|---|
| **API key 存储** | OS keychain（macOS Keychain / Windows Credential Manager） | 桌面产品会存真钱数据源和 LLM key，明文文件迟早过不了安全审查。现在做对。 |
| **非敏感配置** | `~/.finagent/settings.json`（0600 权限） | model_name、sec_user_agent、log_level 等不敏感，文件存储足够。 |
| **Run 结果持久化** | SQLite（`~/.finagent/runs.db`） | Runs 模型已设计为可查询/可重连/可追溯。内存 dict 是假实现，断线/重启/crash 后全没。生产级说不过去。 |
| **OpenAPI client** | openapi-typescript + openapi-fetch | 轻、类型干净、不生成难维护代码。长期方案。 |
| **Sensitivity grid** | 默认 7x7，UI 固定不给用户配置 | 兼顾信息量和计算速度。未来要配置再加。 |
| **前端状态管理** | Zustand + React Query | Zustand 管本地 UI/草稿/workspace 状态，React Query 管 server state/cache。分离关注点。 |

---

## 10. Security（安全章节）

### 10.1 SecretStore 抽象

所有业务代码通过 `SecretStore` 接口访问 API keys，不直接接触存储机制。

```python
from abc import ABC, abstractmethod

class SecretStore(ABC):
    """Abstract secret storage. Business code calls this, never touches storage directly."""
    
    @abstractmethod
    async def get(self, key: str) -> str | None:
        """Retrieve a secret by key. Returns None if not set."""
    
    @abstractmethod
    async def set(self, key: str, value: str) -> None:
        """Store a secret."""
    
    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove a secret."""
    
    @abstractmethod
    async def has(self, key: str) -> bool:
        """Check if a secret exists without retrieving it."""
```

**两个实现：**

| 实现 | 用途 | 启用条件 |
|---|---|---|
| `KeychainSecretStore` | 生产桌面运行 | 默认，检测到 keyring 可用时使用 |
| `FileSecretStore` | 开发/CI/测试 | 显式 `FINAGENT_DEV_MODE=1` 或 keyring 不可用时 fallback |

`FileSecretStore` 规则：
- 文件路径 `~/.finagent/.secrets`（注意：不是 `settings.json`）
- 文件权限 `0600`（仅当前用户可读写）
- 启动时检查权限，不合格则拒绝启动并报错
- 日志中永不出现 secret 值，只出现 `***SET***` 或 `***EMPTY***`

### 10.2 安全不变量

1. **GET /api/settings 永不返回 API key 明文。** 只返回 `*_key_set: bool`。
2. **日志脱敏。** 任何 logging 输出中，API key 替换为 `***`。Config 的 `__repr__` 必须脱敏。
3. **前端不长期存储 key 原文。** Settings 页面填写后立即 PUT 到后端，前端不在 Zustand/localStorage 中保存。
4. **本 V1 为 local-only 产品。** Server 绑定 `127.0.0.1`，不接受远程连接。这是安全边界的前提。
5. **SECURITY.md 必须声明：** API keys 存储在 OS keychain（默认）或本地加密文件（dev mode），不上传、不同步、不明文日志。

---

## 11. Runs 持久化 Schema

SQLite 数据库 `~/.finagent/runs.db`，三张表。

### 11.1 runs 表

```sql
CREATE TABLE runs (
    run_id       TEXT PRIMARY KEY,
    pipeline_type TEXT NOT NULL,
    ticker       TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('created', 'running', 'completed', 'failed')),
    created_at   TEXT NOT NULL,  -- ISO 8601
    completed_at TEXT,           -- ISO 8601, NULL if not finished
    duration_s   REAL,
    result_text  TEXT,           -- narrative summary
    result_json  TEXT,           -- structured result (DCFResult etc.) as JSON
    error        TEXT            -- error message if failed
);

CREATE INDEX idx_runs_ticker ON runs(ticker);
CREATE INDEX idx_runs_created ON runs(created_at DESC);
```

### 11.2 run_events 表（replay buffer）

```sql
CREATE TABLE run_events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id   TEXT NOT NULL REFERENCES runs(run_id),
    seq      INTEGER NOT NULL,  -- event sequence number within run
    event    TEXT NOT NULL,      -- JSON payload (RunEvent)
    created_at TEXT NOT NULL     -- ISO 8601
);

CREATE INDEX idx_events_run ON run_events(run_id, seq);
```

**用途：** SSE 断线重连时，客户端传 `Last-Event-ID: {seq}`，服务端从 `run_events` 补发 seq 之后的事件。

### 11.3 artifacts 表

```sql
CREATE TABLE artifacts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL REFERENCES runs(run_id),
    artifact_type TEXT NOT NULL,  -- 'dcf_result', 'lbo_result', 'report_html', 'report_pdf', 'excel'
    format        TEXT NOT NULL,  -- 'json', 'html', 'pdf', 'xlsx'
    data          BLOB,           -- actual content (small artifacts inline)
    file_path     TEXT,           -- path to file (large artifacts on disk)
    created_at    TEXT NOT NULL
);

CREATE INDEX idx_artifacts_run ON artifacts(run_id);
```

### 11.4 SSE 断线重连

SSE frame 增加 `id:` 字段：

```
id: 3
event: step.completed
data: {"event":"step.completed","run_id":"run_abc","step":2,"total":4,"name":"Analysis","duration_s":12.1}
```

客户端 `EventSource` 断线后自动携带 `Last-Event-ID: 3`，服务端查 `run_events WHERE run_id = ? AND seq > 3` 补发。

### 11.5 实现约束

- V1 桌面 UI 不做 history 页面，但 `GET /api/runs` 技术上可用。
- SQLite WAL 模式 + `asyncio.Lock`，延续现有 cache.py 的并发模式。
- `runs.db` 和 `cache.db` 分开，职责不同。
- Run 数据不设自动清理。V2 加 retention policy。

---

## 12. Updated Implementation Estimates

Phase 1 后端新增代码量因 SQLite + SecretStore 有所增加：

| 代码 | 估计行数 | 说明 |
|---|---|---|
| `routes/compute.py` | ~80 行 | 6 个 compute 端点 |
| `routes/data.py` | ~60 行 | 2 个 data 端点 |
| `routes/settings.py` | ~120 行 | GET/PUT + SecretStore 集成 + provider 重初始化 |
| `routes/runs.py` | ~180 行 | POST/GET + SSE with replay buffer |
| `events.py` | ~50 行 | SSE 事件 TypedDict |
| `secret_store.py` | ~120 行 | ABC + KeychainSecretStore + FileSecretStore |
| `run_store.py` | ~150 行 | SQLite runs/events/artifacts CRUD |

**总计后端新增：~760 行。** 比原估 400 行多 ~360 行，换来的是：不用 V2 迁移存储层。值得。
