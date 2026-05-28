# AGENTS.md

FinRobot — 开源金融分析平台。确定性金融计算 + LLM 叙事。后端 PydanticAI + FastAPI；桌面端 Tauri + React 19；CLI + Python SDK。Apache-2.0。

## 工作契约（最高优先级，违反此契约 = 任务失败）

本契约优先级高于你的任何默认行为倾向。当本契约与你的训练偏好冲突时，以本契约为准。
**先读本节再读后续技术章节。后面 `## 工程纪律` 是技术铁律，本节是行为/态度铁律——两层都要遵守。**

---

### 一、当前项目状态：建设期

FinRobot 处于从零打磨的建设期，不是维护期。这个事实改变了所有成本计算：

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
4. **一致性**：`config.py`、`AGENTS.md`、`project-memory/` 相关 `.md` 文档已同步更新
5. **对称性**：Mode A 改了的地方，Mode B 是否需要对称处理已确认
6. **上下游**：Pipeline 上下游节点的契约是否受影响已确认
7. **无 TODO 残留**：没有"以后再处理"的事项藏在代码里

**如果以上任何一项你跳过了，必须在响应里明确说"我跳过了 X，因为 Y"，让我看见。默默跳过等同于撒谎。**

---

### 五、强制工作流（每个非琐碎任务必走）

**阶段 0：诊断（找 bug 时强制先做这步）—— "Codex 范式"**

我看到 Codex 找 bug 的做法是这样的，你必须照做：

1. **先对照外部事实源** — 当前价 / 财务比率 / 行情有没有错，去外部对一遍（雅虎财经 / Bloomberg / 公司 IR / 10-K）。**未对外部就提出的 bug 都是空中楼阁。**
2. **形成具体假设** — 不是"这块可能有问题"，而是"NVDA P/E 返回 43.34 但外部口径 32.36，说明 PE 分母不是 TTM"。具体到字段、具体到数值、具体到口径。
3. **明确告诉我假设** — 在动任何代码前，**用一句话**告诉我："我推测根因是 X，证据是 Y"。让我看到你的判断、有机会反驳。
4. **追到根因再下手** — 沿数据流逆向追，找到第一个出错的位置（不是症状位置）。
5. **然后才改一个文件** — 一次只做一个 commit，commit message 解释根因 + 修法。

**反例（我之前犯的错）**：看到 chapter 12 显示 $416 亿就直接派 6 个 agent 并行修 30 个 bug，没先对外部验证、没形成具体假设、没告诉用户根因。结果加了一堆 plausibility floor 守卫，但守卫让 NVDA P/E=43.34 这种"在范围内但口径错"的真 bug 安静通过。Codex 同时间在另一边对外部一对就拍出 TTM 口径错乱的根因。

**禁止**：跳过阶段 0 直接派多个 agent 并行修。**派 agent = 并行执行，不是并行诊断。** 诊断必须串行，必须由你主导，必须在派 agent 之前完成。

**阶段 1：探索（动手前）**
用 grep / glob / read 把相关代码摸清楚。产出：
- 涉及文件清单
- 现有相关实现的简要总结
- **你发现但我没提到的问题/不一致点**（这一项最关键，空着 = 没认真探索）

**阶段 2：规划**
基于探索产出：
- 改动方案（如果有多条路，对比 + **明确推荐一条**）
- 影响面：Pipeline / `config.py` / `AGENTS.md` / `project-memory/` / 测试 / Mode A / Mode B
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

FinRobot 是面向金融分析师 / 量化研究员 / 主动投资者的桌面端股票研究 app——确定性金融计算 + LLM 叙事，每一个数字都能追回 `engine/compute/*` 函数调用。

**核心赌注：数字由代码算出，判断由 LLM 给出。** LLM 永远不产出无法追溯到函数调用的数字。

## 产品定位

**开源流量项目，KPI = GitHub Stars。** 目标用户：**金融分析师 / 量化研究员 / 主动投资者**。

