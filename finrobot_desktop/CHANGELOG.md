# Changelog

All notable changes to this project will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- shares_outstanding silent fallback to 1 → derived from market_cap/price with warning (C1)
- tax_rate hardcoded 0.21 → parametrized in ForecastAssumptions (C2)
- LBO IRR formula warning not surfaced to users (C4)
- ruff 20 errors + mypy 131 errors → zero (C3)

### Changed
- FinancialData facade removed — access via sub-models (S3)
- PipelineStep uses Strategy pattern for executor/validator (S6)
- Shared financial data step extracted to _helpers.py (S5)
- Provider declares financials_fields + extractor uses TypedDict (S4)

### Added
- External-reference tests for WACC, DCF, multiples, LBO (S1)
- Pre-commit hooks (ruff + standard hooks) (M3)
- PEP 561 py.typed marker (M5)

## [0.1.0] - 2026-04-10 (P3)

### Added
- ProgressCallback Protocol for real-time pipeline events
- SSE streaming endpoint `/api/pipeline/stream/{type}/{ticker}`
- Per-role model routing (model_data, model_analysis, etc.)
- Cross-provider data validation for financials
- Python SDK (`from finagent import FinAgent`)
- Compact context mode for multi-step pipelines

## [0.0.5] - 2026-04-03 (P2d)

### Added
- LBO analysis pipeline with deterministic IRR/MOIC
- Earnings quality analysis pipeline
- IC Memo pipeline with IRR hurdle gate
- Excel export for DCF/LBO/Comps
- BM25-based RAG for SEC 10-K filings

## [0.0.4] - 2026-04-02 (P2c)

### Added
- HTML/PDF equity research reports
- 11 chart types (football field, waterfall, sensitivity, etc.)
- FinRobot baseline feature parity

## [0.0.3] - 2026-04-01 (P2a)

### Added
- Multi-provider data layer (FMP, Finnhub, yfinance, SEC EDGAR)
- Rate limiting per provider
- Stale cache fallback with prominent warnings

## [0.0.2] - 2026-03-31 (P1.5)

### Added
- Deterministic compute layer (WACC, DCF, multiples)
- Typed pipeline with structured output validation
- Financial data extraction from provider responses

## [0.0.1] - 2026-03-30 (P0-P1a)

### Added
- Initial project structure
- PydanticAI + FastAPI foundation
- Skill ecosystem (56 vendored skills)
- CLI (run, research, comps, dcf, serve)
