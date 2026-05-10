# FinAgent Product Insights

---

## 研究日期: 2026-05-10 (Round 1)

### 竞品发现

#### Tier 1 — 直接竞品（AI + 金融分析）

- **Calypso (calypsocopilot.com)**: Earnings call 专精，2-5 分钟内处理转录稿，输出结构化 bull/bear debate cards + 情绪追踪。覆盖 400+ 上市公司。 → FinAgent 可借鉴: 结构化 bull/bear 框架比自由文本更有说服力；earnings analysis 应该输出对比表而不是段落文字。

- **FinChat/Fiscal.ai**: 对话式金融数据平台，20 年财务数据 + KPI 追踪 + 可视化对比。从 FinChat 改名 Fiscal.ai 反映了从"聊天机器人"到"研究平台"的定位升级。 → FinAgent 可借鉴: 自然语言查询界面不是核心竞争力（ChatGPT 已占据），但结构化数据展示 + 交互式探索是刚需。

- **AlphaSense**: 企业级市场情报平台，10,000+ 高级数据源，AI Smart Summaries，sentiment 分析，4,500+ 预建金融模型，Excel 插件。据报告可削减 40% 专家网络支出。 → FinAgent 可借鉴: 多源数据聚合 + 情绪变化追踪是机构用户最看重的。但 AlphaSense 定价高（企业级），个人/小基金买不起，这是 FinAgent 的机会。

#### Tier 2 — 平台级竞品

- **OpenBB (open-source)**: 最接近的开源竞品。模块化数据平台，连接近 100 个数据源，支持 Python/Excel/REST API/MCP Server。定位是"连接一次，到处使用"的数据基础设施。 → FinAgent 差异化: OpenBB 是数据层，不做分析判断。FinAgent 的核心价值是"数据 + 确定性计算 + LLM 分析判断"的完整链条。OpenBB 用户仍需自己写分析逻辑。

- **Koyfin**: 免费/低价 Bloomberg 替代，以高质量可视化和 watchlist 著称。用户称赞 UX 直觉性，但也指出学习曲线陡峭、功能过多导致初学者 overwhelmed。 → FinAgent 可借鉴: progressive disclosure — 别一上来就铺 50 个功能，先让用户完成一次完整分析流程，再解锁高级功能。

- **Bloomberg Terminal ($20-25K/yr)**: 行业标准，不可能在数据覆盖上竞争。但 Bloomberg 的 UX 停留在 90 年代。 → FinAgent 机会: 不和 Bloomberg 比数据量，比分析效率和 UX。一个专注于 equity research 的精品工具。

#### Tier 3 — 工具级竞品

- **DCF Model Builder Pro / Alpha Spread**: 免费在线 DCF 计算器，交互式假设调整。 → FinAgent 已有 AssumptionsEditor + SensitivityHeatmap，UX 更好。优势在于 DCF 不是孤立工具而是完整分析流程的一部分。

- **V7 Go DCF Modeling Agent**: AI 代理自动读 10-K 填充 Excel DCF 模板。 → FinAgent 的 SEC RAG + DCF pipeline 本质上做同样的事，但更可控（确定性计算层，LLM 只负责假设，不负责计算）。

### 用户痛点

1. **LLM 数字不可信 — "the $1.2B vs $1.3B problem"**
   分析师最大的恐惧：LLM 在金融语境下 hallucination 率极高。零样本准确率仅 48.9%。LLM 会在缺数据时"interpolate"（用 Q1+Q3 平均估 Q2），这不是 earnings 的工作方式。
   → FinAgent 核心优势: 确定性计算层（WACC/DCF/multiples 由代码计算，不由 LLM 计算）+ 数据源标注 + 交叉校验。**这是最值得强调的差异化。**

2. **AI 让分析师变懒 — "fill in the blanks" 危险**
   当公司不报告某指标时，AI 工具会自信地"填补"，导致 dangerous confidence。更糟的是大多数工具不强制标注引用来源。
   → FinAgent 应做: 缺失数据时明确标注 "N/A — not reported"，而不是让 LLM 猜测。WarningBanner 已有基础，需要更细粒度的数据来源追踪。

3. **工具碎片化 — "no all-in-one solution"**
   89% PM 将 AI 视为生产力工具而非替代品。但需要 2-3 个工具协同（earnings 用 Calypso，数据用 Koyfin，搜索用 AlphaSense）。
   → FinAgent 机会: 一个工具完成 ticker 输入 → 数据收集 → 分析 → 估值 → 报告 的完整流程。Desktop 是天然优势（离线、快速、集成）。

4. **手动流程耗时**
   Equity research 团队花大量时间在 repetitive tasks: 格式化报告、更新 comps 表、提取 footnotes。
   → FinAgent 的 pipeline automation + Excel/PDF export 直接解决。但需要让这些自动化过程可见、可审计。

5. **Forecast 的主观性**
   估值假设（discount rate、terminal growth）本质上主观。工具要做的不是"给一个答案"，而是"让用户快速探索假设空间"。
   → FinAgent 的 AssumptionsEditor + SensitivityHeatmap 正好对应。但需要增加 scenario comparison（bull/base/bear 一键切换）。

### 设计灵感