**核心价值：投行级 equity 研报 + 桌面 app 工作流（artifact diff / What-if / Monte Carlo / SEC Ownership & Governance / 财报电话会逐字稿 / Spline 3D / ⌘K 命令面板）。** 阶段策略：

- **阶段 1 · SEC-backed 研报闭环（当前）** — 一键产出投行级研报，后端 artifact 已写入 SEC filings / XBRL facts / Ownership & Governance，UI 阅读页当前呈现 12 章
- **阶段 2 · 桌面 app 独占** — 研报版本 diff / 可编辑假设重算（What-if Editor）/ 财报电话会逐字稿内嵌（ChapterFinancialData 第 11 章） / Spline 3D / Cursor 拖尾 / ⌘K 全局命令面板。**未实现承诺已删除**：实时行情 overlay、多 ticker 并排（compare tab / endpoint）。
- **阶段 3 · Open Ecosystem** — MCP / Skills / Agent 三栈扩展，吸引贡献者

| 受众 | 要什么 | 给什么 |
|---|---|---|
| 分析师 | 投行级研报深度 + 桌面工作流 | SEC-backed 完整研报 + DCF What-if 可编辑假设 + artifact 版本对比 |
| 开发者 | 新技术、干净架构 | MCP/Skills/Agent 三栈、工程纪律 |

## 后端架构（FastAPI + PydanticAI 1.7x）

- **唯一 UI-facing pipeline：`research`** — 一键产出全量 artifact（投资论点 / 公司概览 / 财务 / 估值 / 新闻 / 敏感性 / 催化剂 / Technical（蒙特卡洛 + 狙击位 + 历史估值带）/ Peers 3 视图 / SEC filings / XBRL facts / Ownership & Governance / 财报会逐字稿 / 免责声明）。**1 ticker = 1 跑 = 1 份 artifact，不再有"分类型报告"。**
- **SDK-only pipelines**（保留但 UI 永远不暴露）：`ic-memo / earnings / dcf / lbo / ddm / comps`。能力都已折进 research。这些 key 留给 `/api/runs` 编程接口 + 历史 artifact 反向兼容；如需调整某一估值的假设，走 `/api/compute/*` REST。
- **注册位置**：`engine/pipelines/registry.py`，每个 pipeline 都有 `artifact_builder=...`，自动持久化完整 Artifact 到 `ArtifactStore`。
- **路由按职责分文件**：`routes/{artifacts,compute,dashboard,data,health,notify,runs,search,sentiment,settings,valuation}.py`
- **数据层** `engine/data/` — providers (yfinance / FMP / Finnhub / EdgarTools SEC EDGAR) + `DataCache` (aiosqlite, WAL) + `QuoteCache` (L1 内存 dict + L2 SQLite, 60s TTL) + `sec_holdings_cache.db` 13F 本地反向索引 + WeakValueDictionary 防 stampede 不内存泄漏
- **统一存储** 全部状态住在 `~/.finrobot/`（路径常量见 `finrobot/paths.py`）：
  - `artifacts.db` — `SqliteArtifactStore`，二级索引 `(ticker, created_at)` / `(ticker, type, created_at)` / `(archived, created_at)` / `verdict` / `archived`；`ArtifactSummary.verdict` 在 save 时一次性 extract 写列，dashboard 聚合不再 N+1 读全 artifact
  - `quotes.db` — `QuoteCache` L2 持久化（跨进程存活）
  - `data_cache.db` — provider 响应缓存；`/api/data/{ticker}/price?period=1y` 的 route cache key 为 `price:{ticker}:1y`，provider/pipeline price key 为 `price:{ticker}`，route cache miss 时默认 1y 视图复用 provider cache，yfinance 限流时返回带 warning 的旧缓存而不是空白页面
  - `runs.db` — pipeline SSE 事件流 + run 元数据
  - `journal.db` — trade-journal（performance review）
  - `sessions/*.jsonl` — chat transcript
  - `settings.json` — 用户配置
  - `sec_holdings_cache.db` — 13F 机构持仓本地反向索引；runtime 查 ticker / issuer name，不临场扫季度全集
