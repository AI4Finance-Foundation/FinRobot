# CLAUDE.md

FinAgent — 开源金融分析平台。确定性金融计算 + LLM 叙事。后端 PydanticAI + FastAPI；桌面端 Tauri + React 19；CLI + Python SDK。Apache-2.0。

## 项目背景

FinAgent = **FinRobot equity 桌面 app 化重写** + **Claude Code 对话架构** + **工程纪律层**。
- 对标 `/Users/zhunihaoyun/Desktop/code/Fin/FinRobot/finrobot_equity/`（8 agents、6 估值、SEC、Adanos）
- 对话架构参考 `/Users/zhunihaoyun/Desktop/code/claude-code/src/`（P6 八个 pillar）
- 立场：包含 FinRobot 所有能力并超越它。FinRobot 是下限，桌面 app 独占能力是超越点。

**核心赌注：数字由代码算出，判断由 LLM 给出。** LLM 永远不产出无法追溯到函数调用的数字。

## 产品定位

**开源流量项目，KPI = GitHub Stars。** 目标用户：**金融分析师 / 量化研究员 / 主动投资者**。

**核心价值：FinRobot equity 研报能力 + 桌面 app 工作流。** 阶段策略：

- **阶段 1 · FinRobot Parity（当前）** — 复刻 FinRobot 全部 10 章节研报形态 + 8 agents 叙事，章节命名 / 文案 / 排版全部按投行术语，功能对等
- **阶段 2 · Desktop Augmentation** — 用桌面 app 独占能力超越：实时行情 overlay / artifact 版本 diff / 可编辑假设重算 / 多 ticker 并排 / 财报电话会音频内嵌 / Spline 3D / Cursor 拖尾 / ⌘K 全局命令面板
- **阶段 3 · Open Ecosystem** — MCP / Skills / Agent 三栈扩展，吸引贡献者

| 受众 | 要什么 | 给什么 |
|---|---|---|
| 分析师 | 投行级研报深度 + 桌面工作流 | 10 章完整研报 + 估值模型可编辑 + artifact 版本对比 |
| 开发者 | 新技术、干净架构 | MCP/Skills/Agent 三栈、工程纪律 |

## 后端架构（FastAPI + PydanticAI 1.7x）

- **唯一 UI-facing pipeline：`research`** — 一键产出包含 FinRobot 8 章 + 桌面增强（蒙特卡洛 / 狙击位 / 敏感性 / 财报会 / Peers 3 视图）的全量 artifact。**1 ticker = 1 跑 = 1 份 artifact，不再有"分类型报告"。**
- **SDK-only pipelines**（保留但 UI 永远不暴露）：`ic-memo / earnings / dcf / lbo / ddm / comps`。能力都已折进 research。这些 key 留给 `/api/runs` 编程接口 + 历史 artifact 反向兼容；如需调整某一估值的假设，走 `/api/compute/*` REST。
- **注册位置**：`engine/pipelines/registry.py`，每个 pipeline 都有 `artifact_builder=...`，自动持久化完整 Artifact 到 `ArtifactStore`。
- **路由按职责分文件**：`routes/{analyze,artifacts,ask,backtest,compute,dashboard,data,export,journal,market,notify,runs,search,sentiment,settings,valuation}.py`
- **数据层** `engine/data/` — providers (yfinance / FMP / Finnhub / SEC EDGAR) + SQLite cache + WeakValueDictionary 防 stampede 不内存泄漏
- **聚合层** `engine/aggregations/` — 叶层纯函数（hit_rate_overview / recent_research）
- **compute 层** `engine/compute/`（FinRobot 同款 + 增强）：
  - 估值：`dcf / ddm / lbo / comps / multiples / wacc / valuation_aggregator / valuation_synthesis`
  - 财务：`forward_estimates / historical_extractor / historical_valuation / extractor / data_processor`
  - 主题：`catalyst / sentiment / news / rag / earnings / industry / market`
  - 桌面增强：`monte_carlo / sniper / composite_score / spreadsheet_gen / signal / compare`

### 关键 endpoints