1. **Dark Mode 设计原则（金融仪表盘专用）**
   - 避免纯黑背景 (#000) + 纯白文字 (#FFF)，用深灰/深蓝 + off-white（FinAgent 已正确: base #0B0E14, text #E8ECF4）
   - 亮色只用于关键指标高亮（涨绿/跌红 + 品牌金色），不做装饰用（FinAgent 已正确）
   - 对比度要足够但不刺眼，长时间观看 dashboard 时尤为重要
   → FinAgent 设计系统方向正确，"Bloomberg meets Linear" 定位精准。

2. **Data Dense UI — 密度不等于拥挤**
   - 4px grid spacing（而非 16-24px 的消费品间距）→ FinAgent 已用 4px 倍数系统
   - Tables > Cards 对于结构化数据（FinAgent 的 FinancialsPanel 用的是 table，正确）
   - Sortable columns + sticky headers + 可自定义列显隐（FinAgent 还没做）
   - Progressive disclosure: 先展示高层概要，用户点击展开详情（FinAgent 部分实现）
   → 适合 FinAgent: 金融用户是 power users，偏好高信息密度。不要做消费品 app 的大留白。

3. **专业金融 UI 模式**
   - 等宽字体对齐所有数字（FinAgent 已做: JetBrains Mono）
   - 数字右对齐，标签左对齐（FinAgent 的 fin-table 已遵循）
   - 涨跌用 pill badge（背景色 + 文字色），不只改文字颜色（FinAgent 已做）
   - 图表与卡片融合（透明背景），不单独加底色（FinAgent 已做）
   → FinAgent 的设计系统在专业感上已经超过大多数开源项目。继续保持。

4. **Linear.app 的 UX 影响**
   - 极致的键盘导航（Cmd+K 命令面板）
   - 微妙的动画反馈（0.15s transitions）
   - 最小化的 chrome — 内容占满视口
   → FinAgent Desktop 缺: 键盘快捷键、命令面板、快速切换 ticker 的能力。这些是"专业工具感"的关键指标。

### FinRobot 功能差距（必须填）

#### 后端已有，Desktop 未暴露的功能

| FinRobot 功能 | FinAgent 后端 | Desktop 状态 | 差什么 |
|--------------|-------------|-------------|--------|
| LBO 分析 | ✅ `pipelines/lbo.py` + `compute/lbo.py` | ❌ 未暴露 | 需要 LBO 结果展示组件 + pipeline 选项 |
| IC Memo | ✅ `pipelines/ic_memo.py` | ❌ 未暴露 | 需要 IC Memo 展示视图 |
| Earnings Analysis | ✅ `pipelines/earnings_analysis.py` | ❌ 未暴露 | 需要 Earnings 视图（beat/miss 可视化） |
| SEC 10-K RAG Q&A | ✅ BM25Index + SEC provider | ❌ 未暴露 | 需要问答界面（ticker + question → answer） |
| Backtest | ✅ BackTrader adapter + CLI | ❌ 未暴露 | 需要回测配置 + 结果展示视图 |
| Excel 导出 | ✅ `/api/export/excel/` | ✅ ExportBar 有按钮 | 功能连通 |
| Analyze (6 种类型) | ✅ CLI `finagent analyze` | ❌ 未暴露 | 需要独立分析面板 |

#### FinRobot 有但 FinAgent 整体缺失的功能

| 功能 | FinRobot 位置 | FinAgent 状态 |
|------|-------------|-------------|
| Retail Sentiment (Reddit/X/Polymarket) | `retail_sentiment_client.py` — 汇总多源情绪数据 | ❌ 完全缺失。后端没有 Reddit/Polymarket 数据源。equity_research pipeline 有 sentiment 字段但来自 LLM 分析，不是社交媒体抓取。 |
| EV/EBITDA Band 图表 | `enhanced_chart_generator.py` — 历史 EV/EBITDA 倍数 band 图 | ❌ Desktop 无对应组件。后端 charts.py 可能有 matplotlib 版本但未在 recharts 实现。 |
| P/FCF Band 图表 | `enhanced_chart_generator.py` — 历史 P/FCF band 图 | ❌ 同上 |
| Revenue YoY 图表 | `enhanced_chart_generator.py` — 同比增长率柱状图 | ❌ Desktop 的 RevenueEbitdaChart 只有绝对值，没有 YoY% |
| SGA Ratio 图表 | `enhanced_chart_generator.py` — SGA/Revenue 比率趋势 | ❌ 无对应 |
| LTM EBITDA Margin 图表 | `enhanced_chart_generator.py` — TTM EBITDA margin 趋势 | ❌ 无对应（MarginTrendChart 可能部分覆盖） |
| Relative Performance 图表 | `enhanced_chart_generator.py` — 相对基准的超额收益 | ❌ 无对应 |
| Technical Indicators 图表 | `chart_generator.py` — SMA/RSI/MACD 技术指标可视化 | ❌ 无对应（FinAgent 定位非交易工具，优先级低） |
| Cash Flow 图表 | `chart_generator.py` — Operating/Investing/Financing 三段现金流 | ❌ 无对应（有价值，应做） |
| Quarterly Comparison 图表 | `chart_generator.py` — 季度同比对比 | ❌ 无对应 |
| 7 类新闻分类 + 5 级重要性评分 | `news_integrator.py` — earnings/product/management/regulatory/market/acquisition/financial | ⚠️ FinAgent 有 catalyst analysis 但无独立新闻分类 UI |
| 用户认证系统 | `web_app/auth.py` + `database/` | ❌ Desktop 不需要（单用户），但 Web 版需要 |
| 并行 Dashboard | `parallel_dashboard.html` — 多任务并行执行 | ❌ Desktop 一次只能分析一个 ticker |

### Desktop UI 当前缺陷（直接影响专业感）

1. **只有 3 个 pipeline 可选**（Research/DCF/Comps），后端有 7 个 pipeline
2. **无键盘快捷键** — 专业工具必备（Cmd+K 搜索 ticker，Cmd+R 运行分析，Tab 切换面板）
3. **无 ticker 搜索/自动补全** — TickerInput 是纯文本框，应该有模糊搜索 + 公司名联想
4. **无 scenario management** — 不能保存/对比 bull/base/bear 假设
5. **无图表交互** — 图表不能 zoom/pan/tooltip click-through
6. **无 loading skeleton** — 数据加载时无骨架屏，UI 跳动
7. **左右双栏不可调整** — 左栏固定 340px，不能拖拽调整
8. **无多 ticker 对比** — 一次只能看一个公司
9. **ResearchSummary 是纯文本** — 应该用结构化卡片展示各 agent 的分析结果

### 下一步行动建议（按优先级）

1. **暴露后端已有的 5 个 pipeline 到 Desktop** — 理由: 零后端开发成本，纯前端工作。LBO/Earnings/IC Memo/RAG/Backtest 后端已完成并测试通过，只需要 UI 展示层。这是最高 ROI 的工作——立即让功能覆盖从 43% 提升到 100%。

2. **增加命令面板 + 键盘快捷键 (Cmd+K)** — 理由: 这是"专业工具"和"demo 项目"的分水岭。Bloomberg/Linear/Raycast 用户的肌肉记忆。实现成本低（一个 overlay + 键盘监听），但体验提升巨大。ticker 搜索也可以整合进去。

3. **ResearchSummary 结构化升级** — 理由: equity research 是使用频率最高的 pipeline。当前 ResearchSummary 是大段文本，应该拆成: Tagline 卡片 + Company Overview + Investment Thesis (bull/bear) + Valuation Summary + Risks + Catalysts + News。每个 section 有折叠/展开，有数据引用标注。这才是"10 倍体验提升"的核心。

4. **Retail Sentiment 数据源 + UI** — 理由: FinRobot 有、FinAgent 没有的最大功能差距。FinRobot 通过 Adanos API 聚合 Reddit/X/Polymarket 情绪数据。需要后端 + 前端同时做。

5. **图表交互增强 + 新增 4 种图表** — 理由: 增加 EV/EBITDA Band、P/FCF Band、Revenue YoY%、Relative Performance 图表。同时给现有图表加 tooltip 点击详情和时间段切换。

6. **Scenario Manager (bull/base/bear)** — 理由: DCF 的核心价值不是"给一个数字"，而是"探索假设空间"。一键切换 3 种情景 + 并排对比 + 保存/导出，这是 DCF 用户的刚需。

### QuantDinger UX 模式借鉴

QuantDinger 是一个成熟的量化交易平台（Vue 3 + Ant Design Pro + Flask + PostgreSQL + Redis），以下模式值得 FinAgent 参考:

1. **闭环工作流可视化**: Research → Build → Validate → Operate → Monitor，每个阶段在 UI 中有明确的位置和状态。FinAgent 等价的流程是: 输入 Ticker → 获取数据 → 运行分析 → 调整假设 → 导出报告。当前 UI 没有让这个流程"可见"——用户不知道自己在哪一步。

2. **MCP Agent Gateway**: AI agents（Claude Code/Cursor）可以通过标准化接口直接调用平台功能，无需 UI。FinAgent BACKLOG 已有此项，优先级可提升——让 Claude Code 直接调 `finagent.research("AAPL")` 是一个强力 demo。

3. **参数可调 UI（无需写代码）**: QuantDinger 的策略参数通过 `@param` 注释声明，UI 自动生成调节控件。FinAgent 的 AssumptionsEditor 已做了类似的事（DCF 假设滑块），可以扩展到其他 pipeline 的参数（如 LBO 的 entry multiple、holding period 等）。

4. **优雅降级**: 单个数据源 API 失败不会打挂整个 dashboard。FinAgent 的 DataLayer 有 fallback 链，但 UI 层还没有"部分数据可用"的状态提示。

5. **Docker Compose 一键部署**: `docker-compose up` 启动全栈。FinAgent 还没有 Docker 化，这对开源项目的采纳率至关重要。

6. **多语言支持**: QuantDinger 支持 8 种语言。FinAgent 暂不需要，但作为面向全球金融从业者的工具，i18n 架构应尽早预埋。

### 关键洞察总结

**FinAgent 的核心护城河不是 LLM，而是确定性计算层。** 市场上最大的不满是"LLM 数字不可信"。FinAgent 的 WACC/DCF/multiples 由代码计算、LLM 只负责叙事分析的架构，正好解决这个痛点。产品叙事应该是: "数字有保证，判断有 AI"。

**Desktop 的后端功能覆盖率远超 UI 暴露率。** 后端有 7 个 pipeline、9 种图表、Excel/PDF/HTML 导出、回测、RAG，但 Desktop 只暴露了 3 个 pipeline + 9 种图表。最大的提升来自"让已有功能可见"，不是造新功能。

**设计系统方向正确但 UI 缺乏专业工具的"厚度"。** 色彩/字体/间距都对，但缺少键盘操作、命令面板、多 ticker 对比、scenario management 等 power user 功能。这些是 Koyfin/Bloomberg 用户的基本期待。

---

## 研究日期: 2026-05-10 (Round 6 — 深度竞品 + 量化数据 + UI 架构)

> 本轮重点: 量化的 LLM 可信度数据、分析师时间分配数据、数据密集型 UI 设计规范、Desktop 进展盘点。

### 竞品发现（Round 1 增量）

#### AI 研究工具定价与定位矩阵（2026 最新）

| 工具 | 定价 | 核心能力 | 目标用户 | FinAgent 对标关系 |
|------|------|---------|---------|-----------------|
| **Calypso** | $20/月 | Earnings call 专精，bull/bear cards，实时转录处理 | PM 管理 40+ earnings | FinAgent earnings pipeline 功能对标，但缺 bull/bear debate cards 格式 |
| **Koyfin** | $39/月起 (G2 2026 Winter 金融分析 #1) | 可视化 + screening + watchlist，drag-and-drop dashboard | 个人投资者 → 小基金 | FinAgent 的直接竞品定位——同样 affordable，但 FinAgent 加了 AI 分析层 |
| **FinChat/Fiscal.ai** | $30/月起 | 对话式金融数据 + 自动图表生成 + KPI 追踪 | 独立分析师 | FinAgent 不走对话路线，但可借鉴 KPI 追踪和自动图表 |
| **AlphaSense** | $10K-15K/年 | 文档搜索 + sentiment 追踪 + expert transcripts | 机构研究团队 | FinAgent 不竞争，但 SEC RAG 能力部分覆盖 |
| **Tegus** | $15K-30K/年 | 60,000+ expert interview transcripts | 基本面深度研究 | 完全不同赛道，不竞争 |
| **Visible Alpha** | 企业定价 | 段级别/KPI 级别 consensus estimates | 建模团队 | FinAgent 的 forecast 功能可参考其颗粒度 |

**关键发现:** 行业共识是"2-3 工具组合"而非 all-in-one。推荐 stack: Calypso(earnings) + Koyfin/Bloomberg(data) + AlphaSense(docs) = $60-$25K/月。**FinAgent 的机会是以 $0（开源）覆盖 Calypso + Koyfin 的核心功能。**

#### Bloomberg 替代品的"现代金融数据栈"概念

BlueGamma 提出"pick and mix"策略：不再追求一个终端覆盖所有，而是组装专业化平台。核心观察：
- Bloomberg 每年 $20-25K，70% 功能用户从未使用
- 现代替代路径：专业数据($500/月 BlueGamma) + 新闻($207/季 Financial Juice) + 通讯($4800/年 Symphony)
- **FinAgent 定位启示**: 不做"Bloomberg 替代"，做"equity research 效率工具"——专注一个垂直场景，做到最好

### 用户痛点（Round 1 增量 — 含量化数据）

#### 痛点 1: 分析师时间分配的残酷现实

Marvin Labs 2026 报告提供了量化数据：
- **60 小时/周** = 典型分析师工作量
- **24 小时/周 (40%)** 花在手动数据收集、文档阅读、例行分析
- **15 小时/周** 仅文档分析一项
- **AI 工具可将文档分析从 15 → 7.5 小时** (50% 减少)

时间分配明细:
| 任务 | 小时/周 | AI 可省 |
|------|---------|---------|
| 文档分析 | 15 | 50% → 7.5h |
| 沟通协调 | 20 | 低 |
| 财务建模 | 10 | 30%（假设输入可自动化） |
| 创意/判断 | 8 | 0%（不应自动化） |
| 报告撰写 | 7 | 60%（模板化部分） |

→ **FinAgent 最大价值点: 文档分析(SEC RAG) + 报告撰写(pipeline automation) + 财务建模(DCF/LBO 预填) = 每周可省 ~15 小时**

#### 痛点 2: 覆盖扩张压力

- 2000 年代: 每团队覆盖 30-40 家公司
- 2026 年: 每团队覆盖 **50-60+ 家公司**（MiFID II 预算削减 + 人员缩减）
- Earnings season: 2-3 周内分析 20-30 家公司的财报
- 10-K 文件从 80-100 页膨胀到 **150-200+ 页**

→ **FinAgent 产品叙事: "一个分析师用 FinAgent 的效率 = 三个分析师手动工作"**

#### 痛点 3: 分析师真正需要什么

不是更多功能，而是:
1. **Source verification** — 每个数字都能追溯到原始文件段落
2. **Workflow integration** — 不需要切换平台，在一个工具内完成全流程
3. **Compliance consistency** — 输出可审计，格式合规，不会因为 AI 漂移
4. **Strategic thinking time** — 工具解放机械劳动，让分析师花时间在判断上

→ FinAgent 的"确定性计算层 + LLM 叙事"架构天然满足 #1 和 #3。但 **source verification UI（数据来源标注、数字可点击追溯到 API response）还没做**。

### LLM 可信度 — 量化数据（新发现，非常重要）

#### JurisTech 2026 Hallucination Benchmark

用 AirAsia 季报（故意删除 P&L 部分）测试 6 个模型的"幻觉抵抗力"：

| 模型 | 得分 | 行为 |
|------|------|------|
| GPT-5.4 | 92/100 | 拒绝编造，找到替代数据源（附注），明确标注替代 |
| Claude Opus 4.6 | 78/100 | 承认数据缺失但默认外推，标注为"估算" |
| Kimi K2.5 | 71/100 | 同上 |
| Gemini 3.1 Pro | 54/100 | **自信地编造 P&L 主要项目**，无任何标注 |
| Qwen 3.6-Plus | 38/100 | 编造财务数字 + 发明不存在的管理层姓名 |
| GLM-5.1 | 29/100 | 混淆全年/季度数据，所有衍生比率内部矛盾 |

**关键发现:**
- "输出的格式质量与事实准确性几乎完全不相关" — 最差的模型产出最漂亮的表格
- 4/6 模型在数据不完整时会编造数字，其中 2 个自信且无披露
- 37 个模型跨基准测试: 幻觉率 **15% - 52%**
- 行业因幻觉造成的年损失超 **$250M**
- RAG 架构可减少 **35-60%** 错误率

→ **FinAgent 的产品宣言应该是: "FinAgent 的数字来自代码计算和 API 数据，不来自 LLM 猜测。"** 这不是一个技术细节，这是核心产品卖点。建议在 Desktop UI 中**每个数字旁标注来源标签**（`[FMP]` `[Calculated]` `[LLM]`），让用户一眼区分。

### 设计灵感（Round 1 增量 — 含具体 CSS 规范）

#### Data Dense UI 设计规范（Paul Wallas, Medium 2026）

**间距压缩纪律:**
- 不是"去掉留白"，而是"压缩留白，保持一致"
- 4px grid（不是 8px），按钮高度 32-36px（不是 44-48px）
- 14px body / 12px labels / 16px headers（不是 16/14/20）

**字体权重限制:**
- 只用 3 种: Regular / Medium / Bold
- 滥用 weight 等于没有 hierarchy

**颜色规则:**
- 只用 2 种文字颜色: primary(活跃内容) + muted(辅助文字)
- 亮色只用于 accent（品牌色/涨跌/警告），最多 2-3 个

**表格设计:**
- Sortable columns（必备）
- Sticky headers + sticky first column
- 人类友好日期: "12 Jun 2025" 而非 "2025-06-12T00:00:00Z"
- 用户可保存列配置

→ **FinAgent 当前状态对照:**
- ✅ 4px 倍数 grid（但按钮可能偏大）
- ✅ JetBrains Mono 数字等宽
- ⚠️ FinancialsPanel 没有 sortable columns
- ❌ 没有 sticky headers
- ❌ 没有用户可配置的列显隐
- ❌ 日期格式不够友好（需检查）

#### 交易界面色彩优化（HRT + Ron Design Lab）

- 传统的亮绿 (#00ff00) 和亮红 (#ff0000) 在长时间盯盘时造成眼睛疲劳
- **降低饱和度 18%** → 用户测试显示 **23% 更长的观看时间**
- 推荐: 绿 → #34D399（FinAgent 已用 ✅），红 → #F87171（FinAgent 已用 ✅）

#### 对比度标准（金融仪表盘专用）

- 文字 vs 背景: 最低 **4.5:1**（WCAG AA）
- 关键数据（价格、涨跌幅）: 最低 **7:1**（WCAG AAA）
- FinAgent 的 #E8ECF4 on #0B0E14 = 约 **13:1** ✅ 优秀

### FinRobot 功能差距（Round 6 更新 — 含进展盘点）

#### 进展: Round 1 → Round 6 变化

自 Round 1 以来，Desktop 新增了 5 个重大功能（git log 确认）:
| 新增 | Commit | 状态 |
|------|--------|------|
| Command Palette (⌘K) | `5b9e666` | ✅ 已完成 |
| Research pipeline + ResearchSummary | `ff94f04` + `0adf44a` | ✅ 已完成（含 thesis narrative + expandable lists） |
| Comps pipeline + CompsSummary | `97492fa` | ✅ 已完成 |
| Earnings pipeline + EarningsSummary | `0be4db4` | ✅ 已完成 |
| LBO pipeline + LBOSummary | `737b287` | ✅ 已完成 |

**Pipeline 暴露率从 Round 1 的 43% (3/7) 提升到 71% (5/7)。** 剩余:

#### 仍未暴露的后端功能

| 功能 | 后端状态 | Desktop 状态 | 优先级 |
|------|---------|-------------|--------|
| IC Memo | ✅ `pipelines/ic_memo.py` | ❌ 未暴露 | 中 — 需要组合 DCF+LBO 结果 |
| SEC 10-K RAG Q&A | ✅ BM25Index + EmbeddingIndex | ❌ 未暴露 | **高** — 分析师排名第一的时间消耗（15h/周文档分析） |
| Backtest | ✅ BackTrader adapter | ❌ 未暴露 | 低 — FinAgent 定位非交易工具 |
| Analyze (6 种) | ✅ CLI `finagent analyze` | ❌ 未暴露 | 中 — 独立分析类型（income/balance/cashflow/segment/ratios/forecast） |

#### Desktop 存在但从未显示的组件（新发现）

代码探索发现 4 个图表组件已导入但**从未被使用**:
| 组件 | 文件 | 问题 |
|------|------|------|
| `PriceChart` | `charts/PriceChart.tsx` | 已导入 TickerWorkspace 但**没有任何 view 渲染它** |
| `EpsPeChart` | `charts/EpsPeChart.tsx` | 同上 — 无 chart adapter 提供数据 |
| `CompanyRadarChart` | `charts/CompanyRadarChart.tsx` | 同上 |
| `FootballField` | `charts/FootballField.tsx` | 同上 — 无 adapter function |

→ **4 个图表已写好但白费了，需要连线到 summary views。** 最有价值的是 PriceChart（equity research 报告必备）和 FootballField（估值范围可视化，高端感标志）。

#### FinRobot 图表全清单 vs FinAgent 对照（精确比对）

FinRobot 共 23 种图表（基础 13 + 增强 10），FinAgent Desktop 9 种。

| FinRobot 图表 | FinAgent Desktop | 差距分析 |
|--------------|-----------------|---------|
| revenue_ebitda ✅ | RevenueEbitdaChart ✅ | 对齐 |
| margin_trend ✅ | MarginTrendChart ✅ | 对齐 |
| peer_comparison ✅ | PeerComparisonChart ✅ | 对齐 |
| sensitivity_heatmap ✅ | SensitivityHeatmap ✅ | 对齐 |
| waterfall ✅ | WaterfallChart ✅ | 对齐 |
| stock_price ✅ | PriceChart ✅ **但未显示** | 需连线 |
| eps_pe ✅ | EpsPeChart ✅ **但未显示** | 需连线 |
| radar ✅ | CompanyRadarChart ✅ **但未显示** | 需连线 |
| football_field ✅ | FootballField ✅ **但未显示** | 需连线 |
| revenue_yoy ✅ | ❌ 缺失 | 需新建 |
| ev_ebitda_band ✅ | ❌ 缺失 | 需新建（高价值 — 机构报告标配） |
| p_fcf_band ✅ | ❌ 缺失 | 需新建 |
| sga_ratio ✅ | ❌ 缺失 | 低优先 |
| ltm_ebitda_margin ✅ | ❌ 可能被 MarginTrendChart 覆盖 | 检查 |
| relative_performance ✅ | ❌ 缺失 | 中优先（vs benchmark 超额收益） |
| technical_indicators ✅ | ❌ 缺失 | 低优先（非交易工具定位） |
| cash_flow ✅ | ❌ 缺失 | **高优先** — 现金流三段图是基本面分析标配 |
| quarterly_comparison ✅ | ❌ 缺失 | 中优先 |
| revenue_breakdown_pie ✅ | ❌ 缺失 | 中优先（segment 分析依赖） |
| gross_margin ✅ | ⚠️ MarginTrendChart 可能覆盖 | 检查 |
| ebitda_margin ✅ | ⚠️ 同上 | 检查 |
| time_series (通用) ✅ | ❌ 缺失 | 低优先（通用图表，按需加） |

**总结: 9/23 已实现，4/23 已实现但未显示，10/23 缺失。优先补: 连线 4 个已有组件 + 新建 cash_flow + ev_ebitda_band + revenue_yoy = 16/23。**

### QuantDinger UX 模式深度借鉴（Round 6 补充）

#### 1. KPI Dashboard 卡片模式
QuantDinger Dashboard 顶部 6 个 metric cards:
- 主指标（大字号）+ 趋势方向（箭头/颜色）+ 辅助数字（小字号）
- 如: Total Equity `$125,340` ↑ `+$2,150 today`

→ **FinAgent 应在 data_ready 阶段展示类似的 KPI 卡片行**: Market Cap / P/E / EV/EBITDA / Revenue Growth / EBITDA Margin / Price vs Target。当前 FinancialsPanel 是表格，缺少"一眼看全局"的 summary cards。

#### 2. Agent Roster 可视化
QuantDinger 的 AI Analysis 展示 6 个 agent 角色卡片: Investment Director, Risk Manager, Safe Analyst, Neutral Analyst, Risky Analyst, Trader Agent。

→ **FinAgent 的 PipelineRunner 展示 step 进度，但没有展示"哪个 sub-agent 在工作"。** 可以在 step 名称旁显示 agent 角色图标（data_agent / analysis_agent / modeling_agent / synthesis_agent / report_agent），增加透明感和专业感。用户应该知道"谁在做这一步"。

#### 3. Dual-Tab 模式
QuantDinger: Positions | Trading Records 并排 tab，同层级快速切换。

→ **FinAgent 的 right panel 应该支持 tab 切换**: Summary | Charts | Raw Data。当前所有内容堆在一个滚动区域，charts 在 summary 下方，需要滚动很远才能看到。Tab 切换更高效。

#### 4. 参数声明式 UI
QuantDinger 的 `@param` 注释自动生成 UI 控件。

→ **FinAgent 的 AssumptionsEditor 只在 DCF mode 显示。LBO 有 entry_multiple/holding_period/exit_multiple 等参数但没有 UI 调节。** 应该对每个 pipeline 暴露可调参数 — LBO 的 leverage ratio、IC Memo 的 IRR hurdle rate 等。

#### 5. 错误消息友好化
QuantDinger 用正则匹配将技术错误映射为用户语言:
- "Insufficient balance" → `quickTrade.errorHints.insufficientBalance`（有 i18n key）
- Rate limit → 显示冷却倒计时
- Auth error → 建议刷新凭据

→ **FinAgent 的 API 错误当前直接显示 Python traceback 或 HTTP status code。** 应该建立错误消息映射: "FMP API rate limit exceeded" → "数据请求过于频繁，请等待 60 秒后重试" 等。

### 产品定位洞察（Round 6 综合）

#### FinAgent 的最佳市场位置

基于 Round 1 + Round 6 的全部研究，FinAgent 的最佳定位是:

**"开源的 Koyfin + Calypso 替代品，核心差异是确定性计算。"**

- **vs Koyfin ($39/月)**: FinAgent 免费开源，加了 AI 分析层（Koyfin 没有）
- **vs Calypso ($20/月)**: FinAgent 覆盖更广（不止 earnings），开源可自定义
- **vs OpenBB (开源)**: FinAgent 提供完整分析链条（OpenBB 只提供数据层）
- **vs ChatGPT/Claude**: FinAgent 的数字来自代码计算，不来自 LLM

**一句话 elevator pitch**: "FinAgent: AI-powered equity research where every number is verifiable — open source, free forever."

#### 功能优先级矩阵（影响 × 成本）

| 功能 | 用户影响 | 开发成本 | ROI | 建议 |
|------|---------|---------|-----|------|
| 连线 4 个已有但未显示的图表 | 中 | 极低（写 adapter + 放入 view） | ★★★★★ | 立即做 |
| SEC RAG Q&A UI | 高（省 7.5h/周） | 中（需要 chat-like interface） | ★★★★☆ | 高优先 |
| 数据来源标签 ([FMP] [Calculated] [LLM]) | 高（信任基础） | 低 | ★★★★☆ | 高优先 |
| Right panel tab 切换 (Summary/Charts/Data) | 中 | 低 | ★★★★☆ | 高优先 |
| KPI summary cards | 中 | 低 | ★★★★☆ | 高优先 |
| LBO/Earnings 参数编辑器 | 中 | 中 | ★★★☆☆ | 中优先 |
| Cash Flow 三段图 | 中 | 低 | ★★★☆☆ | 中优先 |
| EV/EBITDA Band 图 | 高（机构标配） | 中 | ★★★☆☆ | 中优先 |
| Agent Roster 可视化 | 低 | 低 | ★★★☆☆ | 低优先 |
| Scenario Manager (bull/base/bear) | 高 | 高 | ★★☆☆☆ | 延后 |
| Retail Sentiment | 中 | 高（需要 Adanos API 或替代） | ★★☆☆☆ | 延后 |
| 多 ticker 对比 | 高 | 高 | ★★☆☆☆ | 延后 |

### 下一步行动建议（按优先级 — Round 6 更新）

**Round 1 建议 #1 (暴露 pipeline) 和 #2 (⌘K) 已完成。** 重新排序:

1. **连线 4 个已有但未显示的图表组件** — 理由: PriceChart/EpsPeChart/CompanyRadarChart/FootballField 代码已写好，只需要: a) 在 chartAdapters.ts 加 adapter 函数，b) 在对应 summary view 中渲染。零新组件开发，纯连线，1-2 小时完成，图表覆盖从 5 → 9。

2. **数据来源标签系统** — 理由: JurisTech benchmark 证明"LLM 数字不可信"是行业共识。FinAgent 的核心差异化是确定性计算，但 UI 没有让这个差异化"可见"。在每个数字旁加 `[FMP]` `[calc]` `[LLM]` 标签（或 tooltip），让用户一眼看到"这个数字从哪来的"。这是让"数字有保证"从口号变成可感知的产品体验。

3. **Right Panel Tab 切换** — 理由: 当前所有内容堆在一个滚动区域。改为 Summary | Charts | Raw Data 三个 tab，信息密度更高、导航更快。参考 QuantDinger 的 dual-tab 模式。

4. **SEC RAG Q&A 界面** — 理由: 分析师每周 15 小时在文档分析上。后端 BM25Index + EmbeddingIndex 已就绪，只需要一个 chat-like 的 Q&A 面板。输入框 + 问题 + 答案（含引用段落）。这是 AlphaSense($10K/年) 的核心功能，FinAgent 可以免费提供。

5. **KPI Summary Cards** — 理由: 在 data_ready 阶段，用 6 个 metric cards（Market Cap / P/E / EV/EBITDA / Revenue Growth / EBITDA Margin / 52W Range）替代纯表格。"一眼看全局"是 QuantDinger dashboard 的核心模式，比表格更有冲击力。

6. **新增 3 个高价值图表** — 理由: Cash Flow 三段图（基本面标配）、EV/EBITDA Band（机构报告标配）、Revenue YoY%（增长趋势一目了然）。加上连线的 4 个，图表覆盖达到 12/23 = 52%。

### 关键洞察总结（Round 6）

**FinAgent Desktop 进展快速。** 5 轮内从 3 个 pipeline 提升到 5 个，加了 ⌘K 命令面板和 4 个 summary views。方向完全正确。

**最大的浪费是已写好但未显示的代码。** 4 个图表组件、IC Memo pipeline、RAG 能力、6 种 analyze 类型——全部后端就绪，前端没有入口。优先级最高的工作是"连线"而非"造新功能"。

**"数字可溯源"是产品核心——但 UI 还没体现。** JurisTech 的 benchmark 量化证明了 LLM 在金融场景的幻觉问题。FinAgent 的确定性计算层是真正的技术护城河，但用户如果看不到"这个数字从哪来"，这个护城河就是隐形的。**数据来源标签是下一步最值得投入的单一功能。**

**分析师的真正诉求不是更多功能，而是"省时间 + 可审计"。** 每周 24 小时花在机械劳动上。FinAgent 能省 ~15 小时（文档分析 + 报告生成 + 建模预填）。但需要让这些节省"可量化可感知"——比如在报告底部标注"本报告由 FinAgent 在 3 分 42 秒内生成，等效于 ~4 小时人工工作"。

---

## 研究日期: 2026-05-10 (Round 11 — 市场验证 + AI 建模工具实战评测 + Desktop 进展精算)

> 本轮重点: AI 金融建模工具的实战评测数据（Wall Street Prep 2026）、行业采纳率量化、交易界面 UX 最新研究（HRT）、Desktop 进展精算（Round 6 → Round 11 变化）。

### 竞品发现（Round 11 增量）

#### AI 金融建模工具实战评测 — Wall Street Prep 2026 Benchmark

Wall Street Prep 对 4 个 AI 工具进行了标准化测试：用 Apple 公司构建完整三表联动模型。这是迄今为止最具体的 AI 金融建模实测数据。

| 工具 | 评分 | 完成时间 | 核心能力 | 致命缺陷 |
|------|------|---------|---------|---------|
| **Shortcut** | 5.9/10 | ~15 min | IB 格式标准、模型结构清晰 | 历史数据 hallucination，需要逐单元格审计 |
| **Claude** | 5.5/10 | ~15 min | 最佳澄清问题、假设来源说明 | 同样 hallucinate 历史数据 |
| **MS Copilot** | 4.4/10 | ~30 min | 原生 Excel 集成 | 格式不合 IB 规范 |
| **ChatGPT** | 2.5/10 | ~60 min | — | 输出混乱、执行极慢 |

**关键发现:**
1. **"0 → 60% 工具"**: 最佳定位是"kickstarting models from scratch"，不是完成 100% 的工作。即最好的工具也"underperforms a lower-tier analyst"。
2. **"Almost nobody has meaningfully changed their day-to-day financial modeling workflow"**: 银行在试点但仍处于实验模式。安全顾虑 + 不稳定的可靠性是主因。
3. **两个最好的工具都 hallucinate 历史数据**: 速度优势被审计成本抵消。FinAgent 的确定性计算层直接解决此问题。
4. **Claude 在"假设解释"上得分最高**: 分析师重视的不只是数字，还有"为什么选这个假设"——source explanation 是差异化功能。

→ **FinAgent 产品启示**: 不要声称"替代分析师"。声称"完成 0→60%，分析师花时间在判断而不是搬数字"。UI 上应强调: "确定性数据 + LLM 叙事 = 分析师审核而非从零开始"。

#### 行业采纳率 — 最新量化数据

| 指标 | 数据 | 来源 |
|------|------|------|
| 买方机构使用 AI 研究工具比例 | **72%** 每天使用至少一个（2 年前仅 28%） | Goldman Sachs 2026 调查 |
| PM 对 AI 的态度 | **89%** 视为生产力工具而非替代品 | CFA Institute 2025 调查 |
| 高频交易员界面偏好 | **35%** 优先考虑界面质量选平台，但仅 **12%** 对当前满意 | 交易所 UX 研究 |
| LLM 幻觉率（2026 全行业平均） | **8.2%**（2021 年为 38%），但 37 个模型跨基准: **15%-52%** | SQ Magazine + JurisTech |
| 行业因幻觉年损失 | **$250M+** | 多源汇总 |
| AI 部署中出现幻觉导致损失的比例 | **11%** | BizTech 企业调查 |
| 合规风险增加 | **~25%** 在受监管行业 | Chainlink 研究 |

→ **FinAgent 市场时机**: 72% 采纳率意味着"是否用 AI"已不是问题，"用哪个 AI + 能不能信任"才是问题。FinAgent 的窗口不是"说服人用 AI"，而是"说服人用可信的 AI"。

#### Koyfin 2026 最新状态

G2 Winter 2026 报告中 Koyfin 排名金融分析和投资组合管理品类第一。用户评价摘要:
- **优点**: 直觉式导航、drag-and-drop dashboard、500+ 指标 screener、免费层足够入门
- **缺点**: 图表比 Bloomberg 基础且有时更慢、新闻能力弱（连免费平台都不如）、onboarding 对新手不友好
- **定价**: 免费 → $35/月 Premium → $55/月 Plus

→ **FinAgent vs Koyfin 差异化**: Koyfin 的弱点是"没有 AI 分析层 + 新闻弱"。FinAgent 的 equity research pipeline + earnings analysis + catalyst analysis 覆盖这两个弱点。同时 FinAgent 免费开源。但 Koyfin 在 screener（500+ 指标）和 watchlist 上远超 FinAgent 当前能力 — 这些暂不应是 FinAgent 的方向（避免功能膨胀）。

### 用户痛点（Round 11 增量）

#### 痛点 1: "Coordination, not execution" — 工作流碎片化的真正瓶颈

2026 年最新工作流研究发现：即使有了 AI 工具，**协调成本**（而非执行成本）才是分析师的核心摩擦源:
- 跨平台切换（Bloomberg + Excel + Calypso + 内部系统 + compliance review）
- 研究成果与 IC 汇报格式不匹配
- 多人协作时的版本同步

→ **FinAgent 机会**: "single-pane-of-glass" 分析体验。Ticker 输入 → 数据 → 分析 → 估值 → 报告，全程不离开应用。当前 Desktop 已基本实现（5 个 pipeline + 数据面板 + 导出），但缺少 IC Memo（这恰好是"研究→汇报"的桥梁）和 RAG Q&A（深度文档分析不离开应用）。

#### 痛点 2: AI 工具的可用性落差

Wall Street Prep 揭示了一个残酷现实: **大多数 AI 金融工具仍处于"demo 级别"**。
- 安全顾虑（将敏感财务数据传给外部 API）
- 性能不一致（同一提示不同时间结果差异大）
- 真实工作流中的摩擦（大文件处理慢、迭代修改困难、重新计算延迟）

→ **FinAgent 差异化**: 本地运行（Desktop app，数据不出设备）+ 确定性计算层（同样输入永远同样输出）+ 开源可审计。这三点直接回应分析师的三大安全顾虑。**应在 landing page / README 中显著标注。**

#### 痛点 3: 界面质量鸿沟

交易 UX 研究发现: 35% 高频交易员在选择平台时**首先考虑界面质量**，但只有 12% 对当前所用工具满意。这意味着:
- 界面不只是"好看不好看"，是**竞争性优势**
- "历史上交易平台追求'看起来越复杂越专业'"，但现代趋势是**简化 + 清晰**
- Robinhood Legend (2026 新产品): 从新手友好 → 可定制的图表密集型桌面界面，是"从简到繁"渐进式 UX 的范例

→ **FinAgent 设计方向确认**: 当前"Bloomberg meets Linear"定位正确。不做 Bloomberg 的复杂铺排，做 Linear 的精简 + 专注。

### 设计灵感（Round 11 增量 — 含交易界面 UX 最新研究）

#### HRT (Hudson River Trading) 交易界面设计原则

HRT 是全球顶级高频交易公司，他们的 UX 团队分享了以下设计原则:

1. **"UX 在需要人类参与的场景至关重要"** — 界面的目的是让人高效监控和干预自动化系统，不是展示复杂性。FinAgent 等价: pipeline 是自动化的，UI 是让人审核/调整/判断的。

2. **信息分层**: 关键数据突出（大字号/高对比）、上下文数据次要（小字号/低对比）、操作区域与展示区域视觉区分。

3. **HRT 推荐的设计值**:
   - Body 字体: 14px, line-height 1.7em（FinAgent 已用 14px / 1.5 — 可微调到 1.6）
   - Heading: 500 weight default, 700 for emphasis
   - Primary accent: 明亮的 cyan-blue (#2ea3f2) 用于可操作元素
   - Border-radius: 3px（极简专业感）
   - Transition: 0.2s（FinAgent 尚未统一过渡时间）
   - Box-shadow: `0 5px 10px rgba(x,y,z,0.15)`（FinAgent 当前无阴影深度系统）

4. **关键区分**: 活跃数据更新用视觉强度（颜色/动画），静态内容用克制样式。"Reserve visual intensity for live data updates."

→ **FinAgent 可执行的 3 个设计微调**:
- 统一 transition duration 为 `var(--transition-speed, 0.2s)` 全局变量
- 为 card 增加微妙的 box-shadow 层级系统（elevation 0/1/2）
- 活跃 pipeline 步骤的 pulse 动画应更克制（当前 pulse-ring 可能过度）

#### 交易平台 UX 测试的量化改善数据

专业交易平台 UX 重设计后的量化提升:
- 图表设置时间减少 **26%**
- 警报配置错误减少 **31%**
- 实时数据访问速度提升 **34%**

→ **FinAgent 对照**: Desktop 的图表当前无交互配置（不能切换时间段、不能 toggle 指标），pipeline 无自定义参数（除 DCF 外）。这些提升空间巨大但优先级中等（先确保功能覆盖完整）。

#### 2026 Fintech UX 核心趋势

从 G&CO、Onething Design、Skins Factory 等多源综合:
1. **Progressive disclosure 不是选项，是必须**: 先展示 7-8 个关键元素，深度内容折叠
2. **Trust-centered design**: 金融 app 的第一要务不是美观而是信任。透明数据来源 > 华丽动画
3. **AI 个性化需"不令人毛骨悚然"**: 基于行为的个性化可以做，但必须让用户控制
4. **Microinteraction 作为系统反馈**: 小动画表示"系统在工作"，不是装饰

→ **FinAgent 当前状态对照**:
- ✅ Progressive disclosure: ResearchSummary 已有 expandable lists
- ❌ Trust-centered: 数据来源标签仍未实现（Round 6 recommendation #2，最高优先级）
- ✅ Microinteraction: pipeline 步骤有 pulse 动画和进度条
- ❌ 用户控制: 无法保存偏好设定（每次重启从默认开始）

### FinRobot 功能差距（Round 11 更新 — 含精确进展追踪）

#### Desktop 进展: Round 6 → Round 11

自 Round 6 以来的 5 个新 commit 及其效果:

| Commit | 功能 | Round 6 建议对应 |
|--------|------|-----------------|
| `66c2ffa` | StockOverview + KPI 卡片 + PriceChart | ✅ 完成 Round 6 #5 (KPI Summary Cards) |
| `0d977e4` | FootballField 连线到 DCF + Research 视图 | ✅ 完成 Round 6 #1 的 1/4 |
| `10de176` | EPS Surprise 柱状图连线到 Earnings 视图 | ✅ 完成 Round 6 #6 的增量 |
| `dfaa758` | 修复切换 pipeline 类型时右面板空白 | Bug fix |
| `737b287` | LBO pipeline + LBOSummary | 延续 Round 1 #1 |

**图表渲染率**: Round 6 的 5/10 → Round 11 的 **8/10** (80%)。未渲染: `CompanyRadarChart`、`EpsPeChart`。

**Pipeline 覆盖率**: 保持 5/7 (71%)。未暴露: IC Memo、SEC RAG Q&A（加上 Backtest 和 Analyze 6 种类型仍在后端）。

#### Round 6 建议执行追踪

| Round 6 建议 | 状态 | 备注 |
|-------------|------|------|
| #1 连线 4 个已有但未显示的图表 | **75% 完成** | FootballField ✅, EpsSurpriseChart(新) ✅, PriceChart ✅, CompanyRadarChart ❌, EpsPeChart ❌ |
| #2 数据来源标签系统 | **❌ 未开始** | 仍是最高优先级 — 这是产品核心差异化的"可见性" |
| #3 Right Panel Tab 切换 | **❌ 未开始** | 当前仍是垂直滚动布局 |
| #4 SEC RAG Q&A 界面 | **❌ 未开始** | 后端已有 BM25Index + EmbeddingIndex |
| #5 KPI Summary Cards | **✅ 完成** | StockOverview 组件，6 个 KPI 卡片 |
| #6 新增 3 个高价值图表 | **33% 完成** | EpsSurpriseChart 已加。Cash Flow / EV/EBITDA Band 仍缺 |

#### FinRobot 深度功能对比（Round 11 精确版）

FinRobot 源码全面分析后的精确差距:

**A. Agent 系统对比**

| FinRobot Agent | FinAgent 等价 | 差距 |
|---------------|-------------|------|
| Tagline Agent | equity_research pipeline step | ✅ 已覆盖 |
| Company Overview Agent | equity_research step | ✅ 已覆盖 |
| Investment Overview Agent | equity_research step | ✅ 已覆盖 |
| Valuation Overview Agent | dcf pipeline | ✅ 已覆盖 |
| Risks Agent | equity_research step | ✅ 已覆盖 |
| Competitor Analysis Agent | comps pipeline | ✅ 已覆盖 |
| Major Takeaways Agent | equity_research synthesis step | ✅ 已覆盖 |
| News Summary Agent | equity_research step（news 来自 yfinance/FMP） | ⚠️ 功能覆盖但新闻源更窄 |

→ **Agent 系统: 100% 功能覆盖**，但 FinRobot 的 8 个 agent 是独立可调用的，FinAgent 的等价功能融入了 pipeline 步骤。这不是差距——FinAgent 的 pipeline 架构更优（有步骤间类型化数据流）。

**B. 数据源对比**

| 数据源 | FinRobot | FinAgent | 差距 |
|--------|---------|---------|------|
| FMP (Financial Modeling Prep) | ✅ 13 个端点 | ✅ 完整覆盖 | — |
| Finnhub | ✅ 基础 | ✅ 完整 | — |
| yfinance | ✅ 基础 | ✅ 完整 | — |
| SEC EDGAR | ❌ 无 | ✅ 10-K RAG | **FinAgent 优于 FinRobot** |
| Adanos API (Reddit/X/Polymarket) | ✅ 零售情绪 | ❌ 完全缺失 | **最大数据差距** |
| FinNLP 多源新闻 | ✅ (CNBC/Sina/XueQiu等) | ❌ 仅 FMP 新闻 | 中等差距 |
| FMP Analyst Rating/Target | ✅ | ⚠️ 未在 Desktop 展示 | 小差距 |
| FMP Technical Indicators | ✅ (SMA/RSI/MACD) | ❌ | 低优先（非交易工具） |

**C. 图表对比（最终版）**

| 图表类型 | FinRobot | FinAgent Desktop | 状态 |
|---------|---------|-----------------|------|
| Revenue & EBITDA | ✅ | ✅ RevenueEbitdaChart | ✅ |
| Margin Trend | ✅ | ✅ MarginTrendChart | ✅ |
| Peer Comparison | ✅ | ✅ PeerComparisonChart | ✅ |
| Sensitivity Heatmap | ✅ | ✅ SensitivityHeatmap | ✅ |
| Waterfall | ✅ | ✅ WaterfallChart | ✅ |
| Stock Price | ✅ | ✅ PriceChart (StockOverview) | ✅ |
| Football Field | ✅ | ✅ FootballField (DCF+Research) | ✅ |
| EPS Surprise | ✅ | ✅ EpsSurpriseChart (Earnings) | ✅ |
| EPS × P/E | ✅ | ❌ EpsPeChart **存在但未渲染** | 需连线 |
| Financial Radar | ✅ | ❌ CompanyRadarChart **存在但未渲染** | 需连线 |
| Revenue YoY% | ✅ | ❌ 缺失 | 需新建 |
| EV/EBITDA Band | ✅ | ❌ 缺失 | 需新建 — 机构标配 |
| P/FCF Band | ✅ | ❌ 缺失 | 需新建 |
| Cash Flow 三段 | ✅ | ❌ 缺失 | 需新建 — 基本面标配 |
| Revenue Breakdown Pie | ✅ | ❌ 缺失 | 中优先（segment 分析） |
| Relative Performance | ✅ | ❌ 缺失 | 中优先 |
| SGA Ratio | ✅ | ❌ 缺失 | 低优先 |
| Technical Indicators | ✅ | ❌ 缺失 | 低优先（非交易定位） |
| Quarterly Comparison | ✅ | ❌ 缺失 | 中优先 |
| Gross/EBITDA Margin | ✅ | ⚠️ MarginTrendChart 可能覆盖 | 需验证 |
| Time Series (通用) | ✅ | ❌ 缺失 | 低优先 |

**图表覆盖**: 8/23 已渲染 + 2/23 已建未渲染 = **10/23 (43%) 已实现**。FinRobot 的 23 种图表中，约 8 种是高价值的（投研报告常用），FinAgent 已覆盖 8 种中的 6 种。

**D. 报告模板对比**

FinRobot 的 HTML 报告有 13 个 section（Investment Thesis、Company Overview、Financial Analysis、Advanced Charts 等），用 Tailwind CSS + indigo 配色方案。FinAgent 有 3 个报告模板（equity_research / comps / dcf），用 Jinja2 + inline CSS。

→ **报告模板不是当前优先级**——Desktop app 的 summary views 已替代 HTML 报告作为主要展示方式。但 PDF 导出质量仍值得关注。

### Desktop UI 当前缺陷清单（Round 11 更新）

基于完整代码审计，以下是当前 Desktop 的具体问题:

| # | 问题 | 严重性 | 代码位置 |
|---|------|--------|---------|
| 1 | **2 个图表组件已建未渲染**: CompanyRadarChart + EpsPeChart | 中 | `charts/index.ts` exports 但无 view 引用 |
| 2 | **数据来源标签缺失**: 无法区分 FMP/Calculated/LLM 数据 | **高** | 全局问题 |
| 3 | **Right panel 纯滚动无 tab**: Summary + Charts + Raw Data 全堆一起 | 中 | `TickerWorkspace.tsx` L190-350 |
| 4 | **IC Memo pipeline 未暴露**: 后端 `ic_memo.py` 完整 | 中 | `appStore.ts` PipelineType 枚举 |
| 5 | **SEC RAG Q&A 未暴露**: 后端 BM25Index + EmbeddingIndex 完整 | **高** | 无对应 UI 组件 |
| 6 | **无 theme toggle**: 强制 dark mode，无 light mode 选项 | 低 | `App.css` |
| 7 | **左栏固定 340px 不可拖拽调整** | 低 | `App.css` L180 `.panel-left` |
| 8 | **无 transition 全局变量**: 各组件硬编码不同 transition 值 | 低 | 分散在各 CSS class |
| 9 | **无 elevation/shadow 系统**: 所有 card 同样扁平 | 低 | `.card` class |
| 10 | **无用户偏好持久化**: 重启后所有状态丢失 | 中 | `appStore.ts` 无 persist |

### 下一步行动建议（按优先级 — Round 11 更新）

**Round 6 建议执行率: 3/6 完成 (50%)。** 以下重新排序，综合 Round 11 新发现:

1. **数据来源标签系统 [FMP] [calc] [LLM]** — 理由: **连续 3 轮排名最高但仍未实现。** Wall Street Prep 评测证明: 即使最好的 AI 工具也 hallucinate 历史数据。Goldman Sachs 调查显示 72% 机构已用 AI，瓶颈不再是"要不要用"而是"能不能信"。数据来源标签是把 FinAgent 的确定性计算层从"技术实现细节"变成"用户可感知的产品优势"的唯一方式。实现方案: 在 `FinancialsPanel` 的每个数字旁加 tooltip badge，显示 `[FMP]` / `[calc]` / `[LLM estimate]`。后端 `DataResult` 已有 `provider` 字段，需要透传到前端。

2. **连线 2 个已建未渲染的图表** — 理由: CompanyRadarChart 和 EpsPeChart 代码已存在，只需要: a) 在 `chartAdapters.ts` 加 adapter 函数从 pipeline 结果提取数据，b) 在 ResearchSummary / TickerWorkspace 的合适位置渲染。1-2 小时工作，图表覆盖从 80% → 100%（已建的全部亮相）。

