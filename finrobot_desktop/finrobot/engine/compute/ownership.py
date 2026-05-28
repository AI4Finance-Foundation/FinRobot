"""Ownership & Governance analysis from SEC raw provider payloads.

The functions in this module are deterministic adapters: they convert
EdgarToolsProvider JSON payloads into the persisted SEC Pydantic models.
No LLM touches these numbers.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

from finrobot.engine.models.sec import (
    FilingProvenance,
    InsiderTransaction,
    InstitutionalHolding,
    OwnershipGovernanceAnalysis,
    ProxyCompensation,
)


def _parse_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str) and value:
        return date.fromisoformat(value[:10])
    raise ValueError(f"missing SEC date: {value!r}")


def _maybe_parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    return _parse_date(value)


def _provenance(
    *,
    form: str,
    filing_date: Any,
    accession_no: Any,
    period_of_report: Any = None,
    source_url: Any = None,
) -> FilingProvenance:
    return FilingProvenance(
        form=form,
        filing_date=_parse_date(filing_date),
        accession_no=str(accession_no or ""),
        period_of_report=_maybe_parse_date(period_of_report),
        source_url=str(source_url) if source_url else None,
    )


def _money_from_text(text: str) -> float | None:
    """Extract a dollar amount from proxy prose/table text."""
    if not text:
        return None
    match = re.search(r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(million|m|billion|bn)?", text, re.I)
    if not match:
        return None
    value = float(match.group(1).replace(",", ""))
    scale = (match.group(2) or "").lower()
    if scale in {"million", "m"}:
        value *= 1_000_000
    elif scale in {"billion", "bn"}:
        value *= 1_000_000_000
    return value


def _ceo_comp_from_text(text: str) -> float | None:
    """Extract CEO total compensation anchored near a CEO pay keyword.

    Must find a dollar amount within 200 characters after one of:
      - "CEO total compensation"
      - "CEO compensation"
      - "CEO total pay"
      - "CEO pay"
    Avoids grabbing the first $ in the document (which is often market cap or revenue).
    """
    anchor_pattern = re.compile(
        r"CEO\s+(?:total\s+)?(?:compensation|pay)",
        re.I,
    )
    match = anchor_pattern.search(text)
    if not match:
        return None
    window = text[match.start() : match.start() + 200]
    return _money_from_text(window)


# Words that look like a proper-noun name regex match but are actually titles/roles.
_CEO_NAME_BLACKLIST: frozenset[str] = frozenset(
    {
        "Chief Executive Officer",
        "Chief",
        "Executive",
        "Officer",
        "Chairman",
        "President",
        "Board",
        "Director",
        "CEO",
        "CFO",
        "COO",
        "CTO",
        "Vice",
        "Senior",
        "Named",
        "Named Executive",
    }
)

# Plausibility gate: CEO comp must be between $1M and $500M.
_CEO_COMP_MIN: float = 1_000_000.0
_CEO_COMP_MAX: float = 500_000_000.0


def _extract_ceo_pay_ratio(text: str) -> int | None:
    match = re.search(
        r"CEO\s+pay\s+ratio[^0-9]{0,80}([0-9][0-9,]*)\s*(?:to|:)\s*1",
        text,
        re.I,
    )
    if match:
        return int(match.group(1).replace(",", ""))
    match = re.search(r"([0-9][0-9,]*)\s*(?:to|:)\s*1[^.\n]{0,80}CEO\s+pay\s+ratio", text, re.I)
    if match:
        return int(match.group(1).replace(",", ""))
    return None


def _is_blacklisted_name(candidate: str) -> bool:
    """Return True when every token in candidate is a blacklisted title/role word."""
    tokens = candidate.split()
    return all(
        t.title() in _CEO_NAME_BLACKLIST
        or t.upper() in _CEO_NAME_BLACKLIST
        or t.lower() in {w.lower() for w in _CEO_NAME_BLACKLIST}
        for t in tokens
    )


def _extract_ceo_name(text: str) -> str | None:
    """Extract CEO name from proxy text, rejecting title/role tokens.

    Strategy (in priority order):
    1. Look for "Firstname Lastname, ... Chief Executive Officer/CEO" pattern —
       name appears before the title on the same line (most SCT table formats).
    2. Look for "Mr./Ms./Dr. Firstname Lastname" near a CEO anchor.
    3. Look for a capitalized proper-noun sequence in the post-CEO window that
       is not entirely composed of blacklisted title words.

    The window search deliberately excludes the article "The" (a common false
    positive when "The CEO" appears as a subject noun phrase).
    """
    # Strategy 0: name on the line immediately before "CEO ..." line (table format).
    # e.g. "Sundar Pichai\nCEO Total Compensation $74M"
    prev_line_pattern = re.compile(
        r"([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3})"
        r"\s*\n\s*CEO\b",
    )
    for m in prev_line_pattern.finditer(text):
        candidate = m.group(1).strip()
        if not _is_blacklisted_name(candidate):
            return candidate

    # Strategy 1: name precedes title on the same line/sentence.
    # Pattern: "Tim Cook, ... Chief Executive Officer" or "Tim Cook (CEO)"
    # IMPORTANT: do NOT use re.I here — the name group uses [A-Z] to enforce
    # uppercase-first, and re.I would make [A-Z] match lowercase too.
    pre_title_pattern = re.compile(
        r"([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){1,3})"
        r"[^A-Z\n]{0,80}"  # gap must not contain caps (to stop at title word start)
        r"(?:Chief Executive Officer|CEO)\b",
    )
    for m in pre_title_pattern.finditer(text):
        candidate = m.group(1).strip()
        if not _is_blacklisted_name(candidate):
            return candidate

    # Strategy 2: Mr./Ms./Dr. + name near CEO anchor.
    honorific_pattern = re.compile(
        r"(?:Mr\.|Ms\.|Mrs\.|Dr\.)\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3})",
        re.I,
    )
    ceo_positions = [m.start() for m in re.finditer(r"(?:Chief Executive Officer|CEO)\b", text, re.I)]
    for m in honorific_pattern.finditer(text):
        candidate = m.group(1).strip()
        if _is_blacklisted_name(candidate):
            continue
        # Must be within 300 chars of a CEO anchor.
        if any(abs(m.start() - pos) <= 300 for pos in ceo_positions):
            return candidate

    # Strategy 3: post-anchor scan with strict blacklist filtering.
    ceo_match = re.search(r"(?:Chief Executive Officer|CEO)\b[^\n]{0,120}", text, re.I)
    if not ceo_match:
        return None
    window = ceo_match.group(0)
    for candidate_match in re.finditer(
        r"\b([A-Z][A-Za-z'-]+(?:\s+[A-Z][A-Za-z'-]+){1,3})\b",
        window,
    ):
        candidate = candidate_match.group(1).strip()
        # Skip single-char initials-only matches.
        if len(candidate.replace(" ", "")) <= 3:
            continue
        if _is_blacklisted_name(candidate):
            continue
        # Skip the article "The" as a leading word.
        if candidate.lower().startswith("the "):
            continue
        return candidate
    return None


def build_proxy_compensation(raw_proxy: dict[str, Any]) -> ProxyCompensation | None:
    """Extract a compact DEF 14A compensation summary.

    The exact DEF 14A table layout varies by issuer. We persist provenance
    even when only the filing metadata is extractable, and opportunistically
    parse common CEO pay ratio / dollar amount prose for UI cards.

    Plausibility gates applied before returning:
    - ceo_name: rejected if composed entirely of blacklisted title words.
    - ceo_total_compensation: must be in [1M, 500M]; outside range → None.
    - ceo_total_compensation: extracted only from within 200 chars of a
      "CEO total compensation/pay" keyword anchor (not first $ in document).
    - When all three main fields (name, comp, ratio) are None, appends
      "proxy_compensation" to degraded_sections is handled upstream in
      compute_ownership_governance.
    """
    if not raw_proxy or (raw_proxy.get("proxy") is None and "text" not in raw_proxy):
        return None
    if not raw_proxy.get("filing_date") or not raw_proxy.get("accession_no"):
        return None

    text = str(raw_proxy.get("text") or "")

    ceo_name = _extract_ceo_name(text)

    raw_comp = _ceo_comp_from_text(text)
    ceo_total_compensation: float | None = None
    if raw_comp is not None and _CEO_COMP_MIN <= raw_comp <= _CEO_COMP_MAX:
        ceo_total_compensation = raw_comp

    ceo_pay_ratio = _extract_ceo_pay_ratio(text)

    return ProxyCompensation(
        filing_date=_parse_date(raw_proxy["filing_date"]),
        accession_no=str(raw_proxy["accession_no"]),
        ceo_name=ceo_name,
        ceo_total_compensation=ceo_total_compensation,
        ceo_pay_ratio=ceo_pay_ratio,
        provenance=_provenance(
            form="DEF 14A",
            filing_date=raw_proxy["filing_date"],
            accession_no=raw_proxy["accession_no"],
            source_url=raw_proxy.get("source_url"),
        ),
    )


def build_insider_transactions(raw_insider: dict[str, Any]) -> list[InsiderTransaction]:
    rows: list[InsiderTransaction] = []
    for tx in raw_insider.get("transactions") or []:
        provenance = _provenance(
            form="4",
            filing_date=tx["filing_date"],
            accession_no=tx["accession_no"],
            source_url=tx.get("source_url"),
        )
        rows.append(
            InsiderTransaction(
                filing_date=provenance.filing_date,
                accession_no=provenance.accession_no,
                insider_name=str(tx.get("insider_name") or ""),
                insider_position=tx.get("insider_position"),
                transaction_type=str(tx.get("transaction_type") or ""),
                code=str(tx.get("code") or ""),
                shares=float(tx.get("shares") or 0),
                value=float(tx.get("value") or 0),
                price_per_share=(
                    float(tx["price_per_share"])
                    if tx.get("price_per_share") not in (None, "")
                    else None
                ),
                security_type=str(tx.get("security_type") or ""),
                security_title=str(tx.get("security_title") or ""),
                underlying_security=str(tx.get("underlying_security") or ""),
                exercise_date=_maybe_parse_date(tx.get("exercise_date")),
                expiration_date=_maybe_parse_date(tx.get("expiration_date")),
                footnote_ids=str(tx.get("footnote_ids") or ""),
                footnotes_text=str(tx.get("footnotes_text") or ""),
                provenance=provenance,
            )
        )
    return rows


def build_institutional_holdings(raw_holdings: dict[str, Any]) -> list[InstitutionalHolding]:
    rows: list[InstitutionalHolding] = []
    for row in raw_holdings.get("holders") or []:
        provenance = _provenance(
            form="13F-HR",
            filing_date=row["filing_date"],
            accession_no=row["accession_no"],
            period_of_report=row.get("period_end"),
            source_url=row.get("source_url"),
        )
        rows.append(
            InstitutionalHolding(
                holder_name=str(row.get("holder_name") or ""),
                holder_cik=row.get("holder_cik"),
                cusip=str(row.get("cusip") or ""),
                name_of_issuer=str(row.get("name_of_issuer") or ""),
                title_of_class=str(row.get("title_of_class") or "COM"),
                shares=int(row.get("shares") or 0),
                value_usd=float(row.get("value_usd") or 0),
                period_end=_parse_date(row.get("period_end")),
                shares_change_pct=(
                    float(row["shares_change_pct"])
                    if row.get("shares_change_pct") not in (None, "")
                    else None
                ),
                provenance=provenance,
            )
        )
    return rows


def compute_ownership_governance(
    *,
    insider_data: dict[str, Any] | None,
    institutional_data: dict[str, Any] | None,
    proxy_data: dict[str, Any] | None,
) -> OwnershipGovernanceAnalysis:
    degraded_sections: list[str] = []

    insiders = build_insider_transactions(insider_data or {})
    if not insiders:
        degraded_sections.append("insider_transactions")

    institutions = build_institutional_holdings(institutional_data or {})
    if not institutions:
        degraded_sections.append("institutional_holdings")

    proxy = build_proxy_compensation(proxy_data or {})
    if proxy is None:
        degraded_sections.append("proxy_compensation")
    elif (
        proxy.ceo_name is None
        and proxy.ceo_total_compensation is None
        and proxy.ceo_pay_ratio is None
    ):
        # ProxyCompensation object exists (filing metadata present) but all
        # substantive NEO fields parsed to None — nothing useful to display.
        # Treat as degraded so UI renders a placeholder instead of an empty card.
        degraded_sections.append("proxy_compensation")
        proxy = None

    return OwnershipGovernanceAnalysis(
        insider_transactions=insiders,
        institutional_holdings=institutions,
        proxy_compensation=proxy,
        generated_at=datetime.now(tz=timezone.utc),
        degraded_sections=degraded_sections,
    )
