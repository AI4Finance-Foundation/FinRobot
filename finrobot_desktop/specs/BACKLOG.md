# FinAgent Backlog

## Post-P0 Quick Wins
- [x] Add finagent_cache.db to .gitignore

## P1a: Skill Runtime
- [x] Skill loader + registry + activate_skill tool
- [x] 56 Anthropic skills in FinAgent native format

## P1b: Sub-agents + Optimization
- [x] Split lead_agent into data/analysis/modeling/synthesis/report agents
- [x] Strict validators (replace validate_is_non_empty with domain-specific validators)
- [x] Comps pipeline (6 steps)
- [x] DCF pipeline (6 steps)

## P1.5: Financial Computing Core
- [x] Pydantic models for inter-step data (FinancialData, PeerComps, DCFResult)
- [x] Deterministic WACC, DCF, multiples calculation
- [x] Numerical validators (replace keyword-search validators)
- [x] Data extractor (yfinance → typed models)

## P1c: Desktop App + Streaming
- [x] Electron + React + useChat
- [x] SSE streaming for pipeline progress
- [x] CLI streaming output (finagent run / finagent research)

### P2a — 数据源扩展（FMP / Finnhub / SEC EDGAR）

- [x] FMP Provider（财务报表 + D&A 明细 + key 归一化）
- [x] Finnhub Provider（基本面数据 + 单位转换）
- [x] SEC EDGAR Provider（10-K metadata + MD&A 提取 + User-Agent + rate limit）
- [x] DataLayer 链式回退（FMP → Finnhub → yfinance）
- [x] FCF 公式修复（标准公式 EBIT(1-T)+D&A-CapEx-ΔNWC，回退到简化公式）
- [x] DCFInputs.da_pct_revenue + DCFResult.fcf_formula
- [x] Extractor 多 provider 支持（key 归一化策略）
- [x] FinAgentSettings 新增 fmp_api_key / finnhub_api_key / sec_user_agent
- [x] 30 个新测试，288 测试全过

> P2a 完成于 2026-04-01。三个新数据源 + 链式回退 + FCF 公式修复。代码质量最高的一个阶段：零缺陷、零类型逃逸、零回归。

## P2c: 补齐 FinRobot 基线 + Desktop 完整 UI (Current)

### Phase A — 确定性计算层（完成）
- [x] 数据清洗层（clean_financial_number + 字段名归一化）
- [x] 数据处理增强（历史指标提取 + 3年 forecast + CAGR）
- [x] 催化剂分析（排序/过滤/Top-N，确定性部分）
- [x] 估值综合（多方法加权 + football field）
- [x] 多年数据获取（fetch_historical + 3 个 provider 适配）
- [x] 新闻获取 + LLM 分类（fetch_news + classify_news + yfinance 格式统一）

### Phase B — 图表/报告/Desktop UI（完成）
- [x] 图表引擎（9种图表，matplotlib：revenue_ebitda/margin_trend/peer_comparison/sensitivity/football_field/price/eps_pe/waterfall/radar）
- [x] HTML 报告模板（3个模板：equity_research/comps/dcf，Jinja2 + inline CSS）
- [x] PDF 输出（weasyprint，服务端已连通）
- [x] Desktop 多面板 Workspace（Layout.tsx 左右双面板 + 4 tabs：research/dcf/comps/settings）
- [x] Desktop 图表组件（recharts，9个组件与 Python 端一一对应）
- [x] Desktop Settings 页面（API keys + 模型选择 + SEC user-agent）
- [x] 报告预览 + 下载按钮（ReportActions.tsx + /api/report/html + /api/report/pdf 端点）
- [x] **Pipeline → 报告 context 连线**（build_report_context + report_cache in deps，3 个 pipeline tool 写入缓存，miss → 404）

## P2d: 超越 FinRobot（新增管线 + Excel 输出）

> Spec: `specs/P2d.md` | 完成于 2026-04-03