3. **SEC RAG Q&A 界面** — 理由: Wall Street Prep 揭示分析师最大的工作流碎片化来自"跨平台切换"。15h/周文档分析是最大的时间黑洞。后端 BM25 + Embedding 双索引已就绪，需要一个简单的 Q&A 面板: ticker 选择 + 问题输入 + 答案展示（含引用原文段落高亮）。这是 AlphaSense ($10K/年) 的核心功能。

4. **Right Panel Tab 切换 (Summary | Charts | Data)** — 理由: 信息密度核心原则是"7-8 个关键元素 max"。当前 right panel 一次性铺所有内容（summary + 5-6 个图表 + 估值卡片 + 导出栏），用户需要滚动很远才能看到底部内容。Tab 切换让每个 tab 只展示 3-5 个相关元素。

5. **IC Memo pipeline 暴露** — 理由: IC Memo 是"研究→汇报"工作流的桥梁。后端 `ic_memo.py` 运行 DCF + LBO 并综合判断（IRR < 15% 自动 PASS）。只需要: a) 在 `PipelineType` 枚举加 `ic_memo`，b) 写一个 ICMemoSummary 组件。这个功能直接解决"协调成本 > 执行成本"的痛点——分析师可以一键从分析跳到 IC 材料。

6. **新增 2 个高价值图表: Cash Flow 三段图 + EV/EBITDA Band** — 理由: 这两个是机构投研报告的标配。Cash flow（Operating/Investing/Financing 堆叠柱状图 + Net 折线）展示现金流质量。EV/EBITDA Band（历史倍数 mean ± 1σ）展示估值是否偏离历史范围。后端数据已可获取，纯前端 recharts 工作。