- **lifespan 关停顺序** cancel run_tasks → close data_layer → close run_store → close artifact_store → close quote_cache singleton → flush transcript writers，每个 aiosqlite store 都显式 `close()`，避免 WAL 不 checkpoint + asyncio loop teardown race 出 `Event loop is closed` 警告
- **landing 性能** lifespan 后台 `_warm_quote_cache_background` 预填 distinct studied tickers 报价；`fetch_quotes_batch_cached` 内部 cold 路径用 `asyncio.gather` + `asyncio.to_thread` 把 yfinance fast_info 并发 fan-out（N 个 ticker 同时拉，不再串行循环 1.5s/ticker）。冷启动 hit-rate **4.80s → 0.007s**（warmup 后），warmup 自身 4 ticker ≈ 1.5-2s（旧串行 ~6s）
- **SEC 后台刷新** `_refresh_sec_holdings_background` 是显式 opt-in：`sec_holdings_auto_refresh` 默认关。用户开启后，lifespan 在 SEC identity 有效且 13F cache 超过 60 天时刷新最近完整季度；刷新以独立 `python -m scripts.refresh_sec_holdings` 子进程运行，不占 FastAPI event loop，shutdown 会终止刷新子进程；默认 identity 被 `_is_valid_identity` 拒绝时 app 正常启动但不注册 EdgarToolsProvider
- **聚合层** `engine/aggregations/` — 叶层纯函数（hit_rate_overview / recent_research）
- **compute 层** `engine/compute/`：
  - 估值：`dcf / ddm / lbo / comps / multiples / wacc / valuation_aggregator / valuation_synthesis`
  - 财务：`forward_estimates / historical_extractor / historical_valuation / extractor / data_processor`
  - 主题：`catalyst / sentiment / news / rag / earnings / industry / market`
  - 桌面增强：`monte_carlo / sniper / composite_score / spreadsheet_gen / signal / compare`
  - SEC：`ownership / xbrl_aligned_comps` 纯函数承接 Form 4 / 13F / DEF 14A / XBRL-aligned peer comps，所有 SEC 行保留 `FilingProvenance`
