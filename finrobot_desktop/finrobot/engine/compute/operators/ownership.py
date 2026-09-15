"""Ownership & Governance analysis from SEC raw provider payloads.

The functions in this module are deterministic adapters: they convert
EdgarToolsProvider JSON payloads into the persisted SEC Pydantic models.
No LLM touches these numbers.
"""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


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
    match = re.search(r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(million|billion|bn)?\b", text, re.I)
    if not match:
        return None
    value = float(match.group(1).replace(",", ""))
    scale = (match.group(2) or "").lower()
    if scale == "million":
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

    # NOTE: a looser "year-stacked rows" pattern (name once, one row per year,
    # no adjacent title) was tried to cover JPM/AMZN, but it grabbed a WRONG
    # number on TSLA — whose proxy embeds a PEER company's comp table (Apple /
    # Tim Cook) for comparison, and the role-less pattern can't tell it isn't
    # TSLA's own CEO. A wrong CEO-comp figure is worse than a blank, so we only
    # trust role-anchored table rows + the labeled pay-ratio prose disclosure.
    for heading in re.finditer(
        r"(?:Summary Compensation Table|Name and Principal Position)", compact, re.I
    ):
        window = compact[heading.start() : heading.start() + 12_000]
        header = re.search(r"Name and Principal Position.*?(?:Total|Fiscal)", window, re.I)
        search_window = window[header.end() :] if header else window
        for pattern in (row_pattern_role_first, row_pattern_role_after):
            for match in pattern.finditer(search_window):
                name = _strip_leading_sct_header_words(match.group("name").strip())
                name = _strip_leading_name_verbs(name)
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
    comp_match_end: int | None = None
    if m is not None:
        val = float(m.group(1).replace(",", ""))
        if _CEO_COMP_MIN <= val <= _CEO_COMP_MAX:
            comp = val
            comp_match_end = m.end()

    ratio: int | None = None
    # Issuers phrase the Item 402(u) ratio several ways:
    #   "...pay ratio was 129:1"            (NVDA)
    #   "...pay ratio of 533 to 1"          (AAPL)
    #   "...resulting in a ratio of 363 to 1" (JPM — no literal "pay ratio")
    #
    # The 402(u) disclosure states the *current-year* comp then its matching
    # ratio in the same sentence/paragraph. When we anchored a comp, search
    # for the ratio from that comp onward so the returned (comp, ratio) is a
    # genuine same-paragraph pair — a plain first-match would grab a prior-year
    # ratio quoted earlier ("Last year, our CEO pay ratio was 250 to 1. For
    # fiscal 2025 ... 312 to 1.") that does not belong to this comp. If no
    # paired ratio follows the comp, fall back to a document-wide first match.
    ratio_patterns = (
        r"pay\s+ratio\s+(?:of\s+)?(?:was|is|equal to|:)?\s*(?:approximately\s+)?"
        r"([0-9][0-9,]*)\s*(?:to|:)\s*1\b",
        r"ratio\s+of\s+(?:approximately\s+)?([0-9][0-9,]*)\s*(?:to|:)\s*1\b",
    )
    if comp_match_end is not None:
        ratio = _first_ratio_match(ratio_patterns, compact, comp_match_end)
    if ratio is None:
        ratio = _first_ratio_match(ratio_patterns, compact, 0)

    return comp, ratio


def _first_ratio_match(patterns: tuple[str, ...], text: str, start: int) -> int | None:
    """Return the first pay-ratio integer matched at or after ``start``."""
    for pattern in patterns:
        match = re.compile(pattern, re.I).search(text, start)
        if match is not None:
            return int(match.group(1).replace(",", ""))
    return None


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


# Generational suffixes legitimately end with a period inside a personal name.
_NAME_SUFFIX_TOKENS: frozenset[str] = frozenset({"jr.", "sr.", "ii.", "iii.", "iv."})

# Corporate-entity and compensation-document vocabulary. A real personal name
# never contains these, so ANY occurrence poisons the candidate — unlike the
# title-word list, which only rejects when it covers EVERY token ("CEO Pay
# Ratio" and "Acme Corp" both sailed past that all-token gate via the weak
# post-anchor scan). Compared with trailing punctuation stripped.
_NON_PERSON_TOKENS: frozenset[str] = frozenset(
    {
        "corp",
        "corporation",
        "inc",
        "incorporated",
        "llc",
        "ltd",
        "plc",
        "holdings",
        "company",
        "companies",
        "pay",
        "ratio",
        "compensation",
        "committee",
        "proxy",
        "statement",
        "table",
        "summary",
        "annual",
        "fiscal",
        "report",
        "shareholder",
        "shareholders",
        "stockholder",
        "stockholders",
        # pay-ratio prose ("Median Employee") and tenure qualifiers ("Former
        # Chairman") that the full-basket cache sweep caught leaking through
        # the weaker strategies (GOOGL / MU, 2026-07-07).
        "median",
        "employee",
        "employees",
        "former",
        "interim",
    }
)


def _is_sentence_boundary_token(token: str) -> bool:
    """A token ending '.' that is neither an initial ("B.") nor a suffix ("Jr.").

    A name run containing one straddles a sentence boundary — it was stitched
    from prose, not read from a name cell. MSFT 2026-07-07: the CD&A sentence
    "…$6,254,433 for Mr. Smith." followed by the "CEO Pay Ratio" heading let
    the name-above-title strategy emit "Mr. Smith." as the CEO and hang the
    $96.5M SCT total on the Vice Chair's honorific. Real name cells never
    carry a full-stop token, so this is a subsystem-wide reject (every
    extractor funnels through _is_blacklisted_name).
    """
    return token.endswith(".") and len(token) > 2 and token.lower() not in _NAME_SUFFIX_TOKENS


def _is_blacklisted_name(candidate: str) -> bool:
    """Return True when the candidate is not a plausible personal name.

    Three reject paths:
      (a) every token is a title/role word ("Chief Executive Officer") —
          the regex matched a job description rather than a name; or
      (b) any token is an English function word ("Us", "All", "The") —
          a regex with `\\s+` between tokens stitched a sentence fragment
          across a paragraph break into a fake multi-token name. Real
          personal names never contain pronouns/articles/conjunctions; or
      (c) any token is a sentence-boundary full stop ("Smith." / "Mr.") —
          the run straddles prose punctuation instead of naming one person
          (see _is_sentence_boundary_token); or
      (d) any token is corporate/compensation-document vocabulary ("Acme
          Corp", "CEO Pay Ratio") — a company or heading, not a person.
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
    if any(_is_sentence_boundary_token(t) for t in tokens):
        return True
    if any(t.lower().strip(".,") in _NON_PERSON_TOKENS for t in tokens):
        return True
    # A possessive token ("Micron's") is issuer prose, never a name part.
    if any(t.lower().rstrip(".,").endswith(("'s", "’s")) for t in tokens):
        return True
    return False


# "<Name>, [our] [Chairman/President and] Chief Executive Officer" — the name
# is SYNTACTICALLY APPOSITIVE to the title, so they describe the SAME person.
# This is the only binding where a director/other-officer surname cannot be
# substituted by mere proximity. The comma (or dash/colon) right after the name
# is the load-bearing anchor; the optional "our" and "Chairman/President and"
# prefixes cover the canonical KO/AAPL-style "James Quincey, our Chairman and
# Chief Executive Officer". NO re.I — the name group [A-Z] must enforce
# uppercase-first tokens (re.I would match lowercase and over-capture).
_CEO_APPOSITIVE_TITLE_RE = re.compile(
    r"([A-Z][A-Za-z.'’-]+(?:[ \t\xa0]+[A-Z][A-Za-z.'’-]+){1,3})"
    r"[ \t\xa0]*[,\-:–—][ \t\xa0]*"
    r"(?:our[ \t\xa0]+)?"
    r"(?:(?:Chairman|President|Chief Executive)[ \t\xa0]+and[ \t\xa0]+){0,2}"
    r"Chief Executive Officer\b",
)


# Capitalized proxy action verbs that lead a "<Verb> <Name>, <title>" sentence
# ("Reelect James Quincey, our Chairman and CEO"). The name group's leading
# [A-Z] would glue them onto the front of the name; strip them like the SCT
# header words. Real personal names never start with these.
_CEO_NAME_LEADING_VERBS: frozenset[str] = frozenset(
    {
        "reelect",
        "re-elect",
        "elect",
        "reelected",
        "elected",
        "nominate",
        "nominated",
        "appoint",
        "appointed",
        "reappoint",
        "reappointed",
        "name",
        "named",
        "for",
        "mr",
        "ms",
        "mrs",
        "dr",
    }
)


def _strip_leading_name_verbs(name: str) -> str:
    tokens = name.split()
    while tokens and tokens[0].lower().strip(".,") in _CEO_NAME_LEADING_VERBS:
        tokens.pop(0)
    return " ".join(tokens)


def _appositive_ceo_name(text: str) -> str | None:
    """Name directly comma-anchored to the canonical CEO title (one person).

    Returns the first non-blacklisted name bound to "<Name>, [our] [Chairman
    and] Chief Executive Officer". When two DISTINCT names bind that title (a
    leadership-transition proxy — KO 2026 lists both the outgoing "James
    Quincey, our Chairman and Chief Executive Officer" and the successor), the
    binding is no longer unambiguous, so the first appositive (the issuer's
    current named CEO, who is introduced before the successor) is returned —
    proximity strategies below would instead grab whichever name sits nearest
    *any* CEO mention and lose the appositive guarantee entirely.
    """
    for m in _CEO_APPOSITIVE_TITLE_RE.finditer(text):
        candidate = _strip_leading_name_verbs(m.group(1).strip())
        if len(candidate.split()) < 2:
            # A single residual token is not a "Firstname Lastname" — reject
            # rather than emit a lone surname/first name.
            continue
        if not _is_blacklisted_name(candidate):
            return candidate
    return None


def _extract_ceo_name(text: str) -> str | None:
    """Extract CEO name from proxy text — 宁可 None 绝不编 (never a wrong person).

    Strategy, strongest binding first. The ranking is by how tightly the NAME
    is bound to the CEO TITLE for the *same* person — proximity heuristics that
    bind any nearby name to any nearby title are demoted, because in a multi-
    executive / leadership-transition proxy they grab the wrong person (KO 2026:
    successor-COO "Henrique Braun" mis-bound as CEO over named CEO James
    Quincey via "Mr. Braun" sitting near a CEO anchor that belonged to Quincey).

    0. "Firstname Lastname\\nCEO ..." (table layout — name on line above title).
    1. "<Name>, [our] [Chairman and] Chief Executive Officer" — appositive bind
       (the name and title describe the SAME person; substitution-proof).
    2. Single, UNAMBIGUOUS "Mr./Ms./Dr. <Name>" near a CEO anchor — fires only
       when exactly one distinct honorific name sits near CEO anchors. When ≥2
       distinct candidates qualify (succession proxy), abstain: a wrong name is
       worse than None, and the appositive bind above already had its chance.
    3. Single, UNAMBIGUOUS post-anchor name — same abstain-on-tie rule.

    Honorific proximity and post-anchor scans NEVER win over the appositive
    bind, and NEVER guess when the binding is ambiguous: None beats a wrong CEO.
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
    # The title line is either bare "CEO …" or the full canonical form the
    # signature/letter layout uses ("Satya Nadella\n\nChairman and Chief
    # Executive Officer" — MSFT 2025 proxy, missed while the bare-CEO branch
    # false-matched a "CEO Pay Ratio" heading). The full-title branch must END
    # the title claim there: "Chief Executive Officer, Acme" / "… of Acme" is a
    # DIRECTOR's outside role, not this issuer's CEO — reject via lookahead.
    prev_line_pattern = re.compile(
        r"([A-Z][A-Za-z.'-]+(?:[ \t\xa0]+[A-Z][A-Za-z.'-]+){1,3})"
        r"\s*\n\s*"
        r"(?:CEO\b|"
        r"(?:(?:Chairman|Vice[ \t\xa0]+Chair(?:man)?|President)[ \t\xa0]+and[ \t\xa0]+){0,2}"
        r"Chief[ \t\xa0]+Executive[ \t\xa0]+Officer\b(?![ \t\xa0]*[,–—-])(?![ \t\xa0]+of\b))",
    )
    for m in prev_line_pattern.finditer(text):
        # Same hygiene as the appositive path: strip leading honorifics/action
        # verbs ("Mr Smith" → "Smith") and require a Firstname-Lastname run —
        # a single residual token is a prose fragment, not a name cell.
        candidate = _strip_leading_name_verbs(m.group(1).strip())
        if len(candidate.split()) < 2:
            continue
        if not _is_blacklisted_name(candidate):
            return candidate

    # Strategy 1: appositive "<Name>, [our] [Chairman and] Chief Executive
    # Officer" — the highest-confidence prose signal because the comma binds the
    # name to the title for ONE person. Promoted above the honorific/proximity
    # heuristics, which a leadership-transition proxy (KO) defeats by placing a
    # successor's "Mr. <Name>" near the named CEO's title anchor.
    appositive = _appositive_ceo_name(text)
    if appositive is not None:
        return appositive

    ceo_positions = [
        m.start() for m in re.finditer(r"(?:Chief Executive Officer|CEO)\b", text, re.I)
    ]

    # Strategy 2: "Mr./Ms./Dr. <Name>" near a CEO anchor — but ONLY when exactly
    # one distinct candidate qualifies. The honorific marks a personal name, yet
    # proximity to "a" CEO mention does NOT prove the title is THIS person's: a
    # succession proxy puts "Mr. <successor>" and "Mr. <current CEO>" both near
    # CEO anchors. When ≥2 distinct names qualify we cannot tell which is CEO →
    # abstain (None) rather than emit a coin-flip. NO re.I (see name-group note).
    honorific_pattern = re.compile(
        r"(?:Mr\.|Ms\.|Mrs\.|Dr\.)[ \t\xa0]+"
        r"([A-Z][A-Za-z.'-]+(?:[ \t\xa0]+[A-Z][A-Za-z.'-]+){0,3})",
    )
    honorific_hits: list[str] = []
    for m in honorific_pattern.finditer(text):
        candidate = m.group(1).strip()
        if _is_blacklisted_name(candidate):
            continue
        if any(abs(m.start() - pos) <= 300 for pos in ceo_positions):
            if candidate not in honorific_hits:
                honorific_hits.append(candidate)
    if len(honorific_hits) == 1:
        return honorific_hits[0]
    if len(honorific_hits) > 1:
        # Ambiguous (multiple execs near CEO anchors) — abstain. Do NOT fall
        # through to the even-weaker post-anchor scan, which would resolve the
        # same ambiguity by grabbing whichever name happens to sit first.
        return None

    # Strategy 3: post-anchor scan — weakest signal (first capitalized bigram in
    # a 120-char window after a CEO mention). Same abstain-on-tie discipline:
    # collect the distinct candidates across ALL CEO anchors and only resolve
    # when exactly one survives. "Mr. <successor> will serve as Chief Executive
    # Officer" plus the named CEO's own mention would otherwise both qualify.
    post_hits: list[str] = []
    for ceo_match in re.finditer(r"(?:Chief Executive Officer|CEO)\b[^\n]{0,120}", text, re.I):
        window = ceo_match.group(0)
        for candidate_match in re.finditer(
            r"\b([A-Z][A-Za-z'-]+(?:\s+[A-Z][A-Za-z'-]+){1,3})\b",
            window,
        ):
            candidate = candidate_match.group(1).strip()
            if len(candidate.replace(" ", "")) <= 3:
                continue
            if _is_blacklisted_name(candidate):
                continue
            if candidate.lower().startswith("the "):
                continue
            if candidate not in post_hits:
                post_hits.append(candidate)
    if len(post_hits) == 1:
        return post_hits[0]
    return None


