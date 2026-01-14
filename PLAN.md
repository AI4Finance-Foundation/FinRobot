# FinRobot Migration Plan

> Roadmap for transforming FinRobot into an enterprise-grade, AI-powered investment management system.

## Vision

Build an autonomous multi-agent system for managing investment funds using AI agents that:

- Monitor markets and news in real-time
- Analyze SEC filings and investment bank reports
- Calculate risk metrics and generate alerts
- Recommend portfolio rebalancing
- Execute trades (with human approval)

```
┌─────────────────────────────────────────────────────────────┐
│              AGENTIC INVESTMENT FUND SYSTEM                 │
│                                                             │
│    Fund Manager (Leader) → Stock Analyst + Risk Manager     │
│                              + Trading Agent                │
│                                                             │
│    Data: YFinance | FinnHub | SEC | OpenBB | News | Alt     │
│                                                             │
│    Dashboard: mi_patrimonio (Next.js) ~€945K+               │
└─────────────────────────────────────────────────────────────┘
```

---

## Macro Phases

| Phase | Goal | Status |
|-------|------|--------|
| **A: Stabilize** | Clean codebase, establish governance (Phases 0-7) | In Progress |
| **B: Build Agents** | Create agentic investment system (Phases 8-12) | Not Started |

---

## Phase A: Stabilize

### Phase 0: Governance Setup

- [x] Create `CLAUDE.md` (coding standards)
- [x] Create `PLAN.md` (this file)
- [ ] Configure `pyproject.toml` with ruff + mypy
- [ ] Update `tsconfig.json` with strict settings
- [ ] Create `.pre-commit-config.yaml`
- [ ] Create PR template

### Phase 1: Security Fixes

| Task | File | Status |
|------|------|--------|
| Remove bare `except:` | `sec_utils.py:87` | ✅ Done |
| Remove bare `except:` | `price_server.py:269` | ✅ Done |
| Remove bare `except:` | `ai_advisor.py:122` | ✅ Done |
| Remove bare `except:` | `setup.py:7` | ✅ Done |
| Remove bare `except:` | `xbrl_parser.py:288` | ✅ Done |
| API keys in URLs | `fmp_utils.py` | N/A (FMP API requires key in URL) |
| Add input validation | `mi_patrimonio/`, `vercel-patrimonio/` | ✅ Done |

### Phase 2: Delete Redundant Code

| Task | Status |
|------|--------|
| Delete `vercel-finrobot/` directory | ✅ Done |
| Archive `tutorials_beginner/`, `tutorials_advanced/`, `experiments/` | ✅ Done |
| Remove commented code in data sources | ✅ Done |

### Phase 3: English Migration

| Spanish | English | Status |
|---------|---------|--------|
| `config_portfolios.py` | All fields migrated to English | ✅ Done |
| `PERFILES_RIESGO` | `RISK_PROFILES` | ✅ Done |
| `CATEGORIAS_ACTIVOS` | `ASSET_CATEGORIES` | ✅ Done |
| `ETFS_RECOMENDADOS` | `RECOMMENDED_ETFS` | ✅ Done |
| `calcular_distribucion` | `calculate_distribution` | ✅ Done |
| `obtener_cotizacion` | `get_quote` | ✅ Done |
| `obtener_cotizaciones_batch` | `get_quotes_batch` | ✅ Done |
| `obtener_historico` | `get_historical` | ✅ Done |
| `obtener_tipo_cambio` | `get_exchange_rate` | ✅ Done |
| `PerfilInversor` | `InvestorProfile` | ✅ Done |
| `Posicion` | `Position` | ✅ Done |
| `renta_variable` | `equities` | ✅ Done |
| `renta_fija` | `fixed_income` | ✅ Done |

**Note**: All core modules (`config.py`, `portfolio.py`, `data_provider.py`, `config_portfolios.py`) include legacy aliases for backward compatibility with existing code.

### Phase 4: Testing Infrastructure

| Task | Status |
|------|--------|
| Setup pytest + fixtures | Pending |
| Create `test_portfolio.py` | Pending |
| Create `test_risk_analyzer.py` | Pending |
| Setup Vitest for TypeScript | Pending |
| Create `useLivePrices.test.ts` | Pending |
| Achieve 70% coverage | Pending |

### Phase 5: Error Handling Standardization

| Task | Status |
|------|--------|
| Create `exceptions.py` (Python) | Pending |
| Create `errors.ts` (TypeScript) | Pending |
| Replace `print()` with `logger.error()` | Pending |
| Add error codes to all exceptions | Pending |

### Phase 6: Architecture Cleanup

| Task | Status |
|------|--------|
| Remove global variables | Pending |
| Create abstract `DataProvider` base class | Pending |
| Implement dependency injection | Pending |

