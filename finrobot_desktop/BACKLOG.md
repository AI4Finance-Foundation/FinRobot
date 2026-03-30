# FinAgent Backlog

## Post-P0 Quick Wins
- [ ] CLI streaming output: use agent.run_stream() instead of run_sync() for real-time text output
- [ ] Reduce pipeline prompt size: don't pass full previous step output, pass a summary
- [ ] Step 5 (report) can concatenate step 1-4 outputs directly without LLM call
- [ ] Add finagent_cache.db to .gitignore

## P1a: Skill Runtime
- [ ] Skill loader + registry + activate_skill tool
- [ ] 41 Anthropic skills in FinAgent native format

## P1b: Sub-agents + Optimization
- [ ] Split lead_agent into data/analysis/modeling/synthesis/report agents
- [ ] Use smaller/faster models for simple steps (data collection doesn't need LLM)
- [ ] Parallelize independent steps (peer_analysis and financial_modeling can run concurrently)
- [ ] Strict validators (replace validate_is_non_empty with domain-specific validators)

## P1c: Desktop App + Streaming
- [ ] Electron + React + useChat
- [ ] SSE streaming for pipeline progress
- [ ] CLI streaming output (finagent run / finagent research)

## P2a-P2b: Data Layer
- [ ] FMP + Finnhub providers via FinRobot data adapter (subprocess isolated)
- [ ] SEC EDGAR provider
- [ ] Multi-source cross-validation (compare yfinance vs FMP, flag discrepancies)
- [ ] Full cache + fallback chain

## P2c: Advanced Pipelines + Tools
- [ ] Comps pipeline (6 steps)
- [ ] DCF pipeline (6 steps)
- [ ] LBO, earnings, IC memo pipelines
- [ ] spreadsheet_gen tool — Excel output with formulas (openpyxl)

## P3a: Advanced
- [ ] Memory system
- [ ] Skill composition
- [ ] Python SDK

## P3b: Packaging
- [ ] PyInstaller + electron-builder