# A "Firstname [M.] Lastname" run: 2–4 uppercase-first tokens, allowing middle
# initials ("D."), hyphens ("Jen-Hsun") and apostrophes ("D'Amaro"). NO re.I —
# the leading [A-Z] must stay case-sensitive or it over-captures lowercase prose.
_CERT_NAME_RUN = r"[A-Z][A-Za-z.'’\-]+(?:[ \t\xa0]+[A-Z][A-Za-z.'’\-]+){1,3}"

# The defining first sentence of a Section-302 certification:
#   "I, Timothy D. Cook, certify that:"                         (AAPL — bare)
#   "I, Henrique Braun, Chief Executive Officer of The Coca-Cola
#    Company, certify that:"                                    (KO — title clause)
# The name is bounded by the comma right after it, so the optional title clause
# (a single comma-delimited run, no comma inside) can never be swallowed into
# the name. Only "certify" is case-insensitive; the name group is not.
_CERT_OPENING_RE = re.compile(
    r"\bI,[ \t\xa0]+(" + _CERT_NAME_RUN + r")[ \t\xa0]*,[ \t\xa0]*"
    r"(?:[^,\n]{0,90}?,[ \t\xa0]*)?"
    r"[Cc]ertif",
)

# Signature-block fallback: the typed name on its own line immediately above the
# "[Chairman/President and] Chief Executive Officer" title line (every 302 cert
# closes this way after the "/s/ NAME" graphic line).
_CERT_SIGBLOCK_RE = re.compile(
    r"(" + _CERT_NAME_RUN + r")[ \t\xa0]*\n[ \t\xa0\r]*"
    r"(?:(?:Chairman|Vice[ \t\xa0]+Chair(?:man)?|President)[ \t\xa0]+and[ \t\xa0]+){0,2}"
    r"Chief[ \t\xa0]+Executive[ \t\xa0]+Officer\b",
)


