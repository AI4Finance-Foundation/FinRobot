"""EMPIRICAL VALIDATION: DDM as the bank's lead valuation method in the equity_research
pipeline (slices 1+2+3 of the bank-DDM handoff).

Drives the REAL deterministic valuation path on LIVE data, no LLM, no full report:
  data_collection (extract_financial_data) → execute_peer_analysis →
  _execute_financial_modeling  (which now, for a bank, computes DDM and feeds it to
  build_valuation_synthesis) → resolve_canonical_thesis + audit_artifact gate.

What it proves, per ticker:
  • bank → ``ddm_calc`` populated AND a ``ddm`` row in the method set (slice 1)
  • bank → synthesis ANCHORS on ddm, headline ≈ DDM (slice 2), NOT the underpriced
    peer-comps blend; non-bank → no ddm row, anchor/target byte-identical (regression)
  • the numeric_audit gate withholds the bank target BEFORE slice 3 (EV blocked_field)
    and ships it AFTER (EV downgraded to review) — printed as ``gate_withhold``

The headline target must sit in the fresh sell-side band (pull it yourself — live
quants have memory weight 0). JPM 2026-06-23: price ~$331, sell-side avg $342
(low $295 / high $391), Buy → a DDM ~$332 is sane; a comps blend ~$264-287 is below
the sell-side low = the bug this fixes.

Run: `python scripts/_bank_ddm_research_validation.py [TICKERS...]`
(uses the local FMP key via hydrate_settings_from_secrets — no backend needed).
"""

from __future__ import annotations

import asyncio
import sys

from finrobot.config import get_settings
from finrobot.engine.compute.coordinators.extractor import extract_financial_data
from finrobot.engine.compute.operators.audit import audit_artifact
from finrobot.engine.compute.operators.forward_estimates import get_forward_financials
from finrobot.engine.compute.operators.valuation_synthesis import (
    resolve_canonical_thesis,
)
from finrobot.engine.data.factory import build_data_layer
from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.types import DataType
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.models.financial import DDMResult, ValuationSynthesis
from finrobot.engine.pipelines._helpers import execute_peer_analysis
from finrobot.engine.pipelines.equity_research import _execute_financial_modeling
from finrobot.engine.primitives.industry import is_bank
from finrobot.paths import SETTINGS_JSON
from finrobot.routes.settings import load_non_secret_settings
from finrobot.secret_store import create_secret_store
from finrobot.server import hydrate_settings_from_secrets

# Banks (the fix target) + non-bank controls (must be byte-identical to pre-change).
BASKET = sys.argv[1:] or ["JPM", "GS", "BAC", "WFC", "KO", "AAPL", "MU"]


