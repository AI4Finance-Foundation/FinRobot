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
    ScheduleThirteenAlert,
)


def _parse_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str) and value:
        return date.fromisoformat(value[:10])
    raise ValueError(f"missing SEC date: {value!r}")


def _opt_float(value: Any) -> float | None:
    """Parse a numeric to float; None/empty/unparseable → None (missing data).

    Preserves an explicit 0.0 (a forfeit's $0 value is real) — only genuinely
    absent values collapse to None, so a parse gap never reads as a real 0.
    """
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _maybe_parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        return _parse_date(value)
    except ValueError:
        # Defense-in-depth: SEC Form 4 footnote stand-ins like "[F4]" or
        # filer free-text in date fields must collapse to None at the last
        # parse layer too — providers normalise upstream, but cached
        # payloads from earlier code versions can still carry garbage.
        return None


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


# SEC Form 4 General Instructions, Section 8 — Table II/IV transaction codes.
# Canonical code → human transaction_type mapping. The edgar-python library
# emits the wrong label for code ``M`` on the derivative side of an option
# exercise (it tags the disposed-of option as "derivative_sale", which to a
# reader reads as an open-market sale of derivatives — but code M IS the
# exercise itself). Mapping locally guarantees both sides of the exercise
# carry the same "exercise" label, with ``security_type`` left to distinguish
# which side of the transaction each row reflects.
_FORM4_CODE_TO_TYPE: dict[str, str] = {
    "P": "purchase",
    "S": "sale",
    "V": "voluntary_report",
    "A": "grant",
    "D": "disposition_to_issuer",
    "F": "tax_withholding",
    "I": "discretionary",
    "M": "exercise",
    "C": "conversion",
    "E": "expiration_short",
    "H": "expiration_long",
    "O": "exercise_otm",
    "X": "exercise_itm_atm",
    "G": "gift",
    "L": "small_acquisition",
    "W": "estate",
    "Z": "voting_trust",
    "J": "other",
    "K": "equity_swap",
    "U": "tender",
}


def _canonical_transaction_type(code: Any, fallback: Any) -> str:
    """Resolve Form 4 transaction code → canonical type, ignoring upstream label.

    edgar-python sometimes returns derivative-side variants of the same code
    with different labels (``M`` → ``derivative_sale`` on the option leg,
    ``exercise`` on the stock leg). Canonicalize on ``code`` so the UI never
    has to second-guess the SEC's two-row exercise representation. Unknown
    codes fall through to the upstream label, then to an empty string —
    never raise, since Form 4 footnote-only filings sometimes ship without
    a code at all.
    """
    code_str = str(code or "").strip().upper()
    if code_str in _FORM4_CODE_TO_TYPE:
        return _FORM4_CODE_TO_TYPE[code_str]
    return str(fallback or "")


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


