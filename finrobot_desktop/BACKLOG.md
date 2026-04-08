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

> Spec: `specs/P3.md`

- [ ] Track 1: Pipeline streaming（进度回调 + CLI 实时输出 + Server SSE 端点）
- [ ] Track 2: Python SDK（`from finagent import FinAgent; agent.research("AAPL")`）
- [ ] Track 3: 多源数据交叉验证（N7 — revenue/EBITDA 15% 阈值自动告警）
- [ ] Track 4: 模型路由（per-role model override，便宜步骤用快模型）
- [ ] Track 5: Prompt 优化（只传最近一步文本 + structured data，~60% 减量）

## P4: Packaging + Memory (Future)
- [ ] Memory system（跨会话上下文）
- [ ] Skill composition（链式 skill 组合）
- [ ] PyInstaller + electron-builder（可执行文件分发）

## Future Optimizations
- [ ] CLI streaming output: use agent.run_stream() instead of run_sync() for real-time text output
- [ ] Reduce pipeline prompt size: don't pass full previous step output, pass a summary
- [ ] Step 5 (report) can concatenate step 1-4 outputs directly without LLM call
- [ ] Use smaller/faster models for simple steps (data collection doesn't need LLM)
- [ ] Parallelize independent steps (peer_analysis and financial_modeling can run concurrently)