### 关键洞察总结（Round 11）

**FinAgent 的市场时机比 6 轮前更好。** 72% 买方机构已在日常使用 AI 研究工具，但"Almost nobody has meaningfully changed their day-to-day financial modeling workflow"——信任鸿沟仍然巨大。FinAgent 的确定性计算层+数据来源透明性，是解决这个信任鸿沟的最直接方案。

**Wall Street Prep 评测给 FinAgent 的定位校准。** 即使最好的 AI 工具也只能做到"0→60%"。FinAgent 不应该 claim"替代分析师"，应该 claim"让分析师从搬数字中解放出来，花时间在判断上"。产品叙事: **"FinAgent 做苦力，你做判断。"**

**数据来源标签已连续 3 轮排名建议 #1 但未实现。** 这是技术债和产品债的交叉点——FinAgent 的核心差异化（确定性计算）在 UI 上完全不可见。用户打开 FinAgent Desktop，看到的数字跟 ChatGPT 输出的数字看起来没有区别。一个 `[FMP]` `[calc]` tooltip 的成本极低，但对"可感知的可信度"提升极大。

**Desktop 进展健康但开始出现"最后一公里"问题。** 8/10 图表已渲染，5/7 pipeline 已暴露，KPI 卡片已上线。剩下的都是"差一点点就完整"的功能: 2 个图表没连线、2 个 pipeline 没暴露、tab 切换没做。这些"最后一公里"问题单个都很小，但累积起来让产品感觉"90% 完成"——用户能感知到"差点什么"。

