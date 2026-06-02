"""Audit: no direct yfinance access in finrobot/engine/ outside sanctioned gateways (门一).

All per-stock data must flow through DataLayer so the provider chain
(FMP → yfinance) and the future circuit-breaker (批3) cover every path. A direct
``import yfinance`` or ``yf.Ticker`` / ``yf.download`` / ``yf.Tickers`` call
bypasses both — it can't fall back to FMP and won't be tripped by the breaker.

Whitelist (user-ratified single-point gateways — low-frequency / non-stock,
NOT 收口 targets):
  - providers/yfinance_provider.py — THE yfinance provider
  - providers/fx.py                — single FX spot-rate gateway

compute/market.py was removed from this whitelist once its index/ETF display
(the only direct-yfinance user) was deleted and the technical snapshot moved
onto ``DataLayer.fetch_canonical(PRICE)`` (门一收口, ADR-0006).

backtest/backtrader_adapter.py was removed once it stopped calling
``yf.download`` and started pulling price bars through
``DataLayer.fetch_price_range`` (BUG-022) — the backtest now shares the provider
chain like every other path, so the exemption became a closeable hole.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "finrobot" / "engine"

_WHITELIST = {
    "finrobot/engine/data/providers/yfinance_provider.py",
    "finrobot/engine/data/providers/fx.py",
}
# yfinance entry points that hit the network directly.
_YF_CALL_ATTRS = {"Ticker", "Tickers", "download"}
_YF_BASE_NAMES = {"yf", "yfinance"}


def _engine_py_files() -> list[Path]:
    return sorted(p for p in ENGINE.rglob("*.py") if p.name != "__init__.py")


def _yfinance_violations(filepath: Path) -> list[tuple[int, str]]:
    """AST-detected direct yfinance usages (imports + yf.* call attributes).

    AST-based (not grep) so prose like "NaN pollution from yfinance" in a
    comment isn't a false positive — only real import / attribute nodes count.
    """
    tree = ast.parse(filepath.read_text(), filename=str(filepath))
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "yfinance" or alias.name.startswith("yfinance."):
                    out.append((node.lineno, f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "yfinance" or node.module.startswith("yfinance."):
                out.append((node.lineno, f"from {node.module} import ..."))
        elif isinstance(node, ast.Attribute) and node.attr in _YF_CALL_ATTRS:
            base = node.value
            if isinstance(base, ast.Name) and base.id in _YF_BASE_NAMES:
                out.append((node.lineno, f"{base.id}.{node.attr}(...)"))
    return out


class TestNoDirectYfinanceInEngine:
    """门一 收口 守门: the 6 historical yfinance direct-call sites stay收口'd."""

    def test_no_direct_yfinance_outside_whitelist(self) -> None:
        violations: list[str] = []
        for py in _engine_py_files():
            rel = py.relative_to(ROOT).as_posix()
            if rel in _WHITELIST:
                continue
            for lineno, what in _yfinance_violations(py):
                violations.append(
                    f"  {rel}:{lineno} — {what}\n"
                    f"  FIX: route through DataLayer (fetch / fetch_historical / "
                    f"fetch_quote / fetch_price). Direct yfinance bypasses the "
                    f"provider chain + 批3 circuit-breaker."
                )
        assert not violations, (
            "Direct yfinance access found in finrobot/engine/ outside the "
            "sanctioned single-point gateways (门一):\n" + "\n".join(violations)
        )

    def test_whitelist_entries_exist(self) -> None:
        """A whitelist entry pointing at a renamed/deleted file is a silent hole."""
        missing = sorted(w for w in _WHITELIST if not (ROOT / w).exists())
        assert not missing, f"Whitelist references non-existent files: {missing}"

    def test_whitelisted_gateways_actually_use_yfinance(self) -> None:
        """Each exemption must still touch yfinance; a stale one should be dropped
        so the net keeps tightening as code moves onto the DataLayer."""
        dead = sorted(w for w in _WHITELIST if not _yfinance_violations(ROOT / w))
        assert not dead, (
            "Whitelisted files no longer use yfinance — drop them from the "
            f"whitelist so the audit tightens: {dead}"
        )