def _normalise_proxy_text(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def _summary_table_ceo_comp_from_text(text: str) -> tuple[str | None, float | None]:
    """Extract actual CEO total compensation from the Summary Compensation Table.

    DEF 14A prose often contains "target CEO compensation" before the required
    SEC Summary Compensation Table. Target pay is an intended package, while
    the UI field is actual SCT total compensation, so this table is the first
    source to trust.
    """
    if not text:
        return None, None

    compact = _normalise_proxy_text(text)

    # Layout A — title BETWEEN name and year (e.g. some issuers):
    #   "Jane Doe, Chief Executive Officer 2026 1,000,000 ... 12,000,000"
    # ``role`` forbids digits so it cannot span a data row: without this, a
    # "name year ...figures... total <title>" layout (NVDA) lets the role
    # group swallow the first year's figures and the parser reads the NEXT
    # year's total. Real job titles never contain digits.
    row_pattern_role_first = re.compile(
        r"(?P<name>[A-Z][A-Za-z.'’-]+(?:\s+[A-Z][A-Za-z.'’-]+){1,3})\s+"
        r"(?P<role>[^\d\n]{0,140}?(?:Chief Executive Officer|CEO)[^\d\n]{0,80}?)\s+"
        r"(?P<year>20\d{2})\s+"
        r"(?P<salary>[0-9][0-9,]*)\s+"
        r"(?P<stock>[0-9][0-9,]*)\s+"
        r"(?P<incentive>[0-9][0-9,]*)\s+"
        r"(?P<other>[0-9][0-9,]*)(?:\s*\([^)]*\))*\s+"
        r"(?P<total>[0-9][0-9,]*)",
        re.I,
    )

    # Layout B — name + year + figures on one line, title on the NEXT line
    # (NVDA FY2026):
    #   "Jen-Hsun Huang 2026 1,497,627 24,800,511 6,000,000 4,045,691 (4)
    #    36,343,830 President and CEO 2025 ..."
    # The total is the last comma-grouped number before the role text. We
    # require the role to appear within ~160 chars AFTER the total so a
    # non-CEO NEO row can't match.
    row_pattern_role_after = re.compile(
        r"(?P<name>[A-Z][A-Za-z.'’-]+(?:\s+[A-Z][A-Za-z.'’-]+){1,3})\s+"
        r"(?P<year>20\d{2})\s+"
        r"(?P<figures>(?:[0-9][0-9,]*(?:\s*\([^)]*\))*\s+){2,7})"
        r"(?P<total>[0-9]{1,3}(?:,[0-9]{3})+)"
        r"(?P<after>.{0,160}?(?:Chief Executive Officer|President and CEO|\bCEO\b))",
        re.I,
    )

    for heading in re.finditer(
        r"(?:Summary Compensation Table|Name and Principal Position)", compact, re.I
    ):
        window = compact[heading.start() : heading.start() + 12_000]
        header = re.search(r"Name and Principal Position.*?(?:Total|Fiscal)", window, re.I)
        search_window = window[header.end() :] if header else window
        for pattern in (row_pattern_role_first, row_pattern_role_after):
            for match in pattern.finditer(search_window):
                name = _strip_leading_sct_header_words(match.group("name").strip())
                total = float(match.group("total").replace(",", ""))
                if len(name.split()) < 2 or _is_blacklisted_name(name):
                    continue
                if _CEO_COMP_MIN <= total <= _CEO_COMP_MAX:
                    return name, total
    return None, None


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
    for match in anchor_pattern.finditer(text):
        context = text[max(0, match.start() - 80) : match.start() + 200]
        if re.search(r"\btarget\b", context, re.I):
            continue
        return _money_from_text(context)
    return None


def _ceo_comp_and_ratio_from_disclosure(text: str) -> tuple[float | None, int | None]:
    """Parse the SEC-mandated CEO pay-ratio disclosure (Item 402(u)).

    Every proxy with a pay ratio states, in plain prose, the CEO's *actual*
    SCT total compensation and the ratio, e.g. NVDA FY2026:

      "Our median employee's total compensation for Fiscal 2026 was $282,050.
       Our CEO's Fiscal 2026 total compensation was $36,343,830. Therefore,
       our Fiscal 2026 CEO to median employee pay ratio was 129:1."

    This is the single most reliable source: the dollar figure is the SCT
    total by definition, and the ratio is spelled out. Far more robust than
    parsing the table grid, whose column layout varies by issuer.

    Returns ``(ceo_total_compensation | None, ceo_pay_ratio | None)``.
    """
    compact = _normalise_proxy_text(text)

    comp: float | None = None
    # "CEO['s] [annual] [fiscal YYYY] total compensation [was/of/is/:] $X"
    m = re.search(
        r"(?:CEO|chief executive officer)['’s]*\s+"
        r"(?:annual\s+)?(?:fiscal\s+\d{4}\s+)?total\s+compensation\s+"
        r"(?:was|of|is|equal to|:)?\s*\$?\s*([0-9][0-9,]+)",
        compact,
        re.I,
    )
    if m is None:
        # Reverse phrasing: "annual total compensation of our CEO ... $X"
        m = re.search(
            r"total\s+compensation\s+of\s+our\s+(?:CEO|chief executive officer)"
            r"[^$\n]{0,80}\$\s*([0-9][0-9,]+)",
            compact,
            re.I,
        )
    if m is not None:
        val = float(m.group(1).replace(",", ""))
        if _CEO_COMP_MIN <= val <= _CEO_COMP_MAX:
            comp = val

    ratio: int | None = None
    # Issuers phrase the Item 402(u) ratio several ways:
    #   "...pay ratio was 129:1"            (NVDA)
    #   "...pay ratio of 533 to 1"          (AAPL)
    #   "...resulting in a ratio of 363 to 1" (JPM — no literal "pay ratio")
    for ratio_pat in (
        r"pay\s+ratio\s+(?:of\s+)?(?:was|is|equal to|:)?\s*(?:approximately\s+)?"
        r"([0-9][0-9,]*)\s*(?:to|:)\s*1\b",
        r"ratio\s+of\s+(?:approximately\s+)?([0-9][0-9,]*)\s*(?:to|:)\s*1\b",
    ):
        rm = re.search(ratio_pat, compact, re.I)
        if rm is not None:
            ratio = int(rm.group(1).replace(",", ""))
            break

    return comp, ratio


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

# Function words that never appear inside a real personal name. Used as a
# secondary reject in _is_blacklisted_name to catch garbage candidates
# that regex over-capture stitches together across paragraph breaks —
# e.g. TSLA DEF 14A heading "...Better Future for Us All\n\nTesla does
# not currently have a long-term CEO performance award..." was matched
# as candidate name "Us All Tesla" because the title-only blacklist let
# "Tesla" through. Compared case-insensitively against each token.
_CEO_NAME_STOPWORDS: frozenset[str] = frozenset(
    {
        # pronouns
        "i",
        "we",
        "us",
        "our",
        "ours",
        "you",
        "your",
        "he",
        "his",
        "she",
        "her",
        "they",
        "their",
        "it",
        "its",
        # articles / determiners / quantifiers
        "the",
        "a",
        "an",
        "this",
        "that",
        "these",
        "those",
        "all",
        "some",
        "any",
        "each",
        "every",
        "other",
        "another",
        "such",
        # conjunctions
        "and",
        "or",
        "but",
        "so",
        "yet",
        "nor",
        "for",
        "as",
        # common prepositions
        "of",
        "in",
        "on",
        "at",
        "to",
        "by",
        "with",
        "from",
        "about",
        "into",
        "onto",
        "upon",
        "over",
        "under",
        "between",
        "through",
        # auxiliaries
        "is",
        "are",
        "was",
        "were",
        "has",
        "have",
        "had",
        "do",
        "does",
        "did",
        "be",
        "been",
        "being",
        "will",
        "would",
        "should",
        "could",
        "can",
        "may",
        "might",
        "must",
    }
)

# Plausibility gate: CEO comp must be between $1M and $500M.
_CEO_COMP_MIN: float = 1_000_000.0
_CEO_COMP_MAX: float = 500_000_000.0

# Summary-Compensation-Table column-header / accounting words. They are
# capitalized and sit immediately before the first data row, so a name regex
# anchored on "<tokens> <year>" can glue them onto the front of the real name
# (e.g. "...Non-Equity Incentive Total Jen-Hsun Huang 2026 ..." → captured name
# "Incentive Total Jen-Hsun Huang"). We strip them from the front of the match.
_SCT_HEADER_WORDS: frozenset[str] = frozenset(
    {
        "name",
        "principal",
        "position",
        "fiscal",
        "year",
        "salary",
        "bonus",
        "stock",
        "awards",
        "award",
        "option",
        "options",
        "incentive",
        "equity",
        "non-equity",
        "nonequity",
        "pension",
        "deferred",
        "nonqualified",
        "non-qualified",
        "compensation",
        "change",
        "value",
        "earnings",
        "total",
        "all",
        "other",
    }
)


def _strip_leading_sct_header_words(name: str) -> str:
    """Drop leading SCT column-header words a name-regex over-captured."""
    tokens = name.split()
    while tokens and tokens[0].lower().strip(",") in _SCT_HEADER_WORDS:
        tokens.pop(0)
    return " ".join(tokens)


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
    match = re.search(
        r"annual\s+total\s+compensation\s+of\s+our\s+CEO"
        r".{0,500}?ratio\s+of\s+these\s+amounts\s+is\s+"
        r"([0-9][0-9,]*)\s*(?:to|:)\s*1",
        _normalise_proxy_text(text),
        re.I,
    )
    if match:
        return int(match.group(1).replace(",", ""))
    return None


def _is_blacklisted_name(candidate: str) -> bool:
    """Return True when the candidate is not a plausible personal name.

    Two reject paths:
      (a) every token is a title/role word ("Chief Executive Officer") —
          the regex matched a job description rather than a name; or
      (b) any token is an English function word ("Us", "All", "The") —
          a regex with `\\s+` between tokens stitched a sentence fragment
          across a paragraph break into a fake multi-token name. Real
          personal names never contain pronouns/articles/conjunctions.
    """
    tokens = candidate.split()
    if not tokens:
        return True
    if all(
        t.title() in _CEO_NAME_BLACKLIST
        or t.upper() in _CEO_NAME_BLACKLIST
        or t.lower() in {w.lower() for w in _CEO_NAME_BLACKLIST}
        for t in tokens
    ):
        return True
    if any(t.lower() in _CEO_NAME_STOPWORDS for t in tokens):
        return True
    return False


def _extract_ceo_name(text: str) -> str | None:
    """Extract CEO name from proxy text, rejecting title/role tokens.

    Strategy (in priority order — highest-confidence signal first):
    0. "Firstname Lastname\\nCEO ..." (table layout — name on line above title).
    1. "Mr./Ms./Dr. Firstname Lastname" within 300 chars of a CEO anchor —
       the honorific is a strong signal that what follows is a personal name.
    2. "Firstname Lastname, Chief Executive Officer" with explicit comma /
       dash / colon connector — only the canonical full title, not bare
       "CEO" which appears inside compound nouns ("2025 CEO Performance
       Award", "CEO Pay Ratio").
    3. Post-CEO-anchor scan with strict blacklist filtering.

    The window search deliberately excludes the article "The" (a common false
    positive when "The CEO" appears as a subject noun phrase).
    """
    # Strategy 0: name on the line immediately before "CEO ..." line (table format).
    # e.g. "Sundar Pichai\nCEO Total Compensation $74M"
    # Inter-token connector is `[ \t\xa0]+` (not `\s+`) so a multi-token
    # name cannot span paragraph breaks — a real personal name fits on
    # one line. TSLA bug 2026-05-28: `\s+` stitched "Us All\n\nTesla"
    # (heading + paragraph start) into a fake 3-token name candidate.
    # Quantifier `{1,3}` (not `{0,3}`) requires at least 2 name tokens —
    # CEO entries in SCT tables are always "Firstname Lastname", never a
    # bare single word, and the single-word form let section headings
    # ("Compensation Discussion and Analysis\n\nCEO …") leak through as
    # a fake one-token name "Analysis" (NVDA proxy 2026-05-28).
    prev_line_pattern = re.compile(
        r"([A-Z][A-Za-z.'-]+(?:[ \t\xa0]+[A-Z][A-Za-z.'-]+){1,3})"
        r"\s*\n\s*CEO\b",
    )
    for m in prev_line_pattern.finditer(text):
        candidate = m.group(1).strip()
        if not _is_blacklisted_name(candidate):
            return candidate

    # Strategy 1 (was 2): Mr./Ms./Dr. + name near CEO anchor.
    # The honorific is a strong, low-false-positive signal — promoted ahead
    # of the punctuation heuristic so a "Mr. Musk ... CEO Interim Award"
    # mention wins before a section-heading false positive can fire.
    # NO re.I — the name group must enforce real uppercase-first tokens;
    # `re.I` made [A-Z] case-insensitive, gluing "Mr. Musk as Chief
    # Executive" into a 4-token candidate that the stopword filter then
    # rejected. SEC filings capitalize honorifics by convention.
    honorific_pattern = re.compile(
        r"(?:Mr\.|Ms\.|Mrs\.|Dr\.)[ \t\xa0]+"
        r"([A-Z][A-Za-z.'-]+(?:[ \t\xa0]+[A-Z][A-Za-z.'-]+){0,3})",
    )
    ceo_positions = [
        m.start() for m in re.finditer(r"(?:Chief Executive Officer|CEO)\b", text, re.I)
    ]
    for m in honorific_pattern.finditer(text):
        candidate = m.group(1).strip()
        if _is_blacklisted_name(candidate):
            continue
        # Must be within 300 chars of a CEO anchor.
        if any(abs(m.start() - pos) <= 300 for pos in ceo_positions):
            return candidate

    # Strategy 2 (was 1): "Name, Chief Executive Officer" with explicit
    # comma / dash / colon connector. Two important narrowings vs. the
    # original Strategy 1 that produced TSLA false positives:
    #   - require the FULL title "Chief Executive Officer" (no bare "CEO"),
    #     because bare CEO appears inside compound nouns like
    #     "CEO Performance Award" which the regex couldn't distinguish
    #     from a real title mention;
    #   - drop `(` from the connector class — parenthetical asides
    #     ("Equity Incentive Plan (as defined below) and the 2025 CEO …")
    #     produced too many false positives despite passing the stopword
    #     filter.
    # IMPORTANT: do NOT use re.I here — the name group uses [A-Z] to enforce
    # uppercase-first, and re.I would make [A-Z] match lowercase too.
    pre_title_pattern = re.compile(
        r"([A-Z][A-Za-z.'-]+(?:[ \t\xa0]+[A-Z][A-Za-z.'-]+){1,3})"
        r"[ \t\xa0]*[,\-:–—]"
        r"[^A-Z\n]{0,80}"
        r"Chief Executive Officer\b",
    )
    for m in pre_title_pattern.finditer(text):
        candidate = m.group(1).strip()
        if not _is_blacklisted_name(candidate):
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

    summary_name, summary_comp = _summary_table_ceo_comp_from_text(text)
    disclosure_comp, disclosure_ratio = _ceo_comp_and_ratio_from_disclosure(text)
    ceo_name = summary_name or _extract_ceo_name(text)

    # Comp source priority: SCT table grid → pay-ratio disclosure prose →
    # generic "CEO compensation $X" anchor. All three are SCT-total figures;
    # the disclosure is the most reliable cross-issuer fallback.
    raw_comp = (
        summary_comp
        if summary_comp is not None
        else disclosure_comp
        if disclosure_comp is not None
        else _ceo_comp_from_text(text)
    )
    ceo_total_compensation: float | None = None
    if raw_comp is not None and _CEO_COMP_MIN <= raw_comp <= _CEO_COMP_MAX:
        ceo_total_compensation = raw_comp

    # Ratio: the dedicated extractor handles "CEO pay ratio" phrasings; the
    # disclosure parser catches "CEO to median employee pay ratio was N:1".
    ceo_pay_ratio = _extract_ceo_pay_ratio(text)
    if ceo_pay_ratio is None:
        ceo_pay_ratio = disclosure_ratio

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
                transaction_type=_canonical_transaction_type(
                    tx.get("code"), tx.get("transaction_type")
                ),
                code=str(tx.get("code") or ""),
                shares=_opt_float(tx.get("shares")),
                value=_opt_float(tx.get("value")),
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


def build_schedule13_alerts(raw_schedule13: dict[str, Any]) -> list[ScheduleThirteenAlert]:
    """Build 5%+ beneficial-ownership alerts from SC 13D/13G fetch payload.

    Each row already carries a parsed share count (the provider skips filings
    where it couldn't read one), so ``shares`` here is always a real figure.
    """
    rows: list[ScheduleThirteenAlert] = []
    for a in raw_schedule13.get("alerts") or []:
        rows.append(
            ScheduleThirteenAlert(
                filer_name=str(a.get("filer_name") or ""),
                filer_cik=a.get("filer_cik"),
                filing_date=_parse_date(a["filing_date"]),
                accession_no=str(a.get("accession_no") or ""),
                schedule_type="13D" if str(a.get("schedule_type")).upper() == "13D" else "13G",
                shares=int(a.get("shares") or 0),
                pct_of_class=(
                    float(a["pct_of_class"]) if a.get("pct_of_class") not in (None, "") else None
                ),
                transaction_summary=str(a.get("transaction_summary") or ""),
            )
        )
    return rows


def compute_ownership_governance(
    *,
    insider_data: dict[str, Any] | None,
    institutional_data: dict[str, Any] | None,
    proxy_data: dict[str, Any] | None,
    schedule13_data: dict[str, Any] | None = None,
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

    # schedule13_data None = "not requested" (legacy callers) → leave empty,
    # not degraded. Only mark degraded when a fetch was attempted and failed;
    # a successful fetch with zero filings is genuinely "no 5%+ events" and
    # the UI shows that plainly rather than a degraded placeholder.
    schedule13_alerts: list[ScheduleThirteenAlert] = []
    if schedule13_data is not None:
        schedule13_alerts = build_schedule13_alerts(schedule13_data)
        if not schedule13_alerts and schedule13_data.get("available") is False:
            degraded_sections.append("schedule13_alerts")

    return OwnershipGovernanceAnalysis(
        insider_transactions=insiders,
        institutional_holdings=institutions,
        proxy_compensation=proxy,
        schedule13_alerts=schedule13_alerts,
        generated_at=datetime.now(tz=timezone.utc),
        degraded_sections=degraded_sections,
    )
