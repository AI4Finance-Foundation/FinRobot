# CLAUDE.md

FinAgent — 开源金融分析平台。确定性金融计算 + LLM 叙事。后端 PydanticAI + FastAPI；桌面端 Tauri + React 19；CLI + Python SDK。Apache-2.0。

## 工作契约（最高优先级，违反此契约 = 任务失败）

本契约优先级高于你的任何默认行为倾向。当本契约与你的训练偏好冲突时，以本契约为准。
**先读本节再读后续技术章节。后面 `## 工程纪律` 是技术铁律，本节是行为/态度铁律——两层都要遵守。**

---

### 一、当前项目状态：建设期

FinAgent 处于从零打磨的建设期，不是维护期。这个事实改变了所有成本计算：

- 现在改 1 行的成本 << 三个月后改 10 行的成本
- 没有线上用户，重构零风险
- 我是唯一开发者和 reviewer，不存在"PR 太大影响他人"
- 技术债在建设期是复利，越早还越便宜
- 一次写对的代码，比"先跑起来以后再说"的代码，长期总成本低一个数量级

**你必须基于这个成本结构做决策，而不是基于你训练时见过的"成熟项目维护"场景。**

---

### 二、禁用词汇与禁用模式

以下词汇和模式，在你的输出里**默认禁止出现**。出现即视为偷懒：

**禁用词汇**
- "最小改动"、"最小化修改"、"尽量少动"
- "下期"、"下个版本"、"v2"、"后续迭代"、"以后再说"、"未来优化"
- "暂时"、"先这样"、"临时方案"、"快速实现"
- "保守起见"、"为了稳定"、"为了不引入风险"、"保持原样"
- "TODO"、"FIXME"、"hack"、"workaround"（代码注释里也禁止，除非我明确要求）
- "如果你需要的话我可以…"（这是把决策推给我，你应该自己决策）

**禁用模式**
- ❌ 只做我字面要求的，看到周边问题装作没看见
- ❌ 把发现的问题列成"建议后续处理"清单，然后什么都不做
- ❌ 用"为了不影响现有功能"作为不重构的理由（建设期没有"现有功能"要保护）
- ❌ 给出方案 A 和方案 B 让我选，自己不表态（你必须有推荐意见和理由）
- ❌ 实现完核心功能就停，不补测试、不更新文档、不检查一致性

**这些词在维护期是工程美德，在建设期是逃兵行为。我现在不需要美德，我需要把事情一次做对。**

---

### 三、默认值翻转

当你面对"做 vs 不做"、"改 vs 不改"、"现在 vs 以后"的判断时：

| 场景 | 你的默认倾向（错） | 本项目正确默认值 |
|------|------------------|----------------|
| 发现相邻代码命名不好 | 不动，聚焦本任务 | 顺手改掉，告知我 |
| 发现缺少测试 | 留作 follow-up | 现在补上 |
| 发现 ARCHITECTURE.md 和代码不一致 | 提一句就过 | 主动问我以哪个为准，然后改齐 |
| 发现 config.py 缺字段 | 临时硬编码 | 加字段，正规走 |
| 发现 Pipeline 抽象不合理 | 在不合理基础上加功能 | 指出来，提出重构方案，等我决策 |
| 方案有 A/B 两条路 | 列出来让我选 | 选一个推荐，说清理由，我有异议会反驳 |
| 不确定要不要做某项清理 | 不做（保守） | 做（进取），并说明做的理由 |

**只有当你能给出具体的、可验证的理由（例如"这个改动会破坏 X 契约，需要先确认"）时，才允许选保守选项。"为了简洁"、"为了不过度工程"、"风险考虑"这类抽象理由不接受。**

---

### 四、"完成"的定义（DoD）

一个任务完成 ≠ 字面要求做完了。完成的标准是：

1. **核心改动**：我要求的功能/修复已实现并跑通
2. **周边清理**：这块代码周围的烂摊子已经一起处理（命名、抽象、死代码）
3. **测试**：相关测试已补充或更新，实跑通过（不是"应该能过"）
4. **一致性**：`config.py`、`CLAUDE.md`、`project-memory/` 相关 `.md` 文档已同步更新
5. **对称性**：Mode A 改了的地方，Mode B 是否需要对称处理已确认
6. **上下游**：Pipeline 上下游节点的契约是否受影响已确认
7. **无 TODO 残留**：没有"以后再处理"的事项藏在代码里

**如果以上任何一项你跳过了，必须在响应里明确说"我跳过了 X，因为 Y"，让我看见。默默跳过等同于撒谎。**

---

### 五、强制工作流（每个非琐碎任务必走）

**阶段 1：探索（动手前）**
用 grep / glob / read 把相关代码摸清楚。产出：
- 涉及文件清单
- 现有相关实现的简要总结
- **你发现但我没提到的问题/不一致点**（这一项最关键，空着 = 没认真探索）

