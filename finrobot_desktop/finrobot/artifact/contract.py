"""Output-contract total gate — the one invariant check between a fully assembled
artifact and the store.

Every upstream gate sees a fragment: the data-health gate sees a
``ValuationSynthesis``, the numeric audit sees a ``FinancialData`` snapshot, the
narrative reconcile sees one prose field. None of them ever sees the assembled
artifact — headline, basis, narrative, currency all in one object. ``runner.py``
persists at a single boundary (builder output → ``store.save``); this contract
runs in the gap and asserts whole-artifact invariants the fragment gates are
structurally blind to:

  · C1 — the headline target/MARKET ratio must sit in the calibrated divergence
    band (single-method [1/2x, 2x], multi-method [1/4x, 4x]). Catches the MU
    $2172 = 2.5x-$864 accident no matter how the upstream gate mis-calibrated.
  · C1b — the surviving methods must corroborate EACH OTHER (max/min mid ≤ the
    leaf corroboration span). The backstop C1 is blind to: a target in-band vs the
    market while the methods are 7x apart (MU 0.69x-of-market case).
  · C2 — a ``$``-anchored amount with two decimal points ($2172.062.06) is a
    string-concatenation artifact the narrative reconcile produced *after* every
    upstream gate ran; withhold (a malformed amount cannot be safely repaired).

A violated HARD clause is a VALUE-withhold: it degrades through the existing
withhold machinery — null the target slot(s) + ``valuation_withheld`` +
``[CONTRACT/*]`` warning — while PRESERVING the directional verdict (corrupt /
out-of-band data withholds the price, never the judgment; there is no "REVIEW"
refuse-to-rate state any more). It never raises (an exception would blank the
whole run; an analyst would rather see the full report and know which number is
suspect). A SOFT clause only annotates.

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
from finrobot.engine.models.reconcile_tolerances import NARRATIVE_DRIFT_TOLERANCE
from finrobot.engine.models.valuation_thresholds import (
    MARKET_DIVERGENCE_RATIO_K,
    METHOD_CORROBORATION_SPAN_K,
    SINGLE_METHOD_DIVERGENCE_RATIO_K,
)

if TYPE_CHECKING:
    from finrobot.artifact.models import Artifact

ClauseSeverity = Literal["H", "S"]

# When a clause withholds, the POINT-target conclusion (the tagline) is
# neutralised but the directional verdict and the analysis body are preserved
# verbatim, with a provenance stamp telling the reader the price target was
# withheld after the narrative was written. EN placeholder (single-locale ship);
# revisit copy when the cover badge wording is finalised.
_WITHHELD_NARRATIVE_STAMP = (
    "Price target withheld by the output contract; the directional verdict still "
    "stands and the analysis below was written before the withhold."
)


@dataclass(frozen=True)
class ContractClause:
    """One whole-artifact invariant. ``severity`` H → violation withholds the
    headline TARGET + sets ``valuation_withheld`` (the directional verdict is
    preserved); S → violation only appends a note. ``check`` is a pure function
    returning the violation as a :class:`Finding`, or None when the invariant
    holds (or does not apply to this artifact's shape)."""

    id: str
    severity: ClauseSeverity  # H → violation withholds the TARGET (verdict kept); S → note only.
    check: Callable[["Artifact"], Finding | None]
    # surface=False → an INTERNAL invariant (C7's no-resurrection scrub): it still
    # withholds + scrubs, but its evidence is engineering plumbing ("nulling so it
    # cannot resurrect downstream"), so it is emitted under a non-surfacing
    # "[CONTRACT/<id>/internal]" tag the report UI skips. The analyst-facing clauses
    # (C1–C4) keep the default and drive the audit banner / cover withhold reason.
    surface: bool = True


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


# ── C1b: method-vs-method corroboration span ─────────────────────────────────


def _clause_c1b_method_span(artifact: "Artifact") -> Finding | None:
    """The method-disagreement backstop C1 is structurally blind to. C1 compares
    the headline to the MARKET; a target can sit comfortably in the market band
    (e.g. MU 0.69x of market) while the surviving methods are 7x apart from EACH
    OTHER — no honest blended point exists, so the POINT must be withheld (the
    directional verdict still ships). Reads the dumped ``valuation_synthesis.methods``
    mids and fires when max/min exceeds the shared leaf corroboration span; a
    value-withhold, never a refuse-to-rate. Every read is guarded — methods may be
    absent, a non-list, or (in unit fixtures) a list of bare names with no mid."""
    target = extract_target_price(artifact)
    if target is None or target <= 0:
        return None  # no per-share headline to withhold
    synthesis = artifact.outputs.structured.get("valuation_synthesis")
    if not isinstance(synthesis, dict):
        return None
    methods = synthesis.get("methods")
    if not isinstance(methods, list):
        return None

    mids: list[float] = []
    for method in methods:
        if not isinstance(method, dict):
            continue  # a bare method name carries no mid — nothing to span
        mid = method.get("mid")
        if isinstance(mid, bool):  # True == 1 must not masquerade as a mid
            continue
        if isinstance(mid, (int, float)) and mid > 0:
            mids.append(float(mid))
    if len(mids) <= 1:
        return None  # a single (or zero) mid can't disagree with itself

    lo, hi = min(mids), max(mids)
    span = hi / lo
    if span <= METHOD_CORROBORATION_SPAN_K:
        return None

    return Finding(
        field_key="thesis.price_target",
        check="contract_c1b_method_span",
        severity="blocked_field",
        evidence=(
            f"valuation methods span {span:.2g}x (min ${lo:.2f}, max ${hi:.2f}) — "
            f"above the {METHOD_CORROBORATION_SPAN_K:.0f}x corroboration limit; "
            f"no honest blended point exists, withholding the target {target:.2f}"
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


# ── C3: basis conclusion amount == headline ──────────────────────────────────

# Same shape as equity_research.py:710 `_DOLLAR_RE` (group 1 = numeric body, with
# optional thousands separators / decimals). Replicated here, not imported, to
# keep the contract off the pipeline layer (Q4 red line); it is a regex literal,
# not a numeric threshold.
_DOLLAR_RE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)")

# A conclusion cue immediately preceding a $-amount marks it as the BASIS's stated
# conclusion (vs a per-method mid the basis merely cites). Only a cue-anchored
# amount is compared to the headline — this is the false-positive guard: no cue,
# no comparison (we never guess which of several cited $-amounts is the verdict).
_CONCLUSION_CUE_RE = re.compile(
    r"(?:→|price\s+target|target|目标价|目标)\s*[:：]?\s*\$\s?"
    r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _clause_c3_basis_matches_headline(artifact: "Artifact") -> Finding | None:
    """A cue-anchored conclusion $-amount in the basis / valuation_overview must
    equal the headline price_target (relative tolerance). CONSERVATIVE: fires ONLY
    on a clear contradiction — a $-amount that directly follows a conclusion cue
    (→ / target / 目标). No cue-anchored amount → NO-OP (cited per-method mids are
    not guessed to be the verdict). Catches a table-vs-prose desync the upstream
    narrative reconcile could itself have produced."""
    target = extract_target_price(artifact)
    if target is None or target <= 0:
        return None
    thesis = artifact.outputs.structured.get("thesis")
    if not isinstance(thesis, dict):
        return None

    for field_name in ("price_target_basis", "valuation_overview"):
        text = thesis.get(field_name)
        if not isinstance(text, str):
            continue
        for match in _CONCLUSION_CUE_RE.finditer(text):
            try:
                amount = float(match.group(1).replace(",", ""))
            except ValueError:
                continue
            if abs(amount - target) <= abs(target) * NARRATIVE_DRIFT_TOLERANCE:
                continue
            return Finding(
                field_key=f"thesis.{field_name}",
                check="contract_c3_basis_headline_desync",
                severity="blocked_field",
                evidence=(
                    f"basis conclusion amount ${amount:.2f} (after '{match.group(0).strip()}') "
                    f"contradicts the headline price_target {target:.2f}"
                ),
            )
    return None


# ── C4: currency / unit caliber ──────────────────────────────────────────────

# audit_currency_caliber (compute/operators/audit/currency_caliber) emits this
# check id for a cross-currency ratio. The contract matches the id (or the
# "currency" family) on the already-dumped numeric_audit findings — it does not
# re-run the auditor.
_CURRENCY_CHECK = "cross_currency_ratio"


def _clause_c4_currency_caliber(artifact: "Artifact") -> Finding | None:
    """Backstop for a currency-caliber miss. Fires when a per-share headline still
    survives AND either: (a) numeric_audit carries a currency-family blocked_field
    finding (the type-agnostic missed-withhold — mixed-currency P/E on SAP / TSM /
    TM), or (b) a currency block is present but missing quote_currency /
    reporting_currency (the caliber tags never resolved). Every read is guarded —
    numeric_audit is absent on plain dcf/ddm, currency absent on non-equity."""
    target = extract_target_price(artifact)
    if target is None or target <= 0:
        return None
    structured = artifact.outputs.structured

    numeric_audit = structured.get("numeric_audit")
    if isinstance(numeric_audit, dict):
        findings = numeric_audit.get("findings")
        if isinstance(findings, list):
            for finding in findings:
                if not isinstance(finding, dict):
                    continue
                if finding.get("severity") != "blocked_field":
                    continue
                check = finding.get("check")
                if not isinstance(check, str):
                    continue
                if check == _CURRENCY_CHECK or "currency" in check:
                    return Finding(
                        field_key="thesis.price_target",
                        check="contract_c4_currency_caliber",
                        severity="blocked_field",
                        evidence=(
                            f"currency-caliber finding '{check}' on "
                            f"{finding.get('field_key', '?')} blocked but headline "
                            f"{target:.2f} survived — withholding mixed-currency target"
                        ),
                    )

    currency = structured.get("currency")
    if isinstance(currency, dict):
        for key in ("quote_currency", "reporting_currency"):
            if not currency.get(key):
                return Finding(
                    field_key="currency",
                    check="contract_c4_currency_caliber",
                    severity="blocked_field",
                    evidence=(
                        f"per-share headline {target:.2f} present but currency "
                        f"caliber is incomplete (missing {key}) — cannot label the "
                        f"amount's currency"
                    ),
                )
    return None


# ── C6: single-method no-cross-check disclosure (SOFT) ───────────────────────

# The basis must admit it lacks a second opinion. Any of these phrasings counts
# (case-insensitive); upstream resolve_canonical_thesis writes "no cross-check
# available" — C6 re-checks new paths didn't drop it.
_CROSS_CHECK_DISCLOSURES = (
    "no cross-check",
    "no cross check",
    "single-method",
    "single method",
    "无交叉",
    "单一方法",
)


def _clause_c6_single_method_disclosure(artifact: "Artifact") -> Finding | None:
    """SOFT: when only one method survived (valuation_synthesis.weighted_price is
    None) and a live headline exists, the basis MUST disclose it has no
    cross-check. Missing → a note (severity review) — the target still ships, the
    analyst is just told it has no second opinion. Never withholds."""
    target = extract_target_price(artifact)
    if target is None or target <= 0:
        return None
    structured = artifact.outputs.structured
    synthesis = structured.get("valuation_synthesis")
    if not isinstance(synthesis, dict) or synthesis.get("weighted_price") is not None:
        return None  # multi-method (corroborated) or no synthesis block → not C6's case

    thesis = structured.get("thesis")
    basis = thesis.get("price_target_basis") if isinstance(thesis, dict) else None
    haystack = basis.lower() if isinstance(basis, str) else ""
    if any(phrase in haystack for phrase in _CROSS_CHECK_DISCLOSURES):
        return None

    return Finding(
        field_key="thesis.price_target_basis",
        check="contract_c6_single_method_disclosure",
        severity="review",
        evidence=(
            f"single-method headline {target:.2f} (no weighted cross-check) but the "
            f"basis does not disclose it lacks corroboration"
        ),
    )


# ── C7: withheld must not resurrect ──────────────────────────────────────────

# Raw fallback slots a withheld headline can hide in. extract_target_price is
# thesis-authoritative and ignores them, but other consumers (coverage list,
# signal lamp) read them directly — so C7 scans the RAW slots, not the extractor.
_FALLBACK_HEADLINE_SLOTS: tuple[tuple[str, str | None], ...] = (
    ("price_target", "thesis"),
    ("target_price", "thesis"),
    ("implied_price", None),
    ("equity_value_per_share", None),
    ("target_price", None),
    ("implied_price", "financial_modeling"),
    ("implied_price", "dcf_result"),
)


def _is_withheld(artifact: "Artifact") -> bool:
    """The withhold judge for C7: True when the published thesis is withholding its
    POINT target. The verdict/target decoupling (commit ③) made the target
    withhold its own signal — ``thesis.price_target is None`` while the
    recommendation is directional (BUY/HOLD/SELL) — replacing the deleted
    recommendation=='REVIEW' sentinel. The explicit ``valuation_withheld`` flag
    (set by every withhold producer) is also honoured. A legacy stored artifact
    may still carry recommendation=='REVIEW' (read-only back-compat — never
    written any more): treat it as withheld so C7 keeps scrubbing old artifacts.
    Either signal must drive C7 so a fallback $-slot can't resurrect the target."""
    structured = artifact.outputs.structured
    if structured.get("valuation_withheld") is True:
        return True
    thesis = structured.get("thesis")
    if not isinstance(thesis, dict):
        return False
    if thesis.get("recommendation") == "REVIEW":  # legacy artifacts only
        return True
    # The published withhold signal: a directional verdict with no point target.
    recommendation = thesis.get("recommendation")
    if recommendation in ("BUY", "HOLD", "SELL") and thesis.get("price_target") is None:
        return True
    return False


def _clause_c7_no_resurrection(artifact: "Artifact") -> Finding | None:
    """When the artifact is withholding its target (directional verdict, no point),
    NO headline value may survive in ANY fallback slot. Scans the RAW slots (not
    extract_target_price, which already early-returns on a thesis) — the TSLA bug
    was financial_modeling.implied_price = 20.35 riding naked on a thesis whose own
    price_target was withheld. Any positive number found → fire (the _withhold
    scrub then nulls every slot).

    INTERNAL clause (``surface=False``): the finding is recorded as a non-surfacing
    ``[CONTRACT/C7/internal]`` warning for the audit trail but never reaches the
    analyst UI — its evidence is plumbing ("nulling so it cannot resurrect
    downstream"), not a withhold REASON. The real reason rides the analyst-facing
    clauses (C1–C4) or the method-spread warnings."""
    if not _is_withheld(artifact):
        return None
    structured = artifact.outputs.structured
    for slot, parent_key in _FALLBACK_HEADLINE_SLOTS:
        container = structured.get(parent_key) if parent_key is not None else structured
        if not isinstance(container, dict):
            continue
        value = container.get(slot)
        if isinstance(value, bool):  # avoid True == 1 surviving as a "headline"
            continue
        if isinstance(value, (int, float)) and value > 0:
            where = f"{parent_key}.{slot}" if parent_key else slot
            return Finding(
                field_key=where,
                check="contract_c7_no_resurrection",
                severity="blocked_field",
                evidence=(
                    f"withheld-target artifact still carries a headline {value} in "
                    f"{where} — nulling so it cannot resurrect downstream"
                ),
            )
    return None


# ── Registry + enforcement ───────────────────────────────────────────────────

CONTRACT_CLAUSES: list[ContractClause] = [
    ContractClause(id="C1", severity="H", check=_clause_c1_upside_band),
    ContractClause(id="C1b", severity="H", check=_clause_c1b_method_span),
    ContractClause(id="C2", severity="H", check=_clause_c2_double_decimal),
    ContractClause(id="C3", severity="H", check=_clause_c3_basis_matches_headline),
    ContractClause(id="C4", severity="H", check=_clause_c4_currency_caliber),
    ContractClause(id="C6", severity="S", check=_clause_c6_single_method_disclosure),
    ContractClause(id="C7", severity="H", check=_clause_c7_no_resurrection, surface=False),
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


def _scrub_headline_slots(structured: dict[str, Any]) -> None:
    """Null EVERY slot a headline TARGET can hide in — the authoritative thesis
    target, the flat per-share slots a plain dcf/ddm dumps, AND the nested fallback
    slots (``financial_modeling.implied_price`` / ``dcf_result.implied_price``) that
    a withheld-target thesis leaves naked in structured. The directional
    ``recommendation`` is PRESERVED — a hard clause withholds the VALUE, not the
    verdict (绝不编数字: don't ship a fabricated/out-of-band number; do still judge).
    Every hard withhold calls this, so the C7 invariant — withheld ⇒ no headline
    survives in ANY slot — holds for C1/C1b/C2/C3/C4/C7 alike (TSLA $20.35
    resurrection)."""
    thesis = structured.get("thesis")
    if isinstance(thesis, dict):
        thesis["price_target"] = None
    # Flat headline slots (plain dcf `implied_price`, plain ddm `equity_value_per_share`)
    # — absent for equity_research, so this is a no-op there.
    for slot in ("implied_price", "equity_value_per_share", "target_price"):
        if structured.get(slot) is not None:
            structured[slot] = None
    # Nested fallback slots other consumers resurrected from (extract_target_price
    # is thesis-authoritative and ignores them, but the coverage list / signal lamp
    # read them directly — null them so the withhold is terminal everywhere).
    for parent_key in ("financial_modeling", "dcf_result"):
        parent = structured.get(parent_key)
        if isinstance(parent, dict) and parent.get("implied_price") is not None:
            parent["implied_price"] = None


def _withhold(artifact: "Artifact", violations: list[tuple[ContractClause, Finding]]) -> None:
    """Degrade exactly as the numeric-audit gate does (builders.py): null the
    headline TARGET so it cannot resurrect, set valuation_withheld, and record
    machine evidence as [CONTRACT/*] warnings. The directional VERDICT is
    PRESERVED — a hard clause withholds the value, never the judgment (no "REVIEW"
    state any more). Type-agnostic: scrubs the authoritative thesis target, the flat
    per-share slots, and the nested fallback slots, so extract_target_price AND
    every direct consumer see None afterwards (the C7 invariant)."""
    structured = artifact.outputs.structured
    ids = [clause.id for clause, _ in violations]

    _scrub_headline_slots(structured)

    structured["valuation_withheld"] = True
    structured["withheld_reason"] = "contract_" + "+".join(ids)

    # The point-target conclusion is the tagline (a ≤60-char headline call that
    # often quotes the number) — neutralise it since the target is withheld. The
    # directional `recommendation` mirror is PRESERVED (verdict still ships); the
    # analysis body is untouched.
    narrative = artifact.outputs.llm_narrative
    if isinstance(narrative, dict):
        if "tagline" in narrative:
            narrative["tagline"] = None

    numeric_audit = structured.get("numeric_audit")
    if isinstance(numeric_audit, dict):
        numeric_audit["artifact_status"] = "caveated"

    for clause, finding in violations:
        # Internal-invariant clauses (C7's no-resurrection scrub) record evidence for
        # the audit trail but must NOT reach the analyst UI — the "/internal" sub-tag
        # makes the report parser skip them, exactly like "/note" and "/withheld".
        tag = clause.id if clause.surface else f"{clause.id}/internal"
        _append_warning(artifact, f"[CONTRACT/{tag}] {finding.evidence}")
    _append_warning(artifact, f"[CONTRACT/withheld] {_WITHHELD_NARRATIVE_STAMP}")


def _append_warning(artifact: "Artifact", warning: str) -> None:
    """Idempotent append — re-running the contract must not double-stamp."""
    if warning not in artifact.outputs.warnings:
        artifact.outputs.warnings.append(warning)