- [x] LBO pipeline + compute/lbo.py（`LBOInputs/LBOYear/LBOResult` 模型 + 确定性 IRR/MOIC 计算 + 22 测试）
- [x] IC Memo pipeline（运行 DCF + LBO，IRR < 15% 代码强制 PASS，ICFinancials 模型）
- [x] Earnings Analysis pipeline（beat/miss/inline ±2% 阈值 + FMP earnings-surprises endpoint + 19 测试）
- [x] spreadsheet_gen（openpyxl Excel：DCF 3 sheets + LBO 3 sheets + Comps，条件格式 + 12 测试）
- [x] SEC 10-K RAG（BM25Index + chunk_text + SEC provider 10k_rag capability + 13 测试）
- [x] CLI commands：finagent lbo / finagent earnings / finagent ic-memo
- [x] API endpoint：/api/export/excel/{dcf|lbo|comps}/{ticker}
- [x] Orchestrator tools：run_lbo_analysis / run_earnings_analysis / run_ic_memo
- [x] openpyxl + rank-bm25 added to pyproject.toml
- [x] 全部测试通过（552 passed）

## P3: 从壳子到产品（Streaming + SDK + 数据验证 + 模型路由）

> Spec: `specs/P3.md` | 完成于 2026-04-10

- [x] Track 1: Pipeline streaming（进度回调 + CLI 实时输出 + Server SSE 端点）
- [x] Track 2: Python SDK（`from finagent import FinAgent; agent.research("AAPL")`）
- [x] Track 3: 多源数据交叉验证（N7 — revenue/EBITDA 15% 阈值自动告警）
- [x] Track 4: 模型路由（per-role model override，便宜步骤用快模型）
- [x] Track 5: Prompt 优化（最近 2 步全文 + 更早步骤 1 行摘要）

> 后续审计发现 6 处缺陷 + 7 处改进项，Tier 1 已修，其余见下方「P3 审计待办」。

## P3 审计待办（2026-04-10）

> 完整审计报告：2026-04-10 代码审查。已修复项的 commit 见 `git log --grep "P3-audit"`。
> 优先级：**Tier 1** = 阻断开源发布；**Tier 2** = 影响数据可信度；**Tier 3** = 工程质量。

### ✅ Tier 1 — 已修（不可延后的 blocker/regression/lie）

- [x] **D1**: SSE `run_pipeline` 的 `except Exception` 回归 — 吞 CancelledError 破坏客户端
  断连清理（commit `a89bcc9`）
- [x] **D2**: SDK 缺少 fail-fast 配置校验，`_validate_model_config` 只在 CLI 路径生效 —
  迁到 `FinAgentSettings.validate_runtime_config()`，CLI 和 SDK 共用（commit `8fb5229`）
- [x] **D3**: LBO Excel 导出 `ltm_ebitda = entry_debt` + 硬编码 placeholder 占位符输出错数据 —
  改 501 直到 `LBOInputs` 持久化到 `report_cache`（commit `308449a`）
- [x] **I4**: cross-validation 合并丢弃 secondary provider 的 warnings — 改为合并去重
  （commit `12e6249`）

### Tier 2 — 数据可信度（P4 前修）

- [x] **D4: 交叉校验只比对前两个 provider** — `finagent/engine/data/layer.py`。
  当 FMP/Finnhub/yfinance 三个都启用时，FMP 只和 Finnhub 对账，yfinance 永远不参与。
  两个 TTM 数据源恰好一致时，FY 源本可暴露的差异被错过。
  **决策点**：先定语义——迭代所有后续 provider 合并 discrepancy（推荐），还是
  文档化为「只比对主备两源」？语义定了再动代码。

- [x] **D5: 交叉校验对空数据 secondary 无告警** — `validator.py` + `layer.py`。
  secondary 返回 `DataResult(data={})`（不抛 `ProviderError` 但数据为空）时，
  `cross_validate` 对每个字段都 continue，返回空 list → 用户看不到 secondary 实际没数据。
  真实场景：FMP 免费额度耗尽时返回 error payload 被包成空 `DataResult`。
  **修法**：`cross_validate` 开头检查空数据并返回 explicit warning；`DataLayer.fetch`
  在 secondary 明显为空时跳过而非当作"已校验"。

