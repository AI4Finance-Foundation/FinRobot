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
    - start <= 0 or end <= 0 or years <= 0 (geometric-mean growth is undefined for
      non-positive endpoints: a negative end makes ``(end/start)**(1/years)`` a
      complex number — the old code crashed with TypeError on ``float(complex)`` —
      and a zero end is a degenerate -100% that no compounding rate represents
      honestly; honest missing beats a fabricated rate)
    - start or end is NaN/Inf (upstream polluted data; caller should log and fall back)
    """
    if not (math.isfinite(start) and math.isfinite(end)):
        return None
    if start <= 0 or end <= 0 or years <= 0:
        return None
    return float((end / start) ** (1 / years) - 1)
