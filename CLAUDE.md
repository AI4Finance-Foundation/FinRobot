# FinRobot Development Standards

> This file defines the coding standards, conventions, and rules for the FinRobot project.
> All contributors (human and AI) must follow these guidelines.

## Tech Stack

### Allowed

| Category | Technology | Notes |
|----------|------------|-------|
| **Python** | 3.10-3.11 | Type hints required (mypy strict) |
| **TypeScript** | 5.x | Strict mode with maximum type safety |
| **Frontend** | Next.js 14+ (App Router) | React 18+, TailwindCSS |
| **Testing** | Pytest (Python), Vitest (TypeScript) | 70% minimum coverage |
| **Validation** | Pydantic (Python), Zod (TypeScript) | All external inputs |
| **API** | FastAPI (Python), Next.js API Routes | REST preferred |
| **LLM** | OpenAI GPT-4o, AutoGen | Multi-agent orchestration |

### Forbidden

- `any` type in TypeScript (use `unknown` with type guards instead)
- Bare `except:` in Python (always catch specific exceptions)
- Global variables for state management
- Hardcoded secrets or API keys in code
- `console.log` in production code (use structured logging)
- Streamlit (legacy - migrate to Next.js)
- Spanish identifiers (all code must be in English)

---

## Naming Conventions

### Python

```python
# Files: snake_case
portfolio_tracker.py
risk_analyzer.py

# Classes: PascalCase
class PortfolioAnalyzer:
    pass

class InvestorProfile:
    pass

# Functions/Methods: snake_case
def calculate_returns(self) -> float:
    pass

def get_current_allocation(portfolio_id: str) -> dict:
    pass

# Constants: SCREAMING_SNAKE_CASE
MAX_RETRY_ATTEMPTS = 3
DEFAULT_TIMEOUT_SECONDS = 30
RISK_FREE_RATE = 0.035

# Private: leading underscore
def _internal_calculation(self) -> float:
    pass

# Type aliases: PascalCase
PortfolioId = str
AllocationDict = dict[str, float]
```

### TypeScript

```typescript
// Files: camelCase for utilities, PascalCase for components
portfolioTracker.ts
useLivePrices.ts
PortfolioCard.tsx

// Interfaces/Types: PascalCase
interface Position {
  ticker: string;
  shares: number;
  avgCost: number;
}

type PortfolioMetrics = {
  totalValue: number;
  totalPnL: number;
};

// Functions: camelCase
function calculateReturns(): number {
  return 0;
}

// Constants: SCREAMING_SNAKE_CASE
const MAX_RETRY_ATTEMPTS = 3;
const DEFAULT_TIMEOUT_MS = 30000;

// React Components: PascalCase
function PortfolioCard({ position }: { position: Position }) {
  return <div>{position.ticker}</div>;
}

// Hooks: camelCase with "use" prefix
function useLivePrices(tickers: string[]) {
  return { prices: [], loading: false };
}
```

---

## Error Handling

### Python - Correct Pattern

```python
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class DataFetchError(Exception):
    """Failed to fetch data from external source."""
    pass

class ConfigurationError(Exception):
    """Missing or invalid configuration."""
    pass

# CORRECT: Specific exception handling with logging
def fetch_stock_data(ticker: str) -> Optional[dict]:
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.Timeout:
        logger.warning(f"Timeout fetching data for {ticker}")
        raise DataFetchError(f"Timeout: {ticker}")
    except requests.HTTPError as e:
        logger.error(f"HTTP error {e.response.status_code} for {ticker}")
        raise DataFetchError(f"HTTP {e.response.status_code}: {ticker}")
    except requests.RequestException as e:
        logger.error(f"Request failed for {ticker}: {e}")
        raise DataFetchError(f"Request failed: {ticker}")

# WRONG: Never do this
def bad_fetch(ticker: str):
    try:
        return api.fetch(ticker)
    except:  # NEVER use bare except
        pass  # NEVER silently ignore errors
```

### TypeScript - Correct Pattern

```typescript
// Custom error types
export class FinRobotError extends Error {
  constructor(
    message: string,
    public code: string
  ) {
    super(message);
    this.name = "FinRobotError";
  }
}

export class DataFetchError extends FinRobotError {
  constructor(message: string) {
    super(message, "DATA_FETCH_ERROR");
  }
}

// CORRECT: Proper error handling
async function fetchPrices(tickers: string[]): Promise<PriceData> {
  try {
    const response = await fetch(url, {
      signal: AbortSignal.timeout(10000),
    });

    if (!response.ok) {
      throw new DataFetchError(`HTTP ${response.status}`);
    }

    return await response.json();
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      console.warn(`Timeout fetching prices for ${tickers.join(",")}`);
      throw new DataFetchError("Request timeout");
    }
    throw error;
  }
}

// WRONG: Never do this
async function badFetch(url: string) {
  try {
    return await fetch(url).then((r) => r.json());
  } catch {
    // NEVER silently return null on error
    return null;
  }
}
```

