# FinRobot V0 — AutoGen Multi-Agent Framework

> **Educational.** The original FinRobot: a library of role-based financial agents, data-source wrappers, and analysis tools built on [Microsoft AutoGen](https://github.com/microsoft/autogen).

This is the codebase behind the [FinRobot whitepaper](https://arxiv.org/abs/2405.14767), kept in the repository for **learning and reference** — teaching, coursework, reproducing the paper, and understanding how financial agents are wired together. The agent definitions, the tool-registration pattern, and the data plumbing are all small enough to read end to end, which is exactly why it is worth keeping.

**It is not the production system.** There is no deterministic compute layer here, no provenance tracking, and no guarantee that a number in the output was computed rather than generated — the agents call tools and the LLM writes the result. For research you intend to act on, use [`finrobot_desktop/`](../finrobot_desktop/) (V2), where financial figures come from pure-Python operators and every one is traceable. For a self-hosted report-generating web service, use [`finrobot_equity/`](../finrobot_equity/) (V1).

---

## What's in here

| Layer | Module | What it does |
|:---|:---|:---|
| **Agents** | `finrobot/agents/agent_library.py` | 10 predefined roles (system message + toolkit), keyed by name |
| | `finrobot/agents/workflow.py` | Ready-made conversation topologies — single-agent, RAG, multi-agent, leader-led |
| | `finrobot/agents/prompts.py` | Shared prompt fragments, including the financial chain-of-thought scaffolds |
| **Tools** | `finrobot/toolkits.py` | Registers plain Python functions (or whole classes) as AutoGen tools |
| **Data** | `finrobot/data_source/` | Finnhub, FMP, yfinance, SEC EDGAR, Reddit, FinNLP |
| **Capabilities** | `finrobot/functional/` | Statement analysis, charting, quantitative backtesting, PDF reports, RAG |

### Agent roles

`agent_library.library` is a dict keyed by role name. Each entry carries a `profile` (system message) and a `toolkits` list:

```
Software_Developer    Data_Analyst      Programmer       Accountant
Statistician          IT_Specialist     Financial_Analyst
Artificial_Intelligence_Engineer        Market_Analyst   Expert_Investor
```

`Expert_Investor` is the most fully equipped — it carries the SEC-report, charting, text-length and PDF-building toolkits used by the annual-report tutorial.

### Workflows

`finrobot/agents/workflow.py` wraps AutoGen's `ConversableAgent` plumbing so you don't hand-roll group chats:

| Class | Shape |
|:---|:---|
| `SingleAssistant` | One assistant + one user proxy executor |
| `SingleAssistantRAG` | Same, with a retrieval-augmented proxy over your documents |
| `SingleAssistantShadow` | Assistant paired with a "shadow" agent that gets an expanded toolkit mid-conversation |
| `MultiAssistant` | A group chat across several library roles |
| `MultiAssistantWithLeader` | A group chat where one designated agent orchestrates the rest |

### Tool registration

`register_toolkits` is the seam between plain Python and the agent layer. It takes a list of functions — or a class, via `register_tookits_from_cls` — and binds them to a caller/executor pair, so the LLM proposes the call and a separate proxy actually executes it:

```python
from finrobot.toolkits import register_toolkits
from finrobot.data_source import FMPUtils

register_toolkits([FMPUtils.get_sec_report], assistant, user_proxy)
```

### Data sources

| Module | Source | Needs a key |
|:---|:---|:---|
| `finnhub_utils.py` | Finnhub — quotes, company news, basic financials | Yes |
| `fmp_utils.py` | Financial Modeling Prep — statements, ratios, SEC report URLs | Yes |
| `sec_utils.py`, `filings_src/`, `marker_sec_src/` | SEC EDGAR filings and 10-K parsing | Yes (`SEC_API_KEY`) |
| `yfinance_utils.py` | Yahoo Finance — prices, history | No |
| `reddit_utils.py` | Reddit sentiment | Yes |
| `finnlp_utils.py` | [FinNLP](https://github.com/AI4Finance-Foundation/FinNLP) — news and social data | Varies |
| `earnings_calls_src/` | Earnings-call transcripts | Varies |

`FinNLP/` is a git submodule. Fetch it with `git submodule update --init --recursive` if the directory is empty.

---

## Install

The package is published and imported as `finrobot`, but its source now lives under `finrobot_autogen/`. `setup.py` at the **repository root** maps the two, so install from the root — not from this directory:

```bash
conda create --name finrobot python=3.10   # 3.10 or 3.11
conda activate finrobot

cd /path/to/FinRobot      # repo root
pip install -e .
```

Or from PyPI:

```bash
pip install -U finrobot
```

Either way the import name is unchanged:

```python
from finrobot.agents.workflow import SingleAssistant
```

## Configure

Both config files live in **this directory** (`finrobot_autogen/`) — that's where the tutorial notebooks look for them (`../OAI_CONFIG_LIST` relative to `tutorials_*/`).

**1. LLM endpoints** — copy the sample and fill in your key:

```bash
cp OAI_CONFIG_LIST_sample OAI_CONFIG_LIST
```

It is an AutoGen config list, so it holds several entries — OpenAI and Azure OpenAI deployments — and agents select one by model name.

**2. Data API keys:**

```bash
cp config_api_keys_sample config_api_keys
```

```json
{
  "FINNHUB_API_KEY": "...",
  "FMP_API_KEY": "...",
  "SEC_API_KEY": "...",
  "REDDIT_CLIENT_ID": "...",
  "REDDIT_CLIENT_SECRET": "...",
  "TWITTER_BEARER_TOKEN": "..."
}
```

Load them into the environment with `finrobot.utils.register_keys_from_json("config_api_keys")`. Only fill in the keys for the data sources you actually use — the others can stay as placeholders.

Both `OAI_CONFIG_LIST` and `config_api_keys` are gitignored. The `*_sample` files are the ones under version control; never commit the filled-in copies.

---

## Tutorials

Run these from their own directory so the `../OAI_CONFIG_LIST` paths resolve.

### Beginner — `tutorials_beginner/`

| Notebook | What it builds |
|:---|:---|
| `agent_annual_report.ipynb` | `Expert_Investor` reads a 10-K and produces a formatted PDF annual report |
| `agent_fingpt_forecaster.ipynb` | Market forecast agent over news + basic financials |
| `agent_rag_qa.ipynb`, `agent_rag_qa_up.ipynb` | RAG question-answering over your own documents |
| `agent_rag_earnings_call_sec_filings.ipynb` | RAG across earnings-call transcripts and SEC filings |
| `ollama function call.ipynb`, `ollama stock chart.ipynb` | The same patterns against a local model via Ollama |

### Advanced — `tutorials_advanced/`

| Notebook | What it builds |
|:---|:---|
| `agent_trade_strategist.ipynb` | Strategy agent that writes and backtests trading logic |
| `agent_annual_report.ipynb` | The annual-report workflow with the full toolkit wired up |
| `agent_fingpt_forecaster.ipynb` | Forecaster with a richer data pipeline |
| `agent_openbb.ipynb` | OpenBB as an agent tool provider |
| `lmm_agent_mplfinance.ipynb` | Multimodal agent that *looks at* a rendered candlestick chart |
| `lmm_agent_opt_smacross.ipynb` | Multimodal agent that tunes an SMA-crossover strategy from chart feedback |

The two `lmm_*` notebooks need a vision-capable model configured in `OAI_CONFIG_LIST`.

## Experiments

`experiments/` holds less polished multi-agent studies — treat them as research code, not a supported API:

- `investment_group.py` — a group of analyst agents debating a position
- `multi_factor_agents.py` — factor construction and evaluation
- `portfolio_optimization.py` — portfolio construction agent
- `quantitative_investment_group_config.json` — the group configuration those scripts read

`agent_builder_demo.py` at this level shows AutoGen's agent-builder generating a team from a task description, and `test_module.py` is a smoke test over the data-source wrappers.

`report/` contains sample inputs and generated outputs (Microsoft's 2023 annual report and 10-K, an NVDA report) used by the tutorials.

## Status

V0 is stable and kept working, but it is maintained as teaching material, not as a product — active development happens in V1 and V2. Read this generation for the concepts, then build on:

- [`finrobot_desktop/`](../finrobot_desktop/) — **production**: desktop app and CLI, PydanticAI, deterministic compute engine
- [`finrobot_equity/`](../finrobot_equity/) — **web app**: self-hosted equity research report generator

## License

Apache 2.0 — see [LICENSE](../LICENSE).
