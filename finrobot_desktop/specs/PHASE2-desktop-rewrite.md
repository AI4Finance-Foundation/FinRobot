# Phase 2: Desktop Rewrite — Implementation Requirements

> **Status**: Ready for implementation
> **Prerequisite**: Phase 1 protocol layer complete. 24 audit issues found → all fixed → all verified → 930 tests, 0 failures.
> **Spec reference**: `SPEC-desktop-v1.md` (all decisions locked)
> **Scope**: Rewrite desktop frontend to use Phase 1 API. Backend changes: 1 new POST export endpoint.

---

## 0. Executive Summary

Desktop 当前状态：前后端完全断开。路由不匹配、SSE 格式不兼容、Settings 不同步、打包遗漏 skills/。

Phase 2 目标：基于 Phase 1 的 API 协议层，重写桌面前端，实现一个完整可用的 **交互式 DCF 工作流**。

**保留的资产：**
- 9 个 chart 组件（`desktop/src/components/charts/`，1125 行）— 自包含 Recharts 组件，数据接口干净
- `Layout.tsx`（44 行）— 双栏布局
- `ErrorBoundary.tsx`（65 行）
- `electron/main.ts`（192 行）— Python server 启动器，架构正确
- Tailwind + dark theme

**重写的部分：**
- `App.tsx` — 新视图结构
- `usePipelineStream.ts` — 新 SSE 协议
- `appStore.ts` — Zustand + React Query
- `SettingsView.tsx` — 同步到后端
- `ResearchView.tsx` / `DCFView.tsx` / `CompsView.tsx` — 合并为 Ticker Workspace
- `DataPanel.tsx` — 接真实数据
- `ReportActions.tsx` — 新端点 URL

**新建的部分：**
- OpenAPI 类型生成 + API client
- React Query provider
- Ticker Workspace 视图
- Assumptions Editor（滑块组件）
- Pipeline Runner 组件

---

## 1. 开发环境搭建

### 1.1 安装 openapi-typescript + openapi-fetch

```bash
cd desktop
npm install openapi-fetch @tanstack/react-query use-debounce
npm install -D openapi-typescript
```

### 1.2 类型生成脚本

在 `desktop/package.json` 的 `scripts` 中添加：

```json
{
  "generate:api": "npx openapi-typescript http://127.0.0.1:8000/openapi.json -o src/api/schema.d.ts"
}
```

**首次运行前**，需要先启动后端：
```bash
cd .. && uv run finagent serve &
cd desktop && npm run generate:api
```

生成的 `src/api/schema.d.ts` 应提交到 git（CI 中可能无法启动后端来生成）。

### 1.3 API Client 创建

新建 `desktop/src/api/client.ts`：

```typescript
import createClient from "openapi-fetch";
import type { paths } from "./schema";

const BASE_URL = "http://127.0.0.1:8000";

export const api = createClient<paths>({ baseUrl: BASE_URL });

export { BASE_URL };
```

### 1.4 React Query 配置

新建 `desktop/src/api/queryClient.ts`：

```typescript
import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,   // 5 min（与后端 cache 对齐）
      retry: 1,
      refetchOnWindowFocus: false, // 本地应用不需要
    },
  },
});
```

依赖已在 §1.1 统一安装（`@tanstack/react-query`、`use-debounce`）。

---

## 2. 文件变更清单

### 2.1 保留不动的文件

| 文件 | 原因 |
|---|---|
| `src/components/charts/*.tsx` (9 个) | 自包含 Recharts 组件，数据接口不变 |
| `src/components/charts/index.ts` | 导出聚合 |
| `src/components/ErrorBoundary.tsx` | 通用错误边界 |
| `electron/preload.ts` | 最小 preload |
| `electron.vite.config.ts` | 构建配置不变 |
| `tsconfig*.json` | 不变 |

### 2.2 需要修改的文件

| 文件 | 改动 |
|---|---|
| `src/App.tsx` | 重写：新视图结构（Settings + Workspace），加 QueryClientProvider |
| `src/App.css` | 补充 workspace 相关样式 |
| `src/main.tsx` | 无变化或极小调整 |
| `src/stores/appStore.ts` | 重构：去掉 settings 中的 API keys（移到后端），只保留 UI 状态 |
| `src/components/Layout.tsx` | 小改：适配 workspace 布局 |
| `src/components/DataPanel.tsx` | 重写：从 `/api/data/{ticker}/financials` 拉真实数据 |
| `src/components/ReportActions.tsx` | 小改：URL 更新到新端点 |
| `electron/main.ts` | 小改：打包路径修复 |
| `package.json` | 加依赖 + generate:api 脚本 + extraResources 加 skills/ |