- **engine 其他子模块**（routes 不直接暴露但 pipeline / compute 内部依赖）：
  - `agents/` — pydantic-ai agent 工厂 + tool 定义
  - `analysis/` — pipeline 共用的 prompt 模板（`prompts.py`）+ 输出 schema
  - `backtest/` — backtrader adapter（IRR / 历史回测，可选依赖）
  - `notify/` — 桌面通知 / 邮件 hook（轻量 NotifyService）
  - `rag/` — RAG 索引层（rank_bm25 + corpus loader）
  - `services/` — 跨 pipeline 服务（QuoteCache / DataCache 共享 instance）
  - `skills/` — Markdown skill runtime（投行方法论文档加载）

  服务端渲染层（matplotlib `engine/charts/` + Jinja `engine/reports/` + legacy `engine/web/`）与 HTTP Excel 导出端点（`routes/export.py`）已退役。所有图表走前端 inline SVG，没有 server-rendered 图片或 PDF 出口。`engine/compute/spreadsheet_gen.py` 模块保留（openpyxl 写 formula cell）但当前无 HTTP/CLI 入口，若复活需先重新挂载 route。退役决策记录见 `project-memory/架构决策/砍服务端渲染遗产-2026-05-25.md`。

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
/stocks/:ticker/runs/:artifactId → ArtifactDetailPage（12 章长滚动 · sticky toolbar/TOC/right-rail + 底部 ReportStatusBar 显示章节进度 + 回顶）
/settings                      → SettingsPage
```

### Shell（`layout/`）

- `TitleBar` 44px：brand-dot logo + halo cmdK input + AI 助手按钮（Tauri overlay 三色控件）
- `Sidebar` 64px：极窄 icon-only，active 3px 蓝光竖条；点「个股」走 `navMemoryStore.lastStocksPath` 恢复最近一次的 deep path（持久化到 localStorage），⌘+click 强制回 landing
- `RightChatPanel/` 单一 AiChatTab：per-ticker 对话 AI，可拖拽宽度 + ⌘L 收起；suggestion chips 按路由细分（landing / workspace / artifact-detail / settings 各一套）
- `CmdKOverlay`：⌘K 全局，含 section 导航 panel
- `AppShell`：CursorCanvas（Bezier 12-spring 拖尾） + cosmic-stars 双层 drift 背景

### Cosmic 设计 token（`App.css`）

- 深空双轨：`--bg-void/deep/card/elevated` + `--primary/secondary/accent-cyan/accent-pink/accent-amber`
- 半透明 sticky 层：`--bg-sticky-{78,88,92}`（TitleBar / ReportToolbar / ReportStatusBar 三档透明度）
- 三轨字体：`--font-display` (Audiowide) + `--font-mono` (JetBrains Mono) + `--font-body` (Inter)
- 合法动效 keyframes：核心 cosmic-* 7 种（`cosmic-pull-up / morph / shimmer / halo / pulse-dot / pulse-ring / drift-slow + drift-fast`）+ 12 个功能动效（`progress-slide / fadeUp / skeleton-pulse / statusbar-pulse / toast-in / pipeline-done-pulse / check-pop / done-bar-in / ask-bounce / status-pulse / msgIn / blink`）。新加任何 @keyframes 前先 grep `App.css`，重复或类似就用现有的
- 工具类：`.cosmic-card` / `.cosmic-badge.cosmic-badge-{buy,hold,sell}` / `.btn-shimmer` / `.halo-input` / `.cosmic-group-header` / `.ai-icon-btn`

### LLM 叙事字段（ThesisResult）

- `tagline` — ≤ 60 字的可分享一句话结论
- `key_takeaways` — 3-5 条核心结论
- `valuation_overview` — 150-200 字 DCF/Comps/DDM 解读
- `competitor_analysis` — vs 同业 3-4 句叙事
- `news_summary` — 近 30 天新闻整体情绪 + 论点支撑/挑战
- `recommendation` — BUY / HOLD / SELL
- `catalysts` / `risks` — 数组
- `company_overview` — 200-300 字 Company Overview（business / segments / geography / moat 投行口吻）

artifact 路径：
- `outputs.llm_narrative.*` — 顶层 LLM 叙事镜像（`ArtifactOutputs.llm_narrative` 字段，由 equity_research builder 从 `structured.thesis` mirror-write）
- `outputs.structured.thesis.*` — 计算审计链源头，UI 当前读此路径，保持不变

surface 位置：`/stocks/:ticker/runs/:artifactId` 路由（ArtifactDetailPage）的 12 章节按字段映射渲染：
- `tagline` → 00 Cover 顶部 italic 引文
- `key_takeaways` + `recommendation` → 01 Investment Thesis takeaways list + verdict badge
- `company_overview` → 02 Company Overview narrative callout
- `valuation_overview` → 04 Valuation Analysis narrative callout
- `news_summary` → 05 Recent News & Events narrative callout
- `competitor_analysis` → 09 Competitive Landscape narrative callout

工作区 (`/stocks/:ticker`) 的 AIZone hot state 只显示 `headline` + `verdict` 大徽章 + `target_price` 作为入口卡，详情拉详情页看。

## 测试金字塔

- **1527 pytest pass** + 1 skipped + 10 deselected (`-m "not slow and not integration"`)（unit + routes + audit + artifact；`tests/unit/test_paths.py` 覆盖 paths 常量 + journal.db + sessions/ 迁移 / `test_sqlite_store.py` + `test_migrate.py` 覆盖 SQLite ArtifactStore + 文件系统→SQLite 迁移 / `test_quote_cache.py` 覆盖 L1+L2 quote cache / `test_quote_batch.py::test_cached_cold_path_fans_out_per_ticker_concurrently` 守护 yfinance per-ticker 并发不被回退到串行循环，`test_yfinance_rate_limit_is_isolated` 守护 YFRateLimit 不把 dashboard 打成 500 / `test_equity_research_pipeline.py` 覆盖 pipeline 8 步骤结构 + step executor + SEC required data + ownership_governance_analysis 链路 / `test_edgar_provider.py` 覆盖中文 SEC identity 到 ASCII header 的运行时转换 / `test_server.py::test_sec_holdings_refresh_not_inline_in_lifespan` 守护 13F refresh 不阻塞 sidecar readiness / `test_refresh_sec_holdings.py` 守护 13F schema drift 聚合 warning / `test_sec_holdings_cache.py` 覆盖 13F ticker 与 issuer name fallback / `test_ownership_compute.py` 覆盖 Form 4、13F、DEF 14A deterministic 解析 / `test_xbrl_aligned_comps.py` 覆盖 XBRL-aligned peer comps + NetIncomeLoss :annual/:ttm 双 key 不碰撞 / `tests/audit/test_sec_provenance.py` 覆盖 artifact SEC provenance contract + llm_narrative mirror-write / `test_notify_routes.py` 覆盖 8 个 channel test endpoint case / `test_growth_scale_override.py` 覆盖 What-if Editor revenue growth scaling）。实跑时间 `pytest -m "not slow and not integration" -q` ~10s。剩余 aiosqlite teardown warning 是已知 race（见 `project-memory/踩坑记录/aiosqlite-test-teardown-2026-05-27.md`，非致命）。
- **309 vitest pass** + 2 skipped（components + stores + hooks + i18n smoke + format helpers + errorMessage 映射 + API fetch timeout + `ChapterTechnical.test.tsx` + `useQuotesWarmed.test.tsx` + `WhatIfEditor.test.tsx` 守护 3 slider + side-by-side compare 行为；`StockWorkspace.test.tsx` 守护 422 才进入 ticker-not-found，yfinance 502/网络错误保持 workspace shell 可用，AI run 启动失败必须 toast 反馈）
- **Playwright e2e 待新建**：旧 2 个 spec (`v5-walkthrough` + `cosmic-research-flow`) 已删（依赖死 23-section 锚点 + StatBanner/HeroVerdict/FootballField testids）。新 e2e 应该覆盖 landing → workspace dual-zone (cold/running/hot) → ArtifactDetailPage 12-chapter (TOC scroll-spy + chapter mini-grid #anchor jump + Diff modal) 路径

## UI 设计规范强制（桌面 App）

**任何 UI 改动（新组件 / 新页面 / 调样式 / 改 ui/）必须先读：**
`project-memory/编码模式/UI-风格规范-cosmic桌面版.md`

规范定性：**Cosmic Desktop · 太空仪表盘桌面版**（Tauri 桌面 App，非网页）

- 配色：deep space dark `#05050d/0a0a18` + 蓝紫双轨霓虹 `#3B82F6/8B5CF6` + cyan live 信号 `#22D3EE`
- 字体三轨：Audiowide 标题 + JetBrains Mono 数字 + Inter body
- 桌面专属：macOS 窗口控件 + 64px slim sidebar + 自定义 Canvas 拖尾鼠标 + Spline 3D 机器人嵌入
- 动效白名单：核心 cosmic-* 7 种 + 12 个功能动效（progress-slide / fadeUp / skeleton-pulse / statusbar-pulse / toast-in / pipeline-done-pulse / check-pop / done-bar-in / ask-bounce / status-pulse / msgIn / blink）
- 涨绿跌红（美股惯例，非 A 股）
- 样板：`stock-workspace-design-demo.html`（cosmic token 全实例 demo）