---

## Testing Requirements

### Minimum Coverage: 70%

### Python (Pytest)

```python
# Location: tests/ directory mirroring src structure
# Naming: test_<module>.py

# Example structure:
# mi_patrimonio/
#   core/
#     portfolio.py
#   tests/
#     test_portfolio.py
#     conftest.py

# Required test coverage:
# - All financial calculations (100% coverage)
# - API integrations (mock external calls)
# - Data transformations
# - Error handling paths

# Example test file
import pytest
from unittest.mock import Mock, patch

class TestPortfolioCalculations:
    def test_calculate_returns_positive(self):
        portfolio = Portfolio(cost=1000, value=1100)
        assert portfolio.calculate_returns() == 0.10

    def test_calculate_returns_negative(self):
        portfolio = Portfolio(cost=1000, value=900)
        assert portfolio.calculate_returns() == -0.10

    @patch("mi_patrimonio.data_provider.requests.get")
    def test_fetch_prices_timeout(self, mock_get):
        mock_get.side_effect = requests.Timeout()
        with pytest.raises(DataFetchError):
            fetch_prices(["AAPL"])
```

### TypeScript (Vitest)

```typescript
// Location: __tests__/ or *.test.ts adjacent to source
// Naming: <module>.test.ts

// Required test coverage:
// - React hooks (useLivePrices, usePerformanceMetrics)
// - API route handlers
// - Utility functions
// - Component rendering (React Testing Library)

// Example test file
import { describe, it, expect, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useLivePrices } from "../lib/useLivePrices";

describe("useLivePrices", () => {
  it("should fetch prices for given tickers", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ AAPL: { price: 150 } }),
    });

    const { result } = renderHook(() => useLivePrices(["AAPL"]));

    await waitFor(() => {
      expect(result.current.prices.AAPL.price).toBe(150);
    });
  });

  it("should handle fetch errors", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("Network error"));

    const { result } = renderHook(() => useLivePrices(["AAPL"]));

    await waitFor(() => {
      expect(result.current.error).toBeTruthy();
    });
  });
});
```

---

## Git Workflow

### Branch Naming

```
feature/<scope>-<short-description>
fix/<scope>-<short-description>
refactor/<scope>-<description>
test/<scope>-<description>
docs/<scope>-<description>

Examples:
feature/portfolio-add-rebalancing
fix/api-timeout-handling
refactor/data-english-migration
test/portfolio-calculations
```

### Commit Messages (Conventional Commits)

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

**Types:**

- `feat`: New feature
- `fix`: Bug fix
- `refactor`: Code change that neither fixes a bug nor adds a feature
- `test`: Adding or updating tests
- `docs`: Documentation only changes
- `chore`: Changes to build process or auxiliary tools
- `style`: Formatting, missing semicolons, etc.
- `perf`: Performance improvements

**Scopes:**

- `portfolio`: Portfolio management
- `api`: API endpoints
- `ui`: User interface
- `data`: Data sources
- `agents`: AI agents
- `security`: Security fixes

**Examples:**

```
feat(portfolio): add real-time price updates

fix(api): handle timeout in price fetching
- Add AbortSignal.timeout() to all fetch calls
- Return cached data on timeout

refactor(data): migrate identifiers to English
- Rename PERFILES_RIESGO to RISK_PROFILES
- Rename calcular_distribucion to calculate_distribution

test(portfolio): add unit tests for returns calculation
```

### PR Requirements

Before merging, ensure:

- [ ] All tests pass (`pytest` and `npm test`)
- [ ] Coverage >= 70%
- [ ] No TypeScript errors (`tsc --noEmit`)
- [ ] No Python linting errors (`ruff check .`)
- [ ] Conventional commit message format
- [ ] Self-reviewed (no debug code, no TODOs)
- [ ] Updated PLAN.md if architecture changed

---

## Security Rules

### Secrets Management

```python
# CORRECT: Environment variables
import os

api_key = os.environ.get("OPENAI_API_KEY")
if not api_key:
    raise ConfigurationError("OPENAI_API_KEY environment variable not set")

# CORRECT: Configuration file (gitignored)
from pathlib import Path
import json

config_path = Path.home() / ".finrobot" / "config.json"
if config_path.exists():
    with open(config_path) as f:
        config = json.load(f)
        api_key = config.get("openai_api_key")

# WRONG: Hardcoded secrets
api_key = "sk-abc123..."  # NEVER hardcode

# WRONG: Secrets in URLs (appear in logs)
url = f"https://api.example.com?apikey={api_key}"  # NEVER put secrets in URLs
```

### Input Validation

```python
# CORRECT: Pydantic validation for all external inputs
from pydantic import BaseModel, field_validator

class PositionInput(BaseModel):
    ticker: str
    shares: float
    avg_cost: float

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, v: str) -> str:
        if not v or len(v) > 10:
            raise ValueError("Invalid ticker format")
        return v.upper().strip()

    @field_validator("shares")
    @classmethod
    def validate_shares(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Shares must be positive")
        return v
```