### 2.3 需要删除的文件

| 文件 | 原因 |
|---|---|
| `src/hooks/usePipelineStream.ts` | 完全重写为新协议，新文件替代 |
| `src/components/ResearchView.tsx` | 合并进 Workspace |
| `src/components/DCFView.tsx` | 合并进 Workspace |
| `src/components/CompsView.tsx` | 合并进 Workspace |
| `src/components/SettingsView.tsx` | 完全重写 |

### 2.4 需要新建的文件

| 文件 | 说明 |
|---|---|
| `src/api/schema.d.ts` | openapi-typescript 生成（不手写） |
| `src/api/client.ts` | openapi-fetch client |
| `src/api/queryClient.ts` | React Query 配置 |
| `src/hooks/useRunStream.ts` | 新 SSE hook（Runs 协议） |
| `src/hooks/useCompute.ts` | compute API 调用 hook |
| `src/views/SettingsView.tsx` | 新 Settings 视图（同步到后端） |
| `src/views/TickerWorkspace.tsx` | 核心 workspace 视图 |
| `src/components/TickerInput.tsx` | ticker 输入 + 数据加载触发 |
| `src/components/FinancialsPanel.tsx` | 公司基本面展示（替代旧 DataPanel） |
| `src/components/PipelineRunner.tsx` | pipeline 运行 + 进度展示 |
| `src/components/AssumptionsEditor.tsx` | DCF 假设滑块编辑器 |
| `src/components/ValuationCard.tsx` | implied price + upside/downside |
| `src/components/ExportBar.tsx` | Excel/PDF/HTML 导出 |
| `src/components/WarningBanner.tsx` | 数据 warning 展示 |
| `src/utils/chartAdapters.ts` | 后端数据 → chart props 转换函数 |
| **后端** `finagent/routes/export.py` | POST /api/export/excel/dcf（交互式导出） |

---

## 3. 组件设计

### 3.1 App.tsx — 顶层结构

```
<QueryClientProvider client={queryClient}>
  <App>
    ├── if (!settingsReady) → <SettingsView onComplete={markReady} />
    └── if (settingsReady) → <TickerWorkspace />
  </App>
</QueryClientProvider>
```

**逻辑：**
- 启动时 `GET /api/settings` 检查配置状态
- Settings ready 条件：**当前 `model_name` 对应 provider 的 key 已设置**
  - 例如 `model_name = "deepseek:deepseek-chat"` → 需要 `deepseek_api_key_set = true`
  - 例如 `model_name = "anthropic:claude-sonnet-4-6"` → 需要 `anthropic_api_key_set = true`
  - `model_name = "test:..."` → 无需 key
- Provider 从 `model_name` 的 `:` 前缀提取：`const provider = settings.model_name.split(":")[0]`
- 对应 key 字段：`${provider}_api_key_set`（deepseek/anthropic/openai）
- 如果不满足 → 强制进 Settings 引导，提示 "Please configure an API key for {provider}"
- 满足 → 直接进 Workspace

**不再用 tab 导航。** V1 只有一个视图：Ticker Workspace。Settings 只在首次启动或用户主动点击时出现。

### 3.2 SettingsView.tsx — 配置页

**数据源：** `GET /api/settings` + `PUT /api/settings`

**UI 结构：**
```
Settings
├── LLM Provider
│   ├── Model 选择 dropdown（deepseek:deepseek-chat / anthropic:claude-sonnet-4-6 / openai:gpt-4o）
│   └── 对应 API Key 输入（password field）
├── Data Providers (optional)
│   ├── FMP API Key
│   ├── Finnhub API Key
│   └── SEC User-Agent
├── Status 面板
│   ├── "Available providers: yfinance, fmp, ..."（从 GET 响应读）
│   └── 配置验证状态（PUT 后 validate_runtime_config 的结果）
└── Save 按钮
```

**行为：**
- 用户填写 → 点 Save → `PUT /api/settings`
- 后端验证通过 → 返回更新后状态 → 前端显示 "Saved"
- 后端验证失败（400）→ 显示错误信息（如 "Unknown provider 'xxx'"）
- Save 成功后，前端**不保存 key 原文**。只保存 `*_key_set: bool` 用于 UI 显示
- Settings 页面的 key 输入框每次打开都是空的（placeholder 显示 "Configured" 或 "Not set"）

**React Query：**
```typescript
// 读取设置
const { data: settings } = useQuery({
  queryKey: ["settings"],
  queryFn: () => api.GET("/api/settings"),
});

// 更新设置
const mutation = useMutation({
  mutationFn: (body) => api.PUT("/api/settings", { body }),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ["settings"] }),
});
```

