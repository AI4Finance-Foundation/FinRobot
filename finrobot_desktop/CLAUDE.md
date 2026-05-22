# CLAUDE.md

FinAgent — 开源金融分析平台。确定性金融计算 + LLM 叙事。后端 PydanticAI + FastAPI；桌面端 Tauri + React 19；CLI + Python SDK。Apache-2.0。

## 项目背景

FinAgent = **FinRobot equity 金融能力重写** + **Claude Code 对话架构** + **工程纪律层**。
- 对标 `/Users/zhunihaoyun/Desktop/code/Fin/FinRobot/finrobot_equity/`（8 agents、6 估值、SEC、Adanos）
- 对话架构参考 `/Users/zhunihaoyun/Desktop/code/claude-code/src/`（P6 八个 pillar）
- 目标：包含 finrobot 的所有能力并超过它，finrobot 是我们的下限，这是立场

**核心赌注：数字由代码算出，判断由 LLM 给出。** LLM 永远不产出无法追溯到函数调用的数字。

## 产品定位

**开源流量项目，KPI = GitHub Stars。** 目标用户：散户 / 量化新手 / 非专业人士。

**核心价值：给普通人看得懂的基本面报告。** 确定性计算出数字，LLM 给文字解释。技术越新越好（吸引开发者），桌面 APP 风格（好看），不做终端式 GUI。

| 受众 | 要什么 | 给什么 |
|---|---|---|
| 散户 | 简洁好看，看懂大方向 | 结论先行、图表直观、文字解释 |
| 开发者 | 新技术、干净架构 | MCP/Skills/Agent 三栈、工程纪律 |

## 当前架构状态（2026-05-22）

### 后端（FastAPI + PydanticAI 1.7x）
- 7 个 pipeline：`research / ic-memo / earnings / dcf / lbo / ddm / comps`（注册在 `engine/pipelines/registry.py`）
- 每个 pipeline 都有 `artifact_builder=...`，自动持久化完整 Artifact 到 `ArtifactStore`
- 路由按职责分文件：`routes/{analyze,artifacts,ask,backtest,compute,dashboard,data,export,exports,journal,market,notify,runs,search,sentiment,settings,valuation}.py`
- 数据层 `engine/data/` — providers + cache（SQLite + WeakValueDictionary 防 stampede 不内存泄漏）
- 聚合层 `engine/aggregations/` — 叶层纯函数（hit_rate_overview / recent_research）

#### 关键 endpoints
- `POST /api/runs` + `GET /api/runs/{run_id}/events` — SSE 流式跑 pipeline
- `GET /api/artifacts` / `/{id}` / `/by-ticker/{ticker}/timeline` / `/{a}/diff/{b}` — artifact CRUD + 版本 diff
- `GET /api/artifacts/studied-tickers` — distinct ticker rollup（landing 用）
- `GET /api/dashboard/hit-rate` — 跨 ticker 胜率，按 verdict 桶
- `GET /api/dashboard/recent-research` — top-N 历史，含 signal lamp + delta-to-target
- `POST /api/compute/{dcf,ddm,lbo,monte-carlo,sniper,score,multiples,peer-stats,wacc,…}` — 确定性计算独立调用
- `GET /api/valuation/aggregate/{ticker}` + `/historical-bands/{ticker}` — Football Field + EV/EBITDA 历史带
- `POST /api/exports/pdf/{artifact_id}` — weasyprint PDF（缺依赖 → 501 fallback）
- `GET /api/sentiment/{ticker}` — Adanos 散户情绪

### 前端（React 19 + Tauri）

#### 路由（`router.tsx`）
```
/                              → /stocks
/stocks                        → StocksLandingHero（spec §2.2 全件）
/stocks/:ticker                → StockWorkspace（5 group / 23 section）
/stocks/:ticker/runs/:artifactId → ArtifactDetailPage（完整 Artifact 详情）
/settings                      → SettingsPage
```

#### Shell（`layout/`）
- `TitleBar` 44px：brand-dot logo + halo cmdK input + AI 助手按钮（Tauri overlay 三色控件）
- `Sidebar` 64px：极窄 icon-only，active 3px 蓝光竖条
- `RightChatPanel/` 上下 tab 拆分：上 Watchlist（sparkline + 💡 + 聚合 AI 点评）/ 下 AiChatTab
- `CmdKOverlay`：⌘K 全局，含 section 导航 panel（替代 v5 AnchorNav）
- `AppShell`：CursorCanvas（Bezier 12-spring 拖尾） + cosmic-stars 双层 drift 背景