async def _valuation_for(
    deps: FinRobotDeps, ticker: str
) -> tuple[ValuationSynthesis | None, bool, list[str], DDMResult | None]:
    """Run the deterministic valuation prefix of equity_research for one ticker.

    Returns (valuation_synthesis, gate_withhold, ev_findings, ddm_result)."""
    structured_context: dict[str, object] = {}
    _fin = await deps.data_layer.fetch_canonical(DataType.FINANCIALS, ticker)
    _price = await deps.data_layer.fetch_canonical(DataType.PRICE, ticker)
    structured_context["data_collection"] = extract_financial_data(_fin, _price)

    # Forward FY1 consensus so comps_pe takes the FORWARD path the real pipeline uses
    # (peer forward median P/E × target forward EPS), not the trailing fallback —
    # faithful to execute_financial_data_step. Best-effort.
    fin = structured_context["data_collection"]
    try:
        _fwd_raw = await deps.data_layer.fetch_canonical(DataType.FORWARD_ESTIMATES, ticker)
        structured_context["forward_estimates_raw"] = _fwd_raw.payload()
        structured_context["forward_financials"] = get_forward_financials(
            ticker=ticker,
            yf_info=None,
            fmp_analyst_estimates=_fwd_raw.payload(),
            trailing_net_income_usd=fin.income.net_income,
            trailing_revenue_usd=fin.income.revenue,
        )
    except (ProviderError, ValueError, KeyError, TypeError) as e:
        print(f"  (forward estimates unavailable for {ticker}: {e})", file=sys.stderr)

    # peer_analysis step (deterministic peer screen + multiples) → comps_pb / comps_pe.
    peer_out = await execute_peer_analysis(None, deps, "", structured_context, ticker)  # type: ignore[arg-type]
    if peer_out.structured is not None:
        structured_context["peer_analysis"] = peer_out.structured

    # The real financial_modeling executor — for a bank this now computes DDM and
    # threads it into build_valuation_synthesis.
    await _execute_financial_modeling(None, deps, "", structured_context, ticker)  # type: ignore[arg-type]

    vs = structured_context.get("valuation_synthesis")
    ddm = structured_context.get("ddm_calc")
    # numeric_audit gate (the EV blocked_field withhold lives here, separate from the
    # dial's own valuation_withheld). data_collection is the USD-normalized snapshot now.
    audit = audit_artifact(structured_context.get("data_collection"))  # type: ignore[arg-type]
    ev_findings = [
        f.check for f in audit.findings if f.field_key in ("enterprise_value", "ev_ebitda")
    ]
    return (
        vs if isinstance(vs, ValuationSynthesis) else None,
        audit.withhold_valuation,
        ev_findings,
        ddm if isinstance(ddm, DDMResult) else None,
    )


async def main() -> int:
    settings = get_settings(**load_non_secret_settings(SETTINGS_JSON))
    store, _ = create_secret_store()
    settings = await hydrate_settings_from_secrets(settings, store)
    dl = build_data_layer(settings)
    deps = FinRobotDeps(data_layer=dl, settings=settings)
    try:
        print(
            f"{'tkr':<6}{'bank':>5}{'price':>9}  {'methods (name=mid)':<46}"
            f"{'anchor':>9}{'target':>9}{'upside':>8}{'verdict':>9}{'dialW':>6}{'gateW':>6}  ev_findings"
        )
        print("-" * 150)

        for t in BASKET:
            try:
                vs, gate_withhold, ev_findings, ddm = await _valuation_for(deps, t)
            except Exception as e:  # noqa: BLE001
                print(f"{t:<6}  ERROR {str(e)[:80]}")
                continue
            if vs is None:
                print(f"{t:<6}  no valuation_synthesis (single/no method)")
                continue

            thesis = resolve_canonical_thesis(vs, t)
            methods_str = " ".join(f"{m.name}={m.mid:.0f}" for m in vs.methods)
            target = thesis.target
            upside = thesis.upside
            # is_bank from the snapshot industry (cache-hot re-fetch).
            _fin = await deps.data_layer.fetch_canonical(DataType.FINANCIALS, t)
            snap = extract_financial_data(
                _fin, await deps.data_layer.fetch_canonical(DataType.PRICE, t)
            )
            bank = "Y" if is_bank(industry=snap.market.industry, sector=snap.market.sector) else "."
            ddm_note = f" ddm={ddm.equity_value_per_share:.0f}" if ddm is not None else ""
            print(
                f"{t:<6}{bank:>5}{vs.current_price:>9.2f}  {methods_str:<46}"
                f"{(vs.anchor_method or '-'):>9}"
                f"{(f'${target:.0f}' if target is not None else 'WITHHELD'):>9}"
                f"{(f'{upside:+.1%}' if upside is not None else '-'):>8}"
                f"{(thesis.verdict or '-'):>9}{('Y' if vs.valuation_withheld else '.'):>6}"
                f"{('Y' if gate_withhold else '.'):>6}  {','.join(ev_findings) or '-'}{ddm_note}"
            )

        return 0
    finally:
        # Non-server entrypoint: join aiosqlite workers + checkpoint WAL so the process
        # exits cleanly instead of hanging on "Event loop is closed" (2026-06-24).
        from finrobot.engine.data.factory import shutdown_data_layer

        await shutdown_data_layer(dl)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
