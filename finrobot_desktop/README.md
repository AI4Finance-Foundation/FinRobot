# FinAgent

> A financial AI agent platform with extensible skill ecosystem.

**Status: P0 — Engine Core (In Development)**

## What is FinAgent

FinAgent is a financial-domain AI agent platform that bridges the gap between academic financial AI tools (powerful but notebook-only) and generic agent frameworks (capable but financially illiterate).

- **Skill Ecosystem** — 41 institutional-grade financial skills built-in. Write your own in Markdown.
- **Code-Enforced Pipelines** — Equity research, DCF, comps analysis run as step-by-step pipelines. Code guarantees execution order; skills provide methodology. The LLM decides *how* to analyze, never *whether* to skip a step.
- **Unified Data Layer** — yfinance, FMP, Finnhub, SEC EDGAR, MCP — one interface.
- **Desktop + CLI + SDK** — Use it however you work.

## Quick Start (P0)

```bash
pip install -e ".[dev]"

# Quick question
finagent run "What's AAPL's PE ratio?"

# Full equity research pipeline
finagent research AAPL

# Start server (for desktop app)
finagent serve
```

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design document.

## License

Apache 2.0