### 3.3 TickerWorkspace.tsx — 核心视图

这是 V1 唯一的工作视图。

**UI 结构：**
```
TickerWorkspace
├── Header
│   ├── TickerInput（输入框 + "Load" 按钮）
│   ├── Settings 齿轮图标（打开 SettingsView）
│   └── 当前 ticker 标题（如 "AAPL — Apple Inc."）
├── Main Content（垂直滚动）
│   ├── WarningBanner（数据 warnings，黄色）
│   ├── FinancialsPanel（公司基本面数据）
│   ├── PipelineRunner（"Run DCF Analysis" 按钮 + 进度条）
│   ├── [DCF 结果区域]（pipeline 完成后显示）
│   │   ├── ValuationCard（implied price, EV, upside/downside）
│   │   ├── AssumptionsEditor（滑块组件）
│   │   ├── SensitivityHeatmap（7x7）
│   │   ├── WaterfallChart（DCF bridge）
│   │   └── FCF Projection（RevenueEbitdaChart 复用）
│   └── ExportBar（Excel / PDF / HTML）
└── Footer（数据来源 + 时间戳）
```

**状态流转：**
```
IDLE → LOADING_DATA → DATA_READY → RUNNING_PIPELINE → PIPELINE_DONE → INTERACTIVE
                                                                        ↕
                                                              (用户调假设，循环)
```

**Zustand store 结构：**
```typescript
interface WorkspaceState {
  // UI state
  ticker: string;
  phase: "idle" | "loading_data" | "data_ready" | "running_pipeline" | "pipeline_done" | "interactive";

  // DCF state（pipeline 完成后填充，用户调整时更新）
  dcfInputs: DCFInputs | null;       // 当前假设（初始来自 pipeline，用户可修改）
  dcfResult: DCFResult | null;       // 当前计算结果
  sensitivityData: SensitivityResult | null;

  // Actions
  setTicker: (t: string) => void;
  setPhase: (p: Phase) => void;
  setDcfInputs: (inputs: DCFInputs) => void;
  setDcfResult: (result: DCFResult) => void;
  setSensitivityData: (data: SensitivityResult) => void;
  reset: () => void;
}
```

### 3.4 TickerInput.tsx

```
[  AAPL  ] [Load Data]
```

- 输入 ticker → 点击 Load（或回车）
- 触发 `GET /api/data/{ticker}/financials` 和 `GET /api/data/{ticker}/price`
- 加载中显示 spinner
- 成功 → phase 切到 `data_ready`，FinancialsPanel 渲染数据
- 失败（404）→ 显示 "Ticker not found" 错误

**React Query：**
```typescript
const financials = useQuery({
  queryKey: ["financials", ticker],
  queryFn: () => api.GET("/api/data/{ticker}/financials", { params: { path: { ticker } } }),
  enabled: !!ticker && phase !== "idle",
});
```

### 3.5 FinancialsPanel.tsx

替代旧的 `DataPanel.tsx`。显示从 `/api/data/{ticker}/financials` 返回的 `FinancialData`。

**UI 结构：**
```
Company Fundamentals                    [yfinance]  ← 数据来源标签
┌─────────────────────────────────────────────────┐
│ Revenue        $385.6B                          │
│ EBITDA         $134.0B    Margin: 34.7%         │
│ Net Income     $97.0B     Margin: 25.2%         │
│ Gross Margin   46.2%                            │
│ Operating Margin 30.2%                          │
├─────────────────────────────────────────────────┤
│ Market Cap     $3,200B                          │
│ Current Price  $207.79                          │
│ P/E Ratio      33.0x                            │
│ 52W Range      $169.21 — $260.10                │
├─────────────────────────────────────────────────┤
│ Total Debt     $108.0B                          │
│ Total Cash     $30.0B                           │
│ EV             $3,278B                          │
│ EV/EBITDA      24.5x                            │
│ EV/Revenue     8.5x                             │
└─────────────────────────────────────────────────┘
```

**数据映射：**
- `data.income.revenue` → Revenue
- `data.income.ebitda` → EBITDA
- `data.market.market_cap` → Market Cap
- `data.balance.total_debt` → Total Debt
- `data.valuation.ev_ebitda` → EV/EBITDA
- 等等，直接映射 FinancialData 的子模型字段

**数据来源标签：** 右上角显示 `data.data_source`

**null 处理：** 字段为 null 时显示 "—"（em dash），不显示 0

### 3.6 WarningBanner.tsx

显示 `FinancialData.warnings` 数组。