禁忌：不用纯黑、不引新主色、不用 Audiowide 写 < 16px 小字、不引入外部图表库（inline SVG）、不做 < 1200px 响应式（桌面 App 只跑桌面）。

## 12 章研报地图（阶段 1 目标）

`/stocks/:ticker/runs/:artifactId` 路由按 12 章顺序长滚动呈现：

1. **Cover** — ticker / 公司名 / verdict 大徽章 / 目标价 / 报告日期（新增 · P3）
2. **Investment Thesis** — tagline + recommendation + key_takeaways（已有，UI 重排）
3. **Company Overview** — `company_overview` LLM 字段（已有）
4. **Financial Analysis** — 历史财务 + 3 年 forecast（compute 层有，UI 重组）
5. **Valuation Analysis** — Football Field + 4 估值方法明细 + valuation_overview（已有）
6. **Recent News & Events** — NewsTimeline + news_summary（已有）
7. **Sensitivity Analysis** — SensitivityHeatmap + 假设说明（已有）
8. **Key Catalysts** — CatalystGrid 三段：Positive / Risks / Events to Monitor（已有）
9. **Technical & Advanced Analysis** — pipeline `technical_analysis` step 把蒙特卡洛 (10K antithetic sims) + 狙击位 + 历史 EV/EBITDA 估值带烘进 artifact (`structured.technical_analysis`)，章节按子区块 inline SVG 渲染（histogram / KvGrid / band timeline），旧 artifact 无字段时 cold state
10. **Competitive Landscape** — Peers 3 视图 + competitor_analysis（已有）
11. **Financial Data** — DataSnapshot + 5 财报表 + 财报电话会（已有）
12. **Disclaimer** — 投资免责声明（新增 · P3）

