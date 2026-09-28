# FinRobot: An Open-Source AI Agent Platform for Financial Applications using Large Language Models
[![Downloads](https://static.pepy.tech/badge/finrobot)](https://pepy.tech/project/finrobot)
[![Downloads](https://static.pepy.tech/badge/finrobot/week)](https://pepy.tech/project/finrobot)
[![Join Discord](https://img.shields.io/badge/Discord-Join-blue)](https://discord.gg/trsr8SXpW5)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11-blue.svg)](https://www.python.org/downloads/)
[![PyPI](https://img.shields.io/pypi/v/finrobot.svg)](https://pypi.org/project/finrobot/)
![License](https://img.shields.io/github/license/AI4Finance-Foundation/finrobot.svg?color=brightgreen)
![](https://img.shields.io/github/issues-raw/AI4Finance-Foundation/finrobot?label=Issues)
![](https://img.shields.io/github/issues-closed-raw/AI4Finance-Foundation/finrobot?label=Closed+Issues)
![](https://img.shields.io/github/issues-pr-raw/AI4Finance-Foundation/finrobot?label=Open+PRs)
![](https://img.shields.io/github/issues-pr-closed-raw/AI4Finance-Foundation/finrobot?label=Closed+PRs)
[![FinRobot Desktop](https://img.shields.io/badge/Desktop-v0.1.0-blue)](https://github.com/AI4Finance-Foundation/FinRobot/releases/tag/desktop-v0.1.0)

<div align="center">
<img align="center" src=figs/logo_white_background.jpg width="40%"/>
</div>

**FinRobot** is an AI Agent platform tailored for financial applications, surpassing FinGPT's single-model approach. It unifies multiple AI technologies — including LLMs, reinforcement learning, and quantitative analytics — to power investment research automation, algorithmic trading strategies, and risk assessment, delivering a full-stack intelligent solution for the financial industry.

**Concept of AI Agent**: an AI Agent is an intelligent entity that uses large language models as its brain to perceive its environment, make decisions, and execute actions. Unlike traditional artificial intelligence, AI Agents possess the ability to independently think and utilize tools to progressively achieve given objectives.

[Whitepaper on arXiv](https://arxiv.org/abs/2405.14767) · [Official Academic Page](https://ai4finance.org/research/finrobot-open-source-ai-agent.html)

![Visitors](https://api.visitorbadge.io/api/VisitorHit?user=AI4Finance-Foundation&repo=FinRobot&countColor=%23B17A)
[![Discord](https://dcbadge.limes.pink/api/server/trsr8SXpW5?v=20260320)](https://discord.gg/trsr8SXpW5)

---

## Where to start

FinRobot is three projects sharing one financial domain layer. Each has its own README — pick the one that matches what you want to do.

| Directory | Version | What it is | Choose it to… |
|:---|:---|:---|:---|
| **[`finrobot_desktop/`](./finrobot_desktop/)** | V2 | Native desktop research workstation — PydanticAI + FastAPI + React/Tauri | Run investment-bank-grade research locally, or drive it from the `finrobot` CLI |
| **[`finrobot_equity/`](./finrobot_equity/)** | V1 | Equity research report generator with a FastAPI web interface | Self-host something that turns a ticker into a shareable HTML/PDF report |
| **[`finrobot_autogen/`](./finrobot_autogen/)** | V0 | The original AutoGen multi-agent library — the codebase behind the whitepaper | Learn how financial agents are wired together, or build on a small, readable framework |

`pip install finrobot` installs the V0 package. Its source moved into `finrobot_autogen/`, but the import name did not change — every existing `from finrobot... import ...` keeps working.

---

## 🧬 Architecture Evolution

FinRobot evolves alongside the rapid development of AI-agent frameworks. Rather than being tied to a single agent stack, each generation explores how emerging agent architectures can improve financial analysis, research, and decision-making.

| Version | Agent Framework | Project | Availability | Focus |
|---|---|---|---|---|
| **V0** | AutoGen | [`finrobot_autogen/`](./finrobot_autogen/) | Open source | The original FinRobot multi-agent architecture for financial applications |
| **V1** | OpenAI Agents SDK | [`finrobot_equity/`](./finrobot_equity/) | Open source | Equity-research agents, financial analysis, valuation, and automated report generation |
| **V2** | PydanticAI | [`finrobot_desktop/`](./finrobot_desktop/) | Open source; also hosted at [finrobot.ai/v2](https://finrobot.ai/v2) | Structured, type-safe agent workflows for professional equity research |
| **V3** | DeepSeek-Harness | FinRobot V3 | In development | A more autonomous architecture for financial analysis and decision-making |

> **Our philosophy:** FinRobot is not defined by any single agent framework. We continuously adopt, evaluate, and evolve with state-of-the-art agent architectures while keeping the financial domain layer — tools, workflows, deterministic computation, and decision-making capabilities — at the core.

V0 is kept for educational and reference use; V2 is the current generation.

---

## 🧮 Deterministic compute, LLM narration

A design principle that runs through every generation: **deterministic financial computation** and **LLM-based narration** stay strictly separate.

All financial numbers are produced by pure-Python compute operators, not by the language model. The LLM handles reasoning, synthesis, explanation, and report writing, while valuation outputs — DCF, DDM, LBO, WACC, comparable-company analysis, Monte Carlo simulation — are calculated through deterministic code paths with full provenance.

```
Numbers are code-calculated.
Narratives are LLM-assisted.
Every output is provenance-tracked.
```

---

## 🚀 FinRobot Desktop v0.1.0

A native desktop equity research cockpit powered by a production-grade multi-agent architecture. It takes analysts from market data and company filings to valuation, debate, synthesis, and investment-committee-style reports in one traceable workflow.

👉 **Latest release:** [FinRobot Desktop v0.1.0](https://github.com/AI4Finance-Foundation/FinRobot/releases/tag/desktop-v0.1.0)

For macOS Apple Silicon (M1/M2/M3 or later), download `FinRobot_0.1.0_aarch64.dmg` and drag **FinRobot** into **Applications**. Intel Mac builds are not available in this release.

The app is not yet Apple-notarized, so on first launch macOS may report that it is "damaged." Run this once in Terminal, then open it normally:

```bash
xattr -cr /Applications/FinRobot.app
```

### Multi-agent architecture

A **Lead Agent** orchestrates specialized research agents through a pipeline-driven execution engine: five role-based sub-agents for data, analysis, modeling, synthesis, and reporting, plus three debate agents for the bull case, bear case, and judgment.

```
User Research Request
        ↓
Lead Agent / Orchestrator
        ↓
Data Agent → Analysis Agent → Modeling Agent → Synthesis Agent → Report Agent
        ↓
Bull Agent ↔ Bear Agent → Judge Agent
        ↓
Traceable Investment Research Output
```

### Codebase snapshot

| Layer | What it includes |
|---|---|
| **Full-stack system** | ~184k lines across a Python backend, React/Tauri desktop frontend, Rust shell, and tests |
| **Agent runtime** | 9 agents: lead orchestrator, 5 role-based pipeline agents, 3 debate agents |
| **Research pipelines** | 7 pipelines — company research, DCF, comps, LBO, DDM, earnings, IC memo |
| **Deterministic compute** | 32 pure-Python operators (26 valuation/analysis + 6 audit) and 7 coordinators |
| **Data infrastructure** | 7 providers with failover — FMP, Finnhub, yfinance, SEC EDGAR, Adanos, NewsAggregator, FX |
| **Skills** | 56 analyst playbooks across equity research, investment banking, private equity, and wealth management |
| **Product stack** | PydanticAI, FastAPI, SQLite, React 19, Vite 6, Zustand, Tauri/Rust, Recharts |

Full details in [`finrobot_desktop/README.md`](./finrobot_desktop/README.md).

---

## Getting started

### V2 — the desktop app and CLI

Download the [release](https://github.com/AI4Finance-Foundation/FinRobot/releases/tag/desktop-v0.1.0), or run from source:

```bash
cd finrobot_desktop
uv sync

finrobot research AAPL          # full 13-chapter research artifact
finrobot dcf MSFT               # DCF valuation (auto-switches to DDM where appropriate)
finrobot comps NVDA --peers AMD,INTC
finrobot ic-memo TSLA
finrobot ask AAPL "How exposed is the gross margin to tariffs?"
```

Building the Tauri desktop shell is covered in [`finrobot_desktop/README.md`](./finrobot_desktop/README.md).

### V1 — the equity research web app

```bash
cp finrobot_equity/core/config/config.ini.example finrobot_equity/core/config/config.ini
# edit config.ini: fmp_api_key, openai_api_key, (optional) adanos_api_key

chmod +x deploy.sh
./deploy.sh start          # → http://127.0.0.1:8001
```

| Command | Description |
|:---|:---|
| `./deploy.sh start` | Start the web app (auto-installs dependencies) |
| `./deploy.sh stop` | Stop the application |
| `./deploy.sh restart` | Restart the application |
| `./deploy.sh status` | Check running status |
| `./deploy.sh install` | Install/update dependencies only |

If `deploy.sh` doesn't work in your environment:

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-equity.txt
python run_web_app.py
```

A two-step CLI pipeline is available as well — see [`finrobot_equity/README.md`](./finrobot_equity/README.md).

**Example reports:**
[NVDA](https://ai4finance-foundation.github.io/FinRobot/finrobot_equity/core/output/NVDA_Equity_Research_Report.html) ·
[MSFT](https://ai4finance-foundation.github.io/FinRobot/finrobot_equity/core/output/MSFT_Equity_Research_Report.html) ·
[TSLA](https://ai4finance-foundation.github.io/FinRobot/finrobot_equity/core/output/TSLA_Equity_Research_Report.html) ·
[META](https://ai4finance-foundation.github.io/FinRobot/finrobot_equity/core/output/META_Equity_Research_Report.html) ·
[COP](https://ai4finance-foundation.github.io/FinRobot/finrobot_equity/core/output/COP_Equity_Research_Report.html)

### V0 — the AutoGen framework

**1. Create an environment** (Python 3.10 or 3.11):

```bash
conda create --name finrobot python=3.10
conda activate finrobot
```

**2. Install** — from PyPI, or from source at the **repository root** (`setup.py` maps the `finrobot` package to `finrobot_autogen/finrobot`, so installing from inside that directory won't work):

```bash
git clone https://github.com/AI4Finance-Foundation/FinRobot.git
cd FinRobot
pip install -e .          # or: pip install -U finrobot
```

**3. Configure keys** — both files go in `finrobot_autogen/`, which is where the notebooks look for them. Copy rather than rename: the `*_sample` files are tracked, and your filled-in copies are gitignored.

```bash
cd finrobot_autogen
cp OAI_CONFIG_LIST_sample OAI_CONFIG_LIST     # OpenAI / Azure OpenAI endpoints
cp config_api_keys_sample config_api_keys     # Finnhub, FMP, SEC, Reddit, …
```

**4. Run a tutorial** from `finrobot_autogen/tutorials_beginner/` or `tutorials_advanced/`:

```
agent_annual_report.ipynb        # 10-K → formatted PDF annual report
agent_fingpt_forecaster.ipynb    # market forecast from news + financials
agent_trade_strategist.ipynb     # strategy writing and backtesting
lmm_agent_mplfinance.ipynb       # multimodal agent reading a candlestick chart
lmm_agent_opt_smacross.ipynb     # multimodal SMA-crossover tuning
```

The agent library, workflow types, and full tutorial index are in [`finrobot_autogen/README.md`](./finrobot_autogen/README.md).

---

## Repository layout

```
FinRobot/
├── finrobot_autogen/            # V0 — AutoGen generation (PyPI: pip install finrobot)
│   ├── finrobot/                #   package root — imported as `finrobot`
│   │   ├── agents/              #     agent_library.py, workflow.py, prompts.py
│   │   ├── data_source/         #     finnhub / finnlp / fmp / sec / yfinance / reddit
│   │   ├── functional/          #     analyzer, charting, coding, quantitative, rag, text
│   │   ├── toolkits.py          #     registers Python functions as agent tools
│   │   └── utils.py
│   ├── tutorials_beginner/      #   hands-on tutorials
│   ├── tutorials_advanced/      #   advanced tutorials for FinRobot developers
│   ├── experiments/             #   investment group, multi-factor, portfolio optimization
│   ├── configs/ report/         #   agent configs and sample generated reports
│   ├── FinNLP/                  #   git submodule
│   ├── OAI_CONFIG_LIST_sample
│   ├── config_api_keys_sample
│   └── requirements.txt
│
├── finrobot_desktop/            # V2 — PydanticAI desktop generation (current)
│   ├── finrobot/                #   Python backend (FastAPI + compute engine)
│   │   ├── engine/              #     agents/, pipelines/, compute/, data/
│   │   ├── artifact/            #     report store + output contract gate
│   │   ├── audit/ coverage/ obs/ routes/
│   │   └── cli.py server.py sdk.py
│   ├── desktop/                 #   Tauri shell + React frontend (src/, src-tauri/)
│   ├── skills/                  #   56 analyst playbooks
│   ├── tests/ scripts/ tutorials/
│   └── pyproject.toml uv.lock dev.sh
│
├── finrobot_equity/             # V1 — OpenAI Agents SDK generation
│   ├── core/                    #   analysis engine + 8 section-writing agents
│   └── web_app/                 #   FastAPI web application
├── run_web_app.py               #   V1 launcher (runs from repo root)
├── deploy.sh deploy.gcloud.sh   #   V1 deployment
├── Dockerfile                   #   V1 container build
├── requirements-equity.txt
│
├── .github/workflows/           # desktop CI (backend 3.11/3.12, frontend Node 22/24)
├── setup.py                     # packages V0 (as `finrobot`) + V1 for PyPI
├── LICENSE NOTICE TRADEMARK_POLICY.md
└── README.md
```

---

## 🎬 FinRobot Pro — your personal AI-powered equity research assistant

🌐 https://finrobot.ai/

<div align="center">
  <a href="https://www.youtube.com/watch?v=ebgPiJINi-k" target="_blank">
    <img src="https://github.com/user-attachments/assets/de3b9f9c-50aa-49f0-82c6-3d2b938f4670" width="90%" />
  </a>
</div>

<img width="1490" height="808" alt="image" src="https://github.com/user-attachments/assets/bf56065d-a134-4ff8-99e2-8a1e52258ce7" />

<p align="center">
  ▶️ Click the image above to watch the demo video, or see the short preview below.
</p>

https://github.com/user-attachments/assets/93ec0f1e-e28b-4474-a0bf-a79e0c12f0ff

[FinRobot Pro](https://finrobot.ai/) is an AI-powered equity research platform that automates professional stock analysis using large language models and AI agents:

- **Automated report generation** — professional equity research reports on demand
- **Financial analysis** — income statements, balance sheets, and cash flows
- **Valuation analysis** — P/E, EV/EBITDA multiples, and peer comparison
- **Risk assessment** — comprehensive investment risk evaluation

---

## Research foundation

### The FinRobot ecosystem

<div align="center">
<img align="center" src="https://github.com/AI4Finance-Foundation/FinRobot/assets/31713746/6b30d9c1-35e5-4d36-a138-7e2769718f62" width="90%"/>
</div>

The overall framework is organized into four layers, each addressing a specific aspect of financial AI processing:

1. **Financial AI Agents Layer** — includes Financial Chain-of-Thought (CoT) prompting to strengthen complex analysis and decision-making. Market Forecasting Agents, Document Analysis Agents, and Trading Strategies Agents use CoT to break financial problems into logical steps, aligning their algorithms and domain expertise with evolving market dynamics.
2. **Financial LLMs Algorithms Layer** — configures and applies models tuned to specific domains and global market analysis.
3. **LLMOps and DataOps Layers** — a multi-source integration strategy that selects the most suitable LLM for each financial task across a range of state-of-the-art models.
4. **Multi-source LLM Foundation Models Layer** — supports plug-and-play use of general and specialized LLMs.

### Agent workflow

<div align="center">
<img align="center" src="https://github.com/AI4Finance-Foundation/FinRobot/assets/31713746/ff8033be-2326-424a-ac11-17e2c9c4983d" width="60%"/>
</div>

1. **Perception** — captures and interprets multimodal financial data from market feeds, news, and economic indicators, structuring it for analysis.
2. **Brain** — the core processing unit: consumes perception output with LLMs and applies Financial CoT to generate structured instructions.
3. **Action** — executes those instructions with tools, turning analysis into outcomes: trades, portfolio adjustments, reports, or alerts.

### Smart Scheduler

<div align="center">
<img align="center" src="https://github.com/AI4Finance-Foundation/FinRobot/assets/31713746/06fa0b78-ac53-48d3-8a6e-98d15386327e" width="60%"/>
</div>

The Smart Scheduler ensures model diversity and selects the most appropriate LLM for each task.

- **Director Agent** — orchestrates task assignment, allocating work based on performance metrics and task suitability.
- **Agent Registration** — manages registration and tracks agent availability for efficient allocation.
- **Agent Adaptor** — tailors agent functionality to specific tasks.
- **Task Manager** — stores and manages general and fine-tuned LLM-based agents for different financial tasks, updated periodically.

---

## AI Agent papers

+ [Stanford University + Microsoft Research] [Agent AI: Surveying the Horizons of Multimodal Interaction](https://arxiv.org/abs/2401.03568)
+ [Stanford University] [Generative Agents: Interactive Simulacra of Human Behavior](https://arxiv.org/abs/2304.03442)
+ [Fudan NLP Group] [The Rise and Potential of Large Language Model Based Agents: A Survey](https://arxiv.org/abs/2309.07864)
+ [Fudan NLP Group] [LLM-Agent-Paper-List](https://github.com/WooooDyy/LLM-Agent-Paper-List)
+ [Tsinghua University] [Large Language Models Empowered Agent-based Modeling and Simulation: A Survey and Perspectives](https://arxiv.org/abs/2312.11970)
+ [Renmin University] [A Survey on Large Language Model-based Autonomous Agents](https://arxiv.org/pdf/2308.11432.pdf)
+ [Nanyang Technological University] [FinAgent: A Multimodal Foundation Agent for Financial Trading: Tool-Augmented, Diversified, and Generalist](https://arxiv.org/abs/2402.18485)

## AI Agent open-source frameworks & tools

+ [AutoGPT (183k stars)](https://github.com/Significant-Gravitas/AutoGPT): autonomous AI agent platform.
+ [Dify (134k stars)](https://github.com/langgenius/dify): LLM app development platform with workflow orchestration and RAG.
+ [LangChain (130k stars)](https://github.com/langchain-ai/langchain): framework for building context-aware LLM applications.
+ [MetaGPT (65.6k stars)](https://github.com/geekan/MetaGPT): multi-agent framework with role-based collaboration.
+ [AutoGen (56k stars)](https://github.com/microsoft/autogen): framework for multi-agent LLM applications with tools and human interaction.
+ [CrewAI (46.6k stars)](https://github.com/joaomdmoura/crewAI): framework for orchestrating collaborative AI agents.
+ [ChatDev (31.7k stars)](https://github.com/OpenBMB/ChatDev): multi-agent framework for software development tasks.
+ [FastGPT (27.4k stars)](https://github.com/labring/FastGPT): knowledge-based LLM platform with workflow support.
+ [Langfuse (23.4k stars)](https://github.com/langfuse/langfuse): open-source LLM observability and evaluation platform.
+ [BabyAGI (22.2k stars)](https://github.com/yoheinakajima/babyagi): task-driven experimental autonomous agent framework.
+ [SuperAGI (17.3k stars)](https://github.com/TransformerOptimus/SuperAGI): developer-focused autonomous agent framework.
+ [CAMEL (16.4k stars)](https://github.com/camel-ai/camel): framework for cooperative and communicative AI agents.
+ [Bisheng (11.2k stars)](https://github.com/dataelement/bisheng): enterprise open-source LLM application platform.

## Citing FinRobot

```bibtex
@article{yang2024finrobot,
  title   = {FinRobot: An Open-Source AI Agent Platform for Financial Applications using Large Language Models},
  author  = {Yang, Hongyang and Zhang, Boyu and Wang, Neng and Guo, Cheng and Zhang, Xiaoli and Lin, Likun and Wang, Junlin and Zhou, Tianyu and Guan, Mao and Zhang, Runjia and Wang, Christina Dan},
  journal = {arXiv preprint arXiv:2405.14767},
  year    = {2024},
  doi     = {10.48550/arXiv.2405.14767},
  url     = {https://arxiv.org/abs/2405.14767}
}

@inproceedings{zhou2024finrobot,
  title     = {FinRobot: {AI} Agent for Equity Research and Valuation with Large Language Models},
  author    = {Tianyu Zhou and Pinqiao Wang and Yilin Wu and Hongyang Yang},
  booktitle = {ICAIF 2024: The 1st Workshop on Large Language Models and Generative AI for Finance},
  year      = {2024}
}

@inproceedings{han2024enhancing,
  title     = {Enhancing Investment Analysis: Optimizing AI-Agent Collaboration in Financial Research},
  author    = {Han, Xuewen and Wang, Neng and Che, Shangkun and Yang, Hongyang and Zhang, Kunpeng and Xu, Sean Xin},
  booktitle = {ICAIF 2024: Proceedings of the 5th ACM International Conference on AI in Finance},
  pages     = {538--546},
  year      = {2024}
}
```

## License

Apache 2.0 — see [LICENSE](./LICENSE). Trademark usage is covered by [TRADEMARK_POLICY.md](./TRADEMARK_POLICY.md).

**Disclaimer**: The code and documents provided here are released under the Apache-2.0 license. They should not be construed as financial advice or recommendations for live trading. Exercise caution and consult qualified financial professionals before any trading or investment decisions.

<div align="center">
<img align="center" width="30%" alt="image" src="https://github.com/AI4Finance-Foundation/FinGPT/assets/31713746/e0371951-1ce1-488e-aa25-0992dafcc139">
</div>
