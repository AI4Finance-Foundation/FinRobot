"""Pull entry_price / target_price / target_date out of a saved Artifact.

ArtifactSummary's v5 fields (ADR-0001) are populated lazily from the full
Artifact by `_summary_from_artifact` in store.py — no schema additions to
ArtifactMeta / ArtifactInputs are needed, the data is already there:

- `entry_price` lives in ArtifactInputs.raw_data under the FinancialData
  dump path `market.current_price` (the quote snapshot at fetch time).
- `target_price` lives in ArtifactOutputs.structured. Each pipeline puts it
  in a slightly different place — equity_research has it under
  `thesis.price_target`, dcf/ddm/lbo/comps store an `implied_price`. We
  honour each known shape and fall back to None.
- `target_date` is unset by every current pipeline, so we default to
  created_at + 365 days whenever a target_price is available. Pipelines can
  override later by writing `structured["thesis"]["target_date"]`.

Lookups are best-effort. Missing / malformed values return None so the
summary still loads; old artifacts therefore appear with all four fields
None until the user re-runs the pipeline.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from finagent.artifact.models import Artifact

_DEFAULT_TARGET_HORIZON = timedelta(days=365)


def extract_entry_price(artifact: "Artifact") -> float | None:
    """Quote at the time the pipeline fetched data (best available proxy)."""
    market = artifact.inputs.raw_data.get("market")
    if isinstance(market, dict):
        return _coerce_positive_float(market.get("current_price"))
    # Some pipelines (e.g. earnings) skip the standard fetch path.
    return None


def extract_target_price(artifact: "Artifact") -> float | None:
    """AI-given target price from whichever structured slot the pipeline used."""
    structured = artifact.outputs.structured

    # equity_research / ic_memo store the synthesis agent thesis here.
    thesis = structured.get("thesis")
    if isinstance(thesis, dict):
        for key in ("price_target", "target_price"):
            if (v := _coerce_positive_float(thesis.get(key))) is not None:
                return v

    # Single-method valuation pipelines surface an implied_price directly.
    for nest in ("financial_modeling", "dcf_calc", "ddm_calc"):
        nested = structured.get(nest)
        if isinstance(nested, dict):
            if (v := _coerce_positive_float(nested.get("implied_price"))) is not None:
                return v

    # Plain DCF / LBO artifacts dump the result at the top of structured.
    for key in ("implied_price", "target_price"):
        if (v := _coerce_positive_float(structured.get(key))) is not None:
            return v

    return None


def extract_target_date(artifact: "Artifact", target_price: float | None) -> datetime | None:
    """target_date defaults to created_at + 365d once a target exists."""
    if target_price is None:
        return None
    thesis = artifact.outputs.structured.get("thesis")
    if isinstance(thesis, dict):
        raw = thesis.get("target_date")
        if isinstance(raw, datetime):
            return raw
        if isinstance(raw, str):
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                pass
    return artifact.meta.created_at + _DEFAULT_TARGET_HORIZON


def _coerce_positive_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None