`/stocks/:ticker`（StockWorkspace）保持 dashboard 形态：实时行情 + 跑 AI 入口 + artifact timeline 跳转，不承担研报阅读。

## 多语言（i18n）

- **库**：LinguiJS 6.x（@lingui/core + @lingui/react + @lingui/cli + @lingui/format-po）
- **catalog**：`ui/src/i18n/locales/{zh,en}/messages.po` 是源；`messages.mjs` 是 `lingui compile` 产物（gitignored）
- **默认语言**：zh 优先 · 三段探测 localStorage → `@tauri-apps/plugin-os::locale()` → `'zh'` fallback
- **设置切换**：Settings 页 dropdown 立即生效（无重启），持久化到 `finrobot-ui-prefs` localStorage
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
- **mypy strict 全绿** — `pyproject.toml` 用 `strict = true`，CI 跑 `mypy finrobot/ --strict`，本地 `uv run mypy finrobot/` 必须 0 error。`backtrader_adapter` 单独 override `disallow_subclassing_any = false`（Strategy 是 Any 的外部库）
- **前端 lint 真生效** — `ui/eslint.config.js` ESLint 9 flat config；CI desktop job pin `ui/`（不是历史 `desktop/`），跑 `npm run lint + format:check + test + build` 四件套；`@typescript-eslint/no-explicit-any: error` 禁裸 any
- **pydantic-ai 1.7x API 写前必查** https://ai.pydantic.dev/（`feedback_pydantic_ai_api`）
- **UI 文案 i18n** — 用户可见字符串走 `useI18n().t('key')` 或 catalog；不在 JSX 硬编码英文；不暴露 `backend / server / sidecar / HTTP / artifact / run_id` 等内部术语
- **不要 band-aid 修法 / 不留 dead code / 不留假按钮 / 不写死 fallback**
- **AGENTS.md 是当下 state 文档** — 写"是什么"，不写"曾经是什么 / 改自什么"。退役内容直接删，commit 记录就是历史
