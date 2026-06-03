# FinAgent 全量审查 · 改进清单（REVIEW_FINDINGS.md）

> **本轮只读审查，未改动任何源代码/配置/依赖。** 本文件是给下一会话逐条修复用的可执行清单。
>
> **方法**：dynamic workflow 扇出 4 维度（正确性/产品/机会/架构）× 各模块 →每条发现交独立 agent 对抗反驳 → 收敛 3 轮（含完整性批评者补缺口）→ 去重定稿。
> **规模**：130 条发现扛过对抗验证 → 去重为 **106 条**（缺陷 84：Bug 67 / 产品 17；机会 22）。每条均经独立验证，非臆测。
> **缺陷严重度分布**：P0×2 · P1×38 · P2×31 · P3×13
> **ID 稳定编号**：BUG-xxx（含架构硬隐患）/ UX-xxx（产品）/ OPP-xxx（机会）。各区块内按优先级排序。

---

> ## 🚨 修复前必读 · 给按「状态」领活的会话
>
> **① BUG-075 与 BUG-086 是「原子对」，必须同一次改、一起验、一起标已修——中间不留任何窗口。**
> - BUG-075（13F 列名 PascalCase 不匹配）现在让 `institutional_holdings` **全空**，恰好挡住了 BUG-086。
> - BUG-086（取数脚本无条件再 `×1000`）一旦取数能进，机构持仓金额 **1000 倍高估**（$250M→$250B）。
> - **若你只修了 075 就标已修、没同时修 086 → 立刻吐 1000 倍错的美元数进 artifact**，砸"不编数字"的招牌。两条放在同一个 commit 里改。
>
> **② BUG-071 ~ BUG-086 来自 2026-06-03 第二轮『运行时/环境/外部基准/领域口径』专项审计**（见下方对应区块的同名横幅），全部 `reproduced=True` 真复现过。
>
> **③ 多会话共享工作树：动手前先重新 Read 本文件**（拿到含 BUG-071~086 的最新版），状态翻转只用定点 Edit 改那一行 `待修`→`已修`，别整段覆盖。

---

## 一、执行摘要

### 如果只做这几件事，产品就会发生质变

1. **先裁决并统一首屏核心任务：单股深研 vs 覆盖盘运营两套心智同屏未分胜负，是当前最大的体验税也是一切下游设计的总开关。** — CoveragePage 默认 filter='needs_action' + 注释『the triage queue IS the homepage』把首屏定义成『管理一篮子覆盖标的的回访分诊台』，但同屏顶部 CoverageHero 又是 40px FINROBOT 大字 + 单搜索框的冷启动获客姿态（UX-014/UX-001）。两个 40px hero + 一整面分诊墙并置、不告诉用户先看哪个；而权威产品文档（docs/UI设计.md / 前端结构文档）还停在已退役的 /stocks landing，落后代码两个版本。boss 要求里根本没有『Coverage Desk / 分诊』这个概念——它只活在代码和一份 research spec 里。不先由 boss 拍板主回路并回填权威文档，所有 UX/动线优化都是在未定义的地基上施工。
2. **把『搜一支股 → 读到 13 章研报』的首份 wow 做成一条零岔路引导动线，砍掉冷启动逼建组和完成后多余一次点击。** — 这是产品唯一真正不可替代的 wow（ChatGPT 给不了可溯源投行级研报），但当前被拆散：CoverageEmptyState 先逼用户『建组』而非直接搜（UX-001/UX-007 假空态），研报跑完 AIZone 停在 hot 卡还要在两个并存『打开』按钮里再点一次才进正文（UX-002）。冷启动用户最该被惊艳的临门一脚，现在是 4-5 步 + 一次犹豫。建组其实已由 useAddStudiedTicker 后台静默完成——把它前置成唯一路径，让 Coverage Desk 用第一份真实研报做 onboarding，而不是空状态讲概念。
3. **让 IC 投委会从『藏在三级页 + 用完即焚』升级为可发现、可落盘的一等公民研究产物。** — IC 是最高差异化能力（确定性 DCF+LBO 驱动的双边辩论），却三重受困：唯一入口埋在 equity_research 研报 toolbar（ReportToolbar onOpenIcDebate 仅此处，OPP-006），结果故意不持久化刷新即蒸发（IcDebatePage EphemeralNotice），且可落盘的 ic-memo pipeline 全 UI 不可达（OPP-001）。AIZone 的 ARTIFACT_TYPE_LABEL 已为 ic_memo 预留标签——把辩论落成 ic_memo artifact 进 timeline/Coverage 卡留痕、并把入口提到 Inspector/热卡一级，一次性把死代码盘活成 star 级工作流。
4. **修复『可溯源』承诺在代码层的几处静默失守：盈利惊喜整条失效、跨境估值错币种、provider 同源不一致只 warn 不仲裁。** — 这三条直接戳破核心价值主张（『报错一个数字=砸招牌』）：FMP earnings provider 调错端点/读错字段名导致 earnings_history 对所有 ticker 永远为空、盈利惊喜分析静默失效（BUG-001 P0）；comps forward 路径用 USD 归一化同业 P/E × 申报币种 forward EPS，TSM/ASML/BABA 等 ADR 目标价整体偏一个汇率（BUG-006）；DataLayer 跨 provider 仅 warn 不仲裁、容差 15% 结构性低于已知 FMP↔yfinance 25-80% 实差，分歧票静默把 primary 原值印进研报（BUG-007）。可溯源是这个产品对 ChatGPT 的硬差异化，一个错数字比缺功能更致命。
5. **补齐键盘/读屏可达性与渲染兜底——目标用户是终端式不离键的买方/量化研究员，纯鼠标 demo 跌破其肌肉记忆基准线。** — Coverage 卡片墙 <article> 无 tabIndex/role/onKeyDown，键盘与读屏用户无法聚焦任何卡片，连带 Inspector 的全部研报/历史/Run 动作不可达（BUG-002 P0）；Coverage Desk 全程零 hover 反馈、缺 j/k 巡航（UX-011/OPP-007）；研报阅读页/HotState 在 live 应用树无 ErrorBoundary（已实现的只挂在 HTML 导出 viewer），任意渲染崩溃即整页白屏（BUG-028）。这些不是锦上添花——对终端式操作的专业买方,不可达 = 不可用。

### 现有设计中真正做得好、修复时不要误伤的点

- 数字可溯源在代码里真实兑现而非口号：MarketDataZone 每张财务卡都挂 ProvenanceFootnote（显 provider/period_end/degraded 标记），是对 ChatGPT 最硬的差异化，修复时务必保留这条溯源链。
- Live price 与 at-run entry_price 的『冻结并排、永不互相覆盖』设计（CoverageInspector：entry_price 冻结于报告生成时、与 live price 并排）是诚实披露的典范，正确表达了『研报是某时点快照』的金融常识。
- ArtifactDetailPage 强制以 artifact.ticker 而非 URL ticker 为真相源 + canonical 重定向，从结构上防止串报——金融数据完整性的正确防线。
- verdict==='REVIEW' 用来表达『数据健康门控扣留目标价』，而非硬印一个不可信数字——把『宁可说我需要核对、绝不编一个数字』的职业信条做进了产品状态机。
- MarketDataZone 与 AIZone 解耦：行情区与 AI 区互不依赖，5xx 时单卡显 CardError+retry 而非整页崩——确定性数据层与 LLM 叙事层的边界在前端被正确尊重。
- run 状态走 runStreamStore 跨路由存活（SSE EventSource 不随导航中断），用户跑研报时可自由切页，重型异步任务的状态管理方向正确。
- ComparePage 对没有 DCF 的 ticker 显示『先跑 DCF』而不编数字，AIZone OtherArtifacts 对缺失类型做诚实兜底——『没有就说没有』的克制贯穿到了边缘态。
- 退役路由（/stocks landing、/dashboard 等）保留一个发布窗口的重定向而非硬删,迁移节奏对用户友好（注意 BUG-067:迁移 toast 实际无人读取,需顺手接上而非误删这套机制）。

---

## 二、缺陷与问题清单

| ID | 类别 | 严重度 | 一句话问题 | 状态 |
|---|---|---|---|---|
| BUG-001 | Bug | P0 | FMP earnings provider calls wrong endpoint / reads wrong field names → earnings_history is ALWAYS empty for every ticker (silent dead feature) | 已修 |
| BUG-002 | Bug | P0 | Coverage 卡片墙纯鼠标可达：<article> 无 tabIndex/role/onKeyDown，键盘用户无法聚焦任何卡片，连带整个 Inspector（研报/历史/Run 动作）对键盘/读屏完全不可达 | 已修 |
| BUG-003 | Bug | P1 | Live API key persisted in plaintext to session JSONL via provider warning → tool_result transcript | 已修 |
| BUG-004 | Bug | P1 | Entire FastAPI surface is unauthenticated and Host-header-unvalidated — DNS rebinding lets any web page drive secret-writing/quota-burning endpoints despite the CORS whitelist | 待修 |
| BUG-005 | Bug | P1 | PUT /api/settings can silently delete or overwrite the user's live API keys (FMP/Anthropic/OpenAI) with no auth and no confirmation | 待修 |
| BUG-006 | Bug | P1 | 跨境 forward 估值口径错币种:comps_pe 的 forward 路径用『USD 归一化同业 P/E × 申报币种 forward EPS』,ADR(TSM/ASML/BABA)目标价整体偏离一个汇率 | 待修 |
| BUG-007 | Bug | P1 | DataLayer 跨 provider 仅 warn 不仲裁,且 cross_validate 容差(revenue 15%)结构性低于已知 FMP↔yfinance 25-80% 实差——分歧票静默采用 primary(FMP)原值进研报 | 待修 |
| BUG-008 | Bug | P1 | Finnhub provider 把缺失的 total_debt/total_cash 用 `or 0` 伪造成 0 → 下游 EV 误算成「零净债」（违反 FMP 显式遵守的 None≠0 契约） | 已修 |
| BUG-009 | Bug | P1 | xbrl_concept_snapshot 把所有年度营收硬编码成 us-gaap:Revenues，对绝大多数大盘股(ASC-606 口径)是错误的 concept 标签 | 已修 |
| BUG-010 | Bug | P1 | XBRL TTM dict 丢弃 period_end/as_of_date 与 has_calculated_q4/warning，下游无法判定 TTM 截止季与质量 | 已修 |
| BUG-011 | Bug | P1 | _money_from_text 把孤立的 'm' 当成 million 乘子(无词边界),$96 measured→$96M,且 ×1e6 可把 sub-$1M 原值抬过合理性闸门 | 已修 |
| BUG-012 | Bug | P1 | CEO 姓名/总薪酬/pay-ratio 三字段各自独立 first-match 抽取,无任何一致性勾稽,可把张冠李戴/跨年度/口径不符的三元组当权威披露并排展示 | 已修 |
| BUG-013 | Bug | P1 | earnings.py float(row.get('revenue_actual',0)) crashes (TypeError) on present-but-None revenue, and otherwise fabricates $0 revenue → false -100% surprise | 已修 |
| BUG-014 | Bug | P1 | DCF graceful-degrade (tg≥WACC) self-defeats: technical_analysis hard-requires DCFResult and crashes the whole equity_research run one step later | 已修 |
| BUG-015 | Bug | P1 | Thesis & peer-selection wrap recoverable AgentRunError into ValueError, defeating the retry/back-off system and aborting the whole run on the first transient LLM hiccup | 已修 |
| BUG-016 | Bug | P1 | 自由文本叙事字段（valuation_overview/tagline/key_takeaways/competitor_analysis）无 code 级与 canonical target/verdict 对账，结构化标量被强制覆盖而散文不被——表格与散文可冲突 | 待修 |
| BUG-017 | Bug | P1 | Chat-triggered pipelines bypass the app-wide concurrency semaphore — LLM can fire unbounded parallel heavy runs | 待修 |
| BUG-018 | Bug | P1 | Scoped coverage-group hit-rate silently truncates to the GLOBAL newest-500 page → groups show null track record despite having one | 待修 |
| BUG-019 | Bug | P1 | Sharpe ratio uses backtrader default timeframe=Years on daily bars → None for ~1yr windows, meaningless for multi-year | 已修 |
| BUG-020 | Bug | P1 | CLI 全部 pipeline 命令零 ticker 校验/归一化：脏 ticker 直灌 provider + 污染缓存与 artifact | 已修 |
| BUG-021 | Bug | P1 | backtest --auto 对 LLM 失败无任何兜底：直接裸崩，也不回退确定性策略 | 待修 |
| BUG-022 | Bug | P1 | 零 busy_timeout + 多进程写同一 data_cache.db → SQLITE_BUSY 直接抛到调用方 | 已修 |
| BUG-023 | Bug | P1 | Artifact PRIMARY KEY 用秒级时间戳，同票同类型同秒 run 静默覆盖前一份研报（审计链断档） | 已修 |
| BUG-024 | Bug | P1 | useAppStore (547 行) ~92% 死状态：仅 4 个 CmdK 字段有运行时消费方，其余全部无人读 | 待修 |
| BUG-025 | Bug | P1 | Pipeline 集合在 4 处各自硬编码（orchestrator/registry/cli/sdk），registry 抽象只被 runs.py 单独使用 | 待修 |
| BUG-026 | Bug | P1 | DCF/DDM seed 用「最近 2 年」中位数，却在 provenance 和 docstring 里全程标注「过去 3 年中位数」——给分析师看的口径说明是假的 | 待修 |
| BUG-027 | Bug | P1 | POST /api/compute/dcf-sensitivity 的 wacc_range/tg_range 无 max_length 上限 → 巨网格阻塞事件循环 | 已修 |
| BUG-028 | Bug | P1 | No ErrorBoundary in the live app tree — any render crash blanks the whole desktop app | 已修 |
| BUG-029 | Bug | P1 | Competitive table renders unguarded gross/operating margin → fabricated 0.0% or literal NaN% when backend value is null | 已修 |
| BUG-030 | Bug | P1 | 13 章研报全程硬编码 $，而 Coverage 是币种感知——非美元标的会印错币种符号 | 待修 |
| BUG-031 | Bug | P1 | Coverage 批量运行 >6 个 ticker 时耗尽浏览器 HTTP/1.1 连接池，多余的 SSE 与所有普通 API 轮询被无限阻塞 | 待修 |
| BUG-032 | Bug | P1 | Coverage overview 全量 fetch 失败但 fast skeleton 成功时，卡片市场列永久空白——无错误态、无 shimmer、无重试入口 | 已修 |
| BUG-033 | Bug | P1 | Chat tools and /api/runs accept unvalidated ticker strings while a SoT ticker validator already exists in coverage — junk symbols fan out to live providers | 已修 |
| BUG-073 | Bug | P1 | DCF/DDM 绝对估值对外币 ADR 零 FX 归一化:营收(申报币 TWD/EUR)与市值/股本(USD)混算,implied_price 本币计价却当 USD 印出并比价(TSM ~32x 高估)——comps 路径已修,绝对估值路径漏修 | 待修 |
| BUG-077 | Bug | P1 | SkillRegistry._load_all 只 catch SkillLoadError 不 catch pydantic ValidationError——一个字段类型写错的 SKILL.md(外部/partner 技能常见)使 server/SDK/CLI 启动整体崩,违背其 fail-soft 设计 | 待修 |
| UX-001 | 产品 | P1 | 冷启动首份研报动线被拆成两条不相通的入口，且 Starter 终点是空墙而非一份研报 | 待修 |
| UX-002 | 产品 | P1 | 首份研报跑完后还要手动点一次才能阅读——"第一次惊艳"被一次多余点击拦住 | 待修 |
| UX-003 | 产品 | P1 | TickerNotFound 的「返回」按钮指向已退役的 /stocks，触发二次重定向 + 错误的合并提示 | 待修 |
| UX-004 | 产品 | P1 | 投委会辩论跑完是死胡同：无任何 next-step CTA + 用完即焚 | 待修 |
| UX-005 | 产品 | P1 | "待处理"分诊是首屏，但卡片不说"为什么需要我"——理由被挤进一个截断的小药丸 | 待修 |
| UX-006 | 产品 | P1 | 无法删除/归档单份历史研报——后端有 DELETE 端点，前端零入口，跑错/作废的研报永久堆积 | 待修 |
| UX-007 | 产品 | P1 | 冷启动时已有覆盖的老用户会闪现「还没有 ticker——在上方添加」假空态 | 待修 |
| BUG-034 | Bug | P2 | SSE run.completed / run.failed can be lost: status flips to terminal in the DB before the terminal event is appended, so the poll loop may break and never emit it | 待修 |
| BUG-035 | Bug | P2 | SDK 的 provider 链漏注册 NewsAggregatorProvider，与 build_data_layer 漂移 | 待修 |
| BUG-036 | Bug | P2 | Football Field 的 DCF 区间永远是装饰性 ±20%:_dcf_band 读错字段,Monte Carlo P10/P90 分支是死代码,source 标签可误导 | 待修 |
| BUG-037 | Bug | P2 | 外币 SEC 申报人的 XBRL 营收/净利未做 FX 换算即被当作 USD，35% 散度门可能漏掉近平价货币 | 待修 |
| BUG-038 | Bug | P2 | peer 倍数白名单用未格式化原始 float 注入（median_pe/pe_ratio/market_cap），LLM 在 competitor_analysis 里复述时口径/精度无锚，且与前端表格显示口径不保证一致 | 待修 |
| BUG-039 | Bug | P2 | `is_sampled` compares against GLOBAL store count, not the in-window / in-scope population → mislabels fully-covered windows as 'partial' | 待修 |
| BUG-040 | Bug | P2 | Cumulative total_return shown beside annualized-intent Sharpe; annualized Returns analyzer added but never read | 待修 |
| BUG-041 | Bug | P2 | run_strategy_selection tunes 3 iterations on one in-sample window and reports max(total_return) as a 'good' strategy — pure overfitting, no out-of-sample | 待修 |
| BUG-042 | Bug | P2 | Sniper LONG mode: secondary_buy (20-day support) can sit BELOW stop_loss → incoherent trade row passes invariant guards | 待修 |
| BUG-043 | Bug | P2 | Unauthenticated POST /chat, /api/runs and /api/coverage/groups/{id}/runs burn metered LLM credits with zero inbound rate limiting | 待修 |
| BUG-044 | Bug | P2 | Unauthenticated DELETE /api/artifacts/{id} and DELETE /api/coverage/groups/{id} permanently destroy stored research | 待修 |
| BUG-045 | Bug | P2 | ProviderHealth 熔断器是完全未接线的死代码，docstring 谎称「DataLayer owns the wiring」——慢/限流 provider 每次仍付满超时 | 待修 |
| BUG-046 | Bug | P2 | 硬编码中文数据层告警混入英文 CLI 输出(--lang en 不生效于 provider 告警) | 待修 |
| BUG-047 | Bug | P2 | comps --peers 校验滞后且不验格式：错峰到管线中段(已耗 ~30s)才裸崩 | 待修 |
| BUG-048 | Bug | P2 | archive_stale 全表 get()+save() 逐行重写整份 payload，O(N) 次完整 JSON 反序列化+序列化 | 待修 |
| BUG-049 | Bug | P2 | data_cache.cache 表永不淘汰,只增不减(无 TTL 清理/容量上限) | 待修 |
| BUG-050 | Bug | P2 | run_events 无限增长 + SSE 0.2s 轮询单连接 → 批跑下打满单库单锁 | 待修 |
| BUG-051 | Bug | P2 | 前端 pipeline 类型清单三处不一致：appStore 缺 ddm，runStreamStore/后端 registry 含 ddm | 待修 |
| BUG-052 | Bug | P2 | query_financial_data raises an unguarded ValueError on a bad data_type, crashing the live chat SSE stream | 待修 |
| BUG-053 | Bug | P2 | coverage.ts 的 req() 丢弃后端中文 detail 错误体，分组/成员操作失败时用户拿不到具体原因 | 待修 |
| BUG-054 | Bug | P2 | 研报版本切换 <select> 用 opacity:0 覆盖层实现：键盘 Tab 落上去零可见焦点指示，用户看不到焦点在哪 | 待修 |
| BUG-055 | Bug | P2 | 归档（30天自动 stale）的研报混进所有版本列表且零视觉标识——用户分不清『还在跟踪』和『已作废』的版本 | 待修 |
| BUG-056 | Bug | P2 | 研报版本切换器/时间线/Diff 候选只取 timeline 默认 50 条，与 Inspector History(200) 不一致——重度跟踪的 ticker 老版本在报告页内不可达 | 待修 |
| BUG-057 | Bug | P2 | Compare 表把不同时间跑出的 DCF 混在同一张表,且不显任何 vintage/as_of——用户无法判断哪行是今天的、哪行是三周前的 | 待修 |
| BUG-068 | Bug | P2 | 回测对 A股标的零适配(T+1/涨跌停/印花税/停牌全缺)却照常产出净值曲线——A股结果根本不可信,应在入口直接 raise 拒跑而非 warn | 待修 |
| BUG-070 | Bug | P2 | artifact 盖 git_commit 戳的 subprocess except 抓错异常类型(只抓 ImportError/Attr/Type/Value)——git 缺失(FileNotFoundError)/超时(TimeoutExpired)未捕获,无 git 环境(pip 安装用户/Docker slim/CI)研报落地最后一步直接崩 | 待修 |
| BUG-071 | Bug | P2 | FMP _fetch_price 的 price_history 用未复权原始 close(没走 _adjust_fmp_bar),而 _fetch_price_range/yfinance 都已复权——FMP 当 PRICE 主源时 52周高低/SMA 落在名义价上,近一年有拆股的标的 52周高直接 ×拆股比 | 待修 |
| BUG-074 | Bug | P2 | DCF 末年 FCF 为负时 Gordon 终值把负现金流资本化成永续负值→产出负的『每股公允价值』,degrade 分支只防 tg≥WACC 接不住,负价无 guard 直接进研报叙事+LLM prompt | 待修 |
| BUG-075 | Bug | P2 | 13F refresh job 假设 edgartools 小写列名,实装 5.31.5 输出 PascalCase(Cusip/Issuer/Value)→ 每份 filing 被 schema gate 跳过,institutional_holdings 永久空(缓存 0 行),测试 mock 小写列所以 CI 绿 | 待修 |
| BUG-078 | Bug | P2 | agent 工厂/orchestrator 用无 encoding 的 read_text() 读含中文的 .md 指令文件——非 UTF-8 locale(裸 Docker LANG=C/Windows)下 agent 创建即 UnicodeDecodeError 崩;同仓 skills/loader.py 已带 encoding,这两处漏写 | 待修 |
| BUG-079 | Bug | P2 | semantic_diff.build_semantic_delta 对 data_fetched_at 裸做 datetime 相减,一新(tz-aware)一旧(naive)时抛 TypeError→版本对比端点 500;全 artifact/audit 面仅此处漏 _ensure_tz(同胞模块都防了) | 待修 |
| BUG-080 | Bug | P2 | /{ticker}/earnings-calls 构造 EarningsCallTranscript 的循环在 try/except 外,FMP 真实 payload 的 quarter 缺失/为 0(年度会/特别会)触发 ValidationError 逃逸→裸 500,而非 per-item 跳过 | 待修 |
| BUG-081 | Bug | P2 | /{ticker}/price 的 session_state 对所有标的硬编码美东 9:30-16:00 ET 判定→港股/A股/日股盘中被错标『已收盘』,freshness pill 把实时报价显示成上一交易日收盘(与 BUG-030 同源:平台多处默认美国市场) | 待修 |
| BUG-082 | Bug | P2 | `finrobot dcf <ticker>` 默认路径死锁:_should_use_ddm 的 asyncio.run 把 DataCache 的 aiosqlite 连接绑到随后销毁的 loop,第二个 asyncio.run 复用同连接→worker 线程绑死锁,进程退出时永久 hang(单 loop 测试测不出) | 待修 |
| BUG-086 | Bug | P2 | [休眠·须与 BUG-075 同修] 13F value 双倍 ×1000:edgartools 5.31.5 已把 Value 归一化成整美元,refresh 脚本 line 102 又无条件 ×1000→机构持仓金额 1000 倍高估($250M 显示成 $250B);当前被 BUG-075 列名 bug 挡住未触发,BUG-075 一修即吐错数 | 待修 |
| UX-008 | 产品 | P2 | HotState 裁决为 REVIEW 时目标价静默消失，不解释『为什么扣留』 | 待修 |
| UX-009 | 产品 | P2 | 一支股票→多份历史研报的下钻要 3+ 步且断裂——卡片『N 份研报』不可点，发现历史得先进 workspace 再滚到底 | 待修 |
| UX-010 | 产品 | P2 | Compare 必须回 Coverage 多选才能发起——workspace/研报页内无"加入对比"入口 | 待修 |
| UX-011 | 产品 | P2 | Coverage Desk（新首页）全程零 hover 反馈，质感跌破全 App 基准线 | 待修 |
| UX-012 | 产品 | P2 | Coverage Inspector 的 Live/Report 面板丢失溯源——同一数字在卡上可溯、点进去不可溯 | 待修 |
| UX-013 | 产品 | P2 | `/api/dashboard/hit-rate` + useDashboardHitRate are orphaned after the homepage declutter — track-record panel has no live caller | 待修 |
| UX-014 | 产品 | P2 | 首屏产品身份分裂：populated 态顶 FINROBOT 大字、empty 态顶 Coverage Desk，同一页两套品牌/心智 | 待修 |
| BUG-058 | Bug | P3 | Non-critical steps emit a misleading step.completed (green ✓) after exhausting all retries on a real failure | 待修 |
| BUG-059 | Bug | P3 | Validation-failure retries re-run deterministic executors unchanged, burning the full retry budget on identical failing output | 待修 |
| BUG-060 | Bug | P3 | DCF/Monte Carlo 把 Gordon 终值在中年法下按 (n-0.5) 折现——终值『定价日』应是年末 n,这里多折了半年,系统性高估 fair value | 待修 |
| BUG-061 | Bug | P3 | Earnings-call tab selection keyed by array index — duplicate/reordered transcripts collide keys and mis-select | 待修 |
| BUG-062 | Bug | P3 | `is_sampled` / `sample_size` honesty disclosure is dropped at the API→frontend boundary (field absent from the TS contract) | 待修 |
| BUG-063 | Bug | P3 | _resolve_strategy does importlib.import_module(user_string) + getattr before the bt.Strategy check — arbitrary module import with side effects | 待修 |
| BUG-064 | Bug | P3 | _extract_drawdown accepts a warnings list but never uses it — silent None drawdown with no warning, inconsistent with siblings | 待修 |
| BUG-065 | Bug | P3 | 镜像列(verdict/entry/target/tagline)在 extractor 逻辑演进后无回填路径，旧行永久陈旧 | 待修 |
| BUG-066 | Bug | P3 | 禁用态按钮的『为什么不可用』只靠 title tooltip：disabled 元素不触发 hover、tooltip 鼠标专属，键盘/触屏用户拿不到原因（IC 辩论 & Compare） | 待修 |
| BUG-067 | Bug | P3 | 退役路由的「已合并」提示 toast 写进 sessionStorage 但全代码无人读取——功能彻底失效且 router 注释撒谎 | 待修 |
| BUG-069 | Bug | P3 | 回测渲染图时弹出 matplotlib GUI 窗口(Figure 0)并泄漏 figure——模块级 use("Agg") 时机太晚未生效 | 待修 |
| BUG-072 | Bug | P3 | NewsAggregatorProvider 唯一免 key 源 Yahoo RSS headline feed 已被雅虎下线(404),默认无 AV key 配置下该 provider 100% 抛错(被 FMP NEWS 兜住故非必现),工厂注释『uses Yahoo RSS (free, no key)』撒谎 | 待修 |
| BUG-076 | Bug | P3 | Sniper coherence gate 比的是原始 float、ship 的是 round(2) 值——target 与现价相差 <$0.005 时 ideal_buy==take_profit、R/R=0、warning 印出『$372.80 < $372.80』自相矛盾的退化交易行,gate 不 raise 故 _safe_sniper 接不住 | 待修 |
| BUG-083 | Bug | P3 | ~/.finrobot/.secrets 权限偏离 0600(备份还原/编辑器重写/umask 漂移)时,严格等值校验抛未捕获 PermissionError→server 启动崩,无自愈无降级(明文 FileSecretStore 兜底路径:headless/CI/Docker/dev) | 待修 |
| BUG-084 | Bug | P3 | PriceTrendChart 窗口首日收盘价为 0 时 1Y 涨跌幅药丸渲染成 'Infinity%'、Y 轴 domain 被 0 基准拉歪——后端 contracts/data.py 同一除法都有 prev==0 守卫,唯独前端图无(provider 停牌/稀疏日可能给 close=0) | 待修 |
| BUG-085 | Bug | P3 | 已完成的 run 永不从 runStreamStore 清除(clear() 无调用方),StockWorkspace 是路由挂载组件、去重 key 是组件级 useRef——切走再回每次重弹『报告已生成』toast + 3 次 query invalidation 强制重拉 | 待修 |
| UX-015 | 产品 | P3 | 最高曝光的 Run CTA / Pipeline 徽章用字面量 color:'white' 与裸数字圆角，绕过已存在的 token | 待修 |
| UX-016 | 产品 | P3 | prefers-reduced-motion 只关了星空一种动效，shimmer/pulse/halo/skeleton 等仍全速运行 | 待修 |
| UX-017 | 产品 | P3 | 右侧 AI 抽屉与 CmdK 的 "Ask AI" 是两条并存的对话入口，语义重叠且互不打通 | 待修 |

### 详细条目（Bug）

#### [BUG-001] FMP earnings provider calls wrong endpoint / reads wrong field names → earnings_history is ALWAYS empty for every ticker (silent dead feature)

- **类别**：Bug
- **严重度**：P0
- **位置**：finrobot/engine/data/providers/fmp_provider.py:579-601 (_fetch_earnings)
- **现象/问题**：The entire earnings-surprise analysis (beat rate, EPS surprise, revenue surprise, consecutive beats) silently produces empty/zero output for EVERY ticker. The 'earnings' pipeline reports 'Quarters analyzed: 0', 'Beat rate: 0%' for AAPL, NVDA, everything — an analyst-facing feature that looks alive but never returns real data.
- **证据**：Live-verified with the repo .env FMP key: GET https://financialmodelingprep.com/api/v3/earnings-surprises/AAPL returns 109 rows whose keys are ['date','symbol','actualEarningResult','estimatedEarning'] (sample: {"date":"2026-04-30","actualEarningResult":2.01,"estimatedEarning":1.95}). The provider (lines 587-593) reads item.get('epsActual'), item.get('epsEstimated'), item.get('revenueActual'), item.get('revenueEstimated') and filters `if item.get('epsActual') is not None and item.get('epsEstimated') is not None`. None of those keys exist on this endpoint, so every row evaluates the eps fields to None and is dropped. Replicating the exact provider mapping against live data: 109 raw rows → 0 rows after filter. The CORRECT endpoint is https://financialmodelingprep.com/stable/earnings?symbol=AAPL whose rows DO carry ['epsActual','epsEstimated','revenueActual','revenueEstimated'] (live-verified).
- **根因**：First error site is fmp_provider.py:582 `self._get(f'/earnings-surprises/{ticker}')`: the code was written against the field schema of the `stable/earnings` (or v3 historical earning_calendar) endpoint but points at the legacy v3 `/earnings-surprises/` endpoint which uses a completely different schema (actualEarningResult/estimatedEarning, no revenue at all). The empty result then propagates: earnings_analysis.py:53 gets [], calculate_earnings_surprises returns the all-zero EarningsResult branch (earnings.py:28-36). No test caught it because tests/unit/test_earnings.py feeds the compute fn correctly-shaped dicts directly and there is no test of _fetch_earnings.
- **修复方案**：In fmp_provider.py:_fetch_earnings switch the request to the stable earnings endpoint that exposes eps+revenue: change line 582 to call the stable host path `GET /stable/earnings?symbol={ticker}&limit=N` (note: stable is a different base than _BASE_URL='/api/v3', so either add a _STABLE_BASE constant + a host-aware _get, or use the full URL). Keep the eps None-filter (line 593) but ALSO None-guard revenue before float() — see the paired revenue-None finding. Add a unit test in test_fmp_provider.py mocking the stable response shape (with epsActual/revenueActual present) asserting earnings_history is populated, plus a live smoke note. Note: stable/earnings returns FUTURE quarters with epsActual=null,epsEstimated set — the existing eps None-filter correctly drops those.
- **验证补充**：Fix is correct (point _fetch_earnings at stable/earnings, needs _STABLE_BASE since stable is not under /api/v3). Also update test_fmp_provider.py's _fmp_earnings_response/null-eps fixtures to the stable response shape (they currently already use the post-mapping eps*/revenue* keys, masking the bug); add a live smoke note. Verify httpx _get host handling: _get hardcodes _BASE_URL at line 705, so a host-aware _get or full-URL path is mandatory, not optional.
- **影响面/回归风险**：Restores the entire earnings pipeline (1 of the registered pipelines). Regression risk low: change is isolated to one provider method + its (currently absent) test. Must verify the stable endpoint is in the account's plan tier; if not, fall back to v3 /historical/earning_calendar/{ticker} which also carries eps+revenue keys.
- **置信度**：high　|　**状态**：已修（改了 `finrobot/engine/data/providers/fmp_provider.py`：新增 `_STABLE_BASE` 常量；`_get` 加 host-aware `base=` 参数（默认 v3）；`_fetch_earnings` 改调 `GET stable/earnings?symbol={ticker}&limit=40`，base=_STABLE_BASE，保留 eps None-filter 丢弃未来季。`tests/unit/test_fmp_provider.py`：新增 `test_fetch_earnings_hits_stable_endpoint`（断言命中 stable host + symbol param，防回退到 legacy /earnings-surprises）与 `test_earnings_preserves_null_revenue`。**Live-verified（仓库 .env FMP key）**：本账户 tier 有 stable/earnings 权限（200，schema 含 epsActual/revenueActual），无需 v3 fallback；端到端 `FMPProvider.fetch('AAPL','earnings')`→39 季真实数据，`calculate_earnings_surprises` 得 beat_rate=79% / avg_eps=+7.6% / consec_beats=4（修前全 0）。ruff+mypy --strict 通过。)

#### [BUG-002] Coverage 卡片墙纯鼠标可达：<article> 无 tabIndex/role/onKeyDown，键盘用户无法聚焦任何卡片，连带整个 Inspector（研报/历史/Run 动作）对键盘/读屏完全不可达

- **类别**：Bug
- **严重度**：P0
- **位置**：ui/src/components/coverage/CoverageCard.tsx:99-135（<article onClick>）+ CoverageCardGrid.tsx:61-96（grid 无 roving）+ CoveragePage.tsx:386-394
- **现象/问题**：首屏 Coverage Desk 的卡片是一个 <article>，onClick={() => onFocus(row.ticker)} 触发『聚焦此 ticker』，而右侧 CoverageInspector 的内容（Live/Report/History 三 tab + Run/Open/Compare/Remove）完全由 focusedTicker 决定。但这个 <article> 没有 tabIndex、没有 role=button、没有 onKeyDown，CoverageCardGrid 也没有 roving tabindex/方向键导航。结果：键盘用户（Tab 流）根本无法把焦点落到任何卡片上，也就永远无法切换 Inspector 聚焦的标的——首屏最核心的『选一个标的看详情』动作对键盘/读屏用户 100% 不可用。读屏软件还会把卡片读成无语义的一坨文本（<article> 里塞了价格/verdict/指标但没有可激活的语义）。
- **证据**：复现：打开 /coverage，只用键盘 Tab。焦点会跳过所有卡片正文，只能落在卡片内的 checkbox（input，166-171）和右下角 ▶/↗ IconButton（453-474，这俩是真 <button>）。无论怎么按方向键/Enter/Space 都无法改变 focusedTicker → Inspector 永远停在 visibleRows[0]（CoveragePage.tsx:104 的默认聚焦），用户无法用键盘查看第 2…N 个标的的 Live/Report/History。对比同文件内的 checkbox 和 IconButton 都是原生可聚焦元素，唯独承载主交互的卡片本体不是。
- **根因**：CoverageCard.tsx:103 把『聚焦』这个主交互直接挂在 <article> 的 onClick 上，把卡片当 div 用而非可激活控件；第一个出错位置就是这一行——缺少配套的 tabIndex={0} / role + onKeyDown(Enter|Space)，且 grid 层（CoverageCardGrid.tsx）从未实现方向键 roving。这是把鼠标点击当成唯一输入通道的设计遗漏。
- **修复方案**：改 CoverageCard.tsx 的 <article>（99-135）：加 role="button"、tabIndex={0}、aria-pressed={focused}、onKeyDown={(e)=>{ if(e.key==='Enter'||e.key===' '){ e.preventDefault(); onFocus(row.ticker) } }}，并补一条 :focus-visible 描边（现有 border 已随 focused 变色，但键盘焦点需独立可见环——用 outline: 2px solid var(--border-glow) 或在 App.css 加全局 [role=button]:focus-visible 规则，禁硬编码 hex）。注意：checkbox(167) 和 IconButton(375/384) 已 stopPropagation，键盘 Enter 落在它们身上不会冒泡触发 onFocus，无冲突。进阶（中等改动量，约 40 行）：在 CoverageCardGrid.tsx 实现方向键 roving tabindex（↑↓←→ 在卡片间移动焦点 + 同步 onFocus），让分诊墙真正可键盘巡航；最小修复只做单卡可聚焦+Enter 激活即可解 P0。
- **验证补充**：Fix is correct (role=button + tabIndex=0 + onKeyDown Enter/Space + aria-pressed + :focus-visible ring via token, no hardcoded hex). stopPropagation on checkbox(167)/IconButtons(376/385) confirmed, so no bubble conflict. Caveat on severity: for a no-live-users stars project the P0 label is aggressive, but given the explicitly professional-analyst target it is a legitimate full-blocker — keep P0.
- **影响面/回归风险**：影响首屏全部键盘/读屏用户与可访问性合规；回归风险低——只新增 a11y 属性与键盘分支，不改鼠标路径与现有 stopPropagation 逻辑。需补一条 RTL/键盘测试断言卡片可 focus 且 Enter 改 focusedTicker。
- **置信度**：high　|　**状态**：已修（改了 `ui/src/components/coverage/CoverageCard.tsx` 的 `<article>`：加 `role="button"` / `tabIndex={0}` / `aria-pressed={focused}` / `onKeyDown` Enter|Space→`onFocus(row.ticker)`；`ui/src/App.css` 加全局 `[role='button']:focus-visible` 焦点环用 `var(--border-glow)`（无硬编码 hex，独立于 focused 边框色）。**额外修正**：原方案假设 inner checkbox/IconButton 的 stopPropagation 能防双触发——那只挡 onClick，键盘 keydown 仍冒泡，故在 onKeyDown 加 `e.target !== e.currentTarget` 守卫，避免在 checkbox 上按 Space 同时切 Inspector 焦点。CoverageCardGrid 方向键 roving 因 `auto-fill` 响应式列数需运行时测量、有改选中逻辑风险，按方案『有风险即跳过』**跳过**（最小修复已清 P0：每张卡都是 tab stop + Enter 激活，键盘/读屏可达）。验证：`npm run lint` 零报错、`npm run build`（tsc）通过。)

#### [BUG-003] Live API key persisted in plaintext to session JSONL via provider warning → tool_result transcript

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/audit/transcript.py:152-178 (log_tool_result writes result verbatim) ← finrobot/server.py:583-592 ← finrobot/engine/data/interface.py:27-30 (to_context_string embeds warnings) ← finrobot/engine/data/providers/news_aggregator.py:79-82,156-168 (apikey-in-URL ProviderError → warnings)  ·  （另涉：finrobot/engine/data/providers/fmp_provider.py:702 + 679-680（_get 把 apikey 放 query string；_wrap_errors 把 HTTPStatusError 包成 ProviderError(...{e}...)）；finrobot/engine/data/providers/news_aggregator.py:159 + 168；泄漏落点 finrobot/engine/data/layer.py:88/124/149/289/365 logger.warning(...{e}...)；finrobot/obs/{filters,formatters,middleware,setup}.py 全链无 redact ; finrobot/engine/data/providers/news_aggregator.py:80-83（`warn = f"{source_name} fetch failed: {result}"` 同时 append 进 warnings）→ interface.py:20-31 to_context_string 把 warnings 拼进 LLM 上下文；DataResult.warnings 在 routes/sentiment.py:98、routes/data.py:117 等处直接进 API 响应）
- **现象/问题**：A live Alpha Vantage API key can be written in cleartext to ~/.finrobot/sessions/<id>.jsonl and kept there forever. The transcript is an independent persistence sink from the obs logger (already-known leak), so scrubbing the logger does not close this one.
- **证据**：Confirmed full chain: news_aggregator._fetch_alpha_vantage passes the key as a URL param (`params={...,"apikey": self._av_key}`, line 156-159). On HTTP error it raises `ProviderError(f"Alpha Vantage HTTP error...: {e}")` (line 168). I verified with httpx that `str(httpx.HTTPStatusError)` renders `Client error '403 Forbidden' for url 'https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers=AAPL&apikey=<KEY>'` — the key is in the string. That ProviderError is NOT swallowed: NewsAggregator runs sub-fetches under `asyncio.gather(return_exceptions=True)` and appends `f"{source_name} fetch failed: {result}"` to `warnings` (line 80-82), returning them on the DataResult. `query_financial_data` tool returns `result.to_context_string()` (orchestrator.py:73-74), which appends every warning verbatim (interface.py:27-30). server.py:583-589 takes that string as `content` and calls `log_tool_result`, which writes it raw into the JSONL (transcript.py:165-178 — the `model_dump` branch is skipped for plain strings). No redaction exists anywhere in the chat/transcript path (grep for redact/scrub/sanitize/mask in finrobot/audit + server.py returns nothing). File mode 0o600 limits OS-level exposure but the secret is still durably on disk in cleartext, survives key rotation, and is readable by anything running as the user (backups, sync, other tools).
- **根因**：First defect is the provider error formatting: news_aggregator.py:165-168 (and the same pattern in fmp_provider.py:678-689, fx.py) interpolates the raw httpx exception — whose str() contains the full request URL incl. apikey query param — into a user-facing ProviderError that is then surfaced into DataResult.warnings rather than only into a server-side log. The transcript writer is the durable sink that turns a transient warning into a permanent plaintext secret because it does zero redaction (transcript.py has no scrubbing of any kind).
- **修复方案**：Two-layer fix. (1) Stop the key reaching any string at the source: in finrobot/engine/data/providers/news_aggregator.py:165-168, finrobot/engine/data/providers/fmp_provider.py:678-689, and finrobot/engine/data/providers/fx.py — never interpolate the raw httpx exception. Use the status code + sanitized path only, e.g. `raise ProviderError(f"Alpha Vantage HTTP {e.response.status_code} for '{ticker}'") from e` (drop `{e}`); for non-status errors use `type(e).__name__`. (2) Defense-in-depth redaction at the durable sink: add a module-level scrubber in finrobot/audit/transcript.py applied inside `_write_event` before json.dumps that regex-replaces `(?i)(api[_-]?key=)[^&\s"']+` and `X-API-Key`/`X-Finnhub-Token` header values with `\1[REDACTED]`, walking str leaves of the data dict. Note: scrubber must run on the data dict recursively (warnings live nested under data['result'] which itself is a string), and must be cheap (these strings can be large — see disk-growth finding). Prefer fixing (1) as primary; (2) guards future provider code. Magnitude: small (≈30 lines across 3 provider files + one helper in transcript.py).
- **验证补充**：Fix is correct for news_aggregator + fmp_provider but OVERCLAIMS fx.py: fx._fmp_quote_price swallows httpx.HTTPError→None (lines 77-78) and fetch_fx_rate_to_usd's ProviderError (139-143) does NOT interpolate {e} (only currency/ticker names) — no leak there, so the fx.py edit is unnecessary/should be dropped. Also: when ALL news sources fail, news_aggregator raises ProviderError (line 91-92) carrying the same key, surfaced via the 'error' event not tool_result — so the layer-2 transcript scrubber must run on ALL event payloads (error/warnings nested), confirming the finding's own note. Layer-1 source fix (drop {e}) remains the primary, correct fix.
- **影响面/回归风险**：Security/secret-handling. Affects every chat session that triggers a news/sentiment fetch failure while an Alpha Vantage (or any URL-param-keyed) provider key is configured. Regression risk low: removing `{e}` from ProviderError messages only reduces debug detail in warnings (full detail still goes to logger.warning at layer.py:88 path); the scrubber is additive. Verify existing provider-error tests don't assert on the exact `{e}` substring.
- **合并自**：gap-r1-5#1, gap-r1-5#4, gap-r2-4#1（3 条同源发现）
- **置信度**：high　|　**状态**：已修（Layer1（源头）：fmp_provider._wrap_errors 与 news_aggregator._fetch_alpha_vantage 去掉 raw httpx 异常 {e} 插值（含 ?apikey= 的 URL），改用 status code + ticker/type(e).__name__，保留 from e。Layer2（兜底）：audit/transcript.py 在唯一写入口 _write_event 前加递归 _scrub_data，对 str 叶子正则脱敏 apikey=、X-API-Key/X-Finnhub-Token（覆盖所有事件类型，含 error 事件的嵌套 warnings）。按 review 修正 fx.py 不动（已证不泄漏）。新增 transcript/provider/news 泄漏测试。ruff+mypy --strict + 全量 1986 通过）

#### [BUG-004] Entire FastAPI surface is unauthenticated and Host-header-unvalidated — DNS rebinding lets any web page drive secret-writing/quota-burning endpoints despite the CORS whitelist

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/server.py:330-340 (app+CORS, no TrustedHostMiddleware); all of finrobot/routes/* (grep 'Depends' in routes/ returns zero hits)
- **现象/问题**：The whole backend's trust model is 'bound to 127.0.0.1 + CORS whitelist'. There is NO request authentication of any kind (no Depends/Security/Authorization/Bearer/cookie/CSRF token anywhere — the shared-context claim that 'only settings.py has Depends' is factually wrong; it is zero). The only middlewares are RequestTraceMiddleware and CORSMiddleware. CORS protects cross-origin *reads* and forces a preflight for cross-origin JSON XHR, but it does NOT protect the server against (a) DNS rebinding — an attacker domain that re-resolves to 127.0.0.1, after which the browser treats the attacker page as SAME-origin and CORS no longer applies at all — because there is no Host-header allowlist (no TrustedHostMiddleware); and (b) any other local process (curl, a second Electron/Tauri app, malware, a browser extension) which CORS never touches. Once the boundary is crossed, the attacker can PUT /api/settings (overwrite/delete the user's live LLM+FMP API keys, flip model routing), POST /api/runs + POST /api/coverage/groups/{id}/runs and POST /chat (burn the user's metered LLM credits), POST /api/sec-holdings/refresh (trigger a multi-minute full-quarter SEC download that can get the user's IP throttled by EDGAR), and DELETE /api/artifacts/{id} / DELETE /api/coverage/groups/{id} (destroy stored research).
- **证据**：server.py:328-340 shows the only middlewares are RequestTraceMiddleware + CORSMiddleware(allow_origins=[localhost:5173,127.0.0.1:5173]); no TrustedHostMiddleware. `grep -rn Depends finrobot/routes/ finrobot/server.py` returns nothing → no per-route auth. cli.py:685 defaults host=127.0.0.1 (loopback-only is the SOLE control). DNS-rebind repro: attacker page on evil.com (TTL 1s) → first resolve to attacker IP serves JS, then re-resolves evil.com→127.0.0.1; browser now sees fetch('http://evil.com:8321/api/runs',{method:'POST',body:JSON,headers:{'Content-Type':'application/json'}}) as same-origin → preflight passes → run spawns. Local-process repro: any other program runs `curl -X PUT http://127.0.0.1:8321/api/settings -d '{"fmp_api_key":""}'` and wipes the key (settings.py:167-171 deletes the secret when value is falsy).
- **根因**：First point of failure: the design decision at server.py:330-340 to treat 'loopback bind + browser CORS' as the complete trust boundary, with no defense-in-depth (no Host allowlist, no shared-secret token between sidecar and UI). The CORS comment at server.py:332-333 reveals the mental model — it reasons only about browser cross-origin, never about same-origin-via-rebind or non-browser local callers.
- **修复方案**：Two-layer defense in server.py. (1) Add Starlette TrustedHostMiddleware with allowed_hosts=['127.0.0.1','localhost'] (and the chosen --host) so any request whose Host header isn't a loopback name is 400'd — this kills DNS rebinding because the rebind request still carries Host: evil.com. (2) Add a startup-generated capability token: cli.py generates a random token at sidecar launch, passes it to the Tauri shell (it already passes --parent-pid via a private channel) and the shell injects it as a header into every fetch; server.py adds one global dependency (app-level `dependencies=[Depends(verify_local_token)]` on include_router, or a tiny ASGI middleware) that 401s requests lacking the header. This is the real auth the 'only-localhost' note at server.py:328 has been deferring. Note: do NOT rely on CORS for this — preflight is defeated by rebind and absent for non-browser callers. Scope: ~1 new middleware + token plumbing through cli.py↔Tauri (~60-100 LoC across server.py, cli.py, ui/src-tauri sidecar spawn, and ui/src/api/client.ts to attach the header).
- **验证补充**：Fix is sound. Caveat on the token-plumbing half: I could NOT locate the Tauri sidecar spawn (no .rs files surfaced, no externalBin in tauri.conf at the expected path); cli.py accepts --parent-pid but the UI-side passing of it as a 'private channel' is unverified, so the ui-side LoC for the token is less certain than 60-100. TrustedHostMiddleware alone is cheap, verifiable, and kills the rebind vector — land that first independent of token plumbing.
- **影响面/回归风险**：Affects every endpoint (16 routers). Regression risk on the token layer: the Vite dev server (5173) and any test/SDK caller must learn to send the token, or they 401 — must update ui/src/api/client.ts, the dev proxy, and conftest test clients. TrustedHostMiddleware alone is low-risk (loopback names already in use) and can ship independently as the high-value/low-cost half.
- **置信度**：high　|　**状态**：待修

#### [BUG-005] PUT /api/settings can silently delete or overwrite the user's live API keys (FMP/Anthropic/OpenAI) with no auth and no confirmation

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/routes/settings.py:140-195 (put_settings_route), :167-171 (delete on falsy value)
- **现象/问题**：PUT /api/settings is unauthenticated (see finding 1) and accepts partial updates via model_dump(exclude_unset=True). For any secret field present in the body with a falsy value, the handler calls secret_store.delete(key) (settings.py:170-171), and for any present truthy value it overwrites the keychain entry (settings.py:169). A single forged PUT therefore destroys the user's stored live credentials (the repo ships a real .env with live FMP keys per project memory). Because keys live in the OS keychain / a 0600 .secrets file, an overwrite/delete is not recoverable from settings.json. There is also no audit trail of who changed a key.
- **证据**：settings.py:144 payload=update.model_dump(exclude_unset=True); :147 secret_updates pulls only present fields; :167-171 `for key,value in secret_updates.items(): if value: set else: delete`. So body {"fmp_api_key":""} → delete; {"anthropic_api_key":"sk-attacker"} → overwrite. validate_runtime_config() at :163 only checks the *merged candidate* is internally consistent — it does not stop a deletion if the merged config still validates (e.g. another provider's key is still present).
- **根因**：This endpoint is a privileged secret-management surface but sits behind the same zero-auth boundary as read-only data endpoints (root cause = finding 1's missing auth). Secondary: delete-on-falsy is implicit (empty string == 'remove key') with no explicit intent flag, so even a malformed legitimate client can wipe a key.
- **修复方案**：Primary fix is the global auth token from finding 1 — once present this endpoint is no longer reachable by hostile callers. Independently, in settings.py harden the delete path: require an explicit sentinel (e.g. a separate POST /api/settings/clear-secret with the field name, as the existing /reset pattern at :198 already does for non-secrets) rather than overloading empty-string-in-PUT to mean delete; this prevents accidental client wipes.注意: don't break the legitimate 'user cleared the field in SettingsView to remove a key' UX — route that through the explicit clear endpoint and update ui SettingsView accordingly.
- **验证补充**：Both fixes valid. Primary fix is finding-0 auth. The secondary 'explicit clear endpoint instead of empty-string-means-delete' is a genuine UX/safety hardening (prevents accidental client wipes) and mirrors the existing /reset pattern at settings.py:198 — good. Ensure ui SettingsView's 'clear field to remove key' flow is rerouted, as the finding notes.
- **影响面/回归风险**：Affects key management only. Regression risk: SettingsView's current 'clear field to delete key' interaction must move to the explicit endpoint or it stops working; covered by existing settings route tests which must be updated.
- **置信度**：high　|　**状态**：待修

#### [BUG-006] 跨境 forward 估值口径错币种:comps_pe 的 forward 路径用『USD 归一化同业 P/E × 申报币种 forward EPS』,ADR(TSM/ASML/BABA)目标价整体偏离一个汇率

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/engine/compute/valuation_aggregator.py:202-206 (_comps_pe_method used_forward 分支);forward_eps 源 finrobot/engine/compute/forward_estimates.py:177;无 FX 归一,valuation.py:69 直接透传
- **现象/问题**：_comps_pe_method 在 used_forward 分支算 `mid = peer_comps.median_pe * forward_eps`。median_pe 是 peer 集合经 normalize_peer_to_usd 归一到 USD 后算出的同业中值 P/E(无量纲,但隐含 USD 口径);current_price 也是 USD。但 forward_eps 来自 FMP /v3/analyst-estimates 的 estimatedEpsAvg,forward_estimates.py docstring 明确写『per-share, reporting currency』——对台积电是 TWD、ASML 是 EUR、阿里是 CNY。USD 同业倍数 × 申报币种每股收益 = 量纲不一致的目标价,然后和 USD current_price 比,直接错一个汇率(TSM 约 32x)。
- **证据**：valuation_aggregator.py:203 `mid = peer_comps.median_pe * forward_eps`,source 串自称『as-reported 同业 P/E』但完全没提币种。forward_estimates.py:155-160 注释 `"estimatedEpsAvg": 12.5, # per-share, reporting currency`。整条链路 grep 无 fetch_fx / reporting_currency 介入 forward_eps:valuation.py:58/69 `forward = await _forward_financials(...)` → 直接 `forward_eps=forward.forward_eps` 透传给 aggregator,中间无归一。已修的 BUG-018 只归一了 target 的 trailing 口径(normalize_company_to_usd),forward 这条新路径绕过了它。
- **根因**：forward_estimates 这个红线 leaf 只负责选 FY1 行、取原始 consensus 数,从不做币种归一(设计如此);而 aggregator 假定 forward_eps 与 median_pe/current_price 同币种(对美股成立),对外国发行人这个假设破裂,且没有任何 currency tag 流到 aggregator 让它发现不一致。
- **修复方案**：两选一:(A) 在 forward_estimates._from_fmp 返回的 ForwardFinancials 上加 reporting_currency 字段(从 financial_data.reporting_currency 或 FMP 行的 reportedCurrency 取),aggregator 在 _comps_pe_method 里当 reporting_currency != 'USD' 时,先 await fetch_fx_rate_to_usd(ccy) 把 forward_eps 乘汇率归 USD 再 × median_pe;(B) 若不想让 leaf 触网,在 valuation.py:_forward_financials 拿到 reporting_currency 后就地归一 forward_eps→USD 再传入。注意:aggregator 当前是纯同步 leaf,方案 A 需让其 async 或预先在 route 归一(倾向 B,保持 aggregator 纯净)。同时 _ev_ebitda_method/_p_fcf_method 用 forward_ebitda/forward_fcf 也有同样隐患,虽目前 band=None 永远隐藏,修时一并处理避免日后接 PR3 复发。[金融待核] 外部核对:取 TSM,FMP /v3/analyst-estimates 的 estimatedEpsAvg 看是否为 TWD(对照 TSM 10-F 的 TWD EPS 量级,约 40-50 TWD 而非 ~7 USD ADR EPS),确认币种;再人工算 USD 同业 P/E × USD-归一 EPS,核对是否 ≈ 当前 ADR 价。
- **验证补充**：Fix direction sound. Prefer option B (normalize forward_eps→USD in valuation.py:_forward_financials before passing to the aggregator) over option A — keeps the aggregator a pure synchronous leaf, matching the codebase's existing 'normalize at the route/extractor boundary, not in the leaf' pattern. Must source reporting_currency (FinancialData.reporting_currency or FMP reportedCurrency) and call fetch_fx_rate_to_usd. The finding is right that forward_ebitda/forward_fcf carry the same latent bug; fix them in the same pass even though band=None hides them today, so PR3 wiring doesn't silently ship the defect. One caveat: the aggregator's used_forward source label already discloses the multiple's caliber but says nothing about currency — add a currency note or the USD normalization, not just a label.
- **影响面/回归风险**：只影响外国发行人(ADR/外股)的 Football Field comps_pe 行——会给出离谱的目标价(偏一个汇率)且不报错、不隐藏,误导分析师。美股不受影响(USD/USD)。回归风险低(美股路径不变);需为 TSM 类外国票加 FX 归一测试。
- **置信度**：high　|　**状态**：待修

#### [BUG-007] DataLayer 跨 provider 仅 warn 不仲裁,且 cross_validate 容差(revenue 15%)结构性低于已知 FMP↔yfinance 25-80% 实差——分歧票静默采用 primary(FMP)原值进研报

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/engine/data/layer.py:122-136 (fetch financials 分支) + finrobot/engine/data/validator.py:31-38 (_RELATIVE_FIELDS 容差)
- **现象/问题**：fetch() 对 financials 抓两个 provider 后调 cross_validate,但结果只是把 discrepancy 字符串塞进 warnings,primary_result(provider 链里第一个成功者=FMP)的数值无条件胜出并被缓存进 canonical。project-memory 已记录 FMP vs yfinance 差异 25-80% 是 critical 待修。这里的真实隐患是:当两源差 30% 时,validator 会发一条 warning,但 primary 的(可能错的)数字照样进 normalize→canonical→DCF/comps,LLM 拿到的是带 warning 的硬数字而非『需人工核对、暂不出数』。即口径分歧没有阻断 artifact 落地,只是加了句免责。
- **证据**：layer.py:122 `discrepancies = cross_validate(primary_result, result)` → 125-129 只 merge 进 warnings,primary_result 数值不变;134-136 `await self._cache.set(...); return primary_result`。validator.py:31-38 revenue/ebitda/net_income/debt/cash 容差 0.15。这些 warning 经 fetch_canonical:219-221 挂到 NormalizedFinancials.warnings,再经 extractor.py:147-149 进 FinancialData.warnings——但数字仍是 primary 的。无任何代码在分歧时改用 SEC XBRL 仲裁或停止出数(xbrl_aligned_comps 的 _reconcile_ttm 只在 comps 那条路、且只比 XBRL↔FMP,不覆盖 DCF seed 的 fetch_canonical 主路径)。
- **根因**：架构上 fetch() 的 financials 分支把 cross-provider 一致性降级为『告警』而非『仲裁/阻断』,且没有 source-of-truth 优先级(SEC XBRL > FMP > yfinance)。primary 由 provider 注册顺序决定,与哪个更准无关。
- **修复方案**：这是架构级、project-memory 已标 critical 且建议先 spec 的项,不应在本轮直接动代码——[金融待核] + 走专项 spec。最小可落地的诚实化:在 fetch_canonical 把 cross_validate 触发的『关键字段(revenue/net_income)超容差』标进 NormalizedFinancials.provenance.degraded(而非仅 warnings),让下游 dcf_seed/comps 能据此把对应 assumption 标 [金融待核] 或降 confidence,而不是当作可信硬数字。真正仲裁(定 SEC XBRL=SoT、按 fiscal date 对齐 TTM)需单独 spec(project-memory 已有此结论)。外部核对方案:取一只已知分歧票(如 project-memory 记录的样本),分别 curl FMP /v3/income-statement?period=quarter 求和 4 季 TTM net_income 与 yfinance info net_income,再对 SEC 10-Q XBRL us-gaap:NetIncomeLoss rolling-4Q,确认谁对、差在 TTM vs FY 口径还是单位。
- **验证补充**：Agree with the finding's restraint: do NOT build SoT arbitration this round (needs a dedicated spec; project-memory already concludes this). The minimal honest improvement is correct and worth doing — when a key field (revenue/net_income) exceeds tolerance, push a structured marker into Provenance.degraded (the field exists, contracts.py:55) rather than only free-text warnings, so dcf_seed/comps can down-confidence or tag [金融待核] programmatically instead of relying on an LLM to read prose. Note Provenance.degraded is currently an enum-style list (contracts.py:36-55 'structured fallback markers'); adding a cross-provider-divergence marker means extending that enum, a small but real schema touch, not free.
- **影响面/回归风险**：影响所有两源分歧票的 DCF/comps 数字可信度(用 primary=FMP 原值)。当前有 warning 兜底但不阻断。回归风险:若把关键字段超容差升级为 degraded/阻断,可能让一批边缘票从『出数+告警』变成『拒绝出数』,需 boss 确认产品取向(分析师宁可看到带标注的数 vs 宁可不看到错数)。属需 spec 项,不宜本轮硬改。
- **置信度**：high　|　**状态**：待修

#### [BUG-008] Finnhub provider 把缺失的 total_debt/total_cash 用 `or 0` 伪造成 0 → 下游 EV 误算成「零净债」（违反 FMP 显式遵守的 None≠0 契约）

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/engine/data/providers/finnhub_provider.py:135-136（`total_debt = _find_concept("bs", "LongTermDebt") or 0` / `total_cash = ... or 0`）、:141（ebitda `(operating_income or 0)+(da or 0)`）；消费链 finrobot/engine/compute/extractor.py:103-104 + finrobot/engine/compute/multiples.py:67-69
- **现象/问题**：Finnhub 解析 SEC filing 时，若 XBRL 缺 LongTermDebt / CashAndCashEquivalents 概念，`or 0` 把「数据缺失」伪造成「债务为 0 / 现金为 0」。extractor.py:103 的 EV 守卫是 `raw_debt is not None and raw_cash is not None`——FMP 缺数据时传 None 故正确跳过 EV，但 Finnhub 传 0（not None），守卫被骗通过，EV 被算成 `market_cap + 0 - 0 = market_cap`，把一家有真实负债的公司当成零净债，污染 EV/EBITDA、EV/Revenue。当未配 FMP key 时 Finnhub 是 FINANCIALS 主源，直接进研报。
- **证据**：finnhub_provider.py:135 `total_debt = _find_concept("bs", "LongTermDebt") or 0`；同文件 FMP 对照（fmp_provider.py:307 注释明写 "None ≠ 0: a missing balance-sheet line must stay None so enterprise value is left undefined rather than fabricated (market_cap + 0 - 0)"，传 `bal.get("totalDebt")` 即 None）。extractor.py:96-104 注释 "no defaulting missing components to 0" + 守卫 `if raw_debt is not None and raw_cash is not None:` → 对 0 失效。calculate_ev = market_cap + total_debt - cash（multiples.py:69）。data_layer_factory.py:51-53 确认 Finnhub 在 FINANCIALS 链第 2 位，无 FMP 时即为 primary。
- **根因**：第一出错位置是 finnhub_provider.py:135-136 的 `or 0`——producer 端破坏了 consumer 端（extractor/multiples）已正确建立的 None≠0 契约。这是已修「None≠0 整簇」遗漏的新文件：bug 追踪两份清单 grep finnhub 只命中 WebSocket 文案(BUG-20260602-042)，本条未登记。
- **修复方案**：finnhub_provider.py:135-136 改为 `total_debt = _find_concept("bs", "LongTermDebt")`、`total_cash = _find_concept("bs", "CashAndCashEquivalentsAtCarryingValue")`（去掉 ` or 0`，让缺失保持 None）。:141 ebitda 同理：da 缺失时不应 `+0` 静默低估，改成 `operating_income + da if (operating_income is not None and da is not None) else None`。:127-128 `marketCapitalization, 0` / `shareOutstanding, 0` 的 `, 0` 默认也应去掉（:147/:148 已有 `if mkt_cap_millions else None` 守卫，但 :127 的 `, 0` 让该守卫永远为真——一并修）。注意：LongTermDebt 只是总债的一部分，真正口径需对照（见下），但至少不能把缺失当 0。
- **验证补充**：Drop `or 0` on :135-136 and gate ebitda on :141 — correct. The finding ALSO correctly flags (and defers) a real caliber issue: `LongTermDebt` alone undercounts total debt (excludes current portion / short-term debt / leases) vs FMP's `totalDebt` rollup — so even with None-preservation, when present the Finnhub total_debt is systematically too low. That is a separate [金融待核] item the finding rightly does not try to fully fix here. The :127-128 `, 0` cleanup is valid: `profile.get('marketCapitalization', 0)` makes the :147 `if mkt_cap_millions else None` guard reachable only via a real 0, which is fine, but removing the `, 0` default is the cleaner None-honest form. Severity raised P2→P1: silent fabrication of a core valuation input that enters the report unflagged is a砸招牌 data-correctness defect, same class as [0].
- **影响面/回归风险**：影响所有未配 FMP、靠 Finnhub 出 FINANCIALS 的安装的 EV 类估值。回归风险：会让一些此前「错误地算出 EV」的 ticker 变成「EV 留空」——这是正确行为（宁缺毋滥），但前端需确认 EV=None 的降级展示已就绪（multiples.py:189 已支持 None）。加测试：Finnhub filing 缺 LongTermDebt → result.total_debt is None 且 enterprise_value is None。[金融待核] LongTermDebt 单概念是否等于公司总债（含短债/租赁）需对照 SEC 10-K 资产负债表（如 AAPL FY2023 10-K 的 Total term debt = Current portion of term debt + Non-current term debt），核 Finnhub financials-reported 返回的 bs 段是否还有 ShortTermBorrowings/CurrentPortionOfLongTermDebt 概念需合并。
- **置信度**：high　|　**状态**：已修（finnhub_provider.py：total_debt/total_cash 去掉 or 0（缺失保持 None）；ebitda 改 operating_income+da if 二者非 None else None；marketCapitalization/shareOutstanding 去掉 ,0 默认（让既有 if...else None 守卫可达）。新增 tests/unit/test_finnhub_provider.py::TestFinnhubNonePreservation 3 例（缺 debt/cash→None 经 normalize 仍 None→EV 守卫跳过；缺 D&A→ebitda None）。[金融待核] LongTermDebt 单概念欠总债口径，按指示不在本条修。ruff+mypy --strict + 20 例通过）

#### [BUG-009] xbrl_concept_snapshot 把所有年度营收硬编码成 us-gaap:Revenues，对绝大多数大盘股(ASC-606 口径)是错误的 concept 标签

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/engine/compute/xbrl_aligned_comps.py:119-129 (annual concept 映射) + 注入 LLM 见 equity_research.py:159,714,763  ·  （另涉：finrobot/engine/compute/xbrl_aligned_comps.py:127-136 + equity_research.py:763-764）
- **现象/问题**：snapshot 把 latest_revenue 的 us-gaap concept 一律标成 "us-gaap:Revenues"，但该值实际由 edgartools EntityFacts.get_revenue() 解析得到，其 concept 优先级第一个是 RevenueFromContractWithCustomerExcludingAssessedTax。AAPL/MSFT/GOOGL 等后 ASC-606 口径公司的营收 fact 真实 concept 是 RevenueFromContractWithCustomerExcludingAssessedTax，根本不是 Revenues。snapshot 给出的 concept 标签与数值真实出处不符。
- **证据**：edgartools 源码 EntityFacts.get_revenue() 的 concept_variants 顺序为 [RevenueFromContractWithCustomerExcludingAssessedTax, SalesRevenueNet, Revenues, Revenue, TotalRevenues, NetSales]，命中第一个有值的；该库自身注释(本仓库 sec.py:56-58)亦写明 AAPL/MSFT/GOOGL 都报在 RevenueFromContractWithCustomerExcludingAssessedTax 下。而 xbrl_aligned_comps.py:120 把 latest_revenue 写死映射到 us-gaap:Revenues。snapshot 经 equity_research.py:159 注入，并在 763 行作为可引用的权威 SEC concept 喂给 LLM("只能引用 xbrl_facts_snapshot.* 的数字")，再经 builders.py:396 落地 artifact。
- **根因**：xbrl_concept_snapshot 在第 119-126 行用一张静态 (key→concept) 表给年度点值贴 concept，而没有从 provider 取回真实命中的 concept 名。第一个出错位置是 edgar_provider._fetch_xbrl(909 行) 只返回 _float("get_revenue") 的裸值、丢弃了 get_revenue 内部命中的 concept，导致 snapshot 无从知道真实 concept 只能猜。
- **修复方案**：两步：(1) edgar_provider._fetch_xbrl 改用 return_detailed/get_revenue_detailed 或 facts.get_fact 取回命中的真实 concept 字符串(连同 period_end/unit)，把 latest_revenue 等改为 {"concept":真实命中, "value":..., "period_end":..., "units":...} 的 dict 而非裸 float；(2) xbrl_aligned_comps.py:119-136 删除静态 concept 表，直接透传 provider 给的真实 concept。注意 SECCompanyFacts/XBRLFact(sec.py:61) 已定义正确字段(concept/period_end/units 必填)——producer 应向该模型对齐。改动量级：中(provider 取数层 + snapshot 构造层两处协同)。
- **验证补充**：Fix direction correct (carry the matched concept). Tactical note: get_revenue_detailed() returns a UnitResult (unit_handling.py:49-58) which does NOT expose the matched concept name — only value/normalized_unit/original_unit. To recover the real concept use get_fact()/get_annual_fact() over the same concept_variants and read FinancialFact.concept (+period_end/unit/fiscal_period), or wrap the variant loop locally. Don't assume return_detailed alone yields the concept.
- **影响面/回归风险**：影响所有研报的 company_overview/估值叙事里被 LLM 引用并标注来源的 SEC 营收数字——分析师会看到 "us-gaap:Revenues" 而真值出自另一 concept，属可溯源性失真(投行级研报的核心卖点)。回归风险低：仅改 concept 字符串与补字段，数值不变。
- **合并自**：gap-r1-1#1, gap-r1-1#4（2 条同源发现）
- **置信度**：high　|　**状态**：已修（edgar_provider._fetch_xbrl 不再丢弃命中 concept：新增 _select_latest_fact() 走 get_annual_fact/get_fact 遍历各 getter 的 concept_variants 优先级，返回 {concept,value,period_end,units}（对齐 sec.py XBRLFact）；7 个 latest_* 字段（P&L annual / BS 非 annual）都带真实 concept。xbrl_aligned_comps.xbrl_concept_snapshot 删除静态 concept 静态表，透传 provider 真实 concept，拒绝 legacy 裸 float。Live 验证 AAPL get_revenue 命中 us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax（非旧标的 Revenues），值 416.161B 对上 FY2025 10-K。与 BUG-010 同提交。）

#### [BUG-010] XBRL TTM dict 丢弃 period_end/as_of_date 与 has_calculated_q4/warning，下游无法判定 TTM 截止季与质量

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/engine/data/providers/edgar_provider.py:271-318 (_select_recent_ttm) + 905-906
- **现象/问题**：_select_recent_ttm 返回的 TTM dict 只含 {concept, value, periods}，丢掉了 edgartools TTMMetric 已算好的 as_of_date(TTM 最新季 period_end)、has_gaps、has_calculated_q4、warning。下游 xbrl_concept_snapshot/override_company_with_xbrl 拿不到 TTM 截止日期，artifact 无法显示 "TTM 截至哪个季度"，也无法把 edgartools 自己标的数据质量告警(如 Q4 是 FY-YTD 推导出来的、季度有缺口)透出。
- **证据**：edgartools TTMMetric dataclass 字段含 as_of_date/has_gaps/has_calculated_q4/warning(已读源码确认)；TTMCalculator.calculate_ttm 会对推导 Q4/缺口生成 warning。但 edgar_provider.py:312-316 只挑了 concept/value/periods 三项；sec.py:71-84 定义的 XBRLTTMMetric 本意要 periods 形如 ["Q3 2025",...] + component_provenance，与 provider 实际产出的 periods=[{"year":..,"quarter":..}] 形状也不一致。recency gate 用 _metric_latest_period_end 重新遍历 period_facts 求 period_end，等价于现成的 as_of_date，重复劳动且没把这个日期保留下来。
- **根因**：_select_recent_ttm 第 312-316 行构造返回 dict 时只保留三个键，未把 metric.as_of_date 与质量标志一并带出；第一个出错位置即此构造块。
- **修复方案**：在 edgar_provider.py:312 的 best dict 里加 "period_end": metric.as_of_date(已是 date)、"has_calculated_q4": getattr(metric,'has_calculated_q4',False)、"warning": getattr(metric,'warning',None)；recency gate 直接用 metric.as_of_date 替代 _metric_latest_period_end(可删该 helper)。下游 normalize_financials.period_end 与 xbrl_concept_snapshot 透传 period_end；若 has_calculated_q4/warning 非空则 append 进 DataResult.warnings。注意 _validate_ttm_periods 仍需保留(它防的是 NVDA 废弃 concept 的退化窗口)。改动量级：小-中。
- **验证补充**：Fix is sound. Keep _validate_ttm_periods (it gates NVDA's dead-concept degenerate window — confirmed edgar_provider.py:188-202,219-252). Replacing _metric_latest_period_end with metric.as_of_date is safe since calculator sets it to ttm_quarters[-1].period_end. When threading period_end downstream, also fix the periods shape to match XBRLTTMMetric.periods: list[str] (or change the model) — the current dict shape never round-trips into the typed model.
- **影响面/回归风险**：影响 TTM 口径的可溯源性与新鲜度可见性——分析师无法确认 comps/估值用的 TTM 截止季，也看不到 "Q4 系推导" 这类口径瑕疵。回归风险低(只增字段)。
- **置信度**：high　|　**状态**：已修（edgar_provider._select_recent_ttm 返回 dict 增 period_end(=metric.as_of_date)/has_calculated_q4/warning；recency gate 改用 metric.as_of_date（删 _metric_latest_period_end）；periods 形状改 list[str]("Q3 2025") 对齐 XBRLTTMMetric.periods 可 round-trip；has_calculated_q4/warning 非空时 append 进 DataResult.warnings。保留 _validate_ttm_periods（NVDA 废弃 concept 退化窗口门控）。范围说明：period_end 只透传到 snapshot（UI 读取处），未塞进 FMP 口径的 normalize_financials（那是另一 provider、无消费方、避免死路径）。与 BUG-009 同提交。）

#### [BUG-011] _money_from_text 把孤立的 'm' 当成 million 乘子(无词边界),$96 measured→$96M,且 ×1e6 可把 sub-$1M 原值抬过合理性闸门

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/engine/compute/ownership.py:131 (_money_from_text 的 scale 正则) → 被 _ceo_comp_from_text(:235) 调用 → build_proxy_compensation(:652) 兜底取数
- **现象/问题**：scale 捕获组 (million|m|billion|bn) 后没有 \b/词边界,任何以 m/bn 开头的后继单词都会被当成单位。'$96 measured over the period' 被解析成 96×1e6 = $96,000,000。raw $96 本应 < _CEO_COMP_MIN($1M) 被 None 掉,但伪 ×1e6 后恰好落进 [1M,500M] 闸门 → 以权威 CEO 薪酬数字进研报。
- **证据**：已复现:money('$96 measured over the period') 返回 96000000.0;money('$36,343,830 reflecting') 正常返回 36343830.0。正则 r"\$\s*([0-9][0-9]*(?:\.[0-9]+)?)\s*(million|m|billion|bn)?" 中 m 无右边界。该函数是 _ceo_comp_from_text 的唯一取金额手段(第三优先级兜底,build_proxy_compensation:652 会走到)。
- **根因**：ownership.py:131 正则 scale 组缺词边界;合理性闸门 [1M,500M] 反而被 ×1e6 绕过(把垃圾小数抬进合法区间)而非拦下。
- **修复方案**：改 ownership.py:131 正则为 r"\$\s*([0-9][0-9]*(?:\.[0-9]+)?)\s*(million|billion|bn)?\b"——删掉裸 'm'(保留 million/billion/bn 全词+\b),DEF 14A 金额几乎都写完整 'million'/带逗号全额数字,删 'm' 不会漏真实用例;若要保留 '$96 m' 这类简写,把 'm' 改成 r"m(?=illion\b|\b)" 之类带边界写法并加单测。注意 _money_from_text 还服务别处需回归。
- **验证补充**：Fix is correct: r'\$\s*([0-9][0-9]*(?:\.[0-9]+)?)\s*(million|billion|bn)?\b' verified — '$96 measured'→96 (raw, gate kills it), '$96 million'→96M, '$1.5 billion'→1.5e9, '$96bn'→9.6e10 all correct; only loses bare '$96 m' shorthand which DEF 14A rarely uses. Finding's 'still serves other places, needs regression' is overstated — grep confirms _money_from_text has exactly ONE caller in the whole repo (line 235), so no external regression surface.
- **影响面/回归风险**：影响所有走第三优先级兜底取 CEO 薪酬的 ticker(DEF 14A 无标准 SCT 表/无 402(u) 明文披露时);回归风险低,正则收紧只会少匹配垃圾。
- **置信度**：high　|　**状态**：已修（ownership.py:_money_from_text 正则去掉无边界的裸 m 乘子，改 (million|billion|bn)?\b；scale 分支改 ==million。验证 $96 measured→96(被闸门杀)、$96 million→96M、$1.5 billion→1.5e9、$96bn→9.6e10。新增单测。与 BUG-012 同提交。）

#### [BUG-012] CEO 姓名/总薪酬/pay-ratio 三字段各自独立 first-match 抽取,无任何一致性勾稽,可把张冠李戴/跨年度/口径不符的三元组当权威披露并排展示

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/engine/compute/ownership.py:638-662 (build_proxy_compensation 三路独立取数)  ·  （另涉：finrobot/engine/compute/ownership.py:259-277 (_ceo_comp_and_ratio_from_disclosure 的 comp 正则)）
- **现象/问题**：ceo_name 来自 summary_name 或 _extract_ceo_name;ceo_total_compensation 优先 disclosure_comp 再 summary_comp 再 anchor;ceo_pay_ratio 优先 _extract_ceo_pay_ratio 再 disclosure_ratio。三者来自不同正则、不同句子、可能不同财年,代码从不校验 comp/median≈ratio,也不校验 name 与 comp 同源。name 可取自 SCT 表行(Person A),comp 却取自另一句 disclosure(可能指 Person B 或上一年),并排呈现为同一 CEO 的薪酬快照。
- **证据**：已复现 ratio first-match 抓上一年:'Last year, our CEO pay ratio was 250 to 1. For fiscal 2025 ... 312 to 1.' → 返回 250(应为 312)。代码层:line 640 name 与 line 647 comp 与 line 660 ratio 是三条完全独立的 re.search 链,无任一交叉断言;validators.py:64-87 的 validate_ownership_governance 只查结构存在性,不查字段语义/一致性。
- **根因**：build_proxy_compensation 把三个高脆弱度自由文本抽取结果直接组装进 ProxyCompensation,缺少 cross-field sanity gate(comp/ratio 隐含 median 应自洽;name 与 comp 应同源同年)。第一个出错位置是 ownership.py:664 的无校验组装。
- **修复方案**：在 ownership.py build_proxy_compensation return 前加一致性闸门:① 若 disclosure_comp 与 disclosure_ratio 同时存在,优先把这二者作为同源配对(它们出自同一 402(u) 段落,_ceo_comp_and_ratio_from_disclosure 已成对返回——应整体采纳该对而非让 ratio 被 _extract_ceo_pay_ratio 的全局 first-match 覆盖);把 line 660-662 改成优先 disclosure 成对值,_extract_ceo_pay_ratio 仅当 disclosure 缺失时兜底。② ratio/comp 都用窗口锚定在同一 'fiscal YYYY' 附近而非全文 first-match。③ 给 ProxyCompensation 增 source/year 元字段,name 与 comp 不同源时降级(见独立发现)。改动量级:中(单文件 + 模型加字段 + 单测覆盖跨年/张冠李戴)。
- **验证补充**：Core fix is right: prefer the paired (disclosure_comp, disclosure_ratio) since _ceo_comp_and_ratio_from_disclosure already returns them from the same 402(u) paragraph — reorder so disclosure ratio wins when disclosure comp is also taken, instead of letting global first-match _extract_ceo_pay_ratio override it. Caveat on the proposed name-comp same-source meta-field: that overlaps finding [3]; do it once, not twice. The comp/median≈ratio numeric self-consistency check is sound but median-employee comp isn't currently extracted, so it can only gate when disclosure prose carries the median figure — scope it accordingly.
- **影响面/回归风险**：影响所有 DEF 14A 同段落含多年/对比表(TSLA proxy 嵌 Apple/Tim Cook 对比表的坑代码注释已记)的 ticker;回归风险中,需补黄金样本(NVDA/AAPL/JPM 真 proxy 片段)断言。
- **合并自**：gap-r2-2#2, gap-r2-2#3（2 条同源发现）
- **置信度**：high　|　**状态**：已修（ownership.py:build_proxy_compensation 重排——disclosure 成对 (comp,ratio) 存在时 ratio 作为整体优先，_extract_ceo_pay_ratio 仅兜底；并把 _ceo_comp_and_ratio_from_disclosure 改为真正成对（ratio 从 comp 匹配位起搜，避免文档级 first-match 抓上一年）。复现「上一年 250 / 本年 312」现返回 312。未做 name-comp 同源元字段与 comp/median 数值自洽（按指示延后/属他条）。ruff+mypy --strict + 22 例通过。与 BUG-011 同提交。）

#### [BUG-013] earnings.py float(row.get('revenue_actual',0)) crashes (TypeError) on present-but-None revenue, and otherwise fabricates $0 revenue → false -100% surprise

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/engine/compute/earnings.py:40-43
- **现象/问题**：Two coupled defects: (1) when a key is present with value None, float(None) raises TypeError, not the intended default-0; (2) if it did default to 0, a missing actual revenue would be reported as $0 actual vs a real estimate → a fabricated -100% revenue surprise (or, for missing estimate, washed to n/a). Either outcome violates the project's 'never invent a number' bar. This is latent today only because the endpoint bug (finding 1) keeps history empty, but it becomes live the moment finding 1 is fixed.
- **证据**：Reproduced: row={'eps_actual':1.5,'revenue_actual':None,...}; float(row.get('revenue_actual',0)) → TypeError: float() argument must be a string or a real number, not 'NoneType'. dict.get returns the default ONLY when the key is absent — the FMP provider always sets the key (to None when FMP omits the value), so the `, 0` default never fires. Live-verified that real rows with epsActual present but revenueActual=null exist: SAP has 7 such rows (e.g. {date:1999-01-26, epsActual:0.19, epsEstimated:0.2, revenueActual:null, revenueEstimated:1294736840}), RIVN has 6. These rows pass the provider's eps-only filter and reach earnings.py. The EarningsSurprise model (financial.py:737-738) declares revenue_actual/revenue_estimated as non-optional float, so even a None that escaped float() would be rejected by pydantic.
- **根因**：earnings.py:42-43 assumes row values are never None and that a missing field manifests as an absent key. Provider mapping (fmp_provider.py:587-593) filters None only on eps, never on revenue, so revenue_actual/revenue_estimated arrive as None. First error site is earnings.py:42 `float(row.get('revenue_actual', 0))`.
- **修复方案**：In earnings.py replace the four float(...) coercions (lines 40-43) with a helper that maps None→None (not 0), e.g. `def _opt_float(v): return float(v) if v is not None else None`, then make EarningsSurprise.revenue_actual/revenue_estimated and eps_actual/eps_estimated `float | None` in models/financial.py:733-738, and have _surprise_pct/_classify_surprise short-circuit to None/'n/a' when actual or estimated is None (mirror the existing estimated==0 handling at earnings.py:85-112). Quarters with missing revenue then carry revenue_surprise_pct=None and are excluded from avg_revenue/beat aggregates by the existing `is not None` filter at lines 67-68. Alternatively (simpler, narrower) keep model non-optional but have the provider drop revenue None-rows from revenue stats only — but the model-level None is the clean, root-cause fix matching the 'None≠0' cluster already applied elsewhere. Note: do not default to 0; a $0 actual revenue is a real, distinct value from 'unknown'.
- **验证补充**：_opt_float (None→None) approach is right. Refinement: only revenue_actual/revenue_estimated need to become float|None in the model — the eps filter at fmp_provider.py:593 already guarantees eps_actual/eps_estimated are non-None, so making eps optional is unnecessary (though harmless and symmetric with the None≠0 cluster). _surprise_pct/_classify_surprise already short-circuit on None correctly; just ensure rev_actual/rev_est None flows into _surprise_pct(None,...) — that path also needs a None guard since current _surprise_pct only None-guards estimated==0, not None inputs.
- **影响面/回归风险**：Prevents a hard crash of the earnings_data step (which catches ProviderError/ValueError/KeyError but NOT TypeError → would crash, retry 3× identically, fail the step) once finding 1 lands. Touches earnings.py + EarningsSurprise model + their tests. Regression risk: any code reading revenue_actual as a guaranteed float must handle None — grep shows only earnings.py and the artifact/UI render path consume it; verify the renderer tolerates None (it already handles eps None via 'n/a').
- **置信度**：high　|　**状态**：已修（改了 `finrobot/engine/compute/earnings.py`：新增 `_opt_float` 助手把 4 个 `float(row.get(...,0))` 改成 None-preserving；`_surprise_pct` 加 None 输入短路。`finrobot/engine/models/financial.py`：`EarningsSurprise` 的 eps/revenue actual+estimated 四字段改 `float | None`。`tests/unit/test_earnings.py`：新增 `test_none_revenue_preserved_not_fabricated_zero` 断言 None 营收→`revenue_surprise_pct=None`/`direction='n/a'`、不 crash、不进均值。验证：`pytest tests/unit/test_earnings.py` 全绿；ruff+mypy --strict 通过。确认下游消费方仅 builders.py(`len`+`_safe_dump`，None-safe) 与死 appStore(`import type`)，无 UI 回归。)

#### [BUG-014] DCF graceful-degrade (tg≥WACC) self-defeats: technical_analysis hard-requires DCFResult and crashes the whole equity_research run one step later

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/engine/pipelines/equity_research.py:505-509 (technical_analysis) vs :428-453 (financial_modeling degrade)
- **现象/问题**：For low-WACC profiles (low-beta / high-leverage utilities & REITs) where seeded terminal_growth ≥ WACC, financial_modeling deliberately degrades: calculate_dcf raises ValueError, the executor catches it, builds valuation_synthesis from relative methods, and returns StepOutput(structured=None) so the report falls back to relative valuation (this was the BUG-008 fix). But the very next step, technical_analysis, does `dcf = structured_context.get('financial_modeling')` and `if not isinstance(dcf, DCFResult): raise ValueError(...)`. On the degrade path financial_modeling was never written into structured_context as a DCFResult, so dcf is None → ValueError is raised.
- **证据**：Trace: calculate_dcf raises (dcf.py confirms `if tg >= wacc: raise ValueError`) → _execute_financial_modeling except block returns structured=None and does NOT set structured_context['financial_modeling'] (line 475 write is only on the success path). _store_output skips structured (None), validate_is_non_empty passes on the degrade narrative text → step 'succeeds'. Next step technical_analysis line 505 sees None → raises ValueError 'requires DCFResult... received: NoneType'. ValueError is not in _RECOVERABLE_SUBSTRINGS and not a typed-recoverable class, so _is_recoverable_exception returns False → it propagates out of _run_step → out of Pipeline.execute → caught in routes/runs.py:391 → entire run transitions to failed. The graceful-degrade path is therefore dead: the exact scenario it exists to survive still crashes the run.
- **根因**：First error is technical_analysis's hard precondition (equity_research.py:505) being incompatible with financial_modeling's intentional degrade-to-None contract. Underlying mechanism: a non-recoverable executor exception in a NON-critical step still aborts the whole run (best-effort continue only applies to validation failures and recoverable exceptions, not to raw ValueErrors), so technical_analysis is effectively critical despite not being flagged so.
- **修复方案**：In finrobot/engine/pipelines/equity_research.py _execute_technical_analysis: when `dcf` is not a DCFResult, do NOT raise — return a degraded StepOutput (text explaining technical/chapter-09 analysis is skipped because DCF was not applicable, structured=a TechnicalAnalysis with all branches None or a minimal payload). validate_technical_analysis currently fails when all three branches are None, so either (a) relax that validator to pass when there is an explicit 'dcf_unavailable' degrade flag, or (b) build_technical_analysis can still run Monte Carlo/Sniper off current_price + relative-valuation target instead of dcf.implied_price. Cleanest: skip technical_analysis gracefully when no DCFResult, mirroring how the standalone DCF pipeline's output_gen step tolerates the missing result. Note: also audit every other equity_research step downstream of financial_modeling for the same isinstance-or-raise pattern (build_valuation_synthesis already tolerates missing dcf; thesis reads valuation_synthesis not financial_modeling, so it is safe).
- **验证补充**：Fix direction is right (degrade technical_analysis gracefully instead of raising). Prefer the validator route: have _execute_technical_analysis return StepOutput(text=skip-explanation, structured=TechnicalAnalysis with all branches None + a warning), and relax validate_technical_analysis (validators.py:55-60) to PASS when there is an explicit dcf-unavailable marker — currently it fails when all three branches are None, which would just re-trigger the same non-critical degrade→still emits a green check (finding 3). Also audit downstream steps: thesis reads valuation_synthesis not financial_modeling (safe), build_valuation_synthesis already tolerates missing dcf (safe), as the finding notes.
- **影响面/回归风险**：Affects every ticker whose seeded DCF is undefined (utilities/REITs/low-beta high-leverage names). Today these reliably fail the full report instead of producing a relative-valuation report. Regression risk of the fix is low — it only changes the no-DCF branch, which currently always crashes; the happy path (DCF resolves) is untouched. Verify with a low-WACC ticker or a unit test that injects tg≥WACC seeds.
- **置信度**：high　|　**状态**：已修（equity_research._execute_technical_analysis 在 financial_modeling 非 DCFResult 时不再 raise，改返回降级 StepOutput（解释文本 + TechnicalAnalysis 全分支 None + warnings 含 TECHNICAL_DCF_UNAVAILABLE_MARKER）；validators.validate_technical_analysis 当含该 marker 时 PASS（避免再触发非关键降级 + 假绿勾）。marker 常量放在 technical_payload.py 叶子模块避免循环 import。下游审计确认 thesis 读 valuation_synthesis、build_valuation_synthesis 已容忍缺 DCF，均安全无改。与 BUG-015 同提交。）

#### [BUG-015] Thesis & peer-selection wrap recoverable AgentRunError into ValueError, defeating the retry/back-off system and aborting the whole run on the first transient LLM hiccup

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/engine/pipelines/equity_research.py:830-831 (_execute_thesis) and finrobot/engine/pipelines/_helpers.py:126-127 (_llm_select_peers)
- **现象/问题**：Both catch `(AgentRunError, ValidationError, ValueError)` and re-raise as a plain `ValueError`. base.py's _is_recoverable_exception treats AgentRunError as recoverable BY TYPE (so it normally gets up to 3 retries with 2/5/10s back-off), but a ValueError is non-recoverable. By re-wrapping, a transient model error (rate-limit surfaced as AgentRunError, 503, a one-off invalid-JSON ValidationError) becomes a non-recoverable ValueError that propagates immediately with ZERO retries and, because neither step is critical-flagged but raw exceptions bypass best-effort, aborts the entire run.
- **证据**：_execute_thesis: `except (AgentRunError, ValidationError, ValueError) as e: raise ValueError(f'LLM failed to produce valid thesis: {e}') from e`. _llm_select_peers: `except (AgentRunError, ValidationError, ValueError) as e: raise ValueError(f'Failed to select peer companies: {e}') from e`. In base.py:_attempt_with_exc_retry, the raised ValueError → _is_recoverable_exception → message has no recoverable substring and type is ValueError → returns False → re-raised → no retry budget consumed → whole run fails in routes/runs.py. Contrast: if the original AgentRunError reached _run_step it would have been retried 3× with back-off and, failing that, degraded on the non-critical step.
- **根因**：Over-broad exception re-wrapping that erases the exception type the retry system keys on. The intent was presumably to give a clearer message, but it converts the single most common transient failure (AgentRunError) into a permanent one.
- **修复方案**：In both functions, stop swallowing AgentRunError into ValueError. Either (a) let AgentRunError propagate unchanged (it carries its own message) and only re-wrap ValidationError/ValueError, or (b) re-raise preserving recoverability, e.g. catch AgentRunError separately and `raise` it as-is while wrapping only the genuinely-non-recoverable ValidationError. Concretely in equity_research.py:830 change to `except AgentRunError: raise` plus a separate `except (ValidationError, ValueError) as e: raise ValueError(...) from e`; same in _helpers.py:126. Note: ValidationError on structured output IS deterministically non-recoverable (same prompt → same schema failure) so keeping that wrapped is correct; only AgentRunError must stay recoverable.
- **验证补充**：Fix correct: `except AgentRunError: raise` (let it propagate as recoverable) + separate `except (ValidationError, ValueError) as e: raise ValueError(...) from e`. Keeping ValidationError wrapped is right — structured-output schema failure is deterministic (same prompt→same failure), genuinely non-recoverable. Apply identically at helpers:126.
- **影响面/回归风险**：Affects every equity_research/comps run when the LLM has a transient failure on the thesis or peer-selection step (the two LLM-bearing structured steps). Today one flaky API call kills the whole 30-120s pipeline with no retry. Fix restores the designed 3×back-off resilience. Regression risk low; ValidationError handling unchanged.
- **置信度**：high　|　**状态**：已修（equity_research._execute_thesis 与 _helpers._llm_select_peers 不再把 AgentRunError 吞成 ValueError：改 except AgentRunError: raise（按类型可重试，base.py 3×backoff）+ 单独 except (ValidationError, ValueError) 才包成 ValueError（schema 失败确定性不可重试，保持包裹）。新增测试断言 AgentRunError 原样传播、ValidationError 仍被包裹。与 BUG-014 同提交。）

#### [BUG-016] 自由文本叙事字段（valuation_overview/tagline/key_takeaways/competitor_analysis）无 code 级与 canonical target/verdict 对账，结构化标量被强制覆盖而散文不被——表格与散文可冲突

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/engine/pipelines/equity_research.py:828-887（synthesis 后处理）+ finrobot/artifact/builders.py:411-429（llm_narrative 原样镜像）  ·  （另涉：finrobot/engine/pipelines/equity_research.py:673-689（gate prompt 仅约束 valuation_overview）+ 806-809（tagline/key_takeaways 静态指令））
- **现象/问题**：price_target 与 recommendation 在 run 后被确定层 canonical 值硬覆盖（836-876），但同一次 LLM 调用产出的 valuation_overview / tagline / key_takeaways / competitor_analysis / company_overview / news_summary 这 6 个自由文本字段被原样接受并镜像进 outputs.llm_narrative。LLM 可在散文里印一个与被覆盖后的结构化 target 不一致的数。
- **证据**：happy 路径：override 仅在 abs(thesis.price_target - canonical_target) > 0.01 时修正结构化字段（855 行），但 valuation_overview 文本完全不动。若 LLM 返回 price_target=$280 而 canonical=$276.43，结构化字段被改成 276.43，valuation_overview 仍写 '加权目标约 $280'——卡片/表格显示 $276.43，正文说 $280。tests/audit/test_thesis_prompt_discipline.py 全部只断言 prompt 白名单组成（260/300/306 行），无一条断言 LLM 输出的叙事与 canonical 一致；该文件 271 行 docstring 自认 'structured price_target is force-nulled post-run, but free prose can still print "$12.71"'，仅靠'把数字移出白名单'缓解，非输出侧校验。
- **根因**：第一出错位置在 828-887 的后处理块：它只对 thesis.recommendation / price_target / price_target_basis 做 model_copy override，从不读取或校验 thesis.valuation_overview 等自由文本是否引用了被覆盖前的旧数。叙事与结构化标量来自同一次 run，但只有标量进入一致性闸。
- **修复方案**：在 finrobot/engine/pipelines/equity_research.py 的 override 块之后加一个轻量 code 级一致性闸：(1) 当 canonical_target 存在，正则扫描 valuation_overview/tagline/key_takeaways 中的 $金额，若出现一个与 canonical_target 偏离 >2% 且不等于任何 whitelisted per-method mid 的金额 → logger.warning('narrative target drift') 并把该字段重写为附带 canonical 数字的安全模板，或截断该数字短语。(2) 简化且更稳的做法：valuation_overview 不让 LLM 复述加权目标，改由 code 在文本头部拼一行确定性 'Weighted target: $X（{method_breakdown}）' + LLM 只写'为什么各方法分歧'的定性段，从结构上消除散文印错头条数的可能。注意：override 已是唯一一致性来源，加闸不要再触发二次 LLM 调用（成本/漂移）。
- **验证补充**：Fix is sound. Prefer fix (2)/finding-3 (code-render the headline line, LLM writes only qualitative why) as the durable fix; keep fix (1) regex+safe-template as the interim guard. Even with code-rendered numbers, a post-run scan is still warranted since prose can smuggle a number. Do not add a second LLM call — author correctly flags this.
- **影响面/回归风险**：影响所有 equity_research artifact 的正文与分享卡片可信度（目标用户=分析师，表格-正文数字打架直接砸招牌）。回归风险低：纯 run 后处理，不改 pipeline 契约、不改 Mode A/B；若选模板化 valuation_overview 则 8-agent 叙事风格略变，需同步 instructions/synthesis_agent.md。
- **合并自**：gap-r1-2#1, gap-r1-2#2（2 条同源发现）
- **置信度**：high　|　**状态**：待修

#### [BUG-017] Chat-triggered pipelines bypass the app-wide concurrency semaphore — LLM can fire unbounded parallel heavy runs

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/engine/orchestrator.py:33 (_run_pipeline_tool) + 91-158 (8 run_* tools); contrast finrobot/routes/runs.py:243-255 (_run_pipeline)  ·  （另涉：finrobot/server.py:653 (adapter.run_stream_native call, no usage_limits arg)）
- **现象/问题**：The 8 `run_*` lead-agent tools call `pipeline.execute(ctx.deps, ticker)` directly. The only app-wide pipeline concurrency cap — `run_semaphore = asyncio.Semaphore(4)` (server.py:152) — is acquired exclusively inside `_run_pipeline` on the REST `/api/runs` path. The chat path never touches it. A single chat turn that says 'run equity research on AAPL, MSFT, GOOGL, NVDA, AMZN, META, TSLA' lets the model emit N tool calls; pydantic-ai executes a turn's tool calls concurrently, so N full equity-research pipelines (each 8 LLM steps × multi-provider fetch) launch at once with no cap — on top of any 4 REST runs already in flight.
- **证据**：runs.py:245-255 wraps `_run_pipeline_impl` in `async with semaphore`. orchestrator.py:33 `result = await pipeline.execute(ctx.deps, ticker)` has no semaphore. `FinRobotDeps` (deps.py:14-20) has no semaphore field, so the tool cannot reach `app.state.run_semaphore`. The semaphore's own docstring (runs.py:249-253) states its purpose is 'a batch of N coverage runs must not fire N LLM pipelines at once and blow provider/LLM rate limits' — the chat path defeats exactly that guarantee.
- **根因**：The concurrency cap was implemented as a wrapper in the REST executor (`_run_pipeline`) instead of inside `Pipeline.execute` or threaded through `FinRobotDeps`. The chat tools were wired to call `pipeline.execute` directly (orchestrator.py:33), so they were never inside any slot. First wrong location: orchestrator.py:33 (and the 8 tool bodies 97-158) calling execute without slot acquisition.
- **修复方案**：Single chokepoint: thread the semaphore into the deps and acquire it inside `Pipeline.execute`, so EVERY caller (REST, chat tools, coverage batch, CLI, SDK) shares one cap and the wrapper in runs.py can be deleted. Concretely: add `run_semaphore: asyncio.Semaphore | None = None` to FinRobotDeps (deps.py); set it where deps is built (server.py lifespan — reuse the existing `app.state.run_semaphore`, and in CLI/SDK build a default `Semaphore(4)`); in base.py `Pipeline.execute` wrap the step loop in `async with (deps.run_semaphore or _NULL_CTX):`; remove the now-redundant `async with semaphore` in runs.py:254. Note: acquiring the slot inside execute means queue time is counted differently for REST runs — keep the REST wrapper's status='created'-while-queued behaviour by acquiring BEFORE update_run('running') in _run_pipeline_impl, OR accept that running-status now includes queue wait (document the choice). Medium change (~30 lines across 4 files), touches the Mode A/B symmetry contract — flag in commit.
- **验证补充**：Fix is sound (thread semaphore into deps + acquire inside Pipeline.execute, delete runs.py wrapper). Two notes: (1) acquiring inside execute changes the REST 'created-while-queued' status semantics the runs.py docstring relies on — author already flagged this, keep that behaviour by acquiring before update_run('running') or document the change; (2) CLI/SDK building their own Semaphore(4) yields independent caps per process — fine for a single desktop process but not a truly global cap. Acceptable for this architecture.
- **影响面/回归风险**：Affects every pipeline caller. Closes the rate-limit / resource-exhaustion hole on the unauthenticated localhost chat endpoint. Regression risk: REST run 'created→running' timing semantics shift slightly; coverage batch still capped (already goes through spawn_run→execute). Must re-verify the 4-slot cap still holds for coverage after the wrapper is removed.
- **合并自**：gap-r1-3#1, gap-r1-3#2（2 条同源发现）
- **置信度**：high　|　**状态**：待修

#### [BUG-018] Scoped coverage-group hit-rate silently truncates to the GLOBAL newest-500 page → groups show null track record despite having one

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/routes/dashboard.py:377-383 (_collect_signal_inputs) + dashboard.py:176 caller
- **现象/问题**：For a scoped query (?tickers=AAPL,MSFT,... = a coverage group, BUG-055), the route fetches the GLOBAL newest-500 summaries first, THEN filters to the group's tickers in Python. If the group's tickers were last researched a while ago, every one of the group's artifacts can fall outside the global top-500 window → the group's hit-rate buckets come back empty / null even though the group has a full, judgeable track record.
- **证据**：dashboard.py:377-379 `summaries = await store.list_by_ticker(ticker=None, include_archived=False, limit=_HIT_RATE_SAMPLE_CAP)` then 383 `summaries = [s for s in summaries if s.ticker and s.ticker.upper() in tickers]`. Repro: store has 1200 non-archived artifacts; a 3-ticker group (e.g. TSM/ASML/SAP) whose latest report is the 600th-newest. The 500-cap page is dominated by other tickers' recent runs → the 3 group tickers are absent → filtered list is empty → `_signal_for` runs over nothing → overall/by_verdict all null. UI/SDK consumer reads 'samples 不足' for a group that actually has years of closed theses.
- **根因**：First error site is the cap-then-filter ordering in `_collect_signal_inputs`: the SQL LIMIT 500 is applied at the GLOBAL `ticker=None` query, before the Python ticker filter. The cap was sized for the unscoped landing fan-out, not for per-group scoping, so a group's rows can be evicted by unrelated recent activity.
- **修复方案**：In `_collect_signal_inputs`, push the ticker filter into SQL instead of post-filtering a global page. Either (a) add a `tickers: set[str]|None` param to `SqliteArtifactStore.list_by_ticker` that emits `ticker IN (?,?,...)` and apply the 500 cap to the SCOPED query, or (b) when `tickers` is non-None, loop `list_by_ticker(ticker=t, limit=_HIT_RATE_SAMPLE_CAP)` per member and concat (bounded: groups are small). Prefer (a) — one query, cap correctly scoped. Note: the `is_sampled` denominator must then become the scoped count (see related finding), and the `idx_artifacts_ticker_created` index already supports the IN-filter. Change size: ~25 lines (store method + route + 1 store test for the IN path).
- **验证补充**：Fix (a) push ticker IN (?,...) into list_by_ticker and cap the scoped query is correct and preferred. is_sampled denominator must then become scoped+windowed count (finding [1]). Minor: also add a store test asserting the IN path returns rows a global-500 page would have evicted.
- **影响面/回归风险**：Fixes the core 'coverage-group track record' feature (BUG-055). Affects only scoped (?tickers=) callers; unscoped landing unchanged. Regression risk: low — global path keeps current behavior; needs a store test for the IN-clause param binding.
- **置信度**：high　|　**状态**：待修

#### [BUG-019] Sharpe ratio uses backtrader default timeframe=Years on daily bars → None for ~1yr windows, meaningless for multi-year

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/engine/backtest/backtrader_adapter.py:124-128 (addanalyzer SharpeRatio) + :241-246 (_extract_sharpe)
- **现象/问题**：The adapter feeds DAILY price bars but adds bt.analyzers.SharpeRatio with default params. backtrader's default is timeframe=TimeFrame.Years (int 8), convertrate=True, annualize=False. On daily data this resamples returns to YEARLY frequency before computing Sharpe. For the most common backtest window (~1 year of daily bars) there is only ~1 yearly return point → Sharpe is mathematically undefined and backtrader returns None. The adapter then emits warning 'Insufficient data for Sharpe ratio calculation' — blaming data, when the real cause is a mis-configured analyzer. For a 3-year window you get a Sharpe over 3 points: statistically meaningless. The result is shown to quant users right next to riskfreerate.
- **证据**：Reproduced with installed backtrader 1.9.78.123: `bt.analyzers.SharpeRatio.params._getpairs()` → timeframe=8 (TimeFrame.Years), annualize=False, convertrate=True. Ran a buy-and-hold strategy on 252 synthetic daily bars (~1yr) with the adapter's exact config: DEFAULT (timeframe=Years) → sharperatio=None; timeframe=Days,annualize=True → -20.31 (correct annualized daily Sharpe); timeframe=Days,annualize=False → -1.28. So real users running `finrobot backtest AAPL --start 2023-01-01 --end 2024-01-01` get a silent None Sharpe.
- **根因**：backtrader_adapter.py:124-128 omits timeframe/annualize when registering SharpeRatio, inheriting the library default timeframe=Years which is wrong for daily bars. First wrong location is the addanalyzer call, not _extract_sharpe (it correctly relays whatever it gets).
- **修复方案**：In backtrader_adapter.py addanalyzer for sharpe, pass `timeframe=bt.analyzers... ` — concretely: `cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=config.risk_free_rate, timeframe=bt.TimeFrame.Days, compression=1, annualize=True, factor=252)`. This makes Sharpe a proper annualized daily Sharpe consistent with the 'Sharpe assumes risk-free rate X%' annual framing. Note: data feed is daily (PandasData on daily index), so factor=252 trading days is correct; if intraday feeds are ever added, derive factor from feed timeframe. Update the docstring on line 6 and the warning text. Add a regression test in tests/unit/test_backtrader_adapter.py running a real (or fixtured) 1yr daily backtest and asserting sharpe_ratio is a finite float, not None.
- **验证补充**：Fix direction correct. Two cautions: (1) backtrader's SharpeRatio with annualize=True and convertrate semantics interacts with factor — verify the regression test asserts a finite float AND a sane magnitude, since the synthetic-data repro above gave an extreme value (annualization of a tiny-noise series amplifies); test on a realistic price series not pure noise. (2) Keep convertrate handling consistent with riskfreerate being annual (4%). The proposed factor=252 + timeframe=Days + annualize=True is the standard correct config.
- **影响面/回归风险**：Every Sharpe number the backtest has ever produced is either None (short windows) or computed on a handful of yearly points (long windows) — i.e. the headline risk-adjusted metric is effectively broken for the primary use case. Fix changes the numeric Sharpe value (regression risk: any snapshot test pinning the old None/value must be updated). No effect on total_return/drawdown/trades.
- **置信度**：high　|　**状态**：已修（backtrader_adapter.py：SharpeRatio addanalyzer 显式传 timeframe=Days,compression=1,annualize=True,factor=252（修正 backtrader 默认 timeframe=Years 在日线上重采样到年频→1yr 窗口 Sharpe=None 的假象）；更新 docstring + 把误导的「Insufficient data」警告文案改诚实化。新增回归测试：~1yr 日线（真实几何随机游走，非纯噪声）下 sharpe 为有限浮点（实测 2.566，旧默认为 None）。ruff+mypy --strict + 19 例通过）

#### [BUG-020] CLI 全部 pipeline 命令零 ticker 校验/归一化：脏 ticker 直灌 provider + 污染缓存与 artifact

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/cli.py:189-405 (research/comps/dcf/ddm/lbo/earnings/ic-memo) + compare:483 + ask/analyze
- **现象/问题**：CLI 是真实用户入口，却是唯一不做 ticker 校验/大写归一的入口。所有 pipeline 命令把 click.argument('ticker') 原样传 pipeline.execute(deps, ticker, ...)；compare 仅 .upper()，其余连大写都不做。后端 routes 用 _TICKER_RE=^[A-Z0-9.\-]{1,12}$ 校验+大写(coverage.py:53/65)，CLI 完全绕过。
- **证据**：复现：`finrobot research aapl` → pipeline.execute 收到 'aapl'(base.py:322 不校验不归一)→ DataLayer.fetch 用 'aapl' 当缓存主键(cache.py PRIMARY KEY (data_type,ticker)，layer.py:75 不 .upper())→ FMP 用原串拼 URL `/income-statement/aapl`(fmp_provider.py:141，仅 display 字段 .upper())。结果：'aapl' 与服务端写入的 'AAPL' 在同一 data_cache.db 落成两行缓存，artifact 被盖 ticker='aapl'。更糟：`finrobot research '苹果'` 或 `finrobot research 'AAPL;DROP'` 不会被拦，原样 fan-out 到所有 provider(BUG-053 注释正是为此在 routes 加的校验，CLI 没同步)。
- **根因**：第一出错位置=cli.py 各命令拿到 ticker 后未经 _clean_tickers/_TICKER_RE 即调 pipeline.execute；归一化职责被默认放在 routes 层，CLI 这条进程路径漏装(server/cli/sdk 三进程各自装配，校验只在 routes)。
- **修复方案**：在 cli.py 顶部把 routes/coverage.py 的 _TICKER_RE 提到共享位置(如 finrobot/engine/data/types.py 或新 finrobot/tickers.py)，写一个 normalize_cli_ticker(raw)->str：strip+upper+_TICKER_RE.match，不匹配 raise click.ClickException(f"Invalid ticker '{raw}'. Use A-Z/0-9/./- up to 12 chars, e.g. AAPL or BRK.B")。在 research/comps/dcf/ddm/lbo/earnings/ic_memo/ask/analyze 入口、compare 的 tickers 循环、backtest 的 ticker 全部先归一再用。注意：与 routes/coverage.py:53 和 ui/src/utils/ticker.ts 保持同一正则(已是手工同步点，趁此抽公共常量消除三处漂移)。改动量小(~15 行 + 1 工具函数)。
- **验证补充**：Fix direction is right. One sharpening: there are already THREE divergent _TICKER_RE — coverage.py:53 ({1,12}), search.py:26 ({1,10}), validators.py:140 (a different word-boundary regex). Extracting ONE shared constant should reconcile the coverage/search 10-vs-12 drift too, not just add a CLI copy. Note: FMP is case-insensitive in practice so live data still returns; the concrete harm is cache duplication + artifact ticker mismatch + unvalidated junk reaching providers, not a hard fetch failure for lowercase.
- **影响面/回归风险**：影响所有 CLI pipeline 命令；消除缓存大小写碎片化与脏 ticker fan-out。回归风险低——只收紧入口，合法 ticker 行为不变；唯一行为变更是非法输入从'静默跑/拖累 provider'变为'立刻报错'，符合预期。
- **置信度**：high　|　**状态**：已修（新建共享 finrobot/engine/data/ticker.py（_TICKER_RE {1,12} + validate_ticker 抽 strip+upper+regex）。cli.py 全部 pipeline 命令（research/comps/dcf/ddm/lbo/earnings/ic-memo/ask/analyze/compare/backtest）入口经 _validate_ticker_arg 归一，非法→click.ClickException。消除缓存大小写碎片 + 脏 ticker fan-out。与 BUG-033 同提交。）

#### [BUG-021] backtest --auto 对 LLM 失败无任何兜底：直接裸崩，也不回退确定性策略

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/cli.py:543-558 + finrobot/engine/backtest/strategy_agent.py:94/127/144  ·  （另涉：finrobot/cli.py:571-578 (BacktestConfig 构造) + 589）
- **现象/问题**：--auto 模式整条链路对 LLM 调用零保护：run_strategy_selection 里 config_agent.run(initial_prompt)(strategy_agent.py:94) 和 adjust_agent.run(adjust_prompt)(:144) 都无 try/except；cli.py:548-557 的 _run_auto 也只有 finally 关连接、无 except。LLM 鉴权失败/余额不足/网络断时抛 AgentRunError，原样穿透 asyncio.run 成裸 traceback。且产品上无兜底——用户本可直接拿确定性 sma_crossover 默认跑，--auto 失败却既不给清晰错误也不降级。
- **证据**：复现：清空/写错 LLM key 后 `finrobot backtest AAPL --start 2023-01-01 --end 2024-01-01 --auto`。注意 _build_deps 的 validate_runtime_config 这条路径根本没走(--auto 直接 get_settings()+build_data_layer，cli.py:546/549，没调 _build_deps)，所以连'缺 key'这种本可在 0 秒拦下的错也要等到第一次 LLM 调用才裸崩。对照非 auto 路径走 _build_deps→validate_runtime_config 能提前给干净 ClickException。
- **根因**：第一出错位置=cli.py:546 --auto 分支用裸 get_settings() 而非 _build_deps(跳过了 runtime 校验)；次因=strategy_agent.py:94 config_agent.run() 无异常处理与无 fallback。
- **修复方案**：两步：(1) cli.py --auto 分支改为先调 settings.validate_runtime_config() 并 try/except ValueError→ClickException(复用 _build_deps 同款逻辑)，把缺 key 提前拦下；(2) 在 strategy_agent.run_strategy_selection 把 config_agent.run() 用 try/except (AgentRunError, ValidationError) 包裹，失败时 raise 一个明确的 RuntimeError('LLM strategy selection failed: ...; rerun without --auto for the deterministic sma_crossover default') —— 或更佳：catch 后 fallback 到 BacktestConfig(ticker,start,end,strategy='sma_crossover',initial_cash=cash) 跑一次确定性回测并在 summary 顶部标注'LLM 不可用，已回退默认 SMA 策略'。建议选 fallback 方案(更符合'确定性兜底'信条)，约 12 行。注意 fallback 后 best_result 非 None，下游 save_chart 仍正常。
- **验证补充**：Both fix steps valid. Step (1) pre-flight validate_runtime_config()→ClickException is unambiguously correct and high-value. Step (2) fallback to deterministic sma_crossover matches the project's '确定性兜底' creed and is the better choice — but verify the fallback path also closes the data_layer (the existing finally already does) and that run_strategy_selection's signature lets the catch happen at the cli or agent layer cleanly. Catch (AgentRunError, ValidationError) — also consider ModelHTTPError/ModelAPIError (pydantic_ai.exceptions has them) for auth/rate-limit which may not all subclass AgentRunError; verify the actual exception hierarchy before narrowing the except.
- **影响面/回归风险**：影响 --auto 用户在 LLM 故障下的体验；正常 LLM 路径零影响。fallback 方案需确保回退结果的 warnings 明确标注降级，避免分析师误以为是 LLM 调优结果。回归风险低。
- **合并自**：gap-r2-5#2, gap-r2-5#3（2 条同源发现）
- **置信度**：high　|　**状态**：待修

#### [BUG-022] 零 busy_timeout + 多进程写同一 data_cache.db → SQLITE_BUSY 直接抛到调用方

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/engine/data/cache.py:167-171 (无 PRAGMA busy_timeout);finrobot/sdk.py:130 与 finrobot/data_layer_factory.py:88 各开同一 cache_db_path
- **现象/问题**：全仓 7 个 aiosqlite/sqlite3 连接没有任何一处设 PRAGMA busy_timeout(默认=0=立即失败)。WAL 只允许『一写多读』,不允许并发写。SDK 是文档明确的独立进程(sdk.py 注释 separate processes),它和 server 进程都对同一个 data_cache.db / quotes.db 做写入(DataCache.set / _set_slot / QuoteCache L2 write)。两进程同时写 → 后到的写者立刻 SQLITE_BUSY。
- **证据**：grep 全仓:aiosqlite.connect / sqlite3.connect 共 7 处,无一处 execute('PRAGMA busy_timeout=...')。复现:server 跑研报(pipeline 经 DataLayer.fetch→cache.set 写 data_cache.db)的同时,另开终端跑 `finrobot` SDK 路径(_ensure_deps→DataCache(cache_db_path) 写同库),写撞写。DataCache.set/_set_slot(cache.py:207-220)不 catch OperationalError;cached_fetch 同样不 catch → aiosqlite.OperationalError('database is locked') 冒泡成 500/pipeline step 失败。run_store 虽 catch OperationalError 但只是 log+raise,run 照样 failed。
- **根因**：连接初始化(cache.py:167-171、run_store.py:145-149、quote_cache.py:108-112、coverage/sqlite_store.py:117-121、artifact/sqlite_store.py:214-218、models/journal.py:76、sec_holdings_cache.py:119)统一缺 `PRAGMA busy_timeout`。设计假设是『单进程单连接 + asyncio.Lock 串行化写』,但该 Lock 只在进程内有效;SDK/CLI 跨进程访问同一批 db 文件时进程间无锁,WAL 也兜不住并发写。
- **修复方案**：在每个连接初始化块紧跟 journal_mode/synchronous 之后加 `await conn.execute('PRAGMA busy_timeout=5000')`(sqlite3 同步版 conn.execute 同理)。最干净的做法:在 paths.py 旁加一个 `configure_connection(conn)` 协程集中设 WAL+synchronous+busy_timeout,7 个 store 全部改调它(消除 6 处复制粘贴的 PRAGMA 三连)。注意:busy_timeout 不解决『同一进程内单连接写串行』,只解决跨进程/跨连接的瞬时锁等待;真要并发写还需每写者独立连接。改动量:小(7 文件各 +1 行 或 抽 1 函数 + 7 处替换)。
- **验证补充**：Fix is correct. The centralized configure_connection(conn) helper in/near paths.py is the right call (kills 6 duplicated PRAGMA blocks too). Note busy_timeout only fixes transient cross-connection lock waits, not throughput under sustained concurrent writes — which the author correctly states. Apply it to journal.py's per-call _connect() as well (the grep shows it's also missing).
- **影响面/回归风险**：影响所有写路径(研报落地、cache 写、quote 写、coverage CRUD)。回归风险低(busy_timeout 是纯增益,只会把『立即失败』变成『最多等 5s 再失败』)。不加则 SDK+server 并跑场景下偶发 database is locked,且因无重试直接打到用户。
- **置信度**：high　|　**状态**：已修（finrobot/paths.py 加共享 configure_connection（async aiosqlite）+ configure_connection_sync（sqlite3），集中设 WAL+synchronous+busy_timeout=5000。7 处连接初始化全部改调它：engine/data/cache.py、run_store.py、engine/data/quote_cache.py、coverage/sqlite_store.py、artifact/sqlite_store.py、engine/data/sec_holdings_cache.py、models/journal.py（sync _connect）。消除 6 处复制粘贴 PRAGMA。脚本实测两种连接 busy_timeout 均=5000、WAL 保留。ruff+mypy --strict + 全量 1986 通过。）

#### [BUG-023] Artifact PRIMARY KEY 用秒级时间戳，同票同类型同秒 run 静默覆盖前一份研报（审计链断档）

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/artifact/builders.py:69-73 (_make_artifact_id) + finrobot/artifact/sqlite_store.py:238 (ON CONFLICT(id) DO UPDATE)
- **现象/问题**：artifact id = `art_{%Y-%m-%dT%H:%M:%S}_{ticker}_{type}`，秒级粒度。它是 artifacts 表的 PRIMARY KEY，save() 用 `ON CONFLICT(id) DO UPDATE SET ... payload=excluded.payload`。同一 ticker+同一 type 的两次 run 落在同一秒 → id 完全相同 → 第二份 run 静默整体覆盖第一份的 payload + 全部镜像列，第一份研报从此不存在、不在版本历史里、无任何告警。
- **证据**：id 仅含到秒的时间戳（builders.py:70 `_now().strftime("%Y-%m-%dT%H:%M:%S")`），无 uuid/序号后缀；save 的 upsert 子句覆盖 payload。触发路径：用户在 stocks 页双击 Run、或 Coverage 批跑（semaphore=4 并发）与手动 run 竞合、或较快的单方法 pipeline（comps/dcf builder）同票连发。后果违背 models.py:1-7 自我声明的『Bloomberg/FactSet 级 audit-trail，可 byte-equal replay』核心卖点——研报被悄悄吞掉。叠加效应：前端 VersionDiffBanner.tsx:168-174 的 candidates 按 created_at 字符串排序，同秒两份 created_at 相等 → 排序不稳定 → 『compare vs previous』默认基准非确定。
- **根因**：第一出错位置 = builders.py:_make_artifact_id 用秒级时间戳作唯一键，没有为『同秒同票同类型』预留唯一性。upsert 语义本是为 mark_viewed/archive_stale 的合法重写设计，但与碰撞 id 叠加后把『重写自己』变成了『覆盖他人』。
- **修复方案**：改 builders.py:69-73：id 末尾追加去碰撞后缀，建议 `art_{ts}_{ticker}_{type}_{uuid4().hex[:6]}`（毫秒不够，并发同毫秒仍可能撞；uuid 后缀彻底根治且不破坏既有 id 前缀可读性/排序）。注意:(1) created_at 仍独立来自 meta，版本排序应改用 id 唯一性兜底而非纯 created_at——前端 VersionDiffBanner candidates 排序加 id 二级键 `(x.created_at,x.id)` 防同秒不稳定；(2) 既有库里历史 id 不变，无需迁移；(3) parent_artifact_id 链不受影响（它存的是具体 id）。改动量级:小（id 生成一行 + 前端排序一处），但属正确性根治。
- **验证补充**：Fix is correct. Prefer uuid4().hex[:6] suffix (ms still collides under async concurrency). Also add id as secondary sort key in VersionDiffBanner candidates sort. Note: parent_artifact_id chain (set in pipelines/base.py:418) stores a concrete id, so a collision could make a parent id point to an overwritten artifact — worth flagging but the suffix fix prevents it.
- **影响面/回归风险**：影响所有 8 个 builder 的 id 生成 + 版本历史/diff 默认基准。回归风险低：新 id 仍以 `art_{ts}_` 开头，list_by_ticker/timeline/diff 全靠 ticker+type 列与具体 id，不解析 id 内嵌时间戳。需跑 tests/artifact/ 确认没有测试硬编码完整 id 字符串。
- **置信度**：high　|　**状态**：已修（builders.py:_make_artifact_id 末尾追加 uuid4().hex[:6] 去碰撞后缀（ms 在 async 并发下仍可能撞）；保留 art_{ts}_ 前缀，旧 id 不变无需迁移，parent_artifact_id 链存具体 id 不受影响。VersionDiffBanner.tsx candidates 排序加 id 二级键 (created_at,id) 防同秒不稳定。grep tests/ 无硬编码完整 id 断言。ruff+mypy + ui lint/build/116 测试通过。）

#### [BUG-024] useAppStore (547 行) ~92% 死状态：仅 4 个 CmdK 字段有运行时消费方，其余全部无人读

- **类别**：Bug
- **严重度**：P1
- **位置**：ui/src/stores/appStore.ts:1-547（消费方仅 ui/src/layout/CmdKOverlay.tsx, TitleBar.tsx, uiStore.ts）
- **现象/问题**：appStore 是项目最早的 workspace store，定义了 ticker/phase/dcfInputs/dcfResult/scenarios/researchResult/compsResult/earningsResult/lboResult/icMemoResult/monteCarloResult/catalysts/activeTab/view 等 30+ 字段与 setter。实测全仓库只有 3 个文件 import useAppStore，且只读取 cmdPaletteOpen/cmdKQuery/setCmdPaletteOpen/setCmdKQuery 四个 CmdK 字段。其余约 500 行状态与 action 全是死代码。
- **证据**：`grep useAppStore` 仅命中 CmdKOverlay/TitleBar/uiStore；`grep -oE 'useAppStore((s) => s.X)'` 只返回 cmdPaletteOpen/cmdKQuery/setCmdPaletteOpen/setCmdKQuery。setResearchResult/setCompsResult/setEarningsResult/setLboResult/setIcMemoResult/setDcfResult/setMonteCarloResult 全部 0 个外部消费方。dcfResult/compsResult/HistoricalMetrics 在 chartAdapters.ts 与 ChapterFinancialAnalysis.tsx 出现，但只是 `import type`（TS 类型），不碰 store 运行时。完成态结果现在走 TanStack Query（StockWorkspace.tsx:75-77 invalidateQueries），不再回填 appStore——所以 setTicker(appStore.ts:449-478) 那段清空 11 个结果字段的逻辑也永远不会被触发。
- **根因**：研报结果的真源从 appStore 迁移到 server-state（artifacts via react-query）后，旧的 client-state 镜像（*Result 字段 + scenario 派生 deriveScenario + setTicker 清场）没有随迁移删除，留成了 dead state。第一个出错位置是迁移 PR 只加新路径未拔旧路径。
- **修复方案**：拆分 appStore.ts：①把仍被 import type 的纯类型（DCFResult/DCFInputs/CompsResult/CompanyFinancials/HistoricalMetrics/EarningsResult/LBOResult/...）抽到 ui/src/types/finance.ts（或就近 api/schema 派生），chartAdapters.ts、ChapterFinancialAnalysis.tsx 改 import 路径。②把活着的 4 个 CmdK 字段并入 uiStore（它已是 shell-chrome store，CmdK 属 shell）或新建 12 行的 cmdKStore。③删除 useAppStore 整个文件 + appStore.test.ts 中针对死字段的用例。注意：deriveScenario 的 bull/bear ±20% 派生逻辑若产品上还想要，需确认是否已在 server 端实现 scenario（grep 显示前端无消费方，大概率连功能都没接），未接则一并删。改动量级：重构（删 ~500 行 + 改 2 处 import + 迁 4 字段），但风险极低因死代码。
- **验证补充**：Finding missed ChapterCompetitive.tsx (also `import type { CompsResult }`) — the type-extraction step must update 3 import sites, not 2. Otherwise plan sound: move 4 CmdK fields to uiStore (already the shell-chrome store), extract types to ui/src/types/finance.ts, delete file + dead test cases. appStore.test.ts dead cases to drop: 'sets ticker','sets phase','sets and resets DCF inputs','sets warnings' (keep nothing — showSettings also unused outside store). deriveScenario/scenario has no frontend consumer, delete with it.
- **影响面/回归风险**：影响面：仅 3 个文件的 import 路径 + CmdK 接入点。回归风险低（删的是 0 消费方的状态）；唯一真实风险是 appStore.test.ts 里若有断言死字段初值的用例会红，需同步删。收益：新人 / AI 读 stores 目录时不再被一个 547 行、92% 是幽灵的 store 误导成『workspace 状态在这里』。
- **置信度**：high　|　**状态**：待修

#### [BUG-025] Pipeline 集合在 4 处各自硬编码（orchestrator/registry/cli/sdk），registry 抽象只被 runs.py 单独使用

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/engine/orchestrator.py:89-158 · finrobot/engine/pipelines/registry.py:35-43 · finrobot/cli.py:198-441 · finrobot/sdk.py:269-312
- **现象/问题**：新增/改名一个 pipeline 需要同步改 4 个独立位置：orchestrator 里 7 个近乎复制粘贴的 `@agent.tool` wrapper（每个 import + create_*_pipeline + 包一层 _run_pipeline_tool）、registry 的 7 项 map、cli.py 的 7+ 处 inline import+调用、sdk.py 的 7 个 a*() 方法。get_pipeline_factories() 这个本该做唯一收口的注册表，实际只有 routes/runs.py 一个消费方；其余三条执行路（Mode A 对话、CLI、SDK）全部绕过它各搓一遍。
- **证据**：`grep create_*_pipeline 调用点`：orchestrator.py 7 处 + registry.py 7 处 map + cli.py 11 处 + sdk.py 9 处，全部手写。registry.py get_pipeline_factories 仅在 runs.py:124/264 被调。orchestrator 的 8 个 tool 函数体除 docstring 与 pipeline 变量名外完全相同（都是 `return await _run_pipeline_tool(ctx, ticker, X_pipeline)`）。
- **根因**：registry 是后来为打破 server→web→tasks 循环 import 抽出的（registry.py 头注释自述），抽出时只把 runs.py 接过去，orchestrator/cli/sdk 的既有硬编码没回收。第一个出错位置是 registry 引入 PR 未做调用方收敛。
- **修复方案**：让 registry 成为唯一真源并携带 tool 元数据：在 registry 里把每个 pipeline 升级为 `PipelineSpec(key, factory, tool_name, tool_description, cli_help)`。①orchestrator.create_lead_agent 改为 `for spec in iter_pipeline_specs(): agent.tool(_make_tool(spec))`，用闭包工厂生成 tool（pydantic-ai 支持以 docstring/description 动态注册，description 取 spec.tool_description）——删掉 89-158 的 7 个手写 wrapper。②cli.py 的 7 个子命令改为查 registry 取 factory，删 inline import。③sdk.py 的 a*() 改为 `await self._run_pipeline(factories[key], ticker)` 薄封装。注意：orchestrator tool 的 docstring 是 LLM 选 tool 的关键，迁移时务必把现有每条 docstring 原样搬进 spec.tool_description，不能丢；ic-memo 的 key 含连字符，确认 tool 名映射（run_ic_memo）单独存字段。改动量级：跨 3 文件的中型重构。
- **验证补充**：Plan is correct and high-value. One caveat: orchestrator tool docstrings ARE the LLM's tool-selection signal — they must be carried verbatim into PipelineSpec.tool_description (finding already flags this). Also note registry currently maps key→factory only; upgrading to PipelineSpec must keep the lazy-import pattern (registry.py exists specifically to avoid eager imports / circular deps) — generate tool closures lazily, don't import all pipelines at module load. ic-memo key→run_ic_memo tool-name mapping needs an explicit field, confirmed.
- **影响面/回归风险**：影响面：Mode A tool 注册、CLI、SDK 三条路。回归风险中——需保证迁移后 LLM 仍能按 description 正确路由（建议保留一个 test 断言每个 spec 都注册成 tool 且 description 非空）。收益：以后加 pipeline 改 1 处 registry 即可，根除『改一半』漂移（已知 BUG-049 批量运行发 equity_research 而非 research 的 key 漂移就是这类问题的同源症状）。
- **置信度**：high　|　**状态**：待修

#### [BUG-026] DCF/DDM seed 用「最近 2 年」中位数，却在 provenance 和 docstring 里全程标注「过去 3 年中位数」——给分析师看的口径说明是假的

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/engine/compute/dcf_seed.py:55 (_MIN_HISTORY_SAMPLES=2) + _median_ratio:65-100 + _median_recent:444-457；标签产出点 dcf_seed.py:227/280/305/314/324 等全部 prov[...] 字符串
- **现象/问题**：seed_dcf_inputs / seed_ddm_inputs 把 ebitda_margin、capex/营收、D&A/营收、ΔNWC/营收等所有 ticker 历史中位数都通过 _median_ratio/_median_recent 计算，这两个函数用 min_samples 同时充当『最少样本门槛』和『取数窗口』，默认值 2 → 实际只取最近 2 个财年。但所有调用点写进 assumption_provenance 的中文说明都是『过去 3 年 X 中位数』，模块 docstring 也写『historical 3y medians』『ticker historical median (3y)』。fetch_historical_metrics 实际拉 years=5,数据充足,窗口纯粹被 _MIN_HISTORY_SAMPLES=2 截断。
- **证据**：dcf_seed.py:83-84 `nums = numerator[-min_samples:]` / `dens = denominator[-min_samples:]`,min_samples 默认 _MIN_HISTORY_SAMPLES=2;_median_recent:454 `values[-min_samples:]` 同样 2。所有 prov 串如 line 280 `f"{ebitda_margin:.1%}（过去 3 年 EBITDA 利润率中位数）"`、line 305/314/324 同。pipelines/_helpers.py:338 与 dcf.py:81 调用 fetch_historical_metrics(years=5) 证明 3+ 年数据可得,窗口非数据所限。对一只利润率在抬升的票(如 NVDA EBITDA margin 逐年扩张),2 年中位数 vs 3 年中位数会差好几个百分点,而 UI 上的溯源句子声称是 3 年,直接违反项目『每个数字可追溯、报错一个数字砸招牌』红线。
- **根因**：_MIN_HISTORY_SAMPLES 一个常量被复用为两个语义不同的概念:『信任 ticker 自身中位数前至少需要几年样本』(门槛)和『中位数取最近几年』(窗口)。当门槛被定为 2(允许只有 2 年历史的票也用自身数),窗口就被钉死成 2,而文案按设计意图的 3 年写。
- **修复方案**：在 dcf_seed.py 拆分两个常量:保留 _MIN_HISTORY_SAMPLES=2 仅作门槛(`if n < _MIN_HISTORY_SAMPLES: return None`),新增 _MEDIAN_WINDOW_YEARS=3 用于切片(`nums = numerator[-_MEDIAN_WINDOW_YEARS:]`,_median_recent 同改)。_median_ratio/_median_recent 签名把 window 与 min_samples 分开传。注意:门槛仍是 2 时,只有 2 年历史的票切片 [-3:] 自然只拿到 2 个值——行为正确且文案应改为动态『过去 {len(used)} 年』。最稳妥是让两个函数返回实际用到的样本数,prov 串改用真实 n 而非硬编码『3』。改动量级:小(2 函数 + ~6 处 prov 文案,单文件),但需同步 ddm_seed(复用同名 helper)。
- **验证补充**：Fix is correct: split the constant into _MIN_HISTORY_SAMPLES (threshold, keep 2) and a separate window (3), pass them independently to _median_ratio/_median_recent. Strongly prefer the finding's own better suggestion: have the helpers return the actual sample count used and render '过去 {n} 年' dynamically, since a 2y-history ticker sliced [-3:] still yields only 2 points — a hardcoded '3' would re-lie. Drop the claim that ddm_seed provenance strings need changing; they don't.
- **影响面/回归风险**：影响每一份 DCF/DDM 研报的假设溯源展示与 seed 出的 fair value(窗口变化会改 ebitda_margin/capex 等中位数,进而改 implied_price)。回归风险:改窗口=改数字,需重跑金融测试(test 里若 mock 2 年数据期望值需更新);若只改文案不改窗口则零数字回归但承认是 2 年。建议改窗口对齐文案(3 年更稳),并核对 tests/ 中相关期望值。
- **置信度**：high　|　**状态**：待修

#### [BUG-027] POST /api/compute/dcf-sensitivity 的 wacc_range/tg_range 无 max_length 上限 → 巨网格阻塞事件循环

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/routes/compute.py:77-81 (DcfSensitivityRequest) + 575-584 (compute_dcf_sensitivity) → engine/compute/dcf.py:86-122 (calculate_sensitivity)
- **现象/问题**：DcfSensitivityRequest.wacc_range / tg_range 只声明 Field(min_length=1)，无 max_length。calculate_sensitivity 是 `for w in wacc_range: for g in tg_range:` 的 O(W×G×N) 纯同步嵌套循环，且该端点直接 `return calculate_sensitivity(...)`，未像 monte-carlo 那样 `asyncio.to_thread` 卸载。一个 `{"wacc_range":[0.1]*5000,"tg_range":[0.02]*5000}` 的请求会构造 2500 万格 × N 年折现，纯 Python 同步算，整段时间阻塞 asyncio 事件循环——期间所有其他 HTTP 请求（含 SSE 轮询、coverage 概览）全部挂起。
- **证据**：compute.py:79-80 `wacc_range: list[float] = Field(min_length=1)`（无上界）；compute.py:575-584 端点同步返回；dcf.py:105-107 双重 for 循环。对照同文件 DcfEquivalenceLineRequest.steps 显式 `Field(default=13, ge=3, le=40)`（line 478）——作者知道要给循环维度封顶，唯独 sensitivity 漏了。复现：`curl -XPOST localhost:8321/api/compute/dcf-sensitivity -d '{"inputs":{...},"wacc_range":[0.1]*8000,"tg_range":[0.02]*8000}'`。
- **根因**：第一出错位置在 compute.py:79-81 的字段定义——缺 max_length 约束。次因是 compute_dcf_sensitivity (575) 未把 CPU-bound 的 calculate_sensitivity 放进 to_thread（即使加了上限，单 worker 下大网格仍应卸载，与同文件 monte-carlo line 664-678 的处理不对称）。
- **修复方案**：改 finrobot/routes/compute.py：(1) DcfSensitivityRequest 的 wacc_range/tg_range 加 `max_length=25`（敏感性表 UI 最多渲染 ~7×7，25 已极宽松，与 build_sensitivity_ranges 实际产出量级一致）；(2) 把 compute_dcf_sensitivity 端点的 `calculate_sensitivity(...)` 包成 `await asyncio.to_thread(calculate_sensitivity, ...)`，与 monte-carlo 端点对称。注意：DcfSeedRequest 内部走 build_sensitivity_ranges 自产范围（已受控），不受此改影响。
- **验证补充**：Fix is correct. build_sensitivity_ranges produces exactly 5×5=25 cells max, so max_length=25 per axis fits legit UI use and never breaks the internal seed path; max_length could even be 50 safely. Add the to_thread offload as proposed to match monte-carlo. Also worth hoisting pv_fcf out of the inner g-loop in dcf.py (it is WACC-dependent, TG-independent) to cut the constant factor, but that is an optimization not required for the fix.
- **影响面/回归风险**：影响面：唯一可被任意客户端（含 Vite dev origin）直接 POST 的同步重计算端点；修复后行为对合法请求零变化（合法 range 远小于 25）。回归风险：极低，只收紧上界 + 卸载线程；需跑 tests/ 中 dcf-sensitivity 相关用例确认 25 上限不误伤现有夹具。
- **置信度**：high　|　**状态**：已修（routes/compute.py：DcfSensitivityRequest 的 wacc_range/tg_range 加 max_length=25（build_sensitivity_ranges 实产 ≤5×5，内部 seed 路径不受影响）；端点 calculate_sensitivity 包 asyncio.to_thread，与 monte-carlo 对称。新增 tests/routes/test_compute_dcf_sensitivity.py（25 接受/26 拒绝/空轴拒绝/happy 形状）。ruff+mypy --strict + 88 compute 用例通过）

#### [BUG-028] No ErrorBoundary in the live app tree — any render crash blanks the whole desktop app

- **类别**：Bug
- **严重度**：P1
- **位置**：ui/src/main.tsx:44-50 + ui/src/router.tsx (AppShell tree); component at ui/src/components/ErrorBoundary.tsx only imported by ui/src/export/generated/viewer.js
- **现象/问题**：The implemented, tested ErrorBoundary is mounted ONLY inside the standalone HTML export viewer bundle. The live application render tree (main.tsx → QueryClientProvider → RouterProvider → AppShell → routes) has no error boundary at any level. A single uncaught render error in any chapter/page/chart unmounts the entire React tree, leaving a blank white screen with no recovery path.
- **证据**：grep for 'ErrorBoundary' across ui/src returns only its own file + export/generated/viewer.js — never main.tsx, router.tsx, or AppShell. main.tsx renders <RouterProvider router={router}/> directly under QueryClientProvider with nothing wrapping it. router.tsx wraps lazy routes in <RouteSuspense> (handles loading, not errors). The ErrorBoundary class (ErrorBoundary.tsx) is complete: getDerivedStateFromError + a retry button using tSync('shell.error.renderFailed') / tSync('common.retry'). Reproduction: any of the unguarded numeric renders below (e.g. ChapterCompetitive margin NaN is render-safe but a thrown TypeError from a future malformed artifact, or createPortal/getBoundingClientRect on an unexpected shape) crashes to white screen.
- **根因**：ErrorBoundary was authored and exercised by the export viewer but never wired into the primary router. The live tree was never given a top-level catch.
- **修复方案**：In ui/src/main.tsx, import { ErrorBoundary } and wrap <RouterProvider> with it inside QueryClientProvider: `<ErrorBoundary><RouterProvider router={router}/></ErrorBoundary>`. Stronger: also place an ErrorBoundary inside AppShell around the <Outlet/> so a crashed route keeps the Sidebar/TitleBar usable (lets the user navigate away instead of reloading). Confirm shell.error.renderFailed and common.retry exist in both i18n catalogs (they already back the export viewer). No structural change to ErrorBoundary needed — it is ready to mount.
- **验证补充**：Fix is correct and ready to mount as-is. Recommend BOTH layers as the author suggests: wrap <RouterProvider> in main.tsx AND add an inner ErrorBoundary around <Outlet/> in AppShell so a crashed route keeps Sidebar/TitleBar navigable. React-router also supports an errorElement on the root route as an alternative inner-catch — either approach is acceptable; the AppShell-Outlet wrap is simpler and keeps chrome alive.
- **影响面/回归风险**：Pure robustness win, near-zero regression risk (adding a wrapper that is a no-op until something throws). Converts every white-screen-of-death into a recoverable error card. StrictMode double-invoke in dev is unaffected.
- **置信度**：high　|　**状态**：已修（改 ui/src/main.tsx 用 ErrorBoundary 包 RouterProvider（在 QueryClientProvider 内）；ui/src/layout/AppShell.tsx 在 <main> 内只包 <Outlet/>，崩溃路由仍保 Sidebar/TitleBar/StatusBar 可用。i18n shell.error.renderFailed/common.retry 两 catalog 均已存在。验证 npm run lint 零报错 + npm run build(tsc) 通过）

#### [BUG-029] Competitive table renders unguarded gross/operating margin → fabricated 0.0% or literal NaN% when backend value is null

- **类别**：Bug
- **严重度**：P1
- **位置**：ui/src/pages/artifact-detail/chapters/ChapterCompetitive.tsx:158,161 (and TS type ui/src/pages/artifact-detail/chapters/types.ts:73-74)
- **现象/问题**：For every peer/target row the margin cells do `(c.gross_margin * 100).toFixed(1)` and `(c.operating_margin * 100).toFixed(1)` with NO null guard — unlike the adjacent pe_ratio / core_pe_ratio / ev_ebitda cells which all check `!== null && !== undefined` and fall back to '—'. When the backend supplies null (it can, see below), `null * 100` → 0 → renders a fabricated **0.0%** margin; `undefined * 100` → NaN → renders literal **NaN%** to the analyst.
- **证据**：Backend finrobot/engine/models/financial.py:240-241 — CompanyFinancials.gross_margin / operating_margin are `float | None = None` with the explicit 'None ≠ 0' contract (the same None-≠-0 cluster the project just hardened: a provider that omits the figure must NOT be shown as zero). The frontend type CompanyFinancialsShape (types.ts:73-74) wrongly declares them `gross_margin: number` / `operating_margin: number` (non-null), so TS never forces a guard. Render at ChapterCompetitive.tsx:157-162 multiplies directly. This is NOT covered by known BUG-015 (specs/代码审计-bug追踪.md:200-207), which is about core-P/E column *visibility*, not a margin null-deref/fabrication.
- **根因**：Frontend type drift: CompanyFinancialsShape claims margins are non-null while the backend model made them Optional during the None≠0 hardening. The unguarded `* 100` render then fabricates 0.0% (or NaN%) instead of '—'.
- **修复方案**：1) types.ts:73-74 — change to `gross_margin: number | null` and `operating_margin: number | null` to match the backend contract. 2) ChapterCompetitive.tsx:157-162 — guard like the sibling cells: render `c.gross_margin != null ? (c.gross_margin*100).toFixed(1)+'%' : '—'` and same for operating_margin. Note: margins are ratios (0.43) so keep the *100; do NOT route through formatPercent without the alreadyPercent flag. Also audit ChapterFinancialData buildIncomeCells (already guards None) for consistency — it is fine. Mechanical, ~6 lines.
- **验证补充**：Fix is correct. Confirm both: (1) types.ts:73-74 → `number | null`; (2) guard render with `c.gross_margin != null ? (c.gross_margin*100).toFixed(1)+'%' : '—'`. Keep the *100 (margins are ratios ~0.43); do NOT route through formatPercent without alreadyPercent. ~6 lines, mechanical, no behavioral risk.
- **影响面/回归风险**：Removes a fabricated/garbage financial number from the flagship investment-bank report — directly serves the data-integrity red line. Affects any ticker whose peer set has a member with a provider that omits margins (foreign listings, thin coverage). Zero risk to the happy path (full data still renders identically).
- **置信度**：high　|　**状态**：已修（改 ui/.../chapters/types.ts 把 gross_margin/operating_margin 改 number|null（对齐后端 None≠0 契约）；ChapterCompetitive.tsx 两 margin 单元格加 != null 守卫，保留 *100，缺失渲染 — 与同排 pe/ev_ebitda 一致。lint + build(tsc) 通过）

#### [BUG-030] 13 章研报全程硬编码 $，而 Coverage 是币种感知——非美元标的会印错币种符号

- **类别**：Bug
- **严重度**：P1
- **位置**：ui/src/pages/artifact-detail/chapters/ChapterValuation.tsx:127,210-212 / ChapterFinancialData.tsx:122,149-229 / ChapterTechnical.tsx:39-351 / ChapterSensitivity.tsx:84 / ChapterCompetitive.tsx:136 / ChapterOwnershipGovernance.tsx:259,398 / ChapterFinancialAnalysis.tsx:36
- **现象/问题**：研报阅读页的每一个金额都用模板字面量写死美元符号（`$${implied.toFixed(2)}`、fmtMoney=`$${...}`、fmtPrice=`$${...}`、fmtTrillions 返回 $..T/$..B）。types.ts 里研报数据结构根本不带 currency 字段（grep 确认 chapters/types.ts 无 currency）。而 Coverage 侧 CoverageRow 带 currency（api/coverage.ts:69）且 CoverageCard/Inspector 全程走 formatCurrency(v, ccy, locale) 尊重真实币种。
- **证据**：grep 命中 30+ 处 `$${` 横跨 7 个章节文件，覆盖估值/财务数据/技术面/敏感性/竞品/治理薪酬——即一份研报里所有价格、市值、企业价值、目标价、买卖点都强制 $。对一个港股/欧股/日股标的，DCF 隐含价、52 周高低、Sniper 买卖点、CEO 薪酬全部会被打上 $ 但数值其实是 HKD/EUR/JPY——这正是 CLAUDE.md『报错一个数字=砸招牌』『单位/币种极度敏感』的红线。Coverage 卡能对，点进研报就错，同一标的两处币种自相矛盾。
- **根因**：研报渲染链路（artifact→types.ts→chapters）从未把 reporting currency 透传到前端：第一个出错位置是 types.ts 的 shape 定义缺 currency 字段，导致所有 chapter 只能硬写 $。Coverage 链路（coverage.service→CoverageRow.currency）补了这一环，研报链路没补。
- **修复方案**：分两步。① 后端/类型：在 artifact 的 market/financial shape 与 chapters/types.ts 增 reporting_currency（来源同 Coverage 的口径，对齐 coverage.service 取 currency 的字段），ArtifactDetailPage 把它透传给各 Chapter。② 前端：把散落的 `$${x}`、fmtMoney/fmtPrice/fmtTrillions 统一替换为 utils/format.ts 的 formatCurrency(x, currency, locale)（已存在，签名见 format.ts:85），fmtTrillions 改成接收 currency 参数的 compact 版。注意：[金融待核] 当前是否真有非美元标的进研报需对外部源确认——拿一个港股 ticker（如 0700.HK）跑研报，核对『DCF 隐含价/目标价』的币种应为 HKD 而非 $；若产品当前仅支持美股，此条降级为'未来防雷+一致性'但仍应做，因为 Coverage 已经币种感知、研报落后形成内部不一致。
- **验证补充**：Fix direction correct. Refinement: there are TWO currency tags in the backend (reporting_currency for IS/BS line items: revenue/ebitda/debt/cash/comp; quote_currency for market price/market_cap). Per-share prices (DCF implied, 52w, Sniper, target) follow QUOTE currency; revenue/EV/comp follow REPORTING currency. A single 'reporting_currency' passthrough as proposed would mislabel price fields for ADRs where the two differ (TSM: quote=USD, reporting=TWD). The chapter shape must carry BOTH and each field must pick the right one — otherwise the fix introduces a new mislabel. Verify each `$${` site against which tag applies before swapping to formatCurrency.
- **影响面/回归风险**：影响所有非美元标的研报的金额可信度；改动面=7 个 chapter 文件统一替换 + types 加字段 + 透传，纯展示层无计算回归；风险是 formatCurrency 对未知币种的 fallback 行为需测（应回退到币种代码前缀如 'HKD 1.23B' 而非崩）。
- **置信度**：high　|　**状态**：待修

#### [BUG-031] Coverage 批量运行 >6 个 ticker 时耗尽浏览器 HTTP/1.1 连接池，多余的 SSE 与所有普通 API 轮询被无限阻塞

- **类别**：Bug
- **严重度**：P1
- **位置**：ui/src/pages/CoveragePage.tsx:234 (for…trackRun 循环) → ui/src/stores/runStreamStore.ts:168-170 (attachSse 每个 run_id 立刻 new EventSource)
- **现象/问题**：Coverage Desk 的旗舰功能「批量运行」在 onSuccess 里对后端返回的每个 run_id 同步调用 trackExistingRun → attachSse，每个都立刻 open 一条 EventSource 到 /api/runs/{id}/events。这些 SSE 是长连接（整段 pipeline 30-60s 才关）。后端 uvicorn 跑 HTTP/1.1（cli.py:739 无 http2），生产构建直连 http://127.0.0.1:8321（无代理多路复用）。浏览器对单 origin 的 HTTP/1.1 并发连接上限约 6 条。
- **证据**：用户在一个 Studied Tickers 组里勾选 10 个 ticker 点「运行」：后端 batch_run 全部 spawn_run 成功返回 10 个 run_id；前端 for 循环 open 10 条 EventSource。前 ~6 条占满连接池，第 7-10 条被浏览器排队，直到某条先关才连得上。后果叠加：(a) 第 7-10 个 ticker 的卡片永远停在 'running'，收不到任何 step/completed 事件，直到前面的 run 跑完释放连接槽；(b) 连接池被 SSE 占满期间，同 origin 的所有普通查询（useTickerPrice 60s 轮询、useHealth 15s 轮询、overview 刷新）全部排队，整个 app 卡死般无响应。run_semaphore=4 限制后端并发，但不限制前端 SSE 连接数——两者错位放大了问题。
- **根因**：runStreamStore.attachSse 每个 run 一条独立 EventSource，且 CoveragePage 在 batch onSuccess 里无节流地全量 attach。第一个出错位置是 attachSse 的「一 run 一长连接」设计在批量场景下没有连接预算意识。
- **修复方案**：两选一，推荐 A。A（根治）：为 Coverage 批量场景改用单条聚合 SSE——后端加 GET /api/runs/events?ids=a,b,c（或按 group 聚合）一条流推所有 run 的事件，前端 CoveragePage 只 open 1 条，runStreamStore 暴露 attachMultiplexed(runIds, tickerByRunId) 解析后分发到各 ticker 的 patch。改动量级：中（后端新增聚合 route + 前端新增 multiplex 解析，约 150-250 行）。B（缓解，非根治）：在 runStreamStore 加一个模块级 SSE 连接上限（如 5），attachSse 超限时把 runId 入队，等某条 closeAndForget 后再从队列取下一个连接；批量场景轮流连接。注意：B 仍让后 N 个 ticker 延迟显示进度，且不解决普通查询被挤占——只把『卡死』降级为『分批显示』。注意事项：无论哪条都要在 clear/卸载时 close 全部并清队列，避免泄漏。
- **验证补充**：Fix is sound. Minor note: cleanup must close on component unmount too, not only clear() — CoveragePage never calls clear() on navigate-away, so the proposed queue/budget teardown should hook an unmount/visibility path or the connections persist. Also fix A's aggregated route still needs Last-Event-ID resume parity to keep the existing reconnect behavior.
- **影响面/回归风险**：影响 Coverage Desk 批量运行（核心差异化功能）+ 批量期间的整个 app 响应性。回归风险：A 改动后端事件分发，需保证单 run 路径（/stocks 单跑）不受影响（可保留旧单 run SSE，仅 Coverage 用聚合）。
- **置信度**：high　|　**状态**：待修

#### [BUG-032] Coverage overview 全量 fetch 失败但 fast skeleton 成功时，卡片市场列永久空白——无错误态、无 shimmer、无重试入口

- **类别**：Bug
- **严重度**：P1
- **位置**：ui/src/hooks/useCoverage.ts:47-71 (useCoverageOverview 的 isError / marketPending 推导) → 消费方 ui/src/pages/CoveragePage.tsx:362-384 + ui/src/components/coverage/CoverageCard.tsx:87
- **现象/问题**：两段式 overview：fast skeleton（本地 SQLite，仅 research/run 态，市场字段全 None）先画表，full fetch 回填 price/market_cap/ev_ebitda/pe。当 full 查询失败而 fast 成功时，三态推导塌陷成『看起来一切正常但数据全空』：isError = !data && full.isError，因 data = full.data ?? fast.data 取到 fast.data（truthy），故 isError=false；marketPending = !full.data && !!fast.data && !full.isError，因 full.isError=true 故 marketPending=false。
- **证据**：后端 service.py:186-188 确认 fast 模式 market/signal/upside 全留 None。CoverageCard.tsx:87 的 mc(node) 在 marketPending=false 时直接渲染 row 的 null 市场字段（显示 '—'）。于是 full fetch 因 provider 超时/502 失败后，整张 Coverage 表的 price、market_cap、EV/EBITDA、P/E、涨跌幅、upside 全部显示『—』，既没有 ErrorState（CoveragePage:364 的 isError 分支不触发），也没有 Shimmer 占位，也没有 onRetry 按钮。用户无法分辨『这些公司真没数据』还是『行情拉取挂了』，且无任何重试入口（overviewQuery.refetch 只在 isError 分支的 ErrorState 里暴露）。
- **根因**：useCoverageOverview 把『有任意数据』(fast.data 兜底) 当作『成功』，但 fast.data 在语义上是『市场数据尚缺』而非『市场数据为空』。第一个出错位置是 useCoverage.ts:67-68 的 isError/marketPending 没有区分『full 还在 loading（应 shimmer）』与『full 已 error（应报错或保持 shimmer+提示）』两种 !full.data 情形。
- **修复方案**：改 ui/src/hooks/useCoverage.ts:64-70 的返回推导：新增一个 marketError 标志 = !full.data && full.isError && !!fast.data，并在 CoverageOverviewState 暴露；同时把 marketPending 改为 !full.data && !!fast.data && !full.isError（保持）。消费方两选一：(a) marketError 为真时，让 CoverageCard 的市场列继续渲染 Shimmer 并在卡片角标/inspector 显示一个小重试图标调 overviewQuery.refetch()；或 (b) 更简单：marketPending 的定义改成 !full.data && !!fast.data（去掉 !full.isError 这一项），这样 full 失败时市场列保持 Shimmer 而非塌成『—』，并在表头加一条可点重试的 degraded 提示条。注意事项：纯 (b) 会让 full 永久失败时 Shimmer 转圈不停，需配合一个表头级 retry，不能只 Shimmer。
- **验证补充**：Fix direction correct. Note: the fast query has enabled:`!!groupId && !full.data`; on full.isError full.data stays undefined so fast stays enabled and its data persists — good for the shimmer-retain approach. Ensure the new header retry calls full.refetch() (not fast) so it re-attempts the market fetch.
- **影响面/回归风险**：影响 Coverage Desk 的可信度（金融工具最忌『静默显示空数据』被误读为真值）。回归风险低：只改派生标志与卡片占位，不动数据流。
- **置信度**：high　|　**状态**：已修（useCoverage.useCoverageOverview 新增 marketError=!full.data && full.isError && !!fast.data；marketPending 去掉 !full.isError 项→full 失败时市场列保持 Shimmer 而非塌成 —。CoveragePage 加 MarketRetryBar（marketError 时显「行情拉取失败，点击重试」可关闭条，重试调 full.refetch 非 fast；token 化样式，新增 i18n coverage.error.marketFailed/dismiss）。区分「真没数据」与「拉取失败」。lint+build+116 测试通过。）

#### [BUG-033] Chat tools and /api/runs accept unvalidated ticker strings while a SoT ticker validator already exists in coverage — junk symbols fan out to live providers

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/engine/orchestrator.py:69 & 92-158 (tool ticker params) + finrobot/routes/runs.py:62 (_normalise_ticker); validator at finrobot/routes/coverage.py:53 (_TICKER_RE)  ·  （另涉：finrobot/routes/compare.py:28-32 + finrobot/routes/compute.py:97/176/468 (各 ticker 字段) ; finrobot/coverage/sqlite_store.py:48-57 (coverage_members 表无 FK/无校验) + routes/coverage.py:53 (_TICKER_RE 仅格式校验) + coverage/service.py:163-208 (_assemble_row 运行期降级)）
- **现象/问题**：`_TICKER_RE = re.compile(r'^[A-Z0-9.\-]{1,12}$')` exists in coverage.py with an explicit comment (lines 50-52): it was added for BUG-053 to stop junk like '苹果', 'AAPL;MSFT', or over-long strings 'from being persisted and then fanned out to providers forever.' But the chat tools (`run_equity_research`(ticker), …, `query_financial_data`(ticker)) and the `/api/runs` path's `_normalise_ticker` only do `.strip().upper()` with at most a blank check (runs.py:128). So the LLM (or a curl to /api/runs) can drive a full 8-step pipeline / provider fan-out on 'TESLA INC', a company name, a 60-char string, or a SQL-ish blob — wasting an entire pipeline run and N provider calls, and persisting a garbage-keyed artifact.
- **证据**：coverage.py:53-71 validates and rejects. runs.py:62-63 `return t.strip().upper()` — no regex; only `if not norm` blank-check at 128. orchestrator.py tool signatures take raw `ticker: str`. yfinance_provider.py:91 `return yf.Ticker(symbol)` makes a live network object from whatever string arrives; FMP/Finnhub providers similarly interpolate the symbol into request URLs. The validator is described as 'Single backend source of truth' yet two of the three pipeline entry points ignore it.
- **根因**：`_TICKER_RE` lives in routes/coverage.py (a route module) instead of a shared util, so the runs route and the orchestrator tools never call it — classic path split. First wrong location: the validator's placement in coverage.py rather than a shared engine/data util that all three entry points import.
- **修复方案**：Lift `_TICKER_RE` + a `validate_ticker(s) -> str` helper into a shared module (e.g. finrobot/engine/data/ticker.py or finrobot/utils/ticker.py), then: (a) coverage.py imports it (delete its local copy); (b) runs.py `_normalise_ticker` calls it and raises ValueError on miss (already mapped to 400 at create_run line 153-154); (c) orchestrator.py `_run_pipeline_tool` and `query_financial_data` validate ticker up front and return a clean tool-result string ('Invalid ticker symbol: X') instead of running the pipeline — returning, not raising, so the chat stream stays alive (see finding #4). Keep the ui/src/utils/ticker.ts mirror in sync (the comment already flags this dual-maintenance). Small change (~25 lines, 3 call sites + 1 new file).
- **验证补充**：Lift _TICKER_RE + validate_ticker() into a shared module (engine/data/ticker.py) and call from all three entry points. Important boundary nuance: in orchestrator tools, RETURN a clean string ('Invalid ticker: X') rather than raise — a raised ValueError there crashes the SSE stream exactly like #3 (the fix text says this; enforce it). Keep ui/src/utils/ticker.ts mirror in sync. P2 is right (waste/abuse, not data corruption of a real ticker).
- **影响面/回归风险**：Stops wasted pipeline runs and provider quota burn on garbage symbols across all three entry points; prevents garbage-keyed artifacts/cache rows. Regression risk: legitimate exotic symbols must still pass — the regex already allows BRK.B/RDS.A style (dots, hyphens, digits, 1-12 chars); verify any real ticker in current coverage still matches before shipping.
- **合并自**：bug-routes-api#3, gap-r1-3#3, arch-datamodel#3（3 条同源发现）
- **置信度**：high　|　**状态**：已修（routes/runs._normalise_ticker、orchestrator 的 run_* 工具与 query_financial_data、routes/coverage、routes/search 全部改用共享 validate_ticker。关键边界：orchestrator 在坏 ticker 时 RETURN 干净字符串（"Invalid ticker symbol: X"）而非 raise，避免崩 SSE 流。reconcile coverage{1,12}/search{1,10} 漂移。验证 BRK.B/RDS.A 通过、苹果/AAPL;DROP/TESLA INC 拒绝。未动 validators.py:140（留后续）。ui/utils/ticker.ts 已是 {1,12} 无漂移。与 BUG-020 同提交。）

#### [BUG-034] SSE run.completed / run.failed can be lost: status flips to terminal in the DB before the terminal event is appended, so the poll loop may break and never emit it

- **类别**：Bug
- **严重度**：P2
- **位置**：finrobot/routes/runs.py:356-364 (completed) & :416-423 (failed) vs :231-237 (stream_run_events poll loop)  ·  （另涉：finrobot/routes/runs.py:338-363 (_run_pipeline_impl 成功分支内部)）
- **现象/问题**：In _run_pipeline_impl the run row is set to status='completed' (update_run, line 356) BEFORE the RunCompleted event is appended (line 364). The SSE generator polls every 0.2s: it (a) drains events_after(current_seq), (b) reads get_run, (c) if status∈{completed,failed} fetches trailing events and breaks. If a poll iteration observes status='completed' (line 356 already committed) while RunCompleted (line 364) is not yet committed, and the trailing fetch at step (c) runs before line 364 commits, the loop breaks WITHOUT ever yielding run.completed. Same window on the failed path (status set 416, RunFailed appended 423).
- **证据**：Ordering in runs.py: ArtifactReady is appended (340-355) BEFORE the status flip (356) — safe. But RunCompleted is appended at 364, AFTER update_run(status='completed') at 356. The two are separate awaited DB commits on a lock-serialized aiosqlite connection, so an interleaving where the poll's get_run + trailing get_events_after both land between the 356 commit and the 364 commit is reachable (a ~ms window, polled at 200ms). Frontend (per architecture map / debate.py:160 comment) depends on receiving the terminal event; without it EventSource reads the server-side stream close as an error and enters the SSE_ERROR_LIMIT=8 reconnect path the codebase explicitly documents as the '请检查后端' failure.
- **根因**：State transition (status column) and its corresponding event are written in the wrong order and non-atomically: the terminal status becomes visible to readers before the terminal event exists.
- **修复方案**：In routes/runs.py, append the RunCompleted/RunFailed event BEFORE calling update_run(status=...). i.e. swap so the event row exists before the status flips terminal. Then the poll's invariant holds: any reader that sees a terminal status is guaranteed the terminal event is already in run_events and will be caught by either the main or trailing get_events_after. Apply to both the success block (move the _append(RunCompleted) above update_run(status='completed')) and the except block (move _append(RunFailed) above update_run(status='failed')). Keep result_text/result_json/artifact writes wherever, but the status flip must be the last write. Note: ArtifactReady ordering is already correct; only the terminal-event ordering needs the swap.
- **验证补充**：Fix correct and minimal: move _append(RunCompleted) ABOVE update_run(status='completed'), and _append(RunFailed) ABOVE update_run(status='failed'). Then any reader seeing a terminal status is guaranteed the terminal event already exists. Note severity is genuinely P2 not P1: frontend already has SSE reconnect (SSE_ERROR_LIMIT=8) and on reconnect the trailing get_events_after replays the now-committed terminal event, so the user-visible failure is a transient reconnect, not a permanent hang — still worth fixing but not data-loss-permanent.
- **影响面/回归风险**：Affects all runs but only on a narrow timing window — low frequency, high annoyance when it hits (UI shows a stuck spinner / spurious reconnect storm, and the completion CTA never fires). Fix is a 2-line reorder per branch, no schema change; regression risk minimal. Recommend a test that asserts run_events contains the terminal event whenever runs.status is terminal.
- **合并自**：bug-pipeline#3, bug-routes-api#4（2 条同源发现）
- **置信度**：medium　|　**状态**：待修

#### [BUG-035] SDK 的 provider 链漏注册 NewsAggregatorProvider，与 build_data_layer 漂移

- **类别**：Bug
- **严重度**：P2
- **位置**：finrobot/sdk.py:105-138 (_ensure_deps) vs finrobot/data_layer_factory.py:82-86
- **现象/问题**：sdk.py:_ensure_deps 手搓 provider 链时只 append 了 FMP/Finnhub/yfinance/Edgar/Adanos，**没有 NewsAggregatorProvider**；而服务端唯一装配点 build_data_layer 始终 append NewsAggregatorProvider（Yahoo RSS 免费、无 key）。结果：任何走 SDK（FinRobot().research/analyze/aresearch，以及独立 CLI 进程若复用 SDK 路径）的调用，DataType.NEWS 取数能力比 server 进程少一个 always-on 源——研报的新闻/催化剂章节、sentiment 旁路在 SDK 下静默降级（拿不到 Yahoo RSS 兜底新闻），而同一 ticker 在桌面 App 里却有。两套 provider 组装逻辑分裂，未来任一处加 provider 都会再漂移。
- **证据**：data_layer_factory.py:82-86 注释明写 `News aggregator — always registered; uses Yahoo RSS (free, no key)` 并无条件 append；sdk.py:114 之后只到 Adanos(122-125) 就直接 cache+DataLayer(130-131)，全程无 NewsAggregatorProvider import。架构地图 P1 已独立标出此漂移。
- **根因**：第一出错位置 sdk.py:_ensure_deps——它是 build_data_layer 的平行复制实现，复制时漏掉了 news_aggregator 这一支。根因是 provider 装配没有单一事实源：sdk 本应直接调用 build_data_layer(settings) 而非自己重搓。
- **修复方案**：改 finrobot/sdk.py：删除 _ensure_deps 里手搓 provider 链的整段（105-131 的 providers 构造 + DataCache + DataLayer），改为 `from finrobot.data_layer_factory import build_data_layer; data_layer = build_data_layer(self._settings)`，让 SDK 与 server 共用唯一装配点。注意：build_data_layer 内部已处理 Edgar 条件注册 + Adanos + news，与现有 sdk 逻辑等价但多了 news；需确认 sdk 不依赖 cache 对象的单独引用（close() 走 data_layer.close() 即可）。这是连根拔路径分裂，符合红线，非最小改动。
- **验证补充**：Fix is correct and is the right root-cause collapse: replace the hand-built providers+cache+DataLayer block (sdk.py:105-131) with `from finrobot.data_layer_factory import build_data_layer; data_layer = build_data_layer(self._settings)`. Verified close() only calls self._deps.data_layer.close(), so dropping the separate `cache` local is safe (DataLayer.close delegates to cache.close). The skills registry (lines 127-128) and create_sub_agents (137) are unrelated to data_layer and must stay.
- **影响面/回归风险**：影响面：所有 SDK/脚本用户的新闻取数恢复与桌面端一致；消除两处 provider 装配漂移源。回归风险：低——build_data_layer 是 server 每次启动都跑的成熟路径；唯一行为变化是 SDK 多出 news 源（正向）。需跑 SDK 相关测试确认 DataLayer 构造签名一致。
- **置信度**：high　|　**状态**：待修

#### [BUG-036] Football Field 的 DCF 区间永远是装饰性 ±20%:_dcf_band 读错字段,Monte Carlo P10/P90 分支是死代码,source 标签可误导

- **类别**：Bug
- **严重度**：P2
- **位置**：finrobot/engine/compute/valuation_aggregator.py:165-172 (_dcf_band)
- **现象/问题**：_dcf_band 想优先用 Monte Carlo 的 P10/P90 做 DCF 区间,否则回退 ±20%。它从 `dcf.sensitivity_table` 里 get('p10')/get('p90')。但 sensitivity_table 在所有写入点(dcf.py:119、equity_research.py:458、ic_memo.py:116、compute.py:288/447)装的都是 calculate_sensitivity 产出的 WACC×TG 网格,键是 {wacc_values, tg_values, implied_prices},根本没有 p10/p90 键。而 Monte Carlo 的 percentiles 用的键是 '5'/'10'/.../'90'(monte_carlo.py:236),也不叫 p10/p90,且从未被写进 DCFResult.sensitivity_table。所以 isinstance(p10,...) 分支永远 False,DCF 行永远走 mid*(1±0.20),source 永远是 'implied_price ± 20%'。
- **证据**：_dcf_band:167-171 `sensitivity = dcf.sensitivity_table or {}; p10 = sensitivity.get('p10')`。dcf.py:118-119 `sensitivity = calculate_sensitivity(...); dcf_result.model_copy(update={'sensitivity_table': sensitivity})`,calculate_sensitivity(dcf.py:120-124) 只 return {'wacc_values','tg_values','implied_prices'}。monte_carlo.py:236 `percentiles = {str(p): ... for p in [5,10,25,50,75,90,95]}` 键是 '10'/'90' 不是 'p10'/'p90',且无任何代码把 MonteCarloResult 回填进 DCFResult.sensitivity_table。
- **根因**：两处口径漂移:(1) p10/p90 这两个键从未存在于任何被写入 sensitivity_table 的结构;(2) 即便想接 Monte Carlo,其百分位键名是 '10'/'90' 不是 'p10'/'p90',且 MC 结果与 DCFResult 没有连线。这是一个『写了优先路径但从未通电』的占位实现。
- **修复方案**：决定要不要真接 Monte Carlo P10/P90:若要,在 dcf 管线跑完 calculate_dcf 后调 run_monte_carlo,把 result.percentiles['10']/['90'] 存进 DCFResult.sensitivity_table['p10']/['p90'](或新增专门字段),_dcf_band 保持读 p10/p90;若暂不接,则删掉 _dcf_band 的 MC 分支与 'monte_carlo_p10_p90' source 标签,只留 ±20% 并把 source 文案改成诚实的『implied_price ± 20%(占位区间,非真实分布)』,避免 UI 显示一个永不出现的来源名。倾向后者(删死代码)符合项目反占位红线。改动量级:小(单函数)。
- **验证补充**：Both options viable; the finding's lean (delete the MC branch, keep honest ±20%, drop the never-emitted 'monte_carlo_p10_p90' label) is the right call for an anti-placeholder cleanup and is the lower-risk change. If instead wiring real MC is desired, note the percentile keys are '10'/'90' (str) not 'p10'/'p90' — the finding correctly catches this. Minor: the proposed honest source text '占位区间，非真实分布' is fine but the current 'implied_price ± 20%' is already honest, so the rename is optional polish, not a correctness fix.
- **影响面/回归风险**：影响 Football Field 上 DCF 行的区间宽度与来源标注。当前无崩溃(有回退),但区间是固定 ±20% 的假精度,且代码暗示有 MC 分布支撑而实际没有。回归风险极低。
- **置信度**：high　|　**状态**：待修

#### [BUG-037] 外币 SEC 申报人的 XBRL 营收/净利未做 FX 换算即被当作 USD，35% 散度门可能漏掉近平价货币

- **类别**：Bug
- **严重度**：P2
- **位置**：finrobot/engine/data/providers/edgar_provider.py:880-917 (_float/get_*) + xbrl_aligned_comps.py:66 (35% 门)
- **现象/问题**：edgartools 标准 getter 以 unit='USD'、strict_unit_match=False 调用，对外币申报人(20-F 的外国私人发行人，functional currency 为 EUR/GBP/CHF/JPY 等)会判定货币 "compatible" 而直接返回未换算的本币数值，仅给一句 suggestion 而 success=True。TTM 路径(TTMCalculator)更是完全不按 unit 过滤，直接 sum numeric_value。FinAgent 把这些值当 USD 用。
- **证据**：已读 UnitNormalizer.get_normalized_value 源码：当 normalized_unit != target 且非 strict 且 are_compatible 为真时，返回原币值 value(只附 "Consider currency conversion" suggestion)，不做汇率换算；实测 are_compatible(EUR,USD)=True、两者均为 CURRENCY 类型。_get_standardized_concept_value 在 unit 未显式传入时 strict_unit_match=None→False。comps 路径 _helpers.py:171-172 对每个 peer 调 fetch(XBRL_FACTS) 后 override_company_with_xbrl，而 FMP base 已在 167-169 行 FX 归一到 USD——于是用未换算外币 XBRL 去和 USD 基比对。
- **根因**：调用 edgartools getter 时未启用严格单位匹配/未拿回 unit 字段，库本身不做 FX。唯一防线是 xbrl_aligned_comps.py:66 的 35% 散度门(_TTM_DIVERGENCE_TOLERANCE)：本币与 USD 差异 >35% 才回退 FMP。对近平价货币(GBP≈1.27、CHF≈1.1)散度可能 <35%，未换算外币值会静默 override 掉正确的 FMP USD 值。
- **修复方案**：在 edgar_provider _fetch_xbrl 里对每个 getter 用 return_detailed 取 UnitResult，检查 normalized_unit；若 != 'USD' 则该字段返回 None(让下游回退 FMP)并 append warning "XBRL fact in {ccy}, not USD; suppressed"，绝不把外币值当 USD 透出。注意：这是保守丢弃而非现场 FX(现场 FX 需引入汇率源，超出本层职责)；与 normalize_peer_to_usd 的边界保持一致。改动量级：中。
- **验证补充**：Fix (suppress foreign-unit facts to None + warn) is the right boundary-consistent choice vs introducing an FX source here. BUT the fix text targets only _fetch_xbrl getters (latest_*/snapshot). The HIGHER-risk path is the comps override which uses ttm_revenue/ttm_net_income from _select_recent_ttm/TTMCalculator — that path must ALSO be unit-guarded (check metric.unit, which calculator.py:185 sets to ttm_quarters[0].unit, and suppress when !=USD). Guarding only the getters leaves the comps override exposed.
- **影响面/回归风险**：影响外国 SEC 申报人作为 target 或 peer 时的 comps/估值正确性；US 申报人(绝大多数路径)不受影响。当前占位 identity 下 Edgar provider 未注册故未触发，但配真 identity 后即为活口。回归风险低(US 票走原 USD 快路径不变)。
- **置信度**：medium　|　**状态**：待修

#### [BUG-038] peer 倍数白名单用未格式化原始 float 注入（median_pe/pe_ratio/market_cap），LLM 在 competitor_analysis 里复述时口径/精度无锚，且与前端表格显示口径不保证一致

- **类别**：Bug
- **严重度**：P2
- **位置**：finrobot/engine/pipelines/equity_research.py:739-752
- **现象/问题**：白名单注入 peer 倍数时用裸 f-string 插值 {pa_for_prompt.median_pe} / {p.pe_ratio} / {p.market_cap}（740-751），不像 valuation 字段那样统一 :.2f 格式化，也不带单位/口径标注。LLM 拿到的是 28.736199... 这样的原始浮点，复述进 competitor_analysis 时会自行四舍五入/换算，得到的数可能与前端 SourcedNumber 表格渲染的同一字段不一致。
- **证据**：对比：valuation methods 用 low=${m.low:.2f}（726 行）显式两位小数，DCF wacc 用 :.4f（758），而 peer 段 740-751 全是裸值。market_cap 尤其危险——若是 3411000000000 这样的裸数，LLM 在散文里要么照印天文数字要么自行换算成 '$3.4T'，换算口径（B/T/亿）无约束。已知基线 BUG-015/029 正是 competitive 章节 as-reported vs core P/E 口径分裂的同源风险面，本条是其'精度/格式'侧未覆盖的活口。
- **根因**：白名单 builder 对 peer 段未做与 valuation 段对称的格式化与单位标注；median_pe 等可能为 None 时还会注入字面 'None'（无 isinstance/格式守卫），LLM 可能把 'None' 误读为某种值。第一出错位置=739-752 的裸插值。
- **修复方案**：在 equity_research.py:739-752 给 peer 段加与 valuation 段一致的格式化：median_pe/pe_ratio 用 :.1f 或 :.2f 并显式标 'x'（倍），market_cap 用确定性 humanize（如 _fmt_market_cap → '$3.41T'）后再注入，None 值显式写 'n/a（未取得）'而非裸 None。注意要和前端 SourcedNumber 的渲染口径对齐（同一 humanize 规则），否则只是把不一致从 prompt 端搬到渲染端。属小改，<30 行。
- **验证补充**：Fix is correct and the author's own caveat is the load-bearing one: the humanize rule MUST match the frontend SourcedNumber render (ev_ebitda/pe rendered as 'x', market_cap as $T/$B) or you just relocate the inconsistency. Verify the exact ui render format before picking :.1f vs :.2f. Also guard None explicitly so 'None' never reaches the LLM. <30 lines is realistic.
- **影响面/回归风险**：影响 competitor_analysis 叙事与前端 peer 表的数字一致性观感。回归低，仅改 prompt 文本格式；需顺手核对前端 market_cap/PE 的格式化函数取同一口径。
- **置信度**：medium　|　**状态**：待修

#### [BUG-039] `is_sampled` compares against GLOBAL store count, not the in-window / in-scope population → mislabels fully-covered windows as 'partial'

- **类别**：Bug
- **严重度**：P2
- **位置**：finrobot/routes/dashboard.py:181-182  ·  （另涉：ui/src/hooks/useDashboardHitRate.ts:21-26 (HitRateOverview interface) vs finrobot/routes/dashboard.py:76-80）
- **现象/问题**：`store_count = await store.count(include_archived=False)` is the count of ALL non-archived artifacts; `is_sampled = store_count > 500`. But the aggregation that produces the buckets is filtered by `window` (30d/90d, cutoff applied in compute_hit_rate_overview) AND, for scoped calls, by ticker set. So `is_sampled` answers a different question than the buckets represent: a 30d window whose in-window artifacts number 40 (store total 700) is reported `is_sampled=true`, implying 'we only show part of your 30d record' — false, the 30d window captured everything. Symmetrically it cannot flag the real truncation in the scoped-group case above.
- **证据**：dashboard.py:181 counts the whole store; dashboard.py:185-188 `compute_hit_rate_overview(artifacts=inputs, window=window)` applies the window cutoff (hit_rate_overview.py:88-94) AFTER the 500-cap fetch. So the population the buckets describe = (newest-500 ∩ window ∩ tickers), but `is_sampled` is derived purely from the unfiltered global COUNT(*). The flag is honest only for the unscoped, window='all' case.
- **根因**：The sampling check uses a denominator (`store.count()` global all-time) that does not match the population actually aggregated (window-cut and/or ticker-scoped). The 500 cap only causes real data loss when the IN-window, in-scope artifact count exceeds 500 — that is the condition `is_sampled` should test, not 'store has >500 rows total'.
- **修复方案**：Compute the comparison count over the SAME filter the buckets use. Add `count(window, tickers)` capability: for window!='all' add a `created_at >= cutoff` clause and (for scoped) an `IN` clause to `SqliteArtifactStore.count`, then `is_sampled = scoped_windowed_count > _HIT_RATE_SAMPLE_CAP`. Simplest correct version: have `_collect_signal_inputs` also return the true scoped+windowed COUNT(*) (one extra cheap query) and set `is_sampled` from that, not from the global count. Note: keep `sample_size` = cap. Change size: ~20 lines (store.count signature + route wiring + test).
- **验证补充**：Sound. Simplest correct fix: have _collect_signal_inputs return the true scoped+windowed COUNT(*) and derive is_sampled from that. Note the window cut currently lives inside the aggregation, not in SQL, so adding a created_at>=cutoff clause to count() must mirror the aggregation's entry_date semantics exactly (it filters on entry_date==created_at) to stay consistent.
- **影响面/回归风险**：Makes the only 'is this number trustworthy' flag on a first-screen analyst statistic actually correct. Pairs with the scoped-truncation fix (same store method touched). Regression risk: low; affects only the boolean flag value, not bucket math.
- **合并自**：gap-r1-4#2, gap-r1-4#3（2 条同源发现）
- **置信度**：high　|　**状态**：待修

#### [BUG-040] Cumulative total_return shown beside annualized-intent Sharpe; annualized Returns analyzer added but never read

- **类别**：Bug
- **严重度**：P2
- **位置**：finrobot/engine/backtest/backtrader_adapter.py:130 (Returns analyzer added) + :148 (total_return cumulative) + engine.py:84-87 (format_summary)
- **现象/问题**：total_return = (final-initial)/initial is the RAW CUMULATIVE return over the entire window (could be 3 days or 5 years), printed as 'Total Return: +X%' directly above an annualized-framed Sharpe ('Sharpe ratio assumes risk-free rate of 4.0%'). A quant reading +60% total return next to Sharpe 1.2 cannot tell if that 60% is over 1 year or 5 years — the two metrics are on different time bases with no period label. Worse, the code adds `bt.analyzers.Returns` (which computes rnorm/rnorm100 = the ANNUALIZED normalized return) at line 130 but NEVER extracts it — it is a dead analyzer. The one number that would make the mix honest (annualized return) is computed and thrown away.
- **证据**：Line 130 `cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")` has no corresponding get_analysis() call (grep for 'returns'/'rnorm' in the adapter returns only the addanalyzer line and an unrelated warning string). Returns.get_analysis() exposes rnorm100 (annualized %). engine.py format_summary prints total_return and sharpe with no period/annualization annotation.
- **根因**：The Returns analyzer was wired in (line 130) but the extraction + BacktestResult field were never added, leaving total_return as the only return metric and it is cumulative. First wrong location: missing _extract_returns + missing annualized_return field on BacktestResult.
- **修复方案**：Add to BacktestResult (engine.py) a field `annualized_return: float | None = None`. In backtrader_adapter._run_sync add `annualized_return = self._extract_returns(strat, warnings)` reading `strat.analyzers.returns.get_analysis().get('rnorm100')/100`. Pass it into BacktestResult. In engine.py format_summary print both with explicit basis, e.g. 'Total Return (cumulative): +X%' and 'Annualized Return: +Y%'. Either consume the Returns analyzer or remove line 130 — do not leave it dead. Note strategy_agent selects on total_return; consider whether selection should use annualized_return when windows differ (here windows are fixed per run so it is fine, but document it).
- **验证补充**：Fix is correct: add annualized_return field + _extract_returns reading rnorm100/100, or remove the dead analyzer. Minor: rnorm100 is already a percent (e.g. 0.286 meaning 0.286%/... actually it is %); divide by 100 to get a fraction for consistency with total_return being a fraction — the proposed '/100' is right. Keep the explicit-basis labels.
- **影响面/回归风险**：Display/clarity correctness; no change to underlying trade simulation. Adds one optional field (backward compatible). Low regression risk; format_summary string output changes (update any test pinning exact summary text).
- **置信度**：high　|　**状态**：待修

#### [BUG-041] run_strategy_selection tunes 3 iterations on one in-sample window and reports max(total_return) as a 'good' strategy — pure overfitting, no out-of-sample

- **类别**：Bug
- **严重度**：P2
- **位置**：finrobot/engine/backtest/strategy_agent.py:118-163 (loop + best_result = max total_return) + :42-53 (_ADJUSTMENT_TEMPLATE)
- **现象/问题**：--auto / aauto_backtest runs the SAME start_date→end_date window up to 3 times, lets the LLM nudge params toward higher total_return, and returns `max(total_return)` (line 129) as the recommended strategy. There is zero out-of-sample / holdout / walk-forward split. The whole window is the optimization set AND the evaluation set. For the target user (quant researchers) this is textbook in-sample overfitting presented as a 'tuned' result — the most dangerous failure mode in quant, because it looks like rigor (LLM 'reasoning' + deterministic backtest) while delivering a curve-fit number with no generalization signal. The prompt explicitly asks the LLM to 'adjust parameters to try to improve performance' on results it just saw on that same window.
- **证据**：Lines 118-159: for iteration in 1..3, run on config (immutable dates forced every iteration to start_date/end_date), `if result.total_return > best_result.total_return: best_result = result`, return best_result. No second window anywhere (grep for out-of-sample/walk-forward/holdout/train.test in the backtest module finds nothing). _ADJUSTMENT_TEMPLATE line 48-51 feeds 'Best result so far: total_return=...' and asks to improve. Selection metric is total_return, not even risk-adjusted.
- **根因**：Design: the optimization loop never partitions the date range into in-sample (tune) vs out-of-sample (evaluate). First wrong location: run_strategy_selection takes a single (start_date,end_date) and reuses it for every iteration and for final reporting.
- **修复方案**：[重构, ~medium] Split the window: derive an in-sample sub-range (e.g. first 70% of the date span) for the 3 tuning iterations and an out-of-sample tail (last 30%) for the final reported result. Tune on in-sample (select best params by in-sample metric), then run ONCE on out-of-sample with those params and return THAT BacktestResult, with warnings noting 'params tuned on in-sample {is_start}-{is_end}, reported on out-of-sample {oos_start}-{oos_end}'. Also switch the selection metric from raw total_return to a risk-adjusted one (Sharpe, after the Sharpe fix) or at least annualized_return. If a hard split is too invasive now, the minimum non-band-aid change is to attach a prominent warning to the returned result: 'Parameters tuned and evaluated on the same window; result is in-sample and likely overfit — not a validated strategy.' Update strategy_agent docstring (lines 1-9, currently claims 'tuned strategy' framing). Note: changing return semantics is a behavior change to the --auto/aauto_backtest contract — flag as [破坏性] for CLI/SDK callers.
- **验证补充**：70/30 IS/OOS split + report OOS result is the right direction and is correctly flagged [破坏性] for CLI/SDK callers. Implementation cautions: (1) the date range is just YYYY-MM-DD strings — splitting requires parsing to dates and picking a boundary; ensure the OOS window is long enough for the SMA slow period (default 30) to warm up or the OOS run yields zero trades. (2) Switching selection to Sharpe depends on fixing finding [0] first, else selection is on None; until then annualized_return (finding [1]) is the safer interim selection metric. (3) The fallback 'just attach a prominent overfit warning' is acceptable per house rules only if the full split is deferred with an explicit reason — but given build-phase 'do it right' discipline, prefer the real split.
- **影响面/回归风险**：Affects CLI --auto and SDK auto_backtest/aauto_backtest only (not exposed via routes/agents). Behavior change: returned result reflects OOS not best-in-sample, so numbers drop — that is the point. Regression: tests in test_strategy_agent.py assert best-across-iterations semantics (lines 141,184) and would need rewrite. High product value: stops shipping overfit numbers to quant users.
- **置信度**：high　|　**状态**：待修

#### [BUG-042] Sniper LONG mode: secondary_buy (20-day support) can sit BELOW stop_loss → incoherent trade row passes invariant guards

- **类别**：Bug
- **严重度**：P2
- **位置**：finrobot/engine/compute/sniper.py:161-203
- **现象/问题**：In LONG mode the second entry level secondary_buy=support (20-day rolling min). stop_loss is floored at current*0.85. When the 20-day window contains a deep drawdown (support well below current), secondary_buy ends up BELOW stop_loss — i.e. the chart shows a 'secondary buy' price you could only reach after already being stopped out. The artifact renders an incoherent ladder (stop above a buy level) to a professional analyst, undermining the 'every number traceable/coherent' promise.
- **证据**：Worked example: current=100, 20-day support=70 (a recent crash low still in the window), low vol. Code: stop_loss=max(support - vol_buffer, current*0.85)=max(~65, 85)=85; secondary_buy=support=70. Result secondary_buy(70) < stop_loss(85). The invariant block (sniper.py:182-203) only validates take_profit vs ideal_buy and stop_loss vs ideal_buy — it never checks secondary_buy, so this row ships.
- **根因**：sniper.py:161 sets secondary_buy=support unconditionally, while sniper.py:166 floors stop_loss at current*0.85 independent of support. No invariant ties the two. First problematic site is the missing guard / the unconditional secondary_buy=support at line 161 when support < stop floor.
- **修复方案**：In sniper.py LONG branch, after computing stop_loss, clamp secondary_buy to not fall below stop_loss: `secondary_buy = max(support, stop_loss)` OR, if support<stop_loss, drop the secondary level and add an invariant_warning ('20-day support below stop; no secondary entry'). Add the coherence check to the invariant block (lines 193-203): for LONG assert stop_loss < secondary_buy <= take_profit (or secondary_buy is None). Add a unit test in tests/unit covering a price series whose 20-day min is far below current. Small change (~5 lines + test).
- **验证补充**：Fix is sound. Prefer the 'drop secondary level + invariant_warning' variant over silently clamping secondary_buy=max(support,stop_loss), because clamping would collapse secondary_buy onto stop_loss (a degenerate entry==stop), mirroring the same degeneracy the SHORT branch already warns against (sniper.py:121-126). Add the invariant assertion stop_loss < secondary_buy <= take_profit (or secondary_buy is None) to the LONG guard, and a unit test with a crash-low series.
- **影响面/回归风险**：Edge-case only (requires a deep recent drawdown in the trailing-20 window), but removes a visibly wrong trade ladder. Regression risk low; verify the UI sniper card / SHORT branch (which uses different anchors) is unaffected — SHORT sets secondary_buy=max(resistance,current) and is already coherent.
- **置信度**：high　|　**状态**：待修

#### [BUG-043] Unauthenticated POST /chat, /api/runs and /api/coverage/groups/{id}/runs burn metered LLM credits with zero inbound rate limiting

- **类别**：Bug
- **严重度**：P2
- **位置**：finrobot/server.py:662 (/chat), finrobot/routes/runs.py:143 (POST /api/runs), finrobot/routes/coverage.py:339 (batch runs); no rate-limit middleware anywhere
- **现象/问题**：Three endpoints spend the user's real LLM money (DeepSeek/Anthropic/OpenAI) per call. All are unauthenticated (finding 1) and there is NO inbound rate limiting (the only rate-limit code in the repo is outbound quote-fetch throttling in engine/data/quote_*). A local process or DNS-rebind page can loop POST /chat or fire POST /api/coverage/groups/{id}/runs against a large group to spawn many pipelines. The run_semaphore(=4) caps *concurrency* but not *total spend* — an attacker just keeps the queue full, draining credits and EDGAR rate budget indefinitely.
- **证据**：server.py:662 chat() opens an LLM stream after only a startup_error check; runs.py:138 spawn_run creates an asyncio task per request with no per-caller quota; coverage.py:339 batch endpoint fans out one run per member ticker. `grep RateLimit|slowapi|limiter` finds only QuoteFetchRateLimited (outbound provider throttle), nothing inbound. run_semaphore at server.py:152 bounds parallelism to 4 but unbounded requests just queue (status stays 'created').
- **根因**：Cost-bearing actions share the same no-auth boundary as free reads (finding 1), plus there is no notion of a spend budget / inbound throttle anywhere in the app.
- **修复方案**：The auth token (finding 1) removes the hostile-caller vector and is the correct primary fix. As defense-in-depth against runaway loops (incl. buggy clients), add a lightweight in-process token-bucket on the cost-bearing endpoints — e.g. a small dependency in runs.py/coverage.py/server.py chat() that limits new runs to N/minute and rejects with 429 beyond that. ~30 LoC, single shared limiter object on app.state. 注意 batch runs legitimately spawn many at once — bucket on 'runs started per minute' not 'per request' so a normal coverage batch of 10 still goes through.
- **验证补充**：Fix sound. The in-process token-bucket as defense-in-depth (also catches buggy clients/retry storms) is worth doing independent of auth. Bucket on 'runs started per minute' not per-request, as noted, so a legit 10-ticker coverage batch isn't rejected.
- **影响面/回归风险**：Financial-loss containment. Low regression risk (429 only triggers under abnormal volume); must size the bucket above the largest legitimate coverage batch.
- **置信度**：high　|　**状态**：待修

#### [BUG-044] Unauthenticated DELETE /api/artifacts/{id} and DELETE /api/coverage/groups/{id} permanently destroy stored research

- **类别**：Bug
- **严重度**：P2
- **位置**：finrobot/routes/artifacts.py:210 (DELETE artifact), finrobot/routes/coverage.py:234 (DELETE group)
- **现象/问题**：Two DELETE endpoints destroy persisted state (a generated equity-research artifact; an entire coverage group with its members) and are unauthenticated (finding 1). DELETE is a non-simple method, so a cross-origin browser fetch would be preflighted and blocked by CORS — BUT DNS rebinding makes the request same-origin (preflight passes) and any local process can issue the DELETE directly via curl. For the target user (an analyst whose artifacts are their work product), silent loss of a report is a real harm, and there is no soft-delete/undo on the artifact path.
- **证据**：artifacts.py:210 `@router.delete('/{artifact_id}')`; coverage.py:234 `@router.delete('/groups/{group_id}', status_code=204)`. Both reachable with no credential. CORS forces preflight for DELETE cross-origin, but TrustedHostMiddleware is absent (finding 1) so a rebind request is same-origin and skips that protection; curl from another local process is unaffected by CORS in any case.
- **根因**：Destructive endpoints behind the zero-auth boundary (root cause = finding 1).
- **修复方案**：Covered by the finding-1 auth token (primary). Orthogonal hardening worth doing now for the analyst-work-product case: make artifact deletion a soft archive (set a deleted_at column in artifacts.db rather than hard DELETE) so an accidental or malicious delete is recoverable; the store already has archive_stale plumbing (artifact/store.py) to build on. ~20-40 LoC in artifact/sqlite_store.py + the route.
- **验证补充**：Fix valid. Soft-archive (deleted_at column) is a reasonable orthogonal hardening for the work-product case; verify the claimed archive_stale plumbing in artifact/store.py actually exists before estimating 20-40 LoC (I did not confirm that specific helper this session). Auth from finding 0 remains the primary fix.
- **影响面/回归风险**：Data-loss containment for the user's primary work product. Soft-delete change touches artifact store schema + list filters (must exclude soft-deleted rows); moderate regression surface, covered by artifact store tests.
- **置信度**：high　|　**状态**：待修

#### [BUG-045] ProviderHealth 熔断器是完全未接线的死代码，docstring 谎称「DataLayer owns the wiring」——慢/限流 provider 每次仍付满超时

- **类别**：Bug
- **严重度**：P2
- **位置**：finrobot/engine/data/provider_health.py:1-13（docstring 称 DataLayer 调 record_*/is_available）；实际 finrobot/engine/data/layer.py:82-89 的 provider 循环无任何 health 调用
- **现象/问题**：provider_health.py 实现了一个完整的 per-provider 熔断状态机，docstring 第 11-12 行明写「the DataLayer owns the wiring (calls record_* / is_available around provider.fetch)」。但通读 layer.py 全文，DataLayer.fetch / fetch_quote / fetch_price / fetch_historical 的 provider 循环里**没有任何** record_success/record_failure/is_available 调用。全仓库 grep（排除自身与 test）对 ProviderHealth 的唯一引用是 interface.py:78 一句注释（"批3's ProviderHealth circuit-breaker will use..."）。即整模块是 dead code，且 docstring 与现实矛盾，会误导维护者以为熔断已生效。后果：当 FMP/Finnhub 持续 429 或慢，DataLayer 每次请求仍按优先级顺序付满 15s 超时（_TIMEOUT），批量 Coverage 跑被拖垮——正是该模块声称要解决的问题。
- **证据**：`grep -rn 'ProviderHealth|record_success|record_failure|is_available' finrobot/ --include=*.py`（排除 provider_health.py 自身与 test）仅命中 interface.py:78 注释。layer.py:82-89 provider 循环：`for provider in self._providers: ... try: result = await provider.fetch(...) except ProviderError as e: logger.warning(...); continue`——无 health gate。BACKLOG 也把「Provider 健康机制（无 ProviderHealth/熔断状态机）」列为 P0 未建能力，印证此模块是半成品。附带：provider_health.py:23 与 interface.py:65-70 各有一份 is_rate_limit_error，marker 集还**不一致**（health 有 'throttl' 无 'rate-limit'；interface 有 'rate-limit' 无 'throttl'），两套分类对同一个 429 文本可能给出不同判断。
- **根因**：模块按 BACKLOG P0 写了纯函数实现但从未接进 DataLayer；docstring 描述的是目标态而非现状（第一出错位置=layer.py 循环缺 wiring，叠加 docstring 撒谎）。
- **修复方案**：二选一、择一即做到位：(A) 真接线——在 DataLayer.__init__ 持一个 ProviderHealth 实例，provider 循环里 `if not health.is_available(provider.name): continue`，成功调 record_success，ProviderError 调 record_failure(name, is_rate_limit_error(e))；fetch_quote/fetch_price/fetch_historical/fetch_price_range 四处循环都要接（对称性）。同时把 is_rate_limit_error 收口到 interface.py 一份，删 provider_health.py:26-29 的副本，统一 marker 集（合并为 429/too many requests/rate limit/rate-limit/throttl）。(B) 若暂不接线，则删除 provider_health.py 并修正 interface.py:78 误导注释——但 CLAUDE.md 建设期红线倾向「现在做对」，推荐 A。改动量级：A 约 60-80 行 + 测试；B 删文件。
- **验证补充**：Recommendation A (wire it) aligns with CLAUDE.md建设期 red line and is correct; must wire all four loops (fetch/fetch_quote/fetch_price/fetch_historical+range) for symmetry, consolidate is_rate_limit_error to interface.py's one copy, and merge marker sets to the union {429, too many requests, rate limit, rate-limit, throttl}. Also fix the stale BACKLOG:52 ('没有 ProviderHealth') since the registry does exist. P2 is right: real latency/throughput cost under throttling + maintainer-misleading docstring, but not a data-correctness/security issue.
- **影响面/回归风险**：A 影响所有 provider 失败/限流路径的性能与正确降级，回归风险中（需测：熔断打开后 DataLayer 跳过该 provider、冷却后恢复；不能因熔断把唯一可用 provider 也跳过导致全失败）。B 零功能风险。当前现状下用户感知=批量行情/研报在某 provider 抽风时整体变慢。
- **置信度**：high　|　**状态**：待修

#### [BUG-046] 硬编码中文数据层告警混入英文 CLI 输出(--lang en 不生效于 provider 告警)

- **类别**：Bug
- **严重度**：P2
- **位置**：finrobot/engine/data/layer.py:146-147,153 → 经 base.py:758/789 进入 format_summary 英文报告
- **现象/问题**：DataLayer.fetch 在'全源失败用陈旧缓存'和'无数据'两种情况写死中文 warning(layer.py:146 '⚠️ 数据源全部失败，正在显示 N 小时前的缓存数据…请稍后重试'；:153 '数据暂不可用…所有数据源失败且无缓存')。这些 warning 进入 DataResult.warnings→structured_data.warnings→format_summary 的英文'## Data Source Notes'与英文 Disclaimer 段(base.py:764-800)。分析师跑 `finrobot research AAPL --lang en` 遇到陈旧缓存时，得到一份中英混排的报告。
- **证据**：layer.py:142 注释自承'retail users'——但目标用户是分析师，且 CLI 有 --lang en 明确请求英文。--lang 只控制 LLM 叙事语言(effective_lang，base.py:336)，控不到 provider 层这些写死中文串。format_summary(base.py:758) 无条件把 model.warnings 原样列出，不按 lang 切换。
- **根因**：第一出错位置=layer.py:146/153 把面向用户的 warning 文案写死中文，且 warning 文案与 effective_lang 完全解耦(provider 层拿不到 lang)。
- **修复方案**：layer.py 这两条 warning 改为英文(provider/数据层是面向开发者+全语言报告的底层，应英文中性)，把'陈旧/缓存/不可用'语义用英文表达，例如 'All data sources failed; showing cached data from {n}h ago ({ticker}/{data_type}). Retry later for fresh data.'。中文本地化应在展示层(UI WarningBanner / 报告渲染)按 meta.language 翻译，而非写死在数据层。注意 base.py:790-793 的 source_warnings 过滤靠英文子串 'source'/'stale'/'cache' 匹配——当前中文 warning 根本匹配不上这些子串，所以陈旧告警其实没进 Disclaimer 的 Data Sources 段(二次 bug)，改英文后会被正确匹配收进 disclaimer。改动量小但需扫一遍其它写死中文的 provider 告警一并处理。
- **验证补充**：Direction correct: data/provider layer should emit neutral English; localization belongs in the display/UI layer keyed on meta.language. Note the comment at layer.py:142 ('retail users') is itself off-target per project positioning (analysts). Sweep for other hardcoded-Chinese provider warnings as the finding says. Minor: changing to English also fixes the disclaimer-filter miss as a free side effect, so call that out as the real correctness win, not just cosmetics.
- **影响面/回归风险**：影响所有语言下的报告/CLI 输出一致性 + 修复 disclaimer 漏收陈旧告警。回归风险：若有测试断言中文 warning 文案需同步更新；UI 若直接渲染了这些中文串需改为本地化。
- **置信度**：high　|　**状态**：待修

#### [BUG-047] comps --peers 校验滞后且不验格式：错峰到管线中段(已耗 ~30s)才裸崩

- **类别**：Bug
- **严重度**：P2
- **位置**：finrobot/cli.py:237-241 → finrobot/engine/pipelines/_helpers.py:147-152 (peer_analysis step)
- **现象/问题**：`--peers` help 文案承诺'3-10'，但 cli.py:237-239 只 split/strip/upper，不校验数量也不校验 ticker 格式。真正的数量校验在 _helpers.py:149-152 的 peer_analysis 步骤里(raise ValueError 非 recoverable)，而那是 comps 管线第 2+ 步——data_collection 已先跑完(~30s+ LLM+取数)才在 peer 步裸崩(经 _is_recoverable_exception 判非 recoverable→re-raise 穿透 execute→asyncio.run 裸 traceback，cli.py:241 无 try)。且 ticker 格式从不校验:`--peers '苹果,!!!'` 会原样进 PeerSelection 喂 provider。
- **证据**：复现：`finrobot comps AAPL --peers MSFT,GOOGL`(仅 2 个)→ 先跑完 data_collection→peer 步 raise ValueError('--peers needs 3-10 tickers, got 2')→裸 traceback(非干净 CLI 错)。对照同文件 compare 命令把 2-10 数量校验前置到 cli.py:420-423 给了干净 ClickException——comps 没对称处理。_peer_override(_helpers.py:76-95) 只 dedupe/strip，无 _TICKER_RE。
- **根因**：第一出错位置=cli.py:223-241 comps 命令未在入口对 peers 做数量(3-10)+格式校验，把校验推迟到管线深处且以裸 ValueError 形式抛出。
- **修复方案**：在 cli.py comps 命令解析 --peers 后立即校验(复用 finding#1 抽出的 normalize_cli_ticker + 数量检查)：`peers_list = [normalize_cli_ticker(p) for p in peers.split(',') if p.strip()]; if not 3 <= len(peers_list) <= 10: raise click.ClickException(f'--peers needs 3-10 tickers, got {len(peers_list)}')`，再传给 extra['peers']。这样非法输入 0 秒拦下、不浪费一次 data_collection。_helpers.py:149 的运行期校验保留作纵深防御(SDK/路由也走它)。注意常量 _PEER_COMP_SET_MIN 当前=3，CLI 侧硬编码 3 时加注释指向该常量避免漂移。改动量~5 行。
- **验证补充**：Fix correct. Reuse the finding#0 normalize_cli_ticker plus a count check at the comps entry. Keep _helpers.py:149 runtime check as defense-in-depth (SDK/routes still go through it) — the finding already says this. Minor: hardcoding '3' in CLI duplicates _PEER_COMP_SET_MIN; better to import the constant than comment-link it, to avoid the very drift the finding warns about.
- **影响面/回归风险**：仅影响 comps --peers 误用的反馈时机与质量；合法输入零影响。回归风险低。
- **置信度**：high　|　**状态**：待修

#### [BUG-048] archive_stale 全表 get()+save() 逐行重写整份 payload，O(N) 次完整 JSON 反序列化+序列化

- **类别**：Bug
- **严重度**：P2
- **位置**：finrobot/artifact/sqlite_store.py:358-381 (archive_stale)  ·  （另涉：finrobot/artifact/sqlite_store.py:342-348 (mark_viewed→save) + 228-257 (save 全列 UPSERT 含 payload) ; finrobot/artifact/sqlite_store.py:358-381）
- **现象/问题**：archive_stale 先 SELECT 全部未归档行的 (id,created_at,last_viewed_at) 判龄，对每个过期行调 get()（整 payload 反序列化成 Artifact）+ save()（整 payload 重新序列化 + upsert 全部 15 列）。它本质只想把一个 bool（archived）+ 一个时间列翻成 true，却为每行付了两次完整 payload 编解码。equity_research payload 含 raw_data 全量行情快照，单份可达数十 KB~MB 级。
- **证据**：sqlite_store.py:375-379 注释自陈『Full re-save so the embedded payload meta.archived stays in sync with the column』——为保 payload 内 meta.archived 与列一致而整份重写。server.py:187 背景任务 hours=24*30，一次扫 30 天前所有未归档行，批量场景下是 N 次 MB 级 JSON roundtrip。这不是正确性 bug（结果对），是 archive 模式选择导致的 O(N·payload) I/O。
- **根因**：第一设计点 = payload 内嵌了一份 meta.archived 副本，与独立的 archived 列双存，为维持二者一致只能整份重写。根因是 archived 状态被存了两遍（列 + payload.meta）。
- **修复方案**：两选一:(A) 轻量——archive 改纯列 UPDATE `UPDATE artifacts SET archived=1 WHERE archived=0 AND <age 条件>`（一条 SQL 批量），接受 payload.meta.archived 与列短暂不一致；get() 返回时用列值覆盖 payload.meta.archived 再返回（读时对齐，写时不整份重写）。(B) 彻底——把 archived/last_viewed_at 从 payload.meta 移除，只存列，payload 不再冗余存这俩易变字段（它们本就不属于『可 replay 的计算快照』，放 meta 是建模越界）。推荐 B：archived/last_viewed_at 是生命周期元数据，不是 audit 快照的一部分，从 payload 拿掉后 archive_stale 自然变成一条 UPDATE，mark_viewed 同理。注意:B 需改 ArtifactMeta + 所有读 meta.archived 的点改读列 + 一次性 migration 容忍旧 payload 里残留这俩字段（model 设 ignore extra 或保留字段但不再权威）。改动量级:A 小 / B 中（跨 models+store+读取点）。
- **验证补充**：Recommended Fix B (move archived/last_viewed_at out of payload.meta, keep as columns only) is the correct root-fix — these are lifecycle metadata, not part of the replayable compute snapshot, so storing them in the audit payload is modeling越界. archive_stale then collapses to one batch UPDATE, mark_viewed likewise. Needs: ArtifactMeta change + read-point migration + tolerate residual fields in legacy payloads (model_config extra='ignore' or keep field non-authoritative). Fix A is a valid cheaper interim but B is the建设期-correct choice.
- **影响面/回归风险**：A 仅改 archive_stale + get；B 触及 ArtifactMeta 契约（archived/last_viewed_at 语义）。回归风险:B 需确认没有消费方依赖 payload.meta.archived 作权威（当前列才是权威，meta 那份本就是冗余镜像，故风险可控）。
- **合并自**：arch-storage#2, arch-storage#5, arch-datamodel#5（3 条同源发现）
- **置信度**：high　|　**状态**：待修

#### [BUG-049] data_cache.cache 表永不淘汰,只增不减(无 TTL 清理/容量上限)

- **类别**：Bug
- **严重度**：P2
- **位置**：finrobot/engine/data/cache.py:14-22 (表无过期清理) + 272-278 (只有手动 clear)
- **现象/问题**：cache 表的 TTL 只用于『读时判 is_stale』,从不删行。过期行永久留存,只能靠手动 cache.clear() 全清或按 ticker 清。随『研究过的 ticker 数 × data_type 数 × canonical/raw 双槽 × PRICE 各 period 后缀』线性增长,无上限。
- **证据**：sqlite3 ~/.finrobot/data_cache.db:231 行 3.4MB,MIN(cached_at)=2026-05-29(5 天前的行还在),MAX=今天 → 过期行从未被清。cache.py 全文搜 DELETE 只有 clear()(275/277)两处,无任何按 cached_at 的淘汰。PRICE 槽还按 period 后缀(cached_fetch cache_key_suffix `:{period}`)裂成多行/ticker。raw_slot_key + canonical_key 又把每 ticker 每类型 ×2 槽。
- **根因**：cache.py 设计为『读时 TTL 判断』而非『写时/定期淘汰』。没有后台清理任务(server.py 只有 _archive_stale_background 管 artifacts,不碰 data_cache),也没有行数/字节上限。单桌面用户短期无感,但研究面铺开(分析师覆盖几百标的)后 data_cache.db 持续膨胀,且每次 _get_slot 的索引虽是 PK 命中、但 VACUUM 从不跑 → 文件只涨不缩。
- **修复方案**：在 server.py 的 startup background 加一个周期任务(复用 _archive_stale_background 的 asyncio.create_task 模式),调用新方法 `DataCache.evict_expired()`:`DELETE FROM cache WHERE cached_at < ?`(阈值取各 TTL 的保守上界,如 max(_TTL_SECONDS) 的 N 倍,或简单按 30 天硬上限删)。注意:别按 _get_ttl_seconds 精确删,因为 raw/canonical/period 槽的 data_type 列已带后缀,精确 TTL 反查复杂;粗粒度按绝对天数删最稳。删后可选 `PRAGMA incremental_vacuum` 或周期 VACUUM 回收文件。改动量:小(1 方法 + 1 background task)。
- **验证补充**：Fix (background evict_expired with coarse absolute-age DELETE + optional VACUUM) is sound. Coarse absolute cutoff is the right call given raw/canonical/period suffixes make per-type TTL reverse-lookup messy. Keep P2 — slow leak, no correctness impact, single-user impact is gradual.
- **影响面/回归风险**：影响磁盘占用与冷启动扫描成本,非正确性。回归风险低(删的都是过期行,读路径本就当 stale 重取)。当前 3.4MB 无感,属增长性技术债。
- **置信度**：high　|　**状态**：待修

#### [BUG-050] run_events 无限增长 + SSE 0.2s 轮询单连接 → 批跑下打满单库单锁

- **类别**：Bug
- **严重度**：P2
- **位置**：finrobot/run_store.py:47-55 (run_events 无清理) + finrobot/routes/runs.py:226-238 (0.2s 轮询 get_events_after)
- **现象/问题**：run_events 每个 run 累积 12-22 行,run 完成后从不删除;runs 表本身也不清。SSE 传输(runs.py)每 0.2s 对 run_events 跑一次 get_events_after(=5 QPS/活动 run),全部打在 RunStore 的单一 aiosqlite 连接 + 单 _conn_lock 上。Coverage 批跑 N 个 ticker 并发 = N 条轮询协程 ×5 QPS 全挤一条连接。
- **证据**：sqlite3 ~/.finrobot/runs.db:run_events 198 行 / 16 runs,MAX 22 行/run,AVG 12.4。全仓搜 DELETE FROM run_events / prune event:0 处 → 永不清。runs.py:226-238 轮询间隔 0.2s。run_store 所有方法共用 self._conn(单连接)+ self._conn_lock(虽只 init 用,但单连接=所有 SQL 串行在一个 aiosqlite worker 线程)。批跑受 run_semaphore=4 限,但已完成/排队的 run 的 SSE 流仍在轮询。
- **根因**：两个独立缺口叠加:(1) run_events/runs 无生命周期管理——没有『run 完成 M 天后清事件』的任务;(2) SSE 用 DB 轮询而非内存 pub/sub(events.py 无内存广播),把本可 O(1) 内存通知的事流变成对单库的持续 SELECT。表越大,每次 get_events_after(WHERE run_id=? AND seq>?)虽有 idx_events_run 索引命中,但行数膨胀 + 高频轮询 + 单连接串行,放大尾延迟。
- **修复方案**：两步:(a) 加事件保留:server.py background 周期 `DELETE FROM run_events WHERE run_id IN (SELECT run_id FROM runs WHERE completed_at < ?)`(终态 run 超 7 天清事件;runs 行可保留做历史)。(b) 降轮询压力:已完成 run 的 SSE 在发完 run.completed/failed 后立刻 break(确认 runs.py:233 trailing 逻辑已读完终态即停);把轮询间隔在『无新事件』时退避(0.2s→指数到 1s)。彻底解法是内存事件总线(asyncio.Queue per run_id,append_event 同时 put,SSE await queue.get())——但属 P3 重构,先做 (a)+退避。改动量:(a)(b) 小;内存总线 中。
- **验证补充**：IMPORTANT correction to the prose: the terminal-state break (runs.py:232-237) AND the client-disconnect early-return (222-224) ALREADY EXIST — so the author's proposed step (b) 'confirm trailing logic breaks on terminal state' is already done, and completed/queued runs do NOT keep polling forever (disconnect stops them). The genuine gaps are just: (1) unbounded run_events growth, (2) 0.2s busy-poll on a single shared connection under batch fan-out. Fix (a) event retention DELETE + backoff on idle poll is correct; the asyncio.Queue pub/sub is the real fix but P3. Keep P2.
- **影响面/回归风险**：批跑/长会话场景的库压与延迟,非正确性。回归风险低(清的是终态 run 的旧事件,resume via Last-Event-ID 只对活动 run 有意义)。当前 198 行无感。
- **置信度**：high　|　**状态**：待修

#### [BUG-051] 前端 pipeline 类型清单三处不一致：appStore 缺 ddm，runStreamStore/后端 registry 含 ddm

- **类别**：Bug
- **严重度**：P2
- **位置**：ui/src/stores/appStore.ts:11 (PipelineType, 6 项) vs ui/src/stores/runStreamStore.ts:90-111 (PIPELINE_STEP_NAMES, 7 项) vs finrobot/engine/pipelines/registry.py:36-42 (7 项)
- **现象/问题**：appStore 的 `PipelineType = 'research'|'dcf'|'comps'|'earnings'|'lbo'|'ic-memo'` 只有 6 个，漏了 ddm；runStreamStore.PIPELINE_STEP_NAMES 有 ddm（7 个）；后端 registry 也有 ddm（7 个）。三份手工维护的 pipeline 枚举互不一致。
- **证据**：appStore.ts:11 明确 6 项无 ddm。runStreamStore.ts:109 有 `ddm: ['data_collection','ddm_modeling','report']`。registry.py:39 有 `'ddm'`。runStreamStore 的 pipelineType 字段类型本身已松成 `string`（line 43）不再约束，等于放弃了类型层防护。
- **根因**：PipelineType 与 PIPELINE_STEP_NAMES 是各自独立硬编码、靠人记得同步。DDM pipeline 后加时改了 runStreamStore 和后端，漏改 appStore（而 appStore 此字段恰好已无运行时消费方，所以没暴露成 bug——但若复用 appStore.PipelineType 做 ddm 触发会编译期漏类型）。第一个出错位置是 ddm 引入 PR。
- **修复方案**：与上一条收敛同源：后端 registry 暴露一个 `/api/pipelines` 或在 OpenAPI schema 里导出 pipeline key 枚举，前端 PipelineType 改为从 `schema.d.ts` 生成的 union 派生（generate:api 已有 codegen 管线），删掉 appStore.ts:11 的手写 union；PIPELINE_STEP_NAMES 仍需手维护步名（步名是前端镜像，注释已说明），但 key 集合应来自同一 union 以触发『缺 ddm 即编译红』。若不想接后端，至少把 PipelineType 与 PIPELINE_STEP_NAMES 的 key 用一个 `satisfies Record<PipelineType, ...>` 绑定，让缺项编译期报错。注意 appStore 若按 finding-1 删除，则 PipelineType 须迁到 types 文件再做绑定。
- **验证补充**：Severity P2 is fair but note this is partly a SYMPTOM of F0+F1: once appStore is deleted (F0) and pipeline keys are sourced from registry (F1), the appStore.PipelineType union vanishes and the only remaining frontend mirror is PIPELINE_STEP_NAMES. Best fix is the F1/F2 combined: export pipeline keys via OpenAPI/`/api/pipelines` so the union is codegen-derived (generate:api pipeline exists), and bind PIPELINE_STEP_NAMES with `satisfies Record<PipelineKey,...>` so a missing key is a compile error. Don't fix F2 standalone — fold into F0/F1 to avoid re-introducing a hand-maintained union.
- **影响面/回归风险**：影响面：触发 run 的类型安全。当前因 appStore.PipelineType 无消费方故无运行时 bug，属潜伏隐患（任何复用此 union 的新代码会静默缺 ddm 分支）。回归风险低。
- **置信度**：high　|　**状态**：待修

#### [BUG-052] query_financial_data raises an unguarded ValueError on a bad data_type, crashing the live chat SSE stream

- **类别**：Bug
- **严重度**：P2
- **位置**：finrobot/engine/orchestrator.py:67-74 (query_financial_data) → finrobot/engine/data/layer.py:70 (DataType(data_type))  ·  （另涉：finrobot/engine/orchestrator.py:67-74 vs finrobot/engine/agents/factory.py:41-47）
- **现象/问题**：The tool signature is `data_type: str | DataType` and the docstring lists only 6 of the 23 real enum values. When the model passes any string that isn't an exact DataType value — e.g. 'balance_sheet', 'income_statement', 'cashflow', 'fundamentals', or just 'financial' — `data_layer.fetch` runs `DataType(data_type)` at layer.py:70, which raises a bare `ValueError`. The tool has no try/except and does not raise ModelRetry, so in pydantic-ai 1.73 the exception propagates out of the agent run and tears down the in-flight /chat SSE stream mid-response instead of letting the model recover.
- **证据**：orchestrator.py:73 `result = await ctx.deps.data_layer.fetch(data_type, ticker)` — no guard. Verified `DataType('garbage')` raises `ValueError: 'garbage' is not a valid DataType`. Grep of orchestrator.py shows zero try/except/ModelRetry. The docstring (orchestrator.py:72) advertises only 'financials, price, news, earnings, filings, 10k_rag' but the enum has 23 members, so the model is under-informed about valid values and likely to guess synonyms.
- **根因**：The tool delegates straight to fetch() which validates the enum and raises, but the tool neither constrains data_type to a Literal/enum the framework can validate-and-retry, nor catches the ValueError to return a retryable message. First wrong location: orchestrator.py:73 calling fetch without guarding the enum coercion (layer.py:70 is where the raise originates but the tool is responsible for handling it).
- **修复方案**：In orchestrator.py query_financial_data, validate up front: `try: dt = DataType(data_type) except ValueError: raise ModelRetry(f"Unknown data_type {data_type!r}. Valid: {[d.value for d in DataType]}")` (import ModelRetry from pydantic_ai). ModelRetry feeds the error back to the model so it self-corrects instead of crashing the stream. Also widen/correct the docstring to enumerate the real common values (financials/price/quote/news/earnings/filings/profile/historical/quarterly/forward_estimates/...) so the model picks valid ones first try. Small change (~6 lines, 1 file).
- **验证补充**：Fix is correct: `try: dt=DataType(data_type) except ValueError: raise ModelRetry(...)` (ModelRetry import verified) feeds the error back so the model self-corrects. Use the coerced `dt` in the fetch call to avoid re-coercion. Also widen the docstring to the real common values. Same ModelRetry-not-raise discipline should be applied to the ticker validation in #2.
- **影响面/回归风险**：Prevents a one-token model mistake from killing a live chat session. Low regression risk — ModelRetry is the framework-blessed path. Same defensive pattern should be applied wherever a chat tool can raise a non-ModelRetry exception (the 8 run_* tools can also throw from pipeline.execute — consider a shared guard in _run_pipeline_tool returning an error dict).
- **合并自**：arch-coupling#4, gap-r1-3#4（2 条同源发现）
- **置信度**：high　|　**状态**：待修

#### [BUG-053] coverage.ts 的 req() 丢弃后端中文 detail 错误体，分组/成员操作失败时用户拿不到具体原因

- **类别**：Bug
- **严重度**：P2
- **位置**：ui/src/api/coverage.ts:135-140 (req 帮助函数) 对比 ui/src/api/errors.ts:15-28 (extractErrorDetail)
- **现象/问题**：req() 在 !r.ok 时只 throw new FetchHttpError(r.status, r.statusText)，完全不读 response body。但后端 FastAPI 错误统一返回 {detail: 中文用户文案}（errors.ts 注释明确：422=ticker 非法、502=provider 失败、503=能力未配置都带可读 detail）。statusText 在 HTTP/1.1 下常是 'Bad Request' 这类英文短语甚至空串，信息量为零。
- **证据**：useAddMembers/useCreateGroup 等 mutation 的 onError 在 CoveragePage 里统一弹 t('coverage.error.addFailed') / createFailed 这类泛化文案（CoveragePage.tsx:199、203），所以后端如果返回『ticker XYZ 不存在/已在组内/分组名重复』这类具体 detail，用户永远看不到——只看到『添加失败』。与项目『错误要可溯源、给分析师投行级体验』的红线相悖。对比同仓 startRun（runStreamStore.ts:324-327）和 startDebate（debateStore.ts:243-245）都正确读了 body.detail，唯独 coverage.ts 的 req() 没读，属路径分裂。
- **根因**：coverage.ts:137 的 req() 是为新端点手搓的极简封装，漏了和 errors.ts/startRun 对齐的 detail 提取。第一个出错位置就是这一行 throw。
- **修复方案**：改 ui/src/api/coverage.ts:135-140 的 req()：!r.ok 时先 const detail = await extractErrorDetail(r, '') （复用 ui/src/api/errors.ts），detail 非空则 throw new FetchHttpError(r.status, r.statusText) 的同时把 detail 作为 message（可给 FetchHttpError 加可选第三参 detail 并让 mapErrorToUserMessage 优先返回它），或直接 throw new Error(detail) 当 detail 存在。配套：CoveragePage 的 onError 改成优先显示 mapErrorToUserMessage(err) 而非写死 coverage.error.*。注意事项：extractErrorDetail 会 consume body，调用一次即可；req 的 204 分支保持。改动量级：小（约 10-20 行）。
- **验证补充**：Fix is right; two refinements: (1) extractErrorDetail consumes the body once — call it exactly once in req() and pass detail into FetchHttpError (add optional 3rd param) so mapErrorToUserMessage can prefer it; throwing a plain Error(detail) also works but loses err.status for any status-based branching. (2) Must also update ALL four CoveragePage onError sites (addFailed/createFailed/runFailed/removeFailed) to mapErrorToUserMessage(err), else the read detail still gets overwritten by the hardcoded toast.
- **影响面/回归风险**：影响所有 Coverage CRUD/批量操作的错误可读性。回归风险低，仅丰富错误信息，不改成功路径。
- **置信度**：high　|　**状态**：待修

#### [BUG-054] 研报版本切换 <select> 用 opacity:0 覆盖层实现：键盘 Tab 落上去零可见焦点指示，用户看不到焦点在哪

- **类别**：Bug
- **严重度**：P2
- **位置**：ui/src/pages/artifact-detail/shell/ReportToolbar.tsx:157-181（hidden select）+ hiddenSelectStyle 377-385
- **现象/问题**：报告顶栏的版本切换是一个真实的原生 <select>，但用 hiddenSelectStyle（position:absolute; inset:0; opacity:0）盖在可见的版本标签+chevron 上。原生 select 键盘可聚焦可操作（这点没问题），但因为它 opacity:0、可见的 reportVersionLabel/ChevronDown 又不响应 :focus，键盘用户 Tab 到这个控件时屏幕上没有任何焦点指示——焦点『消失』在标签上，用户不知道现在按 ↑↓/Space 会打开版本下拉。
- **证据**：复现：在多版本研报页（sameTypeTimeline.length>1）只用键盘 Tab。焦点会停在这个透明 select 上但视觉无变化（标签 158 行只是 <span>，不随 select:focus 改样式）。对比同栏的 back 按钮(124)、面包屑按钮(145/149)、ToolbarButton(294) 都是原生 button 有 UA 默认焦点环——唯独这个最容易被忽略的版本切换控件，焦点不可见。
- **根因**：hiddenSelectStyle(377-385) 把 select 设成 opacity:0 纯透明热区，焦点态没有任何投影到可见 DOM；可见标签是独立 <span> 不知道 select 的 focus 状态。第一个出错位置是 162-168 的 select 结构：交互元素透明而装饰元素可见，二者焦点未绑定。
- **修复方案**：改 ReportToolbar.tsx：给包裹的 <span>（157）加 :focus-within 样式（用 CSS 类而非 inline，因 inline 无法表达 :focus-within），让 select 获焦时可见标签描边/变色（border 或 outline 用 var(--accent-cyan)，禁硬编码）；或更稳妥——把透明 select 换成可见的轻样式 select / 一个 role=combobox 的真按钮+菜单。最小修复：在 App.css 加 .version-switch:focus-within{outline:2px solid var(--accent-cyan);border-radius:...} 并给 157 的 span 挂该 class。注意保留 aria-label（167）。
- **验证补充**：Fix valid. :focus-within must be a CSS class (inline can't express it) on the span(157) — author already notes this. Use var(--accent-cyan), keep aria-label(167). P2 is on the high side for a still-operable control but acceptable.
- **影响面/回归风险**：仅影响键盘用户对版本切换的可发现性，范围小；回归风险极低（纯增焦点样式）。
- **置信度**：high　|　**状态**：待修

#### [BUG-055] 归档（30天自动 stale）的研报混进所有版本列表且零视觉标识——用户分不清『还在跟踪』和『已作废』的版本

- **类别**：Bug
- **严重度**：P2
- **位置**：ReportRightRail.tsx L92-131 / AIZone.tsx L1004-1045 / CoverageInspector.tsx HistoryPanel L349-407 / VersionDiffBanner.tsx L275-281（base 下拉）  ·  （另涉：ReportToolbar.tsx L173-176 / ReportRightRail.tsx L118,L127 / AIZone.tsx L1038 / CoverageInspector.tsx L370 / VersionDiffBanner.tsx L277）
- **现象/问题**：后端 30 天 stale-archive 后台任务会把旧 artifact 标 archived=true（ArtifactDetailPage.tsx:103 注释明确）。timeline 端点 include_archived=True 把归档项也返回。但前端所有渲染版本的地方都没读 `archived` 字段——归档版和活跃版长得一模一样。用户在版本切换下拉、右栏时间线、History tab、Diff 基准选择器里，根本无法区分哪些版本是系统判定『已过期作废』的、哪些是当前在跟踪的。
- **证据**：ArtifactSummaryV5 类型 types/v5.ts:30 有 `archived: boolean`；后端 finrobot/routes/artifacts.py:96-125 timeline 端点 `include_archived=True` 注释『shows the full history including archived entries』。但全仓 grep `.archived` 在 pages/components/views 渲染层零命中（只有 type 定义和 schema.d.ts）。ReportRightRail L114-128、AIZone L1030-1041、Inspector L361-385、VersionDiffBanner L276-280 渲染每个版本时都只用 created_at/verdict/target_price/signal，从不读 archived。
- **根因**：timeline 契约把 archived 暴露上来了，前端消费时漏接这个字段。第一个出错位置：useV5Artifacts.ts 的 timeline 消费方全部忽略 a.archived。
- **修复方案**：在四个渲染版本行的组件里读 `a.archived`：归档行加一个灰色『已归档』pill（var(--text-dim) 描边，复用 SignalBadge 的样式骨架）或整行 opacity 0.6 + tooltip。VersionDiffBanner 的 base `<option>` 文案后缀 `· 已归档`（L276-280）。注意 markArtifactViewed 会 un-archive（artifacts.py:292），所以打开后该标识应消失——invalidate timeline query 已在 ArtifactDetailPage L117 做了，状态会自洽。量级：低（加一个字段读取 + 一个 pill，~4 处）。
- **验证补充**：Fix is correct and low-risk. Note markArtifactViewed un-archives on open (artifacts.py:290-303) and ArtifactDetailPage L117 already invalidates the timeline query, so the pill self-clears — finding acknowledges this correctly.
- **影响面/回归风险**：纯展示增强，无逻辑回归。让『最新 vs 历史/作废』对用户透明，直接回应审查聚焦点。
- **合并自**：ux-onetomany#2, ux-onetomany#5（2 条同源发现）
- **置信度**：high　|　**状态**：待修

#### [BUG-056] 研报版本切换器/时间线/Diff 候选只取 timeline 默认 50 条，与 Inspector History(200) 不一致——重度跟踪的 ticker 老版本在报告页内不可达

- **类别**：Bug
- **严重度**：P2
- **位置**：ArtifactDetailPage.tsx L63 `useV5ArtifactTimeline(symbol)`（无 limit）
- **现象/问题**：ArtifactDetailPage 拉 timeline 时不传 limit，吃后端默认 50。这一份 timeline 同时喂给 toolbar 版本下拉、右栏时间线、和 VersionDiffBanner 的候选集。一支被反复跑（research+DCF+LBO+comps 多类型混计）的 ticker 一旦总 artifact 超 50，第 51 条往后的老版本在报告页内的版本切换器和 Diff 基准里全部消失；而同一支股票在 Coverage Inspector History 里（显式 limit 200）却能看到它们——同一份历史，两个入口给出不同的『全部』，用户会困惑。
- **证据**：ArtifactDetailPage.tsx:63 `useV5ArtifactTimeline(symbol)` 未传 limit → useV5Artifacts.ts:33 `qs=''` → 后端 artifacts.py:100 `limit: int = 50`。对比 CoverageInspector.tsx:320 `HISTORY_LIMIT = 200` 注释明说『match the coverage service's own 200 ceiling so a heavily-run ticker isn't truncated』——证明项目已知道 50 会截断，却只在 Inspector 修了，报告页漏了。
- **根因**：timeline limit 的修复（200）只打在 Inspector 一处，ArtifactDetailPage 的同名 hook 调用没同步。第一个出错位置：ArtifactDetailPage.tsx:63 缺 limit 参数。
- **修复方案**：ArtifactDetailPage.tsx:63 改为 `useV5ArtifactTimeline(symbol, 200)`，与 Inspector 对齐。注意 useV5Artifacts.ts:28 注释已说明 limit 进 queryKey，不会和无 limit 的其它调用方串缓存——但 AIZone.tsx:89 也用无 limit 调同 ticker，会各自缓存一份（200 那份多拉数据）。可接受；若想省一次请求，把 AIZone 也统一成 200。量级：低（1 行，含考虑统一 AIZone）。
- **验证补充**：One-line fix useV5ArtifactTimeline(symbol, 200) is correct. limit is in the query key (useV5Artifacts L28) so no cache crosstalk. AIZone L89 also calls with no limit (50) for the same ticker — for true consistency unify AIZone to 200 too, else AIZone's slice(0,5) preview and the report page derive from a different cached page (harmless given the slice but inconsistent). Finding flags this correctly.
- **影响面/回归风险**：边缘场景（单 ticker >50 artifacts）；多数 ticker 无感。回归面极小。修后报告页与 Inspector 的『全部历史』口径一致。
- **置信度**：high　|　**状态**：待修

#### [BUG-057] Compare 表把不同时间跑出的 DCF 混在同一张表,且不显任何 vintage/as_of——用户无法判断哪行是今天的、哪行是三周前的

- **类别**：Bug
- **严重度**：P2
- **位置**：finrobot/coverage/service.py:544 _compare_one(取 latest DCF)+ finrobot/engine/compute/compare.py:19-33 CompanyValuation(无 created_at/as_of 字段)+ ui/src/pages/ComparePage.tsx(表格无日期列)
- **现象/问题**：Compare 对每个 ticker 取其『最新一条 DCF-bearing artifact』(_latest_dcf_result:581 newest-first)。但各 ticker 最新 DCF 的时间天差地别——A 的 DCF 是今天跑的、B 的是三周前研报内嵌的。表里把它们的 implied_price/WACC/upside 并排呈现,却没有任何一列告诉用户每行 DCF 的生成时间。current_price 是实时的,但 implied_price 用的是历史假设,混在一起的 upside 误导性强。这违反项目『每个数字可追溯 provider/fetched_at』的底线。
- **证据**：compute/compare.py:19-33 CompanyValuation 字段只有 ticker/price/implied/wacc/... 无 created_at/as_of/artifact_id;ComparisonResult.generated_at(compare.py:40)是『这次 assemble 的时间』不是各 DCF 的时间;ComparePage.tsx 表头(line 79-88)是 ticker/price/implied/upside/WACC/EV-EBITDA/PE,无日期/新鲜度列。service.py:581 list_by_ticker include_archived=True 还会捞到已归档的旧 DCF。
- **根因**：build_comparison/CompanyValuation 在设计时只关心数值不关心 provenance,与 coverage 卡片(CoverageRow 带 latest_at/price_as_of/sources)那套可溯源标准不一致——Compare 这条链漏接了 as_of。
- **修复方案**：在 compute/compare.py CompanyValuation 加 dcf_as_of: str | None(取 artifact.created_at)与 dcf_artifact_id: str | None;_compare_one(service.py:544)从 summary 拿 created_at/id 传入 build_company_valuation;ComparePage 表加一列『DCF 日期』并对超过 N 天的行加 amber『已过期』标记(可复用 coverage 的 _needs_refresh 阈值)。注意:_latest_dcf_result 当前为拿 DCFResult 丢弃了 summary 元数据(line 582 只用 summary.type/id 取 artifact),改成把 summary.created_at 一并返回(返回 tuple 或带 id 的小 dataclass)。改动量级:小-中(模型 +2 字段、service 取数、ComparePage 加列,约 50 行)。
- **验证补充**：Severity correctly P2: this is a provenance/traceability defect that makes the comparison misleading, but the arithmetic of each individual row is correct — it's not a wrong-number bug, so not P1. Fix plan is sound; the load-bearing detail the finding correctly identifies: _latest_dcf_result currently returns only DCFResult and must be changed to also return summary.created_at + summary.id (tuple or small dataclass) so build_company_valuation can stamp vintage. Also worth dropping include_archived=True or at least flagging archived DCFs, since comparing against an archived valuation compounds the staleness problem.
- **影响面/回归风险**：CompanyValuation schema 变更会反映到 /api/compare 响应与 openapi schema.d.ts(需 regenerate)。回归风险低:纯增字段、老消费者忽略即可;但前端 useCompare 类型要同步。
- **置信度**：high　|　**状态**：待修

#### [BUG-058] Non-critical steps emit a misleading step.completed (green ✓) after exhausting all retries on a real failure

- **类别**：Bug
- **严重度**：P3
- **位置**：finrobot/engine/pipelines/base.py:378-397
- **现象/问题**：When a non-critical step fails after all retries, the code appends to failed_validations but then still calls `progress.on_step_end(...)` (line 394), which emits a step.completed SSE event. The frontend renders a green checkmark on a step that actually failed; the failure only surfaces in the report's failed_validations footer, not the live progress UI. The code comments at 382-385 explicitly acknowledge this ('a green ✓ on this step because on_step_end fires regardless') and route critical steps around it by raising before on_step_end — but non-critical steps still emit the false-positive.
- **证据**：base.py: after _run_step returns a non-None validation_error, `failed_validations.append(...)`; for critical steps it raises (no on_step_end); for non-critical it falls through to line 394 `await progress.on_step_end(i, total, step.name, elapsed)` which constructs StepCompleted in routes/runs.py RunProgress.on_step_end. There is no step.failed event in events.py for the non-aborting case, so the live UI has no way to show the degrade.
- **根因**：on_step_end is overloaded as 'step finished' but is fired unconditionally regardless of whether the step passed or degraded; there is no per-step degraded/failed signal in the event vocabulary.
- **修复方案**：Either (a) add a `step.degraded` event to finrobot/events.py and have base.py emit it (instead of on_step_end) when validation_error is set on a non-critical step, then render it as a warning state in the UI; or (b) extend StepCompleted with an optional `degraded: bool` / `error: str` field and set it when the step finished with a failed validation. Minimal-blast option (b): in base.py pass the validation_error into on_step_end and include it in the StepCompleted TypedDict; frontend treats non-empty error as amber not green. Touches base.py + events.py + runs.py RunProgress + the UI step renderer (small, ~30 lines).
- **验证补充**：Both options viable; option (b) (extend StepCompleted with optional degraded:bool/error:str and have the UI render amber) is lower-blast and keeps event count stable. Touches base.py (pass validation_error into on_step_end), events.py (StepCompleted TypedDict), runs.py RunProgress.on_step_end, runStreamStore.ts step renderer. Genuinely P3 — honesty/UX gap, not a correctness or data bug; failure is already truthfully recorded in failed_validations.
- **影响面/回归风险**：UX honesty only — no data corruption. Affects any run where a non-critical step (catalyst/peer/ownership/technical/thesis-as-non-critical) degrades. Low risk; additive event field.
- **置信度**：high　|　**状态**：待修

#### [BUG-059] Validation-failure retries re-run deterministic executors unchanged, burning the full retry budget on identical failing output

- **类别**：Bug
- **严重度**：P3
- **位置**：finrobot/engine/pipelines/base.py:544-577 (retry loop) interacting with deterministic executors (equity_research _execute_financial_modeling / _execute_technical_analysis / _execute_catalyst_analysis / execute_peer_analysis)
- **现象/问题**：On a validation failure the retry loop rebuilds a 'Previous output failed validation… fix and try again' prompt and re-invokes step.executor. For deterministic executors the agent/prompt arguments are ignored — they recompute purely from structured_context + data_layer. So a validation failure caused by deterministic inputs (e.g. peer sanity-range violation, DCF implied_price≤0) re-produces byte-identical failing output on every retry, wasting all 3 retries (and, for peer_analysis, re-fetching every peer's financials + XBRL + FX each attempt — heavy provider load) before degrading. The retry mechanism only helps the few steps whose executor actually consumes the re-prompt (the inner agent.run in data_collection, thesis, report).
- **证据**：base.py:552-554 builds retry_prompt only as text; deterministic executors like _execute_financial_modeling/_execute_technical_analysis mark `prompt` as noqa ARG001 (unused). execute_peer_analysis re-runs the full _fetch_one_peer gather every attempt. The validation predicates (validate_dcf_result, validate_peer_comps) are pure functions of the recomputed structured output, so identical inputs → identical failure → 3 wasted retries + N redundant provider fetches.
- **根因**：The retry loop assumes a re-prompt can change the outcome (true for LLM steps) but applies uniformly to deterministic steps where the executor is a pure function of state that the re-prompt cannot influence.
- **修复方案**：In base.py give StepExecutor (or PipelineStep) a `deterministic: bool` marker (or detect that the executor ignores prompt). When set, on a VALIDATION failure (exc_err is None) skip the retry loop entirely and go straight to degrade — there is no point re-running. Keep retries for the recoverable-EXCEPTION path (transient provider/FX errors genuinely may succeed on retry). Concretely: in _run_step, if step.deterministic and validation is not None and not validation.passed, return validation.error immediately without looping. Mark _execute_financial_modeling/_execute_technical_analysis/_execute_catalyst_analysis/execute_peer_analysis (and dcf/lbo/ddm deterministic steps) as deterministic=True in their PipelineStep definitions. Note: do NOT short-circuit the exception path — peer FX 429s are recoverable and benefit from back-off.
- **验证补充**：Mark deterministic=True ONLY on financial_modeling/technical_analysis/catalyst_analysis/ownership_governance_analysis (and standalone dcf/lbo/ddm calc steps) and short-circuit their VALIDATION-failure retries (when exc_err is None). Do NOT mark peer_analysis deterministic — its executor consumes the re-prompt and re-selects peers, which is the documented intended retry. Keep the exception-retry path for ALL steps (peer FX 429s recover with backoff). Net effect: P3 efficiency/provider-load fix, not a correctness bug — output is identical so no wrong number ships, only wasted latency/retries.
- **影响面/回归风险**：Performance/cost only (no wrong numbers): cuts ~3× redundant LLM-free recompute and, for peer_analysis, ~3× redundant multi-peer provider fetches on a failing run. Affects any run that hits a deterministic validation failure. Low regression risk if scoped to the validation path; verify the exception-retry path is untouched.
- **置信度**：medium　|　**状态**：待修

#### [BUG-060] DCF/Monte Carlo 把 Gordon 终值在中年法下按 (n-0.5) 折现——终值『定价日』应是年末 n,这里多折了半年,系统性高估 fair value

- **类别**：Bug
- **严重度**：P3
- **位置**：finrobot/engine/compute/dcf.py:62 + 115 + 193 + 381 (pv_terminal = tv/(1+wacc)**(n-offset));finrobot/engine/compute/monte_carlo.py:194 同
- **现象/问题**：mid_year=True 时,显式期 FCF 按 (t-0.5) 折现是对的(现金流年中到账)。但 Gordon 终值 tv = FCF_n*(1+tg)/(wacc-tg) 是一笔『站在第 n 年年末』评估的永续值(它资本化的是 n+1 年起、按年末口径的现金流),其定价日是年末 n,应按 n 折现,而非 n-offset=n-0.5。代码对终值也用了 n-0.5,等于把终值多向前折半年、放大 (1+wacc)^0.5 ≈ 票面 WACC 16% 时约 +7.7% 的终值现值。终值通常占 DCF 价值 60-80%,故 implied_price 在开 mid_year 时被系统性高估约 4-6%。
- **证据**：dcf.py:61-62 `terminal_value = projected_fcf[-1]*(1+tg)/(wacc-tg); pv_terminal = terminal_value/(1+wacc)**(n-offset)`,offset=0.5。R&P/Damodaran 主流口径:Gordon perpetuity TV 与第 n 年年末现金流同期,折现指数用 n(年末),mid-year 半年调整只施于显式期 FCF;部分实务对 TV 也用 n-0.5 但仅当 TV 由『退出倍数 × 年中 EBITDA』构造,而这里 TV 是 Gordon 永续,定价日是年末。代码 docstring(dcf.py:24-26)只引 R&P Ch.8 说 mid-year 抬 3-6%,未区分 TV 的折现期。
- **根因**：把显式期的半年提前折现规则机械套用到终值的折现指数上,未区分『年中到账的显式 FCF』与『年末定价的 Gordon 永续值』两种不同 timing 对象。
- **修复方案**：[金融待核] 先与外部基准对齐再改:对照 Rosenbaum & Pearl 3e Ch.8 mid-year convention 对 Gordon TV 的折现期定义(以及 Macabacus / Damodaran spreadsheet 的实现)。若确认 Gordon TV 应按 n 折现,则把 dcf.py 4 处与 monte_carlo.py:194 的 `**(n - offset)` 改为 `**n`(只有显式 FCF 用 (i+1-offset)),并更新 docstring 说明 TV 不享受 mid-year 半年提前。注意 calculate_dcf、calculate_sensitivity、_price_for、solve_for_implied_wacc 内联折现、monte_carlo 需同步改,否则反推/敏感性与 headline 口径分裂。改动量级:小但需 5 处对称改 + 金融测试期望值重算。外部核对:挑一只票手算 mid_year=True 的 DCF,TV 分别用 ^n 与 ^(n-0.5) 折现,对比哪个与 Bloomberg/标准 DCF 模板一致。
- **验证补充**：Do NOT change code on this finding's current evidence — it would risk introducing a deviation from the prevailing Macabacus/WSP/R&P mid-year-on-Gordon-TV convention that the code likely already follows. Correct next step is the finding's own [金融待核] path: pull the authoritative R&P 3e Ch.8 and Macabacus implementations, confirm whether Gordon TV under mid-year is discounted at n-0.5 (most templates) or n (exit-multiple TV only), and only then decide. If a change is ever made it must hit all 5 sites symmetrically (4 in dcf.py + monte_carlo.py) and re-baseline the finance test expected values, as the finding notes. The finding's quoted '+7.7%/+4-6%' overstatement is conditional on its premise being right, which is not established.
- **影响面/回归风险**：仅在 mid_year=True 路径影响 implied_price(高估约 4-6%);默认 mid_year=False 不受影响——需确认管线默认是否开 mid_year。当前全代码内部一致,故无『反推≠正算』的自相矛盾,只是相对外部标准可能偏高。回归风险:改后所有开 mid_year 的 DCF 数字下移,金融测试期望值需重算。属口径核对项,不宜未对基准就硬改。
- **置信度**：medium　|　**状态**：待修

#### [BUG-061] Earnings-call tab selection keyed by array index — duplicate/reordered transcripts collide keys and mis-select

- **类别**：Bug
- **严重度**：P3
- **位置**：ui/src/pages/artifact-detail/chapters/ChapterFinancialData.tsx:407,456,468,472-474
- **现象/问题**：EarningsCallSection tracks the active transcript by array index (selectedIdx) but renders the tab buttons with React key `${tx.year}-Q${tx.quarter}`. If two transcripts share the same year+quarter (amended/duplicate filings — possible from the provider) the keys collide (React dev warning + unstable reconciliation). Separately, because selection is index-based, a background refetch that returns a reordered/shorter list makes selectedIdx point at the wrong (or absent) transcript; line 456 falls back to transcripts[0] only when out of range, silently jumping the user's selection.
- **证据**：Line 407 `useState(0)`; line 474 `onClick={() => setSelectedIdx(i)}` (index); line 472 `key={`${tx.year}-Q${tx.quarter}`}` (content key) — the selection space and the key space disagree. Line 456 `transcripts[selectedIdx] ?? transcripts[0]`. Query (line 409-432) has staleTime 1h and refetchOnMount false so reorder is unlikely but not impossible across cache windows.
- **根因**：Mixed identity model: stable content key for rendering but positional index for state. The two diverge whenever the list has duplicate (year,quarter) pairs or is reordered.
- **修复方案**：ChapterFinancialData.tsx — store the selected transcript's identity instead of its index: `const [selectedKey, setSelectedKey] = useState<string|null>(null)` keyed by `${tx.year}-Q${tx.quarter}-${idx}` (idx in the key disambiguates true duplicates), derive `const selected = transcripts.find(...) ?? transcripts[0]`, and set on click from the same composite key. Use that composite key for the button `key` too so it is unique even on duplicate quarters. ~10 lines.
- **验证补充**：Fix direction is sound (identity-based selection). Store a composite key including idx to disambiguate true duplicates, derive `selected = transcripts.find(...) ?? transcripts[0]`, and use the same composite key for the button `key`. Cleaner still: dedup/normalize (year,quarter) at the backend route (data.py:242) so the provider's amended filings don't reach the client duplicated — that removes the root cause rather than only the symptom, but the frontend identity fix is the minimal correct change for this file's scope.
- **影响面/回归风险**：Rare (needs duplicate or reordered transcripts); worst case is a React key warning + the user's tab selection jumping. No data fabrication. Low blast radius.
- **置信度**：medium　|　**状态**：待修

#### [BUG-062] `is_sampled` / `sample_size` honesty disclosure is dropped at the API→frontend boundary (field absent from the TS contract)

- **类别**：Bug
- **严重度**：P3
- **位置**：ui/src/hooks/useDashboardHitRate.ts:21-26 (HitRateOverview interface) vs finrobot/routes/dashboard.py:76-80
- **现象/问题**：The backend deliberately exposes `is_sampled` + `sample_size` so the UI can say 'computed over the latest 500, not your full record' instead of pretending the rate is the full track record (per the docstring at dashboard.py:62-80). The frontend `HitRateOverview` interface omits both fields entirely, so the disclosure can never render — the analyst sees a bare hit_rate % with no indication it may be a truncated sample. The whole honesty mechanism dead-ends at the type boundary.
- **证据**：useDashboardHitRate.ts:21-26 defines `HitRateOverview` with only window/overall/by_verdict/generated_at — no `is_sampled`, no `sample_size`. `grep is_sampled ui/src` → zero hits. The generated schema (schema.d.ts:1920) DOES include the fields, but the hand-written hook interface (the one actually consumed) drops them, and no component reads them.
- **根因**：Hand-maintained TS interface in the hook diverged from the backend Pydantic model / generated schema; the sampling fields were added to the backend response but never threaded into the consumed interface or any banner component.
- **修复方案**：Add `is_sampled: boolean` and `sample_size: number` to `HitRateOverview` in useDashboardHitRate.ts and render a '基于最近 N 条样本' caption when `is_sampled` is true wherever the banner is shown. Better: drop the hand-written interface and consume the generated `components['schemas']['HitRateOverview']` so it can't drift again. Note: currently latent because the hook has no live caller (see related Product finding) — but must be fixed before re-wiring or the analyst sees an undisclosed sampled stat. Change size: ~5 lines + caption.
- **验证补充**：Important: proposed fix (b) 'consume the generated components[schemas][HitRateOverview]' will NOT surface the fields until the OpenAPI schema is regenerated (current schema.d.ts is stale and lacks them). Correct order: regenerate schema FIRST, then either hand-add the two fields or switch to the generated type. This is only worth doing as part of re-homing the panel ([3]); fixing it in isolation has no user-visible effect.
- **影响面/回归风险**：Restores the honest-sampling UX the backend already pays for. No backend change. Regression risk: none (additive fields).
- **置信度**：high　|　**状态**：待修

#### [BUG-063] _resolve_strategy does importlib.import_module(user_string) + getattr before the bt.Strategy check — arbitrary module import with side effects

- **类别**：Bug
- **严重度**：P3
- **位置**：finrobot/engine/backtest/backtrader_adapter.py:229-235
- **现象/问题**：For any strategy name containing ':', the adapter splits on the last ':' and calls importlib.import_module(module_path) then getattr(module, class_name) on fully user-controlled strings, only checking issubclass(cls, bt.Strategy) AFTER the import has already run. Importing an arbitrary module executes that module's top-level code (side effects) regardless of whether it turns out to be a Strategy. Reachable from `finrobot backtest TICK --strategy 'os:getcwd'` and SDK BacktestConfig(strategy='any.module:Attr'). Severity is bounded because the only entry points are the local CLI and the in-process SDK (no HTTP route, no LLM tool exposes raw strategy strings — strategy_agent only ever produces 'sma_crossover'), so this is a trusted-local-input surface, not a remote RCE. Still: an undocumented 'import any module and trigger its side effects' primitive with no allow-list.
- **证据**：Lines 230-233: `module = importlib.import_module(module_path); cls = getattr(module, class_name); if not issubclass(cls, bt.Strategy): raise`. The issubclass guard is post-import. test_backtrader_adapter.py:69 only tests the ModuleNotFoundError path ('nonexistent_module:MyStrategy'), confirming no allow-list guard exists. No route/agent passes attacker-controlled strategy (grep of routes/orchestrator/agents for backtest = empty).
- **根因**：backtrader_adapter.py:231 imports before validating. There is no registry/allow-list of permitted strategy modules; the contract is 'any importable module:attr'.
- **修复方案**：Introduce an explicit strategy registry: a dict mapping safe names → Strategy classes (start with {'sma_crossover': _get_sma_crossover()}), and resolve only from it. If dynamic loading must stay for power users, gate it behind an explicit opt-in (e.g. an allowed-module prefix in config, default empty) and validate the prefix BEFORE import_module. At minimum, wrap getattr/issubclass so a non-existent attribute raises a clean ValueError (currently getattr raises AttributeError, not the friendly 'Unknown strategy' error). Document in the CLI --strategy help that module:ClassName executes arbitrary import. Keep the issubclass check but move the safety decision before import.
- **验证补充**：Registry/allow-list fix is sound and aligns with house 'no band-aid' rule. Note: strategy_agent forces ticker/dates/cash immutable (lines 98-105,152-159) but NOT strategy, so an LLM could in principle emit a 'module:Class' string — a registry would also harden that path. The 'friendly ValueError on missing attr' point is valid: getattr currently raises AttributeError, not the 'Unknown strategy' message; wrap it. Do NOT over-claim this as a security-critical fix in commit messaging — it's hardening of a local-trust boundary.
- **影响面/回归风险**：Local-only surface; no remote exposure today. Low functional regression (sma_crossover path unchanged). If a registry replaces free-form import, any external caller relying on arbitrary module:Class loading breaks — acceptable given it is undocumented and untested beyond the not-found case. Flag as mild behavior change for SDK power users.
- **置信度**：high　|　**状态**：待修

#### [BUG-064] _extract_drawdown accepts a warnings list but never uses it — silent None drawdown with no warning, inconsistent with siblings

- **类别**：Bug
- **严重度**：P3
- **位置**：finrobot/engine/backtest/backtrader_adapter.py:248-253
- **现象/问题**：_extract_drawdown(self, strat, warnings) takes the warnings accumulator like its siblings _extract_sharpe/_extract_trades, but never appends to it. When the DrawDown analyzer returns no 'max'/'drawdown' (e.g. zero-trade backtest), max_dd is None and the result silently carries max_drawdown=None with no user-facing warning, unlike Sharpe which warns 'Insufficient data...'. Inconsistent behavior: one missing metric warns, another goes silent.
- **证据**：Lines 248-253: the function reads analysis.get('max',{}).get('drawdown'); if None it returns None without warnings.append(...). Compare _extract_sharpe (line 245) which appends 'Insufficient data for Sharpe ratio calculation'. The warnings param is dead here.
- **根因**：backtrader_adapter.py:248 signature carries warnings for symmetry but the None branch (line 253 `return None`) omits the warning append.
- **修复方案**：In the None branch add `warnings.append('Insufficient data for max drawdown calculation')` before returning None, mirroring _extract_sharpe. Trivial one-line change; no signature change. Optionally add a test asserting the warning is emitted when the analyzer yields no max.
- **验证补充**：One-line fix as proposed is correct. Minor wording: a None drawdown on a zero-trade backtest is really 'no trades executed' more than 'insufficient data'; consider 'No trades executed; max drawdown unavailable' for accuracy, but mirroring the Sharpe phrasing for consistency is acceptable.
- **影响面/回归风险**：Cosmetic/consistency; no numeric change. Zero regression risk. Makes degraded backtests honest about which metrics were unavailable.
- **置信度**：high　|　**状态**：待修

#### [BUG-065] 镜像列(verdict/entry/target/tagline)在 extractor 逻辑演进后无回填路径，旧行永久陈旧

- **类别**：Bug
- **严重度**：P3
- **位置**：finrobot/artifact/sqlite_store.py:166-188 (_artifact_to_row 写列) + 350-356 (rebuild_summaries 永久 no-op) + 342-348 (mark_viewed)
- **现象/问题**：verdict/entry_price/target_price/target_date/tagline 这些镜像列只在 save() 时由 summary_extractor 从 payload 现抽现写。dashboard 命中率/recent-strip 直接读这些列、绝不回 payload（dashboard.py:294/317-319/399-404，文档化的 N+1 消除）。但 extractor 的抽取规则会演进（summary_extractor 已记录多种 thesis 形状兼容历史）。一旦规则变更或修 bug，库里已存的行除非被重新 save()，否则列值永久停留在旧逻辑产出——而唯一会触发 re-save 的是 mark_viewed/archive_stale，两者都不是主动全量回填。
- **证据**：rebuild_summaries() 是 tested no-op（sqlite_store.py:351 docstring『summary columns are populated at save time』；test_sqlite_store.py:198 test_rebuild_summaries_is_noop），无任何真实 backfill。已知基线第三类列出『旧 artifact 的 llm_narrative 永远空 dict（lazy migration 未做）』正是同一类陈旧——但那是 payload 内字段，这里是被直接当 source-of-truth 读的索引列，影响命中率统计/信号灯，错得更隐蔽（数字看着对、其实是旧规则算的）。例：若未来 extract_verdict 新增识别一种 recommendation 写法，所有历史行的 verdict 列仍为 None → 命中率分母/分子错。
- **根因**：第一出错位置 = rebuild_summaries 被设计成 no-op 且无替代 backfill。镜像列模式（双写）缺了它本该配套的『schema/extractor 版本变更后重投影』能力；当前隐式假设 extractor 永不变，与建设期高频迭代现实冲突。
- **修复方案**：把 rebuild_summaries 实现成真回填：遍历所有行 `SELECT id,payload`，对每行 `Artifact.model_validate_json`→`_artifact_to_row`→ 只 UPDATE 那批镜像列（不动 payload，避免无谓重写）。批量分页（如每 500 行一 commit）防大库锁表。再在 server.py startup（已有 reconcile_orphaned_runs/archive 背景任务那处）按一个 `SUMMARY_PROJECTION_VERSION` 常量 gate：版本 bump 时跑一次 rebuild。注意:(1) 与 mark_viewed 的 archived 同步逻辑一致——只更新列、payload.meta.archived 不在镜像列里所以无冲突；(2) extractor 抛错的行 skip 并 log，不中断整批。改动量级:中（一个方法 + 一处 startup gate + 一个版本常量）。
- **验证补充**：Fix (real backfill in rebuild_summaries + SUMMARY_PROJECTION_VERSION gate at startup) is sound. Implement as UPDATE of mirror columns only (not payload) to avoid the same O(N·payload) cost flagged in finding 4. Batch-commit per N rows; skip+log rows that fail model_validate_json.
- **影响面/回归风险**：影响 dashboard 命中率/recent-strip/coverage research_count 等所有读镜像列的聚合。回归风险低（纯增量回填，payload 不动）；需注意大库首启动一次性回填的耗时，故分页 + 仅版本变更时触发。
- **置信度**：high　|　**状态**：待修

#### [BUG-066] 禁用态按钮的『为什么不可用』只靠 title tooltip：disabled 元素不触发 hover、tooltip 鼠标专属，键盘/触屏用户拿不到原因（IC 辩论 & Compare）

- **类别**：Bug
- **严重度**：P3
- **位置**：ui/src/pages/artifact-detail/shell/ReportToolbar.tsx:240-250（IC 辩论 disabled+title）+ ui/src/components/coverage/CoverageInspector.tsx:190-196（Compare disabled 用 label 而非 title，相对更好）
- **现象/问题**：ReportToolbar 的 IC 辩论按钮在非 equity_research 报告上 disabled，唯一解释（'仅 equity_research 可用'）放在 title 属性里。但 HTML disabled 元素在多数浏览器不触发鼠标事件、title tooltip 本就只对鼠标 hover 生效——键盘用户 Tab 跳过 disabled 按钮（不可聚焦）根本碰不到 tooltip，触屏用户也没有 hover。结果：在 dcf/lbo 等报告上，用户看到一个灰掉的『⚖ IC 辩论』却完全无法得知为何不能点。
- **证据**：复现：打开一个 dcf 类型 artifact 的报告页 → toolbar 的 IC 辩论按钮 disabled。键盘 Tab 不会停在它上（disabled 不可聚焦），触屏点击无反应也无提示，只有鼠标用户悬停才看到 title。对照：同仓库 CoverageInspector.tsx:190-193 处理 Compare 禁用时把原因写进可见 label（compareReady? compare : compareHint），是更可达的做法——说明项目已有正确范式，IC 按钮没遵循。
- **根因**：ReportToolbar.tsx:242-247 用 disabled + title 表达『不可用原因』，依赖鼠标 hover 这一单一通道；ToolbarButton(294-332) 也未在 disabled 时渲染任何可见说明文字。第一个出错位置是 240-250 这段 props。
- **修复方案**：两选一：(a) 非 equity_research 时干脆不渲染 IC 按钮（与 onOpenIcDebate 仅对 equity 传入的现状一致，最简单，去掉 disabled 分支）；(b) 若要保留以示能力存在，则在按钮旁渲染可见的小字说明或改用 aria-disabled+可聚焦+点击弹 toast 说明，而非 disabled+title。推荐 (a)：删 ReportToolbar.tsx:242 的 disabled 表达式分支，改为 {reportType==='equity_research' && onOpenIcDebate && <ToolbarButton.../>}。注意同步删除现已无用的 t('report.toolbar.icDebateOnlyEquity') 文案引用。
- **验证补充**：Fix (a) is correct and cleanest: render {reportType==='equity_research' && onOpenIcDebate && <ToolbarButton.../>} since the handler is already undefined off-equity. Remember to drop the now-unused t('report.toolbar.icDebateOnlyEquity') key (present in en/zh .po+.mjs per grep). P3 appropriate.
- **影响面/回归风险**：影响触屏/键盘用户对该能力的理解，范围限于非 equity 报告页；回归风险低。若选 (a) 需确认产品是否希望在其它报告类型上『展示但禁用』来暗示功能存在——这是产品取舍，倾向 (a) 因当前 tooltip 已是失效解释。
- **置信度**：high　|　**状态**：待修

#### [BUG-067] 退役路由的「已合并」提示 toast 写进 sessionStorage 但全代码无人读取——功能彻底失效且 router 注释撒谎

- **类别**：Bug
- **严重度**：P3
- **位置**：ui/src/router.tsx:57-86（RedirectWithToast）+ ui/src/layout/AppShell.tsx
- **现象/问题**：RedirectWithToast 在跳转前把提示文案写入 sessionStorage[REDIRECT_TOAST_KEY]（line 70），router 文件头注释（line 6-9）明写『AppShell reads + clears the slot on mount』。但 grep 全仓 REDIRECT_TOAST_KEY / 'finrobot.redirect_toast' 只有 router.tsx 这一个写入点，AppShell 及任何组件/hook 都不读、不清。结果：所有退役路由（/stocks /dashboard /library /journal /playground）跳转时承诺给用户的『工作台已合并到「个股」首页』这类 banner 永远不显示，且 sessionStorage 里堆死键。
- **证据**：`grep -rn REDIRECT_TOAST_KEY ui/src` → 仅 router.tsx。`grep getItem/removeItem ... toast|redirect` 在 AppShell/CoveragePage/Toast.tsx 全空。注释声称的消费者不存在 = 文档与代码不一致 + 死代码。
- **根因**：重构把 6 菜单砍到 2 菜单时，RedirectWithToast 的写入侧保留了，但 AppShell 里读取+清除 sessionStorage 的那段从未实现（或被删）。第一个出错位置：AppShell.tsx 缺少一个 useEffect 去 `sessionStorage.getItem(REDIRECT_TOAST_KEY)` → addToast → removeItem。
- **修复方案**：在 AppShell.tsx 加一个挂载时 useEffect：读取 REDIRECT_TOAST_KEY，非空则 useToastStore.addToast({type:'info',title:该文案}) 并 sessionStorage.removeItem。从 router.tsx export 的 REDIRECT_TOAST_KEY 已可直接 import。注意：必须在路由跳转后的目标页 mount 时机读取，AppShell 是所有路由的父壳，挂载早于 Outlet 内容，时序正确。若决定不要这个 banner，则反向删干净：移除 RedirectWithToast 里的 sessionStorage 写入 + line 6-9 注释，别留半截。二选一，不要保留现状。改动量：~10 行单文件（接上）或 ~5 行（删）。
- **验证补充**：Both fix options valid (wire AppShell consumer OR delete the write+comment). Given finding #3's direction also touches these redirects, prefer the DELETE option — the merged-route toasts add little value and the i18n strings (shell.router.*) can be dropped too. Don't leave the half-built mechanism.
- **影响面/回归风险**：影响所有从旧链接/书签进来的用户——他们被静默重定向、毫无解释。接上后回归风险低（新增一个 toast）；删除方向需同步改 router 头注释避免再次误导。
- **置信度**：high　|　**状态**：待修

#### [BUG-068] 回测对 A股标的零适配(T+1/涨跌停/印花税/停牌全缺)却照常产出净值曲线——A股结果根本不可信,应在入口直接 raise 拒跑

- **类别**：Bug
- **严重度**：P2
- **位置**：finrobot/engine/backtest/backtrader_adapter.py:_run_sync(:103-178,全程无 setcommission/无微观结构约束)+ SMACrossOver.next(:77-82,T+0 当日买卖)+ engine.py BacktestConfig(:17-55,无 market/交易规则字段)
- **现象/问题**：backtrader 回测完全按"美股 T+0、零摩擦"撮合,对 A股标的的四条核心约束一条都没建模:(1) `cerebro.broker.setcommission` 全仓从未调用 → 无佣金、无 A股卖方 0.05% 印花税;(2) SMACrossOver.next 金叉当日 `buy()`、死叉当日 `close()` 是 T+0,而 A股 T+1 下当日买入不可卖 → 系统性高估收益;(3) 无涨跌停约束 → 涨停封板时买单本不可成交,回测却按收盘价虚构成交;(4) 无停牌处理。数据走 DataLayer(FMP/finnhub/yfinance,美股向 provider),A股覆盖与复权口径亦存疑。净结果:对 A股 ticker 能跑出一条漂亮但根本不可信的曲线,而手敲 SDK/CLI 的人很容易只看曲线、自动略过 warning。
- **证据**：grep 整个 backtest 模块 `commission/印花/T+1/涨跌停/停牌/akshare/tushare` 仅命中一条自承认的 warning 文案 `"assumes zero commission and zero slippage"`(backtrader_adapter.py:163);`setcommission` 全仓零调用;SMACrossOver.next(backtrader_adapter.py:77-82)的 buy/close 无任何 T+1 持仓锁。回测无 route/agent/pipeline/UI 触达,仅 SDK(abacktest/aauto_backtest)+ CLI 暴露(grep routes/orchestrator/agents/pipelines 为空)。
- **根因**：回测引擎只实现了美股 T+0 零摩擦撮合,从未建模任何 A股市场微观结构;BacktestConfig 也无字段可区分标的所属市场。按"宁可说我需要核对、绝不编一个数字"的信条,第一道闸应在入口拒绝非美股标的,而不是产出一条不可信曲线——能跑出来的图本身就是诱惑。
- **修复方案**：按 boss 裁决——回测定位为"附带功能,不投入扩 A股撮合规则",故走**拒跑(raise)而非 warn**(警告会被忽略,拒跑=物理上不可能被骗):在 BackTraderAdapter.run 起始处(或 BacktestConfig 入口校验)对非美股标的 `raise ValueError("Backtest models US-equity T+0 zero-friction execution only; A-share/HK tickers (T+1, price limits, stamp duty, halts unmodeled) are rejected to avoid producing untrustworthy curves. ticker=…")`。市场判定复用现有 ticker 正则/约定(A股 6 位纯数字代码、`.SS/.SZ/.HK` 后缀);**不要保留"顶格警告"后路**。美股那条零佣金零滑点 warning(:163)保留——那是程度问题不是真假问题。补测试:tests/unit/test_backtrader_adapter 断言 A股 ticker(如 `600519` / `600519.SS`)→ run raise ValueError。
- **影响面/回归风险**：仅影响 CLI 回测 / SDK abacktest/aauto_backtest 的 A股调用;美股路径零影响。拒跑是行为收紧:曾经/将要用本回测跑 A股的脚本会从"拿到假数字"变成"明确报错"——这正是目的,回归风险低。关联:策略库扩充(动量/RSI/均值回归等多策略)经 boss 裁决为"附带功能不投入",**不作为 bug**,如后续要做另立 OPP 备案。
- **置信度**：high　|　**状态**：待修

#### [BUG-069] 回测渲染图时弹出 matplotlib GUI 窗口(Figure 0)并泄漏 figure——模块级 use("Agg") 时机太晚未生效

- **类别**：Bug
- **严重度**：P3
- **位置**：finrobot/engine/backtest/backtrader_adapter.py:38-43(模块级 `matplotlib.use("Agg")` in try)+ :280-296(_render_chart 调 cerebro.plot)
- **现象/问题**：跑回测(CLI/SDK)时 _render_chart 调 `cerebro.plot(style="candlestick")`(:287)会弹出一个交互式 matplotlib 窗口(标题 Figure 0,含 Broker value/cash 曲线、Trades Net Profit/Loss、BuySell 信号、K线+成交量)。本意是后台 savefig 成 base64 PNG、绝不弹窗——模块顶部已写 `matplotlib.use("Agg")`(:41)兜底,但未生效:实测本机默认 backend 仍是 macosx(交互式)。同时 cerebro.plot 内部可能新建多个 figure,_render_chart 只 `plt.close` 取到的 `fig[0][0]`(:290),其余在异常/多图路径下不被回收,长跑泄漏。
- **证据**：`python -c "import matplotlib; print(matplotlib.get_backend())"` → `macosx`(交互式);backtrader_adapter.py:41 的 `use("Agg")` 无 `force=True`,若有别的模块先 import matplotlib.pyplot 把 backend 锁成 macosx,此处静默不切换,等回测 plot 时拿交互 backend 弹窗。
- **根因**：模块级 `matplotlib.use("Agg")` 时机太晚且无 force——backend 在更早的 import 处已被 macosx 占用。第一出错位置是 backtrader_adapter.py:41(use 调用),非 _render_chart。
- **修复方案**：在 _render_chart 渲染前显式 `plt.switch_backend("Agg")`(或模块级改 `matplotlib.use("Agg", force=True)`),确保 cerebro.plot 永远走无 GUI 后端;并把 cerebro.plot 返回的**所有** figure 都 `plt.close`(遍历返回列表而非只 close `[0][0]`)防泄漏。补测试:断言渲染后 `get_backend()` 为 agg 系且无新增打开的 figure(或 mock cerebro.plot 验证 close 调用覆盖全部 fig)。
- **影响面/回归风险**：仅影响跑回测时的渲染副作用(弹窗骚扰 + figure 泄漏);chart_base64 内容不变,零数字影响。回归风险低——只收紧 backend 选择与 figure 回收。
- **置信度**：high　|　**状态**：待修

#### [BUG-070] artifact git_commit 盖戳的 subprocess except 抓错异常类型——无 git 环境(FileNotFoundError)/超时(TimeoutExpired)未捕获,研报落地最后一步崩

- **类别**：Bug
- **严重度**：P2
- **位置**：finrobot/artifact/builders.py:54-66(_get_git_commit)→ :112-121(_make_base_compute_version)→ 盖在每个 compute artifact 的 ArtifactComputeVersion 上
- **现象/问题**：`_get_git_commit()` 用 `subprocess.run(["git","rev-parse","--short","HEAD"], timeout=2)` 给 artifact 盖代码版本戳,意图是"取不到就返回 None",但 `except (ImportError, AttributeError, TypeError, ValueError)`(:64)抓的全是错的异常类型——subprocess 在这两个最常见失败模式下抛的根本不是它们:(1) **git 不在 PATH** → `FileNotFoundError`(OSError 子类);(2) **git 卡住超过 2s**(大仓 / 慢盘 / index.lock) → `subprocess.TimeoutExpired`(SubprocessError 子类)。两者都不被现有 except 捕获 → 异常穿透 `_make_base_compute_version` → **artifact 落地直接崩**。这是个典型"静态审查盲区":审 agent 看到 `try/except` + `timeout=2` 就判定已兜底,但 except 列表里没有一个能接住 subprocess 真正抛的异常。
- **证据**：实测确认 `subprocess.run(['no_such_binary'], timeout=2)` → `FileNotFoundError`(被现有 except 捕获? **False**);`subprocess.run(['sleep','5'], timeout=0.3)` → `TimeoutExpired`(被捕获? **False**)。调用链:builders.py:118 `git_commit=_get_git_commit()` 在 `_make_base_compute_version` 内,给所有 compute artifact 盖 ArtifactComputeVersion 溯源戳——主路径,非边缘。
- **根因**：第一出错位置=builders.py:64 的 except 元组。写代码时凭直觉填了 import/attr/type/value(import 一个模块时的常见错),但本函数根本没 import 动作,真正的失败源是外部进程缺失/超时。属"防御性 except 抓了一组与实际失败模式无关的异常"。
- **修复方案**：把 except 改成实际会抛的:`except (FileNotFoundError, subprocess.SubprocessError, OSError):`(SubprocessError 覆盖 TimeoutExpired/CalledProcessError,FileNotFoundError/OSError 覆盖缺二进制与权限)→ 返回 None,让 git_commit 优雅缺省(字段本就是 `str | None`)。注意 ImportError 在这里根本到不了(无 import),可删;若想极稳可叠 `except Exception` 兜底但要 log.warning 不静默。补测试:tests 里 monkeypatch `subprocess.run` 抛 FileNotFoundError 与 TimeoutExpired,断言 `_get_git_commit()` 返回 None 且 `_make_base_compute_version(...)` 不抛、git_commit=None。
- **影响面/回归风险**：影响所有**无 git 或 git 慢**的运行环境——`pip install finrobot` 的终端用户(很可能没装 git 或不在仓库内)、Docker slim 镜像、CI without git、打包发行版。对一个 KPI=GitHub Stars、靠 `pip install` 跑起来的开源项目,这是高频首跑翻车点:用户跑完一条 30s 研报管线,在存 artifact 的最后一步崩。开发机有 git 且快,所以本地永不复现——这正是它躲过审查的原因。修复零行为变更(只是把"本该缺省"的路径真正接住),回归风险低。
- **置信度**：high　|　**状态**：待修

> **以下 BUG-071 ~ BUG-086 来自 2026-06-03 第二轮『运行时/环境/外部基准/领域口径』透镜专项审计**（dynamic workflow 12 子系统扇出 → 每条 Bash 实跑/实算验证 → 对抗验证者默认 refute 亲自复现 → 16 条 real 留存）。全部 `reproduced=True`，补的是静态对抗式审查（BUG-001~067）系统性触不到的『只有真跑/换环境/对外部基准才暴露』那一类。

#### [BUG-071] FMP _fetch_price 用未复权原始 close 作 price_history → 52周高低/SMA 与已复权路径口径分裂

- **类别**：Bug
- **严重度**：P2（finder P1，验证后按"被 yfinance 兜底 + 拆股标的才极端"降级）
- **位置**：finrobot/engine/data/providers/fmp_provider.py:468-478（price_history 取原始 open/high/low/close/volume，未调 _adjust_fmp_bar:41-67）
- **现象/问题**：FMP 是 PRICE 主源（sdk.py:109 / data_layer_factory.py:48 排在 yfinance 前，且 .env 有真 key）。_fetch_price 的 price_history 用**未复权** close，而同文件 _fetch_price_range(:523) 与 yfinance(auto_adjust=True) 都用复权基准。下游 extractor.fifty_two_week_high/low(extractor.py:124-125) 与 market.py 的 SMA20/50/200 全吃这条 history → 落在名义未复权价上。近 12 个月发生过拆股的标的（如 10:1），拆股前 K 线携带名义价（≈现价 10 倍），**52 周最高直接变成现价的 ~10 倍**；无拆股的分红股也有 0.5%–2% 系统漂移。同一标的同一天，研报 52 周高低会因"这次谁服务了 PRICE"而不同。
- **证据**：live 真 key 跑底层 /historical-price-full('AAPL')：276 根 K 线 **259 根 close≠adjClose**（例 2025-04-29 close=211.21 vs adjClose=210.09）。grep 确认 _fetch_price 不调 _adjust_fmp_bar，_fetch_price_range/yfinance 都走复权基准；price_history → 52w/SMA 消费链确认。
- **根因**：_fetch_price 漏调已存在的 _adjust_fmp_bar；两条价格路径各自文件内自洽，差异只在"谁复权"，静态读不出。
- **修复方案**：_fetch_price 的 price_history 改走 _adjust_fmp_bar(p)（丢弃缺 adjClose 的行），或直接复用 _fetch_price_range 的 bar 构建，保证 PRICE / PRICE_RANGE / yfinance 三路同口径。补测试断言 close 用 adjClose 基准。
- **影响面/回归风险**：影响 FMP 当 PRICE 活跃源时的 52w/SMA 数字（研报 MarketDataZone 直接展示）。修复改变这些数值（拆股标的差异巨大）——任何 pin 旧值的快照测试需更新。
- **置信度**：high　|　**状态**：待修

#### [BUG-072] NewsAggregator 唯一免 key 源 Yahoo RSS 已 404 下线 → 默认配置该 provider 100% 抛错 + 工厂注释撒谎

- **类别**：Bug
- **严重度**：P3（被 FMP NEWS 兜住、DataLayer graceful-degrade，故非用户必现）
- **位置**：finrobot/engine/data/providers/news_aggregator.py:36(_YAHOO_RSS_URL) + 91-92(全失败即 raise)；注册 finrobot/data_layer_factory.py:82-86
- **现象/问题**：默认无 alpha_vantage_api_key（本机实测 None）时 news_aggregator 只剩 Yahoo RSS 一个源。`feeds.finance.yahoo.com/rss/2.0/headline` 现返回 404 HTML → raise_for_status 抛 → ProviderError → fetch() 全失败抛"All news sources failed"。即该 provider 在默认配置下**永远不可能成功**，是个"注册了但必抛错"的死源，工厂注释还写着"always registered; uses Yahoo RSS (free, no key)"。
- **证据**：live httpx GET 该端点 ×3 ticker(AAPL/MSFT/TSLA) 全 404 + text/html；get_settings().alpha_vantage_api_key 实测 None。区别于 BUG-035(SDK 链注册漂移)。
- **根因**：外部端点失效（雅虎停服）+ 唯一免 key fallback 失守；纯静态触不到网络。
- **修复方案**：换 yfinance Ticker.news 或以 FMP/Finnhub 为 NEWS 主源；若无可用免 key 新闻源，删掉 Yahoo 分支并修正工厂的"free, no key"假承诺，别注册一个默认必抛错的 provider。
- **影响面/回归风险**：当前被 FMP NEWS 掩盖；FMP/yfinance NEWS 都失败时回退它会失败（被 DataLayer 接住降级，非整请求崩）。修复降低误导 + 恢复一条真实 fallback。
- **置信度**：high　|　**状态**：待修

#### [BUG-073] DCF/DDM 绝对估值对外币 ADR 零 FX 归一化 → 本币价当 USD 印出并比价

- **类别**：Bug
- **严重度**：P1
- **位置**：finrobot/engine/compute/dcf_seed.py:226,387,403,406；finrobot/engine/compute/ddm_seed.py:92-109；调用方 finrobot/engine/pipelines/equity_research.py:428 与 finrobot/routes/compute.py:257（直接喂未归一化 FinancialData）
- **现象/问题**：对 TSM/ASML/SAP 等美国上市 ADR，seed_dcf_inputs 直接读 income.revenue（申报币 TWD/EUR）与 market.market_cap / shares_outstanding（quote 币 USD）。EV∝TWD 营收 → equity_value(TWD)/shares → implied_price 实为"每股 TWD"，但 equity_research.py:465 `DCF base case implies $X per share` 当 USD 印出并与 USD 市价比出 BUY/SELL。TWD/USD≈0.031 → **价被放大 ~32x**；debt_ratio=total_debt(TWD)/(total_debt(TWD)+market_cap(USD)) 跨币种比值使 WACC 权重失真。DDM 的 payout×net_income(TWD)/shares 回退路径同样污染。
- **证据**：grep dcf_seed/ddm_seed/lbo_seed 对 currency/fx **零命中**（三个 seed 完全不读币种 tag）；currency.py:resolve_reporting_currency 对无点号 ADR+country=Taiwan 返回 'TWD'（financial.py:130 注释明写"DISAGREE for ADRs: TSM TWD/USD"）；只有 comps 的 normalize_peer_to_usd 做 FX，绝对估值分支不做（BUG-018 只修了 comps）。数值复现：跨币 debt_ratio=0.526 vs 正确 0.034，价 ~32x。
- **根因**：FX 归一化只在 comps 路径接线，DCF/DDM 绝对估值路径漏接；字段全是裸 float，需对照真实 ADR 申报币种事实才暴露。
- **修复方案**：seed_dcf_inputs / seed_ddm_inputs 入口对 reporting_currency≠USD 或 ≠quote_currency 复用 fx_normalize.normalize_company_to_usd（fetch_fx_rate_to_usd 取 reporting/quote 双 rate），把营收/债务/现金与市值/股本统一折 USD 再 seed；或币种不一致直接 raise/标 [金融待核] 拒跑。LBO 全程单一申报币内部自洽，只需标注币种不强制 FX。
- **影响面/回归风险**：影响所有外币 ADR 的 DCF/DDM 目标价与 verdict（研报核心数字）。区别于 BUG-006(comps forward)/BUG-037(XBRL 散度门)。修复改变 ADR 目标价（应当）。
- **置信度**：high　|　**状态**：待修

#### [BUG-074] DCF 末年 FCF 为负时 Gordon 终值资本化成永续负值 → 负『每股公允价值』直接进研报+LLM prompt

- **类别**：Bug
- **严重度**：P2
- **位置**：finrobot/engine/compute/dcf.py:61-67（terminal_value/pv_terminal/implied_price 无负值 guard）；finrobot/engine/pipelines/equity_research.py:431(degrade 只 except tg≥WACC),461(只过滤 sensitivity p>0),465/756(负价进叙事+prompt)
- **现象/问题**：terminal_value=projected_fcf[-1]×(1+tg)/(wacc-tg)。seed 把 CAGR 下限钳到 -20%，叠加 capex/da/nwc 后末年 FCF 可为负；tg<wacc 仍成立 → 终值为大额负数 → implied_price 为负。pipeline 的 graceful-degrade 只 except "tg≥wacc" 的 ValueError，**接不住负终值**；第 461 行 p>0 过滤只作用于 sensitivity 表，base case 不过滤。结果：研报印出负"公允价值/股"，且第 756 行把它当权威可引用数喂进 LLM thesis prompt 白名单。
- **证据**：python 跑真实衰退参数(revenue 1e11, growth=[-0.20]×5, ebitda 8%, capex 6%, da 5%, nwc 2%, tax 21%) → last fcf=-2.06e8 → terminal_value=-3.06e9 → implied_price=-$2.33（验证者复现到 -$24.03）。grep dcf.py/pipeline 无任何负终值/负价 guard。区别于 BUG-014(tg≥WACC)/BUG-026/060；valuation_aggregator.py:130 的 implied_price≤0 guard 只护 synthesis/football-field，不护叙事与 prompt。
- **根因**：把暂时的负 FCF 谷底当永续，公式在 tg<wacc 下数学合法所以静态看不出；degrade 只防一种异常给"已兜底"错觉。
- **修复方案**：calculate_dcf 算完 terminal_value 后对 projected_fcf[-1]≤0（或 terminal_value<0 / implied_price<0）显式处理：raise 独立异常让 degrade 接住跳过 DCF 章节（与 tg≥WACC 同等待遇），或用归一化稳态 FCF（末年营收×行业 FCF margin 下限）替代负末年 FCF 并在 provenance 标注；绝不让负公允价值落地或进 prompt。
- **影响面/回归风险**：影响衰退/高 capex 谷底公司的 DCF 章节与 LLM 叙事。修复让这类标的 DCF 优雅跳过或用稳态基数，回归风险低。
- **置信度**：high　|　**状态**：待修

#### [BUG-075] 13F refresh job 假设 edgartools 小写列名,实装 5.31.5 输出 PascalCase → institutional_holdings 永久空

- **类别**：Bug
- **严重度**：P2（finder P1，验证后按"机构持仓为分析增强非主数字"降级）
- **位置**：scripts/refresh_sec_holdings.py:49-51,98-102,155-163
- **现象/问题**：脚本 _EXPECTED_COLUMNS={cusip,nameOfIssuer,titleOfClass,value,sshPrnamt}（原始 XML 小写名），但实装 edgartools 5.31.5 的 ThirteenF.holdings DataFrame 输出 **PascalCase**（Cusip/Issuer/Value/SharesPrnAmount/Class）。schema gate(L155-163) 判每份 filing "unexpected schema" 全部 `continue`，_normalise_holding_row 读小写键全返回 None → 缓存恒 0 行 → compute_ownership_governance 的 institutional_holdings 永远 degraded（空）。
- **证据**：importlib.metadata 确认装的就是 5.31.5；inspect.getsource(ThirteenF.holdings) 显示 id_cols=['Issuer','Class','Cusip','Ticker']、sum_cols=['SharesPrnAmount','Value',...]；喂真实 PascalCase row 给 _normalise_holding_row → None；live ~/.finrobot/sec_holdings_cache.db 存在(job 跑过)但 `SELECT COUNT(*) FROM holdings`=0。test_refresh_sec_holdings.py mock 的是小写列(line14 'issuerName')，所以 **CI 绿、生产死**——典型集成时盲区。
- **根因**：依赖库列名约定与脚本假设漂移（库升级后大小写变了），mock 用了假设的列名所以测试测不出。
- **修复方案**：抓取后立即 `holdings_df.rename(columns=str.lower)` 统一小写再消费（不硬编码大小写）；或 _EXPECTED_COLUMNS 与读取改 PascalCase。补一条**用真实 edgartools 5.31.x 列名**的测试并 pin 版本，杜绝再次悄悄腐烂；更新过期的"edgartools 5.31"注释。
- **影响面/回归风险**：影响所有 ownership/governance 分析的机构持仓段（当前全空）。**注意：修此 bug 会激活 BUG-086（×1000 双倍放大），两条必须一起修**，否则机构金额立刻 1000 倍高估。
- **置信度**：high　|　**状态**：待修

#### [BUG-076] Sniper coherence gate 比原始 float、ship round(2) 值 → target 与现价差 <$0.005 时产出 R/R=0 的退化交易行

- **类别**：Bug
- **严重度**：P3（需 DCF target 落在现价半美分内，低频）
- **位置**：finrobot/engine/compute/sniper.py:182-204(gate 比未 round 值) vs 205-218(return 时 round(...,2))
- **现象/问题**：DCF target 与现价相差 sub-cent 时，coherence gate 用未 round 的 ideal_buy/take_profit/stop_loss 比较通过，但实际 ship 的 SniperPoints 把每个价位 round 到 2 位 → ideal_buy==take_profit(如都 372.80)、risk_reward_ratio=0.0、invariant_warning 字面印出"DCF intrinsic $372.80 < current $372.80"（自相矛盾）。gate 不 raise → _safe_sniper(technical_payload.py:172) 只 catch ValueError 接不住 → 退化行直接进 artifact，/api/compute/sniper 原样返回。
- **证据**：python 跑 calculate_sniper_points(current=372.80, dcf_target=372.799, hist=[372.80]×20) → **返回(非 raise)** ideal_buy=372.8/tp=372.8/rr=0.0/direction=SHORT/warning 含"$372.80 < $372.80"；current=50.00 dcf_target=49.997 同样 rr=0.0。区别于 BUG-042(LONG 模式 secondary_buy vs stop_loss)。
- **根因**：gate 在 round 之前比、return 在 round 之后给，round 把价位塌缩成相等；唯有对近似相等输入执行才显形。
- **修复方案**：对所有价位先 round(...,2) 再过 gate（或 gate 比 round 后的值），使 round 后塌缩(ideal_buy==take_profit / stop 落在入场 round 内 / R/R==0)被捕获 → raise ValueError(让 _safe_sniper 降级 None+warning) 或跳过 sniper 模块；并像 signal.py 拒绝 target==entry 那样在上游拒 |current−target|<1 tick。
- **影响面/回归风险**：低频(需 DCF target 落现价半美分内)；修复只收紧退化行，回归风险低。
- **置信度**：high　|　**状态**：待修

#### [BUG-077] SkillRegistry._load_all 只 catch SkillLoadError 不 catch pydantic ValidationError → 一个坏 SKILL.md 崩掉 server/SDK/CLI 启动

- **类别**：Bug
- **严重度**：P1（验证者从 P2 升级——是启动级崩溃，违背 fail-soft 设计）
- **位置**：finrobot/engine/skills/registry.py:30-35(except SkillLoadError) + finrobot/server.py:114(SkillRegistry(skills_path) 在 startup try/except 之外)
- **现象/问题**：frontmatter YAML 合法但字段类型写错的 SKILL.md（如 `triggers: comps-analysis` 字符串而非 list、`requires_data: [revenue, ebitda]` list-of-str 而非 list-of-dict）能过 _parse_frontmatter，但 load_skill 调 Skill(...) 抛 pydantic **ValidationError**——_load_all 的 `except SkillLoadError` 接不住 → 穿出 SkillRegistry.__init__。server.py:114 在 startup try/except 外建 registry → 一个坏技能文件**崩掉整个 FastAPI 启动**，正好复现 server.py:95-110 注释声称要防的"埋 stderr/60s hang"，且 registry docstring(L28-29)"don't crash on one bad skill" 对 ValidationError 是谎言。
- **证据**：写一个 `triggers: comps-analysis` + list-of-str requires_data 的 SKILL.md，跑 SkillRegistry(Path) → "REGISTRY INIT CRASHED: pydantic ValidationError — 3 errors"。当前 56 个内置技能全 load 干净(latent)；skills/ 树已带 partner-lseg/partner-spglobal 外部命名空间——外部作者技能是预期输入面。
- **根因**：except 列表漏了 ValidationError；load_skill 把裸 frontmatter 直喂 Skill(...) 无 coercion。
- **修复方案**：_load_all 的 except 扩成 `(SkillLoadError, pydantic.ValidationError)`（或 `Exception`），单个坏技能 log-and-skip（兑现文档契约）；或 load_skill 把 ValidationError 包成 SkillLoadError。registry 永不准从 __init__ 抛。可选再硬化 server.py:114 / sdk.py:128 try→registry 降级 None。
- **影响面/回归风险**：影响任何含一个类型错技能文件的部署（外部/partner 技能常见）。修复零行为变更（坏技能本就该 skip），回归风险低。
- **置信度**：high　|　**状态**：待修

#### [BUG-078] agent 工厂/orchestrator 用无 encoding 的 read_text() 读含中文 .md → 非 UTF-8 locale 下 agent 创建崩

- **类别**：Bug
- **严重度**：P2
- **位置**：finrobot/engine/agents/factory.py:27 + finrobot/engine/orchestrator.py:52
- **现象/问题**：create_sub_agents()/create_lead_agent() 在建 Agent 前 read_text() 读 instructions/*.md（含 UTF-8 中文：bull_agent.md 1560 非 ASCII 字节、bear 1428、judge 1455 等）。Path.read_text() 不传 encoding 时用 locale.getpreferredencoding()。LANG=C/POSIX（裸 Docker、未配 locale 的 systemd service）下 =ascii → **UnicodeDecodeError** → lead/sub agent 创建失败 → serve 启动崩/chat 无法初始化。Windows cp1252 同样炸。macOS(UTF-8) 永不复现。
- **证据**：grep 确认两处 read_text() 无 encoding；统计非 ASCII 字节(bull=1560 等)；`b.decode('ascii')` 对 bull/report/modeling 全 FAILS(0xe4/0xe2)，bull 连 cp1252 都 FAILS(0x81)；反证：同仓 skills/loader.py:29 `read_text(encoding="utf-8")` ——agents 路径漏写。
- **根因**：read_text() 漏传 encoding，依赖部署机 locale；纯静态无法判定 preferredencoding 运行时取值。
- **修复方案**：factory.py:27 与 orchestrator.py:52 补 `encoding="utf-8"`（与 skills/loader.py 对齐）；顺手 grep 全仓其余无 encoding 的文本 read_text()/open() 一并修齐。
- **影响面/回归风险**：影响所有非 UTF-8 locale 部署（裸 Docker/CI/Windows）；macOS/已配 locale 零影响。修复零风险。
- **置信度**：high　|　**状态**：待修

#### [BUG-079] semantic_diff 对 data_fetched_at 裸做 datetime 相减 → 一新一旧(tz-aware/naive)时版本对比端点 500

- **类别**：Bug
- **严重度**：P2（latent：当前 producer 全 tz-aware，旧/导入的 naive 数据才触发）
- **位置**：finrobot/artifact/semantic_diff.py:542；reachable 自 finrobot/routes/artifacts.py:267(GET /api/artifacts/{a}/diff/{b})
- **现象/问题**：L542 `gap_days = abs((b.inputs.data_fetched_at - a.inputs.data_fetched_at).days)` 无 tz 归一化。Pydantic 对无 offset 的 JSON 保留 naive datetime、有 `+00:00` 的为 UTC。当两个对比 artifact 一 naive 一 aware → `TypeError: can't subtract offset-naive and offset-aware` → 端点 500。全 artifact/audit/aggregations/analysis 面**只此一处**漏 _ensure_tz（同胞 hit_rate_overview/recent_research/compute/signal 都先归一化）。
- **证据**：grep semantic_diff.py 的 _ensure_tz/tzinfo **0 命中**；python 复现 ArtifactInputs.model_validate_json 对无 offset → tzinfo=None、对 +00:00 → UTC；端到端跑 build_semantic_delta(naive, aware) → 抛 TypeError。routes/artifacts.py:260-267 无 tz guard。区别于 OPP-006(前端)。
- **根因**：唯一漏做 _ensure_tz 的 datetime 减法；要真反序列化两个不同 vintage 的 artifact 才触发。
- **修复方案**：减法前归一化：`_aware(dt)=dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)`，`gap_days=abs((_aware(b)-_aware(a)).days)`，与同胞 _ensure_tz 纪律一致；补 naive×aware 配对回归测试。
- **影响面/回归风险**：影响旧/导入的 naive 时间戳 artifact 的版本对比；当前所有 producer tz-aware 故 latent。修复零行为变更。
- **置信度**：high　|　**状态**：待修

#### [BUG-080] /{ticker}/earnings-calls 构造循环在 try/except 外 → FMP quarter 缺失/为 0 触发 ValidationError 逃逸成裸 500

- **类别**：Bug
- **严重度**：P2
- **位置**：finrobot/routes/data.py:240-258（构造循环在 229-238 的 try/except 之外）
- **现象/问题**：用户点开"财报电话会逐字稿"标签，若 FMP 该次 transcript 的 quarter 缺失（年度会/特别会）或为 0/null，整个 endpoint 返回 500 + traceback（Tauri 壳里面板崩、无可读错误），而非降级跳过该条或 422。EarningsCallTranscript(earnings_call.py:19) 要求 `quarter: int Field(ge=1,le=4)`，而 route/provider 用 `.get('quarter', 0)` 的哨兵默认 0——恰是模型拒绝的值。
- **证据**：Read 确认 try/except(229-238) 只包 data_layer.fetch，构造循环(240-258)在外；python 跑 `EarningsCallTranscript(quarter=0,...)` → ValidationError(greater_than_equal)，quarter=None → ValidationError(int_type)。_data_http_error 只映射 ValueError/ProviderError，无全局 handler。区别于 BUG-013(/earnings history)/BUG-061(前端 React key)。
- **根因**：构造在 try 外 + 用了模型本身拒绝的哨兵默认 0；类型上 quarter 恒 int 故静态看不出 FMP 会喂 0/缺失。
- **修复方案**：把构造循环移进 try 并 catch ValidationError，单条 transcript 失败做 per-item 跳过+累加 warning（而非整请求 500）；或构造前校验 quarter∈1..4，非法落 skipped。
- **影响面/回归风险**：影响有年度会/特别会/pre-backfill quarter=0 的标的的逐字稿标签（FMP key 后）。修复让单条坏数据降级而非整页崩。
- **置信度**：high　|　**状态**：待修

#### [BUG-081] /{ticker}/price 的 session_state 对所有标的硬编码美东时段 → 港股/A股/日股盘中错标『已收盘』

- **类别**：Bug
- **严重度**：P2
- **位置**：finrobot/routes/data.py:377-410（_compute_session_state，_MARKET_TZ=America/New_York 9:30-16:00 对所有 ticker 无差别套用）
- **现象/问题**：非美股标的（yfinance 支持的 0700.HK / 600519.SS / 7203.T）在其本地交易时段内查 /price，session_state 恒为 'closed'，前端 freshness pill 把一笔真盘中报价显示成"上一交易日收盘"。ticker 仅 .upper() 无市场区分。
- **证据**：python 复现：港股盘中 10:00 HKT(==周二 22:00 ET) → _compute_session_state → 'closed'；A 股同理。港/A/日股交易时段恰落 ET 盘后，永远判 closed。docstring 自称"故意用交易所时区"但默认了交易所=ET。区别于 BUG-030(研报硬编码 $)、BUG-068(A股回测)——同源但不同位置。
- **根因**：把"美国"当默认市场（与 BUG-030 同一类平台级假设）；唯有对照外部市场日历才看得出"交易所"假设对非美标的是错的。
- **修复方案**：按标的所属交易所的时区+交易时段判定：从 yfinance 后缀(.HK/.SS/.SZ/.T/无=US)或 payload['exchange'] 解析市场，查对应 market calendar；无法判定时返 'unknown' 而非谎称 closed。
- **影响面/回归风险**：影响所有非美标的的 /price 市场状态标签。修复需引入市场→时区映射，回归风险低（美股路径不变）。
- **置信度**：high　|　**状态**：待修

#### [BUG-082] `finrobot dcf <ticker>` 死锁:_should_use_ddm 的 asyncio.run 把 cache 连接绑到随后销毁的 loop,第二个 asyncio.run 永久 hang

- **类别**：Bug
- **严重度**：P2（finder P1，验证后确认为"进程退出时 hang"非"零输出"，按严重度持平）
- **位置**：finrobot/cli.py:76(_should_use_ddm 内的 asyncio.run) + cli.py:285/294(dcf 命令第二个 asyncio.run)
- **现象/问题**：`finrobot dcf AAPL`（默认路径，无 --force-dcf）永久 hang、不返回不报错。dcf 命令对**同一个 deps.data_layer 做两次 asyncio.run 且中间不 close**：L76 _should_use_ddm 里 fetch(FINANCIALS) 开 DataCache 的 aiosqlite 连接(cache.py:167)绑到 loop-1 后销毁 loop-1；L285/294 第二个 asyncio.run 在 loop-2 复用同连接 → aiosqlite worker 线程绑死在已关闭的 loop-1，解释器退出时主线程在 threading._shutdown join 这个孤儿 worker 线程上**永久阻塞**。只有 dcf 命令受影响（comps/lbo/earnings/ddm 各单次 asyncio.run，backtest 命令在两次 run 间正确 close）。
- **证据**：独立 python 复现该模式(DataCache 在一个 asyncio.run 下打开、第二个 asyncio.run 复用且不 close) → 进程 hang 3+ 分钟(ps 显示仍在 R/S，强杀)；faulthandler 确认阻塞在解释器 shutdown 的线程 join；grep 确认 cli.py dcf 在 L76 与 L285/294 间无 data_layer.close()，backtest(cli.py:555/587)有。单 loop 测试(pytest-asyncio 单 loop)测不出跨 loop 连接复用。
- **根因**：用一次性 asyncio.run 打开共享 cache 连接，连接(及 worker 线程)跨 loop 存活到第二个 loop。
- **修复方案**：别用一次性 asyncio.run 开共享 cache——(a) 把 bank/DDM 探测折进跑 pipeline 的那个 asyncio.run（FINANCIALS fetch + is_bank 检查放进同一 async 入口），或 (b) 全程单 loop：`asyncio.run(_dcf_or_ddm(deps, ticker))`。去掉 _should_use_ddm 的独立 asyncio.run 即根除跨 loop 连接复用。
- **影响面/回归风险**：影响默认 `finrobot dcf <ticker>`（这是 CLI 一等命令）。修复收敛到单 loop，回归风险低。
- **置信度**：high　|　**状态**：待修

#### [BUG-083] ~/.finrobot/.secrets 权限偏离 0600 时严格等值校验抛未捕获 PermissionError → server 启动崩,无自愈

- **类别**：Bug
- **严重度**：P3（仅明文 FileSecretStore 兜底路径 + 需外部事件改 mode）
- **位置**：finrobot/secret_store.py:166-169(FileSecretStore._ensure_file 严格等值 0600 校验) ← finrobot/server.py:73/88(startup hydrate_settings_from_secrets)
- **现象/问题**：用明文 FileSecretStore 兜底的机器（headless/CI/Docker/WSL 或 FINROBOT_DEV_MODE=1），若 .secrets 的 mode 非**恰好** 0600，第一次 get() 即抛 PermissionError。server.py 在 lifespan startup(L88) 遍历每个 key 字段 get()(L73)，无 try/except → 整个 server 启动失败；CLI/SDK 同样崩。
- **证据**：L166-169 `if S_IMODE != (S_IRUSR|S_IWUSR): raise PermissionError`，每次读经 _ensure_file 触发。python 复现：建 store 写 secret(0600)→ chmod 0644 → get() 抛 PermissionError。非 0600 漂移的现实诱因：备份/zip 还原(tar/zip 不保 0600)、编辑器以 umask 默认(0644)重写、同步工具重置权限、非默认 umask——都不罕见。区别于 BUG-003/OPP-010(泄漏/脱敏)。
- **根因**：严格等值校验失败时崩而非自愈；happy path(O_EXCL 总建 0600)使单进程内永正确，要外部事件改 mode 才触发，无 in-repo 测试设此场景。
- **修复方案**：读时自愈而非崩——mode≠0600 则 `os.chmod(path, 0o600)` 后继续（文件本就 user-owned 本地，收紧权限永远安全），仅 chmod 本身失败才 raise；或把 server.py 的 hydrate 循环包成降级 no-keys + 大声 warning 而非中止启动。
- **影响面/回归风险**：影响明文 secret store 兜底 + 权限漂移的机器。自愈方案零安全损失（只会收紧权限），回归风险低。
- **置信度**：high　|　**状态**：待修

#### [BUG-084] PriceTrendChart 窗口首日收盘价为 0 时 1Y 涨跌幅渲染成 'Infinity%' + Y 轴 domain 拉歪

- **类别**：Bug
- **严重度**：P3（FMP _adjust_fmp_bar 丢 falsy close，实际触发率近零）
- **位置**：ui/src/components/charts/PriceTrendChart.tsx:123-124,221（ui_charts 与 ui_pages 两个 partition 独立各抓一次，同一 bug）
- **现象/问题**：`first=closes[0]; pct=((last.close-first)/first)*100`，无 first===0 守卫。首根 K 线 close===0 时 pct=Infinity，header 药丸渲染字面量 'Infinity%'（红/绿），Y 轴 domain 也被 0 基准拉歪。后端 contracts.py:trailing_1y_return_pct 与 routes/data.py:429 对同一除法都有 `if first/prev==0: return None` 守卫，**唯独前端图无**。
- **证据**：node 跑 closes=[0,10,20] → pct=Infinity，toFixed(1)==='Infinity'；后端 normalize/price.py 只丢 None close 不丢 0.0，故 0 首根可流到 closes[0]。组件已有 points.length<2 守卫但无 first===0 守卫。区别于 BUG-029(另一组件)。
- **根因**：前端是唯一未防的除数;只有真实 payload 含 0 收盘价(停牌/退市/稀疏日)才触发。
- **修复方案**：`const pct = first>0 ? ((last.close-first)/first)*100 : null`，null 时渲染 '—'（与组件其他 null 处理一致，镜像后端 prev==0 行为）；并在 windowOneYear 丢弃前导 0/非有限 close。
- **影响面/回归风险**：极低触发率；修复零回归。
- **置信度**：high　|　**状态**：待修

#### [BUG-085] 已完成 run 永不从 runStreamStore 清除 → StockWorkspace 每次回访重弹『报告已生成』toast + 3 次 query invalidation

- **类别**：Bug
- **严重度**：P3（finder P2，验证后按"骚扰+多余重拉非数据错"降级）
- **位置**：ui/src/stores/runStreamStore.ts:248-258,383-390(run.completed 不清 run，clear() 无调用方) + ui/src/views/StockWorkspace.tsx:55-97(组件级 lastNotifiedRunIdRef)
- **现象/问题**：AAPL 研报跑完后 run 永留 store(status:'completed')。弹成功 toast + invalidate 三棵 query(v5-artifacts-timeline / studied-tickers / dashboard) 的 effect 只靠组件级 useRef 去重。StockWorkspace 挂在路由 'stocks/:ticker'，导航去 /coverage 再回 /stocks/AAPL 会完全 remount → ref 重置 null → effect 重跑 → 看到仍在的 completed runState → (a) 重弹"报告已生成"toast (b) 重 invalidate 3 棵 query 强制重拉，**每次回访都来、无限**。
- **证据**：grep 全 ui/src 对 run store 的 clear()/dismiss()：clear() 无生产调用方(仅 test)，dismiss() 只置 flag 不删 run → completed RunState 整 session 常驻。router.tsx:107 确认 StockWorkspace 是 route-element(导航 remount)。StockWorkspace.tsx:58 useRef 每次 mount 重置 null；effect deps 含 runState?.status 故 remount 即跑。无全局/常挂的 run watcher(Sidebar 零 invalidate 引用)。
- **根因**：跨生命周期运行时交互——(store 存活>组件) ×(去重 key 限组件) ×(run 永不清)；每个文件本地都对，只在运行时交点出 bug。
- **修复方案**：让完成副作用在 **store 级**幂等而非组件级——(a) run.completed/failed 后在被消费视图 dismiss 时真的从 s.runs 删终态 run；或 (b) 把去重 key 移出组件、放进 runStreamStore 模块级 `notifiedTerminal: Set<runId>`（store action 内 check/mark），remount 无法重放 toast/invalidation。推荐 (b)。
- **影响面/回归风险**：影响每次回访已跑过研报的 ticker（骚扰 + 多余重拉）。修复零数据影响。
- **置信度**：high　|　**状态**：待修

#### [BUG-086] [休眠·须与 BUG-075 同修] 13F value 双倍 ×1000 → 机构持仓金额 1000 倍高估

- **类别**：Bug
- **严重度**：P2（休眠：当前被 BUG-075 列名 bug 挡住不执行；BUG-075 一修即激活吐错数）
- **位置**：scripts/refresh_sec_holdings.py:99-102
- **现象/问题**：edgartools 5.31.5 的 ThirteenF.holdings 已把 Value 列对现代(post-2022Q3)filing 归一化成**整美元**（仅 legacy thousands schema 内部 ×1000），即脚本拿到的 DataFrame 已是整美元。但 L102 `float(df_row.get('value') or 0) * 1000.0` 又**无条件再 ×1000** → InstitutionalHolding.value_usd 对所有现代 filing **1000 倍高估**（$250M 持仓显示成 $250B）。L99 注释"13F reports value in THOUSANDS"对原始 SEC XML 成立，但对 edgartools 返回的已归一化值**不成立**。给分析师看一个 1000 倍错的美元数 = 砸招牌。
- **证据**：inspect ThirteenF 确认 `_value_in_thousands`(models.py:537-540) 仅对 period_of_report≤2022-09-30 才 ×1000，现代 filing 已是整美元；L102 的 ×1000 是第二次。**当前不可达**：因 BUG-075 的列名(小写)不匹配，schema gate 跳过每份 filing，_normalise_holding_row(含 L102)从不执行——所以今天不产出错数，但 BUG-075 修好后立即激活。
- **根因**：误以为 edgartools 返回的是原始 XML 的 thousands 口径，重复了库已做的归一化；被另一个未修 bug(列名)掩盖处于休眠。
- **修复方案**：删掉 `* 1000.0`，直接 `float(df_row.get('Value') or 0)`（edgartools 已返整美元、legacy thousands 它自己回填）。补**外部基准断言测试**：取一个已知 holder/issuer/季度（如 Vanguard 的 AAPL 持仓），value_usd 对 SEC EDGAR 实际 13F 值在容差内匹配，gate refresh。
- **影响面/回归风险**：**必须和 BUG-075 同一次修**——单修 BUG-075 不修本条 = 机构金额 1000 倍错进 artifact。两条一起修：列名对齐(取数能进) + 删 ×1000(口径对) + 外部基准测试(防回归)。
- **置信度**：high（技术判定确证，验证者唯一保留是"当前休眠不可达"，已如实标注）　|　**状态**：待修

### 详细条目（产品）

#### [UX-001] 冷启动首份研报动线被拆成两条不相通的入口，且 Starter 终点是空墙而非一份研报

- **类别**：产品
- **严重度**：P1
- **位置**：动线：/coverage 冷启动 → CoverageEmptyState（Starter）/ CoverageHero 并存 → /stocks/:ticker cold → 跑研报 → 读 13 章  ·  （另涉：CoveragePage.tsx:185-209（CoverageEmptyState 早返回）vs :289（CoverageHero 永不在零态渲染））
- **现象/问题**：零数据新用户进 /coverage 面对两个互不相通的起点：(a) 顶部 CoverageHero 大搜索框（输 ticker→/stocks/:ticker，AIZone cold，再点跑）；(b) 当 groups 为空时整页被 CoverageEmptyState 接管（Hero 看不到了），CTA 是『创建覆盖组』（i18n: coverage.starter.cta），把 3-10 个 ticker 加进一个组后落在一面『暂无研报』的空墙，用户还得自己点卡→进 workspace→点跑→等→回来。两条路心智不同（搜一支深研 vs 建一个组），且 Starter 这条加完 ticker 不产出任何研报——第一次『读到一份 13 章可溯源研报』的 wow（本产品真正的差异化）被推到 4-5 步之后，没有任何一条路把『首份研报』设计成引导动线。
- **证据**：CoverageEmptyState.tsx:104-123 CTA=coverage.starter.cta=『创建覆盖组』，step3=『运行研究，生成第一份可追溯研报』被排在第 3 步且需用户自行触发；CoveragePage.tsx:185-209 groups 为空时整页 return CoverageEmptyState（CoverageHero 被旁路）。两个入口（line 289 的 Hero vs 空态的 Starter）在『groups 是否为空』上互斥呈现，新用户先看到的是 Starter 而非 Hero。boss 要求 PM 三问『桌面内闭环吗 / 读得透吗』在冷启动这里不成立。
- **根因**：CoverageDesk 改版（specs/research/CoverageDesk-首页改版方案-2026-06-01）把首屏改成『覆盖盘运营』心智，但冷启动场景仍沿用旧的『建组』Starter，没有为『新用户第一份研报』裁决一条单一主动线；ensure_studied_membership 已经做到『打开任意 ticker 即静默入组』（service.py:476），Starter 的手动建组其实是冗余且更慢的第二条路。
- **修复方案**：裁决主动线=『搜一支→一路到读 13 章』。CoveragePage.tsx:185 的空态分支不要整页替换成『建组』Starter，而是渲染一个放大版的 CoverageHero（复用 CoverageHero.tsx，文案改成『输入一支股票，看 FinRobot 给你一份可溯源研报』）+ 3-4 个热门 ticker chip（直接 navigate('/stocks/SYM') 而非 toggle 进待建组列表）。建组完全交给已有的 useAddStudiedTicker 静默后台完成（StockWorkspace.tsx:126-137 已实现）。CoverageEmptyState.tsx 的手动『创建覆盖组』流程降级删除或仅保留为高级入口。注意：这是行为级改动，碰到冷启动首屏，按 CLAUDE.md 属需 boss 知情的 IA 决策——建议落地前在 docs/UI设计.md 里把『主任务=单股深研，Coverage Desk=回访沉淀层』写成权威定义。改动量：中（重写 CoverageEmptyState 渲染 + CoveragePage 空态分支，~80-120 行，跨 2 文件 + 1 文档）。
- **验证补充**：Direction (single 'search one name → read report' funnel) is sound and aligns with the auto-enrol contract. Do NOT ship as silent behavior change — finding correctly tags it [需确认]/IA decision per CLAUDE.md. Drop to P2 and gate on boss sign-off + docs/UI设计.md authority before coding.
- **影响面/回归风险**：影响 100% 新用户的第一印象与留存——首份研报是唯一的 aha。回归风险中：改了冷启动渲染分支，需确认『有 groups 但 needs_action 为空』『有 groups 有 rows』等其它态不受影响；Starter 删除后要确认没有别处依赖 coverage.starter.* 文案/onCreate 回调（CoveragePage.tsx:189-206 的 createGroup+addMembers 仅此处用，可一并清理）。
- **合并自**：ux-IA-simplify#1, ux-firsttime#4（2 条同源发现）
- **置信度**：high　|　**状态**：待修

#### [UX-002] 首份研报跑完后还要手动点一次才能阅读——"第一次惊艳"被一次多余点击拦住

- **类别**：产品
- **严重度**：P1
- **位置**：PipelineProgressPanel.tsx:173-195（完成态"打开研报"按钮，无自动跳转）+ AIZone.tsx:879-898（HotState 再要一次"打开完整研报"）  ·  （另涉：动线：AIZone 跑研报完成 → HotState（ui/src/views/workspace/AIZone.tsx:272-308, 879-898 open-latest-report 按钮） ; 动线环节：跑研报完成 → AIZone hot 卡 / PipelineProgressPanel ; 动线环节 3-5:ui/src/views/StockWorkspace.tsx:59-97(完成只发 toast + invalidate)+ ui/src/views/PipelineProgressPanel.tsx:173-195(完成态保留'打开研报'按钮)+ AIZone HotState(再要点 open-latest-report)）
- **现象/问题**：研报跑完，PipelineProgressPanel 头部出现"打开研报"按钮但绝不自动导航；同时 AIZone 翻成 HotState，又要用户点"→ 打开完整 13 章研报"。用户盯着进度条等了 60s，完成的那一刻没有被直接送进研报正文，而是要在两个并存的"打开"按钮里自己再点一下。对首次使用者，这一步正是"哦，原来它能给我这个"的临门一脚，却被一次多余点击稀释。
- **证据**：PipelineProgressPanel L173 `{run.status === 'completed' && run.artifactId && (<button ...onClick={() => navigate(\`/stocks/${ticker}/runs/${run.artifactId}\`)}>打开研报</button>)}`——只渲染按钮，组件内无任何 completed→navigate 的 effect。StockWorkspace L59-97 的完成 effect 只发 toast + invalidate query，不导航。cold CTA 文案已诚实承诺产出（i18n `▶ 立即跑 AI 研报（~60s）` + 13 章清单），所以问题不在文案而在完成后的衔接。
- **根因**：完成态被设计成"停在原地让用户决定"，但首份研报和重跑用的是同一套完成逻辑，没有区分"这是该 ticker 第一份研报（值得自动带去阅读）"vs"重跑（用户多半想留在 workspace 比对版本）"。第一个出错位置是 PipelineProgressPanel 完成分支只挂按钮、无条件自动跳转。
- **修复方案**：在 StockWorkspace 的完成 effect（L63 `if (runState.status === 'completed')`）里加一个"首份研报自动导航"判据：当该 ticker 此前 equity_research 版本数为 0（用 useV5ArtifactTimeline 过滤 type==='equity_research' 的 length，或 latest 之前为空）且本次产物是 equity_research 时，`navigate(\`/stocks/${symbol}/runs/${run.artifactId}\`)`；重跑（已有版本）保持现状只 toast。注意：从 Coverage 批跑触发的 run 用户可能不在该 workspace 页（CoveragePage 也 track run），自动导航只应在用户当前就在该 ticker 的 workspace 时发生——用 useLocation 判断 pathname 是否 `/stocks/${symbol}` 再跳，避免把正在看别的票的用户强行拽走。改动量级：小（StockWorkspace 完成 effect 加约 10 行 + 一个 timeline 长度判据）。
- **验证补充**：Fix is feasible. Caveats: (a) StockWorkspace does NOT currently import useV5ArtifactTimeline — the 'first equity_research version' judgment must add that hook (AIZone already uses it, pattern exists). (b) runState exposes artifactType (used in AIZone L145) and runId/artifactId, so gating on type==='equity_research' + prior version count==0 is doable. (c) useLocation guard already present (StockWorkspace L37) — must check pathname===`/stocks/${symbol}` before navigating so a Coverage-batch run doesn't yank a user viewing another ticker. The finding already calls these out correctly.
- **影响面/回归风险**：只影响"用户停留在该 ticker workspace 且这是首份研报"的场景，转化关键路径。回归风险：必须严守"仅首份+仅当前页+仅 research"三条件，否则会打断重跑比对、或把批跑用户从覆盖墙弹走。
- **合并自**：ux-IA-simplify#2, ux-firsttime#6, ux-coreflow#5, opp-wow#4（4 条同源发现）
- **置信度**：high　|　**状态**：待修

#### [UX-003] TickerNotFound 的「返回」按钮指向已退役的 /stocks，触发二次重定向 + 错误的合并提示

- **类别**：产品
- **严重度**：P1
- **位置**：ui/src/views/workspace/TickerNotFoundView.tsx:67 (`to="/stocks"`)  ·  （另涉：ReportToolbar.tsx:145（面包屑 STOCKS → navigate('/stocks')）→ router.tsx:101-106（/stocks 是 RedirectWithToast 退役重定向） ; ui/src/pages/artifact-detail/shell/ReportToolbar.tsx:145）
- **现象/问题**：用户输错一个 ticker（422）落到 TickerNotFoundView，唯一的 CTA『返回』link 到 /stocks。但 /stocks 已在 router.tsx:101-106 退役为 RedirectWithToast→/coverage。所以点『返回』不是干净落地，而是经过一次重定向；而那次重定向写入的 sessionStorage 文案是『stocks 已合并到 coverage』——一个跟『ticker 没找到』毫不相干的工作台合并提示（若 finding#2 修复后会真的弹出来，更荒谬）。
- **证据**：TickerNotFoundView.tsx:67 `<Link to="/stocks">`；router.tsx:101-106 /stocks→RedirectWithToast(messageKey='shell.router.stocksMergedCoverage')。同类问题：dashboard.py 无关，但 router.tsx:136-171 里 /dashboard /library /journal /playground 全部 `to="/stocks"`，而 /stocks 本身又是重定向→形成 /dashboard→/stocks→/coverage 的双跳链，两次 RedirectWithToast 写同一个 sessionStorage 键，第二次覆盖第一次，用户即便修了 finding#2 也只会看到『stocks merged』而非『dashboard merged』的错误提示。
- **根因**：砍 /stocks landing 时，下游所有指向 /stocks 的链接（TickerNotFoundView 的返回、4 个退役页的 redirect target）没有跟着改成最终目标 /coverage。第一个出错位置是这些 `to` 字面量没随 /stocks 退役而更新——路径分裂/死链（CLAUDE.md 明令禁止）。
- **修复方案**：1) TickerNotFoundView.tsx:67 把 `to="/stocks"` 改为 `to="/coverage"`，文案 ticker.notFound.backButton 若写的是『返回个股』可顺手校准成『返回覆盖台』。2) router.tsx:136-171 把 /dashboard /library /journal /playground 的 `to="/stocks"` 全部直接改为 `to="/coverage"`（消除双跳），并校对各自 messageKey 文案指向 coverage。注意 library/:ticker、playground/:ticker 用 preserveTicker→应改为 `to="/stocks/:ticker"` 形式（带 ticker 进个股工作台）而非 /stocks，否则丢上下文。改动量：~7 处字面量，单/双文件。
- **验证补充**：Fixes correct: TickerNotFoundView→/coverage; retired routes→/coverage directly. Caveat on the preserveTicker ones (library/:ticker, playground/:ticker): their target should become /stocks/:ticker (StockWorkspace) to keep the ticker, NOT /coverage — finding already notes this. Verify StockWorkspace is the intended landing for a preserved ticker.
- **影响面/回归风险**：影响输错代码的用户（高频误操作）+ 所有走旧链接的用户。回归风险低（只换目的地常量）；建议跑一遍 router 测试确认无路径 404。
- **合并自**：ux-IA-simplify#3, ux-coreflow#2, ux-firsttime#3（3 条同源发现）
- **置信度**：high　|　**状态**：待修

#### [UX-004] 投委会辩论跑完是死胡同：无任何 next-step CTA + 用完即焚

- **类别**：产品
- **严重度**：P1
- **位置**：ui/src/pages/ic/IcDebatePage.tsx:144-244 + components/debate/VerdictCard.tsx
- **现象/问题**：IC 辩论是产品里最重的差异化能力（Bull/Bear 交叉辩论 + Conviction Score + Change My Mind），但辩论 completed 之后整页是死胡同：VerdictCard 没有任何按钮/导航，页面底部只有 bull/bear 两栏论点，唯一的动作是「重试辩论」或浏览器后退。用户读完一个有信念度的裁决后，无法『把这个结论落到任何地方』——不能存成 memo、不能回研报对照、不能加进 coverage、刷新即全部丢失（EphemeralNotice 明示）。
- **证据**：复现：研报 ReportToolbar 点「投委会」→ /ic/NVDA → 点开始 → 等辩论流完 → 看到裁决和双栏论点 → 此时屏幕上能点的只有右上角『⚖ 重试辩论』(IcDebatePage.tsx:161-167) 和面包屑后退。VerdictCard.tsx 通读无 button/onClick/navigate（grep 确认 62-91 行只有样式）。辩论结果不写 artifact（文件头注释 BUG-20260602-015 + EphemeralNotice 423-452），刷新即失。而 AIZone 的 ARTIFACT_TYPE_LABEL 已预留 ic_memo 标签(AIZone.tsx:33)、CompactArtifactViewer 已能渲染 ic_memo(CompactArtifactViewer.tsx:203-215)——说明持久化的数据通道已存在，只差把辩论结论落地。
- **根因**：辩论被定位成『纯流式临时视图』而非『产出物』：startDebate 走 SSE 不落 artifact，IcDebatePage 完成态只渲染论点不给出口。第一个出错位置是 IcDebatePage completed 分支(145-244)缺一个底部 action 区。
- **修复方案**：在 IcDebatePage.tsx isCompleted 分支底部（MarketImpliedPanel 之后、bull/bear grid 之前或之后）加一个 action 行：①『← 回到研报』(navigate(reportPath)，reportPath 已在 40 行算好) ②『回 Coverage』(navigate('/coverage')) 两个明确出口；VerdictCard 顶部也可加一个回研报链接。中期：把辩论结论持久化为 ic_memo artifact（后端 /api/debate 加 save，前端完成后 invalidate timeline），届时把 EphemeralNotice 换成『已存入 NVDA 历史』+ 打开链接。注意：当前 EphemeralNotice 的诚实文案在持久化落地前不能删。
- **验证补充**：建议先做轻量出口（两个 navigate 按钮），持久化 ic_memo 列为后续；注意 EphemeralNotice 文案在 save 落地前保留——作者已正确指出
- **影响面/回归风险**：仅前端加 2 个导航按钮，零回归风险；持久化是中等改动(后端+store)。影响所有走 IC 辩论的用户——目前他们读完最有价值的结论后被晾在原地。
- **置信度**：high　|　**状态**：待修

#### [UX-005] "待处理"分诊是首屏，但卡片不说"为什么需要我"——理由被挤进一个截断的小药丸

- **类别**：产品
- **严重度**：P1
- **位置**：CoverageCard.tsx:305-325（status pill 单行截断）+ cardStatus():58-67（只取 reasons[0]）
- **现象/问题**：首屏默认 filter='needs_action'（CoveragePage L69），整页定位为"分诊队列就是首页"。但 coveragePriority 已经算出结构化的 reasons[]（run_failed / signal_closed / never_run / 数据警告），卡片却只把 reasons[0] 塞进底部一个 flexShrink:1、ellipsis、fontSize:10 的小药丸里，和 provider·as_of 抢同一行宽度。用户站在"待处理"首屏，看到的是一排卡片，却要逐个 focus 到右侧 inspector 才知道每张为什么待处理。分诊台退化成一个计数器。
- **证据**：CoverageCard cardStatus L64-65 `const { reasons } = coveragePriority(row); if (reasons.length > 0) return { text: reasons[0], tone: 'warn' }`——只用第一条。渲染处 L305-325 该 pill `flexShrink:1, minWidth:0, overflow:hidden, textOverflow:ellipsis, whiteSpace:nowrap, fontSize:10`，且与右侧 `provider · asOf` 共享一个 space-between 行。coveragePriority L33-36 明明聚合了 needs_refresh.detail + warnings 的完整列表。WallHeader 的三段也只显计数（`{t(FILTER_KEY[f])} · {filterCounts[f]}`，L107），不显理由分布。
- **根因**：卡片信息架构把"为什么待处理"当成次要的"质量/freshness"附注，而非"待处理首屏"的主信息。第一个出错位置是 cardStatus 把多条 reasons 压成一条、且渲染层用最弱的视觉权重（10px 截断药丸）承载它。
- **修复方案**：在 CoverageCard 里把"needs action 理由"提升为卡片的一等公民：当 needsWarn（L85）为真时，在 verdict 行下方或 metrics 上方加一条不截断的理由行（最多显 2 条 reasons，amber 图标 + 简短 detail），把现有底部 pill 留给"fresh / running / provider"。理由文案直接用 coveragePriority().reasons（已是 backend detail 文本）。注意：detail 是后端文本，长度不可控——用 2 行 clamp（-webkit-line-clamp:2）而非 nowrap ellipsis，且只在 needs_action 视图强化（all 视图保持紧凑），避免把"全部"墙撑乱。改动量级：中（CoverageCard 加一段条件渲染 + 微调高度 floor，~40 行；需回归卡片等高墙不被理由行打破——L112 minHeight 是 floor 不是 cap，安全）。
- **验证补充**：Fix is reasonable. Validated safety note: CoverageCard L112 minHeight is a FLOOR not a cap (comment L1-9 + L110-112), and the grid uses gridAutoRows:'max-content' (L108-109 comment), so adding a 2-line reason row won't clip — confirmed. Scope the strengthened reason row to needsWarn (L85) + needs_action view only, as the finding says, to avoid bloating the 'all' wall. Use -webkit-line-clamp:2 not nowrap.
- **影响面/回归风险**：影响首屏分诊的实际可用性（核心动线）。回归风险：理由行高度可变可能破坏"等高卡墙"的视觉节奏——必须用固定行数 clamp 并验证 needs_action 与 all 两视图下卡片仍对齐。
- **置信度**：high　|　**状态**：待修

#### [UX-006] 无法删除/归档单份历史研报——后端有 DELETE 端点，前端零入口，跑错/作废的研报永久堆积

- **类别**：产品
- **严重度**：P1
- **位置**：CoverageInspector.tsx onRemove (L197-201/258-271 CoveragePage) + ui/src/api/client.ts（无 deleteArtifact）
- **现象/问题**：一支股票随研究迭代会积累十几份研报/模型产物（每次 Re-run 都新增一份 immutable 版本）。用户跑错 ticker、用了脏数据、或某版 thesis 被推翻，想删掉它——但整个桌面端没有任何删除/归档单份 artifact 的入口。Inspector 的『移除』按钮（onRemove→handleRemoveMember）只把 ticker 从覆盖分组里摘掉，artifacts 全部留在库里，下次再打开这支股票它们又全回来了。
- **证据**：后端 finrobot/routes/artifacts.py:210 `@router.delete("/{artifact_id}")` 完整实现了永久删除；但 ui/src/api/client.ts 只导出了 markArtifactViewed，全仓 grep `api.DELETE`/`deleteArtifact` 对 artifact 零命中（只有 coverage group/member 的 DELETE）。CoveragePage.tsx:258 handleRemoveMember 调的是 useRemoveMember → /api/coverage/groups/{id}/members（仅移出 watchlist）。版本时间线（ReportRightRail/AIZone/Inspector History/ReportToolbar 下拉）每一处都只读不能管。
- **根因**：管理动作（删/归档）在 redesign 落地时未接线：后端 D 已就绪，前端 C/U/D 中只接了读（timeline）和『查看』（view/un-archive），删除被整体跳过。第一个出错位置是 ui/src/api/client.ts 缺 deleteArtifact 封装 + Inspector History 行无删除按钮。
- **修复方案**：① ui/src/api/client.ts 加 `deleteArtifact(id)` 封装 `api.DELETE('/api/artifacts/{artifact_id}')`；② CoverageInspector.tsx 的 HistoryPanel 每行（L349-407）在 ↗ 旁加一个垃圾桶 IconButton，点了走 ConfirmDialog（项目已有 CoverageGroupMenu 的 confirm 模式可复用）→ deleteArtifact → 成功后 invalidate ['v5-artifacts-timeline', ticker] + ['studied-tickers'] + ['dashboard']；③ ReportToolbar 也加一个『删除此版本』（非 primary，放 Export 左侧），删当前 artifact 后 navigate('/stocks/'+ticker)。注意：删除是永久的（后端 hard delete），confirm 文案要写明『不可恢复』；删的是 current 版本时必须先离开详情页避免 404 闪烁。量级：中（~3 文件，含一个复用 confirm 组件）。
- **验证补充**：Fix plan is sound. One caution: deleting the CURRENTLY-viewed artifact from ReportToolbar must navigate away BEFORE the cache invalidation (useArtifactDetail has staleTime:Infinity/retry:1 — a refetch on a deleted id yields 404). Suggested order: navigate('/stocks/'+ticker) first, then invalidate timeline/studied/dashboard. Otherwise correct.
- **影响面/回归风险**：影响所有有多份历史的 ticker；回归面小（纯新增动作，读路径不动）。需注意删掉 parent_artifact_id 被引用的版本后，子版本的 VersionDiffBanner defaultBase 会 fallback 到 candidates[0]（已有保护，L181），不会崩。
- **置信度**：high　|　**状态**：待修

#### [UX-007] 冷启动时已有覆盖的老用户会闪现「还没有 ticker——在上方添加」假空态

- **类别**：产品
- **严重度**：P1
- **位置**：ui/src/pages/CoveragePage.tsx:185, 362-371
- **现象/问题**：CoveragePage 主渲染路径没有对 groupsQuery.isLoading 做加载守卫。groups 还在请求中时（每次冷启动、server 刚 boot 时这条 /api/coverage/groups 是未缓存且可能慢），activeGroupId=null → useCoverageOverview(null) 因 enabled:false 在 TanStack v5 下 isLoading=false、data=undefined → rows=[] → 命中 line 370 的 rows.length===0 分支，渲染 t('coverage.emptyGroup')=「还没有 ticker——在上方添加。」。一个有满满一墙 Studied Tickers 的老用户，每次打开 app 的第一帧都被告知他的覆盖盘是空的。
- **证据**：复现：清掉 query 缓存 / 冷启动 app 进 /coverage。line 185 的 Starter 守卫是 `!groupsQuery.isLoading && groups.length===0`，loading 期间为 false 跳过 Starter；落到主渲染，line 362 的 `overviewQuery.isLoading` 对一个 disabled query 为 false（v5 disabled query: status='pending' 但 fetchStatus='idle'，isLoading=isPending&&isFetching=false），于是直接走 line 370 的空态文案。这是「错误/加载态伪装成空态」——审查重点明确列出的反模式。
- **根因**：CoveragePage 把『groups 在加载』和『group 内 rows 为空』两个状态合流到同一个 rows.length===0 出口。第一个出错位置是主渲染缺少 `if (groupsQuery.isLoading) return <Placeholder text={t('coverage.loading')} />` 这一层守卫——empty-state 守卫只判 !isLoading 却没给 isLoading 单独出口。
- **修复方案**：CoveragePage.tsx：在 line 184 的 Starter 守卫之前（或之上）补一个加载守卫——`if (groupsQuery.isLoading) return <全页 Placeholder/skeleton text={t('coverage.loading')} />`（与 line 362 已有的 coverage.loading 文案一致）。注意 activeGroupId 仍为 null 时不要进 overview 出口；守卫要在 useCoverageOverview 之前判断 groupsQuery.isLoading，避免空态文案先于真实数据出现。改动量：~6 行，单文件。
- **验证补充**：Fix direction correct (add `if (groupsQuery.isLoading) return <Placeholder text={t('coverage.loading')}/>` before line 185). Note the window is brief (groups resolves fast once cached), so the visible blink is short — still worth fixing for correctness.
- **影响面/回归风险**：影响每一次冷启动的首帧观感（最高频路径）。回归风险极低——只是把 loading 从 emptyGroup 文案里分流出来；现有 Starter / 错误态 / 正常态分支不变。建议加一条测试：mock groupsQuery.isLoading=true 时断言不出现 coverage.emptyGroup 文案。
- **置信度**：high　|　**状态**：待修

#### [UX-008] HotState 裁决为 REVIEW 时目标价静默消失，不解释『为什么扣留』

- **类别**：产品
- **严重度**：P2
- **位置**：ui/src/views/workspace/AIZone.tsx:818-844 (target 块) + 731-741 (REVIEW tone)
- **现象/问题**：当研报裁决是 REVIEW（数据健康门控：估值方法交叉校验分歧>50%，目标价被扣留），HotState 渲染一个中性『待复核』徽章，但因为 target===null，整个『12-Month Target』块直接不渲染——用户看到的是一个没有目标价的研报卡，且没有任何一行字解释『目标价为什么不见了』。分析师会以为是 bug 或数据没跑出来，而不是『系统因为口径打架主动扣留了目标价』——这恰恰是本产品最该自豪的诚实信条，却没说出口。
- **证据**：AIZone.tsx:818 `{target !== null && (...12-Month Target...)}`：REVIEW 时 target 为 null，块消失。731-741 REVIEW 用中性 slate tone，verdictLabel→『待复核』(verdict.ts:46)。卡片只剩一个徽章+可能的 tagline/headline，但 tagline 是 LLM 写的 ≤60 字 share line，不保证解释扣留原因。对比 IC 页有专门的 ic.column.provisional 长文案解释可靠性不足，workspace 卡这里什么都没有。
- **根因**：REVIEW 的『目标价被扣留』是一个需要主动解释的特殊态，但 HotState 把它当成『恰好没有 target 的普通研报』处理——target 块用 truthy 判断直接吞掉，没有 REVIEW 专属的说明行。
- **修复方案**：AIZone.tsx HotState：当 verdict==='REVIEW' 时，在 target 块的位置渲染一行说明（替代消失的目标价），如『目标价已扣留 · 估值方法交叉校验分歧过大，点开研报看口径明细 →』，i18n 新增 key。复用已有的中性 tone 配色，不用涨绿跌红。注意别和已有 tagline 重复堆叠。
- **验证补充**：复用现成 chapter.cover/thesis.targetWithheld 文案家族而非全新 key，保持口径一致；说明文案应指向『点开研报看口径明细』，与全文 thesis 章节的扣留解释呼应
- **影响面/回归风险**：局部展示改动，零数据回归。把一个看起来像 bug 的静默态变成产品的诚实卖点。
- **置信度**：high　|　**状态**：待修

#### [UX-009] 一支股票→多份历史研报的下钻要 3+ 步且断裂——卡片『N 份研报』不可点，发现历史得先进 workspace 再滚到底

- **类别**：产品
- **严重度**：P2
- **位置**：CoverageCard.tsx L363-371（研报计数文本）+ CoveragePage.tsx L382/391（onOpen→/stocks/SYM）
- **现象/问题**：覆盖墙卡片上明明写着『3 份研报 · 2026-05-30』，这是用户对『这支股票有多少历史』的第一个认知锚点——但它是纯文本，不可点。卡片右下的 ↗（open）跳到的是 /stocks/SYM 工作台，落在 AIZone 的最新报告卡，用户得往下滚过 verdict 卡 + 13 章 mini-grid 才看到『版本时间线』，而且那里只列最近 5 个（AIZone L1004 slice(0,5)），更老的版本在工作台上根本看不到。要看全部历史，路径是：卡片→工作台→滚到底→发现只有5个→进某份报告→用 toolbar 下拉。Inspector 的 History tab 是唯一列全（limit 200）的地方，但它要先 focus 卡片切到第三个 tab，发现成本高。
- **证据**：CoverageCard.tsx L363 研报计数是 `<span>` 文本无 onClick；CoveragePage.tsx L382 `onOpen={(ticker)=>navigate('/stocks/'+ticker)}` 落工作台不落报告列表。AIZone.tsx:1004 `timeline.slice(0,5)`、ReportRightRail.tsx:92 `slice(0,8)` 都截断且无『查看全部』。只有 CoverageInspector HistoryPanel（L327 HISTORY_LIMIT=200）和 ReportToolbar 下拉（L170 不截断）列全。
- **根因**：一对多关系的『多』没有一个统一的、一眼可达的列表入口；它散在 4 个截断/需切 tab 的二级位置（架构地图『历史靠 ticker 上下文内联，没有独立 Library 页』印证）。第一个可改位置：卡片研报计数不可点 + onOpen 落点是工作台而非历史。
- **修复方案**：两选一（选 A，成本低收益直接）：A) CoverageCard.tsx 把研报计数文本（L363-371）包成 button，点击 onFocus(ticker) 并让 Inspector 默认切到 history tab（给 CoverageInspector 加 `initialTab` prop，CoveragePage 透传一个 focus+tab 的回调）——一键从『3 份研报』直达全量历史列表。B) AIZone 版本时间线 L1004 的 slice(0,5) 后加一个『查看全部 N 个版本』按钮，点了展开或跳 Inspector。注意 A 里 Inspector 的 tab state 现在是组件内 useState（L64），要支持外部初始值得提升或用 key 重置。量级：中（CoverageCard + CoverageInspector + CoveragePage 三处联动）。
- **验证补充**：Option A is reasonable but note the stated cost is real: CoverageInspector tab state is component-internal useState (L64) — adding initialTab requires lifting it or a key-based remount, and CoveragePage must thread focus+tab through onFocus. 'Medium, 3 files' is honest. Prefer A.
- **影响面/回归风险**：缩短最高频动线（看一支股票攒了哪些历史）。回归面：Inspector tab 默认值改动需确认不破坏现有 live 默认 tab 的测试。
- **置信度**：high　|　**状态**：待修

#### [UX-010] Compare 必须回 Coverage 多选才能发起——workspace/研报页内无"加入对比"入口

- **类别**：产品
- **严重度**：P2
- **位置**：动线环节：ComparePage 入口仅 CoveragePage 批量栏(L249-256)/CoverageInspector(L194)；StockWorkspace & ArtifactDetailPage 无 compare 入口
- **现象/问题**：对比（/compare?tickers=）需要 ≥2 个 ticker，发起点全在 Coverage 页（批量多选栏 + inspector 的 Compare，且 inspector 的 Compare 还依赖页面级 selectedTickers）。用户在看 NVDA 的 workspace 或研报正文时，想"拉 AMD 来对比"，必须先返回 /coverage、勾选两张卡，再点 Compare。一个天然在"读单股"语境里产生的需求，被迫回到列表页用列表交互完成。
- **证据**：ComparePage 的导航全部来自 CoveragePage：handleCompare（L249-256）navigate(`/compare?tickers=`)，由批量栏 BarButton（L326-330，依赖 selectedTickers）和 CoverageInspector onCompare（L392，依赖 focused+selection≥2）触发。CoverageInspector Compare 按钮 L194 `disabled={!compareReady}`，compareReady（CoveragePage L160-163）= `new Set([focusedTicker,...selectedTickers]).size >= 2`——必须先在覆盖墙多选。StockWorkspace（整文件）与 ReportToolbar（L227-250 的动作区）都没有任何 compare 入口。CmdK 的 coverage-compare 命令同样依赖 coverageStore.selectedTickers（CmdKOverlay L544-554），workspace 里那个 selection 通常是空的。
- **根因**：Compare 被实现成"覆盖盘的批量操作"，绑死在 CoveragePage 的 selectedTickers 视图态上，没有一个"以当前 ticker 为锚 + 选一个对手"的轻量入口。第一个出错位置是 compare 的发起完全依赖 coverageStore 的多选态，而该态只在 Coverage 页被填充。
- **修复方案**：在 StockWorkspace 的 TickerHero 动作区（或 AIZone header）加一个"对比…"入口：点开一个轻量 ticker 输入/最近研究 picker（可复用 CmdK 的 /api/search），选定后 navigate(`/compare?tickers=${current},${picked}`)，无需经过 Coverage 多选。同理在 ReportToolbar 动作区（ReportToolbar.tsx L227-250 之间）加一个"对比"按钮走同逻辑。注意：ComparePage 对无 DCF 的 ticker 已诚实显"先跑 DCF"不编数字，新入口拉进来的对手票若无 DCF 会落到该提示，属预期——不要在入口侧硬拦。改动量级：中（一个小 picker 组件 + 两处入口接线，~60 行）。
- **验证补充**：Fix sound. The anchor-+-picker entry (reuse /api/search like CmdK) is the right shape since the existing compareReady gating is coverageStore-only. Honest no-DCF fallback in ComparePage (L1-3 header) means picked peers without DCF land on '先跑 DCF' — correctly left unblocked at the entry side.
- **影响面/回归风险**：影响"读单股时顺手对比"的高频意图。回归风险：低——只新增入口，ComparePage 自身逻辑不动；需确认 picker 的 ticker 校验复用 utils/ticker 的 isValidTicker，避免拼出非法 /compare query。
- **置信度**：high　|　**状态**：待修

#### [UX-011] Coverage Desk（新首页）全程零 hover 反馈，质感跌破全 App 基准线

- **类别**：产品
- **严重度**：P2
- **位置**：ui/src/components/coverage/CoverageCard.tsx:99-393 / CoverageInspector.tsx:150-201,517 / WallHeader.tsx:81-168 / CoverageEmptyState.tsx:83-123
- **现象/问题**：新首页 Coverage Desk 的卡片、Inspector 的 4 个 ActionButton 与 3 个 tab、WallHeader 的分诊段与排序按钮、空状态的热门 chip 与 CTA——全部用 inline style 写成，inline style 物理上无法表达 :hover，且这些组件均无 onMouseEnter/onMouseOver 兜底（grep 确认 coverage 目录除 CoverageGroupMenu 外零 JS hover 处理）。CoverageCard 只在 focused（点击后）时给 border-glow+boxShadow，鼠标悬停时卡片/按钮纹丝不动。
- **证据**：对比基准：App.css 已为 class 化控件写满 hover——.btn:hover(1112)、.btn-shimmer:hover(4891)、.cosmic-card:hover(4841)、.segmented-btn:hover(1217) 等十余条。桌面 App 全局 cursor:none + 发光 dot 光标（CursorCanvas），hover 态是用户判断'这块能点'的首要信号；cosmic 规范第 10 节检查清单明列'卡片有 hover glow、按钮有合法动效'、5.2 节要求 active 发光。用户场景：分析师把光标移到一张覆盖卡或 ▶ 跑研报按钮上，没有任何边框提亮/背景变化，无法确认这是可点的控件还是静态展示——而隔壁 StockWorkspace 的同类按钮都会亮。新首页因此显著比旧页面'糙'。
- **根因**：Coverage Desk 改版（2026-06-01）整套用 inline style 重写，绕过了已有的 .cosmic-card/.btn class 体系，导致这批 class 上沉淀的 hover/focus 视觉全部丢失。第一个出错点是 CoverageCard.tsx:104 起的 article inline style 块没有任何 hover 路径，且未复用 .cosmic-card class。
- **修复方案**：两种改法择一（推荐 A）。A（中等改动量，~6 文件）：给 CoverageCard 的 <article> 加 className='cosmic-card'（它已带 ::before 顶部发光线 + :hover border 提亮），inline style 只保留布局/floor，颜色边框交给 class；CoverageInspector 的 ActionButton、WallHeader 的分诊/排序按钮、tab 按钮、空状态 chip 改用已有 .btn/.segmented-btn class 或新增一条 .coverage-pill:hover{border-color:var(--border-glow)}。B（轻量，纯 hover）：在 App.css 加 [data-testid^='coverage-card']:hover{border-color:var(--border-glow);box-shadow:0 8px 32px var(--primary-soft)} + 给 IconButton/ActionButton 一个 className 挂 :hover。注意：CoverageCard 用 focused 复用了 border-glow，hover 态须用更弱的提示（如仅 border 不加 boxShadow）以免 hover 与 focused 视觉撞车。
- **验证补充**：Fix A is NOT drop-in: .cosmic-card sets border:1px solid var(--border-soft) and padding:24px, but CoverageCard already sets border, background, borderRadius, padding INLINE — inline wins over class, so .cosmic-card:hover's border-color change won't apply while an inline `border` is present (the hover rule only sets border-color, which inline border shorthand overrides). Adding className='cosmic-card' alone yields NO hover effect. Must remove the inline border from the card and let the class own it (keeping the focused/needsWarn variants via a data-attr or extra class). Fix B (a dedicated [data-testid^='coverage-card']:hover rule in App.css) is actually the cleaner path and avoids the padding/border collision; recommend B over A. Keep hover weaker than focused (border only, no boxShadow) as author noted — correct.
- **影响面/回归风险**：纯视觉/可发现性提升，无逻辑回归；唯一风险是 hover 与 focused/selected 三态颜色叠加要排好优先级（focused>hover>default），测试用例只看快照不看 hover 故不会破测。
- **置信度**：high　|　**状态**：待修

#### [UX-012] Coverage Inspector 的 Live/Report 面板丢失溯源——同一数字在卡上可溯、点进去不可溯

- **类别**：产品
- **严重度**：P2
- **位置**：ui/src/components/coverage/CoverageInspector.tsx:239-313（LivePanel/ReportPanel 的 Kv 值）
- **现象/问题**：Inspector 是'聚焦单标的深看'的地方，但其 LivePanel 的 price/market_cap 和 ReportPanel 的 entry_price/target_price/upside 全部用裸 formatCurrency/formatPercent 直出，没包 SourcedNumber。而同一行数据在 CoverageCard 上（CoverageCard.tsx:194-288）每个数字都过 SourcedNumber——带 provider/fetched_at 溯源 popover + 口径不符的 amber 内联告警。结果：用户在卡片上能 hover 看到'这个价来自 FMP，3 分钟前'，点进 Inspector 想细看反而看不到溯源了。
- **证据**：CoverageCard 对 price/market_cap/revenue_ttm/multiple/upside 五个数字逐个 <SourcedNumber source={row.sources?.x}>；CoverageInspector LivePanel 第 239/246 行 formatCurrency(row.price...)/formatCompactNumber(row.market_cap) 是纯文本，ReportPanel 299/302/308 同理。row.sources 数据是现成的（卡片在用），Inspector 只是没接。这违背项目头号卖点'数字可溯源'（cosmic 规范 9 节'数字溯源必须可见'、CLAUDE.md 数据正确性），且方向反了——越往深看溯源越该在，现在越深越没有。
- **根因**：Inspector 用了自己的轻量 Kv 原语（CoverageInspector.tsx:470 Kv），children 直接收格式化字符串，没走 SourcedNumber 包裹；第一个出错位置是 LivePanel:239 起把值当纯字符串塞进 Kv。
- **修复方案**：在 LivePanel/ReportPanel 里把 price/market_cap/entry_price/target_price/upside 的值改成 <SourcedNumber value={row.x} source={row.sources?.x ?? undefined} ticker={row.ticker} format={...}>，与 CoverageCard 用法对齐（已 import 路径现成）。Kv 的 children 已是 ReactNode 可直接收 SourcedNumber，无需改 Kv。注意 upside/1D 这类百分比用 formatPercent 作 format 回调；market state 行不需要溯源（它是派生标签不是 provider 数字）。
- **验证补充**：Fix is correct and low-risk (Kv children is ReactNode, SourcedNumber drops in). Two refinements: (1) market_cap on the card uses source row.sources?.market_cap — reuse the SAME source key in Inspector, don't invent. (2) Author correctly notes market-state row is a derived label (not a provider number) and must NOT be wrapped — keep that exclusion. provider/as_of/currency Kv rows are also metadata, not numbers — leave them bare.
- **影响面/回归风险**：提升核心卖点一致性，纯展示层、无计算回归；改动局限在 CoverageInspector 两个 Panel，约 6 个 Kv。风险极低。
- **置信度**：high　|　**状态**：待修

#### [UX-013] `/api/dashboard/hit-rate` + useDashboardHitRate are orphaned after the homepage declutter — track-record panel has no live caller

- **类别**：产品
- **严重度**：P2
- **位置**：ui/src/hooks/useDashboardHitRate.ts (no live importer) + finrobot/routes/dashboard.py:142 endpoint
- **现象/问题**：After 'declutter homepage IA — kill the toolbar' (commit a01bfe4), nothing renders the hit-rate banner: `useDashboardHitRate` is referenced only in comments (AiChatTab.tsx:278, StockWorkspace.tsx:73) — zero live callers. The cross-ticker hit-rate — the single most differentiating 'does this product's calls actually work' statistic for an analyst/quant — is computed by the backend (and pays a cold quote fetch, dashboard.py:283) but surfaced nowhere.
- **证据**：`grep -rn 'useDashboardHitRate\b' ui/src --include=*.tsx --include=*.ts` minus the definition file and comment lines → empty. CoverageHero.tsx:5 comment confirms 'no hit-rate banner ... those lived in the old [home]'. The endpoint, hook, aggregation module, and is_sampled machinery are all live code with no consumer.
- **根因**：Homepage IA rewrite removed the banner host component without re-homing the track-record panel; the hook+endpoint were left in place but disconnected.
- **修复方案**：Decide and act (don't leave dead): EITHER (a) re-home the panel — render the scoped hit-rate on the Coverage group detail view and/or per-ticker workspace header (the scoping param exists for exactly this), wiring useDashboardHitRate with the group's tickers; OR (b) if the track-record panel is intentionally retired, delete the hook, the two dashboard routes' hit-rate path is still used? — verify and remove the orphaned hook + is_sampled fields. Recommend (a): the track record is the product's credibility proof for the target user. Note: fixing the two correctness bugs above is prerequisite for (a). Change size: medium (one panel component + placement) for (a); small for (b).
- **验证补充**：Recommendation (a) re-home on the Coverage group detail / per-ticker workspace header is sound and the tickers scoping param exists for exactly this. Prerequisite chain is correct: [0] and [1] must be fixed before (a) or scoped groups silently show null and an undisclosed sampled stat. If (b) delete is chosen, also remove the aggregation module's now-unused path and the is_sampled fields. /recent-research is a separate live endpoint and must NOT be removed.
- **影响面/回归风险**：—
- **置信度**：high　|　**状态**：待修

#### [UX-014] 首屏产品身份分裂：populated 态顶 FINROBOT 大字、empty 态顶 Coverage Desk，同一页两套品牌/心智

- **类别**：产品
- **严重度**：P2
- **位置**：ui/src/components/coverage/CoverageHero.tsx:102 (FINROBOT 40px) vs ui/src/components/coverage/CoverageEmptyState.tsx:56 ("Coverage Desk" 28px 硬编码英文)
- **现象/问题**：同一个 /coverage 路由，有数据时顶部是 CoverageHero 的『FINROBOT』40px 渐变大字 + morphing tagline（获客 hero 姿态）；零数据时整页换成 CoverageEmptyState 的『Coverage Desk』28px 标题（运营台姿态）。两个标题、两种字号、两种心智，用户在『加第一支股票』前后看到的是两个不同产品的首页。且『Coverage Desk』是 line 56 写死的英文字面量，未走 i18n（其余文案都走 t()），中文 locale 下这块不翻译。
- **证据**：CoverageEmptyState.tsx:47-57 `<h1>Coverage Desk</h1>` 字面量，非 t() 调用；同文件其它文案（subtitle/cta/steps）全走 t()。CoverageHero.tsx:102 `FINROBOT` 渐变 40px。两者在 groups 是否为空时互斥出现于同一路由顶部。
- **根因**：CoverageEmptyState 是改版较早落地的组件，标题自带一套；CoverageHero 是后来从退役的 /stocks landing 搬回来的，带回了 FINROBOT 品牌字。两者没统一首屏标识，且空态标题漏了 i18n。
- **修复方案**：统一首屏标识：让空态复用 CoverageHero 的标题块（或反之），二选一保留一套品牌字号。最小修正：CoverageEmptyState.tsx:56 的『Coverage Desk』改为走 t()（新增 coverage.starter.title 键，zh/en 两份），并与 Hero 的视觉层级对齐。若采纳 finding#4 的『空态=放大 Hero』方案，本问题自然消解（空态直接用 CoverageHero）。注意硬编码英文违反项目 i18n 约定。改动量：低（接 finding#4 则 0 额外成本；独立修则 ~1 键 + 1 行）。
- **验证补充**：Minimal correct fix: add coverage.starter.title (zh/en) and route line 56 through t(). The 'unify brand identity' part is optional polish, not a bug — don't conflate. If #3 is adopted (empty state → Hero), this dissolves for free. P3, not P2.
- **影响面/回归风险**：影响首屏一致性观感。回归风险极低。建议与 finding#4 合并处理。
- **置信度**：high　|　**状态**：待修

#### [UX-015] 最高曝光的 Run CTA / Pipeline 徽章用字面量 color:'white' 与裸数字圆角，绕过已存在的 token

- **类别**：产品
- **严重度**：P3
- **位置**：ui/src/views/workspace/AIZone.tsx:699,888 / views/PipelineProgressPanel.tsx:187 / AIZone.tsx:674,698(borderRadius:10)
- **现象/问题**：全 App 最重的主 CTA『跑研报』按钮（AIZone RunCta）填色用 color:'white' 字面量，而项目早有 --text-on-primary（App.css:26，注释明写'legible text on the primary/secondary gradient fill'就是为这个场景准备的）。同处 borderRadius:10 写裸数字而非 var(--radius-md)。PipelineProgressPanel:187 同样 color:'white'。
- **证据**：grep 全仓 views/components 非 test 仅 3 处 color:'white'（AIZone:699/888、PipelineProgressPanel:187），全在 gradient 填充的 CTA/徽章上——恰好是 --text-on-primary 的目标用例。cosmic 规范第 10 节检查清单第一条:'所有颜色来自 CSS Variables，没有硬编码 hex'；字面量 'white' 同属违规。虽然 white≈--text-on-primary(#ffffff) 当前视觉无差，但破坏了'恢复 light 主题时纯靠 token 推导'的不变量（规范第 2.76 节明述该承诺）。
- **根因**：改 RunCta/Pipeline 时图省事直接写 'white'/10，没查已有 token。第一个出错位置 AIZone.tsx:699。
- **修复方案**：AIZone.tsx:699/888、PipelineProgressPanel.tsx:187 的 color:'white' → 'var(--text-on-primary)'；AIZone.tsx:674/698 的 borderRadius:10 → 'var(--radius-md)'。注意 PipelineProgressPanel:187 那处若文字压在动态进度色上，确认 --text-on-primary 在该背景下对比度仍足（pipeline 用 primary/secondary gradient，足够）。
- **验证补充**：Fix is correct and safe. Minor: verify --radius-md actually equals 10 (or whatever the design intends) before swapping borderRadius:10 → var(--radius-md); if the token is e.g. 8 or 12, the swap silently changes the visual. Confirm token value first, else it's a stealth restyle.
- **影响面/回归风险**：零视觉变化、零逻辑回归，纯 token 卫生；唯一价值是守住'零硬编码颜色'不变量，避免下次有人 grep 'no hardcoded color' 时漏网繁殖。
- **置信度**：high　|　**状态**：待修

#### [UX-016] prefers-reduced-motion 只关了星空一种动效，shimmer/pulse/halo/skeleton 等仍全速运行

- **类别**：产品
- **严重度**：P3
- **位置**：ui/src/App.css:4792-4797（唯一 reduced-motion 块）
- **现象/问题**：全 App 唯一的 @media(prefers-reduced-motion:reduce) 块只把 .cosmic-stars 的 animation 设 none。其余 24 个 @keyframes——skeleton 的 shimmer(无限循环,2100)、pulse-ring(565)、pulse-dot、halo、btn-shimmer、toast-in、check-pop、ask-bounce、status-pulse、cosmic-morph(CoverageHero tagline,12s 无限)——在用户声明'减少动效'后照常跑。CursorCanvas.tsx:19-23 正确读了 matchMedia 关掉拖尾，CSS 侧却没跟上。
- **证据**：grep 全仓 reduced-motion 只命中 App.css(2 处,实为同一块)+ uiStore + CursorCanvas + 生成的 viewer.css。25 个 keyframes 中仅 cosmic-stars 被 gate。对前庭敏感/晕动症用户（金融分析师长时间盯屏是高发人群），满屏 skeleton 流光 + tagline 循环 morph + pulse 呼吸点在'已请求静止'时仍动，是体贴度缺口，也是桌面 App 上架无障碍审查会被点的项。
- **根因**：reduced-motion 支持只做了星空一处试点没铺开；第一个出错位置 App.css:4792 该 @media 块的选择器列表只有 .cosmic-stars。
- **修复方案**：在 App.css 扩一个全局 reduced-motion 兜底块：@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}} 再保留对 .cosmic-stars 的显式 none。注意：① 不要把它写在文件早处被后续规则覆盖，放末尾；② skeleton 关动画后要确保静态态仍有可辨底色（.skeleton 背景是 gradient，静止时给个中间色 background-position 即可，否则一片纯色看不出在加载）——这点要手验一次 loading 态截图。
- **验证补充**：Global wildcard *{animation-duration:.01ms!important;...} is the standard pattern and fine, but the author's own caveat is the real risk: .skeleton uses an animated gradient to read as 'loading'; killing the animation can leave a flat near-invisible block. Must set an explicit static visible background for .skeleton inside the reduced-motion block (not rely on background-position of a paused gradient), and visually verify a loading-state screenshot. Place block at end of file to avoid override. Otherwise correct.
- **影响面/回归风险**：无障碍/体贴度提升；风险点是 !important 全局压制可能误伤某个真正需要动的功能态（如 pipeline 进度条 width 过渡）——width transition 属信息性非装饰，可在该块用更克制的写法或给进度条加豁免 class。建议改完用 Playwright 在 emulateMedia reduced-motion 下截一张 loading + 一张 pipeline running 自验。
- **置信度**：high　|　**状态**：待修

#### [UX-017] 右侧 AI 抽屉与 CmdK 的 "Ask AI" 是两条并存的对话入口，语义重叠且互不打通

- **类别**：产品
- **严重度**：P3
- **位置**：动线环节：CmdKOverlay.tsx:512-523（Ask-AI fallback → uiStore.sendChatPrompt）vs RightChatPanel（⌘L 抽屉，独立 useChat）
- **现象/问题**：用户有两个发起 AI 对话的口：⌘L 打开的右侧抽屉（RightChatPanel，常驻、带 ContextBar 上下文绑定），和 ⌘K 搜索零结果时的"Ask AI"fallback（把 free-text 通过 uiStore.pendingChatPrompt 转交给抽屉）。两者最终都进同一个抽屉，但用户心智里这是两个"问 AI"的地方，且 CmdK 的 Ask AI 只在"搜索无结果"时才出现，发现路径绕。对"我就想问个问题"的用户，先打 ⌘K、打字、看到无结果、才出现 Ask AI，比直接 ⌘L 多了一层。
- **证据**：CmdKOverlay handleAIFallback L512-523 `useUiStore.getState().sendChatPrompt(text, true)`，注释说明它复用抽屉的 pendingChatPrompt 通道。showAiFallback（L612）`= !isLoading && debouncedQuery.length>0 && !hasRemoteResults`——只在有 query 且无远程结果时显示。AppShell L23-31 ⌘L toggleAiPanel 是另一条独立入口，RightChatPanel 用自己的 useChat。两条路通向同一抽屉但触发条件/可发现性完全不同。
- **根因**：CmdK 既是"导航/搜索"又兼"AI 兜底"，与专职 AI 抽屉职责重叠。Ask-AI 被设计成"搜索失败的安慰奖"而非"一等提问入口"，导致它藏在零结果态后面。属信息架构层的轻度冗余，非 bug。
- **修复方案**：两选一（建议 A）：A) 让 CmdK 的 Ask-AI 成为常驻一等项——query 非空时始终在列表底部显示"问 AI：<query>"（去掉 `!hasRemoteResults` 限制，改为始终可选，CmdKOverlay L612），这样"搜"和"问"在同一面板平权，用户不必先看到失败。B) 反向收敛：去掉 CmdK 的 AI fallback，在空结果区只放一句"按 ⌘L 问 AI"提示，把提问唯一化到抽屉。选 A：CmdK 已是全局命令面，让它直接承接提问比教用户记两个快捷键好。注意：sendChatPrompt 已会自动展开抽屉，A 不需要新通道。改动量级：小（改 showAiFallback 条件 + 文案，~10 行）。
- **验证补充**：Fix A (drop !hasRemoteResults so 'Ask AI: <query>' is always offered when query non-empty, CmdKOverlay L612) is low-risk: sendChatPrompt already auto-opens the drawer (L520, no new channel). Reasonable. P3 severity is appropriate — pure polish, not blocking.
- **影响面/回归风险**：影响"提问"这一高频动作的入口清晰度。回归风险：低——若选 A，需确认 query 同时有远程结果时 Ask-AI 项排在结果之后不抢焦点（cmdk loop 选中顺序）。
- **置信度**：medium　|　**状态**：待修

---

## 三、机会清单（让产品惊艳的高杠杆项）

| ID | 类别 | 价值/成本 | 一句话 | 状态 |
|---|---|---|---|---|
| OPP-001 | 机会 | 高价值·低成本 | 有 ≤60 字 tagline 和整套 Recharts 图,却没有一键'分享卡/截图/复制结论'——KPI 是 Stars 却缺病毒式产物 | 待评估 |
| OPP-002 | 机会 | 高价值·中成本 | 两个「IC」功能撞名:持久化的 ic-memo 流水线全 UI 不可达,桌面端唯一的「投委会」按钮跑的是用完即焚的 /api/debate | 待评估 |
| OPP-003 | 机会 | 高价值·中成本 | Compare 页让用户『先跑 DCF』,但整个桌面端没有任何地方能跑 DCF/LBO/comps——只有 research 一种流水线可被用户启动 | 待评估 |
| OPP-004 | 机会 | 高价值·中成本 | Bull/Base/Bear 情景建模 state 已建好却完全悬空——把死代码激活成分析师真正想要的 wow | 待评估 |
| OPP-005 | 机会 | 高价值·中成本 | 把 valuation_overview/competitor_analysis 从'LLM 复述数字'重构为'code 拼确定性数字行 + LLM 只写定性 why'，从结构上根除散文印错数 | 待评估 |
| OPP-006 | 机会 | 高价值·中成本 | DCF/LBO/comps 等模型产物有版本切换但没有版本对比——semantic_diff 后端已完整支持 dcf/ic_memo，前端只给了 equity_research | 待评估 |
| OPP-007 | 机会 | 高价值·中成本 | 研报↔投委会入口不对称:verdict 出现的两个主力面(AIZone 热卡 + CoverageInspector)都没有『质疑/IC』入口,唯一入口埋在三级页 toolbar | 待评估 |
| OPP-008 | 机会 | 高价值·中成本 | Coverage Desk 缺键盘巡航是把『投行级研究台』降格为『鼠标 demo』——补一套 j/k+方向键 roving 让分析师不离键操作整面分诊墙 | 待评估 |
| OPP-009 | 机会 | 高价值·中成本 | Make the loopback-only trust model explicit and self-defending: TrustedHost + a sidecar capability token shipped as one auth seam | 待评估 |
| OPP-010 | 机会 | 中价值·低成本 | Centralize secret redaction at every persistence boundary instead of per-provider string hygiene | 待评估 |
| OPP-011 | 机会 | 中价值·低成本 | SourcedNumber 的'每个数字可溯源'是真差异化,却只活在报告内页,冷启动/落地从没把它当卖点亮出来 | 待评估 |
| OPP-012 | 机会 | 中价值·低成本 | CLI 缺统一错误网关：每条命令各自(不)处理异常,体验碎片化 | 待评估 |
| OPP-013 | 机会 | 中价值·低成本 | list_versions(limit=1000) 是零调用方死代码，且与真实生效的 timeline(limit=50) 形成第二条版本读取路径 | 待评估 |
| OPP-014 | 机会 | 中价值·低成本 | 正则从自由文本抠出的 ceo_name/comp/ratio 与确定性计算数字同权威落地(带完整 DEF 14A provenance),无 confidence/heuristic 标志,读者无法区分脆弱抓取与可信计算 | 待评估 |
| OPP-015 | 机会 | 中价值·中成本 | 报告里的数字/章节没有'就这个问 AI'的行内入口——代码兜底数字 + LLM 叙事的组合拳没打满 | 待评估 |
| OPP-016 | 机会 | 中价值·中成本 | Session transcripts grow unbounded forever — no retention/rotation/size cap, full payloads written verbatim | 待评估 |
| OPP-017 | 机会 | 中价值·中成本 | 7 个独立 db 无统一备份/完整性校验/迁移框架——研究资产无安全网 | 待评估 |
| OPP-018 | 机会 | 中价值·中成本 | TTM 组成季的 per-quarter provenance(component_provenance)已建模但从未填充 | 待评估 |
| OPP-019 | 机会 | 中价值·中成本 | SSE 三 store（runStream/debate + 各自模块级 EventSource Map）重复实现连接/重连/8-error 兜底 | 待评估 |
| OPP-020 | 机会 | 低价值·低成本 | emoji 图标（🤖 AI NARRATIVE / ⚠ CTA）与 ▶↗▲▼ 字形按钮，违背 inline-SVG 图标语言、跨平台渲染不一致 | 待评估 |
| OPP-021 | 机会 | 中价值·高成本 | Pipeline 步骤声明仍是命令式逐条 PipelineStep，可升级为可校验的声明式 DAG/契约 | 待评估 |
| OPP-022 | 机会 | 低价值·中成本 | cross_tickers 仅存 JSON 列无索引无查询路径，peer 维度的『股票↔研报』一对多关联不可逆查 | 待评估 |

### 详细条目（机会）

#### [OPP-001] 有 ≤60 字 tagline 和整套 Recharts 图,却没有一键'分享卡/截图/复制结论'——KPI 是 Stars 却缺病毒式产物

- **类别**：机会
- **价值/成本**：高价值·低成本
- **位置**：动线环节 5(读研报)+ ui/src/pages/artifact-detail/shell/ReportToolbar.tsx:225-235(唯一导出=整页 HTML)+ ui/src/views/workspace/AIZone.tsx:847-863(tagline 已渲染但只展示)
- **现象/问题**：项目 KPI 明确是 GitHub Stars,而最能驱动自传播的'一眼结论 + 好看的图'目前没有任何轻量分享出口。后端专门写了 summary_extractor.extract_tagline 产出一句 ≤60 字可分享结论(schema.d.ts:1170 注释明说'shareable conclusion'),前端 AIZone 也把它渲染成漂亮的 cyan 斜体——但到此为止:没有'复制这句结论'、没有'生成分享图(verdict + 目标价 + tagline + football field)'、没有'复制 Markdown 摘要'。唯一的导出是 ReportToolbar 的整页 HTML(几百 KB 自包含文件),太重、不适合贴推/贴群/截图发圈。
- **证据**：ReportToolbar.tsx 只有一个 onExportHtml;全仓 grep navigator.share/toPng/html2canvas/copy-to-clipboard/shareCard 在非测试代码中无任何分享/截图/复制结论实现(仅 WaterfallChart 注释里提到 screenshot)。tagline 字段存在且已渲染(AIZone.tsx:851)但无任何复制/导出按钮挂在它上面。项目已装 Recharts 且有 FootballField/SensitivityHeatmap/CompanyRadarChart 等成品图,做一张分享图的素材齐备。
- **依据/现状**：导出路径只设计了'给自己存档'(整页 HTML),没设计'给别人看/自传播'这条;tagline 当成展示文案而非可分享 primitive。
- **落地方案**：加一个轻量'分享'入口(报告 toolbar 或 HotState 卡):最小版=复制一段 Markdown(ticker · verdict · 12M target · tagline · 报告链接)到剪贴板(navigator.clipboard,0 依赖);进阶版=用已装 Recharts/已有 FootballField 渲染一张 1200×630 OG 卡(verdict 大徽章 + 目标价 + tagline + 估值横条),用 dom-to-image/canvas 导出 PNG。注意:分享图里的数字必须直接取 artifact 冻结值(verdict/target_price/tagline 都在 ArtifactSummaryV5 上),不得重算;带上'代码兜底·可溯源'水印呼应定位。量级:复制版 ~30 行;PNG 卡片版 ~1 个组件 + 1 个 png 库(中)。
- **验证补充**：Minor factual nit: tagline is authored by the equity_research pipeline prompt (equity_research.py:805) and stored on the model; schema attributes population to summary_extractor.extract_tagline. Doesn't affect the finding. Severity P2 not P1 — it's a net-new feature, not a defect blocking users; but high strategic value given Stars KPI.
- **影响面/回归风险**：直接服务 Stars KPI——分析师把一张带 FinRobot 水印的可溯源结论图发出去,就是免费获客;复制版几乎零成本先上。回归面:纯新增,不动现有 HTML 导出与数据,无风险。
- **置信度**：high　|　**状态**：待评估

#### [OPP-002] 两个「IC」功能撞名:持久化的 ic-memo 流水线全 UI 不可达,桌面端唯一的「投委会」按钮跑的是用完即焚的 /api/debate

- **类别**：机会
- **价值/成本**：高价值·中成本
- **位置**：finrobot/engine/pipelines/registry.py:42 ↔ finrobot/routes/debate.py + ui/src/pages/artifact-detail/shell/ReportToolbar.tsx:240-250  ·  （另涉：动线环节 6(IC 投委会):finrobot/engine/pipelines/ic_memo.py(已注册 'ic-memo',builds 持久 ic_memo artifact)vs finrobot/routes/debate.py(/api/debate,SSE 流,不落盘)+ ui/src/pages/ic/IcDebatePage.tsx:12-18(EphemeralNotice) ; ui/src/pages/ic/IcDebatePage.tsx:12-18,155-157 + ui/src/stores/debateStore.ts(无持久层) + finrobot/routes/debate.py:87(create_run 但不 save artifact) ; 动线环节：ReportToolbar.tsx:240-250（唯一入口）→ IcDebatePage.tsx:12-18（不持久化）；CoverageInspector 无 IC 动作）
- **现象/问题**：代码里有两个几乎同名的 IC 能力,但桌面端只暴露了价值较低的那个,价值高的那个完全够不到。(1) ic-memo 是一条完整注册的流水线(registry.py:42 "ic-memo"→create_ic_memo_pipeline;builders.py:465 build_ic_memo_artifact 产出 type="ic_memo" 含 dcf_result+lbo_result;orchestrator.py:150 注册为 run_ic_memo tool;cli.py:381 与 sdk.py:203 都有入口),它产出的 artifact 带 verdict,会被 coverage 卡片当研报计数与采信(service.py:83 _DCF_BEARING_TYPES 含 ic_memo、service.py:234 verdict 取数含 ic_memo)。(2) 而桌面端唯一带「⚖ 投委会/IC Debate」字样的按钮(ReportToolbar:240)跳 /ic/:ticker,跑的是 debate.py 的 bull/bear 流式辩论——明确不落 artifact、刷新即失(IcDebatePage:12-18 + EphemeralNotice)。结果:真正能沉淀进研报体系的 ic_memo 备忘录,用户在 App 里没有任何按钮能生成(只能命令行 finrobot ic-memo)。
- **证据**：registry.py:35-43 工厂表含 "ic-memo";全仓 grep startRun 的 literal pipeline 实参只有 AIZone.tsx:181 'research' 与 ReportToolbar.tsx:81(仅当你已在看一个 ic_memo artifact 时 re-run 才会传 'ic-memo',而该 artifact 本身只能 CLI 产生 → 循环不可达);useBatchRun 默认 'research',CoveragePage.handleRun 也只传默认。AIZone.tsx:33 与 CompactArtifactViewer.tsx:227 都已为 ic_memo 预留展示标签『投委会备忘录』,即展示侧已就绪、生产侧无入口。佐证:runStreamStore.ts:105 给 'ic-memo' 写的步骤名 ['data_collection','financial_analysis','memo_drafting','report'] 与真实流水线 ic_memo.py:177-210 的 5 步 ['situation_overview','financial_analysis','investment_thesis','risk_factors','recommendation'] 对不上——正因从没真跑过,漂移一直没被发现。
- **依据/现状**：两条 IC 线独立演进、命名几乎相同(ic-memo 流水线 vs IC debate),桌面端在 ReportToolbar 只接了 debate 一条,ic-memo 流水线停留在 CLI/SDK/orchestrator 层从未在前端开 run 入口;PipelineType 枚举(appStore.ts:11)虽含 'ic-memo' 但无 UI 调用方。
- **落地方案**：先定语义边界(需 boss 拍板二选一):方案A『debate 即 ic-memo 的生成器』——让 _run_debate_task(debate.py:147)在 run_debate 成功后调用 build_ic_memo_artifact 把 verdict+bull/bear 落成 ic_memo artifact 并 artifact_store.save(),IcDebatePage 去掉 EphemeralNotice、完成后导航到 /stocks/:ticker/runs/:newId;这样『投委会』按钮既辩论又沉淀,ic-memo 流水线退役合并(删 registry.py:42 那行 + cli/sdk ic_memo 入口,约 -150 行死代码)。方案B『两者都留』——则必须在 UI 给 ic-memo 流水线一个 run 入口(见下条 P1 的 pipeline 选择器),并把两个功能改成不同文案(debate=『多空辩论』,ic-memo=『投委会备忘录』)消除撞名。注意:改前先跑 grep 确认 ic_memo artifact 在 valuation.py:161/208、semantic_diff.py、coverage service 的所有读取点都还兼容(方案A 新产的 ic_memo 结构需与 build_ic_memo_artifact 一致)。改动量级:方案A 中(跨 debate.py + IcDebatePage + 删 3 处 CLI/SDK 入口);属架构级,标 [需确认] 由 boss 选 A/B。
- **验证补充**：Finding correctly flags this as [需确认] for boss A/B. One correction to method: this should be merged with [1] as a single decision (debate-persists-as-ic_memo vs keep-both), not decided in isolation. Also the claimed '-150 lines dead code' for retiring ic-memo is optimistic — ic_memo.py has bespoke executors (_execute_ic_financials, _execute_recommendation) and validators that debate's evidence-set path does not produce, so method A is not a clean delete.
- **影响面/回归风险**：影响 debate 路由、IcDebatePage、coverage 卡片采信逻辑。回归风险:方案A 会让 debate run 开始写 artifacts.db,需确认 coverage _DCF_BEARING_TYPES/verdict 读取对新 ic_memo 兼容(已含 ic_memo,低风险);若选 A 务必同步 runStreamStore.ts:105 步名或直接删该条。
- **合并自**：opp-linkage#1, opp-wow#2, opp-linkage#2, ux-IA-simplify#5（4 条同源发现）
- **置信度**：high　|　**状态**：待评估

#### [OPP-003] Compare 页让用户『先跑 DCF』,但整个桌面端没有任何地方能跑 DCF/LBO/comps——只有 research 一种流水线可被用户启动

- **类别**：机会
- **价值/成本**：高价值·中成本
- **位置**：ui/src/pages/ComparePage.tsx + finrobot/coverage/service.py:546(无 DCF 时返回错误文案)+ ui/src/pages/CoveragePage.tsx:215 / ui/src/views/workspace/AIZone.tsx:181(唯一两个 run 启动点都硬编码 'research')
- **现象/问题**：Compare 后端需要每个 ticker 有 DCF artifact(_compare_one:544),缺了就回填错误『尚未运行 DCF——先对该 ticker 运行 DCF 再对比』(service.py:546),前端原样显示(ComparePage:101-104)。但桌面端没有任何按钮能启动 DCF/LBO/DDM/comps/earnings/ic-memo 流水线——这些工厂都注册在 registry.py 却只有 CLI/SDK 入口。用户被指示去做一件 App 里做不到的事,Compare 对一个『只跑过 research 没单独跑过 DCF』的 ticker 永远是死路(注:research 报告内嵌 DCF 会被 _DCF_BEARING_TYPES 捞到,所以跑过 research 的能比;但 Compare 文案与 cold ticker 体验仍是断的)。
- **证据**：grep 全仓 startRun literal 与 batchRun 调用:AIZone.tsx:181 'research'、CoveragePage handleRun 走 useBatchRun 默认 'research'(api/coverage.ts:189 default)、ReportToolbar.tsx:81 仅在已有该类型 artifact 时 re-run。useBatchRun(useCoverage.ts:155)与 batchRun(coverage.ts:189)明确支持 pipelineType 形参,后端 BatchRunRequest.pipeline_type(coverage.py:125)也接受任意 registry key,但无一个 UI 调用方传非 'research' 值 → dcf/lbo/comps/ddm/earnings/ic-memo 全部 UI 不可启动。
- **依据/现状**：批跑/单跑 UI 在 round-3 IA 精简时只保留了『跑研报』单一动作(CoveragePage 注释『triage queue IS the homepage』),把多 pipeline 选择能力留在了后端契约里没接;Compare 的『run DCF first』文案是从有多 pipeline 入口的旧版继承下来的,入口砍了文案没改。
- **落地方案**：两选一:(简,优先)既然 research 报告内嵌 DCF 已能喂 Compare,把 service.py:546 与 ComparePage 的『先跑 DCF』改成『先跑研报/AI 分析』并在该 cell 直接给一个『→跑研报』按钮(navigate /stocks/:ticker 或直接 batchRun([ticker],'research')),让死路变成一键补齐——约 30 行。(全,根治)在 Coverage 批量栏 + CoverageInspector 给一个 pipeline 选择(research/dcf/lbo/comps/…)下拉,handleRun/handleCompare 透传 pipelineType 到已支持的 useBatchRun;这同时解决上面 ic-memo 无 run 入口。注意:选择器要按 registry key 命名(kebab 'ic-memo' 而非 artifact type 'ic_memo',见 coverage.py:119-123 BUG-049 教训);PIPELINE_STEP_NAMES(runStreamStore.ts:105)要校对每条 pipeline 真实步名(ic-memo 当前是错的)。改动量级:简版小、全版中。
- **验证补充**：The simple fix (rewrite the error/cell to '先跑研报/AI 分析' + a one-click →跑研报 button) is sound and the highest-leverage low-cost move. The full fix (pipeline dropdown) is also valid but note the finding's own caveat is correct and load-bearing: the selector MUST use kebab registry keys ('ic-memo') not artifact types ('ic_memo') per coverage.py:119-123 BUG-049, AND PIPELINE_STEP_NAMES in runStreamStore.ts:105 must be corrected (the ic-memo entry is currently wrong, 4 vs 5 steps) or newly-exposed pipelines render broken progress.
- **影响面/回归风险**：简版只动 Compare 文案+一个按钮,风险极低。全版触及 Coverage 批跑 UI + runStreamStore 步名镜像,需逐 pipeline 核对步名否则进度条错乱。
- **置信度**：high　|　**状态**：待评估

#### [OPP-004] Bull/Base/Bear 情景建模 state 已建好却完全悬空——把死代码激活成分析师真正想要的 wow

- **类别**：机会
- **价值/成本**：高价值·中成本
- **位置**：ui/src/stores/appStore.ts:278-318 (Scenarios/ScenarioResults/activeScenario) + ui/src/pages/artifact-detail/shell/ReportRightRail.tsx:150-278 (WhatIfEditor 只做单点滑块)
- **现象/问题**：appStore 里有一整套 base/bull/bear 三情景建模 state(Scenarios / ScenarioResults / activeScenario + setActiveScenario/setScenarioInputs/setScenarioResult),但 grep 全仓 setter/state 在 appStore.ts 之外的引用数=0,useAppStore 的非测试消费者只有 TitleBar 和 CmdKOverlay(命令面板)。三情景建模完全是死 state。与此同时,报告右栏 WhatIfEditor 自己重新实现了一个一次性单点滑块(WACC/TG/growth 三杆 → BASE→NEW 一个 delta),无法保存、无法并排看 bull vs bear。对买方分析师,'同一个 DCF 出三套情景的目标价'正是 Excel 的核心动作,也正是'代码兜底 + 可溯源'最该炫的地方。
- **证据**：grep 'setActiveScenario|setScenarioInputs|setScenarioResult|activeScenario' 排除 appStore.ts 与 test 后命中 0 行;report 代码只 import 类型(DCFResult/CompsResult)不碰情景 state。后端 /api/compute/artifacts/{id}/what-if/dcf 已经接受 wacc_override/tg_override/growth_scale_override 三杆(ReportRightRail.tsx:28-33,41-59)——正好是 bull/base/bear 预设需要的全部输入,且回放冻结 DCFInputs 保证三情景口径一致、delta 只归因于假设而非数据漂移。
- **依据/现状**：情景 state 是更早 workspace 版本的遗留,Coverage/报告分页重构时 WhatIfEditor 走了独立的一次性路径,情景 store 没接线也没删——典型路径分裂 + 死代码。
- **落地方案**：两条路选一条(推荐 A):A) 激活——把 WhatIfEditor 升级成三标签(BEAR/BASE/BULL),每个标签存一组 {wacc,tg,growth} 预设(bear/base/bull 可给保守-15%growth/+2%WACC 等默认偏移),并排 POST 三次 what-if/dcf 把三个 implied_price 画成一条 football-field 式横条(项目已有 ui/src/components/charts/FootballField.tsx 可直接喂)。把激活后的情景写进 appStore 现成的 scenarios/scenarioResults,删掉 WhatIfEditor 里重复的单点 useState。B) 若不做三情景,直接删 appStore.ts:280-318 + 对应 setter,消除死 state。注意:任一方案都要保持 what-if 回放冻结输入、绝不重 fetch 的现有契约(ReportRightRail.tsx:35-40 注释),否则 delta 会被数据漂移污染。重构量级:A 约 1 个组件 + store 接线(~200 行);B 纯删(~60 行)。
- **影响面/回归风险**：A 给报告页一个真正区别于 ChatGPT 的'情景压力测试'wow,且复用已有 football-field/什么-if 后端,边际成本低;B 至少清掉误导性死 state。回归面:仅限报告右栏 + appStore;what-if 后端不动,无数据正确性风险。
- **置信度**：high　|　**状态**：待评估

#### [OPP-005] 把 valuation_overview/competitor_analysis 从'LLM 复述数字'重构为'code 拼确定性数字行 + LLM 只写定性 why'，从结构上根除散文印错数

- **类别**：机会
- **价值/成本**：高价值·中成本
- **位置**：finrobot/engine/pipelines/equity_research.py:789-826（synthesis_agent 指令）+ artifact 渲染层
- **现象/问题**：当前架构让 LLM 既'引用'又'复述'确定层数字（valuation_overview 要解释加权目标怎么来、competitor_analysis 要给倍数对比），把'确定性数字'和'定性判断'揉在同一段自由文本里，于是必须靠 prompt 白名单 + run 后 override 两道补丁去防 hallucination，且 override 只覆盖标量、不覆盖散文（见 finding 1）。这是 ADR-0005/0006'数字由 compute 出、判断由 LLM 给'契约在叙事层的漏口。
- **证据**：valuation_overview 指令（818-820）要求 LLM 复述 DCF/Comps/DDM 各自 implied price 与加权过程——这些全是确定层已有的 vs.methods[*].mid 和 weighted_price；competitor_analysis（821-822）要求复述 peer 倍数。这些数字 code 已持有，让 LLM 复述纯属把可追溯的确定值降级成可 hallucinate 的散文。
- **依据/现状**：叙事字段设计时把'数字表'和'why 叙事'合并成一段 prose，没有在 code 侧先把数字渲染成确定性句子再交给 LLM 写解释。
- **落地方案**：重构（中等改动量，约 60-100 行 + 渲染层）：valuation_overview 拆成两段——code 端用 method_breakdown/weighted_price 拼一行确定性 'DCF $A · Comps $B · DDM $C → 加权 $T' 直接进 artifact（不过 LLM），LLM 只产出'为什么三法分歧/为什么 verdict 合理'的纯定性段（无数字）。competitor_analysis 同理：peer 倍数表由 code 渲染，LLM 只写'相对同业贵/便宜在哪、增速换估值是否划算'的判断。这样 finding 1/2 的 override 缺口从结构上消失。注意：需同步 instructions/synthesis_agent.md、前端对应渲染组件、以及 test_thesis_prompt_discipline 的断言对象（从'数字在白名单'转为'LLM 段不含 $数字'）。
- **验证补充**：Keep but sequence correctly: this is the durable fix; 0/1 should still ship as interim guards because (a) the refactor is larger and (b) even with code-rendered numbers the LLM-written qualitative segment can still smuggle a stray $number, so a post-run scan/whitelist remains worthwhile. When done, re-target test_thesis_prompt_discipline from 'number is in whitelist' to 'LLM qualitative segment contains no $-number', and ensure the code-rendered line itself reuses the same humanize helper as finding 2 to stay consistent with SourcedNumber.
- **影响面/回归风险**：提升所有研报数字可信度到'散文不可能印错数'的强保证，是把产品从'能用'推向'投行级可溯源'的高杠杆改动。回归中：改叙事生成路径与渲染，需回归 8-agent 叙事完整性与 artifact schema 兼容（valuation_overview 文本语义变化，旧 artifact 仍可读因字段仍是 str|None）。
- **置信度**：high　|　**状态**：待评估

#### [OPP-006] DCF/LBO/comps 等模型产物有版本切换但没有版本对比——semantic_diff 后端已完整支持 dcf/ic_memo，前端只给了 equity_research

- **类别**：机会
- **价值/成本**：高价值·中成本
- **位置**：ArtifactDetailPage.tsx L228-255（非 research 分支不渲染 VersionDiffBanner）
- **现象/问题**：量化研究员对同一支股票会反复跑 DCF（调 WACC、改增长假设），最想要的就是『这次 DCF vs 上次 DCF，公允价值变了多少、是哪个假设驱动的』。后端 semantic_diff.py 的归因引擎 _dcf_result（L165-176）明确支持 `dcf`/`equity_research`/`ic_memo` 三种类型、能逐项拆解 WACC/终值增长对公允价值的贡献。但前端 VersionDiffBanner 只在 isResearch 分支渲染（ArtifactDetailPage L305）；非 research 的 CompactArtifactViewer 分支（L228-255）只有一个 toolbar 版本下拉（能跳版本），没有任何对比/归因 banner。两份 DCF 之间的 diff 能力建好了却没接到 UI。
- **证据**：semantic_diff.py:165-176 `_dcf_result` 对 `art.type == "dcf"` 直接返回 structured；L380-414 attribution plan 对 wacc/terminal_growth 做确定性 re-price。但 ArtifactDetailPage.tsx 非 research 分支（L228-255）只渲染 `<ReportToolbar>` + `<CompactArtifactViewer>`，无 VersionDiffBanner。VersionDiffBanner 本身 reportType-agnostic（它按 timeline.filter(type===reportType) 取同类版本），完全能用于 dcf。
- **依据/现状**：VersionDiffBanner 的接入点只写在 research 渲染分支里（L305），非 research 分支复制 toolbar 时漏了 banner。不是后端缺能力，是前端接入点偏置。
- **落地方案**：在 ArtifactDetailPage.tsx 非 research 分支（L249 `<CompactArtifactViewer>` 之前）也插入 `<VersionDiffBanner currentId={artifactId} currentCreatedAt={createdAt} reportType={data.type} parentArtifactId={parentArtifactId} timeline={timeline ?? []} />`。VersionDiffBanner 在同类版本 <2 时自己返回 null（L225），所以单版本 DCF 不会多出空 banner。注意 currency_assumed 逻辑（DCF 路径无币种标记，会显示『货币假定 USD』）对 dcf 类型尤其会触发——这是诚实披露不是 bug，保留。量级：中（1 处接入 + 验证 dcf 的 conclusion 行不出现重复 target/implied，semantic_diff L577 已对纯 dcf 跳过 implied_price 重复行）。
- **验证补充**：Insertion plan correct (banner self-returns null when same-type candidates<2 per L225). currency_assumed note is accurate: _resolve_currency (L209) runs for any pair and L506/643 sets currency_assumed; a plain DCF lacking a currency tag will surface the 'assumed USD' disclosure — correctly kept as honest disclosure. Verify the implied_price dedup (L577: equity_research/ic_memo only get the implied row) so plain dcf doesn't double-print target — finding already flags this.
- **影响面/回归风险**：高价值差异化：把已建好的确定性归因能力暴露给最高频的 DCF 迭代场景。回归面：只新增 banner，CompactArtifactViewer 本体不动；需确认 reportData.deriveReportData 对 dcf 能产出 createdAt（L156 已对所有类型给 createdAt/versionLabel）。
- **置信度**：high　|　**状态**：待评估

#### [OPP-007] 研报↔投委会入口不对称:verdict 出现的两个主力面(AIZone 热卡 + CoverageInspector)都没有『质疑/IC』入口,唯一入口埋在三级页 toolbar

- **类别**：机会
- **价值/成本**：高价值·中成本
- **位置**：ui/src/views/workspace/AIZone.tsx:878-902(HotState 动作区) + ui/src/components/coverage/CoverageInspector.tsx:181-202(动作区) ↔ 唯一入口 ui/src/pages/artifact-detail/shell/ReportToolbar.tsx:240
- **现象/问题**：『对这份研报开一场投委会辩论』在产品上是 ChatGPT 给不了的差异化动作,但它只在 ArtifactDetailPage 顶部 toolbar 有一个按钮(ReportToolbar:240)。而 verdict/目标价真正高频出现的两个面——AIZone 的 HotState 大卡(刚跑完研报最显眼的落点,有 BUY 大徽章+目标价+打开+重跑)和 CoverageInspector(研究台每个 ticker 的右栏,有 Run/Open/Compare/Remove)——都没有 IC 入口。用户看到一个 BUY 判断,最自然的下一步『压力测试它』却要先点进全文研报、找到顶栏才能触发。
- **证据**：AIZone.tsx:878-902 HotState 动作区只有 open-latest-report 与 onRerun 两个按钮,无 IC;CoverageInspector.tsx:181-202 ActionButton 网格是 runResearch/openStock/compare/remove,无 IC;ReportToolbar.tsx:239-250 是全 UI 唯一带 onOpenIcDebate 的按钮,且 disabled unless reportType==='equity_research'。CmdK(CmdKOverlay)也无 IC 入口(grep 无 /ic 注册)。
- **依据/现状**：IC 入口在做 ArtifactDetailPage 时只在最近的容器(toolbar)接了一个,没有作为『针对任一 verdict-bearing artifact 的动作』下沉到 AIZone/Inspector 这些 artifact 卡片组件。
- **落地方案**：在 AIZone HotState 动作区(line 899 onRerun 旁)加一个『⚖ 投委会』ghost 按钮 navigate(`/ic/${ticker}?artifact_id=${latest.id}`);在 CoverageInspector ReportPanel 有 research(row.research_count>0)时、或动作网格加一个 IC ActionButton,onClick navigate(`/ic/${row.ticker}?artifact_id=${row.latest_artifact_id}`)(latest_artifact_id 已在 CoverageRow 上,service.py:238)。注意:只对有 equity_research/ic_memo verdict 的 artifact 显示(与 toolbar 的 equity_research 门控一致,避免对纯 DCF 开辩论时 build_evidence_set 422);若上面 P1 把 debate 改成落 artifact,这些入口同时变成『生成投委会备忘录』。改动量级:小(两处各加一个按钮+一个 navigate,约 30 行)。
- **验证补充**：Fix is reasonable and the finding's own gating note is the critical correctness guard: only surface the IC button when latest artifact is equity_research/ic_memo (has a verdict), matching ReportToolbar's reportType==='equity_research' gate, else build_evidence_set throws 422. row.latest_artifact_id (service.py:238) and latest_verdict are available on CoverageRow to drive both the gate and the nav target. NOTE this entry should be sequenced AFTER deciding [1]: if debate becomes artifact-producing, these buttons' semantics shift from 'open ephemeral debate' to 'generate IC memo', so don't ship [3] before [1]/[0]'s A/B is decided or you'll wire entries to a surface about to change.
- **影响面/回归风险**：纯增量入口,不改数据流;低回归风险。需确保对无 research 的 ticker 隐藏/禁用按钮,否则点进去 IC StartPanel 会显示 noArtifactWarning。
- **置信度**：high　|　**状态**：待评估

#### [OPP-008] Coverage Desk 缺键盘巡航是把『投行级研究台』降格为『鼠标 demo』——补一套 j/k+方向键 roving 让分析师不离键操作整面分诊墙

- **类别**：机会
- **价值/成本**：高价值·中成本
- **位置**：动线：/coverage 首屏分诊（CoverageCardGrid 卡片墙 ↔ CoverageInspector）+ WallHeader 滤镜切换
- **现象/问题**：目标用户是每天盯盘的买方研究员/量化研究员，他们的肌肉记忆是 Bloomberg/终端式不离键操作。当前 Coverage Desk 的全部巡航（切卡、切 Live/Report/History tab、Run、Compare）都必须用鼠标点：卡片不可聚焦（见 P0 Bug）、tab 切换是鼠标点 button、批量选择要鼠标勾 checkbox。一个声称『投行级深度 + 可溯源』的研究台，却无法用键盘扫过 20 个标的的 verdict/upside，体验上立刻露馅为『好看的 demo』而非『专业工具』。这是把『能用』推向『惊艳』的高杠杆点：专业用户对键盘流的敏感度极高。
- **证据**：场景：研究员早上开 app 想快速过一遍 Needs Action 队列的 15 个标的——理想是 j/k 上下移动焦点、Enter 进 workspace、r 触发 Run、c 加入对比、数字键切 Inspector tab，全程手不离键盘。当前必须：鼠标点卡 → 鼠标点 Inspector tab → 鼠标点 Run，每个标的 3+ 次鼠标往返。对比 CmdKOverlay 已经做了完整键盘体验（↑↓ 选、Enter 确认、Esc 关、loop），说明项目有能力也有审美做键盘流，只是没下沉到主工作面。
- **依据/现状**：卡片墙从设计起就只接 onClick（CoverageCard.tsx:103），未把『分诊巡航』当成一等键盘交互来设计；Inspector tab（CoverageInspector.tsx:147-170）同理只接 onClick。
- **落地方案**：在 CoverageCardGrid.tsx 实现 roving tabindex + 方向键/jk 导航（容器接 onKeyDown，维护 activeIndex，↑↓←→/jk 移动并 onFocus 同步、Enter→onOpen、r→onRun、x→onToggleSelect、c→批量 Compare），同时解掉 P0 的卡片可聚焦问题；给 CoverageInspector 的 tab 组加 role=tablist + ←→ 切换（aria-pressed 已有）；WallHeader 滤镜可加 1/2/3 数字键。改动量中等（~80-120 行 + 一份键位提示浮层/footer，复用 CmdK footer 的 kbd 样式）。注意：键位需避开输入框聚焦时（hero 搜索框 focus 时不拦截字母键）。把键位写进 docs/UI设计.md 与 i18n 文案。
- **验证补充**：Sound. Implement roving tabindex + arrow/jk in CoverageCardGrid (resolving [0] in the same pass), add role=tablist + ←→ to Inspector tabs (aria-pressed already present at 154). Critical guard the author already flags: don't intercept letter keys while the hero search input is focused. Sequence after [0] (P0) so the minimal a11y fix isn't blocked on the larger nav work.
- **影响面/回归风险**：显著提升专业用户日常效率与『这是真终端级工具』的观感，是低成本高记忆点的差异化；回归风险中——需保证输入框/checkbox/已有 stopPropagation 控件聚焦时不误触全局键位，要加守卫（document.activeElement 判断）。建议与 P0 Bug 合并一次做，避免两次改 grid。
- **置信度**：high　|　**状态**：待评估

#### [OPP-009] Make the loopback-only trust model explicit and self-defending: TrustedHost + a sidecar capability token shipped as one auth seam

- **类别**：机会
- **价值/成本**：高价值·中成本
- **位置**：finrobot/server.py:328-340 (trust-model seam), finrobot/cli.py:685-739 (sidecar launch), ui/src-tauri sidecar spawn + ui/src/api/client.ts
- **现象/问题**：Today the trust model is an undocumented implicit assumption ('don't expose the port') enforced only by a code comment (server.py:328) and a default --host. For a product targeting professional analysts who store proprietary research and live broker-adjacent API keys, an auditable, explicit local-auth seam is both correct and a credibility differentiator. The current state leaves a security reviewer with no way to verify the boundary holds — and it doesn't (findings 1-4).
- **证据**：server.py:328-329 the boundary is a comment 'no authentication. For local development only' — yet this is the shipped desktop product per CLAUDE.md (Tauri sidecar), not just dev. cli.py:705 already passes a private --parent-pid handshake from Tauri to the sidecar, proving a private channel exists to also hand over a generated token.
- **依据/现状**：The localhost-only assumption was never promoted from 'dev convenience' to 'enforced product trust boundary' as the project moved from CLI to a packaged desktop app.
- **落地方案**：Build one auth module: (1) cli.py serve() generates a 256-bit token at boot, exposes it to the Tauri shell via the same private launch channel as --parent-pid (env var or argv); (2) server.py registers TrustedHostMiddleware(loopback) + a global dependency that requires header X-FinRobot-Token == the boot token, with the /health route exempt for the parent-death/readiness probe; (3) ui/src/api/client.ts + EventSource + Vercel chat fetch attach the header (EventSource can't set headers → pass token as a query param for the SSE routes only, validated by the same dependency). Document the model in docs/. This is the clean, one-time consolidation that retires findings 1-4's shared root cause. Magnitude: medium refactor, ~120-180 LoC across backend+sidecar+UI, plus test-client/dev-proxy updates.
- **验证补充**：Split the work: TrustedHostMiddleware is cheap, fully backend-side, and independently verifiable — ship it first (kills DNS-rebind). The capability-token half depends on locating the actual sidecar spawn; the 120-180 LoC estimate may be off until that spawn path is found and confirmed to support extra argv/env. EventSource-can't-set-headers→query-param-token note is correct and necessary for the SSE routes (runs.py:206 stream).
- **影响面/回归风险**：Closes the entire class of local-attacker findings in one seam; high product value (auditable security story for the target user). Regression risk concentrated in the SSE query-param token path and dev-server/test-client wiring — must verify Vite dev, /chat stream, /api/runs/{id}/events resume, and pytest TestClient all carry the token.
- **置信度**：high　|　**状态**：待评估

#### [OPP-010] Centralize secret redaction at every persistence boundary instead of per-provider string hygiene

- **类别**：机会
- **价值/成本**：中价值·低成本
- **位置**：finrobot/audit/transcript.py:74-94 (transcript sink) + finrobot/obs/setup.py (log sink) + provider error formatters (news_aggregator/fmp/fx)  ·  （另涉：finrobot/obs/filters.py（新增 RedactingFilter）+ setup.py:48-69（wiring））
- **现象/问题**：The same secret-in-string hazard exists at two independent sinks (obs logger — already noted — and transcript JSONL) and is currently 'fixed' (if at all) by asking every provider to format errors carefully. That is fragile: any new provider that interpolates an httpx exception re-opens the leak at both sinks. There is no single chokepoint that guarantees secrets never hit durable storage.
- **证据**：server.py:59-71 already maintains an authoritative `_SECRET_FIELDS` list (anthropic/openai/deepseek/fmp/finnhub/alpha_vantage/adanos keys) — the values are known to the process. Yet neither the logging formatter nor TranscriptWriter consults it; redaction relies entirely on provider authors not interpolating raw exceptions. The two-sink reality is exactly why the per-provider fix in the P1 finding is necessary-but-insufficient.
- **依据/现状**：No shared redaction primitive; secret knowledge (the _SECRET_FIELDS values) lives in config/secret_store but is never injected into the output paths.
- **落地方案**：Add finrobot/audit/redaction.py exposing `redact(text: str, secrets: Iterable[str]) -> str` that (a) replaces any known live secret value substring with [REDACTED] and (b) regex-strips `api[_-]?key=...` / known auth header patterns as a value-agnostic backstop. Wire it into both sinks: a logging.Filter installed in obs/setup.py and a call inside transcript._write_event. Source the live secret set from the same secret_store the server already builds (app.state.secret_store). Magnitude: medium refactor (~80 lines + 2 wiring points + tests asserting a planted key never appears in either output). This makes provider-level hygiene a defense-in-depth nicety rather than the only line of defense.
- **验证补充**：Sound. Caveat: a value-substring replacer must guard against empty/very-short secret values (an empty or 1-char key would replace everything) — only redact secrets above a min length, and keep the value-agnostic regex backstop (api[_-]?key=, X-API-Key/X-Finnhub-Token headers) as the primary. Cost (~80 lines + 2 wiring points + planted-key tests) is not understated. Should land AFTER [0]'s layer-1 source fix, as explicit defense-in-depth, not as the sole line of defense.
- **影响面/回归风险**：Eliminates the entire class at the boundary; future providers can't reintroduce it. Risk: value-substring redaction must handle empty/very-short keys safely (skip secrets under N chars to avoid mangling unrelated text). Touches the hot logging path — keep the matcher precompiled and short-circuit when no secrets configured.
- **合并自**：gap-r1-5#5, gap-r2-4#3（2 条同源发现）
- **置信度**：high　|　**状态**：待评估

#### [OPP-011] SourcedNumber 的'每个数字可溯源'是真差异化,却只活在报告内页,冷启动/落地从没把它当卖点亮出来

- **类别**：机会
- **价值/成本**：中价值·低成本
- **位置**：ui/src/components/SourcedNumber.tsx(provider/as_of/formula/warning + deep-link 全做了)vs 冷启动动线(CoverageHero / CoverageEmptyState / AIZone ColdState 都未展示这一能力)
- **现象/问题**：SourcedNumber 是这个产品对 ChatGPT 的最硬区别:任意数字 hover 即弹 provider / as_of(口径时点)/ formula_id / data warning + '打开来源研报'深链,且数据质量警告做成行内 amber 三角不藏在 hover 里(分析师扫几十行也能看到)。这正是'LLM 会编数字,我们代码兜底可溯源'的可触摸证据。但它只在报告/工作台内部出现;新用户在 CoverageHero(大 LOGO + 搜索框)、ColdState(🤖 + 跑 AI CTA)、Starter 这些'第一印象'界面里完全感受不到——产品最强的护城河在最需要打动人的入口处隐身。
- **证据**：SourcedNumber.tsx 完整实现 provenance 弹层 + 行内警告 + artifact 深链;但 CoverageHero.tsx(整文件)、CoverageEmptyState.tsx(整文件)、AIZone ColdState(AIZone.tsx:544-630)的文案/视觉里没有任何'每个数字都标出处'的展示或样例。ColdState 只有 immutableNote 一行小字讲'不可变',没讲'可溯源'。
- **依据/现状**：溯源能力是按'报告内的功能'实现的,从没被提炼成'落地页讲故事的卖点';冷启动文案停留在泛化的'跑 AI 研报'。
- **落地方案**：在冷启动至少一处把溯源具象化:最低成本——在 AIZone ColdState 的描述区放一个静态 SourcedNumber 样例(如一个示意'营收 $X ⓘ→ FMP · 2024-Q4 · 已校验'),配文'这里每个数字都能点开看出处,LLM 编不了'。或在 CoverageHero 副标语轮播里加一句'代码算数字 · LLM 给判断 · 每个数都可溯源'。注意:样例若用真数字必须是 mock/示意并明确标注,绝不能让人误以为是某真股票的实时值(数据正确性红线)。量级:~20-40 行静态展示。
- **验证补充**：Downgrade to P3 and narrow scope to true cold/empty surfaces (ColdState/CoverageEmptyState/Hero). Acknowledge SourcedNumber already ships on populated CoverageCards. Mock-data caveat in the fix is correct and mandatory (data-correctness redline).
- **影响面/回归风险**：把最强差异化前置到第一印象,提升'这个和 ChatGPT 不一样'的转化;纯展示层改动。回归面:仅落地/冷启动组件,不碰数据与报告逻辑。
- **置信度**：medium　|　**状态**：待评估

#### [OPP-012] CLI 缺统一错误网关：每条命令各自(不)处理异常,体验碎片化

- **类别**：机会
- **价值/成本**：中价值·低成本
- **位置**：finrobot/cli.py 整体 (@click.group cli:117-120 + 各 command)
- **现象/问题**：全 CLI 只有 5 处把异常转 ClickException(config:44 / compare 数量:421,423 / params:569)，其余所有失败模式(数据全源失败、no price data、provider 限流、LLM 各类错误、artifact 落地失败)都以裸 Python traceback 呈现。分析师作为非工程用户,看到 backtrader/pydantic/httpx 的内部堆栈无法自助。这是个系统性体验缺口,不是单点 bug。
- **证据**：backtrader_adapter.py:189-197 抛 ValueError('No price data available for X between A and B')——文案其实很友好,但因 cli.py:589 _run_manual 外无 except,用户看到的是它被埋在 traceback 末行。这类'好文案被裸 traceback 淹没'遍布所有命令。
- **依据/现状**：click.group 未装全局异常→ClickException 的边界;每命令重复(且不全)地手工 try/except。
- **落地方案**：加一个轻量装饰器 @clean_cli_errors 包裹每个 command body:catch (ValueError, RuntimeError, ProviderError, AgentRunError, OSError) → click.ClickException(str(e));对预期内的业务错(no price data / 数据不可用 / LLM 失败)直出干净一行,对真正意外仍可用 --debug flag 透传 traceback。或更克制:在 cli() group 用 click 的 result_callback / 自定义 Group.invoke 包一层。建议装饰器方案(显式、可逐命令豁免)。注意:不要吞掉编程错误(KeyError/AttributeError 这类应让它 traceback 暴露 bug),只规整面向用户的业务异常。约 20 行 + 逐命令加装饰器。
- **验证补充**：Decorator approach is sound and aligns with project's anti-band-aid stance (root cause, all commands). Strongly endorse the explicit caveat: do NOT swallow KeyError/AttributeError/programming errors — only map business exceptions (ValueError, ProviderError, AgentRunError, OSError, pydantic.ValidationError). Provide a --debug/env escape hatch to re-raise full tracebacks. One caution: a blanket decorator could mask the per-command catches in findings #1/#2/#4 — implement those targeted fixes too rather than relying solely on the gateway, since the gateway gives generic str(e) whereas the targeted fixes can give actionable, command-specific guidance. Mild confidence downgrade because the precise exception set to catch needs care to avoid hiding real bugs.
- **影响面/回归风险**：统一所有 CLI 命令的失败体验,把已有的好错误文案真正呈现给用户。回归风险:需确保不误吞应当冒泡的编程 bug——靠白名单异常类型控制。
- **置信度**：high　|　**状态**：待评估

#### [OPP-013] list_versions(limit=1000) 是零调用方死代码，且与真实生效的 timeline(limit=50) 形成第二条版本读取路径

- **类别**：机会
- **价值/成本**：中价值·低成本
- **位置**：finrobot/artifact/sqlite_store.py:333-340 + store.py:67-68 (list_versions) vs routes/artifacts.py:96-121 (ticker_timeline, limit=50)
- **现象/问题**：list_versions(ticker,type) 硬编码 include_archived=True,limit=1000，被审查重点点名为『版本历史扩展性』担忧——但通读全仓+前端+测试，它的唯一引用是 tests/artifact/test_store.py 两处单测，生产零调用方。真正给 VersionDiffBanner 喂版本候选集的是 GET /api/artifacts/by-ticker/{ticker}/timeline（artifacts.py:96），默认 limit=50。于是存在两条平行的『取某票版本列表』路径：一条死的 limit=1000、一条活的 limit=50，且语义不同（死的限定 type、活的全 type）。
- **证据**：grep list_versions：仅 sqlite_store.py/store.py 定义 + test_store.py 调用，无 routes/无前端引用。VersionDiffBanner.tsx:168-174 的 candidates 来自 timeline prop，timeline 来自 by-ticker/timeline 端点（limit=50）。CLAUDE.md 红线明列『路径分裂/dead code 要连根拔』。limit=50 对版本历史是真约束：同票超过 50 份任意类型 artifact 后，第 51 份起的旧版本不进 diff 候选集——但这是 timeline 端点的问题，不是 list_versions 的。
- **依据/现状**：list_versions 是文件系统 store 时代遗留的版本读 API，迁到 SQLite + 引入 timeline 端点后未删，CLAUDE.md 定义的『完成』含『死代码顺手清』未执行。审查担忧的『limit=1000 扩展性』瞄错了对象——真隐患在 timeline 的 limit=50。
- **落地方案**：两步:(1) 删 list_versions（sqlite_store.py:333-340 + store.py:67-68）及 test_store.py 对应两测，消灭路径分裂；(2) 把版本历史的真约束 limit=50 提到分析师场景合理值——active** ticker 一年可能 >50 份混合 artifact。建议 ticker_timeline 默认 limit 提到 200（与 service.py:177/_assemble_row 已用的 limit=200 对齐），或改成不分页全量（单票 artifact 数有界，COUNT 通常 <100）。注意:timeline 端点会 attach_signals（artifacts.py:124）逐个抓价，limit 调大需确认 attach_signals 是批量 quote 而非 N 次串行 fetch，否则放大延迟。改动量级:小。
- **验证补充**：Fix is right (delete list_versions + its 2 tests; raise timeline default limit). Caveat the reviewer already notes: ticker_timeline calls attach_signals (artifacts.py:124) per-summary — verify it's a batched quote, not N serial fetches, before bumping limit, else raising limit amplifies cold-start latency the column-mirror design was built to avoid.
- **影响面/回归风险**：删 list_versions 影响面=仅两个单测。调 timeline limit 影响版本 diff 候选完整性 + 该端点延迟（取决于 attach_signals 实现）。回归风险低。
- **置信度**：high　|　**状态**：待评估

#### [OPP-014] 正则从自由文本抠出的 ceo_name/comp/ratio 与确定性计算数字同权威落地(带完整 DEF 14A provenance),无 confidence/heuristic 标志,读者无法区分脆弱抓取与可信计算

- **类别**：机会
- **价值/成本**：中价值·低成本
- **位置**：finrobot/engine/compute/ownership.py:664-676 + finrobot/engine/models/sec.py:259-274 (ProxyCompensation) + finrobot/artifact/builders.py:407-409
- **现象/问题**：822 行 ownership 的 proxy 字段全靠黑名单+区间兜底的启发式正则抠 DEF 14A 自由文本,但 ProxyCompensation 把 ceo_name/ceo_total_compensation/ceo_pay_ratio 与 FilingProvenance(form=DEF 14A, accession_no, source_url)一起持久化进 artifact.outputs.structured.ownership_governance,在研报中与 DCF/comps 这类确定性计算数字同等权威呈现。模型无 confidence/extraction_method 字段,UI/分析师无法知道这是'正则猜的'。CLAUDE.md 红线:数字必须可追溯且区分确定性 vs 启发式。
- **证据**：sec.py:259-274 ProxyCompensation 字段全无 confidence 标记;ownership.py 全文 grep confidence/extraction_method/heuristic 只在注释出现,无字段;builders.py:407-409 _safe_dump 整体落地。validators.py:64-87 不做语义校验。
- **依据/现状**：架构层缺'抽取置信度/方法'维度——脆弱正则结果与确定性计算结果共用同一 provenance 通道,无降权信号。
- **落地方案**：给 sec.py ProxyCompensation 增 extraction_confidence: Literal['disclosure','sct_table','prose_anchor','none'] 与可选 needs_review: bool;build_proxy_compensation 按实际命中的来源(disclosure_comp/summary_comp/_ceo_comp_from_text)填该字段;prose_anchor(_ceo_comp_from_text 兜底)与 name/comp 不同源时置 needs_review=True;前端 ownership 卡片对 needs_review/prose_anchor 字段加'低置信·待核'角标(走现有 cosmic token,不硬编码 hex)。改动量级:中(模型+compute+前端卡片+i18n key)。
- **验证补充**：Fix direction is right but scope it tighter: a single extraction_method/provenance enum on the COMP value ('disclosure'|'sct_table'|'prose_anchor'|'none') is the high-value 80%; prose_anchor (the _ceo_comp_from_text fallback, the only path that can emit findings [0]'s fabricated number) should always set needs_review=True. Per-field source tracking for name vs ratio is nice-to-have — don't gold-plate. The UI badge belongs to this finding; don't also build it in [1]/[2]. Add the field only after fixes [0]/[2] land so 'prose_anchor' genuinely means lower trust rather than masking an unfixed regex bug.
- **影响面/回归风险**：影响所有展示 CEO 薪酬卡片的研报;纯增量字段,无破坏现有契约(默认值可填 'none'/False),回归风险低。属把'能用'推向'可信'的高杠杆诚实化改动,与 BUG-015/057 诚实化思路一致。
- **置信度**：high　|　**状态**：待评估

#### [OPP-015] 报告里的数字/章节没有'就这个问 AI'的行内入口——代码兜底数字 + LLM 叙事的组合拳没打满

- **类别**：机会
- **价值/成本**：中价值·中成本
- **位置**：动线环节 5/9:ui/src/pages/artifact-detail/(无 ask-AI 行内钩子)+ ui/src/layout/RightChatPanel/AiChatTab.tsx:228-239(context_bundle 只在页/ticker 粒度绑定)
- **现象/问题**：产品定位是'数字由 compute 算、判断由 LLM 给',按理报告里每个数字/章节旁边都该能一键'就这个数问 AI:为什么 WACC 取 10%?这个目标价对不对?'——把可溯源数字直接喂进对话上下文。现状:右侧 chat 的 context_bundle 只在当前页/ticker 粒度绑定(AiChatTab.tsx:228),报告正文里没有任何 number 级/章节级的'explain this / ask AI'触发点(grep 仅命中 ChapterValuation 里的术语解释器注释,非 ask-AI)。分析师想追问某个数字,得自己切到 chat 再手敲上下文。
- **证据**：grep explain/askAi/sendToChat/chatAbout 在 artifact-detail 下无行内 ask-AI 实现;AiChatTab.tsx:228-239 context_bundle 构造是页级。SourcedNumber 已经持有 provider/formula_id/artifact_id 等结构化上下文,具备喂给 chat 的现成 payload 但没接线到对话。
- **依据/现状**：chat 上下文按'当前页'设计,报告正文与对话之间缺一条'选中某数字/章节 → 注入 chat'的桥;溯源元数据和对话上下文是两套独立系统。
- **落地方案**：给 SourcedNumber 的 popover(已有 provider/formula/artifact_id)加一个'就这个问 AI'动作:点了把 {字段名, 值, provider, formula_id, as_of, ticker, artifact_id} 作为一条结构化 context 注入 RightChatPanel 并打开它(复用 AiChatTab 的 context_bundle 通道,扩一个 'number-focus' 字段)。章节级同理:ChapterBase 标题旁加一个小'问 AI'图标带 chapter id。注意:注入的数字必须带口径(as_of/formula_id)一起进 prompt,否则 LLM 失去溯源前提又可能编;且要明确'数字是 compute 算的、AI 只解释不改数'。量级:SourcedNumber + chat context 通道扩展(~1 组件 + store 一个 action,中)。
- **验证补充**：Reuse the existing pinned channel (kind:'number-focus', structured label) rather than inventing a new context field — addPinned + setSelectedText + open aiPanelOpen already exist, so the fix is lighter than 'extend the bundle'. P3/P2; high-value combo move but additive feature, not a bug.
- **影响面/回归风险**：让'可溯源数字 + LLM 解释'真正闭环成一个连续动作,是 ChatGPT+yfinance 做不到的工作流;但比前几条更重,放 P3。回归面:SourcedNumber 与 chat store,需保证注入不污染现有页级上下文。
- **置信度**：medium　|　**状态**：待评估

#### [OPP-016] Session transcripts grow unbounded forever — no retention/rotation/size cap, full payloads written verbatim

- **类别**：机会
- **价值/成本**：中价值·中成本
- **位置**：finrobot/audit/transcript.py:83-94 (_write_event, no cap) + finrobot/paths.py:63 (SESSIONS_DIR) — no cleanup path exists anywhere
- **现象/问题**：~/.finrobot/sessions/*.jsonl is append-only with zero retention, rotation, or per-line size cap. Every tool_result is written in full: full 13-chapter report `summary` strings, full 10-K document text (data_type `10k_rag`), full news payloads. Over a desktop app's lifetime this is monotonic disk growth the user never sees and can never reclaim through the app.
- **证据**：grep across finrobot/ for session cleanup/prune/rotate/retention/unlink against SESSIONS_DIR returns nothing — the only retention knob, config.py:119 `log_retention_days=7`, is wired solely to the obs RotatingFileHandler (obs/setup.py:63), not to transcripts. transcript.py:_write_event opens the file in append mode and writes `line + "\n"` with no length check (grep for truncate/cap/`[:N]` in transcript.py returns nothing). The payloads are large: query_financial_data with data_type=`10k_rag` (types.py:26 RAG_10K) returns 10-K text; pipeline tools return `result.format_summary()` (orchestrator.py:35) which is the full report narrative. Contrast: the LLM-side prompt builder (engine/pipelines/base.py) has explicit char caps (12k/16k/200k) — the transcript sink deliberately has none. Persistence read side (persistence.py:182-191 load_session_transcript) reads the entire file into memory per call, so a multi-MB session also degrades cmd+K history loads.
- **依据/现状**：The transcript was designed append-only-forever (transcript.py:3-6 docstring: 'Append-only') with no lifecycle owner. No component is responsible for trimming SESSIONS_DIR; the 256-entry LRU on transcript_writers (server.py:171) bounds in-memory writers, not on-disk files.
- **落地方案**：Add a retention sweep for SESSIONS_DIR. Option A (chosen — symmetric with existing artifact archive at server.py:187 hours=24*30): in finrobot/audit/persistence.py add `prune_sessions(base_dir=None, *, keep_days: int, max_total_mb: int|None)` that deletes *.jsonl older than keep_days (by last_active_at / file mtime) and, if over max_total_mb, deletes oldest-first until under budget; call it once from the server lifespan startup background block alongside reconcile_orphaned_runs (server.py ~157-187). Add `session_retention_days` to config.py (default e.g. 90) rather than reusing log_retention_days (7d is too aggressive for chat history users expect to revisit). Note: must not delete the file for an active session_id present in app.state.transcript_writers; key the sweep on mtime and skip currently-open writers. Secondary (optional): cap per-tool_result payload in transcript.py with a configurable max (e.g. 64k) writing a `"truncated": true` marker — but only after confirming the history-replay UI doesn't depend on full payloads. Magnitude: medium (new prune function + config field + 1 startup call; the payload cap is a separate decision).
- **验证补充**：Fix approach sound. Two refinements: (1) keying the sweep on file mtime AND skipping session_ids currently in app.state.transcript_writers (per the finding's note) is essential — correct. (2) A new session_retention_days config field is right; reusing log_retention_days (7d) would silently delete chat history. The optional per-tool_result payload cap should be deferred until confirming the history-replay UI (load_session_transcript consumers) doesn't need full payloads — leave that as a separate decision, not bundled.
- **影响面/回归风险**：Operational/disk. Affects every long-lived desktop install; heavy users analyzing many tickers with 10-K RAG accumulate hundreds of MB silently. Regression risk: pruning is destructive — must guard active sessions and make keep_days conservative; get explicit sign-off on default retention since this is chat history, not logs.
- **置信度**：high　|　**状态**：待评估

#### [OPP-017] 7 个独立 db 无统一备份/完整性校验/迁移框架——研究资产无安全网

- **类别**：机会
- **价值/成本**：中价值·中成本
- **位置**：finrobot/paths.py:52-69 (7 db 各自为政) + 全仓无 PRAGMA integrity_check / backup API / 迁移版本表
- **现象/问题**：paths.py 声明 7 个独立 db,各 store 自管 schema。artifacts.db(研报真源)+ coverage.db(用户覆盖universe)是用户的核心研究资产,但全仓没有:统一备份机制、PRAGMA integrity_check、schema 版本表/迁移框架(仅 run_store 有 ad-hoc ALTER TABLE,artifacts/coverage/cache 一旦要改 schema 无迁移路径)、WAL checkpoint 管理。一次断电/磁盘满写坏 WAL,或某次 schema 演进,用户研报可能不可读且无 fallback。
- **证据**：paths.py 注释自称『for backup symmetry』但只是『放同一目录』,无实际备份代码。grep 全仓 integrity_check / .backup / PRAGMA wal_checkpoint:0 处。schema 迁移只有 run_store.py:428-441 一处针对 runs 表的 ad-hoc ALTER。artifacts.db 已 4.9MB 单文件、payload 列存全量研报 JSON,无 schema_version 表 → 下次给 Artifact 模型加必填字段时,旧 payload 反序列化(get() 的 model_validate_json)会 ValueError,现有 catch 只是『return None + warn Corrupt』(sqlite_store.py:269-271)= 静默丢报告。
- **依据/现状**：per-module db 的便利掩盖了缺失的横切关注点:备份/完整性/迁移本应有一个统一的 storage 生命周期管理层,但每个 store 只管自己开连接建表,没人负责跨库的『健康与演进』。
- **落地方案**：建一个 finrobot/storage/ 维护层(或 paths.py 旁):(1) `backup_all()`:用 sqlite3 在线 .backup API 把 7 个 db 原子拷到 ~/.finrobot/backups/<ts>/,server startup 或退出时跑、保留最近 N 份;(2) `check_integrity()`:逐库 PRAGMA integrity_check,startup 报告损坏库并降级;(3) 给 artifacts/coverage/cache 引入 user_version PRAGMA 或 schema_migrations 表 + 一个统一 migrate() 框架(把 run_store 的 ad-hoc ALTER 收编进来),让 Artifact 模型演进有 lazy-migrate 路径而非 model_validate_json 失败即丢。注意:在线 .backup 需短暂只读窗口或 WAL checkpoint;别在跑 pipeline 时备份 artifacts.db。机会类:value=中(保护用户核心研究资产 + 让 schema 演进不再砸旧报告),cost=中(一个维护模块,~150-250 行)。
- **验证补充**：Legitimate opportunity but over-rated as P2 for this project: single desktop user, no prod, KPI is GitHub stars not data-durability SLAs. A 150-250 LOC storage maintenance layer is real cost for speculative protection. Downgrade to P3. Highest-leverage slice is narrow: (1) a user_version/schema_version + lazy-migrate hook so a future Artifact model field doesn't silently drop old reports via get()'s catch-all (this is the only part that prevents real data loss), and (2) startup PRAGMA integrity_check with a warning. Defer the full backup_all()/.backup machinery — sqlite WAL + the user's own filesystem backups cover the desktop case adequately.
- **影响面/回归风险**：提升数据耐久性与可演进性,无行为破坏(纯增量)。当前单用户低风险,但 artifacts.db 已近 5MB 且持续增长,越晚做迁移框架,旧 payload 越多越难补救。
- **置信度**：high　|　**状态**：待评估

#### [OPP-018] TTM 组成季的 per-quarter provenance(component_provenance)已建模但从未填充

- **类别**：机会
- **价值/成本**：中价值·中成本
- **位置**：finrobot/engine/models/sec.py:71-84 (XBRLTTMMetric.component_provenance) vs edgar_provider.py:306-316
- **现象/问题**：XBRLTTMMetric 模型设计了 component_provenance(每个构成季一条 FilingProvenance，UI 可展示 "TTM = Q3+Q4+Q1+Q2" 并链到各 10-Q/10-K)，但 provider 的 _select_recent_ttm 完全没填——它手上明明有 metric.period_facts(每个 FinancialFact 带 accession/filing_date/form_type/period_end)。这是投行级可溯源性的高杠杆差异点：把 TTM 拆到季 + 每季可点回原始 SEC 文件，是 FinRobot 没有的能力。
- **证据**：edgar_provider.py:262 的 _metric_latest_period_end 已在遍历 metric.period_facts；FinancialFact 含 accession/filing_date/form_type/period_end(已读源码)。但 312-316 行只取了汇总 value，period_facts 的逐季 provenance 被丢弃。sec.py:74-77 注释明确写了这个 UI 愿景，却无人填充。
- **依据/现状**：非 bug，是已建模未接线的能力缺口。
- **落地方案**：_select_recent_ttm 返回 dict 增加 "component_provenance": [{"accession":pf.accession, "form":pf.form_type, "filing_date":str(pf.filing_date), "period_end":str(pf.period_end), "fiscal_period":pf.fiscal_period, "value":pf.numeric_value} for pf in metric.period_facts]；xbrl_concept_snapshot 透传；UI 在 comps/财务页渲染 TTM 季度构成 + SEC 链接。改动量级：中(provider+snapshot+一个 UI 组件)。value 中(差异化可溯源)，cost 中。
- **验证补充**：Sound. Sequence after #1 (which is the prerequisite plumbing carrying period_facts out of _select_recent_ttm). Use FinancialFact.form_type (not 'form') and .accession (models.py:50-51) — the finding's pf.form_type/pf.accession field names match the library exactly. UI work is incremental and can land after the provider/snapshot plumbing.
- **影响面/回归风险**：纯增量能力，无回归。把 "TTM 一个数" 升级为 "TTM 可拆季可点回原始申报"，对目标用户(分析师/研究员)是 wow 级溯源体验。
- **置信度**：high　|　**状态**：待评估

#### [OPP-019] SSE 三 store（runStream/debate + 各自模块级 EventSource Map）重复实现连接/重连/8-error 兜底

- **类别**：机会
- **价值/成本**：中价值·中成本
- **位置**：ui/src/stores/runStreamStore.ts:138-293 与 ui/src/stores/debateStore.ts:109-227
- **现象/问题**：runStreamStore 与 debateStore 都各自维护：模块级 `Map<key,EventSource>`、`sseErrorCounts` + `SSE_ERROR_LIMIT=8`、`closeAndForget`、onerror 里『status!=running 即清理 / 连续 8 次 error 强制 fail』的完全相同逻辑，以及 run.completed/run.failed 的关流处理。两份连接生命周期代码逐行同构，仅事件名（step.* vs debate.*）与 key 维度（ticker vs ticker::artifact）不同。
- **证据**：两文件的 closeAndForget、SSE_ERROR_LIMIT、sseErrorCounts、onerror 块、run.completed/run.failed handler 结构一字不差（debateStore 头注释甚至自述『mirrors the pattern in runStreamStore』）。
- **依据/现状**：debate SSE 后加时直接复制 runStream 的连接管理而非抽共享。非 bug，是重复。
- **落地方案**：抽 ui/src/lib/sseChannel.ts：`createSseChannel<K>({ url, onEvent, onTerminal, onError })`，封装 EventSource 创建、Last-Event-ID 重连依赖浏览器原生、8-error 强制失败、关流。两 store 各自只保留『把解析后的 event patch 进自己 state』的回调。注意：debate 的 onerror 文案与 runStream 略不同（中文 vs），抽象时把终态文案做成参数；保留两 store 独立（它们 key 维度与 badge 归属不同，合并 store 会引入 finding 之外的破坏性），只共享连接层。改动量级：中。
- **验证补充**：Endorse extracting ui/src/lib/sseChannel.ts for the connection/reconnect/8-error layer only; keep the two stores separate (different key dimensions ticker vs ticker::artifact, different badge ownership — header comments justify this, and merging would be the out-of-scope breaking change the finding warns against). Note the terminal error string is actually IDENTICAL in both ('SSE 连接中断（连续 8 次错误）...'); only run.failed defaults differ ('Pipeline failed' vs '投委会辩论失败，请重试'), so only those two need to be parameters. Severity P3 (DRY/maintainability, no functional bug) is correct.
- **影响面/回归风险**：影响面：两个 SSE store 的连接层。回归风险中（SSE 重连/8-error 是历史灾难点，注释专门记录过无限重连 bug，抽象后须保留 runStreamStore.test.ts/debateStore.test.ts 全绿并补一个 channel 单测）。收益：兜底逻辑单点维护，未来第三个 SSE 产品面（如 live news 流）直接复用。
- **置信度**：high　|　**状态**：待评估

#### [OPP-020] emoji 图标（🤖 AI NARRATIVE / ⚠ CTA）与 ▶↗▲▼ 字形按钮，违背 inline-SVG 图标语言、跨平台渲染不一致

- **类别**：机会
- **价值/成本**：低价值·低成本
- **位置**：ui/src/pages/artifact-detail/chapters/ChapterBase.tsx:127 / views/workspace/AIZone.tsx:571,660-664 / CoverageCard.tsx:380,389(▶↗) / WallHeader.tsx:167(▲▼)
- **现象/问题**：研报每章 Narrative 卡头用 emoji '🤖 AI NARRATIVE'，AIZone cold 态用 '🤖' 大图标、blocked CTA 用 '⚠' 前缀，Coverage 卡的跑/打开按钮用 ▶/↗ 字形、排序方向用 ▲/▼。cosmic 规范 6.5 节定的图标语言是'简单图标走 inline SVG'，emoji 与几何字形在 macOS/Windows/Linux 三端字体不同会渲染成不同字重/颜色/带苹果彩色描边，桌面 App 三端发布时观感漂移，且 emoji 自带的彩色与 cosmic 冷色调违和。
- **证据**：ChapterBase.tsx:127 硬写 '🤖 AI NARRATIVE' 出现在 13 章每个 Narrative 卡顶；AIZone:571 fontSize:40 的 🤖 是 cold 态视觉主体；▶(CoverageCard:380)/↗(389/CoverageInspector:404)/▲▼(WallHeader:167) 是功能按钮的唯一图形。在 Windows 上 🤖 渲染成 Segoe 彩色 emoji、macOS 是 Apple 彩色版，与规范'科幻冷色 neon'调性冲突；▶▲ 在不同等宽字体里基线/大小不齐。
- **依据/现状**：图标随手用了 Unicode 字形/emoji 没走 inline SVG，是改版期省事遗留；非单点 bug 而是图标语言未统一。
- **落地方案**：建一个极小的 inline-SVG 图标集（play/external-link/chevron-up-down/robot/warn,各 ~10 行 path，放 components/icons/）替换上述字形：CoverageCard ▶→<PlayIcon>、↗→<ExternalLinkIcon>，WallHeader ▲▼→<ChevronIcon>，AIZone ⚠→<WarnIcon>，Narrative/cold 的 🤖→一个线性 robot SVG 或直接用项目已有的 SplineHero fallback 图标。颜色一律 currentColor 继承 token。改动量=新增 1 个 icons 文件 + 替换约 6 处，标'中等'。注意 Narrative 卡头的 '🤖 AI NARRATIVE' 是 13 章共用的 ChapterBase，改一处全章生效。
- **验证补充**：Scope/cost estimate is honest (1 small icons file + ~6 swaps). Refinement: an icon set likely already exists — check components/icons/ (referenced) or existing inline SVGs before adding a new file, to avoid a duplicate icon system. Use currentColor as author says. The 🤖 cold-state at AIZone:571 is a deliberate friendly visual; replacing with a line-robot SVG is fine but confirm it doesn't read as a broken/missing glyph at 40px. Lowest priority of the six; sequence after [1]/[0]/[4].
- **影响面/回归风险**：三端观感一致 + 贴合 cosmic 图标语言；纯展示替换无逻辑回归，唯一风险是 SVG 尺寸/基线要对齐原 emoji 占位避免布局跳动，替换后各章 + 卡片截图自验一次。
- **置信度**：high　|　**状态**：待评估

#### [OPP-021] Pipeline 步骤声明仍是命令式逐条 PipelineStep，可升级为可校验的声明式 DAG/契约

- **类别**：机会
- **价值/成本**：中价值·高成本
- **位置**：finrobot/engine/pipelines/base.py:260-428（PipelineStep/Pipeline.execute）+ 各 create_*_pipeline
- **现象/问题**：每个 pipeline 以 list[PipelineStep] 线性声明，步间数据依赖（thesis 需要 financial_modeling+peer_analysis 的 structured_data）靠 _gather_data 的『最近 2 步全文 + 之前 1 行摘要』启发式（base.py:618-640）隐式传递，而非显式声明『本步消费哪些上游 structured key』。结果：①前端必须硬编码镜像步名与步数（PIPELINE_STEP_NAMES，注释记录过 6-vs-8 漂移 bug）；②步间契约不可静态校验，改步顺序可能静默断依赖；③critical 标记是布尔魔法位（仅 data_collection=True）。
- **证据**：base.py:601-640 _gather_data 的 compact 模式注释自承『Step N often needs both N-1 and N-2…2 is the sweet spot』——这是猜测式上下文窗口，不是声明依赖。runStreamStore.ts:90-111 不得不在前端复刻后端步名顺序。
- **依据/现状**：pipeline 抽象停在『有序步骤列表』层，未升级到『步骤 = 声明 consumes/produces 的节点』。非 bug，是抽象高度不够。
- **落地方案**：给 PipelineStep 增 `consumes: list[str]`（上游 step 名或 structured key）与 `produces: type`（StepOutput.structured 的模型类型）。_gather_data 改为按 consumes 精确注入而非 N-1/N-2 启发式；Pipeline 构造时校验每个 consumes 都有上游 produces 满足（缺则启动即报错，根除静默断链）。再暴露 `pipeline.describe()` 返回步名+顺序，前端通过 `/api/pipelines/{key}` 拉取替代 PIPELINE_STEP_NAMES 硬编码。注意：这是较大重构，须保持 Mode A/B/CLI/SDK 行为不变，建议先在 equity_research（8 步、依赖最复杂）试点再推广。改动量级：大（base.py + 7 个 pipeline 文件 + 前端取数）。价值中、成本高，建议排期而非顺手做。
- **验证补充**：Cost is correctly flagged as large (base.py + 7 pipelines + frontend) and value medium — agree: schedule, don't do opportunistically. Caveat on the proposed `produces: type` static check: pipelines mix LLM steps (StepOutput.structured may be None on best-effort failure, base.py:462) with deterministic compute steps, so a strict construct-time 'every consumes has a satisfying produces' check must tolerate optional/best-effort structured outputs — a missing produces at runtime is already handled gracefully (continue best-effort), so a hard startup failure could over-constrain. Scope the validation to declaration-graph wiring, not runtime presence. `pipeline.describe()` → `/api/pipelines/{key}` is the genuinely useful sub-piece and could ship independently to kill F2's hardcoded mirror.
- **影响面/回归风险**：影响面：所有 pipeline + 前端进度面板取数。回归风险中高（改 _gather_data 注入逻辑会改变喂给 LLM 的上下文，可能影响叙事质量，需逐 pipeline 回归 artifact 内容）。收益：步间契约编译/启动期可校验、前端不再镜像后端步名、新人能从声明直接读出数据流。
- **置信度**：medium　|　**状态**：待评估

#### [OPP-022] cross_tickers 仅存 JSON 列无索引无查询路径，peer 维度的『股票↔研报』一对多关联不可逆查

- **类别**：机会
- **价值/成本**：低价值·中成本
- **位置**：finrobot/artifact/sqlite_store.py:60 (cross_tickers TEXT JSON) + builders.py:247-255 (comps 写 peers 进 cross_tickers)
- **现象/问题**：审查焦点是『股票↔一对多研报建模』。正向（一只票→它的多份研报）由 ticker 列 + 索引良好支持。但 peer 维度的反向关联缺失：comps 研报把同业 peers 存进 cross_tickers JSON 列（builders.py:250），这列无索引、无任何查询消费方——给定一只票 X，无法查到『把 X 当 peer 引用过的所有 comps 研报』。coverage row 的 research_count/artifact_count 也只数 ticker== 自己的，不含被当 peer 引用。
- **证据**：grep cross_tickers 的查询用途：只有 dashboard.py:314 把它塞进展示 DTO，无任何 WHERE/JSON_EXTRACT 查询。建表无 cross_tickers 索引（sqlite_store.py:76-83 索引列表无它）。这意味着『AAPL 在哪些同业研报里被作为对标』这一分析师真实问题（反向 peer 溯源）查不了。注:这部分是『刻意不算 AAPL 的研报量』还是『建模缺失』有歧义——research_count 注释明确只数 verdict-bearing 自票研报，故计数排除 peer 是 by-design；但『可查询性』缺失是另一回事。
- **依据/现状**：cross_tickers 用反范式 JSON 存多值，未配 JSON 索引或关联表，本就只为『展示这份 comps 涉及哪些 peer』的正向渲染设计，未预期反向查询。属建模为当前 UI 够用、为分析师深度溯源不够。
- **落地方案**：若确认要支持反向 peer 溯源（建议先确认是否目标用户真需求，再动）：在 SQLite 上对 cross_tickers 建 JSON 路径索引需 generated column——`ALTER TABLE artifacts ADD COLUMN ...` 不便；更干净的是引入 artifact_peer_refs(artifact_id, peer_ticker) 关联表，save 时同步写入，按 peer_ticker 建索引，提供 list_by_peer_ref(ticker) 查询。注意:(1) 这是新能力非 bug 修复，按 CLAUDE.md 应先确认是不是分析师真痛点再建，避免锦上添花；(2) 若只是想让 coverage row 体现『被引用次数』，成本更低的是 service 层对 cross_tickers 做一次内存聚合。改动量级:中（新表+双写+查询）。
- **验证补充**：Fix proposal (artifact_peer_refs(artifact_id, peer_ticker) relation table + double-write + indexed list_by_peer_ref) is the clean implementation IF需求 is confirmed. But per CLAUDE.md, gate on confirming reverse-peer-traceability is a real target-user pain before building (avoid 锦上添花). Cheaper interim if only a 'referenced-as-peer count' is wanted: in-memory aggregation over cross_tickers at service layer, no new table.
- **影响面/回归风险**：纯新增，不改既有读路径。回归风险低。优先级 P3——先验证用户需求再投入，否则属投机建模。
- **置信度**：medium　|　**状态**：待评估