def _extract_ceo_name_from_cert(cert_text: str) -> str | None:
    """CEO name from an Exhibit-31.1 (SOX-302) certification — None, never wrong.

    The certification is signed, by law, by the CURRENT principal executive
    officer, so its signer is the authoritative "who is CEO now" — fresher than
    the annual DEF 14A prose, which goes stale on a mid-year succession (KO
    Quincey→Braun, DIS Iger→D'Amaro). Two strategies, strongest first:

      1. The opening "I, <Name>[, <title clause>], certify" sentence — the name
         is comma-bounded so the title clause cannot leak into it.
      2. The closing signature block — the typed name directly above the
         "Chief Executive Officer" title line.

    Every candidate funnels through the shared ``_is_blacklisted_name`` choke
    (sentence-boundary / corporate-vocabulary / possessive rejects), so a stray
    boilerplate fragment can never surface as a CEO. A parse miss returns None
    and the caller falls back to the proxy scrape — a miss is safe.
    """
    if not cert_text:
        return None

    compact = _normalise_proxy_text(cert_text)
    m = _CERT_OPENING_RE.search(compact)
    if m is not None:
        candidate = m.group(1).strip()
        if len(candidate.split()) >= 2 and not _is_blacklisted_name(candidate):
            return candidate

    for sig in _CERT_SIGBLOCK_RE.finditer(cert_text):
        candidate = " ".join(sig.group(1).split())
        if len(candidate.split()) >= 2 and not _is_blacklisted_name(candidate):
            return candidate

    return None


