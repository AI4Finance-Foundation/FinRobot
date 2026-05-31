# FinRobot Desktop

> Investment-bank-grade equity research, in a desktop app — deterministic finance numbers + LLM narrative, every figure traceable back to a function call.

FinRobot 是面向金融分析师 / 量化研究员 / 主动投资者的开源桌面端股票研究 app。一份 `research` pipeline 一键产出 13 章 artifact：Cover · Investment Thesis · Company Overview · Financial Analysis · Valuation · Recent News · Sensitivity · Catalysts · Technical & Advanced · Competitive Landscape · Financial Data · Ownership & Governance · Disclaimer。

**核心赌注：数字由代码算出，判断由 LLM 给出。** LLM 永远不产出无法追溯到 `engine/compute/*` 函数调用的数字。

## Quick Start

```bash
uv sync
finrobot serve              # 后端
cd ui && npm run tauri dev  # 桌面端
```

CLI / SDK / 架构契约 / 工程红线详见 [`CLAUDE.md`](CLAUDE.md) · [`AGENTS.md`](AGENTS.md)。

## License

Apache 2.0
