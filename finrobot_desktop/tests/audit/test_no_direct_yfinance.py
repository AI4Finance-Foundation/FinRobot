"""Audit: no module touches yfinance directly outside the provider boundary.

门一收口 (BACKLOG P0 yfinance 直连收口): every price/financial series on the
report / dashboard / signal paths must flow through ``DataLayer`` →
provider abstraction, so provenance is honest and a provider swap is one file.

Allowed:
- ``providers/yfinance_provider.py`` + ``providers/fx.py`` — the legitimate
  yfinance boundary (the whole point is to confine the dependency here).
- ``engine/backtest/`` — opt-in extra, fully isolated (nothing in routes /
  pipelines / orchestrator / server / cli / sdk imports it), so its yf.download
  is off the credibility-critical path. Its own DataLayer 收口 is tracked
  separately in BACKLOG (needs a date-ranged historical-price capability the
  DataLayer doesn't yet expose). Remove this carve-out when backtest is wired.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "finrobot" / "engine"

_ALLOWED: set[Path] = {
    ENGINE / "data" / "providers" / "yfinance_provider.py",
    ENGINE / "data" / "providers" / "fx.py",
}
_ALLOWED_DIRS: set[Path] = {
    ENGINE / "backtest",
}

# Actual usage, not comments/strings: an import or a yf.<Ticker|download|Tickers> call.
_PATTERNS = (
    re.compile(r"^\s*import\s+yfinance", re.MULTILINE),
    re.compile(r"\byf\.Ticker\b"),
    re.compile(r"\byf\.download\b"),
    re.compile(r"\byf\.Tickers\b"),
)


def test_no_direct_yfinance_outside_provider_boundary() -> None:
    violations: list[str] = []
    for py in ENGINE.rglob("*.py"):
        if py in _ALLOWED or any(d in py.parents for d in _ALLOWED_DIRS):
            continue
        text = py.read_text()
        for pat in _PATTERNS:
            for m in pat.finditer(text):
                lineno = text[: m.start()].count("\n") + 1
                violations.append(f"  {py.relative_to(ROOT)}:{lineno} — {m.group(0).strip()!r}")
    assert not violations, (
        "Direct yfinance usage outside providers/ (+ backtest carve-out) — "
        "route through DataLayer / the provider abstraction:\n" + "\n".join(violations)
    )