- [x] **D6: compact context mode 对纯文本步骤有信息损失** — `pipelines/base.py:_gather_data`。
  Step N-3 及更早的纯文本输出（无 `StepOutput.structured`）在 prompt 里只剩
  `[Previous: xxx — N words]` 占位符，全文丢失。40-60% 节省 claim 没有基准测试佐证。
  **修法**：先量化——跑一次真实 5 步 pipeline，比对 step 5 产出质量是否退化；
  不要凭感觉改。然后选：1) 占位符附首 200 字 fallback；2) 在测试里加断言锁定节省比例，
  否则删除 commit message 的数字 claim。

### Tier 3 — 工程质量（P4 候选）

- [x] **I1: SSE 端点每次请求重建 5 个 sub-agents** — `server.py`。
  每次 `/api/pipeline/stream/...` 都调 `create_sub_agents(...)`，重新加载 5 个
  instructions markdown + 初始化 5 个 `Agent`。SDK 的 `_ensure_deps` 会缓存，行为不一致。
  **修法**：在 lifespan 里建好 `app.state.sub_agents`，SSE handler 直接取。

- [x] **I2: SSE `complete` 事件截断 2000 字** — `server.py`。
  `result.format_summary()[:2000]` 截断完整报告，前端可能误以为这就是完整结果。
  **修法**：`complete` 事件改为只返回 `{"event": "complete", "full_report_url":
  "/api/report/html?ticker=..."}`，不内嵌任何内容，强迫消费者走正规通道。

- [x] **I3: `CliProgress` 在重试时产生乱序终端输出** — `cli.py:CliProgress`。
  `on_step_start` 用 `nl=False`，但 retry 后的 `on_step_end` 会写出孤立的 ` done (3.2s)`。
  **修法**：retry 后的 end 重新打印步骤名，或全部 progress 改换行模式。

- [x] **I5: SDK `_sub_agents: dict | None` 类型弱化** — `sdk.py`。
  没有泛型。SDK 是对外契约面，类型应该打满 `dict[str, Agent] | None`。

- [x] **I6: SDK sync API 与 `DataCache` 的事件循环耦合脆弱** — `sdk.py:_run_sync`。
  持久事件循环 + aiosqlite worker thread 在 `_connection.close()` 返回后可能仍有异步回调
  （测试输出已出现 `Event loop is closed` warning）。多 FinAgent 实例会互相干扰。
  **修法**（任选）：1) `close()` 关 loop 前 `await asyncio.sleep(0)` 让 aiosqlite
  清空回调；2) 用 `AsyncExitStack` 管理 `DataCache` 生命周期；3) 默认只暴露 async API，
  sync 只在显式 "script mode" 入口提供。

- [ ] **I7: `DataLayer.fetch` 依赖 `data_type == DataType.FINANCIALS` 的 StrEnum 隐式转换** —
  `layer.py`。能工作，但是 S3 魔法字符串问题的子案例。
  **修法**：`fetch()` 开头 `data_type = DataType(data_type)` 强制类型化。

## P7: FinRobot 完整功能对标 + 报告质量修复

> Spec: `specs/P7.md` + `specs/P7-fixes.md`

### Track 0 — 报告质量修复
- [x] 0.1: 删除中英文重复翻译
- [x] 0.2: Markdown → HTML 渲染（`_markdown_to_html` filter）
- [x] 0.3: 公司名显示修复（`company_name` 字段透传）
- [x] 0.4: auto_bold filter 接入模板

### Track A — 量化回测
- [x] A.1: 回测引擎抽象层（`BacktestConfig`/`BacktestResult`/`BacktestEngine`）
- [x] A.2: BackTrader 适配器（SMA 策略 + 4 分析器 + equity curve PNG）
- [x] A.3: CLI `finagent backtest`
- [x] A.4: SDK `abacktest`/`backtest`
- [x] A.5: LLM 策略选择 agent（`run_strategy_selection`）

### Track B — 独立财务分析
- [x] B.1: CLI `finagent analyze`（6 种分析类型）
- [x] B.2: 分析指令库（`prompts.py`）
- [x] B.3: SDK `aanalyze`/`analyze`

### Track C — RAG Q&A
- [x] C.1: CLI `finagent ask`
- [x] C.2: 可选 embedding RAG（`EmbeddingIndex`，numpy cosine similarity）
- [x] C.3: SDK `aask`/`ask`

