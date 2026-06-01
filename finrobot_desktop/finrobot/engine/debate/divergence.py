"""Divergence-point recomputation for the IC debate pipeline (ADR-0007, Task 4).

Core invariant: all DCF arithmetic stays in engine/compute/dcf.py.
This module only maps DivergencePoint assumption names to the overrides dict
and delegates computation to ``compute_dcf_implied_price``.  Zero DCF math
lives here.

Supported assumption names (case-insensitive, stored lower-case in the model):
    "wacc"              — bull/bear disagree on the discount rate.
    "terminal_growth"   — bull/bear disagree on the long-run growth rate.
"""

from __future__ import annotations

from finrobot.engine.compute.dcf import compute_dcf_implied_price
from finrobot.engine.debate.models import DivergencePoint
from finrobot.engine.models.financial import DCFInputs

# Re-export so tests can monkeypatch via this module's namespace without
# reaching into engine.compute.  Callers that need the real function should
# import from engine.compute.dcf directly.
__all__ = ["recompute_divergence"]

# ---------------------------------------------------------------------------
# Assumption name → override key mapping
# ---------------------------------------------------------------------------

# Maps the human-readable assumption name stored in DivergencePoint.assumption
# to the key accepted by compute_dcf_implied_price's `overrides` dict.
_ASSUMPTION_TO_OVERRIDE_KEY: dict[str, str] = {
    "wacc": "wacc",
    "terminal_growth": "terminal_growth",
    "terminal_growth_rate": "terminal_growth",  # alias
}


def recompute_divergence(
    point: DivergencePoint,
    base_inputs: DCFInputs,
) -> DivergencePoint:
    """Recompute implied equity prices for a single DivergencePoint.

    For the assumption named in ``point.assumption``, substitutes
    ``point.bull_value`` and ``point.bear_value`` independently into the
    canonical DCF arithmetic (``compute_dcf_implied_price``), holding all
    other inputs in ``base_inputs`` constant.  Returns a model_copy of
    ``point`` with ``bull_implied_price`` and ``bear_implied_price`` filled in.

    Parameters
    ----------
    point:
        A DivergencePoint whose bull/bear values diverge on a single
        assumption.  ``point.assumption`` must be a key in
        ``_ASSUMPTION_TO_OVERRIDE_KEY``; anything else raises ``KeyError``
        immediately rather than silently ignoring it.
    base_inputs:
        The DCFInputs produced by ``seed_dcf_inputs`` for this ticker — the
        same inputs the single-stock report used.  All non-diverging
        assumptions are taken from here.

    Returns
    -------
    DivergencePoint
        A new DivergencePoint (model_copy) with ``bull_implied_price`` and
        ``bear_implied_price`` populated.

    Raises
    ------
    KeyError
        If ``point.assumption`` is not a supported assumption name.
    ValueError
        If either value violates the Gordon Growth Model constraint
        (terminal_growth >= wacc).
    """
    assumption_lower = point.assumption.lower()
    override_key = _ASSUMPTION_TO_OVERRIDE_KEY.get(assumption_lower)
    if override_key is None:
        supported = sorted(_ASSUMPTION_TO_OVERRIDE_KEY)
        raise KeyError(
            f"Unsupported divergence assumption: {point.assumption!r}. "
            f"Supported: {supported}"
        )

    bull_price = compute_dcf_implied_price(
        base_inputs,
        overrides={override_key: point.bull_value},
    )
    bear_price = compute_dcf_implied_price(
        base_inputs,
        overrides={override_key: point.bear_value},
    )

    return point.model_copy(
        update={
            "bull_implied_price": bull_price,
            "bear_implied_price": bear_price,
        }
    )