def _cert_provenance(cert_data: dict[str, Any]) -> FilingProvenance | None:
    """FilingProvenance for the 10-Q/10-K a cert-sourced CEO name was read from."""
    if not cert_data.get("filing_date") or not cert_data.get("accession_no"):
        return None
    try:
        return _provenance(
            form=str(cert_data.get("form") or ""),
            filing_date=cert_data["filing_date"],
            accession_no=cert_data["accession_no"],
            source_url=cert_data.get("source_url"),
        )
    except ValueError:
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

    # Comp source priority: pay-ratio disclosure prose → SCT table grid →
    # generic "CEO compensation $X" anchor. The Item 402(u) disclosure states
    # the CEO's actual total comp in words ("...total compensation of our CEO
    # was $96,496,790") and is the most reliable across issuer table formats;
    # all three resolve to the same SCT-total figure.
    raw_comp = (
        disclosure_comp
        if disclosure_comp is not None
        else summary_comp
        if summary_comp is not None
        else _ceo_comp_from_text(text)
    )
    ceo_total_compensation: float | None = None
    if raw_comp is not None and _CEO_COMP_MIN <= raw_comp <= _CEO_COMP_MAX:
        ceo_total_compensation = raw_comp

    # Ratio: prefer the (comp, ratio) pair parsed from the SAME 402(u)
    # paragraph by _ceo_comp_and_ratio_from_disclosure. When that paragraph
    # gives us the comp we're using, its ratio is the matching current-year
    # figure and must win as a unit — otherwise the global first-match
    # _extract_ceo_pay_ratio can grab a prior-year ratio from an earlier
    # sentence ("Last year, our CEO pay ratio was 250 to 1. For fiscal 2025
    # ... 312 to 1.") and override the paired current-year value.
    # _extract_ceo_pay_ratio is only a fallback when the disclosure paragraph
    # yields no ratio.
    if disclosure_ratio is not None:
        ceo_pay_ratio: int | None = disclosure_ratio
    else:
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
        # None ≠ 0: a 13F holder with no parseable share count or value is a
        # parse gap, NOT a real 0-share / $0 position (SEC 13F-HR always reports
        # both SHARES and VALUE > 0 for a held security). The model requires
        # non-null shares/value_usd, so a degenerate row is dropped — coercing
        # missing→0 (the old `or 0`) fabricated a phantom $0 holder. The cache
        # ingest already drops these upstream; this guards any direct caller.
        shares = _opt_float(row.get("shares"))
        value_usd = _opt_float(row.get("value_usd"))
        if shares is None or value_usd is None:
            logger.warning(
                "drop 13F holding with missing shares/value (holder=%s cusip=%s): "
                "shares=%r value_usd=%r",
                row.get("holder_name"),
                row.get("cusip"),
                row.get("shares"),
                row.get("value_usd"),
            )
            continue
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
                shares=int(shares),
                value_usd=value_usd,
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


