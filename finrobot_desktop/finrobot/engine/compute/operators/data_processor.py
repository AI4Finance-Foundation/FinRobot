"""Deterministic CAGR computation (CFA-standard).

Reproducible: identical inputs → identical output with an auditable formula,
where an LLM would produce plausible-but-varying numbers.
"""

from __future__ import annotations

import math


def calculate_cagr(start: float, end: float, years: int) -> float | None:
    """Compound Annual Growth Rate per CFA Institute formula.

    CAGR = (end / start) ^ (1 / years) - 1

    Returns None if:
    - start <= 0 or years <= 0 (formula undefined)
    - start or end is NaN (upstream NaN-polluted data; caller should log and fall back)
    """
    if math.isnan(start) or math.isnan(end):
        return None
    if start <= 0 or years <= 0:
        return None
    return float((end / start) ** (1 / years) - 1)