- `POST /api/runs` + `GET /api/runs/{run_id}/events` — SSE 流式跑 pipeline
- `GET /api/artifacts` / `/{id}` / `/by-ticker/{ticker}/timeline` / `/{a}/diff/{b}` — artifact CRUD + 版本 diff
- `GET /api/artifacts/studied-tickers` — distinct ticker rollup
- `GET /api/dashboard/hit-rate` — 跨 ticker 胜率，按 verdict 桶
- `GET /api/dashboard/recent-research` — top-N ticker **抽屉卡片**：每张卡含 `runs[]`（最多 5 行，每行 = 一份 artifact，带 type / verdict / age_label / artifact_id 可直接路由到详情页）+ run_count（真实总数，超过 5 走 workspace timeline）+ latest_signal（卡头信号灯）
- `POST /api/compute/{dcf,ddm,lbo,monte-carlo,sniper,score,multiples,peer-stats,wacc,…}` — 确定性计算独立调用
- `GET /api/valuation/aggregate/{ticker}` + `/historical-bands/{ticker}` — Football Field + EV/EBITDA 历史带
- `GET /api/sentiment/{ticker}` — Adanos 散户情绪

## 前端架构（React 19 + Tauri）

### 路由（`router.tsx`）

```
/                              → /stocks
/stocks                        → StocksLandingHero
/stocks/:ticker                → StockWorkspace（双区 dashboard · 左 MarketDataZone / 右 AIZone · 三态 cold/running/hot）
/stocks/:ticker/runs/:artifactId → ArtifactDetailPage（12 章 FinRobot-parity 长滚动 · sticky toolbar/TOC/right-rail）
/settings                      → SettingsPage
```

### Shell（`layout/`）

- `TitleBar` 44px：brand-dot logo + halo cmdK input + AI 助手按钮（Tauri overlay 三色控件）
- `Sidebar` 64px：极窄 icon-only，active 3px 蓝光竖条
- `RightChatPanel/` 单一 AiChatTab：per-ticker 对话 AI，可拖拽宽度 + ⌘L 收起
- `CmdKOverlay`：⌘K 全局，含 section 导航 panel
- `AppShell`：CursorCanvas（Bezier 12-spring 拖尾） + cosmic-stars 双层 drift 背景

### Cosmic 设计 token（`App.css`）

- 深空双轨：`--bg-void/deep/card/elevated` + `--primary/secondary/accent-cyan/accent-pink`
- 三轨字体：`--font-display` (Audiowide) + `--font-mono` (JetBrains Mono) + `--font-body` (Inter)
- 7 个合法动效 keyframes：`cosmic-pull-up / morph / shimmer / halo / pulse-dot / pulse-ring / drift-slow + drift-fast`
- 工具类：`.cosmic-card` / `.cosmic-badge.cosmic-badge-{buy,hold,sell}` / `.btn-shimmer` / `.halo-input` / `.cosmic-group-header`

### FinRobot LLM 叙事字段（ThesisResult）

- `tagline` — ≤ 60 字的可分享一句话结论
- `key_takeaways` — 3-5 条核心结论
- `valuation_overview` — 150-200 字 DCF/Comps/DDM 解读
- `competitor_analysis` — vs 同业 3-4 句叙事
- `news_summary` — 近 30 天新闻整体情绪 + 论点支撑/挑战
- `recommendation` — BUY / HOLD / SELL
- `catalysts` / `risks` — 数组
- `company_overview` — 200-300 字 Company Overview（FinRobot 第 8 agent parity，business / segments / geography / moat 投行口吻）

surface 位置：`/stocks/:ticker/runs/:artifactId` 路由（ArtifactDetailPage）的 12 章节按字段映射渲染：
- `tagline` → 00 Cover 顶部 italic 引文
- `key_takeaways` + `recommendation` → 01 Investment Thesis takeaways list + verdict badge
- `company_overview` → 02 Company Overview narrative callout
- `valuation_overview` → 04 Valuation Analysis narrative callout
- `news_summary` → 05 Recent News & Events narrative callout
- `competitor_analysis` → 09 Competitive Landscape narrative callout

工作区 (`/stocks/:ticker`) 的 AIZone hot state 只显示 `headline` + `verdict` 大徽章 + `target_price` 作为入口卡，详情拉详情页看。

## 测试金字塔