# Officer-title tokens that identify the *current* CEO in Form-4 metadata. The
# filer self-declares this title in structured XML — a far more reliable CEO
# identity than scraping a name out of DEF 14A prose, which grabbed director
# "T. Mark Liu" off another company's "Former Chief Executive Officer of Intel"
# bio for MU (2026-06) while the Form-4s carried the real CEO "Sanjay Mehrotra".
_CEO_TITLE_RE = re.compile(r"chief executive officer|\bceo\b", re.I)


# Divisional / regional / subsidiary "CEO" — NOT the parent-company CEO. Ford's
# Form-4s carry both "President and CEO" (Jim Farley, the issuer's CEO) and
# "President & CEO Ford China&IMG" (Shengpo Wu, a regional unit CEO); the
# regional title must be rejected so a business-unit head can't outrank the
# parent CEO on the filing-count tie-break (2026-06-13: F resolved to
# "Shengpo Wu").
def _is_divisional_ceo_title(position: str) -> bool:
    """True when the title is a business-unit/region CEO, not the parent CEO.

    Anchored on the CEO token: a parent-company CEO title ends at "CEO" /
    "Chief Executive Officer" or continues only with a connector ("and", "of
    the Company"). A capitalized unit/region word trailing the CEO token
    ("CEO Ford China", "President & CEO of EMEA") marks a divisional CEO.
    """
    m = _CEO_TITLE_RE.search(position)
    if m is None:
        return False
    tail = position[m.end() :].lstrip(" \t,-")
    # Strip a leading "of [the] " so "CEO of the Company" still reads as parent.
    of_stripped = re.sub(r"^of\s+(?:the\s+)?", "", tail, flags=re.I)
    if not of_stripped:
        return False
    # A connector to ANOTHER parent-level title ("and Chairman") is the issuer
    # CEO; only a proper-noun/number unit name (region/brand/segment) is
    # divisional. "Company"/"Issuer" right after "of the" is the parent.
    if re.match(r"(?:company|issuer)\b", of_stripped, re.I):
        return False
    if re.match(r"and\b", of_stripped, re.I):
        return False
    # Remaining capitalized/numeric token = a named unit ("Ford China&IMG",
    # "EMEA", "Americas") → divisional.
    return bool(re.match(r"[A-Z0-9]", of_stripped))


