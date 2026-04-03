# Data Source Suggestion: FinancialReports.eu for Financial Agent Analysis

## Overview

[FinancialReports.eu](https://financialreports.eu) provides API access to **14M+ filings** from data sources across 30+ countries. Its Markdown conversion endpoint returns LLM-ready text from annual reports, making it ideal for FinRobot's multi-agent financial analysis pipeline.

## Why This Fits FinRobot

FinRobot's agents analyze financial documents and generate research reports. FinancialReports.eu adds:

- **Global filings** — annual reports, interim results, ESG disclosures, M&A announcements from 30+ countries
- **Markdown endpoint** (`GET /filings/{id}/markdown/`) — returns clean text from filing PDFs, ready to feed into LLM agent pipelines
- **33,000+ companies** with ISIN, LEI, and GICS classification
- **11 standardized categories** — Financial Reporting, ESG, M&A, Debt/Equity, Management changes, and more
- **Extends research beyond US** — covers EU, UK, Japan, South Korea, Switzerland, Turkey, Israel, and more

## Integration Approaches

### 1. Filing Analysis Agent Tool

Add FinancialReports.eu as a tool that agents can call to fetch and analyze filings:

```python
import requests

headers = {"X-API-Key": "your-api-key"}

# Search filings for a company
resp = requests.get("https://api.financialreports.eu/filings/",
    headers=headers,
    params={
        "company_isin": "GB0002374006",  # Diageo ISIN
        "categories": "2",               # Financial Reporting
        "page_size": 5
    }
)
filings = resp.json()["results"]

# Get filing content as Markdown for LLM analysis
filing_id = filings[0]["id"]
content = requests.get(
    f"https://api.financialreports.eu/filings/{filing_id}/markdown/",
    headers=headers
).text

# Feed into FinRobot's LLM agent pipeline for analysis
```

### 2. MCP Server Integration

FinancialReports.eu offers an [MCP server](https://financialreports.eu) compatible with Claude.ai and other AI platforms — FinRobot agents could connect to it directly via MCP.

### 3. Python SDK

```bash
pip install financial-reports-generated-client
```

```python
from financial_reports_client import Client
from financial_reports_client.api.filings import filings_list, filings_markdown_retrieve

client = Client(base_url="https://api.financialreports.eu")
client = client.with_headers({"X-API-Key": "your-api-key"})

filings = filings_list.sync(client=client, company_isin="GB0002374006", categories="2")
content = filings_markdown_retrieve.sync(client=client, id=filings.results[0].id)
```

## API Details

| Property | Value |
|---|---|
| **Base URL** | `https://api.financialreports.eu` |
| **API Docs** | [docs.financialreports.eu](https://docs.financialreports.eu/) |
| **Authentication** | API key via `X-API-Key` header |
| **Python SDK** | `pip install financial-reports-generated-client` |
| **Rate Limiting** | Burst limit + monthly quota |
| **Companies** | 33,230+ |
| **Total Filings** | 14,135,359+ |
| **Coverage** | 30+ countries |

## Agent Use Cases

| Agent Task | How FinancialReports.eu Helps |
|---|---|
| Company research | Pull annual reports and filings globally |
| ESG analysis | Dedicated ESG filing category across all countries |
| M&A monitoring | M&A/Partnerships/Legal filing category |
| Earnings analysis | Financial Reporting filings with Markdown text |
| Cross-market comparison | Standardized categories across 30+ countries |
| Report generation | Source filing documents for evidence-based reports |
