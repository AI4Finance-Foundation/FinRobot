#!/usr/bin/env python3
"""Live-verify CEO-name resolution across a representative basket.

For each ticker pulls the REAL DEF 14A + Form-4s via edgartools, runs the full
compute_ownership_governance path (Form-4 officer-title authority + DEF 14A
prose fallback), and prints the resolved CEO name plus which path won.

External-truth benchmark (2026-06): AAPL=Tim Cook, NVDA=Jensen Huang,
TSLA=Elon Musk, RIVN=RJ Scaringe, KO=James Quincey (NOT Braun, the incoming
COO->CEO), F=Jim Farley (NOT Shengpo Wu, the Ford-China divisional CEO),
SAP=None (foreign private issuer — no DEF 14A / Form-4, correctly abstains).

Run after touching ownership CEO-name logic to confirm no basket regression.
"""

from __future__ import annotations

import asyncio

from finrobot.config import get_settings
from finrobot.engine.compute.operators.ownership import (
    _ceo_name_from_insiders,
    _extract_ceo_name,
    build_insider_transactions,
    compute_ownership_governance,
)
from finrobot.engine.data.providers.edgar_provider import EdgarToolsProvider
from finrobot.paths import SETTINGS_JSON, ensure_home
from finrobot.routes.settings import load_non_secret_settings
from finrobot.secret_store import create_secret_store
from finrobot.server import hydrate_settings_from_secrets

BASKET = ("KO", "AAPL", "NVDA", "TSLA", "RIVN", "F", "SAP")


async def main() -> None:
    ensure_home()
    settings = get_settings(**load_non_secret_settings(SETTINGS_JSON))
    secret_store, _ = create_secret_store()
    settings = await hydrate_settings_from_secrets(settings, secret_store)

    provider = EdgarToolsProvider(user_agent=settings.sec_user_agent)
    from edgar import Company  # type: ignore[import-untyped]

    print(f"{'TICKER':<7}{'CEO (resolved)':<24}{'path':<10}{'prose-only':<22}")
    print("-" * 70)
    for ticker in BASKET:
        try:
            c = Company(ticker)
            proxy_raw, _ = provider._fetch_proxy(c)
            insider_raw, _ = provider._fetch_insider(c, days=400)
        except Exception as e:  # noqa: BLE001 — diagnostic script
            print(f"{ticker:<7}fetch error: {e}")
            continue

        insiders = build_insider_transactions(insider_raw or {})
        form4_ceo = _ceo_name_from_insiders(insiders)
        prose_only = _extract_ceo_name(str(proxy_raw.get("text") or ""))

        analysis = compute_ownership_governance(
            insider_data=insider_raw,
            institutional_data=None,
            proxy_data=proxy_raw,
        )
        resolved = analysis.proxy_compensation.ceo_name if analysis.proxy_compensation else None
        path = "Form-4" if form4_ceo else ("prose" if prose_only else "none")
        print(f"{ticker:<7}{str(resolved):<24}{path:<10}{str(prose_only):<22}")


if __name__ == "__main__":
    asyncio.run(main())
