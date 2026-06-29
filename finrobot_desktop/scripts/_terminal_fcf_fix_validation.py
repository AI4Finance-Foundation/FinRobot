"""Empirical validation for the terminal-FCF reinvestment-anchor fix (CLAUDE.md 🔴 protocol).

Evidence pillars, against LIVE/canonical data, BEFORE touching production code:

1. Variable isolation — three configurations per ticker, only the terminal base moves:
     A 现状        : capex_T anchored on da_pct (current ``_terminal_fcf``)
     B 只改锚      : capex_T anchored on min(da_pct, capex_pct) — acquisition
                     amortization stops masquerading as perpetual reinvestment
     C 锚+NWC缩放  : B + terminal ΔNWC = median(ΔNWC/Δrev) × tg instead of the
                     historical-growth-era ΔNWC/revenue median held forever
2. Full-basket regression — AMD must revive (DCF died: terminal FCF −4.34e9 on
   HEAD run_7fa34496cb3a) WITHOUT TSLA collapsing back to ~$20 (capex>da names
   must not move on B), and KO/JNJ/MSFT must stay within a few percent.
3. Loss-maker / refuser sanity — MU & RIVN may legitimately keep refusing; the
   refusal reason must stay honest (negative explicit FCF), not flip to nonsense.

External benchmark anchoring the fix (SEC XBRL companyfacts, AMD FY2025,
fetched 2026-06-10): revenue $34.639B · capex $0.974B (2.8% of revenue) ·
OCF $7.709B → real FCF ≈ +$6.7B. Our seed: da_pct 12.3% vs capex_pct 2.5% —
GAAP D&A is dominated by Xilinx intangible amortization, NOT maintenance capex.

Run: `python scripts/_terminal_fcf_fix_validation.py [TICKERS...]`
(keychain FMP key via hydrate_settings_from_secrets — no backend needed).

NOTE: this was the PRE-fix evidence harness. After the fix landed in
``_terminal_fcf``, variant A (monkeypatch restore) is the new production
formula — A no longer reproduces the old bare-D&A anchor. Kept as the audit
record of the 2026-06-10 basket evidence, not as a re-runnable A/B harness.
"""

from __future__ import annotations

import asyncio
import math
import statistics
import sys

import finrobot.engine.compute.operators.dcf as dcf_mod
from finrobot.config import get_settings
from finrobot.engine.compute.coordinators.dcf_seed import seed_dcf_inputs_for_ticker
from finrobot.engine.data.factory import build_data_layer
from finrobot.engine.models.financial import DCFInputs
from finrobot.paths import SETTINGS_JSON
from finrobot.routes.settings import load_non_secret_settings
from finrobot.secret_store import create_secret_store
from finrobot.server import hydrate_settings_from_secrets

BASKET = sys.argv[1:] or ["AMD", "MU", "TSLA", "AAPL", "MSFT", "NVDA", "KO", "JNJ", "RIVN"]

_ORIG_TERMINAL_FCF = dcf_mod._terminal_fcf


def _terminal_fcf_b(inputs: DCFInputs, terminal_revenue: float, tg: float) -> float:
    """Variant B: maintenance anchor = min(da, capex)."""
    rev = terminal_revenue
    m = min(inputs.da_pct_revenue, inputs.capex_pct_revenue)
    da = rev * m
    ebit = rev * inputs.ebitda_margin - da
    capex = da * (1 + tg)
    return ebit * (1 - inputs.tax_rate) + da - capex - rev * inputs.nwc_pct_revenue


def _make_variant_c(terminal_nwc_pct: float):
    def _terminal_fcf_c(inputs: DCFInputs, terminal_revenue: float, tg: float) -> float:
        rev = terminal_revenue
        m = min(inputs.da_pct_revenue, inputs.capex_pct_revenue)
        da = rev * m
        ebit = rev * inputs.ebitda_margin - da
        capex = da * (1 + tg)
        return ebit * (1 - inputs.tax_rate) + da - capex - rev * terminal_nwc_pct

    return _terminal_fcf_c


def _implied_price(inputs: DCFInputs) -> str:
    try:
        return f"${dcf_mod.calculate_dcf(inputs).implied_price:,.2f}"
    except (ValueError, ArithmeticError) as e:
        return f"拒绝({str(e)[:60]}…)"