### Phase 7: Streamlit Migration

| Task | Status |
|------|--------|
| Identify Streamlit features | Pending |
| Create Next.js equivalents | Pending |
| Delete `app.py`, `app_familia.py` | Pending |

---

## Phase B: Build Agentic System

> **Prerequisite**: Complete Phase A first.

### Phase 8: Agent Infrastructure

- [ ] Create `finrobot/agents/fund_agents.py`
- [ ] Define Portfolio_Manager, Stock_Analyst, Risk_Manager, Trading_Agent
- [ ] Create agent configuration files

### Phase 9: Data Source Extensions

- [ ] Create `news_utils.py` (financial news aggregation)
- [ ] Create `research_utils.py` (investment bank PDF parsing)
- [ ] Create `alternative_utils.py` (sentiment, insider, short interest)

### Phase 10: Multi-Agent Workflow

- [ ] Create `InvestmentFundWorkflow` class
- [ ] Implement `daily_analysis()` method
- [ ] Implement `research_stock()` method
- [ ] Implement `rebalance_portfolio()` method
- [ ] Create `AgentService` for mi_patrimonio integration

### Phase 11: Scheduled Monitoring

- [ ] Create `PortfolioMonitor` with scheduled tasks
- [ ] Implement morning briefing (9:00 AM)
- [ ] Implement market close summary (4:30 PM)
- [ ] Implement weekly review (Friday 5:00 PM)
- [ ] Create `AlertRulesEngine` with configurable rules

### Phase 12: Dashboard Integration

- [ ] Create `/api/agent-insights` endpoint
- [ ] Create `AgentInsights.tsx` component
- [ ] Integrate into main dashboard

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Code coverage | 0% | ≥ 70% |
| Bare excepts | 5+ | 0 |
| Global variables | 5+ | 0 |
| Spanish identifiers | 50+ | 0 |
| TypeScript strict errors | Unknown | 0 |
| Agent response time | N/A | < 30s |
| Dashboard load time | Unknown | < 2s |

---

## Key Files

### To Modify (Phase A)

| File | Changes |
|------|---------|
| `finrobot/data_source/fmp_utils.py` | Remove globals, fix API keys |
| `finrobot/data_source/finnhub_utils.py` | Remove globals, add error handling |
| `finrobot/data_source/sec_utils.py` | Remove bare excepts |
| `mi_patrimonio/portfolio.py` | Rename to English |
| `mi_patrimonio/config_portfolios.py` | Rename to English |
| `mi_patrimonio/price_server.py` | Fix error handling |
| `vercel-patrimonio/lib/useLivePrices.ts` | Add error types |
| `vercel-patrimonio/tsconfig.json` | Enable strict options |

### To Create (Phase A)

| File | Purpose |
|------|---------|
| `pyproject.toml` | Python project config |
| `.pre-commit-config.yaml` | Pre-commit hooks |
| `mi_patrimonio/core/exceptions.py` | Custom exceptions |
| `vercel-patrimonio/lib/errors.ts` | TypeScript error types |
| `mi_patrimonio/tests/test_portfolio.py` | Portfolio tests |

### To Create (Phase B)

| File | Purpose |
|------|---------|
| `finrobot/agents/fund_agents.py` | Investment fund agents |
| `finrobot/workflows/investment_fund.py` | Multi-agent workflow |
| `finrobot/data_source/news_utils.py` | News aggregation |
| `finrobot/data_source/research_utils.py` | IB report parsing |
| `mi_patrimonio/services/agent_service.py` | Agent integration |
| `mi_patrimonio/services/alerts.py` | Alert rules |
| `vercel-patrimonio/components/AgentInsights.tsx` | UI component |

### To Delete (Phase A)

| Path | Reason |
|------|--------|
| `vercel-finrobot/` | Redundant duplicate code |
| `tutorials_beginner/` | Archive (not delete) |
| `tutorials_advanced/` | Archive (not delete) |
| `experiments/` | Archive (not delete) |
| `mi_patrimonio/app.py` | Streamlit legacy |
| `mi_patrimonio/app_familia.py` | Streamlit legacy |

---

## Commands Reference

```bash
# Python quality
ruff check .
ruff format .
mypy --strict mi_patrimonio/
pytest --cov=mi_patrimonio --cov-fail-under=70

# TypeScript quality
cd vercel-patrimonio
tsc --noEmit
npm run lint
npm test -- --coverage

# Run services
./start_services.sh all

# Pre-commit
pre-commit install
pre-commit run --all-files
```

---

## Change Log

| Date | Phase | Changes |
|------|-------|---------|
| 2026-01-14 | 0 | Created CLAUDE.md, PLAN.md |