```
⚠ shares_outstanding missing from yfinance; derived as market_cap / current_price
⚠ D&A not available; simplified FCF formula will be used
```

- 黄色背景，每条 warning 一行
- 空数组时不渲染
- 可折叠（多于 3 条时默认折叠，显示 "3 warnings" + 展开按钮）

### 3.7 PipelineRunner.tsx

**UI 状态机：**

```
[未运行]
  → "Run DCF Analysis" 按钮（蓝色，prominent）
  → 点击 → POST /api/runs { pipeline_type: "dcf", ticker }
  → 获得 run_id

[运行中]
  → GET /api/runs/{run_id}/events (SSE)
  → 进度条 + 步骤列表：
    ✓ Financial Data Extraction (3.2s)
    ● Peer Analysis...
    ○ Financial Modeling
    ○ Report Generation
  → 步骤名称和数量从 SSE step.started/step.completed 事件获取

[完成]
  → 进度条满
  → GET /api/runs/{run_id} 获取完整结果
  → DCFResult 的精确路径：response.result.structured["dcf_calc"]
    （key 是 pipeline step name，定义在 pipelines/dcf.py:88）
  → **后端修复要求（见 §4.4）**：当前 get_run() 返回的是
    result.structured = {"structured_data": {"dcf_calc": ...}, "warnings": [...]}
    需要展平为 result.structured = {"dcf_calc": ...}（warnings 已提升到顶层）
  → DCFInputs 从 DCFResult.inputs 字段获取（DCFResult 内嵌了它的输入）
  → 将 DCFInputs 写入 store.dcfInputs 和 store.originalDcfInputs
  → 将 DCFResult 写入 store.dcfResult
  → phase 切到 pipeline_done → interactive

[失败]
  → 显示错误信息（从 run.failed 事件获取）
  → "Retry" 按钮
```

### 3.8 useRunStream.ts — SSE Hook

替代旧的 `usePipelineStream.ts`。

```typescript
import { BASE_URL } from "../api/client";

interface RunStep {
  name: string;
  status: "pending" | "running" | "completed" | "retrying";
  duration_s?: number;
}

interface UseRunStreamReturn {
  steps: RunStep[];
  status: "idle" | "running" | "completed" | "failed";
  error: string | null;
  progress: number;         // 0-1
  startRun: (pipelineType: string, ticker: string) => Promise<string>;  // returns run_id
}

export function useRunStream(): UseRunStreamReturn {
  // 实现要点：
  // 1. startRun: POST /api/runs → 获得 run_id
  // 2. 创建 EventSource(`${BASE_URL}/api/runs/${runId}/events`)
  // 3. 解析 SSE 事件（event: 字段路由，data: 字段解析 JSON）
  // 4. run.started → 初始化 steps 数组（total_steps 个 pending）
  // 5. step.started → 对应 step 设为 running
  // 6. step.completed → 对应 step 设为 completed，记录 duration_s
  // 7. step.retry → 对应 step 设为 retrying
  // 8. run.completed → status = completed，关闭 EventSource
  // 9. run.failed → status = failed，记录 error，关闭 EventSource
  // 10. 断线重连：EventSource 原生支持，后端通过 Last-Event-ID + replay buffer 补发
  // 11. 组件卸载时关闭 EventSource
}
```

### 3.9 AssumptionsEditor.tsx — 杀手级组件

**这是整个桌面端存在的理由。**

**UI 结构：**
```
DCF Assumptions                              [Reset to AI defaults]
┌──────────────────────────────────────────────────────────┐
│ WACC Components                                          │
│   Risk-Free Rate     [====●========] 4.3%                │
│   Beta               [====●========] 1.24                │
│   Equity Risk Prem.  [====●========] 5.5%                │
│   Cost of Debt       [====●========] 3.5%                │
│   Debt Ratio         [====●========] 15%                 │
│   → WACC (calculated)               9.87%                │
│                                                          │
│ Growth & Margins                                         │
│   EBITDA Margin      [====●========] 35.0%               │
│   Terminal Growth    [====●========] 2.5%                 │
│   Tax Rate           [====●========] 21%                 │
│   Capex % Revenue    [====●========] 4.0%                │
│   NWC % Revenue      [====●========] 2.0%                │
│                                                          │
│ Revenue Growth Rates (per year)                          │
│   Year 1: [5.0%]  Year 2: [5.0%]  Year 3: [4.0%]       │
│   Year 4: [4.0%]  Year 5: [3.0%]                        │
└──────────────────────────────────────────────────────────┘
```

**Slider 范围（直接来自 DCFInputs Pydantic 验证规则）：**