def _terminal_nwc_estimate(
    cwc: list[float | None], revenue: list[float | None], tg: float
) -> tuple[float, str]:
    """median(ΔNWC_build / Δrevenue) × tg — the marginal NWC ratio scaled to
    terminal growth. FMP changeInWorkingCapital carries cash-flow sign
    (negative = build), so build = −cwc. Only revenue-GROWTH years are
    meaningful for a marginal ratio."""
    ratios: list[float] = []
    for i in range(1, min(len(cwc), len(revenue))):
        c, r1, r0 = cwc[i], revenue[i], revenue[i - 1]
        if c is None or r1 is None or r0 is None:
            continue
        d_rev = r1 - r0
        if d_rev <= 0 or not all(map(math.isfinite, (c, d_rev))):
            continue
        ratios.append(-c / d_rev)
    if not ratios:
        return 0.01, "无有效增长年,回退 1.0%"
    level = max(-0.6, min(0.6, statistics.median(ratios)))
    pct = max(-0.05, min(0.05, level * tg))
    return pct, f"median(ΔNWC/Δrev)={level:.1%} × tg={tg:.1%} → {pct:.2%}"


async def main() -> int:
    settings = get_settings(**load_non_secret_settings(SETTINGS_JSON))
    store, _ = create_secret_store()
    settings = await hydrate_settings_from_secrets(settings, store)
    dl = build_data_layer(settings)

    try:
        for ticker in BASKET:
            print("=" * 96)
            try:
                fin, inputs = await seed_dcf_inputs_for_ticker(
                    dl, ticker, fmp_api_key=settings.fmp_api_key
                )
            except Exception as e:  # noqa: BLE001 — per-ticker isolation, basket must finish
                print(f"{ticker}: seed 失败 {type(e).__name__}: {str(e)[:120]}")
                continue

            price = fin.market.current_price if fin.market else None
            m = min(inputs.da_pct_revenue, inputs.capex_pct_revenue)
            print(
                f"{ticker}  市价=${price:,.2f}" if price else f"{ticker}  市价=N/A",
            )
            print(
                f"  种子: ebitda={inputs.ebitda_margin:.1%} da={inputs.da_pct_revenue:.1%} "
                f"capex={inputs.capex_pct_revenue:.1%} nwc={inputs.nwc_pct_revenue:.1%} "
                f"tax={inputs.tax_rate:.1%} → min锚={m:.1%}"
            )
            tg = inputs.terminal_growth_rate
            factor_a = (
                (inputs.ebitda_margin - inputs.da_pct_revenue) * (1 - inputs.tax_rate)
                - inputs.da_pct_revenue * tg
                - inputs.nwc_pct_revenue
            )
            factor_b = (
                (inputs.ebitda_margin - m) * (1 - inputs.tax_rate) - m * tg - inputs.nwc_pct_revenue
            )

            # 终值 NWC 缩放需要历史 ΔNWC/Δrev——从 coordinator 再取一次 historical
            from finrobot.engine.compute.coordinators.historical_extractor import (
                fetch_historical_metrics,
            )

            try:
                hist = await fetch_historical_metrics(dl, ticker)
                nwc_t, nwc_note = _terminal_nwc_estimate(
                    list(hist.change_in_working_capital or []), list(hist.revenue or []), tg
                )
            except Exception as e:  # noqa: BLE001
                nwc_t, nwc_note = inputs.nwc_pct_revenue, f"历史不可得({type(e).__name__}),沿用现值"
            factor_c = (inputs.ebitda_margin - m) * (1 - inputs.tax_rate) - m * tg - nwc_t
            print(
                f"  终值因子(每$1营收): A现状={factor_a:+.2%}  B改锚={factor_b:+.2%}  C锚+NWC={factor_c:+.2%}"
            )
            print(f"  终值NWC: {nwc_note}")

            dcf_mod._terminal_fcf = _ORIG_TERMINAL_FCF
            pa = _implied_price(inputs)
            dcf_mod._terminal_fcf = _terminal_fcf_b
            pb = _implied_price(inputs)
            dcf_mod._terminal_fcf = _make_variant_c(nwc_t)
            pc = _implied_price(inputs)
            dcf_mod._terminal_fcf = _ORIG_TERMINAL_FCF

            def _ratio(p: str) -> str:
                if not p.startswith("$") or not price:
                    return ""
                return f"({float(p[1:].replace(',', '')) / price:.2f}x)"

            print(f"  implied: A={pa}{_ratio(pa)}  B={pb}{_ratio(pb)}  C={pc}{_ratio(pc)}")

        print("=" * 96)
        print(
            "验收判据: AMD B/C 复活且向 comps 收敛 · TSLA B≈A(capex>da 不动) · KO/JNJ/MSFT |C−A|/A < 5%(NWC 本就≈0 的票) · MU/RIVN 拒绝原因仍诚实"
        )
        return 0
    finally:
        # Non-server entrypoint: join the aiosqlite workers + checkpoint WAL so the
        # process exits cleanly instead of hanging on "Event loop is closed" (2026-06-24).
        from finrobot.engine.data.factory import shutdown_data_layer

        await shutdown_data_layer(dl)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