def _ceo_name_from_insiders(insiders: list[InsiderTransaction]) -> str | None:
    """Resolve the current CEO's name from Form-4 officer titles.

    Returns the name carried by the most Form-4 filings whose ``insider_position``
    declares a current parent-company CEO title (tie-break: most recent filing).
    ``None`` when no insider holds such a title. Explicit "former" titles and
    divisional/regional CEO titles ("President & CEO Ford China") are skipped so
    a departed or business-unit CEO cannot win.
    """
    counts: dict[str, int] = {}
    latest: dict[str, date] = {}
    for tx in insiders:
        position = tx.insider_position or ""
        if "former" in position.lower():
            continue
        if not _CEO_TITLE_RE.search(position):
            continue
        if _is_divisional_ceo_title(position):
            continue
        name = (tx.insider_name or "").strip()
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
        if name not in latest or tx.filing_date > latest[name]:
            latest[name] = tx.filing_date
    if not counts:
        return None
    return max(counts, key=lambda n: (counts[n], latest[n]))


def _latest_insider_provenance(
    insiders: list[InsiderTransaction], name: str
) -> FilingProvenance | None:
    """Provenance of the most recent Form-4 filed by ``name`` (for CEO-name source)."""
    matches = [tx for tx in insiders if (tx.insider_name or "").strip() == name]
    if not matches:
        return None
    return max(matches, key=lambda t: t.filing_date).provenance