| 参数 | min | max | step | 显示格式 |
|---|---|---|---|---|
| risk_free_rate | 0 | 0.15 | 0.001 | 百分比 (4.3%) |
| beta | 0 | 5 | 0.01 | 小数 (1.24) |
| equity_risk_premium | 0 | 0.15 | 0.001 | 百分比 |
| cost_of_debt | 0 | 0.20 | 0.001 | 百分比 |
| debt_ratio | 0 | 1 | 0.01 | 百分比 |
| ebitda_margin | 0 | 1 | 0.005 | 百分比 |
| terminal_growth_rate | 0 | 0.05 | 0.001 | 百分比 |
| tax_rate | 0 | 1 | 0.01 | 百分比 |
| capex_pct_revenue | 0 | 1 | 0.005 | 百分比 |
| nwc_pct_revenue | -0.20 | 0.50 | 0.005 | 百分比 |

**WACC 显示：** 不是用户输入，是从 risk_free_rate + beta + ERP + cost_of_debt + debt_ratio 实时计算的只读值。每次任一组件变化 → 调 `POST /api/compute/wacc` → 更新显示。

**交互行为：**
1. 用户拖动任何 slider
2. debounce 100ms
3. 构造新的 `DCFInputs`（从当前 store 读，覆盖被修改的字段）
4. 并行调用：
   - `POST /api/compute/dcf` → 更新 ValuationCard + WaterfallChart
   - `POST /api/compute/dcf-sensitivity` → 更新 SensitivityHeatmap
5. 响应 <100ms，图表即时更新

**"Reset to AI defaults" 按钮：** 将所有 slider 重置为 pipeline 最初返回的 DCFInputs 值。Store 中需保存一份 `originalDcfInputs`。

### 3.10 useCompute.ts — Compute Hook

```typescript
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";

export function useDcfCompute() {
  return useMutation({
    mutationFn: (inputs: DCFInputs) =>
      api.POST("/api/compute/dcf", { body: inputs }),
  });
}

export function useDcfSensitivity() {
  return useMutation({
    mutationFn: (req: { inputs: DCFInputs; wacc_range: number[]; tg_range: number[] }) =>
      api.POST("/api/compute/dcf-sensitivity", { body: req }),
  });
}

export function useWaccCompute() {
  return useMutation({
    mutationFn: (params: WaccParams) =>
      api.POST("/api/compute/wacc", { body: params }),
  });
}
```

**注意：** 用 `useMutation` 而非 `useQuery`，因为 compute 是用户触发的命令式调用，不是声明式数据获取。

### 3.11 ValuationCard.tsx

```
┌─────────────────────────────────┐
│  Implied Share Price            │
│  $68.61                         │
│  ▼ -67.0% vs current ($207.79) │
│                                 │
│  Enterprise Value  $1,134.7B    │
│  Equity Value      $1,056.7B    │
│  WACC              9.87%        │
│  Terminal Value     $1,234.6B   │
│  PV of FCF         $345.7B     │
│                                 │
│  ⚠ Simplified FCF formula used │
└─────────────────────────────────┘
```

- `fcf_formula_warning` 非 null 时底部显示黄色 warning
- upside/downside = `(implied_price - current_price) / current_price`
- current_price 从 FinancialsPanel 的数据获取

### 3.12 ExportBar.tsx

```
[Export Excel (Current Model)]  [View AI Report (HTML)]  [Download AI Report (PDF)]
```

**Excel 导出（反映当前交互假设）：**
- `POST /api/export/excel/dcf` body = 当前 `DCFInputs` + `DCFResult`
- 后端用收到的数据生成 .xlsx，不从 pipeline cache 读
- 用户调完 slider → 导出 → Excel 中的数字和界面一致
- **这需要后端新增一个 POST 端点**（见 §4.3）

**HTML/PDF 报告（反映 AI 原始分析）：**
- HTML: `GET /api/report/html?ticker={ticker}` → 新窗口预览
- PDF: `GET /api/report/pdf?ticker={ticker}` → 下载 .pdf
- 这两个始终反映 pipeline 原始输出（含 LLM 叙述），**不随 slider 调整更新**
- 按钮文案必须标明 "AI Report"，避免用户误以为是当前调整后的模型

只在 pipeline 完成后显示。

### 3.13 SensitivityHeatmap 数据适配

现有 `SensitivityHeatmap.tsx` 接受 `data: Array<{wacc, tg, implied_price}>`（flat array）。

新的后端返回 `DcfSensitivityResult`：
```json
{
  "wacc_values": [0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14],
  "tg_values": [0.01, 0.015, 0.02, 0.025, 0.03, 0.035, 0.04],
  "implied_prices": [[95.2, 102.3, ...], ...]
}
```