#### Cosmic 设计 token（`App.css`）
- 深空双轨：`--bg-void/deep/card/elevated` + `--primary/secondary/accent-cyan/accent-pink`
- 三轨字体：`--font-display` (Audiowide) + `--font-mono` (JetBrains Mono) + `--font-body` (Inter)
- 7 个合法动效 keyframes：`cosmic-pull-up / morph / shimmer / halo / pulse-dot / pulse-ring / drift-slow + drift-fast`
- 工具类：`.cosmic-card` / `.cosmic-badge.cosmic-badge-{buy,hold,sell}` / `.btn-shimmer` / `.halo-input` / `.cosmic-group-header`

#### FinRobot LLM 叙事字段（ThesisResult）
- `tagline` — ≤ 60 字的可分享一句话结论
- `key_takeaways` — 3-5 条核心结论（distinct from catalysts/risks）
- `valuation_overview` — 150-200 字 DCF/Comps/DDM 解读
- `competitor_analysis` — vs 同业 3-4 句叙事
- `news_summary` — 近 30 天新闻整体情绪 + 论点支撑/挑战

surface 位置：HeroVerdict（tagline + takeaways + cosmic-badge）/ FootballField（valuation_overview）/ PeersSection（competitor_analysis）/ NewsTimeline（news_summary）。

#### 已退役
- `AnchorNav.tsx` — section 导航移到 ⌘K（spec §8）
- v4 8-tab 视图（NewsTab / FinancialsTab / 等 4 个）— 整体改为 v5 单页 StockWorkspace
- 16 个孤儿组件（AskPanel / StockHeader / StockOverview / ExportBar / 5 个 *Summary / ValuationCard / AssumptionsEditor / ScenarioCompare / ShortcutSheet / WarningBanner / CatalystPanel / ActivityBar）

## 测试金字塔（2026-05-22）

- **1452 pytest pass** + 2 skipped（unit + integration + routes + audit + artifact）
- **192 vitest pass**（components + stores + hooks）
- **2 Playwright e2e pass**：v5 5-step retail walkthrough + cosmic research flow（landing → studied tickers → workspace → ArtifactDetailPage）

## UI 设计规范强制（桌面 App）

**任何 UI 改动（新组件 / 新页面 / 调样式 / 改 ui/）必须先读：**
`project-memory/编码模式/UI-风格规范-cosmic桌面版.md`

规范定性：**Cosmic Desktop · 太空仪表盘桌面版**（Tauri 桌面 App，非网页）
- 配色：deep space dark `#05050d/0a0a18` + 蓝紫双轨霓虹 `#3B82F6/8B5CF6` + cyan live 信号 `#22D3EE`
- 字体三轨：Audiowide 标题 + JetBrains Mono 数字 + Inter body
- 桌面专属：macOS 窗口控件 + 64px slim sidebar + 自定义 Canvas 拖尾鼠标 + Spline 3D 机器人嵌入
- 动效白名单 7 种：pull-up / morph / shimmer / halo / pulse-dot / pulse-ring / drift（其他禁用）
- 涨绿跌红（美股惯例，非 A 股）
- 样板：`stock-workspace-design-demo.html`（v1 完整 demo，所有 token 实例齐全）

禁忌：不用纯黑、不引新主色、不用 Audiowide 写 < 16px 小字、不引入外部图表库（inline SVG）、不做 < 1200px 响应式（桌面 App 只跑桌面）。

## 工程纪律（项目级铁律）

- **颜色 token 化** — SVG 图表 / sections 不写硬编码 hex，只用 `var(--primary/success/danger/warning/accent-cyan/accent-pink/secondary)`。唯一豁免：`#C9A84C`（watching 信号 gold）。
- **数字溯源** — pipeline 数字都从 `engine/compute/*` 纯函数算出，artifact 落盘后可经 `/api/artifacts/{id}` 复现
- **每文件 + 测试一 commit**（`feedback_commit_per_file`）
- **改 UI 必须 `npm run build`（不止 `tsc`）**（`feedback_frontend_smoke_test`）
- **pydantic-ai 1.7x API 写前必查** https://ai.pydantic.dev/（`feedback_pydantic_ai_api`）
- **不要 band-aid 修法 / 不留 dead code / 不留假按钮 / 不写死 fallback**（feedback 多条）