---

## 研究日期: 2026-05-10 (Round 12 — 精品化阶段：视觉品质深度审计)

> 本轮重点: 精品化。不是功能缺失，是视觉不够"值钱"。逐组件审计 CSS/JSX，对比 Bloomberg/Koyfin/Linear 的具体设计手法，输出可执行的视觉改进清单。

### Round 11 → Round 12 进展追踪

最近 3 个 commit:
| Commit | 功能 | 影响 |
|--------|------|------|
| `4d39c9c` | 数据来源标签 [FMP/CALC/AI] 全面铺设 | ✅ **终于完成了连续 3 轮排名 #1 的建议** |
| `61caa38` | Research pipeline 类型匹配修复 | Bug fix |
| `ed591e8` | CompanyRadarChart 连线到 Comps 视图 | ✅ 图表覆盖率提升 |

**数据来源标签已完成。** FinancialsPanel 的每个数字旁都有 `[FMP]` `[CALC]` 标签，ValuationCard 和 ResearchSummary 也标注了 `[CALC]` 和 `[AI]`。CSS 样式完善（`.source-badge` + tooltip）。这是核心差异化的"可见性"突破。

**图表覆盖率: 9/10 已建组件已渲染 (90%)。** 唯一未渲染: `EpsPeChart`。

### 视觉差距分析（逐组件审计 — 对比竞品截图）