**策略：写 adapter 函数，不改 chart 组件内部。**

新建 `src/utils/chartAdapters.ts`：
```typescript
export function sensitivityGridToHeatmapRows(
  result: DcfSensitivityResult
): Array<{ wacc: number; tg: number; implied_price: number | null }> {
  const rows = [];
  for (let i = 0; i < result.wacc_values.length; i++) {
    for (let j = 0; j < result.tg_values.length; j++) {
      rows.push({
        wacc: result.wacc_values[i],
        tg: result.tg_values[j],
        implied_price: result.implied_prices[i][j],
      });
    }
  }
  return rows;
}
```

这样 SensitivityHeatmap 组件接口不变，现有测试不受影响。其他 chart 如果需要数据转换也放在同一个文件。

---

## 4. 数据流

### 4.1 完整用户旅程

```
┌─────────────────────────────────────────────────────────────────────┐
│ Step 1: 输入 Ticker                                                 │
│                                                                     │
│ User types "AAPL" → clicks "Load Data"                              │
│   → GET /api/data/AAPL/financials                                   │
│   → GET /api/data/AAPL/price                                        │
│   → FinancialsPanel renders company data                            │
│   → WarningBanner shows any data warnings                           │
│   → Phase: idle → loading_data → data_ready                        │
├─────────────────────────────────────────────────────────────────────┤
│ Step 2: Run DCF Pipeline (LLM involved, 30-60s)                    │
│                                                                     │
│ User clicks "Run DCF Analysis"                                      │
│   → POST /api/runs { pipeline_type: "dcf", ticker: "AAPL" }        │
│   → GET /api/runs/{run_id}/events (SSE)                             │
│   → PipelineRunner shows progress bar + step list                   │
│   → On run.completed:                                               │
│       → GET /api/runs/{run_id}                                      │
│       → DCFResult = response.result.structured["dcf_calc"]          │
│       → DCFInputs = DCFResult.inputs                                │
│       → Store as originalDcfInputs + dcfInputs + dcfResult          │
│       → POST /api/compute/dcf-sensitivity (generate 7x7 grid)      │
│       → Render: ValuationCard + AssumptionsEditor + charts          │
│   → Phase: data_ready → running_pipeline → pipeline_done            │
├─────────────────────────────────────────────────────────────────────┤
│ Step 3: Interactive Adjustment (no LLM, <100ms per change)          │
│                                                                     │
│ User drags WACC beta slider from 1.24 to 1.50                      │
│   → debounce 100ms                                                  │
│   → POST /api/compute/wacc { ...updated params }                   │
│   → Update WACC display                                             │
│   → POST /api/compute/dcf { ...updated DCFInputs }                 │
│   → POST /api/compute/dcf-sensitivity { ...updated, 7x7 ranges }  │
│   → ValuationCard updates implied price                             │
│   → SensitivityHeatmap redraws                                      │
│   → WaterfallChart redraws                                          │
│   → Phase: interactive (stays here, loops on every adjustment)      │
├─────────────────────────────────────────────────────────────────────┤
│ Step 4: Export                                                      │
│                                                                     │
│ User clicks "Export Excel (Current Model)"                          │
│   → POST /api/export/excel/dcf                                      │
│     body = { ticker, inputs: current DCFInputs, result: DCFResult } │
│   → Browser downloads .xlsx file                                    │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 State 分工

| 数据 | 管理者 | 原因 |
|---|---|---|
| Settings（是否有 key） | React Query | 来自 server，需 cache + invalidation |
| Financials data | React Query | 来自 server，5 min stale |
| Price data | React Query | 来自 server |
| DCFInputs（当前假设） | Zustand | 用户频繁修改，需即时响应 |
| DCFResult（当前结果） | Zustand | 跟随 DCFInputs 变化 |
| originalDcfInputs | Zustand | pipeline 原始输出，reset 时恢复 |
| Sensitivity data | Zustand | 跟随 DCFInputs 变化 |
| Run progress (steps) | useRunStream local state | 临时性，run 结束后不需要 |
| Current ticker | Zustand | UI 状态 |
| Phase | Zustand | UI 状态机 |

### 4.3 后端补充：POST Excel 导出端点

Phase 2 需要后端新增一个端点，让 Excel 导出反映用户交互后的当前假设，而非 pipeline cache。

**新端点：** `POST /api/export/excel/dcf`

```python
# 新建 finagent/routes/export.py, prefix = "/api/export"

from finagent.engine.compute.spreadsheet_gen import generate_dcf_excel

class DcfExportRequest(BaseModel):
    ticker: str
    inputs: DCFInputs
    result: DCFResult

