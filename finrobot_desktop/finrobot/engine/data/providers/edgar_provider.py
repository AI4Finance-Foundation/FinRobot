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
    DataType.RAG_10K,       # legacy alias
    DataType.FILINGS,       # legacy alias for 10-K
]


# Exceptions we map to ProviderError (don't crash the route layer).
# Wider than strictly needed because edgartools occasionally raises
# bare AttributeError / TypeError when a filing has unexpected structure.
_ADAPTER_CATCH = (
    DataObjectException,
    CompanyNotFoundError,
    OSError,
    RuntimeError,
    ValueError,
    AttributeError,
    TypeError,
)


# Min char threshold below which we treat a typed section attribute as
# "edgartools parser came up short" and fall back to filing.text() so the
# downstream BM25 index isn't blank. Probe 2026-05-27 saw JPM 10-K
# management_discussion = 396 chars (real text is ~100 pages).
_MIN_VALID_SECTION_CHARS = 1000


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

    async def fetch(
        self, ticker: str, data_type: str | DataType, **kwargs: Any
    ) -> DataResult:
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
            raise ProviderError(
                f"edgartools {data_type} for {ticker}: {e}"
            ) from e
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
        ("item_1_business",          "business",
            "Item 1 — Business"),
        ("item_1a_risk_factors",     "risk_factors",
            "Item 1A — Risk Factors"),
        ("item_7_mdna",              "management_discussion",
            "Item 7 — Management's Discussion and Analysis"),
        ("item_10_directors_officers",
            "directors_officers_and_governance",
            "Item 10 — Directors, Officers and Corporate Governance"),
        ("subsidiaries",             "subsidiaries",
            "Subsidiaries"),
        ("notes",                    "notes",
            "Notes to Financial Statements"),
    ]

    def _fetch_10k(
        self, c: Company, want_rag: bool
    ) -> tuple[dict[str, Any], list[str]]:
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
                f"latest 10-K is {filing.form} (amended); "
                "retrying with amendments=False"
            )
            non_amended = c.get_filings(form="10-K", amendments=False).latest(1)
            if non_amended is not None:
                filing = non_amended if not isinstance(non_amended, list) else non_amended[0]
                sections_extraction_quality = "amended_redirected"
                is_amended = False  # we successfully resolved to the original
            else:
                warnings.append(
                    "no non-amended 10-K available; section quality may degrade"
                )

        tenk = filing.obj()
        sections: list[dict[str, Any]] = []
        items: dict[str, str] = {}
        for canonical_id, attr_name, display_title in self._SECTION_ATTRS:
            raw = getattr(tenk, attr_name, "") or ""
            text = str(raw)
            sections.append({
                "canonical_id": canonical_id,
                "title": display_title,
                "text": text,
                "char_count": len(text),
                "extracted_via": "edgartools_attribute",
            })
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
            merged = "\n\n".join(
                f"[{s['title']}]\n{s['text']}" for s in sections if s["text"]
            )
            source_label = f"10-K/{filing.filing_date}"
            chunks = chunk_text(merged, chunk_size=300, overlap=30, source=source_label)
            data["rag_index"] = BM25Index(chunks)
            data["chunk_count"] = len(chunks)

        return data, warnings

    # ------------------------------------------------------------------
    # 10-Q (Quarterly)
    # ------------------------------------------------------------------

    def _fetch_10q(
        self, c: Company, n: int
    ) -> tuple[dict[str, Any], list[str]]:
        filings_iter = c.get_filings(form="10-Q").latest(n)
        if filings_iter is None:
            return {"quarterly_filings": []}, ["No 10-Q filings found"]
        filings = (
            list(filings_iter) if hasattr(filings_iter, "__iter__")
            else [filings_iter]
        )
        out: list[dict[str, Any]] = []
        for f in filings:
            try:
                tenq = f.obj()
                mdna = getattr(tenq, "management_discussion", "") or ""
            except _ADAPTER_CATCH:
                mdna = ""
            out.append({
                "form": f.form,
                "filing_date": str(f.filing_date),
                "period_of_report": str(getattr(f, "period_of_report", "")),
                "accession_no": f.accession_no,
                "mdna_chars": len(str(mdna)),
                "mdna_text": str(mdna),
                "source_url": getattr(f, "homepage_url", None),
            })
        return {"quarterly_filings": out}, []

    # ------------------------------------------------------------------
    # 8-K (Current Report — note: obj class is ``CurrentReport``, not EightK)
    # ------------------------------------------------------------------

    def _fetch_8k(
        self, c: Company, n: int
    ) -> tuple[dict[str, Any], list[str]]:
        filings_iter = c.get_filings(form="8-K").latest(n)
        if filings_iter is None:
            return {"events": []}, ["No 8-K filings found"]
        filings = (
            list(filings_iter) if hasattr(filings_iter, "__iter__")
            else [filings_iter]
        )
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
            events.append({
                "filing_date": str(f.filing_date),
                "period_of_report": str(getattr(f, "period_of_report", "")),
                "accession_no": f.accession_no,
                "items": items,
                "text": text,
                "source_url": getattr(f, "homepage_url", None),
            })
        return {"events": events}, []

    # ------------------------------------------------------------------
    # Form 4 (Insider transactions)
    # ------------------------------------------------------------------

    def _fetch_insider(
        self, c: Company, days: int
    ) -> tuple[dict[str, Any], list[str]]:
        cutoff = date.today() - timedelta(days=days)
        # Pull a generous buffer (60) and stop early when we fall past cutoff.
        filings_iter = c.get_filings(form="4").latest(60)
        if filings_iter is None:
            return {"transactions": [], "window_days": days}, []
        filings = (
            list(filings_iter) if hasattr(filings_iter, "__iter__")
            else [filings_iter]
        )

        transactions: list[dict[str, Any]] = []
        for f in filings:
            if f.filing_date < cutoff:
                break
            try:
                form4 = f.obj()
            except _ADAPTER_CATCH as e:
                logger.warning(
                    "Form 4 obj() failed for %s: %s", f.accession_no, e
                )
                continue
            insider_name = getattr(form4, "insider_name", "") or ""
            position = getattr(form4, "position", None)
            activities: list[Any] = []
            if hasattr(form4, "get_transaction_activities"):
                try:
                    activities = (
                        form4.get_transaction_activities() or []
                    )
                except _ADAPTER_CATCH as e:
                    logger.warning(
                        "get_transaction_activities failed for %s: %s",
                        f.accession_no, e,
                    )
            for act in activities:
                transactions.append({
                    "filing_date": str(f.filing_date),
                    "accession_no": f.accession_no,
                    "insider_name": insider_name,
                    "insider_position": position,
                    "transaction_type": getattr(act, "transaction_type", "") or "",
                    "code": getattr(act, "code", "") or "",
                    "shares": float(getattr(act, "shares", 0) or 0),
                    "value": float(getattr(act, "value", 0) or 0),
                    "price_per_share": (
                        float(getattr(act, "price_per_share", 0) or 0) or None
                    ),
                    "security_type": getattr(act, "security_type", "") or "",
                    "security_title": getattr(act, "security_title", "") or "",
                    "underlying_security": (
                        getattr(act, "underlying_security", "") or ""
                    ),
                    "exercise_date": (
                        str(getattr(act, "exercise_date", None))
                        if getattr(act, "exercise_date", None) else None
                    ),
                    "expiration_date": (
                        str(getattr(act, "expiration_date", None))
                        if getattr(act, "expiration_date", None) else None
                    ),
                    "footnote_ids": getattr(act, "footnote_ids", "") or "",
                    "footnotes_text": getattr(act, "footnotes_text", "") or "",
                })
        return {"transactions": transactions, "window_days": days}, []

    # ------------------------------------------------------------------
    # XBRL Facts (typed getters)
    # ------------------------------------------------------------------

    def _fetch_xbrl(self, c: Company) -> tuple[dict[str, Any], list[str]]:
        facts = c.get_facts()
        if facts is None:
            return {"facts_available": False}, ["EntityFacts unavailable"]

        def _ttm(getter_name: str) -> dict[str, Any] | None:
            getter = getattr(facts, getter_name, None)
            if not callable(getter):
                return None
            try:
                m = getter()
                if m is None:
                    return None
                periods_list: list[Any] = getattr(m, "periods", []) or []
                typed_periods: list[dict[str, Any]] = []
                for p in periods_list:
                    if isinstance(p, tuple) and len(p) == 2:
                        typed_periods.append({"year": int(p[0]), "quarter": str(p[1])})
                    else:
                        typed_periods.append({"raw": str(p)})
                return {
                    "concept": getattr(m, "concept", ""),
                    "value": float(getattr(m, "value", 0) or 0),
                    "periods": typed_periods,
                }
            except _ADAPTER_CATCH:
                return None

        def _float(getter_name: str) -> float | None:
            getter = getattr(facts, getter_name, None)
            if not callable(getter):
                return None
            try:
                v = getter()
                return float(v) if v is not None else None
            except _ADAPTER_CATCH:
                return None

        return {
            "facts_available": True,
            "ttm_revenue":    _ttm("get_ttm_revenue"),
            "ttm_net_income": _ttm("get_ttm_net_income"),
            "latest_revenue":             _float("get_revenue"),
            "latest_net_income":          _float("get_net_income"),
            "latest_gross_profit":        _float("get_gross_profit"),
            "latest_operating_income":    _float("get_operating_income"),
            "latest_total_assets":        _float("get_total_assets"),
            "latest_total_liabilities":   _float("get_total_liabilities"),
            "latest_shareholders_equity": _float("get_shareholders_equity"),
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
                "13F holdings cache not built yet; run "
                "scripts/refresh_sec_holdings.py to populate"
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
            text = (proxy_filing.text() or "")
        except _ADAPTER_CATCH:
            pass
        return {
            "filing_date": str(proxy_filing.filing_date),
            "accession_no": proxy_filing.accession_no,
            "text": text[:50_000],  # cap to keep payload size sane
            "source_url": getattr(proxy_filing, "homepage_url", None),
        }, []
