# FinAgent

> 给普通人看得懂的基本面分析 — 确定性金融计算 + LLM 中文叙事

**Status: P7 feature-complete · 当前迭代 P8（散户体验 + 工程债）**

## What is FinAgent

FinAgent 是开源的金融分析平台。**核心赌注：数字由代码算出，判断由 LLM 给出。LLM 永远不产出无法追溯到函数调用的数字。**

- **散户友好** — 中文界面、术语 hover 白话解释、估值结论一行大字、可转发股友群的 3 段话报告
- **代码强制 Pipeline** — Equity Research / DCF / Comps / LBO / IC Memo / Earnings Analysis 按步骤运行；代码强制顺序，skill 提供方法论，LLM 决定 *怎么* 分析，从不决定 *是否* 跳过
- **架构红线 codify 成 pytest** — `tests/audit/test_architecture.py` 用 AST 扫描禁止 LangChain/LangGraph/AutoGen/LiteLLM，禁止 `except Exception`、`print()`，强制 compute/models 叶子层
- **多源数据 + 自动交叉校验** — yfinance（免费默认）/ FMP（可选）/ Finnhub（可选）/ SEC EDGAR（免费），revenue/EBITDA 跨源差异 >15% 自动告警
- **接口齐全** — CLI / Python SDK / Web UI / 桌面 App（Tauri 2 + React 19）

## Who is FinAgent for

- **散户与量化新手**：要简洁好看、看懂大方向。FinAgent 给中文结论 + 一句话理由 + 数据来源可追溯
- **开发者与工程师**：要新技术、干净架构。FinAgent 用 PydanticAI（不是 LangChain）、Tauri 2、React 19、uv、mypy strict，架构红线代码强制

如果你用 ChatGPT 分析股票但担心数字是编的、步骤是跳的 — FinAgent 给你代码强制的 pipeline，数学是确定性的，每一步必须完成。

## vs LangChain / FinRobot / OpenBB

- **vs LangChain** — FinAgent 用 PydanticAI、不让 LLM 自由发挥产生幻觉数字；架构红线在 CI 强制
- **vs FinRobot** — FinRobot 是 paper 风格 notebook、agent prompt 互调；FinAgent 把"数据→建模→报告"写成 typed pipeline + Pydantic 模型契约
- **vs OpenBB** — OpenBB 走终端 + 全宇宙数据源；FinAgent 走 AI agent + 桌面 GUI 给非专业用户

## Quick Start

**FMP / Finnhub API key 是可选的** — 不配也能跑，yfinance 已能算 DCF（D&A 用回退公式）。配了之后数据更准 + 多源交叉校验自动启用。

```bash
uv sync                                  # 推荐用 uv，不要 pip
# 或：pip install -e ".[dev]"

# 闲聊式提问
finagent run "AAPL 的市盈率多少？"

# 完整股票研究 pipeline
finagent research AAPL

# 可比公司分析
finagent comps AAPL

# DCF 估值
finagent dcf AAPL

# LBO 模型
finagent lbo AAPL

# 财报分析（beat/miss）
finagent earnings AAPL

# 投决会备忘录（DCF + LBO 综合）
finagent ic-memo AAPL

# 单项财务分析（6 种）
finagent analyze AAPL income
finagent analyze AAPL cashflow

# 10-K RAG 问答
finagent ask AAPL "主要风险因素有哪些？"

# 量化回测
finagent backtest AAPL --strategy sma_crossover --start 2023-01-01 --end 2024-01-01

# LLM 自动选策略
finagent backtest AAPL --start 2023-01-01 --end 2024-01-01 --auto

# 启动服务（Web UI + 桌面 App）
finagent serve
```

### Python SDK

```python
from finagent import FinAgent

agent = FinAgent(model="anthropic:claude-sonnet-4-6")

# Pipeline 分析
result = agent.research("AAPL")
result = agent.dcf("AAPL")
result = agent.comps("AAPL")
result = agent.lbo("AAPL")
result = agent.earnings("AAPL")
result = agent.ic_memo("AAPL")

# 单项分析
text = agent.analyze("AAPL", "cashflow")

# RAG 问答
answer = agent.ask("AAPL", "主要风险因素有哪些？")

# 回测（手动或 LLM 引导）
from finagent.engine.backtest.engine import BacktestConfig
result = agent.backtest(BacktestConfig(ticker="AAPL", strategy="sma_crossover", start_date="2023-01-01", end_date="2024-01-01"))
result = agent.auto_backtest("AAPL", "2023-01-01", "2024-01-01")
```

### 金融假设默认值

默认按美股校准：
- 公司所得税率：21%（美国联邦企业税率）
- 无风险利率：美国 10 年期国债收益率

非美股市场通过 SDK 覆盖：

```python
from finagent.engine.models.financial import ForecastAssumptions

assumptions = ForecastAssumptions(tax_rate=0.196)  # 日本企业税率
```

CLI 层面的非美默认值开关在 BACKLOG（A 股 / 港股 provider 同期推进，参考 QuantDinger）。

> **免责声明**：FinAgent 输出仅供参考，不构成投资建议。财务数据来自公开 API，可能存在误差。重要数字请独立核实。

## Architecture

```
finagent/
├── engine/
│   ├── compute/        # 纯函数金融逻辑（DCF/WACC/LBO/DDM）— 叶子层
│   ├── models/         # Pydantic 金融类型 — 叶子层
│   ├── data/providers/ # FMP/Finnhub/yfinance/SEC，DataProvider ABC
│   ├── pipelines/      # 代码强制步骤顺序 + 每步 validator
│   ├── agents/         # PydanticAI 子 agent
│   └── orchestrator.py # Lead agent + tool 注册
├── routes/             # FastAPI HTTP 端点
├── cli.py / sdk.py / server.py

ui/                     # React 19 + Tauri 2 桌面 UI
tests/
├── audit/              # 架构红线 + 金融公式回归（机械强制）
├── unit / integration / routes
```

**架构红线**（pytest 强制，不可破）：
1. `compute/` 和 `models/` 是叶子层 — 不 import agents/pipelines/orchestrator/LLM 库
2. Pipeline 步骤顺序由代码强制 — 工具包整个 pipeline，不暴露单步
3. 数据 provider 走 `DataProvider` ABC — pipelines 不直接调 SDK
4. 依赖黑名单：No LangChain / LangGraph / AutoGen / LiteLLM，PydanticAI only

详见 `CLAUDE.md` 与 `tests/audit/test_architecture.py`。

## License

Apache 2.0