@router.post("/excel/dcf")
async def export_dcf_excel_interactive(req: DcfExportRequest) -> StreamingResponse:
    """Generate DCF Excel from client-provided inputs/result (interactive mode)."""
    xlsx_bytes = generate_dcf_excel(req.result, req.inputs)
    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={req.ticker}_dcf.xlsx"},
    )
```

- 路由挂载在 `prefix="/api/export"`，最终路径 = `POST /api/export/excel/dcf`
- 现有 `GET /api/export/excel/dcf/{ticker}` 保留（从 pipeline cache 导出 AI 原始模型）
- **不要**放在 `routes/compute.py`（那样路径会变成 `/api/compute/export/...`，语义混乱）

### 4.4 后端修复：RunDetail.result.structured 展平

当前 `get_run()` 的返回结构有一层多余嵌套：

```json
// 当前（错误）
{
  "result": {
    "structured": {
      "structured_data": { "dcf_calc": { ... } },
      "failed_validations": [...],
      "warnings": [...]
    }
  }
}
```

`warnings` 和 `failed_validations` 已经被提升到 `RunDetail` 顶层字段，`structured` 内的这两个字段是冗余的。`structured_data` 这层嵌套也没有语义价值。

**需要改 `routes/runs.py:get_run()`**，将 `structured` 展平：

```python
# 当前代码（line 112-118）
structured = record.result_json
# ...
result = RunResult(text=record.result_text, structured=structured)

# 改为
raw = record.result_json
flat_structured = raw.get("structured_data", {}) if raw else None
result = RunResult(text=record.result_text, structured=flat_structured)
```

修复后前端路径：`response.result.structured["dcf_calc"]` — 干净、无歧义。

---

## 5. Electron 打包修复

### 5.1 extraResources 加 skills/

在 `desktop/package.json` 的 `build.extraResources` 中加入：

```json
{
  "from": "../skills",
  "to": "skills",
  "filter": ["**/*"]
}
```

### 5.2 首次启动健壮性

`electron/main.ts` 的 `waitForServer()` 已经有 health check 轮询。确认：
- 超时时间足够（120s 适合首次 `uv sync`）
- 超时后显示有用的错误信息（不是空白窗口）
- Python 进程退出时 Electron 也退出（检查 `serverProcess.on('exit')` 处理）

### 5.3 Settings 页面替代 .env

用户不需要手动创建 `.env` 文件。首次启动 → Settings 引导 → API key 存入 keychain → 后端自动读取。

---

## 6. 验收标准

**所有项必须通过。无例外。**

### 6.1 Settings 流程
- [ ] 首次启动（无任何 key）→ 自动进入 Settings 页面
- [ ] 填写当前 model provider 对应的 API key → Save → 后端验证通过 → 进入 Workspace
- [ ] model 选 DeepSeek 但只填了 Anthropic key → Save → 提示 "DeepSeek API key required"
- [ ] 填写无效 provider 格式 → Save → 显示具体错误信息
- [ ] GET /api/settings 永不返回 key 原文
- [ ] 关闭应用重开 → Settings 不需要重新填写（key 在 keychain）

### 6.2 数据加载
- [ ] 输入 AAPL → Load → 2-5 秒内看到完整的公司基本面数据
- [ ] 数据来源标签正确显示（yfinance / fmp / finnhub）
- [ ] null 字段显示 "—"，不是 0 或空白
- [ ] warnings 在黄色 banner 中显示
- [ ] 输入无效 ticker（如 ZZZZ999）→ 显示 "Ticker not found" 错误

### 6.3 DCF Pipeline
- [ ] "Run DCF Analysis" 按钮可点击
- [ ] 点击后进度条 + 步骤列表实时更新
- [ ] 每个步骤的名称和耗时正确显示
- [ ] 30-60 秒内完成
- [ ] 完成后自动展示 DCF 结果（implied price, sensitivity, waterfall）
- [ ] Pipeline 失败 → 显示错误信息 + Retry 按钮
- [ ] SSE 断线重连后不重复/不丢 step（Last-Event-ID replay 验证）

### 6.4 交互式假设调整（杀手级验收）
- [ ] 所有 slider 初始值 = pipeline 返回的 DCFInputs
- [ ] compute API roundtrip (debounce 触发 → 响应返回) p95 < 200ms
- [ ] UI 可见更新 (debounce 触发 → chart 重绘完成) p95 < 300ms
- [ ] WACC 显示值随组件 slider 变化实时更新
- [ ] Sensitivity heatmap 的 7x7 格子正确着色
- [ ] terminal_growth_rate >= wacc 的格子显示 "N/A"
- [ ] "Reset to AI defaults" 恢复所有 slider 到初始值
- [ ] Revenue growth rates 可以逐年修改
- [ ] 修改 EBITDA margin → implied price 变化方向正确（margin 增加 → price 增加）

### 6.5 导出
- [ ] Export Excel (Current Model) → POST 当前 DCFInputs+DCFResult → 下载 .xlsx → 数字与界面一致
- [ ] View AI Report (HTML) → 新窗口展示 pipeline 原始报告（含 LLM 叙述）
- [ ] Download AI Report (PDF) → 下载 .pdf，内容与 HTML 报告一致
- [ ] 用户调整 slider 后 → Excel 导出反映调整后数字 → HTML/PDF 仍是 AI 原始报告
- [ ] HTML/PDF 按钮文案包含 "AI Report"（不能写成 "Export Report" 造成歧义）

### 6.6 打包与 CI
- [ ] `npm run dist:mac` 成功构建
- [ ] 构建产物中包含 skills/ 目录
- [ ] DMG 安装后首次启动 → 自动安装 Python 依赖 → 进入 Settings
- [ ] `schema.d.ts` 与 `/openapi.json` 同步（CI 中 `npm run generate:api && git diff --exit-code src/api/schema.d.ts`）

---

## 7. 不做的事（显式排除）

| 功能 | 原因 |
|---|---|
| LBO workspace | Phase 3 |
| Comps workspace | Phase 3 |
| Research 完整报告视图 | Phase 3 |
| Run history 页面 | Phase 3（后端已持久化，UI 后做） |
| 多 ticker 对比 | Phase 3 |
| Watchlist | 需要实时数据管道，Phase 3+ |
| 新闻/异动 | 需要新闻 API，Phase 3+ |
| 每日看板 | 需要后台服务，Phase 3+ |
| Skills 执行 | 需要执行引擎，Phase 3+ |
| 深色/浅色主题切换 | 保持当前 dark theme 不变 |

---

## 8. 实现顺序建议

```
Week 1:
  1. 搭建 API client 基础设施（openapi-typescript, openapi-fetch, React Query）
  2. 重写 App.tsx + SettingsView.tsx
  3. 验收 §6.1

