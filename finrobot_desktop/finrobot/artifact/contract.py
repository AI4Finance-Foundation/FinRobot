"""Output-contract total gate — the one invariant check between a fully assembled
artifact and the store.

Every upstream gate sees a fragment: the data-health gate sees a
``ValuationSynthesis``, the numeric audit sees a ``FinancialData`` snapshot, the
narrative reconcile sees one prose field. None of them ever sees the assembled
artifact — headline, basis, narrative, currency all in one object. ``runner.py``
persists at a single boundary (builder output → ``store.save``); this contract
runs in the gap and asserts whole-artifact invariants the fragment gates are
structurally blind to:

  · C1 — the headline target/entry ratio must sit in the calibrated divergence
    band (single-method [1/2x, 2x], multi-method [1/4x, 4x]). Catches the MU
    $2172 = 2.5x-$864 accident no matter how the upstream gate mis-calibrated.
  · C2 — a ``$``-anchored amount with two decimal points ($2172.062.06) is a
    string-concatenation artifact the narrative reconcile produced *after* every
    upstream gate ran; withhold (a malformed amount cannot be safely repaired).

A violated HARD clause degrades through the EXISTING withhold machinery (null
target, REVIEW, ``valuation_withheld`` + ``[CONTRACT/*]`` warning) — never raises
(an exception would blank the whole run; an analyst would rather see the full
report and know which number is suspect). A SOFT clause only annotates.

Design contract (the gate stays dumb — see ADR): zero I/O, never imports
``compute/`` / ``data/`` / ``pipelines/``, holds no bare threshold literal (the
bands are imported calibrated constants from the leaf), and each clause is a pure
``check(artifact) -> Finding | None``. It verifies the *result*; it never re-runs
the computation.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Literal

from finrobot.artifact.summary_extractor import extract_entry_price, extract_target_price
from finrobot.engine.models.numeric_claim import Finding
from finrobot.engine.models.valuation_thresholds import (
    MARKET_DIVERGENCE_RATIO_K,
    SINGLE_METHOD_DIVERGENCE_RATIO_K,
)

if TYPE_CHECKING:
    from finrobot.artifact.models import Artifact

ClauseSeverity = Literal["H", "S"]

# Q2 (locked): when a clause withholds, the conclusion mirror fields are
# neutralised but the analysis body is preserved verbatim, with a provenance
# stamp telling the reader the narrative predates the withhold. EN placeholder
# (single-locale ship); revisit copy when the cover badge wording is finalised.
_WITHHELD_NARRATIVE_STAMP = (
    "Conclusion suspended by the output contract; the analysis below was written "
    "before the withhold."
)


@dataclass(frozen=True)
class ContractClause:
    """One whole-artifact invariant. ``severity`` H → violation withholds the
    headline + flags REVIEW; S → violation only appends a note. ``check`` is a
    pure function returning the violation as a :class:`Finding`, or None when the
    invariant holds (or does not apply to this artifact's shape)."""

    id: str
    severity: ClauseSeverity
    check: Callable[["Artifact"], Finding | None]


# ── C1: headline upside band ─────────────────────────────────────────────────


def _clause_c1_upside_band(artifact: "Artifact") -> Finding | None:
    """target/entry must sit in the calibrated divergence band. Band selection is
    type-agnostic: a corroborated estimate (``valuation_synthesis.weighted_price``
    present = ≥2 methods agreed) gets the wider multi-method band; a lone method
    (no synthesis block, or weighted_price None) gets the tighter single-method
    band — its only cross-check is the market price itself."""
    target = extract_target_price(artifact)
    entry = extract_entry_price(artifact)
    if target is None or entry is None or entry <= 0:
        return None  # no per-share headline to check (lbo / comps / ic_memo)

    ratio = target / entry
    synthesis = artifact.outputs.structured.get("valuation_synthesis")
    corroborated = isinstance(synthesis, dict) and synthesis.get("weighted_price") is not None
    k = MARKET_DIVERGENCE_RATIO_K if corroborated else SINGLE_METHOD_DIVERGENCE_RATIO_K
    lo, hi = 1.0 / k, k
    if lo <= ratio <= hi:
        return None

    band = "multi-method" if corroborated else "single-method"
    return Finding(
        field_key="thesis.price_target",
        check="contract_c1_upside_band",
        severity="blocked_field",
        evidence=(
            f"headline target {target:.2f} is {ratio:.2g}x the entry price {entry:.2f}, "
            f"outside the {band} corroboration band [{lo:.2g}x, {hi:.2g}x]"
        ),
    )


# ── C2: double-decimal malformation ──────────────────────────────────────────

# A ``$``-anchored amount carrying TWO decimal points is a concatenation artifact
# ($2172.062.06, $1,234.562.06). The ``$`` anchor + double-point is what keeps it
# off the high-frequency LEGAL financial decimals a naive ``\d\.\d{2}\d`` mauled:
# beta 1.085, FX 7.234, R² 0.987, a fractional strike $1.875, a percentage 0.025.
# Trailing ``\d+`` (vs the spec's single ``\d``) captures the WHOLE malformed run
# so the evidence names the real token ($2172.062.06), not a truncated prefix —
# detection semantics are unchanged (a match still needs $ + two decimal points).
_DOUBLE_DECIMAL_RE = re.compile(r"\$\d[\d,]*\.\d{2}\d*\.\d+")


def _clause_c2_double_decimal(artifact: "Artifact") -> Finding | None:
    for text in _iter_narrative_strings(artifact):
        match = _DOUBLE_DECIMAL_RE.search(text)
        if match is not None:
            return Finding(
                field_key="narrative",
                check="contract_c2_double_decimal",
                severity="blocked_field",
                evidence=f"malformed amount '{match.group(0)}' (two decimal points) in narrative",
            )
    return None


def _iter_narrative_strings(artifact: "Artifact") -> Iterator[str]:
    """Every analyst-facing string: structured (incl. the thesis prose), the
    llm_narrative mirror (a dict — ⟦复核⟧ must be traversed, not str()'d), and
    summary_text. NOT warnings — those carry the contract's own [CONTRACT/*]
    evidence, scanning them would re-trip C2 on its own output."""
    outputs = artifact.outputs
    yield from _iter_strings(outputs.structured)
    yield from _iter_strings(outputs.llm_narrative)
    if outputs.summary_text:
        yield outputs.summary_text


def _iter_strings(obj: Any) -> Iterator[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _iter_strings(value)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            yield from _iter_strings(value)


# ── Registry + enforcement ───────────────────────────────────────────────────

CONTRACT_CLAUSES: list[ContractClause] = [
    ContractClause(id="C1", severity="H", check=_clause_c1_upside_band),
    ContractClause(id="C2", severity="H", check=_clause_c2_double_decimal),
]


def enforce_artifact_contract(artifact: "Artifact") -> "Artifact":
    """Run every clause at the persist boundary. Hard violations degrade the
    artifact through the existing withhold machinery; soft violations annotate.
    Returns the (possibly degraded) artifact — never raises, never blanks a run.
    A compliant artifact is returned untouched."""
    hard: list[tuple[ContractClause, Finding]] = []
    for clause in CONTRACT_CLAUSES:
        finding = clause.check(artifact)
        if finding is None:
            continue
        if clause.severity == "H":
            hard.append((clause, finding))
        else:
            _append_warning(artifact, f"[CONTRACT/{clause.id}/note] {finding.evidence}")

    if hard:
        _withhold(artifact, hard)
    return artifact


def _withhold(artifact: "Artifact", violations: list[tuple[ContractClause, Finding]]) -> None:
    """Degrade exactly as the numeric-audit gate does (builders.py): null the
    headline so it cannot resurrect, force REVIEW, set valuation_withheld, and
    record machine evidence as [CONTRACT/*] warnings. Type-agnostic: nulls both
    the authoritative thesis target and the flat per-share slots a plain dcf/ddm
    dumps, so extract_target_price is guaranteed None afterwards (the C7 invariant)."""
    structured = artifact.outputs.structured
    ids = [clause.id for clause, _ in violations]

    thesis = structured.get("thesis")
    if isinstance(thesis, dict):
        thesis["price_target"] = None
        thesis["recommendation"] = "REVIEW"
    # Flat headline slots (plain dcf `implied_price`, plain ddm `equity_value_per_share`)
    # — absent for equity_research, so this is a no-op there.
    for slot in ("implied_price", "equity_value_per_share", "target_price"):
        if structured.get(slot) is not None:
            structured[slot] = None

    structured["valuation_withheld"] = True
    structured["withheld_reason"] = "contract_" + "+".join(ids)

    # Q2 (locked): neutralise the conclusion mirror fields, preserve the body.
    narrative = artifact.outputs.llm_narrative
    if isinstance(narrative, dict):
        if "recommendation" in narrative:
            narrative["recommendation"] = "REVIEW"
        if "tagline" in narrative:
            narrative["tagline"] = None

    numeric_audit = structured.get("numeric_audit")
    if isinstance(numeric_audit, dict):
        numeric_audit["artifact_status"] = "review_only"

    for clause, finding in violations:
        _append_warning(artifact, f"[CONTRACT/{clause.id}] {finding.evidence}")
    _append_warning(artifact, f"[CONTRACT/withheld] {_WITHHELD_NARRATIVE_STAMP}")


def _append_warning(artifact: "Artifact", warning: str) -> None:
    """Idempotent append — re-running the contract must not double-stamp."""
    if warning not in artifact.outputs.warnings:
        artifact.outputs.warnings.append(warning)
