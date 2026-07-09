"""EdgarTools SEC primary data layer adapter.

Replaces the hand-rolled ``sec_provider.py`` (382 lines of regex section
splitting + manual ticker→CIK map + manual rate-limit lock).

Architectural rules sealed by spec v4 §5 + 门 1 probe:
  - ``__init__`` MUST NOT raise on bad identity. Identity validation lives
    in ``_is_valid_identity`` + the caller (``build_data_layer``) decides
    whether to register the provider.
  - All edgartools calls run in ``asyncio.to_thread`` (the library is
    sync-blocking; nest-asyncio handles the loop). 门 1 实测 uvicorn
    lifespan serve 起停 10/10 通过 0 异常.
  - Section access uses **typed attributes** (``tenk.business`` etc.) not
    ``tenk.sections()``; edgartools 5.31 the latter is non-callable.
  - 10-K/A amended filings: typed attrs return empty strings → adapter
    re-fetches ``get_filings("10-K", amendments=False)``.
  - Financial-institution MD&A may be < 1000 chars due to edgartools'
    parser limits → adapter falls back to ``filing.text()`` so downstream
    BM25 (``engine/primitives/rag.py``) still has something to index.
  - 13F reverse lookup goes through the local cache
    (``sec_holdings_cache``); never scans all 13F-HR filings on a request.
  - Exception class is ``DataObjectException + CompanyNotFoundError`` (no
    ``EdgarError`` — that class does not exist in 5.31).
  - InsiderTransaction model fields map to edgartools'
    ``TransactionActivity`` (NOT ``form4.transactions``, which is a
    DataFrame attr, not a list).
  - XBRL uses typed getters ``get_revenue() / get_ttm_revenue()``; raw
    ``EntityFacts.to_pandas(tag)`` does not exist in 5.31.

Probe evidence: ``specs/research/edgartools_probe_findings_2026-05-27.md``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

# edgartools 5.31 real exception classes (probe-verified; EdgarError does
# not exist). Imported lazily-fail style so the module loads even without
# the dep (build_data_layer SKIPs registration when identity is invalid).
try:
    from edgar import (
        Company,
        CompanyNotFoundError,
        DataObjectException,
        get_filings,
        set_identity,
    )

    _EDGAR_AVAILABLE = True
except ImportError:  # pragma: no cover — defensive; we always pin edgartools
    Company = None
    CompanyNotFoundError = Exception
    DataObjectException = Exception
    get_filings = None
    set_identity = None
    _EDGAR_AVAILABLE = False

from finrobot.engine.data.interface import (
    DataProvider,
    DataResult,
    ProviderError,
    RateLimitedProviderError,
)
from finrobot.engine.data.types import DataType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Local identity gate — purely synchronous, never touches SEC servers
# ---------------------------------------------------------------------------


def _is_valid_identity(s: str | None) -> bool:
    """Return True iff ``s`` is a SEC-acceptable User-Agent.

    SEC policy requires ``Name email@domain`` format. Our config.py default
    (``"FinRobot admin@example.com"``) is a placeholder — rejecting it here
    is what prevents ``build_data_layer`` from registering an
    EdgarToolsProvider until the user has filled in a real identity.

    This is a pure local check. We never validate the identity by calling
    SEC ("does this email get rate-limited?") — that would be an abuse of
    the public service.
    """
    if not s or not isinstance(s, str):
        return False
    s = s.strip()
    if "@" not in s or " " not in s:
        return False
    if s == "FinRobot admin@example.com":  # our config.py placeholder
        return False
    if _sec_header_identity(s) is None:
        return False
    return True


def _sec_header_identity(s: str | None) -> str | None:
    """Return an ASCII-only User-Agent value accepted by HTTP clients.

    Settings keep the user's display identity exactly as entered. HTTP headers
    cannot carry non-ASCII bytes in httpx/edgartools, so a Chinese display name
    such as ``郭嘉祺 17696026747@163.com`` is converted at the transport edge to
    ``FinRobot 17696026747@163.com`` while preserving the contact email SEC
    needs for abuse/rate-limit attribution.
    """
    if not s or not isinstance(s, str):
        return None
    raw = s.strip()
    if raw == "FinRobot admin@example.com":
        return None
    match = re.search(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w.-]+\.[A-Za-z]{2,}", raw)
    if match is None:
        return None
    email = match.group(0)
    name = raw[: match.start()].strip() or raw[match.end() :].strip()
    ascii_name = "".join(ch if ord(ch) < 128 else " " for ch in name)
    ascii_name = " ".join(ascii_name.split())
    if not ascii_name:
        ascii_name = "FinRobot"
    header = f"{ascii_name} {email}"
    try:
        header.encode("ascii")
    except UnicodeEncodeError:
        return None
    return header


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


_SUPPORTED: list[DataType] = [
    DataType.FILINGS_10K,
    DataType.FILINGS_10Q,
    DataType.FILINGS_8K,
    DataType.XBRL_FACTS,
    DataType.INSIDER_TRADES,
    DataType.INSTITUTIONAL_HOLDINGS,
    DataType.PROXY_STATEMENT,
    DataType.SCHEDULE_13,
    DataType.CEO_CERTIFICATION,
    DataType.RAG_10K,  # legacy alias
    DataType.FILINGS,  # legacy alias for 10-K
]


# Exceptions we map to ProviderError (don't crash the route layer).
# Wider than strictly needed because edgartools occasionally raises
# bare AttributeError / TypeError when a filing has unexpected structure.
#
# httpx.HTTPError is the base of every edgartools network failure
# (ReadTimeout / ConnectError / ConnectTimeout / RemoteProtocolError …).
# edgartools runs its OWN httpx client inside our asyncio.to_thread call, so
# a slow/unreachable SEC raises a raw httpx error that is NOT an OSError —
# without catching it here it escaped fetch() un-wrapped and crashed the whole
# pipeline (observed: 8-K ReadTimeout / "nodename nor servname" ConnectError
# tanking an entire equity_research run from _gather_data). Mapping it to
# ProviderError lets every consumer (_gather_data, _fetch_optional_sec,
# peer XBRL fetch) degrade to "SEC unavailable" instead of aborting.
_ADAPTER_CATCH = (
    DataObjectException,
    CompanyNotFoundError,
    OSError,
    RuntimeError,
    ValueError,
    AttributeError,
    TypeError,
    httpx.HTTPError,
)


def _provider_error(msg: str, cause: BaseException) -> ProviderError:
    """ProviderError factory that preserves rate-limit semantics BY TYPE.

    A wrapped ``httpx.HTTPStatusError`` carrying HTTP 429 becomes
    ``RateLimitedProviderError`` so the circuit-breaker / quote-batch classify
    it structurally instead of sniffing the message. ONLY a literal 429 maps:
    SEC throttling historically answers 403 "Request Rate Threshold Exceeded",
    but 403 is also the generic forbidden/missing-identity status — typing it
    as rate-limit would mis-classify identity failures as transient, so those
    stay plain ``ProviderError`` (the message fallback never matched them
    either; behaviour unchanged).
    """
    if isinstance(cause, httpx.HTTPStatusError) and cause.response.status_code == 429:
        return RateLimitedProviderError(msg)
    return ProviderError(msg)


# Min char threshold below which we treat a typed section attribute as
# "edgartools parser came up short" and fall back to filing.text() so the
# downstream BM25 index isn't blank. Probe 2026-05-27 saw JPM 10-K
# management_discussion = 396 chars (real text is ~100 pages).
_MIN_VALID_SECTION_CHARS = 1000


# ---------------------------------------------------------------------------
# TTM concept selection + validity gate (ADR-0008)
# ---------------------------------------------------------------------------
#
# edgartools' convenience getters ``get_ttm_revenue`` / ``get_ttm_net_income``
# walk a fixed concept list and return the FIRST concept that has ANY facts —
# they never check whether that concept is still being reported. NVDA abandoned
# ``RevenueFromContractWithCustomerExcludingAssessedTax`` after FY2022, but its
# stale facts (frozen at $10.918B, period_end 2020-01-26) still satisfy the
# first-match, so ``get_ttm_revenue`` latched the dead concept and never reached
# the live ``Revenues`` series ($253.5B). We replicate the concept candidate
# lists here but pick by **latest period_end** instead of list order, then gate
# the chosen TTM on period structure (4 distinct consecutive quarters, recent).
# A failed gate returns None — ``_ttm_value`` (compute layer) then falls back to
# the FMP TTM, which is independently correct. See ADR-0008.
# Revenue concept ranking (financial-issuer revenue-subset bug, 2026-06-29):
# total-revenue concepts MUST outrank the ASC-606 contract-revenue SUBSET. For an
# insurer/bank, ``RevenueFromContractWithCustomer…`` reports only fee/contract
# revenue (MET FY2025: $2.4B) — a fraction of total ``Revenues`` ($77.1B) — yet
# BOTH carry the SAME period_end, so the old ASC-606-first list latched the subset
# and fed the LLM revenue understated ~31×. The selectors already pick by latest
# period_end (so a newer concept still wins ACROSS periods — AAPL stopped reporting
# ``Revenues`` after FY2018, its live revenue is ASC-606 only), but a SAME-period
# tie was broken by list order; ordering totals first makes the tie resolve to the
# true total. We break the tie by concept RANK, never magnitude, so a gross-of-tax
# ``…IncludingAssessedTax`` cannot out-bid the real ``Revenues`` total.
_TTM_REVENUE_CONCEPTS: tuple[str, ...] = (
    "Revenues",
    "SalesRevenueNet",
    "Revenue",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
)
_TTM_NET_INCOME_CONCEPTS: tuple[str, ...] = ("NetIncomeLoss", "NetIncome", "ProfitLoss")

# Point-in-time / annual concept candidate lists, mirroring edgartools'
# ``EntityFacts.get_*`` getters (entity_facts.py, 5.31.5). We replicate them so
# we can recover the REAL matched concept the getter would have used instead of
# a hardcoded label: post-ASC-606 issuers (AAPL/MSFT/GOOGL) report revenue under
# ``RevenueFromContractWithCustomerExcludingAssessedTax``, not ``Revenues`` —
# labelling the snapshot "us-gaap:Revenues" was provenance falsification (BUG-009).
# Order = the getter's priority order; first concept with a usable fact wins,
# exactly as ``_get_standardized_concept_value`` does.
# Totals first, ASC-606 contract-revenue subset last — see _TTM_REVENUE_CONCEPTS
# (financial-issuer revenue-subset bug, 2026-06-29). Paired with prefer_recent=True
# at the call site so recency still wins across periods (AAPL: ASC-606 newer →
# 416B) while a SAME-period tie resolves to the total (MET: Revenues 77B over
# ASC-606 2.4B). Post-ASC-606 issuers (AAPL/MSFT/GOOGL) that no longer report
# ``Revenues`` simply fall through to the ASC-606 concept (recency + presence).
_LATEST_REVENUE_CONCEPTS: tuple[str, ...] = (
    "Revenues",
    "TotalRevenues",
    "SalesRevenueNet",
    "NetSales",
    "Revenue",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
)
_LATEST_NET_INCOME_CONCEPTS: tuple[str, ...] = (
    "NetIncomeLoss",
    "ProfitLoss",
    "NetIncome",
    "NetEarnings",
    "NetIncomeLossAttributableToParent",
)
_LATEST_GROSS_PROFIT_CONCEPTS: tuple[str, ...] = ("GrossProfit", "GrossMargin")
_LATEST_OPERATING_INCOME_CONCEPTS: tuple[str, ...] = (
    "OperatingIncomeLoss",
    "OperatingIncome",
    "IncomeLossFromOperations",
    "OperatingProfit",
)
_LATEST_TOTAL_ASSETS_CONCEPTS: tuple[str, ...] = ("Assets", "TotalAssets", "AssetsCurrent")
_LATEST_TOTAL_LIABILITIES_CONCEPTS: tuple[str, ...] = (
    "Liabilities",
    "TotalLiabilities",
    "LiabilitiesAndStockholdersEquity",
)
_LATEST_SHAREHOLDERS_EQUITY_CONCEPTS: tuple[str, ...] = (
    "StockholdersEquity",
    "ShareholdersEquity",
    "TotalEquity",
    "PartnersCapital",
    "MembersEquity",
)

# A legitimate TTM window is exactly four DISCRETE quarters. edgartools labels
# discrete quarters Q1–Q4 and tags cumulative frames (annual / half-year /
# nine-month) with other markers; any non-Qn label inside a TTM window means a
# year-to-date frame leaked in and the naive sum would double-count. Allowlist
# the four quarter labels rather than blocklisting cumulative ones so a new
# cumulative marker can't slip through.
_DISCRETE_QUARTER_LABELS: frozenset[str] = frozenset({"Q1", "Q2", "Q3", "Q4"})

# Latest quarter in a valid TTM must end within this window of "now". A TTM whose
# newest quarter is older than this is a frozen/abandoned concept (NVDA's dead
# revenue concept ends 2020-01-26 — ~6 years stale). ~200 days ≈ one quarter of
# reporting lag plus generous slack for slow filers.
_TTM_RECENCY_DAYS = 200


def _is_usd_unit(unit: Any) -> bool:
    """True iff an XBRL fact's reporting unit is plain USD (BUG-037).

    edgartools surfaces a fact's currency verbatim in ``FinancialFact.unit`` /
    ``TTMMetric.unit`` (e.g. ``"USD"``, ``"EUR"``, ``"GBP"``). The library does
    NOT FX-convert: a 20-F foreign private issuer (functional currency EUR/GBP/
    CHF/JPY) returns its native-currency magnitude with the native unit. This
    layer never introduces an FX source (that boundary lives in
    ``normalize_peer_to_usd``); instead we admit a fact only when its unit is
    USD and suppress everything else to None upstream, so the compute layer falls
    back to the FX-normalized FMP base rather than comparing a native-currency
    XBRL value against a USD peer (the 35% divergence gate can miss near-parity
    currencies like GBP≈1.27 / CHF≈1.1).

    A missing/empty unit is treated as USD: the vast majority of SEC filers are
    domestic USD reporters and edgartools occasionally omits the unit on a
    cleanly-typed currency fact; refusing those would needlessly drop good US
    data. Foreign issuers DO carry an explicit non-USD unit, which is the case
    this guard exists to catch.
    """
    if unit is None:
        return True
    text = str(unit).strip().upper()
    if not text:
        return True
    # Currency facts may carry a compound numerator/denominator (e.g. a per-share
    # unit "USD/SHARES"); the reporting currency is the leading token. Revenue /
    # net income are plain currency, but split defensively so "USD-per-..." still
    # reads as USD rather than failing the equality check.
    head = text.replace("-PER-", "/").split("/", 1)[0].strip()
    return head == "USD"


def _validate_ttm_periods(periods: Any) -> bool:
    """True iff ``periods`` is a structurally valid TTM window.

    edgartools returns ``TTMMetric.periods`` as a list of ``(year, quarter)``
    tuples. A real TTM is four distinct, consecutive discrete quarters. This
    rejects the two ways the convenience getters go wrong:
      - degenerate window (NVDA dead concept → ``[(2020,'FY')]×4``): caught by
        the ``Qn``-only allowlist (``FY`` is not a discrete quarter) AND by the
        distinctness check.
      - year-to-date frame leaking into the sum (would double-count): caught by
        the same allowlist (``H1`` / ``9M`` etc. are not ``Qn``).
    """
    if not isinstance(periods, (list, tuple)) or len(periods) != 4:
        return False
    normalized: list[tuple[int, int]] = []
    for p in periods:
        if not (isinstance(p, tuple) and len(p) == 2):
            return False
        year, quarter = p
        q = str(quarter).upper()
        if q not in _DISCRETE_QUARTER_LABELS:
            return False
        try:
            normalized.append((int(year), int(q[1])))
        except (TypeError, ValueError):
            return False
    if len(set(normalized)) != 4:  # four DISTINCT quarters
        return False
    ordered = sorted(normalized)
    for (y0, q0), (y1, q1) in zip(ordered, ordered[1:]):
        nxt = (y0, q0 + 1) if q0 < 4 else (y0 + 1, 1)
        if (y1, q1) != nxt:  # consecutive, no gap/overlap
            return False
    return True


def _metric_as_of_date(metric: Any) -> date | None:
    """The TTM window's latest-quarter ``period_end`` (edgartools' ``as_of_date``).

    The ``TTMCalculator`` sets ``as_of_date = ttm_quarters[-1].period_end`` (the
    most recent quarter in the window), so it IS the recency-gate value AND the
    TTM "as of which quarter" date threaded downstream. Returns None when the
    field is missing/malformed.
    """
    pe = getattr(metric, "as_of_date", None)
    if isinstance(pe, datetime):
        pe = pe.date()
    return pe if isinstance(pe, date) else None


def _ttm_periods_as_str(periods: Any) -> list[str]:
    """Render edgartools' ``[(year, quarter), ...]`` TTM window as ``["Q3 2025", ...]``.

    Matches ``XBRLTTMMetric.periods: list[str]`` so the dict round-trips into the
    typed model without a shape adapter. ``_validate_ttm_periods`` has already
    confirmed the ``(int, str)`` tuple shape upstream; anything unexpected falls
    back to ``str(p)`` rather than crashing.
    """
    out: list[str] = []
    for p in periods or []:
        if isinstance(p, tuple) and len(p) == 2:
            out.append(f"{p[1]} {p[0]}")
        else:
            out.append(str(p))
    return out


def _select_recent_ttm(
    facts: Any,
    concepts: tuple[str, ...],
    *,
    today: date,
    warnings: list[str] | None = None,
) -> dict[str, Any] | None:
    """Pick the live concept's TTM and return it as a typed dict, or None.

    Among ``concepts`` present in ``facts``, choose the one whose window ends
    latest (``as_of_date``, NOT first-match-wins like edgartools' getters), then
    require the window to pass ``_validate_ttm_periods`` and end within
    ``_TTM_RECENCY_DAYS``. Returns
    ``{"concept", "value", "periods", "period_end", "has_calculated_q4", "warning"}``
    (``periods`` as ``list[str]`` to match ``XBRLTTMMetric.periods``), or None
    when nothing qualifies (→ FMP fallback). ``period_end`` carries the TTM's
    latest-quarter date so downstream can show "TTM as of <quarter>";
    ``has_calculated_q4`` / ``warning`` surface edgartools' quarterization caveats.

    BUG-037: a 20-F foreign private issuer reports TTM in its functional currency
    (EUR/GBP/CHF/JPY) and edgartools returns the native magnitude with a non-USD
    ``TTMMetric.unit`` — no FX is applied. We refuse such a window (skip the
    candidate, append a warning to ``warnings``) so the compute layer falls back
    to the FX-normalized FMP TTM base instead of overriding it with a native-
    currency value the 35% divergence gate could wave through for a near-parity
    currency. FX belongs to ``normalize_peer_to_usd``, not this provider.
    """
    best: dict[str, Any] | None = None
    best_end: date | None = None
    for concept in concepts:
        try:
            metric = facts.get_ttm(concept)
        except _ADAPTER_CATCH:
            continue  # KeyError (absent concept) subclasses LookupError → not caught; handle below
        except LookupError:
            continue
        if metric is None:
            continue
        unit = getattr(metric, "unit", None)
        if not _is_usd_unit(unit):
            if warnings is not None:
                warnings.append(
                    f"SEC XBRL TTM {getattr(metric, 'concept', concept)} reported in "
                    f"{unit}, not USD; suppressed (no FX in provider) — falling back "
                    "to FX-normalized FMP TTM."
                )
            continue
        latest_end = _metric_as_of_date(metric)
        if latest_end is None:
            continue
        # Recency gate: a window whose newest quarter predates the cutoff is a
        # frozen/abandoned concept, even if it "wins" recency among candidates.
        if (today - latest_end).days > _TTM_RECENCY_DAYS:
            continue
        if not _validate_ttm_periods(getattr(metric, "periods", None)):
            continue
        # Strict ``>`` (not ``>=``) keeps the FIRST concept seen at a given
        # period_end. With totals ranked ahead of the ASC-606 subset in
        # _TTM_REVENUE_CONCEPTS, a same-period tie resolves to the total (MET's
        # Revenues over the contract-revenue subset) — do NOT relax to ``>=``.
        if best_end is None or latest_end > best_end:
            best = {
                "concept": getattr(metric, "concept", ""),
                "value": float(getattr(metric, "value", 0) or 0),
                "periods": _ttm_periods_as_str(getattr(metric, "periods", None)),
                "period_end": latest_end,
                "has_calculated_q4": bool(getattr(metric, "has_calculated_q4", False)),
                "warning": getattr(metric, "warning", None),
            }
            best_end = latest_end
    return best


# ---------------------------------------------------------------------------
# Point-in-time / annual fact selection WITH concept recovery (BUG-009)
# ---------------------------------------------------------------------------
#
# edgartools' ``get_revenue()`` / ``get_net_income()`` / … return a bare float
# and DISCARD which concept matched. We previously hardcoded the concept label
# in the artifact snapshot ("us-gaap:Revenues"), but the number actually comes
# from whichever variant in the getter's priority list had a fact — for AAPL/
# MSFT/GOOGL that is ``RevenueFromContractWithCustomerExcludingAssessedTax``,
# not ``Revenues``. Injecting the wrong concept to the LLM as an authoritative
# SEC tag is provenance falsification. ``get_revenue_detailed()`` returns a
# ``UnitResult`` that ALSO drops the concept, so we instead replicate the
# getter's selection over ``FinancialFact`` objects (whose ``.concept`` IS the
# real matched tag) using the public ``get_annual_fact`` / ``get_fact`` API,
# exactly as ``_get_standardized_concept_value`` does internally.


def _select_latest_fact(
    facts: Any,
    concepts: tuple[str, ...],
    *,
    annual: bool,
    prefer_recent: bool = False,
    warnings: list[str] | None = None,
) -> dict[str, Any] | None:
    """Recover the matched ``FinancialFact`` for a point-in-time concept.

    Walks ``concepts`` in priority order, trying each taxonomy-prefixed variant
    (``us-gaap:`` / ``ifrs-full:``) and — when ``annual`` — preferring the FY
    fact (``get_annual_fact``) before falling back to the most recent point
    (``get_fact``), mirroring edgartools' ``_get_standardized_concept_value``.
    Returns ``{"concept", "value", "period_end", "units"}`` aligned to
    ``XBRLFact`` (concept/period_end/units required), or None when no concept
    matches.

    ``prefer_recent`` selects among ALL matching concepts by latest period_end,
    tie-broken by concept rank (earlier in ``concepts`` wins). This is required
    for revenue, where a financial issuer reports both total ``Revenues`` and the
    ASC-606 contract-revenue subset at the SAME period_end: first-match latched
    the subset (MET 31× understated). With totals ranked first (see
    ``_LATEST_REVENUE_CONCEPTS``), a same-period tie resolves to the total while a
    newer concept still wins across periods (AAPL's live revenue is ASC-606 only,
    its ``Revenues`` froze at FY2018). Default False keeps first-match for the
    unambiguous concepts (net income / gross profit / balance sheet) — no
    subset/total split there, and recency-first is unvalidated for them.

    BUG-037: a fact whose ``unit`` is a non-USD currency (a 20-F foreign private
    issuer's native EUR/GBP/CHF/JPY) is rejected — edgartools applies no FX, so
    surfacing the native magnitude as USD would corrupt the artifact snapshot and
    any downstream comparison. We skip such a variant and record a warning;
    suppression (→ FMP fallback) is the boundary-consistent choice (FX lives in
    ``normalize_peer_to_usd``, not here).
    """
    get_annual = getattr(facts, "get_annual_fact", None)
    get_fact = getattr(facts, "get_fact", None)
    if not callable(get_fact):
        return None
    # Probing taxonomy-prefix variants means most lookups intentionally miss
    # (bare ``GrossProfit`` before ``us-gaap:GrossProfit``). edgartools' getters
    # emit a UserWarning per miss; its own ``_get_standardized_concept_value``
    # silences them via the same ``_suppress_warnings`` flag during synonym
    # resolution. We do the same so a normal multi-variant walk isn't log spam.
    prev_suppress = getattr(facts, "_suppress_warnings", False)
    facts._suppress_warnings = True
    # prefer_recent collects the best candidate (latest period_end, then lowest
    # concept rank) across all concepts instead of returning the first match.
    best: dict[str, Any] | None = None
    best_pe: date | None = None
    best_rank = len(concepts)
    try:
        for rank, concept in enumerate(concepts):
            for variant in (concept, f"us-gaap:{concept}", f"ifrs-full:{concept}"):
                fact = None
                try:
                    if annual and callable(get_annual):
                        fact = get_annual(variant)
                    if fact is None:
                        fact = get_fact(variant)
                except _ADAPTER_CATCH:
                    continue
                if fact is None:
                    continue
                numeric = getattr(fact, "numeric_value", None)
                period_end = getattr(fact, "period_end", None)
                if isinstance(period_end, datetime):
                    period_end = period_end.date()
                if numeric is None or not isinstance(period_end, date):
                    continue
                unit = getattr(fact, "unit", "USD")
                if not _is_usd_unit(unit):
                    if warnings is not None:
                        warnings.append(
                            f"SEC XBRL fact {getattr(fact, 'concept', variant)} reported in "
                            f"{unit}, not USD; suppressed (no FX in provider)."
                        )
                    continue
                result = {
                    "concept": str(getattr(fact, "concept", variant)),
                    "value": float(numeric),
                    "period_end": period_end,
                    "units": str(unit or "USD"),
                }
                if not prefer_recent:
                    return result
                if (
                    best_pe is None
                    or period_end > best_pe
                    or (period_end == best_pe and rank < best_rank)
                ):
                    best, best_pe, best_rank = result, period_end, rank
    finally:
        facts._suppress_warnings = prev_suppress
    return best


# SEC Form 4 XML lets date fields (exerciseDate / expirationDate on
# derivative rows) be replaced by a footnote reference like "[F4]" — the
# date is described in footnote F4 rather than given as a literal date
# (typical for option grants with conditional vesting). edgartools'
# value_with_footnotes() surfaces these as strings in five real shapes:
#   1. plain ISO date     "2025-04-15"
#   2. footnote only      "[F4]"        — single or multi:  "[F1,F2]"
#   3. date + footnote    "2025-04-15 [F4]"
#   4. empty              ""
#   5. free-form filer text e.g. "See footnote", "N/A"
# Only shape 1 is a real date; everything else collapses to None at the
# provider boundary. The footnote semantics are already preserved on
# the same row in footnote_ids / footnotes_text, so dropping the date
# stand-in loses no information.
# DEF 14A proxies are long (TSLA 2025 = ~500k chars across 200+ pages).
# A flat head-cap leaves the Summary Compensation Table — which lives
# after the governance overview and TOC — out of reach of ownership.py
# extractors. We keep the governance overview window (intro + risk
# disclosures) and splice in a second window anchored on the SCT
# heading; both are needed for the proxy compensation panel. Total
# payload is bounded at ~140k per ticker.
_PROXY_INTRO_CHARS = 50_000
# Wide enough to span BOTH the Summary Compensation Table AND the CEO
# pay-ratio disclosure that follows it. NVDA FY2026 (probe 2026-06-02):
# real SCT at char 243,910, pay-ratio "129:1" at ~283,000 — ~40k apart.
# A 40k window anchored on the table missed the ratio entirely.
_PROXY_SCT_WINDOW_CHARS = 90_000
_PROXY_INTRO_SCT_GAP_MARKER = "\n\n--- [SCT WINDOW] ---\n\n"


def _slice_proxy_text(full_text: str) -> str:
    """Return up-to-140k window: first 50k (governance) + 90k around the SCT.

    Compensation regex extractors (Summary Compensation Table parser,
    CEO pay ratio extractor) need the SCT section, which for large issuers
    sits 200k+ chars into the full filing. Naïvely capping at 50k loses the
    entire compensation discussion.

    Anchoring is the subtle part: a proxy mentions "Summary Compensation
    Table" many times (TOC, Pay-Versus-Performance cross-references) BEFORE
    the actual table. NVDA FY2026 had 20 such mentions; the real table is
    marked by its column header "Name and Principal Position", which appears
    exactly once. We anchor there; only if that's absent do we fall back to
    an SCT heading that is actually followed by tabular data.
    """
    if not full_text:
        return ""
    intro = full_text[:_PROXY_INTRO_CHARS]
    if len(full_text) <= _PROXY_INTRO_CHARS:
        return intro

    anchor: int | None = None

    # Primary: the SCT column header — unambiguous marker of the real table.
    # Take the FIRST occurrence PAST the intro: large proxies (JPM) repeat the
    # header in a compensation-overview section inside the intro window, while
    # the real Summary Compensation Table sits much deeper.
    nap_first: int | None = None
    for nap_m in re.finditer(r"Name and Principal Position", full_text, re.I):
        if nap_first is None:
            nap_first = nap_m.start()
        if nap_m.start() >= _PROXY_INTRO_CHARS:
            anchor = nap_m.start()
            break

    # Fallback: an SCT heading past the intro that is followed within ~1.5k
    # chars by a data row (a 4-digit year next to a comma-grouped number) —
    # skips TOC entries and prose cross-references.
    if anchor is None:
        for m in re.finditer(r"Summary Compensation Table", full_text, re.I):
            if m.start() < _PROXY_INTRO_CHARS:
                continue
            tail = full_text[m.start() : m.start() + 1500]
            if re.search(r"20\d{2}\s+[0-9]{1,3}(?:,[0-9]{3})+", tail):
                anchor = m.start()
                break

    if anchor is None:
        # Last resort: keep a NAP match even if it fell inside the intro, or
        # bail to intro-only rather than drag a useless tail.
        if nap_first is not None:
            anchor = nap_first
        else:
            return intro

    # Start slightly before the anchor so the "Summary Compensation Table"
    # heading itself (sits just above the column header) is in the window for
    # the downstream table parser.
    start = max(_PROXY_INTRO_CHARS, anchor - 1_200)
    sct_window = full_text[start : start + _PROXY_SCT_WINDOW_CHARS]
    result = intro + _PROXY_INTRO_SCT_GAP_MARKER + sct_window

    # Also capture the Item 402(u) CEO-comp disclosure prose — it states the
    # CEO's actual total compensation in words ("...total compensation of our
    # CEO was $96,496,790") and is the most reliable cross-issuer source, but
    # can sit OUTSIDE the SCT window (MSFT puts it well after the table). Anchor
    # specifically on the CEO-comp sentence (NOT a bare "pay ratio" mention,
    # which often appears inside the SCT window first and would suppress this).
    sct_lo, sct_hi = start, start + _PROXY_SCT_WINDOW_CHARS
    for dm in re.finditer(
        r"total compensation of (?:our |the )?(?:CEO|chief executive officer)"
        r"|(?:CEO|chief executive officer)['’s]{0,2}\s+"
        r"(?:annual\s+|fiscal\s+\d{4}\s+)*total compensation",
        full_text,
        re.I,
    ):
        if not (sct_lo <= dm.start() <= sct_hi):
            lo = max(0, dm.start() - 2_000)
            result += _PROXY_INTRO_SCT_GAP_MARKER + full_text[lo : dm.start() + 6_000]
            break
    return result


# ---------------------------------------------------------------------------
# Schedule 13D/13G parsing helpers (module-level; edgartools has no parser)
# ---------------------------------------------------------------------------

_ISSUER_SUFFIXES: frozenset[str] = frozenset(
    {
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "co",
        "company",
        "ltd",
        "limited",
        "plc",
        "holdings",
        "holding",
        "group",
        "lp",
        "llc",
        "the",
    }
)


def build_rag_chunks(sections: list[dict[str, Any]], filing_date: Any) -> list[dict[str, Any]]:
    """Chunk each 10-K section separately into JSON-serializable chunk dicts.

    Every chunk's ``source`` carries its section title — e.g.
    ``"10-K/2025-10-31 · Item 1A — Risk Factors"`` — which is what ``run_qa``
    cites. The old path merged all sections into one blob, chunked it with a bare
    ``"10-K/<date>"`` source, and let risk chunks straddle section boundaries; the
    section label was then guesswork. ``chunk_index`` is re-numbered globally so
    it stays unique across sections. Whitespace-only sections are skipped.
    """
    from dataclasses import asdict

    from finrobot.engine.primitives.rag import chunk_text

    out: list[dict[str, Any]] = []
    for s in sections:
        text = str(s.get("text") or "")
        if not text.strip():
            continue
        source = f"10-K/{filing_date} · {s['title']}"
        for chunk in chunk_text(text, chunk_size=300, overlap=30, source=source):
            d = asdict(chunk)
            d["chunk_index"] = len(out)  # global, sequential, unique across sections
            out.append(d)
    return out


def _issuer_token(value: str | None) -> str:
    """Stable comparison key for issuer/filer names (strips legal suffixes)."""
    if not value:
        return ""
    tokens = re.findall(r"[a-z0-9]+", value.lower())
    filtered = [t for t in tokens if t not in _ISSUER_SUFFIXES]
    return " ".join(filtered or tokens)


def _schedule13_filer(f: Any) -> tuple[str, str | None]:
    """Return ``(filer_name, filer_cik)`` from a 13D/13G filing's SGML header."""
    header = f.header
    filers = getattr(header, "filers", None) or []
    if not filers:
        return "", None
    ci = getattr(filers[0], "company_information", None)
    if ci is None:
        return "", None
    name = str(getattr(ci, "name", "") or "").strip()
    cik_raw = getattr(ci, "cik", None)
    cik = str(cik_raw).strip() if cik_raw else None
    return name, cik


# Row-9 of the 13D/13G cover-page table: the ONLY authoritative beneficial-
# ownership figure. Anchored on "Aggregat(e|ed) Amount Beneficially Owned" — the
# "Aggregate" qualifier is what distinguishes Row 9 from the Rows 5-8 voting /
# dispositive SUBTOTALS, which the bare "Amount Beneficially Owned" first-match
# used to bind by accident (a Row-7 SOLE VOTING subtotal can sit physically
# adjacent to the table's left-margin "...Beneficially Owned..." caption).
# "Aggregated" (with a D) is a real filer spelling variant (Warner Bros 13G/A).
_SCHED13_AGG_LABEL = re.compile(
    r"Aggregat(?:e|ed)\s+Amount\s+Beneficially\s+Owned",
    re.I,
)
# Cover-page row keywords that bound Row-9's cell. A vertical-label table layout
# renders Row 9 with NO inline number (the value sits in a stripped column), so
# the next ≥4-digit token after the label is Row 10/11/12 prose or — worse — the
# CUSIP. Cutting the search slice at the next row keyword stops Tier-1 from
# binding the CUSIP (e.g. Apple 037833100) as a share count.
_SCHED13_ROW_BOUNDARY = re.compile(
    r"\b(?:CHECK\s+(?:BOX|IF)|PERCENT\s+OF\s+CLASS|TYPE\s+OF\s+REPORTING"
    r"|SOLE\s+VOTING|SHARED\s+VOTING|SOLE\s+DISPOSITIVE|SHARED\s+DISPOSITIVE"
    r"|ROW\s*\(?\s*\d)",
    re.I,
)
# Item 4(a) prose form: paper-style 13G (e.g. FMR LLC) with no cover-page table
# states the aggregate inline — "Amount beneficially owned: N". Also the body
# fallback for vertical-label tables whose cover Row 9 carries no inline number.
_SCHED13_ITEM4A = re.compile(
    r"Amount\s+beneficially\s+owned\s*[:\-]?\s*([0-9][0-9,]{3,})",
    re.I,
)
_SCHED13_NUMBER = re.compile(r"([0-9][0-9,]{3,})")


def _schedule13_shares(text: str) -> int | None:
    """Parse the Row-9 *aggregate* beneficial ownership from a 13D/13G cover page.

    The cover-page table's authoritative figure is Row 9 "Aggregate Amount
    Beneficially Owned by Each Reporting Person" — NOT the Rows 5-8 voting /
    dispositive subtotals. We anchor on the Row-9 label and read the first
    ≥4-digit number in its cell (bounded by the next row keyword so a
    label-without-inline-number layout can't bleed into the CUSIP). When no
    cover-page table is present we fall back to the Item 4(a) prose form.

    Requires ≥4 digits so a cover-page item number ("Item 4") can't match.
    Returns None when the aggregate genuinely can't be located — the caller
    must NOT fabricate a 0, and we must never bind a Rows 5-8 subtotal or a
    CUSIP in its place.
    """
    if not text:
        return None
    # Tier 1 (structured): the Row-9 aggregate cell of the cover-page table.
    for label in _SCHED13_AGG_LABEL.finditer(text):
        window = text[label.end() : label.end() + 200]
        boundary = _SCHED13_ROW_BOUNDARY.search(window)
        if boundary is not None:
            window = window[: boundary.start()]
        num = _SCHED13_NUMBER.search(window)
        if num is not None:
            try:
                return int(num.group(1).replace(",", ""))
            except ValueError:
                pass
    # Tier 2 (prose): Item 4(a) aggregate for paper-style filings with no table.
    prose = _SCHED13_ITEM4A.search(text)
    if prose is not None:
        try:
            return int(prose.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def _schedule13_pct(text: str) -> float | None:
    """Parse "Percent of Class: X%" from a 13D/13G cover page (0..100)."""
    if not text:
        return None
    m = re.search(
        r"Percent\s+of\s+Class[^0-9]{0,40}([0-9]+(?:\.[0-9]+)?)\s*%",
        text,
        re.I,
    )
    if m is None:
        return None
    try:
        val = float(m.group(1))
    except ValueError:
        return None
    return val if 0.0 <= val <= 100.0 else None


def _coerce_form4_date(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # Strip a trailing "[F...]" footnote suffix (shape 3) before validating.
    head = re.sub(r"\s*\[F[\dF,\s]+\]\s*$", "", s).strip()
    if not head:
        return None
    try:
        date.fromisoformat(head[:10])
    except ValueError:
        return None
    return head[:10]


def _opt_float(value: Any) -> float | None:
    """Parse a numeric to float; None/empty/unparseable → None (missing data).

    Preserves an explicit 0.0 — only genuinely absent values collapse to None,
    so a parse gap never reads downstream as a real 0 (e.g. a Form 4 leg with no
    reported share count is None, not a nonsensical 0-share transaction).
    """
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _form4_value(raw_value: Any, price: float | None) -> float | None:
    """Dollar value of one Form-4 leg, abstaining to None when it is unknown.

    edgartools' ``TransactionActivity.value`` is NOT a faithful "missing→None"
    field: ``get_transaction_activities`` computes ``shares * price`` only when a
    usable price exists and otherwise hard-codes ``else 0`` (ownershipforms.py
    market line 1840 / non-market 1876 / derivative 1899). So a footnoted or
    absent price — routine for option exercises (code M), gifts (G), tax
    withholding (F), forfeitures (D) — surfaces as a fabricated ``value=0``, NOT
    None. Passing that through reads downstream as "this insider moved $0 of
    stock", which is false: the leg's dollar value is simply not computable from
    a reported price. None ≠ 0 (CLAUDE.md invariant): an uncomputable value must
    abstain to None.

    Rule: edgartools only ever yields a value from ``shares * price`` (strictly
    positive for the real legs it computes) or the no-price sentinel ``0``. So a
    value of exactly 0 with no usable price backing it is the sentinel → None. A
    genuinely measured value is positive and passes through. (A real $0-priced
    trade does not exist in Form-4 data; a $0 *consideration* forfeit/gift is a
    no-price leg, correctly None here — its share count still carries the event.)
    """
    parsed = _opt_float(raw_value)
    if parsed is None:
        return None
    if parsed == 0 and (price is None or price == 0):
        # No usable price backs this 0 → it is edgartools' sentinel, not a
        # measured zero. Abstain rather than fabricate "$0 of value moved".
        return None
    return parsed


# ---------------------------------------------------------------------------
# SEC XBRL companyfacts — DEEP annual financials history (≥9 fiscal years)
#
# FMP / yfinance only field ~4 years of annual statements, which truncates the
# through-cycle window a commodity-cyclical's DCF normalization needs (the MU
# peak FY2018 + the FY2018-22 downturn fall off-window, so the trailing median
# misprices — script _cyclical_probe_sec.py proved the spread). SEC companyfacts
# carries the full filed history with no API key. This is the SAME extraction the
# probe validated; it emits the canonical per-year ``yearly_data`` dict shape both
# other providers emit, so the provider-agnostic historical_extractor consumes it
# unchanged.
# ---------------------------------------------------------------------------

# us-gaap concept candidate lists for the annual flow series, in priority order
# (first concept that yields data wins). Mirrors _cyclical_probe_sec.py.
# Totals first, ASC-606 subset last — see _TTM_REVENUE_CONCEPTS (2026-06-29).
# Paired with prefer_total_across_concepts=True at the call site: a higher-priority
# (total) concept owns each fiscal year it reports; the ASC-606 subset only fills
# years the totals lack (AAPL pre-FY2019 Revenues + post-FY2019 ASC-606 → one
# consistent total series), instead of the old "first concept with data wins" that
# latched the insurer/bank subset for every year.
_HIST_REVENUE_CONCEPTS: tuple[str, ...] = (
    "Revenues",
    "SalesRevenueNet",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
)
_HIST_GROSS_PROFIT_CONCEPTS: tuple[str, ...] = ("GrossProfit",)
_HIST_OPERATING_INCOME_CONCEPTS: tuple[str, ...] = ("OperatingIncomeLoss",)
_HIST_NET_INCOME_CONCEPTS: tuple[str, ...] = ("NetIncomeLoss", "ProfitLoss")
_HIST_EPS_CONCEPTS: tuple[str, ...] = ("EarningsPerShareBasic", "EarningsPerShareBasicAndDiluted")
_HIST_DA_CONCEPTS: tuple[str, ...] = (
    "DepreciationDepletionAndAmortization",
    "DepreciationAmortizationAndAccretionNet",
    "DepreciationAndAmortization",
    "DepreciationAmortizationAndDepletionNet",
)
_HIST_CAPEX_CONCEPTS: tuple[str, ...] = (
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
)
_HIST_OCF_CONCEPTS: tuple[str, ...] = (
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
)
_HIST_ICF_CONCEPTS: tuple[str, ...] = (
    "NetCashProvidedByUsedInInvestingActivities",
    "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations",
)
_HIST_FCF_CONCEPTS: tuple[str, ...] = (
    "NetCashProvidedByUsedInFinancingActivities",
    "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations",
)
_HIST_SGA_CONCEPTS: tuple[str, ...] = (
    "SellingGeneralAndAdministrativeExpense",
    "GeneralAndAdministrativeExpense",
)
# Minimum full-year duration (days) for a fact to count as an ANNUAL flow rather
# than a quarter / half-year frame.
_ANNUAL_MIN_DURATION_DAYS = 300


def _companyfacts_annual_series(
    facts: dict[str, Any],
    concepts: tuple[str, ...],
    *,
    prefer_total_across_concepts: bool = False,
) -> dict[int, float]:
    """Annual (10-K, full-year) values keyed by TRUE fiscal year (period-end year).

    ⚠ KEY-BY-PERIOD-END, NOT THE ``fy`` FIELD (the fy-bug the probe fixed): the
    SEC XBRL ``fy`` field is the fiscal year of the *FILING*, not of the data
    period. A 10-K restates 2-3 prior years as comparatives and tags every one of
    them with the FILING's ``fy``, so MU's $30.39B FY2018 peak appears tagged
    fy=2019/2020 too — keying by ``fy`` shifts the labels off by ~2 years and
    produces impossible labels (STX "FY2027"). The true fiscal year = calendar
    year of the period END. Latest-filed value per fiscal year wins (a later 10-K's
    restated comparative supersedes the original).

    USD units only, form 10-K/10-K-A, fp=FY, duration ≥ ~1 year.
    """
    usgaap = facts.get("facts", {}).get("us-gaap", {})
    # period_end_year -> (concept_rank, filed, val). A lower concept rank (earlier
    # in ``concepts``) owns the fiscal year; within the same concept, latest-filed
    # wins (restatement). prefer_total_across_concepts keeps scanning every concept
    # so a lower-priority one only fills years the higher-priority concepts don't
    # report (revenue: total Revenues for the years it covers, ASC-606 subset only
    # for the post-transition years totals are missing).
    out: dict[int, tuple[int, str, float]] = {}
    for rank, concept in enumerate(concepts):
        node = usgaap.get(concept)
        if not node:
            continue
        for unit_key, items in node.get("units", {}).items():
            if "USD" not in unit_key:
                continue
            for it in items:
                if it.get("form") not in ("10-K", "10-K/A"):
                    continue
                if it.get("fp") != "FY":
                    continue
                start, end, val = it.get("start"), it.get("end"), it.get("val")
                if val is None or start is None or end is None:
                    continue
                try:
                    d0 = date.fromisoformat(start)
                    d1 = date.fromisoformat(end)
                except ValueError:
                    continue
                if (d1 - d0).days < _ANNUAL_MIN_DURATION_DAYS:
                    continue
                fy = d1.year  # TRUE fiscal year = period-end calendar year
                filed = it.get("filed", "")
                prev = out.get(fy)
                if prev is None:
                    out[fy] = (rank, filed, float(val))
                elif rank == prev[0] and filed > prev[1]:
                    # same concept, later filing — restatement supersedes
                    out[fy] = (rank, filed, float(val))
                # else: a higher-priority concept already owns this fiscal year
                # (concepts iterate in ascending rank) or this is an older filing.
        if out and not prefer_total_across_concepts:
            break  # legacy: first concept that yields data wins
    return {fy: v for fy, (_, _, v) in out.items()}


def _companyfacts_point_series(
    facts: dict[str, Any], concepts: tuple[str, ...]
) -> dict[int, float]:
    """Per-fiscal-year POINT-IN-TIME (instant) values keyed by period-end year.

    For balance-sheet / per-share instants (EPS is a duration flow but reported
    once per FY at the annual frame; this also serves any instant concept). Picks
    the 10-K FY fact whose period end falls in each calendar year, latest-filed
    wins. Unlike :func:`_companyfacts_annual_series` it does NOT require a year
    duration (instants have start==end or no start).
    """
    usgaap = facts.get("facts", {}).get("us-gaap", {})
    out: dict[int, tuple[str, float]] = {}
    for concept in concepts:
        node = usgaap.get(concept)
        if not node:
            continue
        for unit_key, items in node.get("units", {}).items():
            for it in items:
                if it.get("form") not in ("10-K", "10-K/A"):
                    continue
                if it.get("fp") != "FY":
                    continue
                end, val = it.get("end"), it.get("val")
                if val is None or end is None:
                    continue
                # Duration EPS: keep only the full-year frame (skip quarters).
                start = it.get("start")
                if start is not None:
                    try:
                        if (date.fromisoformat(end) - date.fromisoformat(start)).days < (
                            _ANNUAL_MIN_DURATION_DAYS
                        ):
                            continue
                    except ValueError:
                        continue
                try:
                    fy = date.fromisoformat(end).year
                except ValueError:
                    continue
                filed = it.get("filed", "")
                prev = out.get(fy)
                if prev is None or filed > prev[0]:
                    out[fy] = (filed, float(val))
        if out:
            break
    return {fy: v for fy, (_, v) in out.items()}


def _build_sec_yearly_financials(facts: dict[str, Any], max_years: int) -> list[dict[str, Any]]:
    """Assemble newest-first per-year normalized dicts from SEC companyfacts.

    Output shape is identical to ``fmp._build_single_year_data`` /
    ``yfinance._build_yearly_financials`` (the keys ``historical_extractor.
    _build_from_yearly`` reads), so the consumer is provider-agnostic. Emits None
    for a missing cell — the extractor owns the None→0.0 fill and revenue-NaN-year
    filtering. CapEx is reported by SEC as a positive outflow magnitude already
    (PaymentsToAcquire…), matching the FCF "+ D&A − CapEx" positive convention.
    All figures are native USD (SEC domestic filers report USD; the deep-history
    path is gated to US issuers).
    """
    rev = _companyfacts_annual_series(
        facts, _HIST_REVENUE_CONCEPTS, prefer_total_across_concepts=True
    )
    gp = _companyfacts_annual_series(facts, _HIST_GROSS_PROFIT_CONCEPTS)
    oi = _companyfacts_annual_series(facts, _HIST_OPERATING_INCOME_CONCEPTS)
    ni = _companyfacts_annual_series(facts, _HIST_NET_INCOME_CONCEPTS)
    da = _companyfacts_annual_series(facts, _HIST_DA_CONCEPTS)
    capex = _companyfacts_annual_series(facts, _HIST_CAPEX_CONCEPTS)
    ocf = _companyfacts_annual_series(facts, _HIST_OCF_CONCEPTS)
    icf = _companyfacts_annual_series(facts, _HIST_ICF_CONCEPTS)
    fcf = _companyfacts_annual_series(facts, _HIST_FCF_CONCEPTS)
    sga = _companyfacts_annual_series(facts, _HIST_SGA_CONCEPTS)
    eps = _companyfacts_point_series(facts, _HIST_EPS_CONCEPTS)

    years_desc = sorted(rev.keys(), reverse=True)[:max_years]
    yearly: list[dict[str, Any]] = []
    for y in years_desc:
        r = rev.get(y)
        g = gp.get(y)
        o = oi.get(y)
        d = da.get(y)
        # EBITDA via the textbook identity EBITDA = EBIT + D&A. SEC companyfacts has
        # no standalone EBITDA concept, but operating income (EBIT) and D&A are BOTH
        # filed line items, so this is a faithful reconstruction, not a fabrication.
        # Required because the through-cycle DCF anchors on the EBITDA margin: without
        # it the SEC-sourced cyclical falls back to the industry EBITDA aggregate
        # (MU 36.8% vs the real through-cycle 50.7% = op 26.1% + D&A 24.5%), which
        # collapses the implied price (~$28 vs the validated ~$163). None when either
        # component is missing — never a fabricated 0.
        ebitda = (o + d) if (o is not None and d is not None) else None
        yearly.append(
            {
                # period-end fiscal-year string; the extractor's _year_of reads
                # the leading 4 digits, so a bare year is sufficient and unambiguous.
                "fiscal_year": f"{y}-12-31" if y else None,
                "revenue": r,
                "gross_profit": g,
                "operating_income": o,
                "ebitda": ebitda,
                "net_income": ni.get(y),
                "eps": eps.get(y),
                "sga_expense": sga.get(y),
                "gross_margin": (g / r if (g is not None and r) else None),
                "operating_margin": (o / r if (o is not None and r) else None),
                "operating_cash_flow": ocf.get(y),
                "investing_cash_flow": icf.get(y),
                "financing_cash_flow": fcf.get(y),
                "depreciation_amortization": da.get(y),
                "capital_expenditure": capex.get(y),
                # SEC has no single ΔNWC concept; the DCF FCF uses OCF directly when
                # ΔNWC is absent, and the extractor zero-fills it (treated as
                # "missing" by dcf_seed's median, not a real 0).
                "change_in_working_capital": None,
                # Native-currency tags: SEC domestic filers report USD, and the
                # deep-history augmentation is gated to US issuers, so both tags are
                # USD → the extractor's FX step is a no-op.
                "financial_currency": "USD",
                "quote_currency": "USD",
            }
        )
    return yearly


# ---------------------------------------------------------------------------
# Reportable-segment extraction (SOTP floor — Batch 3B v1; light company-
# overview augmentation — BACKLOG A4, 2026-07-09)
# ---------------------------------------------------------------------------
#
# ASC 280 reportable-segment revenue + a profitability metric from the ORIGINAL
# 10-K (``amendments=False`` — the latched .latest() pitfall: a 10-K/A's XBRL is
# incomplete and the dimensioned segment query comes back empty, §8#1).
#
# Two issuer SHAPES, probe-verified 2026-07-09 (TSLA vs MSFT 10-K XBRL):
#
#   · GROSS-PROFIT-anchored (TSLA-style): segment GROSS PROFIT is dimensioned on
#     ``us-gaap:StatementBusinessSegmentsAxis`` (members like
#     AutomotiveSegmentMember) while segment REVENUE is dimensioned on a
#     SEPARATE axis, ``srt:ProductOrServiceAxis`` (members like
#     AutomotiveRevenuesMember). They are matched by a normalized member key
#     (strip ticker prefix + Member/Segment/Revenues suffixes), NOT by label
#     string — label strings differ ("Automotive segment" vs "Automotive
#     Revenues"). The segment axis (gross profit) is authoritative for which
#     legs ARE reportable segments; revenue is attached only where a member
#     normalizes onto one.
#
#   · OPERATING-INCOME-anchored (MSFT-style): MSFT-type issuers report ZERO
#     dimensioned ``GrossProfit`` facts (no segment-level gross profit
#     disclosure at all) — instead ``OperatingIncomeLoss`` is dimensioned on
#     ``us-gaap:StatementBusinessSegmentsAxis``, AND segment revenue is ALSO
#     reported directly on that SAME axis (not on a separate ProductOrService
#     axis at the segment granularity — MSFT's ProductOrServiceAxis revenue is a
#     FINER product breakdown, e.g. "Windows"/"Gaming"/"LinkedIn", that does NOT
#     1:1 map onto the 3 reportable segments, so cross-axis joining it here
#     would silently attach the wrong child-product revenue onto a parent
#     segment). So the OI-anchor path queries revenue on the SAME axis as the
#     OI anchor and matches members directly — no cross-axis join needed or
#     safe. This is a FALLBACK used only when the GP-anchor path finds nothing,
#     so it never changes TSLA-style extraction (SOTP-consumed field stays
#     ``gross_profit``; MSFT-style segments carry ``operating_income`` instead,
#     ``gross_profit`` stays None — SOTP's ``seg.get("gross_profit")`` degrades
#     those legs cleanly, unchanged behavior).

# XBRL concepts (mirror the TTM/latest lists' first entries; segment dimensioning
# rides the same revenue concept post-ASC-606).
_SEG_REVENUE_CONCEPT = "RevenueFromContractWithCustomerExcludingAssessedTax"
_SEG_GROSS_PROFIT_CONCEPT = "GrossProfit"
# MSFT-type fallback anchor (probe-verified 2026-07-09: MSFT reports segment
# OperatingIncomeLoss, never segment GrossProfit — see module docstring above).
_SEG_OPERATING_INCOME_CONCEPT = "OperatingIncomeLoss"
_SEG_AXIS_TOKEN = "BusinessSegmentsAxis"
_SEG_PRODUCT_AXIS_TOKEN = "ProductOrServiceAxis"


def _normalize_segment_member(member: str | None) -> str | None:
    """Canonical join key from an XBRL dimension member URI/qname.

    ``tsla:AutomotiveSegmentMember`` → ``Automotive``;
    ``tsla:AutomotiveRevenuesMember`` → ``Automotive``;
    ``tsla:EnergyGenerationAndStorageSegmentMember`` → ``EnergyGenerationAndStorage``.
    Returns None for an empty member (never coerces to a bogus key — §T2).
    """
    if not member:
        return None
    m = member.split(":", 1)[-1]
    if m.endswith("Member"):
        m = m[: -len("Member")]
    if m.endswith("Segment"):
        m = m[: -len("Segment")]
    if m.endswith("Revenues"):
        m = m[: -len("Revenues")]
    return m or None


def _segment_period(facts: list[dict[str, Any]]) -> tuple[str, str] | None:
    """Pick the latest FULL-YEAR (period span ≥ ~350d) period among segment facts.

    Quarter facts also carry the segment axis; the SOTP floor wants the annual
    figure, so prefer the longest span tied to the latest period_end.
    """
    from datetime import date as _date

    spans: dict[tuple[str, str], int] = {}
    for x in facts:
        ps, pe = x.get("period_start"), x.get("period_end")
        if not ps or not pe:
            continue
        try:
            days = (_date.fromisoformat(pe) - _date.fromisoformat(ps)).days
        except ValueError:
            continue
        spans[(ps, pe)] = days
    full_year = {p: d for p, d in spans.items() if d >= 350}
    pool = full_year or spans
    if not pool:
        return None
    # latest period_end, then longest span
    return max(pool, key=lambda p: (p[1], spans[p]))


def extract_segment_facts(xbrl: Any) -> tuple[dict[str, Any], list[str]]:
    """Reportable-segment revenue + a profitability metric from a parsed 10-K XBRL.

    Returns a ``{"segments": {canonical: {revenue, gross_profit, operating_income,
    label}}, "period", "currency", "primary_metric"}`` dict and a warnings list.
    Missing metrics stay None — never 0 (§T2#4). Pure given the parsed ``xbrl``
    object (the network fetch is the caller's). Raises nothing: a no-segment
    filing yields an empty segments dict + a warning, so a single-segment issuer
    degrades cleanly (SOTP gating drops it; the light company-overview path
    degrades to the FMP fallback or, if that's also empty, drops the panel).

    Anchor priority (module docstring has the full probe evidence):
      1. GrossProfit on the business-segment axis (TSLA-style) — authoritative
         for which legs ARE reportable segments; ``gross_profit`` populated,
         ``operating_income`` stays None. Revenue is attached via a SEPARATE
         ProductOrServiceAxis member normalizing onto the GP-defined key.
      2. OperatingIncomeLoss on the SAME axis (MSFT-style fallback, used only
         when (1) finds nothing) — ``operating_income`` populated,
         ``gross_profit`` stays None. Revenue is queried on the SAME axis and
         matched by member directly (no cross-axis join — see module docstring
         for why joining MSFT's finer ProductOrServiceAxis breakdown here would
         be wrong).
    Neither anchor found (a genuinely single-segment issuer, or non-dimensioned
    XBRL) → empty segments + warning, ``primary_metric`` absent.
    """
    warnings: list[str] = []

    def _seg_facts(concept: str, axis_token: str) -> list[dict[str, Any]]:
        # The whole body (query + row iteration) is guarded: edgartools' query
        # shape varies per filing — .execute() AND the row .get() access have both
        # been observed to raise AttributeError on issuers whose XBRL doesn't
        # expose the assumed structure (KO 2026-02-20 10-K, live). A segment-query
        # miss is a BENIGN, expected outcome for the light company-overview path
        # (most issuers won't match the queried shape), so it degrades to "no
        # segments" — NEVER a reader-facing error string in the artifact Disclaimer.
        # Logged (app log, debuggable) instead, so an unexpected shape stays
        # visible to us without alarming an analyst.
        try:
            rows = xbrl.query().by_concept(concept).execute()
            out = []
            for x in rows:
                if not x.get("is_dimensioned"):
                    continue
                dim = x.get("dimension") or ""
                if axis_token not in dim:
                    continue
                out.append(x)
            return out
        except _ADAPTER_CATCH as e:
            logger.warning(
                "segment query for concept %s on axis %s degraded (no facts): %s",
                concept,
                axis_token,
                type(e).__name__,
            )
            return []

    gp_facts = _seg_facts(_SEG_GROSS_PROFIT_CONCEPT, _SEG_AXIS_TOKEN)
    primary_metric = "gross_profit"
    anchor_facts = gp_facts
    if not anchor_facts:
        # MSFT-type issuers report segment OPERATING INCOME, never segment gross
        # profit — fall back to the same business-segment axis, different concept.
        oi_facts = _seg_facts(_SEG_OPERATING_INCOME_CONCEPT, _SEG_AXIS_TOKEN)
        if oi_facts:
            primary_metric = "operating_income"
            anchor_facts = oi_facts

    if not anchor_facts:
        warnings.append(
            "no segment-axis gross-profit or operating-income facts (single-segment "
            "issuer or non-dimensioned XBRL); segment breakdown not derivable"
        )
        return {"segments": {}, "period": None, "currency": None}, warnings

    period = _segment_period(anchor_facts)
    if period is None:
        warnings.append("could not resolve a segment reporting period")
        return {"segments": {}, "period": None, "currency": None}, warnings

    # The anchor metric defines the reportable segments (authoritative leg).
    segments: dict[str, dict[str, Any]] = {}
    currency: str | None = None
    for x in anchor_facts:
        if (x.get("period_start"), x.get("period_end")) != period:
            continue
        key = _normalize_segment_member(x.get("member"))
        if key is None:
            continue
        currency = currency or _seg_unit_currency(x)
        segments[key] = {
            "label": x.get("dimension_member_label") or x.get("label") or key,
            "gross_profit": x.get("numeric_value") if primary_metric == "gross_profit" else None,
            "operating_income": (
                x.get("numeric_value") if primary_metric == "operating_income" else None
            ),
            "revenue": None,
        }

    if primary_metric == "gross_profit":
        # TSLA-style: revenue lives on a SEPARATE ProductOrServiceAxis, matched
        # onto the GP-defined segment keys by normalized member.
        rev_facts = _seg_facts(_SEG_REVENUE_CONCEPT, _SEG_PRODUCT_AXIS_TOKEN)
        rev_source = "ProductOrService"
    else:
        # MSFT-style: revenue is reported directly on the SAME business-segment
        # axis as operating income (see module docstring for why a cross-axis
        # join to ProductOrServiceAxis would be wrong here).
        rev_facts = _seg_facts(_SEG_REVENUE_CONCEPT, _SEG_AXIS_TOKEN)
        rev_source = "business-segment"
    for x in rev_facts:
        if (x.get("period_start"), x.get("period_end")) != period:
            continue
        key = _normalize_segment_member(x.get("member"))
        if key in segments and segments[key]["revenue"] is None:
            segments[key]["revenue"] = x.get("numeric_value")

    for key, seg in segments.items():
        if seg["revenue"] is None:
            warnings.append(f"segment {key!r}: no matching {rev_source} revenue member")

    return {
        "segments": segments,
        "period": {"start": period[0], "end": period[1]},
        "currency": currency,
        "primary_metric": primary_metric,
    }, warnings


def _seg_unit_currency(fact: dict[str, Any]) -> str | None:
    """Reporting currency from a fact's unit_ref (e.g. 'usd' → 'USD'). None if absent."""
    unit = fact.get("unit_ref")
    if not unit or not isinstance(unit, str):
        return None
    token = unit.split(":")[-1].split("_")[-1].upper()
    return token if len(token) == 3 and token.isalpha() else None


# SOX-302 CEO certification (Exhibit 31.1) attachment matcher.
#
# Section-302 certs are ALWAYS filed as two separate documents — the CEO's
# (Ex-31.1 / .01 / .A) and the CFO's (Ex-31.2 / .02 / .B). We must pick the
# CEO's and NEVER the CFO's (a wrong signer is worse than falling back). Issuer
# naming varies (probed 2026-07-09 across the mega-cap basket): KO/AAPL/MSFT/
# JPM/NVDA/XOM/AMZN/META = "EX-31.1"; GOOGL = "EX-31.01" (leading zero); DIS =
# "EX-31.A" with description "SECTION 302 CERTIFICATION OF CHIEF EXECUTIVE
# OFFICER". Section-906 certs (Ex-32.x) are EXCLUDED — an issuer may file a
# single COMBINED 906 cert signed by BOTH officers, so a name off that document
# is ambiguous.
_EX31_ATTACHMENT_RE = re.compile(r"^EX[-\s]?0*31(?:[.\-_ ]0*([0-9]+|[A-Za-z]))?$", re.I)


def _ceo_cert_attachment_rank(document_type: str, description: str, document: str) -> int | None:
    """Priority (lower = better) if the attachment is the CEO's Section-302 cert.

    ``None`` → not the CEO 302 cert (or it is the CFO's / a 906 cert). Only
    Exhibit-31 family documents qualify; sub-index .1/.A marks the CEO leg and
    .2/.B the CFO leg. An explicit description ("...CHIEF EXECUTIVE OFFICER" /
    "...CHIEF FINANCIAL OFFICER") is honoured over the numbering when present.
    """
    desc = (description or "").upper()
    dtype = (document_type or "").strip()
    doc = (document or "").lower()

    # Restrict to the Exhibit-31 (Section-302) family — by document_type, or by
    # filename when the type is blank/odd. 906 (Ex-32) never reaches here.
    m = _EX31_ATTACHMENT_RE.match(dtype)
    fam = re.search(r"ex[-_]?31[._]?0*([0-9a-z])?", doc) if m is None else None
    if m is None and fam is None:
        return None

    sub = m.group(1) if m else (fam.group(1) if fam else None)
    sub_is_first = sub_is_second = False
    if sub is None:
        sub_is_first = True  # bare "EX-31" — treat as the CEO leg (desc-guarded)
    elif sub.isdigit():
        sub_is_first, sub_is_second = int(sub) == 1, int(sub) == 2
    else:
        sub_is_first, sub_is_second = sub.upper() == "A", sub.upper() == "B"

    if "FINANCIAL OFFICER" in desc:
        return None  # CFO cert — reject outright
    desc_is_ceo = "EXECUTIVE OFFICER" in desc

    if sub_is_second and not desc_is_ceo:
        return None  # CFO leg (.2 / .B)
    if desc_is_ceo and sub_is_first:
        return 0
    if sub_is_first:
        return 2
    return None


class EdgarToolsProvider(DataProvider):
    """SEC EDGAR data provider backed by edgartools 5.31.

    Construct only after ``_is_valid_identity(user_agent)`` is True.
    ``build_data_layer`` enforces that contract; do not bypass it.
    """

    def __init__(self, user_agent: str) -> None:
        # Caller (build_data_layer) is responsible for identity gating.
        # We don't re-validate here — that would put the raise back where
        # we explicitly forbid it (spec v4 §5).
        if not _EDGAR_AVAILABLE:
            raise ImportError(
                "edgartools is not installed but EdgarToolsProvider was "
                "constructed. Check pyproject.toml + uv sync."
            )
        header_identity = _sec_header_identity(user_agent)
        if header_identity is None:
            raise ValueError("SEC EDGAR identity must include a contact email")
        set_identity(header_identity)
        self._user_agent = user_agent
        self._header_identity = header_identity

    @property
    def name(self) -> str:
        return "edgar_tools"

    def capabilities(self) -> list[str | DataType]:
        return list(_SUPPORTED)

    async def fetch(self, ticker: str, data_type: str | DataType, **kwargs: Any) -> DataResult:
        # edgartools 5.31 is sync-blocking; offload to thread so the asyncio
        # event loop stays responsive. nest-asyncio is installed transitively
        # and 门 1 实测 with uvicorn lifespan: 10/10 starts, 0 anomalies.
        try:
            data, warnings = await asyncio.to_thread(
                self._fetch_sync,
                ticker.upper(),
                data_type,
                kwargs,
            )
        except _ADAPTER_CATCH as e:
            raise _provider_error(f"edgartools {data_type} for {ticker}: {e}", e) from e
        return DataResult(
            data=data,
            provider=self.name,
            ticker=ticker.upper(),
            data_type=data_type,
            timestamp=datetime.now(tz=timezone.utc),
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Deep annual financials history (SEC XBRL companyfacts, no API key)
    # ------------------------------------------------------------------

    async def fetch_annual_financials(self, ticker: str, years: int) -> DataResult:
        """≥9 fiscal years of annual financials from SEC companyfacts.

        The deep-history source the through-cycle DCF normalization needs: FMP /
        yfinance only field ~4 annual periods, truncating a commodity-cyclical's
        peak→trough window. Returns a DataResult whose ``data["yearly_data"]`` is a
        newest-first list of canonical per-year dicts (same shape FMP / yfinance
        emit), so the provider-agnostic ``historical_extractor`` consumes it
        unchanged. Raises ``ProviderError`` on CIK-miss / SEC failure / empty facts
        so the caller can fall back to the normal provider chain — a deep-history
        gap must degrade to the shallow window, never crash the seed.

        Not on ``capabilities()``: this is an EXPLICIT augmentation route invoked
        by ``DataLayer.fetch_deep_history`` for cyclicals only. Leaving it off the
        capability list keeps the canonical FINANCIALS chain (and every
        non-cyclical historical fetch) byte-identical — SEC never silently displaces
        FMP/yfinance as the primary financials source.
        """
        cik = await asyncio.to_thread(self._resolve_cik, ticker.upper())
        if cik is None:
            raise ProviderError(f"SEC companyfacts: no CIK for {ticker}")
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
        try:
            async with httpx.AsyncClient(
                headers={
                    "User-Agent": self._header_identity,
                    "Accept-Encoding": "gzip, deflate",
                },
                timeout=30.0,
            ) as client:
                r = await client.get(url)
                r.raise_for_status()
                facts = r.json()
        except httpx.HTTPError as e:
            raise _provider_error(f"SEC companyfacts fetch for {ticker} (CIK {cik}): {e}", e) from e
        yearly = _build_sec_yearly_financials(facts, years)
        if not yearly:
            raise ProviderError(
                f"SEC companyfacts for {ticker} (CIK {cik}) yielded no annual revenue series"
            )
        return DataResult(
            data={"yearly_data": yearly},
            provider=self.name,
            ticker=ticker.upper(),
            data_type=DataType.FINANCIALS,
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def fetch_annual_segments(self, ticker: str) -> DataResult:
        """ASC 280 reportable-segment revenue + gross profit from the latest 10-K.

        The SOTP-floor source (Batch 3B v1): segment-level revenue AND gross profit
        from the ORIGINAL 10-K's XBRL (``amendments=False`` — a 10-K/A's XBRL is
        incomplete and the dimensioned segment query returns empty, §8#1). Returns
        a DataResult whose ``data`` is the ``extract_segment_facts`` dict
        (``{"segments": {...}, "period", "currency"}``). Raises ``ProviderError`` on
        CIK-miss / no-10-K / parse failure so ``DataLayer.fetch_segments`` degrades
        to None and the SOTP gate cleanly drops the name.

        NOT on ``capabilities()``: an EXPLICIT augmentation route (like
        ``fetch_annual_financials``) invoked only for option-value SOTP candidates,
        so SEC never silently displaces FMP/yfinance as the primary source.
        """
        data, warnings = await asyncio.to_thread(self._fetch_segments_sync, ticker.upper())
        return DataResult(
            data=data,
            provider=self.name,
            ticker=ticker.upper(),
            data_type=DataType.FILINGS_10K,
            timestamp=datetime.now(tz=timezone.utc),
            warnings=warnings,
        )

    def _fetch_segments_sync(self, ticker: str) -> tuple[dict[str, Any], list[str]]:
        try:
            c = Company(ticker)
        except _ADAPTER_CATCH as e:
            raise _provider_error(
                f"SEC segments: company lookup failed for {ticker}: {e}", e
            ) from e
        # ORIGINAL 10-K — a 10-K/A's XBRL is incomplete for dimensioned segments.
        filing = c.get_filings(form="10-K", amendments=False).latest(1)
        if isinstance(filing, list):
            filing = filing[0] if filing else None
        if filing is None:
            raise ProviderError(f"SEC segments: no original 10-K for {ticker}")
        try:
            xbrl = filing.xbrl()
        except _ADAPTER_CATCH as e:
            raise _provider_error(f"SEC segments: XBRL parse failed for {ticker}: {e}", e) from e
        if xbrl is None:
            raise ProviderError(f"SEC segments: 10-K has no XBRL for {ticker}")
        data, warnings = extract_segment_facts(xbrl)
        data["accession"] = getattr(filing, "accession_no", None)
        data["filing_date"] = str(getattr(filing, "filing_date", "") or "")
        data["source_concept"] = _SEG_GROSS_PROFIT_CONCEPT
        return data, warnings

    def _resolve_cik(self, ticker: str) -> int | None:
        """CIK for ``ticker`` via edgartools ``Company`` (sync, run in a thread).

        Returns None on any miss so the async caller maps it to a ProviderError
        and degrades to the shallow provider chain rather than crashing.
        """
        try:
            c = Company(ticker)
        except _ADAPTER_CATCH:
            return None
        cik_raw = getattr(c, "cik", None)
        if cik_raw is None or cik_raw == "":
            return None
        try:
            return int(cik_raw)
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _fetch_sync(
        self,
        ticker: str,
        data_type: str | DataType,
        kwargs: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        c = Company(ticker)
        if data_type in (DataType.FILINGS_10K, DataType.FILINGS, DataType.RAG_10K):
            return self._fetch_10k(c, want_rag=(data_type == DataType.RAG_10K))
        if data_type == DataType.FILINGS_10Q:
            return self._fetch_10q(c, n=kwargs.get("n", 4))
        if data_type == DataType.FILINGS_8K:
            return self._fetch_8k(c, n=kwargs.get("n", 10))
        if data_type == DataType.XBRL_FACTS:
            return self._fetch_xbrl(c)
        if data_type == DataType.INSIDER_TRADES:
            return self._fetch_insider(c, days=kwargs.get("days", 90))
        if data_type == DataType.INSTITUTIONAL_HOLDINGS:
            # 13F goes through the local cache — see sec_holdings_cache.
            return self._fetch_13f_sync(ticker, company_name=getattr(c, "name", None))
        if data_type == DataType.PROXY_STATEMENT:
            return self._fetch_proxy(c)
        if data_type == DataType.SCHEDULE_13:
            return self._fetch_schedule13(c, limit=kwargs.get("limit", 8))
        if data_type == DataType.CEO_CERTIFICATION:
            return self._fetch_ceo_certification(c)
        raise ProviderError(f"unreachable data_type: {data_type}")

    # ------------------------------------------------------------------
    # 10-K (Annual report)
    # ------------------------------------------------------------------

    # Mapping: (canonical_id, edgar TenK attr name, display title)
    _SECTION_ATTRS: list[tuple[str, str, str]] = [
        ("item_1_business", "business", "Item 1 — Business"),
        ("item_1a_risk_factors", "risk_factors", "Item 1A — Risk Factors"),
        ("item_7_mdna", "management_discussion", "Item 7 — Management's Discussion and Analysis"),
        (
            "item_10_directors_officers",
            "directors_officers_and_governance",
            "Item 10 — Directors, Officers and Corporate Governance",
        ),
        ("subsidiaries", "subsidiaries", "Subsidiaries"),
        ("notes", "notes", "Notes to Financial Statements"),
    ]

    def _fetch_10k(self, c: Company, want_rag: bool) -> tuple[dict[str, Any], list[str]]:
        warnings: list[str] = []
        filing = c.latest("10-K")
        if filing is None:
            return (
                {"has_10k": False, "items": {}, "mdna_text": ""},
                ["No 10-K filing found"],
            )

        is_amended = filing.form == "10-K/A"
        sections_extraction_quality = "ok"
        if is_amended:
            warnings.append(
                f"latest 10-K is {filing.form} (amended); retrying with amendments=False"
            )
            non_amended = c.get_filings(form="10-K", amendments=False).latest(1)
            if non_amended is not None:
                filing = non_amended if not isinstance(non_amended, list) else non_amended[0]
                sections_extraction_quality = "amended_redirected"
                is_amended = False  # we successfully resolved to the original
            else:
                warnings.append("no non-amended 10-K available; section quality may degrade")

        tenk = filing.obj()
        sections: list[dict[str, Any]] = []
        items: dict[str, str] = {}
        for canonical_id, attr_name, display_title in self._SECTION_ATTRS:
            raw = getattr(tenk, attr_name, "") or ""
            text = str(raw)
            sections.append(
                {
                    "canonical_id": canonical_id,
                    "title": display_title,
                    "text": text,
                    "char_count": len(text),
                    "extracted_via": "edgartools_attribute",
                }
            )
            items[canonical_id] = text

        # Fallback: financial institutions (JPM probe) parsing comes up short.
        mdna = items.get("item_7_mdna", "")
        if not mdna or len(mdna) < _MIN_VALID_SECTION_CHARS:
            warnings.append(
                f"management_discussion too short ({len(mdna)} chars); "
                "falling back to filing.text() full corpus for BM25 indexing"
            )
            sections_extraction_quality = "fallback_to_full_text"
            try:
                full_text = filing.text() or ""
            except _ADAPTER_CATCH as e:
                # Type only — str(e) embeds the SEC URL; this rides to the report.
                warnings.append(f"filing.text() also failed: {type(e).__name__}")
                full_text = ""
            if full_text:
                items["item_7_mdna"] = full_text
                # Replace the empty section text so downstream renderers /
                # RAG see something coherent.
                for s in sections:
                    if s["canonical_id"] == "item_7_mdna":
                        s["text"] = full_text
                        s["char_count"] = len(full_text)
                        s["extracted_via"] = "filing_text_fallback"

        data: dict[str, Any] = {
            "company_name": getattr(c, "name", None),
            "cik": str(getattr(c, "cik", "")).zfill(10) if getattr(c, "cik", None) else "",
            "latest_10k_date": str(filing.filing_date),
            "latest_10k_accession": filing.accession_no,
            "has_10k": True,
            "is_amended": is_amended,
            "form": filing.form,
            "sections_extraction_quality": sections_extraction_quality,
            "items": items,
            "sections": sections,
            "mdna_text": items.get("item_7_mdna", ""),
            "mdna_available": bool(items.get("item_7_mdna")),
            "source_url": getattr(filing, "homepage_url", None),
        }

        if want_rag:
            # Section-aware chunking → each chunk's source carries its Item title
            # so run_qa can cite specific sections. Stored as SERIALIZABLE dicts,
            # never a live BM25Index: the index is a runtime object that cannot
            # round-trip through the canonical JSON cache (caching it made
            # cache.set's model_dump_json raise PydanticSerializationError and
            # crash every live fetch). run_qa rebuilds the index on demand.
            chunks = build_rag_chunks(sections, filing.filing_date)
            data["rag_chunks"] = chunks
            data["chunk_count"] = len(chunks)

        return data, warnings

    # ------------------------------------------------------------------
    # 10-Q (Quarterly)
    # ------------------------------------------------------------------

    def _fetch_10q(self, c: Company, n: int) -> tuple[dict[str, Any], list[str]]:
        filings_iter = c.get_filings(form="10-Q").latest(n)
        if filings_iter is None:
            return {"quarterly_filings": []}, ["No 10-Q filings found"]
        filings = list(filings_iter) if hasattr(filings_iter, "__iter__") else [filings_iter]
        out: list[dict[str, Any]] = []
        for f in filings:
            try:
                tenq = f.obj()
                mdna = getattr(tenq, "management_discussion", "") or ""
            except _ADAPTER_CATCH:
                mdna = ""
            out.append(
                {
                    "form": f.form,
                    "filing_date": str(f.filing_date),
                    "period_of_report": str(getattr(f, "period_of_report", "")),
                    "accession_no": f.accession_no,
                    "mdna_chars": len(str(mdna)),
                    "mdna_text": str(mdna),
                    "source_url": getattr(f, "homepage_url", None),
                }
            )
        return {"quarterly_filings": out}, []

    # ------------------------------------------------------------------
    # 8-K (Current Report — note: obj class is ``CurrentReport``, not EightK)
    # ------------------------------------------------------------------

    def _fetch_8k(self, c: Company, n: int) -> tuple[dict[str, Any], list[str]]:
        filings_iter = c.get_filings(form="8-K").latest(n)
        if filings_iter is None:
            return {"events": []}, ["No 8-K filings found"]
        filings = list(filings_iter) if hasattr(filings_iter, "__iter__") else [filings_iter]
        events: list[dict[str, Any]] = []
        for f in filings:
            items: list[str] = []
            try:
                report = f.obj()
                items = [str(i) for i in (getattr(report, "items", []) or [])]
            except _ADAPTER_CATCH:
                pass
            try:
                text = (f.text() or "")[:5000] if hasattr(f, "text") else ""
            except _ADAPTER_CATCH:
                text = ""
            events.append(
                {
                    "filing_date": str(f.filing_date),
                    "period_of_report": str(getattr(f, "period_of_report", "")),
                    "accession_no": f.accession_no,
                    "items": items,
                    "text": text,
                    "source_url": getattr(f, "homepage_url", None),
                }
            )
        return {"events": events}, []

    # ------------------------------------------------------------------
    # Form 4 (Insider transactions)
    # ------------------------------------------------------------------

    def _fetch_insider(self, c: Company, days: int) -> tuple[dict[str, Any], list[str]]:
        cutoff = date.today() - timedelta(days=days)
        # Pull a generous buffer (60) and stop early when we fall past cutoff.
        filings_iter = c.get_filings(form="4").latest(60)
        if filings_iter is None:
            return {"transactions": [], "window_days": days}, []
        filings = list(filings_iter) if hasattr(filings_iter, "__iter__") else [filings_iter]

        transactions: list[dict[str, Any]] = []
        for f in filings:
            if f.filing_date < cutoff:
                break
            try:
                form4 = f.obj()
            except _ADAPTER_CATCH as e:
                logger.warning("Form 4 obj() failed for %s: %s", f.accession_no, e)
                continue
            insider_name = getattr(form4, "insider_name", "") or ""
            position = getattr(form4, "position", None)
            activities: list[Any] = []
            if hasattr(form4, "get_transaction_activities"):
                try:
                    activities = form4.get_transaction_activities() or []
                except _ADAPTER_CATCH as e:
                    logger.warning(
                        "get_transaction_activities failed for %s: %s",
                        f.accession_no,
                        e,
                    )
            for act in activities:
                # _opt_float (not bare float): Form 4 often carries a footnote
                # marker like "[F1]" in price_per_share instead of a number; bare
                # float("[F1]") raised ValueError and crashed the WHOLE insider
                # parse (every transaction lost). The trailing ``or None`` folds a
                # 0 price (forfeit / gift, code D) to "no price", not $0.
                price = _opt_float(getattr(act, "price_per_share", None)) or None
                transactions.append(
                    {
                        "filing_date": str(f.filing_date),
                        "accession_no": f.accession_no,
                        "insider_name": insider_name,
                        "insider_position": position,
                        "transaction_type": getattr(act, "transaction_type", "") or "",
                        "code": getattr(act, "code", "") or "",
                        # None ≠ 0: a missing share count stays None (the compute
                        # layer treats it as a parse gap, not a nonsensical 0-share
                        # leg).
                        "shares": _opt_float(getattr(act, "shares", None)),
                        # value abstains to None when edgartools fabricated its
                        # no-price sentinel 0 (footnoted/absent price) — see
                        # _form4_value. A genuinely computed (positive) value
                        # passes through unchanged.
                        "value": _form4_value(getattr(act, "value", None), price),
                        "price_per_share": price,
                        "security_type": getattr(act, "security_type", "") or "",
                        "security_title": getattr(act, "security_title", "") or "",
                        "underlying_security": (getattr(act, "underlying_security", "") or ""),
                        "exercise_date": _coerce_form4_date(getattr(act, "exercise_date", None)),
                        "expiration_date": _coerce_form4_date(
                            getattr(act, "expiration_date", None)
                        ),
                        "footnote_ids": getattr(act, "footnote_ids", "") or "",
                        "footnotes_text": getattr(act, "footnotes_text", "") or "",
                    }
                )
        return {"transactions": transactions, "window_days": days}, []

    # ------------------------------------------------------------------
    # XBRL Facts (typed getters)
    # ------------------------------------------------------------------

    def _fetch_xbrl(self, c: Company) -> tuple[dict[str, Any], list[str]]:
        facts = c.get_facts()
        if facts is None:
            return {"facts_available": False}, ["EntityFacts unavailable"]

        today = datetime.now(timezone.utc).date()
        warnings: list[str] = []

        # Concept-aware TTM (ADR-0008): pick the live concept by latest period_end
        # + gate on period structure, instead of edgartools' first-match-wins
        # getters that latch abandoned concepts (NVDA → FY2020 $10.918B). None
        # here → compute layer falls back to FMP TTM.
        ttm_revenue = _select_recent_ttm(
            facts, _TTM_REVENUE_CONCEPTS, today=today, warnings=warnings
        )
        ttm_net_income = _select_recent_ttm(
            facts, _TTM_NET_INCOME_CONCEPTS, today=today, warnings=warnings
        )

        # Surface edgartools' TTM quality caveats so downstream (and the UI)
        # can show "TTM as of <quarter>" honestly: a derived Q4 (FY−9M) is a
        # calculated value, not a reported quarter, and ``warning`` flags gaps /
        # thin history. These ride DataResult.warnings → financial.warnings.
        for label, metric in (("revenue", ttm_revenue), ("net income", ttm_net_income)):
            if not isinstance(metric, dict):
                continue
            if metric.get("has_calculated_q4"):
                warnings.append(
                    f"Trailing-twelve-month {label} includes a calculated Q4 "
                    "(full year minus the first nine months), not a separately "
                    "reported quarter."
                )
            if metric.get("warning"):
                warnings.append(f"Trailing-twelve-month {label}: {metric['warning']}")

        # P&L "latest" is the latest annual point — TTM is the current-period
        # caliber and lives in ``ttm_*`` above. Each latest_* now carries the
        # REAL matched concept (BUG-009), not a hardcoded label, so the artifact
        # snapshot's SEC provenance is honest.
        #
        # Balance-sheet items are point-in-time, so "latest" must mean the most
        # recent reporting period — not the latest *annual* point. ``annual=True``
        # (the getter default) prefers the 10-K fiscal-year value and silently
        # lags by one quarter once a 10-Q is filed: on 2026-05-28 TSLA shipped a
        # 10-Q for Q1 2026 (filed 2026-04-23) carrying assets $143.724B, but the
        # artifact showed $137.806B — the FY2025 10-K snapshot. ``annual=False``
        # falls back to the most recent point regardless of form type, so the
        # 10-Q overrides the 10-K once it lands.
        return {
            "facts_available": True,
            "ttm_revenue": ttm_revenue,
            "ttm_net_income": ttm_net_income,
            "latest_revenue": _select_latest_fact(
                facts, _LATEST_REVENUE_CONCEPTS, annual=True, prefer_recent=True, warnings=warnings
            ),
            "latest_net_income": _select_latest_fact(
                facts, _LATEST_NET_INCOME_CONCEPTS, annual=True, warnings=warnings
            ),
            "latest_gross_profit": _select_latest_fact(
                facts, _LATEST_GROSS_PROFIT_CONCEPTS, annual=True, warnings=warnings
            ),
            "latest_operating_income": _select_latest_fact(
                facts, _LATEST_OPERATING_INCOME_CONCEPTS, annual=True, warnings=warnings
            ),
            "latest_total_assets": _select_latest_fact(
                facts, _LATEST_TOTAL_ASSETS_CONCEPTS, annual=False, warnings=warnings
            ),
            "latest_total_liabilities": _select_latest_fact(
                facts, _LATEST_TOTAL_LIABILITIES_CONCEPTS, annual=False, warnings=warnings
            ),
            "latest_shareholders_equity": _select_latest_fact(
                facts, _LATEST_SHAREHOLDERS_EQUITY_CONCEPTS, annual=False, warnings=warnings
            ),
        }, warnings

    # ------------------------------------------------------------------
    # 13F (local cache lookup; refresh job is scripts/refresh_sec_holdings.py)
    # ------------------------------------------------------------------

    def _fetch_13f_sync(
        self,
        ticker: str,
        company_name: str | None = None,
    ) -> tuple[dict[str, Any], list[str]]:
        # The DataLayer.fetch path is async, but _fetch_sync is called
        # inside asyncio.to_thread so a `nest_asyncio` re-entrant call is
        # safe. The lookup function itself is async (aiosqlite).
        from finrobot.engine.data.sec_holdings_cache import (
            ephemeral_connection,
            lookup_holders_for_ticker,
            cache_status,
        )

        async def _go() -> tuple[list[dict[str, Any]], dict[str, Any]]:
            # Each call here runs under a fresh asyncio.run loop; the module's
            # singleton connection belongs to the server's main loop and an
            # aiosqlite connection awaited cross-loop hangs (BUG-082 sibling).
            # Scope all I/O to a private open-use-close connection instead.
            async with ephemeral_connection() as conn:
                return (
                    await lookup_holders_for_ticker(
                        ticker,
                        issuer_name=company_name,
                        limit=20,
                        conn=conn,
                    ),
                    await cache_status(conn=conn),
                )

        try:
            holders, status = asyncio.run(_go())
        except RuntimeError:
            # If we're somehow already in a running loop (shouldn't happen
            # because to_thread runs in a fresh thread with no loop), use
            # nest-asyncio safe path.
            import nest_asyncio

            nest_asyncio.apply()
            holders, status = asyncio.run(_go())

        warnings: list[str] = []
        if not status.get("populated"):
            warnings.append(
                "13F holdings cache not built yet; run scripts/refresh_sec_holdings.py to populate"
            )
        else:
            # The lookup serves the newest quarter it HAS, which silently lags
            # once the next quarter's 13F-HR deadline passes. Compare the
            # quarter actually served for THIS ticker (the cache's global
            # latest can be fresher than a dropped issuer's rows) against the
            # cadence expectation computed by cache_status.
            expected = status.get("expected_period_end")
            served = str(holders[0]["period_end"]) if holders else status.get("latest_period_end")
            if expected and served and str(served) < str(expected):
                warnings.append(
                    f"13F holdings are stale: serving quarter {served}, but quarter "
                    f"{expected} filings are already due (13F-HR is due 45 days after "
                    "quarter end). Run scripts/refresh_sec_holdings.py or Settings → "
                    "SEC 13F sync to refresh."
                )
        return {
            "holders": holders,
            "source": "local_index",
            "cache_status": status,
        }, warnings

    # ------------------------------------------------------------------
    # DEF 14A (Proxy statement)
    # ------------------------------------------------------------------

    def _fetch_proxy(self, c: Company) -> tuple[dict[str, Any], list[str]]:
        proxy_filing = c.latest("DEF 14A")
        if proxy_filing is None:
            return {"proxy": None}, ["No DEF 14A found"]
        text = ""
        try:
            text = proxy_filing.text() or ""
        except _ADAPTER_CATCH:
            pass
        return {
            "filing_date": str(proxy_filing.filing_date),
            "accession_no": proxy_filing.accession_no,
            "text": _slice_proxy_text(text),
            "source_url": getattr(proxy_filing, "homepage_url", None),
        }, []

    # ------------------------------------------------------------------
    # SOX-302 CEO certification (Exhibit 31.1 of the latest 10-Q/10-K)
    # ------------------------------------------------------------------

    def _fetch_ceo_certification(self, c: Company) -> tuple[dict[str, Any], list[str]]:
        """Exhibit-31.1 (CEO) certification text from the latest periodic report.

        The signer of the Section-302 certification is, by law, the CURRENT
        principal executive officer, and it is re-filed every quarter — a far
        fresher and less ambiguous CEO-identity signal than the annual DEF 14A
        prose. We pick the 10-Q OR 10-K with the more recent filing_date, locate
        the CEO's Ex-31.1 attachment (never the CFO's Ex-31.2), and return its
        raw text for the deterministic name extractor in ``ownership.py``. On
        any miss we return ``cert_available: False`` so the consumer falls back
        to the proxy scrape — a miss is safe, a wrong signer is not.
        """
        filing = c.get_filings(form=["10-Q", "10-K"]).latest(1)
        if filing is None:
            return {"cert_available": False}, ["No 10-Q/10-K filing found"]
        if isinstance(filing, list):
            filing = filing[0] if filing else None
        if filing is None:
            return {"cert_available": False}, ["No 10-Q/10-K filing found"]

        best_att: Any = None
        best_rank = 1_000
        try:
            attachments = list(filing.attachments)
        except _ADAPTER_CATCH:
            attachments = []
        for att in attachments:
            rank = _ceo_cert_attachment_rank(
                str(getattr(att, "document_type", "") or ""),
                str(getattr(att, "description", "") or ""),
                str(getattr(att, "document", "") or ""),
            )
            if rank is not None and rank < best_rank:
                best_att, best_rank = att, rank

        if best_att is None:
            return (
                {
                    "cert_available": False,
                    "form": filing.form,
                    "filing_date": str(filing.filing_date),
                    "accession_no": filing.accession_no,
                },
                [f"No Exhibit 31.1 CEO certification in latest {filing.form}"],
            )

        try:
            cert_text = best_att.text() or ""
        except _ADAPTER_CATCH as e:
            return (
                {
                    "cert_available": False,
                    "form": filing.form,
                    "filing_date": str(filing.filing_date),
                    "accession_no": filing.accession_no,
                },
                [f"Ex-31.1 text() failed: {type(e).__name__}"],
            )

        return {
            "cert_available": bool(cert_text),
            "cert_text": cert_text,
            "form": filing.form,
            "filing_date": str(filing.filing_date),
            "accession_no": filing.accession_no,
            "exhibit": str(getattr(best_att, "document_type", "") or ""),
            "source_url": getattr(filing, "homepage_url", None),
        }, []

    # ------------------------------------------------------------------
    # Schedule 13D / 13G (5%+ beneficial owners)
    # ------------------------------------------------------------------

    def _fetch_schedule13(self, c: Company, limit: int = 8) -> tuple[dict[str, Any], list[str]]:
        """Latest SC 13D/13G beneficial-ownership filings for the SUBJECT company.

        edgartools has no structured 13D/G parser (``.obj()`` is None), so we
        read the filer identity from the SGML header and parse the cover-page
        "Amount Beneficially Owned" / "Percent of Class" from the filing text.
        Deduped by filer (latest filing per reporting person) so the panel
        shows the current 5%+ holders, not every amendment.
        """
        warnings: list[str] = []
        filings_iter = c.get_filings(form=["SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A"])
        if filings_iter is None:
            return {"alerts": []}, []
        filings = list(filings_iter) if hasattr(filings_iter, "__iter__") else [filings_iter]
        # Newest first; scan a bounded buffer so a noisy amender can't starve
        # other holders, then dedupe to `limit` distinct filers.
        try:
            filings.sort(key=lambda f: str(getattr(f, "filing_date", "")), reverse=True)
        except (TypeError, ValueError):
            pass

        subject_cik = str(getattr(c, "cik", "") or "").lstrip("0")
        subject_name = _issuer_token(getattr(c, "name", None))

        alerts: list[dict[str, Any]] = []
        seen_filers: set[str] = set()
        for f in filings[: max(limit * 3, 12)]:
            if len(alerts) >= limit:
                break
            try:
                filer_name, filer_cik = _schedule13_filer(f)
            except _ADAPTER_CATCH as e:
                logger.warning("13D/G header parse failed for %s: %s", f.accession_no, e)
                continue
            if not filer_name:
                continue
            # Skip self-filings (subject == filer): a company doesn't hold 5%
            # of itself; these are filing-agent artifacts, not real holders.
            if (filer_cik and filer_cik.lstrip("0") == subject_cik) or (
                subject_name and _issuer_token(filer_name) == subject_name
            ):
                continue
            dedup_key = filer_cik or filer_name.lower()
            if dedup_key in seen_filers:
                continue

            try:
                text = f.text() or ""
            except _ADAPTER_CATCH as e:
                logger.warning("13D/G text() failed for %s: %s", f.accession_no, e)
                text = ""
            shares = _schedule13_shares(text)
            if shares is None:
                # No reliable share count → don't fabricate a 0. Skip; the
                # model requires a real share figure for this to be useful.
                continue
            seen_filers.add(dedup_key)
            alerts.append(
                {
                    "filer_name": filer_name,
                    "filer_cik": filer_cik,
                    "schedule_type": "13D" if "13D" in str(f.form).upper() else "13G",
                    "filing_date": str(f.filing_date),
                    "accession_no": f.accession_no,
                    "shares": shares,
                    "pct_of_class": _schedule13_pct(text),
                    "source_url": getattr(f, "homepage_url", None),
                }
            )

        if not alerts and filings:
            warnings.append("SC 13D/13G filings found but none parseable")
        return {"alerts": alerts}, warnings
