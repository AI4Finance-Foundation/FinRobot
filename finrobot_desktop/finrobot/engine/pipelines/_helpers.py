"""Shared execute_fn factories for pipeline steps that fetch + extract financial data."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from pydantic_ai import Agent

from finrobot.engine.compute.operators.cyclical_peers import screen_peers_with_cyclical
from finrobot.engine.primitives.corporate_actions import detect_mna_transition
from finrobot.engine.primitives.industry import (
    is_balance_sheet_financial,
    is_bank,
    is_commodity_cyclical,
)
from finrobot.engine.compute.coordinators.extractor import (
    extract_company_financials,
    extract_financial_data,
    normalize_peer_to_usd,
)
from finrobot.engine.compute.coordinators.historical_extractor import fetch_historical_metrics
from finrobot.engine.compute.operators.multiples import (
    calculate_core_pe,
    calculate_multiples,
    calculate_peer_statistics,
)
from finrobot.engine.compute.operators.valuation_aggregator import (
    RERATING_WARNING_MARKER,
    aggregate_valuation,
    through_cycle_roe,
)
from finrobot.engine.compute.operators.valuation_synthesis import synthesize_valuations
from finrobot.engine.compute.operators.xbrl_aligned_comps import (
    build_xbrl_aligned_company,
    override_company_with_xbrl,
)
from finrobot.engine.data.interface import ProviderError
from finrobot.engine.compute.operators.forward_estimates import (
    ForwardFinancials,
    get_forward_financials,
)
from finrobot.engine.data.types import DataType
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.models.financial import (
    CompanyFinancials,
    DCFResult,
    DDMResult,
    FinancialData,
    HistoricalMetrics,
    LBOResult,
    PeerComps,
    PeerSelection,
    RIResult,
    StepOutput,
    ValuationMethod,
    ValuationSynthesis,
)
from finrobot.warning_text import safe_error_text

logger = logging.getLogger(__name__)

# Peer comp-set sizing. Auto-selection over-selects ranked candidates so
# transient drops (a rate-limited financials fetch, a missing FX quote for a
# foreign ADR) thin the set instead of failing the whole report. MIN is the
# floor for a defensible median; MAX caps the published comp set.
_PEER_COMP_SET_MIN = 3
_PEER_COMP_SET_MAX = 6
# Upper bound on a CALLER-SUPPLIED ``--peers`` set (distinct from
# _PEER_COMP_SET_MAX, which caps the auto-selected published set). The CLI
# imports this so its entry-point validation can't drift from the runtime
# defense-in-depth check below (BUG-047).
_PEER_COMP_INPUT_MAX = 10


# ── Whitelist formatting (must mirror the frontend SourcedNumber render) ──────
# The numeric-discipline whitelist injected into the thesis prompt restates peer
# multiples and market caps so the LLM can cite them in competitor_analysis. If
# we inject raw floats (28.736199…, 3411000000000) the LLM self-rounds / self-
# humanizes and the prose can diverge from the peer table the analyst sees. So
# we pre-format to the EXACT same caliber the UI uses, then inject that string:
#   - multiples (P/E, EV/EBITDA, EV/Rev) → "28.7x"   (PeerComparisonChart: v.toFixed(1)+'x')
#   - market_cap                          → "$3.41T"  (formatCompactNumber en: T/B/M=.2f, K=.1f)
# None must never reach the LLM as the literal "None"; it renders "n/a (not available)".
_WHITELIST_NA = "n/a (not available)"


def fmt_multiple(value: float | None) -> str:
    """Format a valuation multiple as the UI does — one decimal + 'x'.

    Mirrors ``PeerComparisonChart`` (``v.toFixed(1) + 'x'``) so a P/E of
    28.7361… injected to the LLM reads identically to the peer table cell.
    """
    if value is None:
        return _WHITELIST_NA
    return f"{value:.1f}x"


def fmt_market_cap(value: float | None) -> str:
    """Humanize a USD market cap as the UI does — ``formatCompactNumber`` (en).

    T/B/M use two decimals, K uses one, matching ``desktop/src/utils/format.ts`` so a
    raw 3_411_000_000_000 reads "$3.41T" in both the prose and the peer table.
    """
    if value is None:
        return _WHITELIST_NA
    abs_v = abs(value)
    if abs_v >= 1e12:
        return f"${value / 1e12:.2f}T"
    if abs_v >= 1e9:
        return f"${value / 1e9:.2f}B"
    if abs_v >= 1e6:
        return f"${value / 1e6:.2f}M"
    if abs_v >= 1e3:
        return f"${value / 1e3:.1f}K"
    return f"${value:,.0f}"


def _find_target_financial_data(structured_context: dict[str, object]) -> FinancialData | None:
    """Locate the target's FinancialData regardless of which step produced it.

    equity_research names the data step ``data_collection``; comps names it
    ``target_data``. Search by type so the shared peer-analysis executor works
    in both pipelines without hard-coding a step key.
    """
    direct = structured_context.get("data_collection")
    if isinstance(direct, FinancialData):
        return direct
    for value in structured_context.values():
        if isinstance(value, FinancialData):
            return value
    return None


def _peer_override(raw: object) -> list[str] | None:
    """Validated custom peer tickers from the ``peers`` run kwarg, or None to
    fall back to automatic selection.

    Accepts a list/tuple of tickers or a comma-separated string; upper-cases,
    strips, dedupes (order-preserving), and drops blanks. Returns None for an
    absent/empty/unrecognized value so the caller runs the normal LLM path.
    """
    if isinstance(raw, str):
        items: list[str] = raw.split(",")
    elif isinstance(raw, (list, tuple)):
        items = [str(x) for x in raw]
    else:
        return None
    deduped: dict[str, None] = {}
    for item in items:
        sym = item.strip().upper()
        if sym:
            deduped.setdefault(sym, None)
    return list(deduped) or None


def _peer_tickers_from_artifact_payload(payload: object, ticker: str) -> list[str]:
    if not isinstance(payload, dict):
        return []
    peer_block = payload.get("peer_analysis") or payload.get("statistical_bench")
    if not isinstance(peer_block, dict):
        return []
    raw_peers = peer_block.get("peers")
    if not isinstance(raw_peers, list):
        return []
    target = ticker.strip().upper()
    tickers: list[str] = []
    for peer in raw_peers:
        sym: str | None = None
        if isinstance(peer, dict) and isinstance(peer.get("ticker"), str):
            sym = peer["ticker"]
        elif isinstance(peer, str):
            sym = peer
        if sym is None:
            continue
        normalized = sym.strip().upper()
        if normalized and normalized != target and normalized not in tickers:
            tickers.append(normalized)
    return tickers


def _artifact_created_at_utc(artifact: object) -> datetime | None:
    meta = getattr(artifact, "meta", None)
    created_at = getattr(meta, "created_at", None)
    if not isinstance(created_at, datetime):
        return None
    if created_at.tzinfo is None:
        return created_at.replace(tzinfo=timezone.utc)
    return created_at.astimezone(timezone.utc)


def _sticky_peer_max_age_days(deps: FinRobotDeps) -> int:
    raw = getattr(deps.settings, "peer_sticky_max_age_days", 7)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


async def _sticky_peer_selection(
    deps: FinRobotDeps,
    source_artifact_id: object,
    ticker: str,
) -> PeerSelection | None:
    if not isinstance(source_artifact_id, str) or not source_artifact_id:
        return None
    store = getattr(deps, "artifact_store", None)
    if store is None:
        return None
    get = getattr(store, "get", None)
    if not callable(get):
        return None
    try:
        artifact = await get(source_artifact_id)
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError):
        logger.warning("Could not load source artifact %s for sticky peers", source_artifact_id)
        return None
    artifact_ticker = getattr(artifact, "ticker", None)
    if not isinstance(artifact_ticker, str) or artifact_ticker.upper() != ticker.upper():
        return None
    max_age_days = _sticky_peer_max_age_days(deps)
    created_at = _artifact_created_at_utc(artifact)
    if max_age_days <= 0 or created_at is None:
        return None
    if datetime.now(tz=timezone.utc) - created_at > timedelta(days=max_age_days):
        logger.info(
            "Parent artifact %s is older than peer sticky window (%s days); reselecting peers",
            source_artifact_id,
            max_age_days,
        )
        return None
    tickers = _peer_tickers_from_artifact_payload(artifact.outputs.structured, ticker)
    if len(tickers) < _PEER_COMP_SET_MIN:
        return None
    return PeerSelection(
        tickers=tickers,
        rationale=(
            f"Reused prior-version peer set from {source_artifact_id} for version stability: "
            f"{', '.join(tickers)}."
        ),
    )


async def _deterministic_select_peers(deps: FinRobotDeps, ticker: str) -> PeerSelection:
    """Deterministic peer selection: PEER_CANDIDATES fetch + pure screen (ADR-0014).

    Replaces the retired LLM selection, whose run-to-run nondeterminism swung
    the published comps_pe target ±30% within one day (MSFT $487 → $636,
    2026-06-05) — a peer median that moves without the market moving is not a
    traceable number. Same candidates always yield the same set; the rationale
    is the algorithm trace (pool → eligibility cuts → tiered picks) instead of
    LLM prose, so the report's peer list is re-derivable by hand.

    The LLM's cross-bucket business judgment (e.g. MU's real comps are memory
    makers filed under "Computer Hardware") is mechanically approximated by
    tier 2 — FMP's stock_peers cross-recommendation list, which crosses
    classification buckets. Residual misclassification risk is bounded by the
    pool-vs-selected median tripwire, the per-peer 5x deviation validator, and
    the full peer table shipping in the report for analyst review. Hand-curated
    sets remain available via the ``--peers`` override.

    Raises:
        ValueError (non-recoverable): when PEER_CANDIDATES is unavailable
            (no FMP key / provider down) or the screen yields no eligible
            peer. Deterministic selection re-runs to the identical result, so
            a retry can never "pick a luckier set" — the step must degrade
            instead of burning retry budget (the BUG-059 class of waste).
    """
    try:
        result = await deps.data_layer.fetch(DataType.PEER_CANDIDATES, ticker)
    except ProviderError as e:
        raise ValueError(
            f"peer candidates unavailable for {ticker} (FMP-only data type; "
            f"comps degrades without it): {e}"
        ) from e
    if result.data.get("error"):
        raise ValueError(f"peer candidates unavailable for {ticker}: {result.data['error']}")
    screen = screen_peers_with_cyclical(result.data, ticker)
    if not screen.tickers:
        raise ValueError(
            f"peer screen for {ticker} produced no eligible peers "
            f"(pool empty after market-cap band + NM filter) — comps degrades"
        )
    return PeerSelection(tickers=screen.tickers, rationale=screen.rationale)


def _forward_currency_signal(
    *,
    is_adr: bool | None,
    quote_currency: str | None,
    net_income_usd: float | None,
    shares: float | None,
) -> tuple[bool, float | None]:
    """(usd_safe, trailing_eps_usd) for the forward FX-mismatch guard.

    ``usd_safe`` = a non-ADR issuer quoting in USD. Both inputs SURVIVE the
    canonical FX normalization (``is_adr`` is a structural flag; ``quote_currency``
    is never overwritten — only ``reporting_currency`` is, to USD), so this is the
    honest "is this issuer foreign?" signal, unlike the post-norm
    ``reporting_currency == quote_currency`` (USD==USD for everyone, always True).

    ``trailing_eps_usd`` = currency-clean USD trailing EPS = trailing net income /
    canonical shares (market-cap-consistent = per ADR). None when net income /
    shares are missing or non-positive (a loss-maker forms no clean EPS anchor —
    the guard's revenue leg covers that case instead)."""
    usd_safe = not (bool(is_adr) or (quote_currency or "USD").upper() != "USD")
    trailing_eps_usd: float | None = None
    if (
        isinstance(net_income_usd, (int, float))
        and net_income_usd > 0
        and isinstance(shares, (int, float))
        and shares > 0
    ):
        trailing_eps_usd = net_income_usd / shares
    return usd_safe, trailing_eps_usd


async def _enrich_company_forward(
    company: CompanyFinancials,
    deps: FinRobotDeps,
    *,
    usd_safe: bool,
    trailing_eps_usd: float | None = None,
) -> None:
    """Populate forward_eps / forward_pe (FY1 consensus) on a comps row, best-effort.

    Shared by the peer rows (``_fetch_one_peer``) and the target
    (``execute_peer_analysis``) so both sides of the comps table carry the same
    forward口径 — previously only peers were enriched, leaving the target's
    forward_eps/forward_pe None even though the comps_pe method consumes the
    target's forward EPS (it just fetched it down a separate path, so the driving
    number was never traceable on the target row).

    ``usd_safe`` (a non-ADR issuer quoting in USD — a signal that SURVIVES
    normalization, unlike the post-FX-norm ``reporting_currency == quote_currency``
    which is USD==USD for everything) marks a clean single-currency issuer taking
    the fast path. A foreign issuer (``usd_safe`` False: an ADR or a non-USD quote)
    is NOT hard-skipped — it is brought into the ``get_forward_financials``
    FX-mismatch guard's scope WITH ``trailing_eps_usd``, a currency-clean USD
    trailing EPS (= trailing net income / canonical shares). The guard's magnitude
    legs then abstain a native-currency consensus (KOF's under-reported MXN
    ``netIncomeAvg`` slips the NI/revenue legs but its native ``epsAvg`` trips the
    EPS leg) while KEEPING a legitimately-USD one (TSM when FMP ships USD). Only a
    foreign issuer with NO derivable eps anchor (shares missing) keeps the
    conservative skip — the ni/rev legs alone can't see the under-reported-NI hole.
    A fetch miss is non-fatal — forward is an optional enrichment, never a drop reason.
    """
    if not usd_safe and trailing_eps_usd is None:
        return
    try:
        _fwd_raw = await deps.data_layer.fetch_canonical(DataType.FORWARD_ESTIMATES, company.ticker)
        _fwd = get_forward_financials(
            ticker=company.ticker,
            yf_info=None,
            fmp_analyst_estimates=_fwd_raw.payload(),
            trailing_net_income_usd=company.net_income,
            trailing_revenue_usd=company.revenue,
            trailing_eps_usd=trailing_eps_usd,
        )
        company.forward_eps = _fwd.forward_eps
        if _fwd.forward_net_income and company.market_cap > 0:
            company.forward_pe = company.market_cap / _fwd.forward_net_income
    # TypeError is in the tuple deliberately: forward enrichment is best-effort
    # (never a drop reason). Under a provider storm a third-party lib
    # (yfinance/pandas) can raise a bare TypeError in a frame outside our wrapped
    # boundaries; abstaining forward P/E to None on it keeps the hiccup from
    # bubbling up and killing the peer fetch (2026-06-12 TSLA: a storm-time
    # TypeError on this path vaporized comps → silent single-method DCF).
    except (ProviderError, ValueError, KeyError, ArithmeticError, TypeError) as _fwd_err:
        logger.debug("forward P/E unavailable for %s: %s", company.ticker, _fwd_err)


async def execute_peer_analysis(
    agent: Agent[Any, Any],
    deps: FinRobotDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
    **kwargs: object,
) -> StepOutput:
    """Select peer tickers, then fetch + compute multiples deterministically.

    Peers come from the deterministic candidate screen UNLESS the caller passes
    ``peers=[...]`` (e.g. ``finrobot comps --peers AAPL,MSFT``), in which case
    auto-selection is skipped and the user's set is used verbatim. Either path
    runs the identical fetch / FX-normalize / multiples / median math, so a
    custom peer set yields the same traceable multiples — only membership changes.
    Shared by equity_research and the standalone comps pipeline so BOTH emit
    deterministic, traceable multiples instead of LLM free text."""
    override = _peer_override(kwargs.get("peers"))
    if override is not None:
        if not _PEER_COMP_SET_MIN <= len(override) <= _PEER_COMP_INPUT_MAX:
            raise ValueError(
                f"--peers needs {_PEER_COMP_SET_MIN}-{_PEER_COMP_INPUT_MAX} tickers, "
                f"got {len(override)}: {override}"
            )
        logger.info("Peer analysis using caller-supplied peers: %s", override)
        selection = PeerSelection(tickers=override, rationale="Caller-supplied peer set (--peers).")
    else:
        sticky_selection = await _sticky_peer_selection(
            deps, kwargs.get("source_artifact_id"), ticker
        )
        selection = (
            sticky_selection
            if sticky_selection is not None
            else await _deterministic_select_peers(deps, ticker)
        )

    # A company is never its own comp. The LLM (and occasionally a caller) sometimes
    # lists the target among its peers; drop it so it neither consumes a candidate
    # slot nor double-counts itself into the peer medians.
    deduped_tickers = [t for t in selection.tickers if t.strip().upper() != ticker.strip().upper()]
    if deduped_tickers != selection.tickers:
        selection = PeerSelection(tickers=deduped_tickers, rationale=selection.rationale)

    # Why a peer was dropped, keyed by ticker — so a foreign comp lost to an FX
    # rate-limit (e.g. SK Hynix) is NAMED in the artifact warning instead of
    # silently vanishing and leaving the analyst to wonder why the obvious peer is
    # missing. Mutated inside _fetch_one_peer; read after the gather.
    peer_drops: dict[str, str] = {}

    async def _fetch_one_peer(peer_ticker: str) -> CompanyFinancials | None:
        try:
            _fin = await deps.data_layer.fetch_canonical(DataType.FINANCIALS, peer_ticker)
            company = extract_company_financials(_fin)
            # usd_safe + a currency-clean USD trailing-EPS anchor from signals that
            # SURVIVE the canonical FX normalization (is_adr / quote_currency — the
            # pre-norm reporting_currency is already overwritten to USD on _fin). A
            # foreign peer (TSM, or KOF) is NOT skipped here anymore: it is handed to
            # get_forward_financials' FX-mismatch guard with the eps anchor, so the
            # guard's EPS leg abstains a native-currency consensus the NI/revenue legs
            # miss (KOF's under-reported MXN netIncomeAvg → fwd P/E 8.7 = USD cap /
            # MXN net income). company.net_income is already USD (canonical FX-norm).
            forward_usd_safe, forward_trailing_eps = _forward_currency_signal(
                is_adr=getattr(_fin, "is_adr", None),
                quote_currency=getattr(_fin, "quote_currency", None),
                net_income_usd=company.net_income,
                shares=getattr(_fin, "shares_outstanding", None),
            )
            # Normalize foreign-listed ADRs / local listings to canonical USD
            # BEFORE multiples are computed — otherwise TSM (TWD financials,
            # USD market_cap) collapses EV/EBITDA to 0.158x. A failed FX lookup
            # falls through to the outer except and drops this peer; thinning
            # the set beats publishing a mixed-unit multiple.
            company = await normalize_peer_to_usd(
                company, fmp_api_key=getattr(deps.settings, "fmp_api_key", None)
            )
            company = calculate_multiples(company)
            xbrl_result = await deps.data_layer.fetch(DataType.XBRL_FACTS, peer_ticker)
            company = override_company_with_xbrl(company, xbrl_result.data)
            # Forward enrichment (shared with the target in execute_peer_analysis).
            # forward_usd_safe + forward_trailing_eps are captured above from _fin's
            # normalization-surviving signals; the eps anchor lets the guard catch a
            # foreign peer whose FMP forward is native currency (KOF).
            await _enrich_company_forward(
                company, deps, usd_safe=forward_usd_safe, trailing_eps_usd=forward_trailing_eps
            )
            return company
        # TypeError is caught too: this is the per-peer "drop one, keep the set"
        # boundary, so a storm-time TypeError raised by a third-party lib
        # (yfinance/pandas/edgartools) in a frame outside our wrapped blocks must
        # drop THIS peer — named in peer_drops, surfaced in the artifact warning —
        # never escape to vaporize the whole comps step into a single-method
        # valuation (2026-06-12 TSLA incident). A systematic TypeError bug still
        # shows: it drops every peer → thin/empty set → the thin-comps warning.
        except (ProviderError, ValueError, KeyError, ArithmeticError, TypeError) as e:
            peer_drops[peer_ticker] = safe_error_text(e)
            logger.warning(f"Skipping peer {peer_ticker}: {e}")
            return None

    # Auto-selection over-selects ranked candidates; we fetch all concurrently and
    # keep the survivors in rank order, capped at PEER_COMP_SET_MAX. Extra
    # candidates are drop-insurance: a rate-limited financials fetch or a missing
    # FX quote drops that one peer instead of failing the whole report. gather +
    # the order-preserving comprehension keep best-first ranking, so the slice
    # retains the most-comparable survivors.
    peer_results = await asyncio.gather(*[_fetch_one_peer(t) for t in selection.tickers])
    fetched: list[CompanyFinancials] = [p for p in peer_results if p is not None]
    # Drop-and-continue on a structurally-invalid peer instead of failing the whole
    # set. A non-positive (or non-finite) revenue row is not a common-equity operating
    # comp — a preferred / non-operating listing that slipped selection, or a provider
    # glitch. validate_peer_comps used to fail the ENTIRE set on one such row (C comps
    # 2026-07-02: MER-PK's non-positive bank net-revenue → median_pb=None, the whole
    # report crashed). Remove it INDIVIDUALLY, name it in peer_drops (surfaced in the
    # artifact warning), and let the rest compute a median (降级不全崩). ``> 0`` also
    # rejects NaN; out-of-band multiples are already nulled by calculate_multiples, so
    # revenue is the one structural check that would otherwise sink the set.
    survivors: list[CompanyFinancials] = []
    for p in fetched:
        if p.revenue > 0:
            survivors.append(p)
        else:
            peer_drops[p.ticker] = (
                f"non-positive revenue ({p.revenue:g}) — not a common-equity operating "
                "comp (preferred / non-operating listing or provider glitch); dropped"
            )
            logger.warning("Dropping structurally-invalid peer %s: revenue=%s", p.ticker, p.revenue)
    # The deterministic screen intentionally over-selects (PEER_SCREEN_TOP_N=7)
    # as drop-insurance, but the comp set is capped at _PEER_COMP_SET_MAX=6. When
    # every candidate fetches cleanly the lowest-ranked survivor is trimmed here.
    # That trim was SILENT — the screen rationale ("picking 7 firms: …") still
    # claimed 7 while the delivered table showed 6, breaking the 7→6 audit trail
    # (KO 2026-07-02: PRMB in the trace, absent from the table, no drop record).
    # Name each trimmed peer in peer_drops so the reconciliation surfaces.
    # The reason string is READER-FACING (artifact warning → report "peers
    # excluded" section) — financial language only; the over-select/fetch
    # mechanics above stay in this comment (2026-07-07 external audit).
    for trimmed in survivors[_PEER_COMP_SET_MAX:]:
        peer_drops[trimmed.ticker] = (
            f"ranked below the {_PEER_COMP_SET_MAX}-peer comp-set cap on "
            "comparability — less comparable than the retained peers; excluded "
            "by ranking, not by data quality"
        )
    peers: list[CompanyFinancials] = survivors[:_PEER_COMP_SET_MAX]

    # A thin comp set is a QUALITY problem, not a crash. peer_analysis is a
    # non-critical step in both pipelines, and the step's validator
    # (validate_peer_comps / validate_has_peers, min_peers=3) already gates a thin
    # set — failing validation triggers a re-selection retry (the LLM may pick a
    # luckier, fully-fetchable set) and, if still thin after retries, degrades
    # best-effort instead of tanking the whole report.
    #
    # Two cases:
    #   • 1..MIN-1 survivors → build the thin PeerComps anyway, tag a warning so
    #     it surfaces in the artifact, and let the validator fail it (→ retry →
    #     degrade). NEVER raise on count here: recoverability is decided BY
    #     exception type, not by matching substrings in a message, so a raise
    #     would not be treated as retryable and would crash the run.
    #   • 0 survivors → PeerComps requires >=1 peer (Field min_length=1), so we
    #     can't build one at all. Raise ProviderError — recoverable BY TYPE (not
    #     by message text), so it retries with backoff then degrades on the
    #     non-critical step, never surfacing a raw pydantic ValidationError.
    if not peers:
        raise ProviderError(
            f"No comparable peers returned usable financials for {ticker} "
            f"(0 of {len(selection.tickers)} candidates: {selection.tickers}). "
            f"All peer financials/FX fetches failed — usually transient provider "
            f"rate-limiting; retry shortly."
        )
    thin_warning: str | None = None
    if len(peers) < _PEER_COMP_SET_MIN:
        thin_warning = (
            f"Thin comp set: only {len(survivors)} of {len(selection.tickers)} "
            f"candidate peers returned usable financials (target >="
            f"{_PEER_COMP_SET_MIN}). Candidates: {selection.tickers}. Usually "
            f"transient data-provider rate-limiting (yfinance 429) or a missing "
            f"FX quote for a foreign-listed peer — median multiples below are "
            f"less reliable; retry shortly for a fuller set."
        )
        logger.warning("%s (target=%s)", thin_warning, ticker)

    target_fin = _find_target_financial_data(structured_context)
    if target_fin is None:
        raise ValueError("target FinancialData not available in context; cannot build peer target.")
    raw_target_xbrl = structured_context.get("xbrl_facts_raw")
    target_xbrl = raw_target_xbrl if isinstance(raw_target_xbrl, dict) else None
    target = await build_xbrl_aligned_company(
        ticker=ticker,
        financial_data=target_fin,
        xbrl_data=target_xbrl,
        fmp_api_key=getattr(deps.settings, "fmp_api_key", None),
    )
    # Enrich the target with the SAME forward口径 as the peers (build_xbrl_aligned_company
    # only does trailing). Mirror the peer path EXACTLY: derive usd_safe + the USD
    # trailing-EPS anchor from signals that SURVIVE normalization (target_fin.market.is_adr
    # / target_fin.quote_currency). The OLD gate ``reporting_currency == quote_currency``
    # read target_fin AFTER canonical FX normalization overwrote reporting_currency to
    # USD, so it was USD==USD == True for EVERY issuer — an ADR target (KOF) always passed
    # and leaked a native-MXN forward P/E (8.7 = USD cap / MXN net income). With the eps
    # anchor the guard's EPS leg now abstains that while keeping a legit-USD ADR (TSM/USD).
    target_usd_safe, target_trailing_eps = _forward_currency_signal(
        is_adr=target_fin.market.is_adr,
        quote_currency=target_fin.quote_currency,
        net_income_usd=target.net_income,
        shares=target_fin.market.shares_outstanding,
    )
    await _enrich_company_forward(
        target, deps, usd_safe=target_usd_safe, trailing_eps_usd=target_trailing_eps
    )

    peer_comps = PeerComps(
        target=target,
        peers=peers,
        peer_justification=selection.rationale,
    )
    peer_comps = calculate_peer_statistics(peer_comps)
    # NOPAT core P/E (target + peers) so the comps_pe method pairs a core peer
    # median with the target's core EPS — one earnings caliber on both sides.
    peer_comps = calculate_core_pe(peer_comps)

    # Insurer comps ROE quality: attach the target + peer-median through-cycle ROE so
    # _comps_pb_method scales the flat peer-median P/B by ROE (a flat median grants no
    # quality premium — it under-prices a high-ROE insurer like PGR, comps $115 vs price
    # $216, and over-prices a low-ROE one). ONLY the insurer cohort
    # (is_balance_sheet_financial and NOT is_bank); banks / non-financials skip the
    # per-peer historical fetch entirely and keep both fields None → flat median →
    # byte-identical. Best-effort: a fetch miss leaves the flat median (comps_pb discloses).
    if is_balance_sheet_financial(
        industry=target_fin.market.industry, sector=target_fin.market.sector
    ) and not is_bank(industry=target_fin.market.industry, sector=target_fin.market.sector):
        try:
            tgt_hist = await fetch_historical_metrics(deps.data_layer, ticker)
            peer_roes: list[float] = []
            for _peer in peers:
                try:
                    _ph = await fetch_historical_metrics(deps.data_layer, _peer.ticker)
                    _pr = through_cycle_roe(_ph.net_income, _ph.shareholders_equity)
                    if _pr is not None:
                        peer_roes.append(_pr)
                except (ProviderError, ValueError, KeyError, TypeError):
                    continue
            peer_comps.target_through_cycle_roe = through_cycle_roe(
                tgt_hist.net_income, tgt_hist.shareholders_equity
            )
            peer_comps.peer_median_through_cycle_roe = median(peer_roes) if peer_roes else None
        except (ProviderError, ValueError, KeyError, TypeError) as _tcroe_err:
            logger.debug("Through-cycle ROE unavailable for %s: %s", ticker, _tcroe_err)

    if thin_warning is not None and thin_warning not in peer_comps.warnings:
        peer_comps.warnings.insert(0, thin_warning)

    # Name every dropped candidate (even when the surviving set is healthy) so a
    # genuine comp lost to a transient FX rate-limit — e.g. a foreign memory peer
    # like SK Hynix — is visibly accounted for, never silently swapped for a
    # less-comparable substitute that happened to fetch cleanly. Each reason
    # carries its own cause (fetch/FX failure, non-positive revenue, or cap-trim),
    # so the screen's "picking N firms" rationale reconciles to the delivered set.
    if peer_drops:
        dropped_warning = (
            "Peers excluded from the comp set (each with its reason below): "
            + "; ".join(f"{t}: {reason}" for t, reason in peer_drops.items())
        )
        if dropped_warning not in peer_comps.warnings:
            peer_comps.warnings.append(dropped_warning)

    # Surface per-row XBRL-vs-FMP TTM divergence flags (ADR-0008) so a kept-FMP
    # [待核] doesn't stay buried on the CompanyFinancials row.
    for company in (peer_comps.target, *peer_comps.peers):
        note = company.ttm_divergence_note
        if note and note not in peer_comps.warnings:
            peer_comps.warnings.append(f"{company.ticker}: {note}")

    ev_ebitda_str = (
        f"{peer_comps.median_ev_ebitda:.1f}x" if peer_comps.median_ev_ebitda is not None else "N/A"
    )
    pe_str = f"{peer_comps.median_pe:.1f}x" if peer_comps.median_pe is not None else "N/A"
    narrative = (
        f"Peer set ({len(peers)} companies): {', '.join(p.ticker for p in peers)}. "
        f"Median EV/EBITDA: {ev_ebitda_str}. "
        f"Median P/E: {pe_str}. "
        f"{selection.rationale}"
    )
    return StepOutput(text=narrative, structured=peer_comps)


async def execute_financial_data_step(
    agent: Agent[Any, Any],
    deps: FinRobotDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
    **_kwargs: object,
) -> StepOutput:
    """Standard data-collection step: run agent + fetch financials/price + extract.

    Used by equity_research, dcf, lbo, comps pipelines.  Centralised here so
    changes to extraction logic propagate everywhere.

    Also builds HistoricalMetrics from multi-year data and injects it into
    structured_context (consumed by the DCF/LBO/technical steps).
    """
    step_result = await agent.run(prompt, deps=deps)
    _fin = await deps.data_layer.fetch_canonical(DataType.FINANCIALS, ticker)
    _price = await deps.data_layer.fetch_canonical(DataType.PRICE, ticker)
    financial_data = extract_financial_data(_fin, _price)
    # Cross-validation warnings are already carried on the canonical objects and
    # merged into FinancialData.warnings inside extract_financial_data — no
    # further merging needed here.

    # Freeze the day-over-day session-change AMOUNT the data agent is shown in the
    # PRICE prompt summary (NormalizedPrice.to_prompt_summary → latest_session_change
    # = last_close − prev_close, in the quote currency) as a traceable artifact leaf.
    # The report-drift audit builds its leaf registry from the FROZEN snapshot, and
    # this amount is NOT reconstructable from any stored field — it is a difference of
    # two closes, not price × a stored ratio (price × session_pct/100 has a relative
    # error ≈ the day's move, redacting a real figure on any material move) — so a
    # narrative that faithfully prints "Latest Session Change: -$3.75" traced to no
    # leaf and was redacted as an orphan (MSFT 2026-07-07). None on <2 bars (no prior
    # close to diff) → nothing frozen; the amount, if narrated, stays unmatched as
    # before. Only build_equity_research_artifact consumes this today (its data
    # narrative is the one that restates the snapshot).
    _session_change, _session_change_pct = _price.latest_session_change()
    if _session_change is not None:
        structured_context["price_session"] = {
            "latest_session_change": _session_change,
            "latest_session_change_pct": _session_change_pct,
        }

    # Target FY1 consensus (forward EPS) so build_valuation_synthesis can take
    # aggregate_valuation's forward comps path (peer forward median P/E × target
    # forward EPS) instead of the trailing fallback. Best-effort: a forward miss
    # must never fail the data step — the synthesis just stays on trailing.
    try:
        _fwd_raw = await deps.data_layer.fetch_canonical(DataType.FORWARD_ESTIMATES, ticker)
        # Raw multi-year payload kept for the DCF stage-1 growth seed (consensus
        # path via get_forward_revenue_growth); forward_financials is the FY1
        # projection the synthesis uses. Both read the same canonical snapshot —
        # the shared slot every other seed entry (REST /dcf-seed, chat MC,
        # IC-memo) also fetches, so consensus presence can't diverge per surface.
        structured_context["forward_estimates_raw"] = _fwd_raw.payload()
        # trailing_* anchor the FX-mismatch guard: financial_data comes from the
        # FX-normalized canonical snapshot, so income.net_income/revenue are
        # currency-clean USD. /analyst-estimates carries no currency field and may
        # be native (TWD for UMC), so without these anchors a foreign target's
        # native-currency forward EPS would feed the forward-comps price target. The
        # eps anchor (net income / canonical shares) covers the hole where FMP
        # UNDER-reports netIncomeAvg (KOF) so the NI/revenue legs stay in-band.
        _, _target_trailing_eps = _forward_currency_signal(
            is_adr=financial_data.market.is_adr,
            quote_currency=financial_data.quote_currency,
            net_income_usd=financial_data.income.net_income,
            shares=financial_data.market.shares_outstanding,
        )
        structured_context["forward_financials"] = get_forward_financials(
            ticker=ticker,
            yf_info=None,
            fmp_analyst_estimates=_fwd_raw.payload(),
            trailing_net_income_usd=financial_data.income.net_income,
            trailing_revenue_usd=financial_data.income.revenue,
            trailing_eps_usd=_target_trailing_eps,
        )
    except (ProviderError, ValueError, KeyError, TypeError) as _fwd_err:
        logger.debug("forward estimates unavailable for %s: %s", ticker, _fwd_err)

    # Build multi-year historical metrics + forecast for chart generation.
    # These are deterministic — no LLM call needed.
    # structured_context IS structured_results (same dict reference) so
    # writes here persist into PipelineResult.structured_data.
    hm = await _build_historical_metrics(deps, ticker)
    if hm is not None:
        structured_context["historical_metrics"] = hm
        logger.info(
            "HistoricalMetrics built for %s: %d years (%s)",
            ticker,
            len(hm.years),
            hm.years,
        )
    else:
        logger.info("HistoricalMetrics not available for %s", ticker)

    logger.info(
        "structured_context keys after data_collection: %s",
        list(structured_context.keys()),
    )
    return StepOutput(text=step_result.output, structured=financial_data)


async def _build_historical_metrics(deps: FinRobotDeps, ticker: str) -> HistoricalMetrics | None:
    """Build multi-year HistoricalMetrics for charts + DCF seeding.

    Delegates to ``fetch_historical_metrics`` — the single canonical extractor
    every other pipeline/route already uses (dcf, lbo, ic_memo, equity_research's
    own modeling-step fallback, routes/compute, routes/data). It reads CapEx /
    D&A / ΔNWC straight from the raw per-year provider dicts.

    The previous FinancialData→``extract_historical_metrics`` path silently
    DROPPED those three cash-flow fields (they never round-tripped through
    FinancialData), so ``dcf_seed`` saw empty CapEx/D&A history and fell back to
    the Damodaran industry aggregate — for ``Software (Internet)`` that means
    CapEx = 31.8% of revenue (an aggregate skewed by cash-burning small-caps),
    which crushed a profitable mega-cap's projected FCF to ~0 and produced a
    NEGATIVE implied price (META: −$22, failing the DCF validator every run).
    Consuming the same complete extractor as everyone else removes that path
    split. Returns None when fewer than 2 usable years exist.
    """
    try:
        # AUTO window (years=None): 5y for a normal name, 10y for a commodity-
        # cyclical so the through-cycle DCF median sees a full peak→trough→recovery
        # window. This is the PRIMARY historical_metrics the report's DCF seeds off
        # (equity_research reads structured_context["historical_metrics"] first), so
        # a hardcoded 5 here would silently starve MU's through-cycle normalization.
        hm = await fetch_historical_metrics(deps.data_layer, ticker)
    except (ValueError, KeyError, TypeError, RuntimeError, AttributeError, OSError) as e:
        logger.warning("Failed to build HistoricalMetrics for %s: %s", ticker, e)
        return None
    if len(hm.years) < 2:
        logger.info(
            "Only %d year(s) of data for %s — skipping HistoricalMetrics",
            len(hm.years),
            ticker,
        )
        return None
    return hm


def build_sensitivity_ranges(
    discount_rate: float, terminal_growth: float
) -> tuple[list[float], list[float]]:
    """Build (discount-rate, terminal-growth) sweep ranges for sensitivity tables.

    Used by DCF (discount_rate=WACC) and DDM (discount_rate=cost of equity).
    Both apply a ±2% sweep around discount_rate paired with terminal-growth
    candidates filtered to stay strictly below min(discount_rate_range), so
    every cell in the resulting grid is a valid Gordon-growth denominator.

    The lower cells are floored at ``terminal_growth + 0.005`` (not a hardcoded
    3%) to keep every rate a valid Gordon denominator. Because that floor is
    below ``discount_rate`` for any sound DCF (WACC > terminal growth), the
    center cell (index 2) always equals ``discount_rate`` — so the sensitivity
    table's center matches the narrative's base-case implied price (BUG-013).
    The old absolute 3% floor clobbered the center whenever WACC < 3%, shifting
    it off the base case by a large margin. (For very low WACC the bottom cells
    may clamp to the floor and repeat; they stay valid, the center stays exact.)
    """
    rate_floor = terminal_growth + 0.005
    rate_range = [round(max(rate_floor, discount_rate - 0.02 + i * 0.01), 4) for i in range(5)]
    tg_candidates = [round(max(0.0, terminal_growth - 0.01 + i * 0.005), 4) for i in range(5)]

    min_rate = min(rate_range)
    tg_range = [g for g in tg_candidates if g < min_rate]

    if len(tg_range) < 2:
        tg_range = [round(0.005 + i * 0.005, 4) for i in range(5) if 0.005 + i * 0.005 < min_rate]

    return rate_range, tg_range


def build_valuation_synthesis(
    structured_context: dict[str, object],
    current_price: float,
    ticker: str,
    *,
    historical_ev_ebitda_band: tuple[float, float] | None = None,
    historical_ev_ebitda_sample_n: int | None = None,
) -> ValuationSynthesis | None:
    """Build ValuationSynthesis from pipeline structured_context via aggregate_valuation.

    Replaces the old 2-method (DCF + EV/EBITDA) hand-rolled logic with the
    canonical 6-method ``aggregate_valuation`` function used by the REST endpoint.
    Adapts ``ValuationAggregate`` → ``ValuationSynthesis`` so the thesis step
    contract (``ValuationSynthesis``) stays intact.

    When only one method resolves, ``weighted_price`` will be None and the
    thesis step will NOT inject an authoritative price target — the LLM narrates
    without a forced number rather than surfacing a spurious single-method "average".
    """
    dcf = structured_context.get("financial_modeling")
    peers = structured_context.get("peer_analysis")
    ddm = structured_context.get("ddm_calc")
    ri = structured_context.get("ri_calc")
    lbo = structured_context.get("lbo_calculation") or structured_context.get("lbo_result")

    financial_data = structured_context.get("data_collection")
    shares: float | None = None
    if isinstance(financial_data, FinancialData):
        shares = financial_data.market.shares_outstanding
    # Fall back to DCFInputs.shares_outstanding when FinancialData is absent.
    # DCF seed always carries this value from the data-collection step, so this
    # keeps comps_pe functional in the common case where dcf resolved but
    # data_collection is not re-stored in the same dict slice.
    if shares is None and isinstance(dcf, DCFResult):
        shares = dcf.inputs.shares_outstanding

    # Current net debt for the EV/EBITDA equity bridge. Gate on
    # ``valuation.enterprise_value is not None`` — the extractor sets EV non-None
    # exactly when BOTH total_debt and total_cash were reported, so only then is
    # balance net debt a real figure rather than a zero-filled artifact. When
    # absent, fall back to the DCF seed's net_debt (same total_debt − cash口径);
    # if neither is available it stays None so the aggregator hides the EV/EBITDA
    # row instead of bridging EV→equity on a fabricated (zero or LBO-future) debt.
    current_net_debt: float | None = None
    if (
        isinstance(financial_data, FinancialData)
        and financial_data.valuation.enterprise_value is not None
        and financial_data.balance.total_debt is not None
        and financial_data.balance.total_cash is not None
    ):
        current_net_debt = financial_data.balance.total_debt - financial_data.balance.total_cash
    elif isinstance(dcf, DCFResult):
        current_net_debt = dcf.inputs.net_debt

    # Target forward EPS (FY1 consensus) → aggregate_valuation's forward comps
    # path. Gated on a single-currency target: forward_eps is reporting-currency
    # and the comps math pairs it with a USD price, so a foreign-listed target
    # (reporting ccy ≠ quote ccy) would mix units — it falls back to the trailing
    # comps path rather than publish a mixed-unit number. Forward provenance is
    # left to the REST route; the pipeline only needs the number here.
    fwd = structured_context.get("forward_financials")
    forward_eps: float | None = None
    if (
        isinstance(fwd, ForwardFinancials)
        and isinstance(financial_data, FinancialData)
        and financial_data.reporting_currency == financial_data.quote_currency
    ):
        forward_eps = fwd.forward_eps

    # EV/EBITDA denominator (batch2) = current TTM operating EBITDA
    # (``income.ebitda`` = OI + D&A) — the SAME caliber as the trailing band it
    # multiplies, so the whole ev leg is single-caliber (a re-rating anchor, not a
    # forward-growth bet). It is DECOUPLED from the forward FX guard that gates
    # forward_eps: forward_eps must be single-currency-gated because it pairs a
    # native-currency estimate with a USD-normalized peer P/E (BUG-006 unit mix),
    # but the ev leg reads every input from ONE canonical FinancialData snapshot —
    # income.ebitda, net debt and shares are all the same (quote) currency and the
    # band is a unitless ratio, so no cross-source currency mix is possible. Hence
    # the row now shows for foreign issuers (TSM/SAP-class) whose native forward
    # EBITDA the FX guard abstained, priced off the canonical TTM EBITDA instead.
    ttm_ebitda: float | None = (
        financial_data.income.ebitda if isinstance(financial_data, FinancialData) else None
    )

    # Commodity-cyclical → add the P/B comps row as the primary relative multiple.
    # Industry/sector when the target snapshot is in scope; the ticker anchor covers
    # memory/storage under the generic "Semiconductors" tag (same gate the seed uses).
    cyclical = is_commodity_cyclical(
        industry=financial_data.market.industry
        if isinstance(financial_data, FinancialData)
        else None,
        sector=financial_data.market.sector if isinstance(financial_data, FinancialData) else None,
        ticker=ticker,
    )
    # Bank / insurer → suppress the cash-flow methods (DCF / EV-EBITDA / P/FCF) in the
    # football field; they are category errors for a balance-sheet-funded financial
    # (deposits / float / reserves are operating raw material, not financing — no clean
    # EBITDA or FCF). P/B + P/E (+ DDM for banks) lead instead. Uses the WIDER
    # is_balance_sheet_financial (banks + risk-carrying insurers), NOT is_bank: an
    # insurer is a DCF category error just like a bank, but is_bank excluded insurers,
    # so a P&C insurer's $1297 DCF anchored a BUY +460% (ALL, 2026-06-24). is_bank stays
    # the bank-only predicate for DDM routing + bank data corrections insurers must not
    # inherit; numeric_audit's sector_sign already used this wider boundary, so this
    # converges both consumers onto one authority.
    financial_sector = is_balance_sheet_financial(
        industry=financial_data.market.industry
        if isinstance(financial_data, FinancialData)
        else None,
        sector=financial_data.market.sector if isinstance(financial_data, FinancialData) else None,
    )
    # Recent stock-funded acquisition / large secondary → the TTM snapshot mixes a
    # post-deal share count with mostly-pre-deal earnings, so every per-share method
    # (DDM g, comps EPS, ROE) reads spuriously bearish while the market prices the
    # pro-forma entity (FITB/Comerica: ddm/comps all −30% vs a Buy sell-side).
    # Detect via the share-count break against the pre-deal weighted-avg baseline
    # (HistoricalMetrics net_income/eps) and degrade gracefully downstream — withhold
    # the poisoned point, hold the verdict neutral. A data-lineage call, not calibration.
    historical = structured_context.get("historical_metrics")
    mna_transition = isinstance(historical, HistoricalMetrics) and detect_mna_transition(
        shares, historical.net_income, historical.eps
    )
    agg = aggregate_valuation(
        ticker=ticker,
        current_price=current_price,
        dcf=dcf if isinstance(dcf, DCFResult) else None,
        peer_comps=peers if isinstance(peers, PeerComps) else None,
        # Residual income (justified P/B) supersedes the dividend-only DDM as the bank
        # intrinsic method when available — ROE-coherent + buyback-invariant. When RI
        # is present the DDM row is suppressed so the football field shows one
        # intrinsic value, not the buyback-blind DDM beside it.
        ddm=ddm if (isinstance(ddm, DDMResult) and not isinstance(ri, RIResult)) else None,
        residual_income=ri if isinstance(ri, RIResult) else None,
        lbo=lbo if isinstance(lbo, LBOResult) else None,
        shares_outstanding=shares,
        current_net_debt=current_net_debt,
        forward_eps=forward_eps,
        ttm_ebitda=ttm_ebitda,
        historical_ev_ebitda_band=historical_ev_ebitda_band,
        historical_ev_ebitda_sample_n=historical_ev_ebitda_sample_n,
        cyclical=cyclical,
        financial_sector=financial_sector,
    )

    if not agg.methods:
        return None

    for w in agg.warnings:
        logger.debug("valuation_synthesis: %s", w)

    # Convert ValuationMethodRange → ValuationMethod for the thesis contract.
    vm_list: list[ValuationMethod] = [
        ValuationMethod(
            name=r.method,
            low=r.low,
            mid=r.mid,
            high=r.high,
            confidence=r.confidence,
            source=r.source,
            assumptions=r.assumptions,
            # Structured re-rating premise (multiples methods only) — the dial's
            # re-rating dominance gate GRADES on this; None for intrinsic methods.
            rerating_ratio=r.rerating_ratio,
        )
        for r in agg.methods
    ]

    try:
        vs = synthesize_valuations(
            vm_list,
            current_price,
            cyclical=cyclical,
            financial_sector=financial_sector,
            mna_transition=bool(mna_transition),
        )
    except ValueError as e:
        logger.warning("Failed to build ValuationSynthesis: %s", e)
        return None

    # Two warning families cross from the aggregate into the report artifact:
    # 1) Method exit reasons ("method withheld") — a runnable method a guard sent
    #    off must say WHY in the artifact, not in a debug log; downstream
    #    resolve_canonical_thesis also folds THESE into the basis prose.
    # 2) Re-rating disclosures (RERATING_WARNING_MARKER) — a multiples method
    #    whose implied multiple sits far from the target's own current multiple
    #    is betting on an unproven re-rating; the reader must see that premise in
    #    the report's warnings section. Deliberately NOT "method withheld": the
    #    method still prices, and basis's withheld-only filter must not absorb it
    #    (cover prose stays lean; the football-field row carries assumptions).
    # The REST aggregate route already surfaces agg.warnings whole.
    forwarded = [w for w in agg.warnings if "method withheld" in w or RERATING_WARNING_MARKER in w]
    if forwarded:
        vs.warnings.extend(w for w in forwarded if w not in vs.warnings)
    return vs