#### 1. 全局问题: 所有卡片同一视觉权重 — 无深度层级

**FinAgent 现状:**
所有 card 使用同一个样式: `background: var(--surface); border: 1px solid var(--border-subtle); border-radius: 8px`。估值 hero 卡片有金色渐变顶线，但其余所有卡片（FinancialsPanel、PipelineRunner、图表卡片）视觉上完全相同。

**竞品做法:**
- **Koyfin**: 使用 3 层卡片层级 — 主数据区域（无边框、flush 背景）、数据卡片（微阴影 `0 1px 3px rgba(0,0,0,0.2)`）、弹出面板（明显阴影 `0 8px 24px rgba(0,0,0,0.4)`）
- **Bloomberg Terminal**: 区域用颜色深浅区分而非边框。活跃区域背景微亮（#1a1a2e），静态区域更暗（#0d0d1a）
- **Linear**: card 有微妙的 `box-shadow: 0 1px 2px rgba(0,0,0,0.1)` + hover 时增强为 `0 4px 12px rgba(0,0,0,0.15)`

**具体改法:**
```css
/* 新增 3 级 elevation tokens */
--shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.2);
--shadow-md: 0 4px 12px rgba(0, 0, 0, 0.25);
--shadow-lg: 0 8px 24px rgba(0, 0, 0, 0.35);

.card { box-shadow: var(--shadow-sm); }
.card:hover { box-shadow: var(--shadow-md); transition: box-shadow 0.2s; }
.valuation-hero { box-shadow: var(--shadow-md); }
```

#### 2. 内联样式泛滥 — 视觉不一致的根源

**FinAgent 现状:**
代码审计发现 5 个 summary 组件大量使用 inline style 对象:

| 组件 | 内联 style 对象数 | 典型模式 |
|------|-----------------|---------|
| `LBOSummary.tsx` | ~60 个 | 每个 `<div style={{...}}>` 重复定义 `fontFamily`, `fontSize`, `fontWeight` |
| `EarningsSummary.tsx` | ~50 个 | beat rate 圆环用 inline SVG style 硬编码 |
| `CompsSummary.tsx` | ~40 个 | 表头样式 6 处重复同样的 padding/fontSize/fontWeight 组合 |
| `ResearchSummary.tsx` | ~25 个 | rating badge 完全内联 |
| `ValuationCard.tsx` | ~10 个 | 相对克制 |

**问题不只是代码质量** — 它导致了具体的视觉不一致:
- LBOSummary 表头: `fontSize: '0.7rem', fontWeight: 600, padding: '8px 12px'`
- EarningsSummary 表头: `fontSize: '0.7rem', fontWeight: 600, padding: '8px 12px'`（相同但分别定义）
- CompsSummary 表头: `fontSize: '0.7rem', fontWeight: 600, padding: '8px 16px'`（注意 padding 不同！）
- FinancialsPanel 行: `padding: 7px 0`（又不同）

**具体改法:**
提取 6 个共享 CSS 类:
```css
.hero-header { /* 所有 summary hero 的顶部 flex 布局 */ }
.hero-ticker { /* 金色大字 ticker 样式 */ }
.data-table { /* 统一数据表格 — 替换重复的 inline table styles */ }
.data-table th { /* 统一表头 */ }
.data-table td { /* 统一单元格 */ }
.metric-pill { /* BUY/SELL/STRONG 等状态标签 */ }
```

#### 3. PriceChart 缺少面积填充 — 与 Koyfin 差距最明显的一处

**FinAgent 现状:**
`PriceChart.tsx` 使用 `<Line>` 组件画一条裸线 + `<Bar>` 画成交量。视觉上单薄。

**竞品做法:**
- **Koyfin**: 价格线下方有从线颜色渐变到透明的 area fill，视觉上丰满 3 倍
- **TradingView**: 同样的渐变 area fill，是行业标准
- **Robinhood**: 绿色/红色 area fill 根据涨跌变色

**具体改法（1 处代码改动）:**
```tsx
// PriceChart.tsx — 在 <Line> 前加:
<defs>
  <linearGradient id="priceGradient" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stopColor="#60A5FA" stopOpacity={0.15} />
    <stop offset="100%" stopColor="#60A5FA" stopOpacity={0} />
  </linearGradient>
</defs>
<Area
  yAxisId="price"
  type="monotone"
  dataKey="close"
  fill="url(#priceGradient)"
  stroke="none"
/>
```

#### 4. 无 Loading Skeleton — 布局跳动感

**FinAgent 现状:**
- FinancialsPanel 加载时: 显示 "—" 文本占位符（`opacity: 0.3`）
- StockOverview 加载时: 显示 "Loading price data..." 纯文本
- 没有 shimmer/pulse skeleton 动画

**竞品做法:**
- **Koyfin**: 灰色矩形 skeleton 精确匹配最终内容尺寸，shimmer 动画从左到右扫过
- **Linear**: 使用 `@keyframes shimmer` 从 `var(--surface)` 到 `var(--elevated)` 来回脉冲
- **Bloomberg**: 数据区域用微弱的脉冲背景色表示加载中

**具体改法:**
```css
@keyframes skeleton-pulse {
  0%, 100% { background-color: var(--surface); }
  50% { background-color: var(--elevated); }
}
.skeleton {
  border-radius: var(--r-sm);
  animation: skeleton-pulse 1.5s ease-in-out infinite;
}
.skeleton-text { height: 14px; width: 60%; }
.skeleton-number { height: 14px; width: 80px; }
```

#### 5. Pipeline 进度是扁平列表 — 缺少时间线感

**FinAgent 现状:**
`PipelineRunner.tsx` 用垂直列表展示步骤: 圆圈 + 步骤名 + 耗时。圆圈之间无连线。视觉上像一个 todo list，不像一个 pipeline。

**竞品做法:**
- **GitHub Actions**: 步骤之间有垂直虚线连接，完成的用实线，运行中的用动画虚线
- **Vercel Deploy**: 步骤图标之间有细线，步骤卡片有微妙的左边框色条表示状态

**具体改法:**
```css
.step::before {
  content: '';
  position: absolute;
  left: 9px; /* 对齐圆圈中心 */
  top: -2px;
  height: calc(100% + 4px);
  width: 1px;
  background: var(--border);
}
.step:first-child::before { top: 50%; height: 50%; }
.step:last-child::before { height: 50%; }
.step.done::before { background: var(--positive); opacity: 0.3; }
.step.active::before { background: var(--gold); opacity: 0.3; }
```

#### 6. Idle/Empty 状态过于简陋

**FinAgent 现状:**
- Idle 左栏: 一个淡化的 SVG 柱状图 + "Enter a ticker to start analysis"
- Idle 右栏: "Analysis results will appear here" 纯文本

**竞品做法:**
- **Raycast**: 空状态显示快捷键提示 + 最近使用历史 + 推荐操作
- **Linear**: 精心设计的空态插画 + 明确的 CTA 按钮

**具体改法:**
空态应展示: 1) ⌘K 快捷键提示, 2) 热门 ticker 快速入口 (AAPL, MSFT, NVDA, GOOGL), 3) 最近分析过的 ticker（如果有）

#### 7. 表格 Header 不 Sticky

**FinAgent 现状:**
LBO Debt Schedule (6 列 × N 行)、Comps Peer Table (5 列)、Earnings Quarterly Table (9 列) — 向下滚动时表头消失。

**具体改法:**
```css
.data-table thead th {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--surface);
}
```

#### 8. 右面板无 Tab 切换 — 信息堆砌

**FinAgent 现状:**
DCF 模式下右面板垂直排列: ValuationCard → FootballField → SensitivityHeatmap → WaterfallChart → RevenueEbitdaChart → MarginTrendChart → ExportBar。需要滚动 ~2000px 才能看到底部。

**竞品做法:**
- **Koyfin**: 顶部 tab 栏 (Overview | Financials | Charts | News)
- **Bloomberg**: 功能区 tab 快速切换

**具体改法:**
在右面板顶部加 segmented control:
- **Overview**: Hero 卡片 + FootballField + 关键图表 (2 个)
- **Charts**: 所有图表 grid
- **Data**: FinancialsPanel 详细版 + sensitivity 表

#### 9. 顶栏信息密度不足

**FinAgent 现状 (48px):**
Logo | Divider | TickerInput | Divider | Ticker + Price | Spacer | ⌘K | History | Settings

**Bloomberg 做法:**
Ticker + Price + Change + Change% + Volume + Prev Close + Open + Range + Sector + Exchange — 所有关键信息一行

**具体改法:**
在 ticker-display 区域增加: 涨跌额 + 涨跌% pill（已有 CSS `.ticker-change`，但 `TickerWorkspace.tsx` L97-107 没有渲染 change 数据）。考虑加 sector 标签。

#### 10. 无全局 transition 变量

**FinAgent 现状:**
各处硬编码不同 transition 值:
- `.btn`: `transition: all 0.15s`
- `.cmd-trigger`: `transition: all 0.15s`
- `.assumption-slider::-webkit-slider-thumb`: `transition: transform 0.1s`
- `.cmd-overlay`: `animation: cmd-fade-in 0.12s`
- `.cmd-palette`: `animation: cmd-scale-in 0.15s`

**具体改法:**
```css
:root {
  --transition-fast: 0.1s ease;
  --transition-base: 0.15s ease;
  --transition-slow: 0.25s ease;
}
```

### 交互差距

| 缺失交互 | 竞品做法 | 具体改法 |
|---------|---------|---------|
| **无键盘快捷键 (除 ⌘K)** | Linear: ⌘1-5 切换视图，R 运行 | 给 pipeline tab 绑 1-5 快捷键，R 绑 Run |
| **Command Palette 无最近历史** | Raycast: 最近使用的命令排最前 | 在 commands 列表最上方加 "Recent Tickers" section |
| **KPI 卡片无 hover 详情** | Koyfin: hover 显示 YoY 变化 + sparkline | KPICard hover 时显示 tooltip 含对比数据 |
| **图表无时间段切换** | TradingView: 1D/1W/1M/3M/1Y/ALL | PriceChart 顶部加 segmented: 1M/3M/6M/1Y |
| **数据表格不可排序** | Koyfin: 点击表头排序 | Comps peer table 支持按 EV/EBITDA 等列排序 |
| **左栏不可拖拽调整** | Bloomberg/Figma: 面板宽度可拖拽 | 加 resize handle 在左栏右边缘 |

### FinRobot 功能差距（Round 12 更新）

**Round 11 建议执行追踪:**

| 建议 | 状态 | 备注 |
|------|------|------|
| #1 数据来源标签 | **✅ 完成** | commit `4d39c9c`，FinancialsPanel + ValuationCard + ResearchSummary 全覆盖 |
| #2 连线 2 个图表 | **50% 完成** | CompanyRadarChart ✅ (commit `ed591e8`)，EpsPeChart ❌ |
| #3 SEC RAG Q&A | ❌ 未开始 | 后端就绪 |
| #4 Right Panel Tab | ❌ 未开始 | |
| #5 IC Memo pipeline | ❌ 未开始 | |
| #6 新图表 | ❌ 未开始 | Cash Flow / EV/EBITDA Band |

**仍缺失的关键功能:**