- **1437 pytest pass** + 1 skipped（unit + integration + routes + audit + artifact）
- **191 vitest pass** + 2 skipped（components + stores + hooks · StockWorkspace.test rewritten for dual-zone dashboard contract）
- **Playwright e2e 待新建**：旧 2 个 spec (`v5-walkthrough` + `cosmic-research-flow`) 已删（依赖死 23-section 锚点 + StatBanner/HeroVerdict/FootballField testids）。新 e2e 应该覆盖 landing → workspace dual-zone (cold/running/hot) → ArtifactDetailPage 12-chapter (TOC scroll-spy + chapter mini-grid #anchor jump + Diff modal) 路径。BACKLOG 待排

## UI 设计规范强制（桌面 App）

**任何 UI 改动（新组件 / 新页面 / 调样式 / 改 ui/）必须先读：**
`project-memory/编码模式/UI-风格规范-cosmic桌面版.md`

规范定性：**Cosmic Desktop · 太空仪表盘桌面版**（Tauri 桌面 App，非网页）

- 配色：deep space dark `#05050d/0a0a18` + 蓝紫双轨霓虹 `#3B82F6/8B5CF6` + cyan live 信号 `#22D3EE`
- 字体三轨：Audiowide 标题 + JetBrains Mono 数字 + Inter body
- 桌面专属：macOS 窗口控件 + 64px slim sidebar + 自定义 Canvas 拖尾鼠标 + Spline 3D 机器人嵌入
- 动效白名单 7 种：pull-up / morph / shimmer / halo / pulse-dot / pulse-ring / drift（其他禁用）
- 涨绿跌红（美股惯例，非 A 股）
- 样板：`stock-workspace-design-demo.html`（cosmic token 全实例 demo）

禁忌：不用纯黑、不引新主色、不用 Audiowide 写 < 16px 小字、不引入外部图表库（inline SVG）、不做 < 1200px 响应式（桌面 App 只跑桌面）。

## FinRobot Parity 章节地图（阶段 1 目标）

`/stocks/:ticker/runs/:artifactId` 路由按 FinRobot 10 章顺序长滚动呈现：

1. **Cover** — ticker / 公司名 / verdict 大徽章 / 目标价 / 报告日期（新增 · P3）
2. **Investment Thesis** — tagline + recommendation + key_takeaways（已有，UI 重排）
3. **Company Overview** — `company_overview` LLM 字段（已有）
4. **Financial Analysis** — 历史财务 + 3 年 forecast（compute 层有，UI 重组）
5. **Valuation Analysis** — Football Field + 4 估值方法明细 + valuation_overview（已有）
6. **Recent News & Events** — NewsTimeline + news_summary（已有）
7. **Sensitivity Analysis** — SensitivityHeatmap + 假设说明（已有）
8. **Key Catalysts** — CatalystGrid 三段：Positive / Risks / Events to Monitor（已有）
9. **Technical & Advanced Analysis** — 蒙特卡洛 + 狙击位 + 价格走势（桌面增强：FinRobot 没这章）
10. **Competitive Landscape** — Peers 3 视图 + competitor_analysis（已有）
11. **Financial Data** — DataSnapshot + 5 财报表 + 财报电话会（已有）
12. **Disclaimer** — 投资免责声明（新增 · P3）

`/stocks/:ticker`（StockWorkspace）保持 dashboard 形态：实时行情 + 跑 AI 入口 + artifact timeline 跳转，不承担研报阅读。

## 工程纪律（项目级铁律）

- **颜色 token 化** — SVG 图表 / chapters / workspace zones 不写硬编码 hex，只用 `var(--primary/success/danger/warning/accent-cyan/accent-pink/secondary)`。唯一豁免：`#C9A84C`（watching 信号 gold）
- **数字溯源** — pipeline 数字都从 `engine/compute/*` 纯函数算出，artifact 落盘后可经 `/api/artifacts/{id}` 复现
- **每文件 + 测试一 commit**（`feedback_commit_per_file`）
- **改 UI 必须 `npm run build`（不止 `tsc`）**（`feedback_frontend_smoke_test`）
- **pydantic-ai 1.7x API 写前必查** https://ai.pydantic.dev/（`feedback_pydantic_ai_api`）
- **不要 band-aid 修法 / 不留 dead code / 不留假按钮 / 不写死 fallback**
- **CLAUDE.md 是当下 state 文档** — 写"是什么"，不写"曾经是什么 / 改自什么"。退役内容直接删，commit 记录就是历史