Week 2:
  4. TickerInput + FinancialsPanel + WarningBanner
  5. 验收 §6.2
  6. useRunStream + PipelineRunner
  7. 验收 §6.3

Week 3:
  8. AssumptionsEditor + useCompute + ValuationCard
  9. 适配 SensitivityHeatmap + WaterfallChart 数据格式
  10. 验收 §6.4（杀手级）

Week 4:
  11. ExportBar
  12. 打包修复
  13. 验收 §6.5 + §6.6
  14. 全流程端到端测试
```

---

## 9. 给实现者的注意事项

1. **不要手写 TypeScript 接口。** 所有 API 类型从 OpenAPI schema 生成。如果后端模型改了，重新跑 `npm run generate:api`。

2. **Slider debounce 策略。** 用户拖动中每 100ms 最多发一次 compute 请求。用 `use-debounce`（已安装，React hook 风格）。不要在每次 onChange 都发请求。用法：`const [debouncedInputs] = useDebounce(dcfInputs, 100);` + `useEffect` 监听 `debouncedInputs` 变化触发 compute。

3. **Sensitivity grid 范围构建。** Pipeline 返回的 DCFResult 中有 `wacc` 和 `inputs.terminal_growth_rate`。以这两个值为中心 ±3 个步长构建 7x7 grid：
   ```
   wacc_range = [wacc-0.03, wacc-0.02, wacc-0.01, wacc, wacc+0.01, wacc+0.02, wacc+0.03]
   tg_range = [tg-0.015, tg-0.01, tg-0.005, tg, tg+0.005, tg+0.01, tg+0.015]
   ```
   确保所有值 >= 0（clamp）。

4. **chart 组件不改内部。** 所有数据格式转换通过 `src/utils/chartAdapters.ts` 中的 adapter 函数完成（见 §3.13）。不修改 chart 组件的 props 接口，不碰 chart 测试。如果某个 chart 的现有接口确实无法适配，先在 adapter 中解决，实在不行再改 chart 并同时更新测试。

5. **错误边界。** 每个独立区域（FinancialsPanel、PipelineRunner、AssumptionsEditor、charts）用 ErrorBoundary 包裹。一个 chart 渲染失败不应该崩掉整个 workspace。

6. **不要在前端存 API key。** Settings 页面的 password input 是 controlled component，但 `onSave` 后立刻清空本地值。Zustand store 中不存任何 key 字符串。
