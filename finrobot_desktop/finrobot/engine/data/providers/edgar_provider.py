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
    BM25 (``engine/compute/rag.py``) still has something to index.
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

from finrobot.engine.data.interface import DataProvider, DataResult, ProviderError
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
_TTM_REVENUE_CONCEPTS: tuple[str, ...] = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "Revenue",
)
_TTM_NET_INCOME_CONCEPTS: tuple[str, ...] = ("NetIncomeLoss", "NetIncome", "ProfitLoss")

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


def _metric_latest_period_end(metric: Any) -> date | None:
    """Latest ``period_end`` across a TTMMetric's underlying period facts.

    Used both to rank candidate concepts (recency wins over list order) and to
    enforce the recency gate. Returns None when no fact carries a usable date.
    """
    latest: date | None = None
    for pf in getattr(metric, "period_facts", None) or []:
        pe = getattr(pf, "period_end", None)
        if isinstance(pe, datetime):
            pe = pe.date()
        if isinstance(pe, date) and (latest is None or pe > latest):
            latest = pe
    return latest


def _select_recent_ttm(
    facts: Any,
    concepts: tuple[str, ...],
    *,
    today: date,
) -> dict[str, Any] | None:
    """Pick the live concept's TTM and return it as a typed dict, or None.

    Among ``concepts`` present in ``facts``, choose the one whose facts have the
    latest ``period_end`` (NOT first-match-wins like edgartools' getters), then
    require the window to pass ``_validate_ttm_periods`` and end within
    ``_TTM_RECENCY_DAYS``. Returns ``{"concept", "value", "periods"}`` shaped like
    the old ``_ttm`` output, or None when nothing qualifies (→ FMP fallback).
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
        latest_end = _metric_latest_period_end(metric)
        if latest_end is None:
            continue
        # Recency gate: a window whose newest quarter predates the cutoff is a
        # frozen/abandoned concept, even if it "wins" recency among candidates.
        if (today - latest_end).days > _TTM_RECENCY_DAYS:
            continue
        if not _validate_ttm_periods(getattr(metric, "periods", None)):
            continue
        if best_end is None or latest_end > best_end:
            periods_typed: list[dict[str, Any]] = []
            for p in metric.periods:
                if isinstance(p, tuple) and len(p) == 2:
                    periods_typed.append({"year": int(p[0]), "quarter": str(p[1])})
                else:
                    periods_typed.append({"raw": str(p)})
            best = {
                "concept": getattr(metric, "concept", ""),
                "value": float(getattr(metric, "value", 0) or 0),
                "periods": periods_typed,
            }
            best_end = latest_end
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
# payload is bounded at ~90k per ticker.
_PROXY_INTRO_CHARS = 50_000
_PROXY_SCT_WINDOW_CHARS = 40_000
_PROXY_INTRO_SCT_GAP_MARKER = "\n\n--- [SCT WINDOW] ---\n\n"


def _slice_proxy_text(full_text: str) -> str:
    """Return up-to-90k window: first 50k (governance) + 40k around SCT.

    Compensation regex extractors (Summary Compensation Table parser,
    CEO pay ratio extractor) need the SCT section, which for TSLA-class
    issuers sits 100k+ chars into the full filing. Naïvely capping at
    50k loses the entire compensation discussion.
    """
    if not full_text:
        return ""
    intro = full_text[:_PROXY_INTRO_CHARS]
    if len(full_text) <= _PROXY_INTRO_CHARS:
        return intro

    # Find the FIRST "Summary Compensation Table" heading past the intro
    # window — earlier matches are nearly always TOC entries, not the
    # real table.
    matches = list(re.finditer(r"Summary Compensation Table", full_text, re.I))
    sct_pos: int | None = None
    for m in matches:
        if m.start() >= _PROXY_INTRO_CHARS:
            sct_pos = m.start()
            break

    if sct_pos is None:
        # Heading not found past the intro window — return the intro
        # only. Avoids dragging along a useless tail.
        return intro

    sct_window = full_text[sct_pos : sct_pos + _PROXY_SCT_WINDOW_CHARS]
    return intro + _PROXY_INTRO_SCT_GAP_MARKER + sct_window


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
            raise ProviderError(f"edgartools {data_type} for {ticker}: {e}") from e
        return DataResult(
            data=data,
            provider=self.name,
            ticker=ticker.upper(),
            data_type=data_type,
            timestamp=datetime.now(tz=timezone.utc),
            warnings=warnings,
        )

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
                warnings.append(f"filing.text() also failed: {e}")
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
            # FinRobot's own BM25 — input switched from regex-strip chunks
            # to clean typed-section chunks.
            from finrobot.engine.compute.rag import BM25Index, chunk_text

            merged = "\n\n".join(f"[{s['title']}]\n{s['text']}" for s in sections if s["text"])
            source_label = f"10-K/{filing.filing_date}"
            chunks = chunk_text(merged, chunk_size=300, overlap=30, source=source_label)
            data["rag_index"] = BM25Index(chunks)
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
                transactions.append(
                    {
                        "filing_date": str(f.filing_date),
                        "accession_no": f.accession_no,
                        "insider_name": insider_name,
                        "insider_position": position,
                        "transaction_type": getattr(act, "transaction_type", "") or "",
                        "code": getattr(act, "code", "") or "",
                        "shares": float(getattr(act, "shares", 0) or 0),
                        "value": float(getattr(act, "value", 0) or 0),
                        "price_per_share": (float(getattr(act, "price_per_share", 0) or 0) or None),
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

        def _float(getter_name: str, **kwargs: Any) -> float | None:
            getter = getattr(facts, getter_name, None)
            if not callable(getter):
                return None
            try:
                v = getter(**kwargs)
                return float(v) if v is not None else None
            except _ADAPTER_CATCH:
                return None

        # Balance-sheet items are point-in-time, so "latest" must mean the
        # most recent reporting period — not the latest *annual* point.
        # ``annual=True`` (the edgar-python default on every standardized
        # getter) prefers the 10-K fiscal-year value and silently lags by
        # one quarter once a 10-Q is filed: on 2026-05-28 TSLA shipped a
        # 10-Q for Q1 2026 (filed 2026-04-23) carrying assets $143.724B,
        # but the artifact showed $137.806B — the FY2025 10-K snapshot.
        # ``annual=False`` falls back to the most recent point regardless
        # of form type, so 10-Q overrides 10-K once it lands.
        return {
            "facts_available": True,
            # Concept-aware TTM (ADR-0008): pick the live concept by latest
            # period_end + gate on period structure, instead of edgartools'
            # first-match-wins getters that latch abandoned concepts (NVDA →
            # FY2020 $10.918B). None here → compute layer falls back to FMP TTM.
            "ttm_revenue": _select_recent_ttm(facts, _TTM_REVENUE_CONCEPTS, today=today),
            "ttm_net_income": _select_recent_ttm(facts, _TTM_NET_INCOME_CONCEPTS, today=today),
            # P&L: "latest" remains the latest annual point — TTM is the
            # current-period caliber and lives in ``ttm_*`` above.
            "latest_revenue": _float("get_revenue"),
            "latest_net_income": _float("get_net_income"),
            "latest_gross_profit": _float("get_gross_profit"),
            "latest_operating_income": _float("get_operating_income"),
            # Balance sheet: include 10-Q in the "most recent" calculus.
            "latest_total_assets": _float("get_total_assets", annual=False),
            "latest_total_liabilities": _float("get_total_liabilities", annual=False),
            "latest_shareholders_equity": _float("get_shareholders_equity", annual=False),
        }, []

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
            lookup_holders_for_ticker,
            cache_status,
        )

        async def _go() -> tuple[list[dict[str, Any]], dict[str, Any]]:
            return (
                await lookup_holders_for_ticker(
                    ticker,
                    issuer_name=company_name,
                    limit=20,
                ),
                await cache_status(),
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