```typescript
// CORRECT: Zod validation for TypeScript
import { z } from "zod";

const PositionSchema = z.object({
  ticker: z
    .string()
    .min(1)
    .max(10)
    .transform((s) => s.toUpperCase().trim()),
  shares: z.number().positive(),
  avgCost: z.number().nonnegative(),
});

type Position = z.infer<typeof PositionSchema>;

function validatePosition(input: unknown): Position {
  return PositionSchema.parse(input);
}
```

---

## Project Structure

```
FinRobot/
├── CLAUDE.md                    # This file - coding standards
├── PLAN.md                      # Migration roadmap
├── pyproject.toml               # Python project config (ruff, mypy, pytest)
├── .pre-commit-config.yaml      # Pre-commit hooks
│
├── finrobot/                    # Core AI library
│   ├── agents/                  # AI agent definitions
│   │   ├── agent_library.py     # Predefined agents
│   │   ├── fund_agents.py       # Investment fund agents
│   │   └── workflow.py          # Multi-agent patterns
│   │
│   ├── data_source/             # External data integrations
│   │   ├── finnhub_utils.py
│   │   ├── yfinance_utils.py
│   │   ├── sec_utils.py
│   │   └── news_utils.py
│   │
│   ├── functional/              # Analysis tools
│   │   ├── analyzer.py
│   │   ├── quantitative.py
│   │   └── charting.py
│   │
│   └── tests/
│       ├── test_agents.py
│       └── test_data_sources.py
│
├── mi_patrimonio/               # Portfolio management
│   ├── core/
│   │   ├── portfolio.py         # Portfolio models
│   │   ├── portfolio_config.py  # Configuration
│   │   └── exceptions.py        # Custom exceptions
│   │
│   ├── services/
│   │   ├── agent_service.py     # Agent integration
│   │   └── alerts.py            # Alert rules
│   │
│   ├── api/
│   │   └── price_server.py      # FastAPI server
│   │
│   └── tests/
│       └── test_portfolio.py
│
├── vercel-patrimonio/           # Next.js frontend
│   ├── app/
│   │   ├── api/                 # API routes
│   │   └── page.tsx             # Main dashboard
│   │
│   ├── components/
│   │   └── AgentInsights.tsx
│   │
│   ├── lib/
│   │   ├── portfolioPositions.ts
│   │   ├── useLivePrices.ts
│   │   └── errors.ts
│   │
│   └── __tests__/
│       └── useLivePrices.test.ts
│
└── scripts/
    └── start_services.sh
```

---

## Code Quality Commands

### Python

```bash
# Linting & Formatting
ruff check .                    # Check for issues
ruff check --fix .              # Auto-fix issues
ruff format .                   # Format code

# Type Checking
mypy --strict mi_patrimonio/    # Strict type checking

# Testing
pytest                          # Run all tests
pytest --cov=mi_patrimonio      # With coverage
pytest --cov-fail-under=70      # Fail if coverage < 70%
```

### TypeScript

```bash
# Type Checking
cd vercel-patrimonio
tsc --noEmit                    # Type check without emitting

# Linting
npm run lint                    # ESLint
npm run lint:fix                # Auto-fix

# Testing
npm test                        # Run tests
npm test -- --coverage          # With coverage
```

### Pre-commit

```bash
# Install hooks
pre-commit install

# Run on all files
pre-commit run --all-files

# Run specific hook
pre-commit run ruff --all-files
```

---

## AI Agent Development

### Adding New Agents

```python
# In finrobot/agents/fund_agents.py

FUND_AGENT_LIBRARY = {
    "My_New_Agent": {
        "title": "My New Agent Title",
        "profile": "Detailed description of the agent's expertise...",
        "responsibilities": [
            "Specific task 1",
            "Specific task 2",
            "Specific task 3",
        ],
        "toolkits": [
            ExistingUtils.some_function,
            ExistingUtils.another_function,
        ],
    },
}
```

### Adding New Data Sources

```python
# In finrobot/data_source/new_utils.py

import os
from functools import wraps
from typing import Annotated
import pandas as pd

def init_new_api(func):
    """Decorator to initialize API client."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        api_key = os.environ.get("NEW_API_KEY")
        if not api_key:
            raise ConfigurationError("NEW_API_KEY not set")
        # Initialize client...
        return func(*args, **kwargs)
    return wrapper

class NewDataUtils:
    """New data source integration."""

    @staticmethod
    @init_new_api
    def get_data(
        ticker: Annotated[str, "Stock ticker symbol"],
        start_date: Annotated[str, "Start date YYYY-MM-DD"],
    ) -> pd.DataFrame:
        """Fetch data from new source."""
        # Implementation...
        pass
```

---

## Change Log

| Date | Version | Changes |
|------|---------|---------|
| 2026-01-14 | 1.0.0 | Initial standards document |