### Track D — Web App
- [x] D.1: Web 前端（FastAPI + Jinja2 + Tailwind CDN）
- [x] D.2: 任务管理（`tasks.py`，SSE streaming）
- [x] D.3: 集成到 `server.py`
- [x] D.4: 部署脚本（`deploy.sh`）

### Track E — Tutorials
- [x] E.1: `tutorials/01_equity_research.ipynb`
- [x] E.2: `tutorials/02_dcf_valuation.ipynb`
- [x] E.3: `tutorials/03_backtest.ipynb`
- [x] E.4: `tutorials/04_rag_qa.ipynb`

## Desktop V1 Rewrite (Current)

> Spec: `PHASE2-desktop-rewrite.md` + `SPEC-desktop-v1.md`

### Phase 1 — 功能连通（完成）
- [x] OpenAPI 类型生成 + openapi-fetch client
- [x] React Query + Zustand 状态管理
- [x] Settings 视图（keychain 存储 API keys）
- [x] TickerWorkspace 主视图（单页工作流）
- [x] FinancialsPanel（实时数据）
- [x] PipelineRunner（SSE 进度流）
- [x] AssumptionsEditor（DCF 假设滑块）
- [x] ValuationCard + SensitivityHeatmap + WaterfallChart
- [x] ExportBar（Excel/HTML/PDF）
- [x] WarningBanner（数据质量警告）
- [x] 后端路由拆分（settings/compute/data/export/runs）
- [x] 端口从 8000 改为 8321（避免与其他服务冲突）

### Phase 2 — UI 打磨（待做）
- [ ] 专业金融界面视觉升级（配色/排版/间距/卡片设计）
- [ ] 左右双栏布局（左栏操作面板，右栏分析结果）
- [ ] 图表交互增强（tooltip/zoom/切换时间段）
- [ ] 加载状态/骨架屏/动画过渡
- [ ] 响应式布局适配

## P4: Packaging + Memory (Future)
- [ ] Memory system（跨会话上下文）
- [ ] Skill composition（链式 skill 组合）
- [ ] PyInstaller + electron-builder（可执行文件分发）

## Future — QuantDinger 借鉴项

> 参考项目: QuantDinger (`/Desktop/code/Fin/QuantDinger`)
> 成熟的量化交易平台，以下功能可直接参考其实现模式。

### 数据源架构升级
- [ ] DataSourceFactory 模式重构 — 参考 QuantDinger `data_sources/factory.py`，统一归一化返回格式，新增 provider 不碰上层代码
- [ ] A 股数据源（akshare） — 参考 `akshare_data_source.py`，解决 A 股/港股数据空白
- [ ] 港股数据源（腾讯接口） — 参考 `tencent_data_source.py`
- [ ] 断路器（Circuit Breaker） — provider 连续失败时自动熔断，防止拖慢整个 pipeline
- [ ] 数据源缓存分层（TTL 按 timeframe 差异化：日内 5m / 日线 30m）

### Agent 集成（MCP Gateway）
- [ ] MCP Server — 参考 QuantDinger `mcp_server/`，让 Claude/Cursor/Codex 直接调用 FinAgent 做分析
- [ ] Agent Token 认证 — 独立于用户 session，scope 控制（R=Read/W=Write/B=Backtest）
- [ ] 审计日志 — 每次 Agent 调用记录参数和结果

### AI 分析闭环
- [ ] 分析校准反馈环 — 参考 `FastAnalysisService`，记录分析结论 + 后续市场表现，校准信号阈值
- [ ] 分析记忆/RAG — 跨会话积累分析上下文，避免重复工作

## Future Optimizations
- [ ] CLI streaming output: use agent.run_stream() instead of run_sync() for real-time text output
- [ ] Reduce pipeline prompt size: don't pass full previous step output, pass a summary
- [ ] Step 5 (report) can concatenate step 1-4 outputs directly without LLM call
- [ ] Use smaller/faster models for simple steps (data collection doesn't need LLM)
- [ ] Parallelize independent steps (peer_analysis and financial_modeling can run concurrently)