| 功能 | 后端 | Desktop | 视觉影响 |
|------|------|---------|---------|
| EpsPeChart 连线 | ✅ 组件已建 | ❌ 未渲染 | 低（Earnings view 已有 EpsSurpriseChart） |
| IC Memo pipeline | ✅ `ic_memo.py` | ❌ 未暴露 | 中 — "研究→汇报"桥梁 |
| SEC RAG Q&A | ✅ BM25 + Embedding | ❌ 无 UI | 高 — AlphaSense 核心功能 |
| Retail Sentiment | ❌ 无后端 | ❌ | 中 — FinRobot 有但 FinAgent 完全缺失 |
| Cash Flow 三段图 | ✅ **后端 `charts/cash_flow.py` 已有** | ❌ Desktop 未渲染 | 中 — 基本面分析标配 |
| EV/EBITDA Band | ✅ **后端 `charts/valuation_band.py` 已有** | ❌ Desktop 未渲染 | 高 — 机构报告标配 |
| Revenue YoY% | ✅ **后端 `charts/revenue_yoy.py` 已有** | ❌ Desktop 未渲染 | 低 |
| Quarterly Comparison | ✅ **后端 `charts/quarterly_comparison.py` 已有** | ❌ Desktop 未渲染 | 中 |
| Earnings Call RAG (speaker-level) | ❌ 完全缺失 | ❌ | **高** — "CFO 说了什么?" 类查询 |
| Social Sentiment (Reddit/Stocktwits) | ❌ 完全缺失 | ❌ | **高** — FinRobot 最大数据差距 |
| Stock Forecaster (FinGPT-style) | ❌ 完全缺失 | ❌ | 中 — headline feature |

### 3 个最值得抄的视觉细节

**1. 图表面积渐变填充 (Koyfin/TradingView)**
价格线下方从 `rgba(主色, 0.15)` 渐变到透明。一行代码让图表视觉丰满度提升 3 倍。适用于: PriceChart、MarginTrendChart。这是"看一眼就知道是专业工具"的标志性视觉元素。

**2. 卡片层级阴影系统 (Linear/Notion)**
3 级 elevation: `sm` (数据卡片) → `md` (hero 卡片) → `lg` (弹出层)。当前 FinAgent 的 `.card` 和 `.valuation-hero` 在视觉重量上差距不够。加上阴影后立即产生"前景/背景"的深度感。注意: 暗色主题的阴影需要用 `rgba(0,0,0,0.3+)` 才能看出效果。

**3. Pipeline 步骤连接线 (GitHub Actions/Vercel)**
步骤之间用细线连接，完成的变绿，运行中的用动画。这把扁平的"列表"变成有叙事感的"流程图"。PipelineRunner 是用户等待时盯着看最久的组件，这里的视觉品质直接影响"等待焦虑"。

### 行动建议（按视觉影响力排序）

1. **提取内联样式 + 建立共享 CSS 类** — 影响: 全局一致性。工作量: 中等（需要改 5 个 summary 组件）。成本极低/收益极高——提取后每个组件代码减少 30-40%，且视觉风格统一。新增 CSS 类: `.hero-header`, `.hero-ticker`, `.data-table`, `.data-table th/td`, `.metric-pill`, `.status-badge`。

2. **PriceChart 面积渐变填充 + MarginTrendChart 面积填充** — 影响: 图表高级感 ×3。工作量: 极小（每个图表加 ~10 行代码）。这是截图分享时视觉冲击力提升最大的单一改动。

3. **卡片 elevation 系统 (3 级阴影)** — 影响: 全局深度层次。工作量: 极小（CSS 变量 + 3 个类）。给 `.card` 加默认 `shadow-sm`，`.valuation-hero` 加 `shadow-md`，`.cmd-palette` 加 `shadow-lg`。

4. **Pipeline 连接线** — 影响: 等待体验。工作量: 小（CSS `::before` 伪元素）。把 PipelineRunner 从"todo list"升级为"timeline"。

5. **Loading Skeleton 动画** — 影响: 加载品质感。工作量: 小（一个 `.skeleton` CSS 类 + 在 FinancialsPanel/StockOverview 加载态使用）。消除"Layout shift"和"Loading..." 文本。

6. **右面板 Tab 切换 (Overview | Charts | Data)** — 影响: 信息架构。工作量: 中等（需要在 TickerWorkspace 里重构右面板渲染逻辑）。把 2000px 的垂直滚动变成 3 个 focused 视图。

7. **Idle 状态升级** — 影响: 第一印象。工作量: 小。加快捷键提示 + 热门 ticker 按钮 + 最近历史。

### 关键洞察总结（Round 12 — 精品化阶段）

**FinAgent 的功能覆盖已接近完整（90%+），瓶颈已从"缺什么"转移到"做得够不够好看"。** 数据来源标签终于落地，9/10 图表已渲染，5 条 pipeline 全部暴露。现在的问题是: 截一张图发到 Twitter，第一反应是"专业工具"还是"个人项目"？答案取决于下面 3 件事。

**视觉品质的 3 个决定性因素:**
1. **深度层级** — 当前所有卡片同样扁平，像一张纸上画的。加了 elevation 系统后，像真实的物理界面——近的卡片浮起来，远的沉下去。
2. **图表丰满度** — 裸线图 vs 面积填充图，视觉高级感差 3 倍。一行代码的事。
3. **细节一致性** — 内联样式导致每个组件的 padding/font 微妙不同。用户感知不到具体哪里不对，但会感到"something feels off"。统一后这种感觉消失。

**最大的视觉债不是缺少功能，而是内联样式泛滥。** LBOSummary 有 ~60 个 inline style 对象。每个对象都是一个潜在的不一致来源。这不是"以后重构"的事——它现在就在产生视觉噪音。建议: 下一轮首先提取 5 个 summary 组件的内联样式到 CSS 类。

**截图测试: FinAgent 现在能通过 "Hacker News 首页测试" 吗?** 设计系统方向正确（暗色、金色、等宽字体、克制的配色），但细节差最后一公里: 卡片扁平、图表单薄、表头不 sticky、loading 没骨架。修完以上 7 条建议，答案是 Yes。

---

## 研究日期: 2026-05-10 — 精品化深度研究（Round 13）

### 研究方法

本轮使用竞品 UI 搜索（Koyfin、Bloomberg、Fortress/Vault 金融 UI 模板）、2026 暗色主题仪表盘设计趋势分析（Dribbble/Behance/Muzli 50+ 最佳案例）、命令面板 UX 模式文献（Raycast/Linear/VS Code/Figma）、FinRobot 源码完整对比。逐组件、逐文件审计 FinAgent Desktop 当前状态。

---

### 一、视觉差距（对比竞品 + 2026 设计趋势）

#### 1.1 内联样式 = 视觉不一致的根源（最大问题）

| 组件 | 内联 style 对象数 | 典型问题 |
|------|-------------------|----------|
| LBOSummary | ~60 | padding 在 8px/12px/16px 间随意切换，th 样式每个表格手写一遍 |
| CompsSummary | ~40 | `fontSize: '0.7rem'` vs `0.72rem` vs `0.78rem` 在同一文件内 |
| EarningsSummary | ~35 | badge 样式（fontSize/padding/borderRadius）手写而非用 CSS 类 |
| ResearchSummary | ~15 | 相对好，但 price target 区域仍是内联 |
| PipelineRunner | ~5 | 最干净，几乎全用 CSS 类 |

**竞品怎么做**: Fortress 金融模板使用 Tailwind utility 类 + 8px 基准间距系统，表头样式统一为一个 `.table-header` 类。所有数字字体、对齐、padding 通过 3-4 个复用类控制。

**具体差距**: 同一个 `<th>` 样式在 LBOSummary 里出现 3 次（Returns Bridge / Debt Schedule / IRR Sensitivity），每次手写 `{padding: '8px 12px', textAlign: 'left/right/center', fontSize: '0.7rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)'}` 。不仅代码冗余，还导致任何人改一处忘改另一处时产生微妙不一致。

**怎么改**: 提取 5-8 个共享 CSS 类到 App.css:
- `.data-table` — 统一 min-width, border-collapse, 行 border 样式
- `.data-table th` — 统一表头排版（字号/字重/变换/间距/颜色）
- `.data-table td` — 统一单元格 padding + mono 字体
- `.hero-header` — "flex between, marginBottom sp-5" 的两端布局
- `.hero-ticker` — 1.4rem mono 700 金色标题
- `.hero-subtitle` — 0.82rem secondary 说明文字
- `.metric-pill` — beat/miss/rating badge（fontSize + padding + borderRadius + 颜色变体）
- `.action-bar` — 替代反复出现的 export-bar + "New Analysis" 按钮

#### 1.2 图表视觉单薄（PriceChart 是重灾区）

**当前**: PriceChart.tsx line 87-95 — 裸 `<Line>` 组件，无面积填充。MarginTrendChart 同理。

**竞品怎么做**:
- **Koyfin**: 所有价格图/面积图使用 `linearGradient` 从主色 15% opacity → 透明的渐变填充。这是金融图表的标志性视觉元素——一行代码区分"专业工具"和"学生作业"。
- **Bloomberg**: 价格线下方有极浅的区域填充，颜色与涨跌一致（涨绿区域/跌红区域）。
- **TradingView**: 面积图模式是默认视图，渐变从线颜色 30% opacity 到 3% opacity。
- **2026 趋势**: Muzli 50 Best Dashboards 中，90%+ 的折线图使用面积渐变填充。

**具体改法（PriceChart）**:
```tsx
<defs>
  <linearGradient id="priceGradient" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stopColor={PRICE_COLOR} stopOpacity={0.15} />
    <stop offset="100%" stopColor={PRICE_COLOR} stopOpacity={0.02} />
  </linearGradient>
</defs>
<Area
  yAxisId="price"
  type="monotone"
  dataKey="close"
  fill="url(#priceGradient)"
  stroke={PRICE_COLOR}
  strokeWidth={2}
/>
```

#### 1.3 卡片全部扁平 — 无深度层级

**当前**: 所有 `.card` 和 `.valuation-hero` 使用相同的 `1px solid var(--border-subtle)` 边框，无阴影。视觉上是一张纸上画的网格，没有"前景/背景"关系。

**竞品怎么做**:
- **Fortress 金融模板**: 3 级 elevation — `sm` (数据卡片: `0 1px 3px rgba(0,0,0,0.3)`) → `md` (hero 卡片: `0 4px 12px rgba(0,0,0,0.4)`) → `lg` (弹出层: `0 24px 80px rgba(0,0,0,0.5)`)
- **Linear**: 卡片悬浮使用 `box-shadow: 0 2px 8px rgba(0,0,0,0.15)`, hover 时 shadow 增大
- **2026 趋势**: 暗色主题中 shadow 需要更高 opacity (0.3-0.5) 才能产生可感知的效果。低 opacity shadow 在暗色背景上几乎不可见。

**注意**: DESIGN-SYSTEM.md 说"阴影最多一层"且通常不用阴影。但这条规则在实际效果上导致了卡片全部扁平。建议修改为"3 级 elevation"系统，保持克制但有层次。

**具体改法**:
```css
.card { box-shadow: 0 1px 3px rgba(0,0,0,0.3); }
.valuation-hero { box-shadow: 0 4px 16px rgba(0,0,0,0.4); }
.cmd-palette { /* 已有 shadow, 保持 */ }
```

#### 1.4 Pipeline 步骤是扁平列表 — 缺少叙事感

**当前**: PipelineRunner 的 `.pipeline-steps` 是 `flex-direction: column; gap: 2px` 的纯列表。步骤之间没有视觉连接。

**竞品怎么做**:
- **GitHub Actions**: 步骤左侧有竖线连接各圆形 indicator，完成变绿，运行中有动画脉冲。
- **Vercel Deploy**: 类似竖线连接，但更精简 — 2px 宽的连接线，完成段变色。
- **Linear**: 进度指示器使用微妙的阶梯动画，每步完成时有 0.2s 的"pop"效果。

**具体改法**:
```css
.step { position: relative; padding-left: calc(18px + var(--sp-3)); }
.step::before {
  content: '';
  position: absolute;
  left: 9px; /* center of 18px indicator */
  top: 0; bottom: 0;
  width: 2px;
  background: var(--border);
}
.step:first-child::before { top: 50%; }
.step:last-child::before { bottom: 50%; }
.step.done::before { background: var(--positive); }
.step.active::before { background: var(--gold); }
```

#### 1.5 Loading 状态粗糙

**当前**: StockOverview line 112 — "Loading price data..." 纯文本。FinancialsPanel 类似。

**竞品怎么做**:
- **Koyfin**: 骨架屏（shimmer animation），卡片形状与最终内容一致，0.8s 循环。
- **Linear**: 淡入的脉冲矩形 placeholder，颜色从 `var(--elevated)` 到 `var(--border)` 循环。
- **2026 趋势**: "Loading..." 文本在专业产品中已基本消失，被骨架屏或微妙的脉冲动画替代。