def compute_ownership_governance(
    *,
    insider_data: dict[str, Any] | None,
    institutional_data: dict[str, Any] | None,
    proxy_data: dict[str, Any] | None,
    schedule13_data: dict[str, Any] | None = None,
    cert_data: dict[str, Any] | None = None,
) -> OwnershipGovernanceAnalysis:
    degraded_sections: list[str] = []

    insiders = build_insider_transactions(insider_data or {})
    if not insiders:
        degraded_sections.append("insider_transactions")

    institutions = build_institutional_holdings(institutional_data or {})
    if not institutions:
        degraded_sections.append("institutional_holdings")

    proxy = build_proxy_compensation(proxy_data or {})
    # CEO identity is a structured fact: the Form-4 officer title (self-declared
    # in XML) is authoritative over the DEF 14A prose scraper, which is fragile
    # enough to grab a director's surname off another firm's "Former CEO of X"
    # bio (MU showed "Liu" — director T. Mark Liu — while Form-4s carry the real
    # CEO "Sanjay Mehrotra"). Override the scraped name whenever a Form-4 CEO
    # resolves; the prose scraper stays as the no-Form-4 fallback.
    ceo_from_insiders = _ceo_name_from_insiders(insiders)
    if proxy is not None and ceo_from_insiders and proxy.ceo_name != ceo_from_insiders:
        logger.info(
            "ownership: CEO name set from Form-4 officer title %r (was proxy-scraped %r)",
            ceo_from_insiders,
            proxy.ceo_name,
        )
        proxy.ceo_name = ceo_from_insiders
        proxy.ceo_name_source = "form4"
        proxy.ceo_name_provenance = _latest_insider_provenance(insiders, ceo_from_insiders)

    # SOX-302 CEO certification (Exhibit 31.1) — the HIGHEST-authority current-CEO
    # source, applied LAST so it wins over both the proxy scrape and the Form-4
    # title. The signer is by law the current principal executive officer and it
    # re-files quarterly, so it is the one signal that reflects a mid-year
    # succession the annual proxy still shows the outgoing CEO for (KO 2026:
    # proxy=Quincey but 10-Q cert=Braun; DIS 2026: proxy=Iger but 10-Q
    # cert=D'Amaro). A cert name only wins after clearing the same
    # _is_blacklisted_name choke; a miss leaves the proxy/Form-4 name untouched.
    cert_name = _extract_ceo_name_from_cert(str((cert_data or {}).get("cert_text") or ""))
    if proxy is not None and cert_name:
        if proxy.ceo_name != cert_name:
            logger.info(
                "ownership: CEO name set from SOX-302 cert %r (was %r via %s)",
                cert_name,
                proxy.ceo_name,
                proxy.ceo_name_source,
            )
        proxy.ceo_name = cert_name
        proxy.ceo_name_source = "sox302_cert"
        proxy.ceo_name_provenance = _cert_provenance(cert_data or {})

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

    # Lift fetch warnings (e.g. 13F stale-quarter) off the raw payloads into
    # the analysis object — builders._collect_warnings only walks structured
    # models, so warnings dropped here would never reach
    # artifact.outputs.warnings. Deduped, order-preserving.
    warnings: list[str] = []
    for payload in (insider_data, institutional_data, proxy_data, schedule13_data, cert_data):
        for warning in (payload or {}).get("warnings") or []:
            if warning not in warnings:
                warnings.append(warning)

    return OwnershipGovernanceAnalysis(
        insider_transactions=insiders,
        institutional_holdings=institutions,
        proxy_compensation=proxy,
        schedule13_alerts=schedule13_alerts,
        generated_at=datetime.now(tz=timezone.utc),
        degraded_sections=degraded_sections,
        warnings=warnings,
    )
