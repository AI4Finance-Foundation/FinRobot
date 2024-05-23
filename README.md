<div align="center">
<img align="center" width="30%" alt="image" src="https://github.com/AI4Finance-Foundation/FinGPT/assets/31713746/e0371951-1ce1-488e-aa25-0992dafcc139">
</div>

# FinRobot: An Open-Source AI Agent Platform for Financial Applications using Large Language Models
[![Downloads](https://static.pepy.tech/badge/finrobot)]([https://pepy.tech/project/finrobot](https://pepy.tech/project/finrobot))
[![Downloads](https://static.pepy.tech/badge/finrobot/week)](https://pepy.tech/project/finrobot)
[![Python 3.8](https://img.shields.io/badge/python-3.6-blue.svg)](https://www.python.org/downloads/release/python-360/)
[![PyPI](https://img.shields.io/pypi/v/finrobot.svg)](https://pypi.org/project/finrobot/)
![License](https://img.shields.io/github/license/AI4Finance-Foundation/finrobot.svg?color=brightgreen)

<div align="center">
<img align="center" src=figs/logo_white_background.jpg width="40%"/>
</div>

**FinRobot** is an AI Agent Platform that transcends the scope of FinGPT, representing a comprehensive solution meticulously designed for financial applications. It integrates **a diverse array of AI technologies**, extending beyond mere language models. This expansive vision highlights the platform's versatility and adaptability, addressing the multifaceted needs of the financial industry.

**Concept of AI Agent**: an AI Agent is an intelligent entity that uses large language models as its brain to perceive its environment, make decisions, and execute actions. Unlike traditional artificial intelligence, AI Agents possess the ability to independently think and utilize tools to progressively achieve given objectives.

[![](https://dcbadge.vercel.app/api/server/trsr8SXpW5)](https://discord.gg/trsr8SXpW5)

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
│   	└── data_agents.py
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
├── tutorials (hands-on tutorial)
│   ├── agent_annual_report.ipynb
│   ├── agent_fingpt_forecaster.ipynb
│   ├── agent_trade_strategist.ipynb
│   ├── lmm_agent_mplfinance.ipynb
│   └── lmm_agent_opt_smacross.ipynb
├── setup.py
├── OAI_CONFIG_LIST_sample
├── config_api_keys_sample
├── requirements.txt
└── README.md
```

## Installation:
1. download the FinRobot repo use terminal or download it manually 
```shell
git clone https://github.com/AI4Finance-Foundation/FinRobot.git
```
2. install dependencies
cd into this repository
```bash
cd FinRobot
pip install FinRobot
```
3. modify OAI_CONFIG_LIST_sample file
```shell
1) rename OAI_CONFIG_LIST_sample to OAI_CONFIG_LIST
2) remove the four lines of comment within the OAI_CONFIG_LIST file
3) add your own openai api-key <your OpenAI API key here>
```
4. modify config_api_keys_sample file
```shell
1) rename config_api_keys_sample to config_api_keys
2) remove the comment within the config_api_keys file
3) add your own finnhub-api "YOUR_FINNHUB_API_KEY"
4) add your own financialmodelingprep and sec-api keys "YOUR_FMP_API_KEY" and "YOUR_SEC_API_KEY" (for financial report generation)
```
5. Run tutorials, use jupyter notebook navigate to the tutorials folder
```shell
#run these notebooks
1) agent_annual_report.ipynb
2) agent_fingpt_forecaster.ipynb
3) agent_trade_strategist.ipynb
4) lmm_agent_mplfinance.ipynb
5) lmm_agent_opt_smacross.ipynb
```

## Demos
### 1. Financial Analyst Agent for Report Writing (Equity Research Report)
1. **Gather Preliminary Data**: 10-K report
2. **Analyze Financial Statements**: balance sheet, income statement, cash flow
3. **Company Overview and Performance**: company description, business highlights, segment analysis
4. **Risk Assessment**: assess risks
5. **Financial Performance Visualization**:  plot PE ratio and EPS
6. **Synthesize Findings into Paragraphs**: combine all parts into a coherent summary
7. **Generate PDF Report**: use tools to generate PDF automatically
8. **Quality Assurance**: check word counts

check out the report folder for more examples

<div align="center">
<img align="center" src="https://github.com/AI4Finance-Foundation/FinRobot/assets/31713746/d2d999e0-dc0e-4196-aca1-218f5fadcc5b" width="60%"/>
</div>


### 2. Market Forecaster Agent (Predict Stock Movements Direction)
Takes a company's ticker symbol, recent basic financials and market news as input and predict its stock movements.

<div align="center">
<img align="center" src="https://github.com/AI4Finance-Foundation/FinRobot/assets/31713746/812ec23a-9cb3-4fad-b716-78533ddcd9dc" width="40%"/>
</div>

### 3. Trade Strategist Agent with multimodal capabilities


## AI Agent Papers

+ [Stanford University + Microsoft Research] [Agent AI: Surveying the Horizons of Multimodal Interaction](https://arxiv.org/abs/2401.03568)
+ [Stanford University] [Generative Agents: Interactive Simulacra of Human Behavior](https://arxiv.org/abs/2304.03442)
+ [Fudan NLP Group] [The Rise and Potential of Large Language Model Based Agents: A Survey](https://arxiv.org/abs/2309.07864)
+ [Fudan NLP Group] [LLM-Agent-Paper-List](https://github.com/WooooDyy/LLM-Agent-Paper-List)
+ [Tsinghua University] [Large Language Models Empowered Agent-based Modeling and Simulation: A Survey and Perspectives](https://arxiv.org/abs/2312.11970)
+ [Renmin University] [A Survey on Large Language Model-based Autonomous Agents](https://arxiv.org/pdf/2308.11432.pdf)
+ [Nanyang Technological University] [FinAgent: A Multimodal Foundation Agent for Financial Trading: Tool-Augmented, Diversified, and Generalist](https://arxiv.org/abs/2402.18485)

## AI Agent Blogs and Videos
+ [Medium] [An Introduction to AI Agents](https://medium.com/humansdotai/an-introduction-to-ai-agents-e8c4afd2ee8f)
+ [Medium] [Unmasking the Best Character AI Chatbots | 2024](https://medium.com/@aitrendorbit/unmasking-the-best-character-ai-chatbots-2024-351de43792f4#the-best-character-ai-chatbots)
+ [big-picture] [ChatGPT, Next Level: Meet 10 Autonomous AI Agents](https://blog.big-picture.com/en/chatgpt-next-level-meet-10-autonomous-ai-agents-auto-gpt-babyagi-agentgpt-microsoft-jarvis-chaosgpt-friends/)
+ [TowardsDataScience] [Navigating the World of LLM Agents: A Beginner’s Guide](https://towardsdatascience.com/navigating-the-world-of-llm-agents-a-beginners-guide-3b8d499db7a9)
+ [YouTube] [Introducing Devin - The "First" AI Agent Software Engineer](https://www.youtube.com/watch?v=iVbN95ica_k)


## AI Agent Open-Source Framework & Tool
+ [AutoGPT (161k stars)](https://github.com/Significant-Gravitas/AutoGPT) is a tool for everyone to use, aiming to democratize AI, making it accessible for everyone to use and build upon.
+ [LangChain (82.7k stars)](https://github.com/langchain-ai/langchain) is a framework for developing context-aware applications powered by language models, enabling them to connect to sources of context and rely on the model's reasoning capabilities for responses and actions.
+ [MetaGPT (39.1k stars)](https://github.com/geekan/MetaGPT) is a multi-agent open-source framework that assigns different roles to GPTs, forming a collaborative software entity to execute complex tasks.
+ [AutoGen (24.8k stars)](https://github.com/microsoft/autogen) is a framework for developing LLM applications with conversational agents that collaborate to solve tasks. These agents are customizable, support human interaction, and operate in modes combining LLMs, human inputs, and tools.
+ [dify (22.7k stars)](https://github.com/langgenius/dify) is an LLM application development platform. It integrates the concepts of Backend as a Service and LLMOps, covering the core tech stack required for building generative AI-native applications, including a built-in RAG engine
+ [ChatDev (22.7k stars)](https://github.com/OpenBMB/ChatDev) is a framework that focuses on developing conversational AI Agents capable of dialogue and question-answering. It provides a range of pre-trained models and interactive interfaces, facilitating the development of customized chat Agents for users.
+ [BabyAGI (19.2k stars)](https://github.com/yoheinakajima/babyagi) is an AI-powered task management system, dedicated to building AI Agents with preliminary general intelligence. 
+ [SuperAGI (14.4k stars)](https://github.com/TransformerOptimus/SuperAGI) is a dev-first open-source autonomous AI agent framework enabling developers to build, manage & run useful autonomous agents.
+ [FastGPT (12.5k stars)](https://github.com/labring/FastGPT) is a knowledge-based platform built on the LLM, offers out-of-the-box data processing and model invocation capabilities, allows for workflow orchestration through Flow visualization.
+ [CrewAI (12.1k stars)](https://github.com/joaomdmoura/crewAI) is a framework for orchestrating role-playing, autonomous AI agents. By fostering collaborative intelligence, CrewAI empowers agents to work together seamlessly, tackling complex tasks.
+ [XAgent (7.5k stars)](https://github.com/OpenBMB/XAgent) is an open-source experimental Large Language Model (LLM) driven autonomous agent that can automatically solve various tasks.
+ [Bisheng (5.5k stars)](https://github.com/dataelement/bisheng) is a leading open-source platform for developing LLM applications.
+ [Voyager (5.1k stars)](https://github.com/OpenBMB/XAgent) An Open-Ended Embodied Agent with Large Language Models.
+ [CAMEL (4.4k stars)](https://github.com/camel-ai/camel) is a framework that offers a comprehensive set of tools and algorithms for building multimodal AI Agents, enabling them to handle various data forms such as text, images, and speech.
+ [Langfuse (2.9k stars)](https://github.com/langfuse/langfuse) is a language fusion framework that can integrate the language abilities of multiple AI Agents, enabling them to simultaneously possess multilingual understanding and generation capabilities.
