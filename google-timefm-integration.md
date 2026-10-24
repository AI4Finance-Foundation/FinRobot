# Google TimesFM Integration Plan for FinRobot

## 1. Executive Summary

This plan outlines the architecture, integration points, and implementation steps to incorporate **Google TimesFM** (Time Series Foundation Model) into the **FinRobot** and **finrobot_equity** platform.

Google TimesFM is a pretrained 200M-parameter time-series foundation model developed by Google Research. It delivers state-of-the-art **zero-shot forecasting** with both point forecasts and probabilistic prediction quantiles ($p_{10}, p_{20}, \dots, p_{90}$).

---

## 2. Target Integration Areas & Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                         Google TimesFM Engine                          │
│        (Zero-Shot Multi-Horizon Point & Quantile Forecasting)          │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
       ┌────────────────────────────┼────────────────────────────┐
       ▼                            ▼                            ▼
┌──────────────────────┐ ┌──────────────────────┐ ┌──────────────────────┐
│  FinGPT Forecaster   │ │ Financial Projections│ │ Quantitative Trading │
│                      │ │    & Sensitivity     │ │   & Strategy Alpha   │
├──────────────────────┤ ├──────────────────────┤ ├──────────────────────┤
│ • Daily/Weekly Stock │ │ • Revenue/EBITDA/FCF │ │ • Predictive Alpha   │
│   Price Trajectory   │ │   Multi-Year Forecast│   Signals for Backtest │
│ • Probabilistic      │ │ • Data-Driven Bear/  │ │ • Volatility Regime  │
│   Confidence Bands   │ │   Base/Bull Scenarios│   Forecasting          │
└──────────────────────┘ └──────────────────────┘ └──────────────────────┘
```

---

## 3. Key Target Areas in the Codebase

### Area 1: Stock Price & Movement Forecasting
* **Target Files:**
  * `finrobot/functional/forecasting.py` (New module)
  * `tutorials_advanced/agent_fingpt_forecaster.ipynb`
  * `finrobot/data_source/yfinance_utils.py`
* **Objective:**
  * Replace or augment qualitative text-based LLM price guessing with numerical point and quantile forecasts (e.g. 5–30 days ahead).
* **Inputs:** Daily OHLCV price series from yfinance.
* **Outputs:** Predicted trajectory, expected return, and 10th/50th/90th percentile bounds.

### Area 2: Financial Statement Projections (Revenue, EBITDA, FCF)
* **Target Files:**
  * `finrobot_equity/core/src/modules/financial_data_processor.py`
  * `finrobot_equity/core/src/generate_financial_analysis.py`
* **Objective:**
  * Replace static heuristics (e.g. fixed 5% annual growth) with data-driven time series forecasts from historical quarterly and annual financial filings.
* **Inputs:** Historical financial statement series (Quarterly / Annual).
* **Outputs:** 1–3 year forward estimates for Revenue, Cost of Operations, EBITDA, and Free Cash Flow.

### Area 3: Statistical Confidence Intervals & Scenario Analysis
* **Target Files:**
  * `finrobot_equity/core/src/modules/sensitivity_analyzer.py`
  * `finrobot_equity/core/src/modules/valuation_engine.py`
* **Objective:**
  * Use TimesFM quantile outputs ($p_{10}, p_{50}, p_{90}$) as empirical **Bear Case**, **Base Case**, and **Bull Case** scenarios in DCF modeling and sensitivity heatmaps.

### Area 4: Quantitative Trading Signals in Backtrader
* **Target Files:**
  * `finrobot/functional/quantitative.py` (`BackTraderUtils`)
* **Objective:**
  * Provide a `TimesFMPredictorIndicator` for Backtrader that generates entry/exit and position sizing signals based on expected forward multi-bar returns.

---

## 4. Implementation Blueprint

### Step 1: Core TimesFM Wrapper Module (`finrobot/functional/timesfm_utils.py`)

```python
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional

class TimesFMForecaster:
    """Wrapper for Google TimesFM time series foundation model."""

    def __init__(
        self,
        context_len: int = 512,
        horizon_len: int = 30,
        backend: str = "cpu",
        repo_id: str = "google/timesfm-1.0-200m"
    ):
        try:
            import timesfm
            self.tfm = timesfm.TimesFm(
                context_len=context_len,
                horizon_len=horizon_len,
                input_patch_len=32,
                output_patch_len=128,
                num_layers=20,
                model_dims=1280,
                backend=backend,
            )
            self.tfm.load_from_checkpoint(repo_id=repo_id)
            self.is_available = True
        except Exception as e:
            print(f"Warning: TimesFM initialization failed ({e}). Fallback mode active.")
            self.tfm = None
            self.is_available = False

    def forecast_series(
        self,
        series: pd.Series,
        freq: int = 0,
        horizon: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Forecast a given pandas Series.
        freq: 0 (daily/high-freq), 1 (weekly), 2 (monthly/quarterly)
        """
        if not self.is_available or self.tfm is None:
            # Heuristic fallback if model not installed
            last_val = series.dropna().iloc[-1]
            return {
                "point_forecast": np.full(horizon or 30, last_val),
                "bear_case_p10": np.full(horizon or 30, last_val * 0.95),
                "base_case_p50": np.full(horizon or 30, last_val),
                "bull_case_p90": np.full(horizon or 30, last_val * 1.05),
            }

        values = series.dropna().values.astype(np.float32)
        forecast, quantiles = self.tfm.forecast(
            inputs=[values],
            freq=[freq]
        )
        
        return {
            "point_forecast": forecast[0],
            "quantiles": quantiles[0],
            "bear_case_p10": quantiles[0][0],
            "base_case_p50": forecast[0],
            "bull_case_p90": quantiles[0][-1],
        }
```

---

## 5. Deployment & Dependency Requirements

1. **Python Dependencies:**
   ```bash
   pip install timesfm
   # Or for JAX/GPU acceleration:
   # pip install "timesfm[torch]" or "timesfm[jax]"
   ```
2. **Hardware Requirements:**
   * **CPU Mode:** Supported for inference (standard environments).
   * **GPU Mode (CUDA / Apple Silicon Metal):** Recommended for batch backtesting and multi-asset universes.

---

## 6. Phased Rollout Plan

- [ ] **Phase 1:** Add `finrobot/functional/timesfm_utils.py` and register tools in `finrobot/toolkits.py`.
- [ ] **Phase 2:** Integrate with `finrobot_equity` financial forecasting & sensitivity analysis.
- [ ] **Phase 3:** Integrate with `FinGPT-Forecaster` notebook tutorials for hybrid LLM + TimesFM stock predictions.
- [ ] **Phase 4:** Add Backtrader TimesFM alpha indicators in `quantitative.py`.
