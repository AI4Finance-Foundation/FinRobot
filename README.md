
# FinRobot: An Open-Source AI Agent Platform for Financial Analysis using Large Language Models
[![Downloads](https://static.pepy.tech/badge/finrobot)]([https://pepy.tech/project/finrobot](https://pepy.tech/project/finrobot))
[![Downloads](https://static.pepy.tech/badge/finrobot/week)](https://pepy.tech/project/finrobot)
[![Join Discord](https://img.shields.io/badge/Discord-Join-blue)](https://discord.gg/trsr8SXpW5)
[![Python 3.8](https://img.shields.io/badge/python-3.6-blue.svg)](https://www.python.org/downloads/release/python-360/)
[![PyPI](https://img.shields.io/pypi/v/finrobot.svg)](https://pypi.org/project/finrobot/)
![License](https://img.shields.io/github/license/AI4Finance-Foundation/finrobot.svg?color=brightgreen)
![](https://img.shields.io/github/issues-raw/AI4Finance-Foundation/finrobot?label=Issues)
![](https://img.shields.io/github/issues-closed-raw/AI4Finance-Foundation/finrobot?label=Closed+Issues)
![](https://img.shields.io/github/issues-pr-raw/AI4Finance-Foundation/finrobot?label=Open+PRs)
![](https://img.shields.io/github/issues-pr-closed-raw/AI4Finance-Foundation/finrobot?label=Closed+PRs)


<div align="center">
<img align="center" src=figs/logo_white_background.jpg width="40%"/>
</div>

**FinRobot** is an AI Agent platform tailored for financial applications, surpassing FinGPT's single-model approach. It unifies multiple AI technologies—including LLMs, reinforcement learning, and quantitative analytics—to power investment research automation, algorithmic trading strategies, and risk assessment, delivering a full-stack intelligent solution for the financial industry.

**Concept of AI Agent**: an AI Agent is an intelligent entity that uses large language models as its brain to perceive its environment, make decisions, and execute actions. Unlike traditional artificial intelligence, AI Agents possess the ability to independently think and utilize tools to progressively achieve given objectives.

[Whitepaper of FinRobot](https://arxiv.org/abs/2405.14767)

![Visitors](https://api.visitorbadge.io/api/VisitorHit?user=AI4Finance-Foundation&repo=FinRobot&countColor=%23B17A)
[![Discord](https://dcbadge.limes.pink/api/server/trsr8SXpW5?v=20260320)](https://discord.gg/trsr8SXpW5)

## 🎬 FinRobot Pro — Your Personal AI-Powered Equity Research Assistant
🌐 https://finrobot.ai/

<div align="center">
  <a href="https://www.youtube.com/watch?v=ebgPiJINi-k" target="_blank">
    <img src="https://github.com/user-attachments/assets/de3b9f9c-50aa-49f0-82c6-3d2b938f4670" width="90%" />
  </a>
</div>

<p align="center">
  ▶️ Click the image above to watch the demo video, or see the short preview below.
</p>

A locally-deployed AI assistant that fetches financial data, runs multi-agent LLM analysis, and generates professional equity research reports.

**1. Configure API Keys**
```bash
cp finrobot_equity/core/config/config.ini.example finrobot_equity/core/config/config.ini
```
Edit `config.ini` with your keys:
```ini
[API_KEYS]
fmp_api_key = YOUR_FMP_API_KEY          # https://financialmodelingprep.com/developer
openai_api_key = YOUR_OPENAI_API_KEY    # https://platform.openai.com/account/api-keys
```

**2. One-Command Deploy (Web Interface)**
```bash
chmod +x deploy.sh
./deploy.sh start

#if deploy.sh not working then
python3 -m venv venv                                                                                                                                           
source venv/bin/activate
pip install -r requirements-equity.txt                                                                                                                         
python run_web_app.py  
```
Access at `http://127.0.0.1:8001`

| Command | Description |
|:---|:---|
| `./deploy.sh start` | Start the web app (auto-installs dependencies) |
| `./deploy.sh stop` | Stop the application |
| `./deploy.sh restart` | Restart the application |
| `./deploy.sh status` | Check running status |

**3. Or Run via Command Line**
```bash
# Step 1: Financial analysis
python finrobot_equity/core/src/generate_financial_analysis.py \
    --company-ticker NVDA \
    --company-name "NVIDIA Corporation" \
    --config-file finrobot_equity/core/config/config.ini \
    --peer-tickers AMD INTC \
    --generate-text-sections

# Step 2: Generate report
python finrobot_equity/core/src/create_equity_report.py \
    --company-ticker NVDA \
    --company-name "NVIDIA Corporation" \
    --analysis-csv output/NVDA/analysis/financial_metrics_and_forecasts.csv \
    --ratios-csv output/NVDA/analysis/ratios_raw_data.csv \
    --config-file finrobot_equity/core/config/config.ini
```

**Pipeline**:
1. **Fetch Financial Data**: income statements, balance sheets, cash flows via FMP API
2. **Process & Forecast**: 3-year financial projections, DCF valuation, peer comparison
3. **AI Agent Analysis**: 8 specialized agents generate investment thesis, risk assessment, valuation overview, etc.
4. **Report Generation**: professional multi-page HTML/PDF with 15+ chart types

### Example Reports
- [NVDA Equity Research Report](https://ai4finance-foundation.github.io/FinRobot/finrobot_equity/core/output/NVDA_Equity_Research_Report.html)
- [MSFT Equity Research Report](https://ai4finance-foundation.github.io/FinRobot/finrobot_equity/core/output/MSFT_Equity_Research_Report.html)
- [COP Equity Research Report](https://ai4finance-foundation.github.io/FinRobot/finrobot_equity/core/output/COP_Equity_Research_Report.html)
- [TSLA Equity Research Report](https://ai4finance-foundation.github.io/FinRobot/finrobot_equity/core/output/TSLA_Equity_Research_Report.html)
- [META Equity Research Report](https://ai4finance-foundation.github.io/FinRobot/finrobot_equity/core/output/META_Equity_Research_Report.html)

For full documentation, see [finrobot_equity/README.md](finrobot_equity/README.md).


## What is FinRobot Pro?


https://github.com/user-attachments/assets/93ec0f1e-e28b-4474-a0bf-a79e0c12f0ff


[FinRobot Pro](https://finrobot.ai/ ) is an AI-powered equity research platform that automates professional stock analysis using Large Language Models (LLMs) and AI Agents.

**Key Features:**

- **Automated Report Generation** – Generate professional equity research reports instantly
- **Financial Analysis** – Deep dive into income statements, balance sheets, and cash flows
- **Valuation Analysis** – P/E ratio, EV/EBITDA multiples, and peer comparison
- **Risk Assessment** – Comprehensive investment risk evaluation


## FinRobot Ecosystem
<div align="center">
<img align="center" src="https://github.com/AI4Finance-Foundation/FinRobot/assets/31713746/6b30d9c1-35e5-4d36-a138-7e2769718f62" width="90%"/>
</div>

### The overall framework of FinRobot is organized into four distinct layers, each designed to address specific aspects of financial AI processing and application:
1. **Financial AI Agents Layer**: The Financial AI Agents Layer now includes Financial Chain-of-Thought (CoT) prompting, enhancing complex analysis and decision-making capacity. Market Forecasting Agents, Document Analysis Agents, and Trading Strategies Agents utilize CoT to dissect financial challenges into logical steps, aligning their advanced algorithms and domain expertise with the evolving dynamics of financial markets for precise, actionable insights.
2. **Financial LLMs Algorithms Layer**: The Financial LLMs Algorithms Layer configures and utilizes specially tuned models tailored to specific domains and global market analysis. 
3. **LLMOps and DataOps Layers**: The LLMOps layer implements a multi-source integration strategy that selects the most suitable LLMs for specific financial tasks, utilizing a range of state-of-the-art models. 
4. **Multi-source LLM Foundation Models Layer**: This foundational layer supports the plug-and-play functionality of various general and specialized LLMs. 


## FinRobot: Agent Workflow
<div align="center">
<img align="center" src="https://github.com/AI4Finance-Foundation/FinRobot/assets/31713746/ff8033be-2326-424a-ac11-17e2c9c4983d" width="60%"/>
</div>

1. **Perception**: This module captures and interprets multimodal financial data from market feeds, news, and economic indicators, using sophisticated techniques to structure the data for thorough analysis.

2. **Brain**: Acting as the core processing unit, this module perceives data from the Perception module with LLMs and utilizes Financial Chain-of-Thought (CoT) processes to generate structured instructions.

3. **Action**: This module executes instructions from the Brain module, applying tools to translate analytical insights into actionable outcomes. Actions include trading, portfolio adjustments, generating reports, or sending alerts, thereby actively influencing the financial environment.

## FinRobot: Smart Scheduler
<div align="center">
<img align="center" src="https://github.com/AI4Finance-Foundation/FinRobot/assets/31713746/06fa0b78-ac53-48d3-8a6e-98d15386327e" width="60%"/>
</div>

The Smart Scheduler is central to ensuring model diversity and optimizing the integration and selection of the most appropriate LLM for each task.
* **Director Agent**: This component orchestrates the task assignment process, ensuring that tasks are allocated to agents based on their performance metrics and suitability for specific tasks.
* **Agent Registration**: Manages the registration and tracks the availability of agents within the system, facilitating an efficient task allocation process.
* **Agent Adaptor**: Tailor agent functionalities to specific tasks, enhancing their performance and integration within the overall system.
* **Task Manager**: Manages and stores different general and fine-tuned LLMs-based agents tailored for various financial tasks, updated periodically to ensure relevance and efficacy.

## File Structure

The main folder **finrobot** has three subfolders **agents, data_source, functional**. 

```
FinRobot
├── finrobot (main folder)
│   ├── agents
│   	├── agent_library.py
│   	└── workflow.py
│   ├── data_source
│   	├── finnhub_utils.py
│   	├── finnlp_utils.py
│   	├── fmp_utils.py
│   	├── sec_utils.py
│   	└── yfinance_utils.py
│   ├── functional
│   	├── analyzer.py
│   	├── charting.py
│   	├── coding.py
│   	├── quantitative.py
│   	├── reportlab.py
│   	└── text.py
│   ├── toolkits.py
│   └── utils.py
│
├── configs
├── experiments
├── tutorials_beginner (hands-on tutorial)
│   ├── agent_fingpt_forecaster.ipynb
│   └── agent_annual_report.ipynb 
├── tutorials_advanced (advanced tutorials for potential finrobot developers)
│   ├── agent_trade_strategist.ipynb
│   ├── agent_fingpt_forecaster.ipynb
│   ├── agent_annual_report.ipynb 
│   ├── lmm_agent_mplfinance.ipynb
│   └── lmm_agent_opt_smacross.ipynb
├── setup.py
├── OAI_CONFIG_LIST_sample
├── config_api_keys_sample
├── requirements.txt
└── README.md
```

## Installation:

**1. (Recommended) Create a new virtual environment**
```shell
conda create --name finrobot python=3.10
conda activate finrobot
```
**2. download the FinRobot repo use terminal or download it manually**
```shell
git clone https://github.com/AI4Finance-Foundation/FinRobot.git
cd FinRobot
```
**3. install finrobot & dependencies from source or pypi**

get our latest release from pypi
```bash
pip install -U finrobot
```
or install from this repo directly
```
pip install -e .
```
**4. modify OAI_CONFIG_LIST_sample file**
```shell
1) rename OAI_CONFIG_LIST_sample to OAI_CONFIG_LIST
2) remove the four lines of comment within the OAI_CONFIG_LIST file
3) add your own openai api-key <your OpenAI API key here>
```
**5. modify config_api_keys_sample file**
```shell
1) rename config_api_keys_sample to config_api_keys
2) remove the comment within the config_api_keys file
3) add your own finnhub-api "YOUR_FINNHUB_API_KEY"
4) add your own financialmodelingprep and sec-api keys "YOUR_FMP_API_KEY" and "YOUR_SEC_API_KEY" (for financial report generation)
```
**6. start navigating the tutorials or the demos below:**
```
# find these notebooks in tutorials
1) agent_annual_report.ipynb
2) agent_fingpt_forecaster.ipynb
3) agent_trade_strategist.ipynb
4) lmm_agent_mplfinance.ipynb
5) lmm_agent_opt_smacross.ipynb
```

## Demos
### 1. Market Forecaster Agent (Predict Stock Movements Direction)
Takes a company's ticker symbol, recent basic financials, and market news as input and predicts its stock movements.

1. Import 
```python
import autogen
from finrobot.utils import get_current_date, register_keys_from_json
from finrobot.agents.workflow import SingleAssistant
```
2. Config
```python
# Read OpenAI API keys from a JSON file
llm_config = {
    "config_list": autogen.config_list_from_json(
        "../OAI_CONFIG_LIST",
        filter_dict={"model": ["gpt-4-0125-preview"]},
    ),
    "timeout": 120,
    "temperature": 0,
}

# Register FINNHUB API keys
register_keys_from_json("../config_api_keys")
```
3. Run
```python
company = "NVDA"

assitant = SingleAssistant(
    "Market_Analyst",
    llm_config,
    # set to "ALWAYS" if you want to chat instead of simply receiving the prediciton
    human_input_mode="NEVER",
)
assitant.chat(
    f"Use all the tools provided to retrieve information available for {company} upon {get_current_date()}. Analyze the positive developments and potential concerns of {company} "
    "with 2-4 most important factors respectively and keep them concise. Most factors should be inferred from company related news. "
    f"Then make a rough prediction (e.g. up/down by 2-3%) of the {company} stock price movement for next week. Provide a summary analysis to support your prediction."
)
```

### 2. Personal AI Equity Research Assistant (Equity Research Report)
### 3. Trade Strategist Agent with multimodal capabilities


## AI Agent Papers

+ [Stanford University + Microsoft Research] [Agent AI: Surveying the Horizons of Multimodal Interaction](https://arxiv.org/abs/2401.03568)
+ [Stanford University] [Generative Agents: Interactive Simulacra of Human Behavior](https://arxiv.org/abs/2304.03442)
+ [Fudan NLP Group] [The Rise and Potential of Large Language Model Based Agents: A Survey](https://arxiv.org/abs/2309.07864)
+ [Fudan NLP Group] [LLM-Agent-Paper-List](https://github.com/WooooDyy/LLM-Agent-Paper-List)
+ [Tsinghua University] [Large Language Models Empowered Agent-based Modeling and Simulation: A Survey and Perspectives](https://arxiv.org/abs/2312.11970)
+ [Renmin University] [A Survey on Large Language Model-based Autonomous Agents](https://arxiv.org/pdf/2308.11432.pdf)
+ [Nanyang Technological University] [FinAgent: A Multimodal Foundation Agent for Financial Trading: Tool-Augmented, Diversified, and Generalist](https://arxiv.org/abs/2402.18485)


## AI Agent Open-Source Frameworks & Tools
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
```
@article{yang2024finrobot,
  title={FinRobot: An Open-Source AI Agent Platform for Financial Applications using Large Language Models},
  author={Yang, Hongyang and Zhang, Boyu and Wang, Neng and Guo, Cheng and Zhang, Xiaoli and Lin, Likun and Wang, Junlin and Zhou, Tianyu and Guan, Mao and Zhang, Runjia and others},
  journal={arXiv preprint arXiv:2405.14767},
  year={2024}
}

@inproceedings{
zhou2024finrobot,
title={FinRobot: {AI} Agent for Equity Research and Valuation with Large Language Models},
author={Tianyu Zhou and Pinqiao Wang and Yilin Wu and Hongyang Yang},
booktitle={ICAIF 2024: The 1st Workshop on Large Language Models and Generative AI for Finance},
year={2024}
}


@inproceedings{han2024enhancing,
  title={Enhancing Investment Analysis: Optimizing AI-Agent Collaboration in Financial Research},
  author={Han, Xuewen and Wang, Neng and Che, Shangkun and Yang, Hongyang and Zhang, Kunpeng and Xu, Sean Xin},
  booktitle={ICAIF 2024: Proceedings of the 5th ACM International Conference on AI in Finance},
  pages={538--546},
  year={2024}
}
```
**Disclaimer**: The codes and documents provided herein are released under the Apache-2.0 license. They should not be construed as financial counsel or recommendations for live trading. It is imperative to exercise caution and consult with qualified financial professionals prior to any trading or investment actions.


<div align="center">
<img align="center" width="30%" alt="image" src="https://github.com/AI4Finance-Foundation/FinGPT/assets/31713746/e0371951-1ce1-488e-aa25-0992dafcc139">
</div>



