"""Pull entry_price / target_price / target_date out of a saved Artifact.

ArtifactSummary's v5 fields (ADR-0001) are populated lazily from the full
Artifact by `_summary_from_artifact` in store.py — no schema additions to
ArtifactMeta / ArtifactInputs are needed, the data is already there:

- `entry_price` lives in ArtifactInputs.raw_data under the FinancialData
  dump path `market.current_price` (the quote snapshot at fetch time).
- `target_price` lives in ArtifactOutputs.structured. Each pipeline puts it in
  a slightly different place — equity_research has it under `thesis.price_target`;
  plain dcf dumps a top-level `implied_price`; plain ddm dumps a top-level
  `equity_value_per_share` (DDMResult has no `implied_price` field). lbo / comps
  carry no per-share headline. We honour each known shape and fall back to None.
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
    from finrobot.artifact.models import Artifact

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

    # equity_research / ic_memo store the synthesis agent thesis here. A
    # ``thesis`` block is AUTHORITATIVE: its ``price_target`` is the gated,
    # cross-checked headline. The data-health gate deliberately nulls it when
    # the valuation is untrustworthy (a single method 0.05x the market, methods
    # disagreeing > 50%, …). Honour that withhold — do NOT fall through to the
    # raw ``financial_modeling.implied_price`` below. ``financial_modeling`` is
    # the un-gated DCF that only ever ships alongside a thesis, so resurrecting
    # it here re-published the very number the gate suppressed (TSLA $20.38 /
    # AMD $22.39 stamped on REVIEW verdicts, 2026-06-05) into the coverage-list
    # column and the signal lamp.
    thesis = structured.get("thesis")
    if isinstance(thesis, dict):
        for key in ("price_target", "target_price"):
            if (v := _coerce_positive_float(thesis.get(key))) is not None:
                return v
        return None

    # Single-method valuation artifacts dump the result model FLAT at the top of
    # structured (builders.py `_safe_dump(result)`) — never nested. Plain DCF
    # surfaces `implied_price`; plain DDM's per-share headline is
    # `equity_value_per_share` (DDMResult carries no `implied_price`). The earlier
    # `dcf_calc`/`ddm_calc` nested read matched no builder output, so every DDM
    # target silently extracted as None.
    for key in ("implied_price", "target_price", "equity_value_per_share"):
        if (v := _coerce_positive_float(structured.get(key))) is not None:
            return v

    return None


# Legacy-only neutral display token. Pre-Phase-2 artifacts stored
# recommendation=="REVIEW" (the deleted refuse-to-judge verdict). New artifacts
# NEVER produce it — the verdict is always directional, the target alone is
# withheld (valuation_withheld). We map a legacy REVIEW to this neutral token
# rather than dropping it to None (the artifact still exists and must surface)
# while never re-emitting the "REVIEW" string the contract forbids.
_WITHHELD_VERDICT_DISPLAY = "WITHHELD"


def extract_verdict(artifact: "Artifact") -> str | None:
    """Pull the directional BUY / HOLD / SELL recommendation from a synthesis
    thesis.

    Stage A landing's hit-rate banner buckets by verdict (only BUY/HOLD/SELL
    create a bucket; everything else still feeds ``overall``). Returns None when
    the artifact has no thesis (e.g. peer_research, ad_hoc) or the recommend
    field is missing / malformed.

    Legacy compatibility: an old stored artifact may carry recommendation==
    "REVIEW" (the deleted refuse-to-judge verdict). It is mapped to the neutral
    ``WITHHELD`` display token — readable, never dropped to None, and never the
    forbidden "REVIEW" string. New artifacts only ever write BUY/HOLD/SELL.
    """
    thesis = artifact.outputs.structured.get("thesis")
    if not isinstance(thesis, dict):
        return None
    raw = thesis.get("recommendation") or thesis.get("verdict")
    if not isinstance(raw, str):
        return None
    normalised = raw.strip().upper()
    if normalised in ("BUY", "HOLD", "SELL"):
        return normalised
    # Legacy artifacts only — read REVIEW, surface a neutral display, never write it.
    if normalised == "REVIEW":
        return _WITHHELD_VERDICT_DISPLAY
    return None


def extract_fairly_valued(artifact: "Artifact") -> bool:
    """In-band point-target withhold = "fairly valued" (a confident HOLD).

    True when the valuation point was withheld BECAUSE the live price sits
    inside the cross-method fair-value band: ``synthesize_valuations`` leads
    such a ``price_target_basis`` with "FAIRLY VALUED" (the generic
    ``_range_spans_market`` path and the bank residual-income ``in_band`` path
    both do). A genuine withhold (M&A data poisoning / a single divergent
    method) leads with "WITHHELD" instead and returns False.

    Mirrors the frontend ``fairlyValued`` derivation in ``reportData.ts``
    (``valuation_withheld === true && /^\\s*fairly valued/i.test(basis)``) so
    the version-timeline column and the report body agree on the same signal.
    Legacy / un-backfilled rows extract False (no thesis / no flag → not
    fairly valued), which the UI treats as a generic withhold.
    """
    structured = artifact.outputs.structured
    if structured.get("valuation_withheld") is not True:
        return False
    thesis = structured.get("thesis")
    basis = thesis.get("price_target_basis", "") if isinstance(thesis, dict) else ""
    return isinstance(basis, str) and basis.lstrip().upper().startswith("FAIRLY VALUED")


def extract_tagline(artifact: "Artifact") -> str | None:
    """Pull the narrative `tagline` — a ≤60-char shareable conclusion
    written by the synthesis_agent. Surfaced on the workspace AI zone's
    hot-state card so analysts see the actual LLM call instead of the
    generic pipeline.format_summary() preview that gets stored as headline.

    Returns None when:
      · artifact has no thesis (peer_research / ad_hoc)
      · thesis lacks the optional tagline slot (legacy artifacts pre the
        2026-05 narrative bump)
      · tagline isn't a string after coercion
    """
    thesis = artifact.outputs.structured.get("thesis")
    if not isinstance(thesis, dict):
        return None
    raw = thesis.get("tagline")
    if not isinstance(raw, str):
        return None
    stripped = raw.strip()
    return stripped or None


def extract_llm_narrative(artifact: "Artifact") -> dict[str, Any]:
    """Best-effort mirror of ``structured.thesis`` for legacy artifacts."""
    thesis = artifact.outputs.structured.get("thesis")
    if not isinstance(thesis, dict):
        return {}
    keys = (
        "tagline",
        "key_takeaways",
        "company_overview",
        "valuation_overview",
        "news_summary",
        "competitor_analysis",
        "recommendation",
        "catalysts",
        "risks",
    )
    return {key: thesis[key] for key in keys if key in thesis}


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


def extract_primary_provider(artifact: "Artifact") -> str | None:
    """The data provider that fed this artifact (``inputs.data_source``).

    Mirrored into the ``primary_provider`` summary column (门四溯源半) so the
    Library list shows at a glance which source produced each snapshot and the
    diff view can flag a provider switch without payload reads.

    Returns None when the builder recorded the "unknown" placeholder (no
    structured step matched) or an empty string — a fake provider chip is
    worse than no chip.
    """
    raw = artifact.inputs.data_source if artifact.inputs else None
    if not isinstance(raw, str):
        return None
    stripped = raw.strip()
    if not stripped or stripped.lower() == "unknown":
        return None
    return stripped
