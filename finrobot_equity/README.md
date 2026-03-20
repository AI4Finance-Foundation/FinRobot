# FinRobot Equity Research Module

AI-powered equity research report generator. Fetches financial data, runs LLM-based analysis, and produces professional multi-page HTML/PDF reports — all with a single command.

## Architecture

```
finrobot_equity/
├── core/                              # Analysis engine
│   ├── config/
│   │   └── config.ini.template        # API key configuration template
│   ├── assets/                        # Static assets (logos for PDF reports)
│   ├── src/
│   │   ├── generate_financial_analysis.py   # Step 1: Data fetching & analysis
│   │   ├── create_equity_report.py          # Step 2: HTML report generation
│   │   ├── generate_pdf_report.py           # Step 3: PDF report generation (optional)
│   │   ├── Run.ipynb                        # Jupyter notebook demo
│   │   └── modules/                         # Core modules
│   │       ├── common_utils.py              #   Config & API key management
│   │       ├── market_data_api.py           #   FMP API client
│   │       ├── financial_data_processor.py  #   Metrics extraction & forecasting
│   │       ├── text_generator_agents.py     #   LLM text generation orchestrator
│   │       ├── chart_generator.py           #   Financial chart rendering
│   │       ├── enhanced_chart_generator.py  #   Advanced chart configurations
│   │       ├── html_renderer.py             #   HTML report renderer
│   │       ├── html_template_professional.py#   HTML template definitions
│   │       ├── report_data_loader.py        #   Data loading utilities
│   │       ├── report_structure.py          #   Report layout management
│   │       ├── enhanced_text_generator.py   #   Advanced text processing
│   │       ├── sensitivity_analyzer.py      #   Sensitivity analysis
│   │       ├── catalyst_analyzer.py         #   Market catalyst identification
│   │       ├── news_integrator.py           #   News data integration
│   │       ├── valuation_engine.py          #   Valuation modeling
│   │       ├── pdf_generator.py             #   PDF report generation
│   │       ├── professional_pdf_report.py   #   Professional PDF templates
│   │       └── equity_agents/               #   AI agents for report sections
│   │           ├── agent_manager.py         #     Agent orchestration
│   │           ├── tagline_agent.py         #     Executive tagline
│   │           ├── company_overview_agent.py#     Company overview
│   │           ├── investment_overview_agent.py  # Investment thesis
│   │           ├── valuation_overview_agent.py   # Valuation analysis
│   │           ├── risks_agent.py                # Risk assessment
│   │           ├── competitor_analysis_agent.py  # Competitive landscape
│   │           ├── major_takeaways_agent.py      # Key takeaways
│   │           └── news_summary_agent.py         # News summarization
│   └── tests/                         # Unit tests
│       ├── test_generate_report.py
│       └── test_modules.py
│
└── web_app/                           # Web interface (FastAPI)
    ├── main.py                        # Application entry point & API routes
    ├── auth.py                        # Authentication (local + GitHub OAuth)
    ├── admin_routes.py                # Admin API endpoints
    ├── database/                      # Database layer (SQLAlchemy + SQLite)
    │   ├── connection.py
    │   ├── models.py
    │   └── crud.py
    ├── middleware/
    │   └── request_logger.py          # Request logging
    ├── templates/                     # Jinja2 HTML templates
    ├── static/                        # CSS & images
    └── data/                          # Runtime data (auto-created, gitignored)
```

## Pipeline

The report generation follows a two-step pipeline:

```
┌─────────────────────────────────┐     ┌──────────────────────────────┐
│  generate_financial_analysis.py │     │  create_equity_report.py     │
│                                 │     │                              │
│  1. Fetch data from FMP API     │────>│  1. Load analysis outputs    │
│  2. Process financial metrics   │     │  2. Auto-fetch market data   │
│  3. Generate 3-year forecasts   │     │  3. Generate charts          │
│  4. Run peer comparison         │     │  4. Render HTML report       │
│  5. AI text generation          │     │  5. Validate & regenerate    │
│                                 │     │                              │
│  Output: CSV + JSON + TXT       │     │  Output: 3-page HTML report  │
└─────────────────────────────────┘     └──────────────────────────────┘
```

## Quick Start

### 1. Configure API Keys

```bash
cp finrobot_equity/core/config/config.ini.template finrobot_equity/core/config/config.ini
```

Edit `config.ini` with your keys:

```ini
[API_KEYS]
fmp_api_key = YOUR_FMP_API_KEY          # https://financialmodelingprep.com/developer
openai_api_key = YOUR_OPENAI_API_KEY    # https://platform.openai.com/account/api-keys
```

### 2. Deploy via Script

```bash
chmod +x deploy.sh
./deploy.sh start
```

Access the web interface at `http://127.0.0.1:8001`.

### 3. Or Run via Command Line

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
    --tagline-file output/NVDA/analysis/tagline.txt \
    --company-overview-file output/NVDA/analysis/company_overview.txt \
    --investment-overview-file output/NVDA/analysis/investment_overview.txt \
    --valuation-overview-file output/NVDA/analysis/valuation_overview.txt \
    --risks-file output/NVDA/analysis/risks.txt \
    --competitor-analysis-file output/NVDA/analysis/competitor_analysis.txt \
    --major-takeaways-file output/NVDA/analysis/major_takeaways.txt \
    --peer-ev-ebitda-csv output/NVDA/analysis/peer_ev_ebitda_comparison.csv \
    --enable-text-regeneration \
    --config-file finrobot_equity/core/config/config.ini
```

## Deployment Commands

| Command | Description |
|:---|:---|
| `./deploy.sh start` | Start the web application (auto-installs dependencies) |
| `./deploy.sh stop` | Stop the application |
| `./deploy.sh restart` | Restart the application |
| `./deploy.sh status` | Check running status and recent logs |
| `./deploy.sh install` | Install/update dependencies only |

### Environment Variables

| Variable | Default | Description |
|:---|:---|:---|
| `GITHUB_CLIENT_ID` | — | GitHub OAuth client ID |
| `GITHUB_CLIENT_SECRET` | — | GitHub OAuth client secret |
| `FINROBOT_ADMIN_EMAIL` | `admin@finrobot.com` | Initial admin email |
| `FINROBOT_ADMIN_PASSWORD` | (random) | Initial admin password |
| `WEB_HOST` | `127.0.0.1` | Server bind address |
| `WEB_PORT` | `8001` | Server port |

## API Dependencies

| Service | Required | Purpose |
|:---|:---|:---|
| [Financial Modeling Prep](https://financialmodelingprep.com/developer) | Yes | Financial data, market metrics, peer comparison |
| [OpenAI](https://platform.openai.com/) | Yes | AI-powered text generation for report sections |

## License

Apache 2.0 — See [LICENSE](../LICENSE) for details.
