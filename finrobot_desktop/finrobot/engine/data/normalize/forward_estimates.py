"""normalize_forward_estimates: raw FORWARD_ESTIMATES DataResult → envelope.

Transport-level normalization only — row interpretation (FY1 selection, growth
derivation) is the §6.4.1 red-line leaf's monopoly
(``compute.operators.forward_estimates``). This gate validates the envelope
shape (a list of dict rows; anything else is dropped), stamps provenance and
carries the raw fetch's warnings, so the canonical cache never stores an
unserializable or shape-ambiguous payload.
"""

from __future__ import annotations

from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.normalize.contracts import (
    NormalizedForwardEstimates,
    Provenance,
)


def normalize_forward_estimates(result: DataResult) -> NormalizedForwardEstimates:
    data = result.data if isinstance(result.data, dict) else {}
    raw_rows = data.get("rows")
    rows = [r for r in raw_rows if isinstance(r, dict)] if isinstance(raw_rows, list) else []
    return NormalizedForwardEstimates(
        ticker=result.ticker,
        rows=rows,
        provenance=Provenance(
            provider=result.provider,
            # FMP serves the current consensus with no publication instant in
            # the payload — fetch time is the honest semantic as_of.
            as_of=result.timestamp,
            fetched_at=result.timestamp,
        ),
        warnings=list(result.warnings),
    )
