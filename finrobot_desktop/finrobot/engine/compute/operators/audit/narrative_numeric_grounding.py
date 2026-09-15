"""Numeric-grounding narrative backstop (ADR-0005 operator layer, zero I/O).

BACKLOG A3 (P1-2, 叙事绑数字): a blind audit of GOOGL/MSFT/KO artifacts found
`ThesisResult.narrative` / `catalysts` / `risks` shipping templated, verdict-only
rhetoric with no supporting figure at all — GOOGL used a bloated headline P/E to
argue "attractively valued" while dropping its own core P/E; MSFT's bull case was
generic "strong moat" / "well-positioned" language with no number behind it; KO's
catalysts carried no dates or magnitudes. The thesis prompt
(`finrobot.engine.pipelines._thesis_prompt.build_thesis_prompt`) now instructs the
LLM that every paragraph/bullet must cite a whitelisted number (the
NARRATIVE ARGUMENT RULE); this module is the deterministic backstop that catches a
non-cooperative LLM that ignored it — mirroring the pattern in
``narrative_divergence.py`` (inject an authoritative instruction, then check for it
in code), just for numeric grounding instead of momentum. It NEVER touches
verdict / price_target / confidence — unquantified prose degrades the READ, not
the call (core contract②). Returns a plain warning string for
``StepOutput.warnings`` (same channel as the momentum hedge / street-range
disclosure), never a new machine code.
"""

from __future__ import annotations

import re

from finrobot.engine.models.financial import ThesisResult

# A "grounding number" is any digit that is NOT solely part of a bare calendar
# year (1900-2099) or an ordinal ("1st"/"2nd"/...). Years and ordinals show up
# constantly in otherwise-unquantified prose ("in fiscal 2025, the 1st half
# saw...") and must NOT count as numeric support, or the check would wave
# through exactly the templated rhetoric it exists to catch. Deliberately
# conservative: this does not try to parse currency / percent / multiple
# semantics or cross-check against the prompt's actual whitelist (that would
# need the whitelist threaded through, and a false positive there would just
# be noise on a non-blocking warning) — it only strips the two known
# false-positive shapes and checks whether ANY digit survives. A false
# negative (an unquantified sentence that happens to retain some other digit,
# e.g. a filing item number) is an acceptable miss for a light-touch,
# non-blocking signal; a false positive on "2025" alone counting as "grounded"
# is not — 别把年份误判为数字支撑.
_YEAR_RE = re.compile(r"(?<![\w.$])(?:19|20)\d{2}(?!\w)")
_ORDINAL_RE = re.compile(r"\b\d{1,2}(?:st|nd|rd|th)\b", re.IGNORECASE)
_DIGIT_RE = re.compile(r"\d")


def _has_grounding_number(text: str) -> bool:
    """True when ``text`` retains at least one digit after stripping bare
    calendar years and ordinal suffixes."""
    stripped = _ORDINAL_RE.sub("", text)
    stripped = _YEAR_RE.sub("", stripped)
    return bool(_DIGIT_RE.search(stripped))


def audit_narrative_numeric_grounding(thesis: ThesisResult) -> str | None:
    """Non-blocking warning when the thesis's argument fields (``narrative`` /
    ``catalysts`` / ``risks``) ship with a paragraph or bullet that carries no
    supporting number at all.

    Checks ``narrative`` as one block and each ``catalysts`` / ``risks`` entry
    individually (a 4-item bull case where one bullet is unquantified template
    filler should surface, not get averaged away). Returns None when every
    non-empty field/entry carries at least one grounding number — including
    when ``thesis.catalysts`` / ``thesis.risks`` are empty, which the schema's
    ``min_length=1`` already prevents in practice, but this function does not
    assume that invariant.
    """
    ungrounded: list[str] = []
    if thesis.narrative.strip() and not _has_grounding_number(thesis.narrative):
        ungrounded.append("narrative")
    for i, catalyst in enumerate(thesis.catalysts):
        if catalyst.strip() and not _has_grounding_number(catalyst):
            ungrounded.append(f"catalysts[{i}]")
    for i, risk in enumerate(thesis.risks):
        if risk.strip() and not _has_grounding_number(risk):
            ungrounded.append(f"risks[{i}]")
    if not ungrounded:
        return None
    return (
        f"[NARRATIVE-NUMERIC] {len(ungrounded)} narrative field(s) carry no "
        f"supporting number ({', '.join(ungrounded)}) — verdict-only rhetoric with "
        "no backing figure (e.g. 'attractively valued' with no P/E, 'a resilient "
        "moat' with no share/margin number) reads as templated, not analyst-grade."
    )