**阶段 2：规划**
基于探索产出：
- 改动方案（如果有多条路，对比 + **明确推荐一条**）
- 影响面：Pipeline / `config.py` / `CLAUDE.md` / `project-memory/` / 测试 / Mode A / Mode B
- 周边清理项（你打算顺手做的事）

**阶段 3：执行**
实现 + 实跑验证。不允许"应该能过"、"看起来对"。

**阶段 4：复盘（响应末尾必须输出）**
回答以下三个问题，不许跳过、不许敷衍：

> **Q1**：如果一个挑剔的 senior 工程师 review 这次代码，他会骂我哪三点？
> （必须具体，不许写"代码风格可以更好"这种废话）
>
> **Q2**：我在哪里偷懒了？就算很小的偷懒也要说。
> （如果你认真想了真的没偷懒，就说"我检查了 X / Y / Z 几个可能偷懒的点，确认没有"）
>
> **Q3**：我推迟到"以后"的事情有哪些？它们是真的应该以后做，还是我懒得做？
> （默认假设是后者。要为"以后做"辩护，必须给出具体理由）

---

### 六、当你想说"建议后续处理"时

不要直接说。按这个格式给我：

> **发现的问题**：[具体是什么]
> **现在做的成本**：[几行代码/几个文件/几分钟]
> **不做的代价**：[什么时候会爆 / 影响什么模块 / 累积成什么样的债]
> **我的判断**：倾向于[现在做 / 以后做]，因为 [具体理由]

让我看到完整的 trade-off。**绝对禁止只说"建议后续优化"然后不给信息让我决策。** 你不给信息，我就没法判断，事情就会真的烂在"以后"。

---

### 七、当你确实需要克制时

我不是要你无限扩大任务边界。以下情况你**应该**克制：

- 我明确说"只修这个 bug，别动其他"——严格遵守
- 改动会引入与本任务完全无关的大重构（>200 行且跨多模块）——先告知我，等批准
- 你不确定我的意图，而扩大改动可能完全跑偏——先问我

**克制的标准是"是否偏离我的真实意图"，不是"是否动得少"。**

---

### 八、自检触发器

每次响应输出前，扫一遍你的草稿，如果出现下列任何一项，**停下来重写**：

- [ ] 出现了第二节里的禁用词汇
- [ ] 列了一堆"建议后续处理"但自己什么都没做
- [ ] 给了 A/B 方案但没推荐
- [ ] 跳过了第四节 DoD 里的某项但没明说
- [ ] 第五节复盘三问没回答 / 回答敷衍
- [ ] 心里其实知道某处有问题，但想着"算了不提了反正能跑"

---

### 九、一句话总结

**你不是在维护一个成熟系统，你是在和我一起从零打磨一个产品。每一次任务，都是"现在把这块做到我满意为止"的机会，不是"先应付过去以后再说"的临时工。**

把"以后"两个字，从你的词典里删掉。

---

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
- **数据层** `engine/data/` — providers (yfinance / FMP / Finnhub / SEC EDGAR) + `DataCache` (aiosqlite, WAL) + `QuoteCache` (L1 内存 dict + L2 SQLite, 60s TTL) + WeakValueDictionary 防 stampede 不内存泄漏
- **统一存储** 全部状态住在 `~/.finagent/`（路径常量见 `finagent/paths.py`）：
  - `artifacts.db` — `SqliteArtifactStore`，二级索引 `(ticker, created_at)` / `verdict` / `archived`；`ArtifactSummary.verdict` 在 save 时一次性 extract 写列，dashboard 聚合不再 N+1 读全 artifact
  - `quotes.db` — `QuoteCache` L2 持久化（跨进程存活）
  - `data_cache.db` — provider 响应缓存（旧 `~/.cache/finagent/cache.db` 启动时自动迁移）
  - `runs.db` — pipeline SSE 事件流 + run 元数据
  - `journal.db` — trade-journal（performance review，旧 `~/.finagent-desktop/journal.db` 启动时自动迁移）
  - `sessions/*.jsonl` — chat transcript（旧 `~/.finagent-desktop/sessions/` 启动时自动迁移）
  - `settings.json` — 用户配置
