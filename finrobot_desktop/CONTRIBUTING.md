# Contributing to FinAgent

## Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)

## Setup

```bash
git clone https://github.com/...
cd FinAgent
uv sync --all-extras
cp .env.example .env
# Fill in your API key in .env
```

## Running Tests

```bash
uv run pytest tests/unit/ -v
```

## Code Standards

All three must pass before submitting a PR:

```bash
uv run ruff format finagent/        # auto-format
uv run ruff check finagent/         # lint
uv run mypy finagent/ --ignore-missing-imports  # type check
```

## Financial Calculations

Any change to `finagent/engine/compute/` must include:

1. A unit test with a hand-calculated expected value (not derived from the function under test)
2. A reference to the formula source — textbook, CFA curriculum, Damodaran, Rosenbaum & Pearl, etc.

Example of an acceptable test:

```python
def test_wacc_example():
    """
    CAPM: CoE = 4% + 1.2 × 5% = 10%
    WACC = 0.9 × 10% + 0.1 × 4% × (1 - 0.21) = 9.316%
    Source: Damodaran, "Investment Valuation" 3rd Ed., Chapter 8.
    """
    coe, wacc = calculate_wacc(0.04, 1.2, 0.05, 0.04, 0.21, 0.1)
    assert abs(coe - 0.10) < 1e-9
    assert abs(wacc - 0.09316) < 1e-9
```

## Pull Request Process

1. Fork the repo
2. Create a branch: `git checkout -b fix/your-description`
3. Make changes; ensure all checks pass
4. Submit PR against `main`
