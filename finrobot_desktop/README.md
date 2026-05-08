# FinAgent

> A financial AI agent platform with extensible skill ecosystem.

**Status: Feature-complete (P7 delivered) — packaging + memory system planned**

## What is FinAgent

FinAgent is a financial-domain AI agent platform that bridges the gap between academic financial AI tools (powerful but notebook-only) and generic agent frameworks (capable but financially illiterate).

- **Skill Ecosystem** — 56 financial analysis skills (sourced from Anthropic's financial-services-plugins). Write your own in Markdown.
- **Code-Enforced Pipelines** — Equity research, DCF, comps, LBO, IC memo, and earnings analysis run as step-by-step pipelines. Code guarantees execution order; skills provide methodology. The LLM decides *how* to analyze, never *whether* to skip a step.
- **Data Layer** — yfinance (built-in, free), FMP (optional, requires API key — provides D&A data for standard DCF formula), Finnhub (optional, requires API key), SEC EDGAR (free, 10-K summaries). Automatic chain fallback: FMP → Finnhub → yfinance.
- **Interfaces** — CLI, Python SDK, Web UI, Desktop app (Electron + React).

## Who is FinAgent for

FinAgent is for **financial professionals who want AI-assisted analysis with computational discipline** — buy-side researchers, independent analysts, small fund managers. If you use ChatGPT for financial analysis but worry about hallucinated numbers and skipped steps, FinAgent gives you code-enforced pipelines where the math is deterministic and every step must complete.

## Quick Start

```bash
pip install -e ".[dev]"

# Quick question (conversational mode)
finagent run "What's AAPL's PE ratio?"

# Full equity research pipeline
finagent research AAPL

# Comparable company analysis
finagent comps AAPL

# DCF valuation
finagent dcf AAPL

# LBO model
finagent lbo AAPL

# Earnings analysis
finagent earnings AAPL

# IC memo (combines DCF + LBO)
finagent ic-memo AAPL

# Standalone financial analysis (6 types)
finagent analyze income AAPL
finagent analyze cashflow AAPL

# 10-K RAG Q&A
finagent ask AAPL "What are the main risk factors?"

# Quantitative backtest
finagent backtest AAPL --strategy sma_crossover --start 2023-01-01 --end 2024-01-01

# LLM-guided automatic strategy selection
finagent backtest AAPL --start 2023-01-01 --end 2024-01-01 --auto

# Start server (Web UI + Desktop app)
finagent serve
```

### Python SDK

```python
from finagent import FinAgent

agent = FinAgent(model="anthropic:claude-sonnet-4-6")

# Pipeline analysis
result = agent.research("AAPL")
result = agent.dcf("AAPL")
result = agent.comps("AAPL")

# Standalone analysis
text = agent.analyze("AAPL", "cashflow")

# RAG Q&A
answer = agent.ask("AAPL", "What are the risk factors?")

# Backtest (manual or LLM-guided)
from finagent.engine.backtest.engine import BacktestConfig
result = agent.backtest(BacktestConfig(ticker="AAPL", strategy="sma_crossover", start_date="2023-01-01", end_date="2024-01-01"))
result = agent.auto_backtest("AAPL", "2023-01-01", "2024-01-01")
```

### Financial Assumptions

Default financial assumptions are calibrated for US equities:
- Tax rate: 21% (US federal corporate rate)
- Risk-free rate: US 10-Year Treasury yield

For non-US markets, override via the SDK:

```python
from finagent.engine.models.financial import ForecastAssumptions

assumptions = ForecastAssumptions(tax_rate=0.196)  # Japan corporate tax
```

CLI flag support for non-US defaults is planned for a future release.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design document.

## License

Apache 2.0