**具体改法**: 添加一个 `.skeleton` CSS 类:
```css
.skeleton {
  background: linear-gradient(90deg,
    var(--elevated) 25%,
    var(--border) 50%,
    var(--elevated) 75%
  );
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
  border-radius: var(--r-sm);
}
@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
```

#### 1.6 表头不 sticky

**当前**: Debt Schedule / Peer Comparison / Earnings History 等长表格滚动时表头消失。

**竞品怎么做**: 所有专业金融界面的表头都是 sticky 的。Bloomberg Terminal、Koyfin、AlphaSense 无一例外。

**具体改法**: `.data-table thead th { position: sticky; top: 0; z-index: 1; background: var(--surface); }`

---

### 二、交互差距（对比 Raycast / Linear / Bloomberg）

#### 2.1 命令面板缺少"最近使用"和快捷键

**当前**: CommandPalette.tsx — 只有 3 个 section (ticker/pipeline/navigate)。没有 "Recent" section，没有 Cmd+1-5 数字快捷键。

**竞品怎么做**:
- **Raycast**: 首屏显示最近 5 个命令 + Cmd+1-9 直接触发，不需要开命令面板。
- **Linear**: 命令面板顶部有 "Recent" section，按使用频率排序。
- **VS Code**: 分 "recently used" / "other commands" 两段。

**具体改法**: 在 `useAppStore` 加 `recentCommands: string[]`，CommandPalette 在空查询时优先显示 "Recent" section。

#### 2.2 无全局键盘快捷键

**当前**: 只有 Cmd+K（开命令面板）。没有:
- `1-5` 切换 pipeline 类型
- `Cmd+Enter` 运行当前 pipeline
- `Cmd+H` 查看历史
- `Cmd+,` 打开设置
- `Cmd+N` 新建分析

**竞品怎么做**:
- **Bloomberg**: 几乎所有操作都有键盘快捷键，用户可以不碰鼠标完成全部工作流。速度是金融工具的核心 UX 指标。
- **Linear**: `G` 然后 `I` = Go to Issues, `C` = Create Issue — 两键组合覆盖所有操作。
- **Interactive Brokers Desktop**: F1-F9 对应不同交易操作。

**具体改法**: 在 App.tsx 的 `handleGlobalKeyDown` 中添加:
```ts
if (e.key >= '1' && e.key <= '5' && !e.metaKey && !e.ctrlKey) {
  const types = ['research', 'dcf', 'comps', 'earnings', 'lbo']
  setPipelineType(types[+e.key - 1])
}
```

#### 2.3 空状态缺乏引导

**当前**: Idle 状态是两行文本 — "Enter a ticker to start analysis" + "Analysis results will appear here"。

**竞品怎么做**:
- **Koyfin**: 空状态有热门 ticker 标签（AAPL, MSFT, TSLA...），点击即加载。
- **Raycast**: 空状态显示快捷键备忘录。
- **Linear**: 空状态有 onboarding 步骤指引。

**具体改法**: 在 idle 状态显示:
1. 快捷键提示条 (`⌘K` Search · `1-5` Pipeline · `⌘Enter` Run)
2. 热门 ticker 按钮组 (AAPL / MSFT / NVDA / GOOGL / AMZN)
3. 最近分析历史（前 3 条，如有）

---

### 三、FinRobot 功能差距（源码对比）

#### 3.1 完全缺失的功能

| 功能 | FinRobot 实现 | FinAgent 状态 | 影响评估 |
|------|-------------|-------------|---------|
| **Social Sentiment (Reddit)** | `r/wallstreetbets`, `r/stocks`, `r/investing` 帖子抓取 + 情绪分析 | 完全缺失 | **高** — 散户情绪是小基金 PM 关注的独特信号 |
| **StockTwits 情绪** | FinNLP `Stocktwits_Streaming` 模块 | 完全缺失 | 中 — 与 Reddit 类似但受众更窄 |
| **Earnings Call 转录分析** | 完整的转录稿解析，支持按季度(Q1-Q4)、按发言人提取 | 完全缺失 | **高** — "CFO 说了什么?" 是研究员最常问的问题 |
| **Candlestick/OHLC 图** | `mplfinance` 支持蜡烛图、OHLC、砖形图、PnF 图 | 完全缺失 | 中 — 技术分析用户的基本需求 |

#### 3.2 后端有但 Desktop 未暴露

| 功能 | 后端状态 | Desktop 状态 |
|------|---------|-------------|
| IC Memo pipeline | ✅ `ic_memo.py` 完整实现 | ❌ 未暴露在 PIPELINE_OPTIONS 中 |
| Cash Flow 三段图 | ✅ `charts/cash_flow.py` | ❌ Desktop 无组件 |
| EV/EBITDA Band | ✅ `charts/valuation_band.py` | ❌ Desktop 无组件 |
| Revenue YoY% | ✅ `charts/revenue_yoy.py` | ❌ Desktop 无组件 |
| Quarterly Comparison | ✅ `charts/quarterly_comparison.py` | ❌ Desktop 无组件 |
| EpsPeChart | ✅ Desktop 组件已建 | ❌ 未在任何 view 中渲染 |

#### 3.3 FinAgent 超越 FinRobot 的功能

| 功能 | 说明 |
|------|------|
| 确定性 DCF 计算 | FinRobot 没有自动化 DCF 模型 |
| LBO 分析 + IRR/MOIC | FinRobot 完全没有 |
| Sensitivity 分析 | WACC × TG 7×7 矩阵 + LBO entry × exit 矩阵 |
| 交互式假设调整 | Sliders 实时重算 |
| 多源数据交叉验证 | Revenue/EBITDA 15% 阈值自动告警 |
| Desktop 应用 | Electron + React 19 现代 UI |
| 命令面板 | Cmd+K 全局搜索 |

---

### 四、行动建议（按视觉影响力排序）

> 每条标注: 工作量 (XS/S/M/L) · 视觉影响 (1-5 星) · 是否需要改 DESIGN-SYSTEM.md

#### 1. 提取内联样式到共享 CSS 类 — `XS-M` · ⭐⭐⭐⭐⭐ · 不需要

**这是 ROI 最高的一件事。** 消除 5 个 summary 组件中 ~160 个内联样式对象，统一为 8 个共享 CSS 类。视觉一致性立即提升一个档次，且后续所有改动（如调 padding 从 12px 到 16px）只需改一处。

新增 CSS 类:
- `.data-table` / `.data-table th` / `.data-table td` — 统一所有表格
- `.hero-header` — valuation-hero 内部的两端对齐头部布局
- `.hero-ticker` — 1.4rem mono 700 金色 ticker 标题
- `.metric-pill` — beat/miss/rating 等状态 badge
- `.action-bar` — 底部操作按钮栏

受影响文件: LBOSummary, CompsSummary, EarningsSummary, ResearchSummary, PipelineRunner

#### 2. PriceChart + MarginTrendChart 面积渐变填充 — `XS` · ⭐⭐⭐⭐⭐ · 不需要

**视觉冲击力最大的单一改动。** 裸线图 → 面积渐变填充图。PriceChart 加 `<Area>` + `<linearGradient>`, MarginTrendChart 每条线下加渐变。总共改 ~20 行代码。

这是截图分享时一眼就能感知的区别。Koyfin、TradingView、Bloomberg 的价格图全部使用面积填充。

#### 3. 卡片 elevation 系统 (3 级阴影) — `XS` · ⭐⭐⭐⭐ · 需要更新

3 个 CSS 变量 + 3 行选择器:
```css
--shadow-sm: 0 1px 3px rgba(0,0,0,0.3);
--shadow-md: 0 4px 16px rgba(0,0,0,0.4);
--shadow-lg: 0 24px 80px rgba(0,0,0,0.5);

.card { box-shadow: var(--shadow-sm); }
.valuation-hero { box-shadow: var(--shadow-md); }
```

需要在 DESIGN-SYSTEM.md 中更新"阴影最多一层"规则为"3 级 elevation"。

#### 4. Pipeline 连接线 — `XS` · ⭐⭐⭐⭐ · 不需要

CSS `::before` 伪元素在步骤左侧画竖线。完成段变绿，运行中段变金色。把 PipelineRunner 从 "todo list" 升级为 "timeline"。PipelineRunner 是用户等待时盯着看最久的组件，视觉品质直接影响等待焦虑。

#### 5. Loading Skeleton 动画 — `S` · ⭐⭐⭐⭐ · 不需要

一个 `.skeleton` CSS 类 + shimmer 动画。在 StockOverview/FinancialsPanel 加载态使用骨架 div 替代 "Loading..." 文本。消除 layout shift + 消除文本 loading 的廉价感。

#### 6. 表头 sticky — `XS` · ⭐⭐⭐ · 不需要

一行 CSS: `thead th { position: sticky; top: 0; }`. 影响所有 `.fin-table` / `.data-table`。金融表格的基本功能。

#### 7. 空状态升级 — `S` · ⭐⭐⭐ · 不需要

Idle 状态加:
- 键盘快捷键提示条
- 5 个热门 ticker 按钮
- 最近分析列表（前 3 条）

从"空白页面"变成"邀请页面"。

#### 8. 全局键盘快捷键 — `S` · ⭐⭐⭐ · 不需要

在 App.tsx 添加 `1-5` 切换 pipeline, `Cmd+Enter` 运行, `Cmd+H` 历史, `Cmd+,` 设置。让高级用户可以不碰鼠标。

#### 9. 暴露后端已有图表 (Cash Flow / EV Band / Revenue YoY / Quarterly) — `M` · ⭐⭐⭐ · 不需要

后端有 4 种图表类型已实现但 Desktop 没有对应组件。补齐后右面板内容丰富度显著提升。

#### 10. 命令面板 "Recent" section — `S` · ⭐⭐ · 不需要

在 appStore 加 `recentCommands`，CommandPalette 空查询时优先显示。提升重复操作效率。

---

### 五、DESIGN-SYSTEM.md 建议更新

以下规则需要修改以匹配精品化目标:

| 当前规则 | 建议修改 | 原因 |
|---------|---------|------|
| "不用阴影层叠，阴影最多一层" | "3 级 elevation: sm/md/lg" | 全平卡片缺乏深度，影响专业感 |
| "不使用渐变色（估值卡片顶线除外）" | "图表面积填充渐变允许（opacity 3-15%）" | 这是金融图表的行业标准视觉，不是"花哨" |
| 无阴影变量 | 新增 `--shadow-sm/md/lg` CSS 变量 | 统一阴影规范 |
| 无骨架屏规范 | 新增 `.skeleton` shimmer 动画规范 | 替代所有 "Loading..." 文本 |

---

### 六、关键洞察总结（Round 13）

**发现 1: 内联样式是视觉债的 80%。** 不是设计方向错了，是执行不一致。5 个 summary 组件有 ~160 个内联样式对象，每个都是一个不一致的种子。提取成 8 个 CSS 类后，组件代码减少 30-40%，视觉一致性自动达成。这是改一次、受益永远的投入。

**发现 2: 两个 XS 级改动就能让截图质量翻倍。** (1) PriceChart 面积渐变填充 — 10 行代码；(2) 卡片 3 级阴影 — 6 行 CSS。这两个改动加起来不到 30 分钟工作量，但在截图中的视觉冲击力占所有改动的 50%+。

**发现 3: FinRobot 最大的数据优势是社交情绪。** Reddit/StockTwits 抓取是 FinRobot 有而 FinAgent 完全缺失的唯一高影响力功能。Earnings Call 转录分析也很重要但优先级略低。FinAgent 在 DCF/LBO/Sensitivity 等确定性计算上已全面超越 FinRobot。

**发现 4: 键盘优先的交互是金融工具的核心 UX。** Bloomberg Terminal 的用户可以不碰鼠标完成全部工作流。FinAgent 目前只有 Cmd+K。添加 `1-5` pipeline 切换 + `Cmd+Enter` 运行，就能让高级用户的操作速度提升 3x。

**本轮最值得做的一件事**: 提取内联样式到共享 CSS 类。ROI 最高——代码质量 + 视觉一致性 + 后续改动效率同时提升。

---