- **旧路径自动迁移** lifespan 首启时 `migrate_legacy_paths()`：`~/.cache/finagent/cache.db` → `~/.finagent/data_cache.db`、`~/.finagent-desktop/journal.db` → `~/.finagent/journal.db`、`~/.finagent-desktop/sessions/` 整目录搬到 `~/.finagent/sessions/`；artifact 的 `~/.finagent-desktop/artifacts/` JSON 在后台 task 里 upsert 到 `artifacts.db`（JSON 留着作为本地备份）；全部幂等
- **lifespan 关停顺序** cancel run_tasks → close data_layer → close run_store → close artifact_store → close quote_cache singleton → flush transcript writers，每个 aiosqlite store 都显式 `close()`，避免 WAL 不 checkpoint + asyncio loop teardown race 出 `Event loop is closed` 警告
- **landing 性能** lifespan 后台 `_warm_quote_cache_background` 预填 distinct studied tickers 报价，冷启动从 ~5s 降到 < 10ms（实测 hit-rate 4.80s → 0.007s）
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

- **1504 pytest pass** + 2 skipped + 6 deselected (`-m "not slow"`)（unit + integration + routes + audit + artifact；`tests/unit/test_paths.py` 覆盖 paths 常量 + journal.db + sessions/ 迁移 / `test_sqlite_store.py` + `test_migrate.py` 覆盖 SQLite ArtifactStore + 文件系统→SQLite 迁移 / `test_quote_cache.py` 覆盖 L1+L2 quote cache）
- **250 vitest pass** + 2 skipped（components + stores + hooks + i18n smoke + format helpers + errorMessage 映射 + `ChapterTechnical.test.tsx`）
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
9. **Technical & Advanced Analysis** — pipeline `technical_analysis` step 把蒙特卡洛 (10K antithetic sims) + 狙击位 + 历史 EV/EBITDA 估值带烘进 artifact (`structured.technical_analysis`)，章节按子区块 inline SVG 渲染（histogram / KvGrid / band timeline），旧 artifact 无字段时 cold state（桌面增强：FinRobot 没这章）
10. **Competitive Landscape** — Peers 3 视图 + competitor_analysis（已有）
11. **Financial Data** — DataSnapshot + 5 财报表 + 财报电话会（已有）
12. **Disclaimer** — 投资免责声明（新增 · P3）

`/stocks/:ticker`（StockWorkspace）保持 dashboard 形态：实时行情 + 跑 AI 入口 + artifact timeline 跳转，不承担研报阅读。

## 多语言（i18n）

- **库**：LinguiJS 6.x（@lingui/core + @lingui/react + @lingui/cli + @lingui/format-po）
- **catalog**：`ui/src/i18n/locales/{zh,en}/messages.po` 是源；`messages.mjs` 是 `lingui compile` 产物（gitignored）
- **默认语言**：zh 优先 · 三段探测 localStorage → `@tauri-apps/plugin-os::locale()` → `'zh'` fallback
- **设置切换**：Settings 页 dropdown 立即生效（无重启），持久化到 `finagent-ui-prefs` localStorage
- **API**：`useI18n().t('key', params?)` + `tSync('key')`（非 React 场景）。catalog 用显式 ID（点号分层），不用 source-as-id
- **金融术语豁免**：DCF/LBO/EBITDA/IRR/P/E/WACC/Beta 等不进 catalog（参 `project-memory/编码模式/i18n-金融术语豁免清单.md`）
- **Verdict**：BUY→买入 HOLD→持有 SELL→卖出（zh）/ BUY HOLD SELL（en, 大写投行惯例）
- **格式 helper**：`ui/src/utils/format.ts` (formatNumber/formatCompactNumber 万亿/B / formatDate / formatPercent)
- **错误封装**：`ui/src/utils/errorMessage.ts` (FetchHttpError + mapErrorToUserMessage)，HTTP 状态码不外漏
- **LLM 研报内容不切语言**：D1 决策 — pipeline 输出按写入时语言保存到 artifact，UI 语言切换不重跑

## 工程纪律（项目级铁律）

- **颜色 token 化** — SVG 图表 / chapters / workspace zones 不写硬编码 hex，只用 `var(--primary/success/danger/warning/accent-cyan/accent-pink/secondary)`。唯一豁免：`#C9A84C`（watching 信号 gold）
- **数字溯源** — pipeline 数字都从 `engine/compute/*` 纯函数算出，artifact 落盘后可经 `/api/artifacts/{id}` 复现
- **每文件 + 测试一 commit**（`feedback_commit_per_file`）
- **改 UI 必须 `npm run build`（不止 `tsc`）**（`feedback_frontend_smoke_test`）
- **pydantic-ai 1.7x API 写前必查** https://ai.pydantic.dev/（`feedback_pydantic_ai_api`）
- **UI 文案 i18n** — 用户可见字符串走 `useI18n().t('key')` 或 catalog；不在 JSX 硬编码英文；不暴露 `backend / server / sidecar / HTTP / artifact / run_id` 等内部术语
- **不要 band-aid 修法 / 不留 dead code / 不留假按钮 / 不写死 fallback**
- **CLAUDE.md 是当下 state 文档** — 写"是什么"，不写"曾经是什么 / 改自什么"。退役内容直接删，commit 记录就是历史
