# FinAgent

> A financial AI agent platform with extensible skill ecosystem.

**Status: P2c — FinRobot Baseline + Desktop UI (In Development)**

## What is FinAgent

FinAgent is a financial-domain AI agent platform that bridges the gap between academic financial AI tools (powerful but notebook-only) and generic agent frameworks (capable but financially illiterate).

- **Skill Ecosystem** — 56 financial analysis skills (sourced from Anthropic's financial-services-plugins). Write your own in Markdown.
- **Code-Enforced Pipelines** — Equity research, DCF, comps analysis run as step-by-step pipelines. Code guarantees execution order; skills provide methodology. The LLM decides *how* to analyze, never *whether* to skip a step.
- **Data Layer** — yfinance (built-in, free), FMP (optional, requires API key — provides D&A data for standard DCF formula), Finnhub (optional, requires API key), SEC EDGAR (free, 10-K summaries). Automatic chain fallback: FMP → Finnhub → yfinance.
- **CLI** — `finagent run` / `finagent research` / `finagent comps` / `finagent dcf`. Desktop app and SDK planned.

## Who is FinAgent for

FinAgent is for **financial professionals who want AI-assisted analysis with computational discipline** — buy-side researchers, independent analysts, small fund managers. If you use ChatGPT for financial analysis but worry about hallucinated numbers and skipped steps, FinAgent gives you code-enforced pipelines where the math is deterministic and every step must complete.

**Current status**: P2c (FinRobot baseline + Desktop UI). The engine runs pipelines with deterministic financial math, multi-source data (FMP/Finnhub/SEC EDGAR/yfinance with chain fallback), and standard DCF formulas. See [Roadmap](#roadmap) for timeline.

## Quick Start

```bash
pip install -e ".[dev]"

# Quick question
finagent run "What's AAPL's PE ratio?"

# Full equity research pipeline
finagent research AAPL

# Comparable company analysis
finagent comps AAPL

# DCF valuation
finagent dcf AAPL

# Start server (for desktop app)
finagent serve
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
