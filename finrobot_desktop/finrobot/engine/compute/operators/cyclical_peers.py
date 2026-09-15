"""Curated commodity-cyclical peer groups for deterministic comps injection.

Why this exists (empirically, scripts/_cyclical_probe_peers.py 2026-06-11): the
two provider industry tags BOTH fail to put a memory/storage cyclical and its real
trading comps in one bucket. MU is tagged generic "Semiconductors" (with NVDA/AMD/
AVGO); its FMP ``stock_peers`` and ``industry_screen`` are ALL logic/equipment/
software names — ZERO storage. The storage makers (WDC/STX/SNDK) sit only in MU's
``sector_screen`` (Tier 3), which ``screen_peers`` SKIPS once the high-affinity
tiers field ≥3 candidates. So MU's auto-selected comps are logic semis whose
growth-stock forward P/E (≈37x) × MU's cycle-peak forward EPS prints a $2199 fair
value — the artifact this map fixes.

The fix mirrors ``_ALIAS_MAP`` / ``is_bank``: a hand-curated deterministic constant
(NOT an LLM judgement, NOT a volatility heuristic) that injects the real cyclical
peer group into Tier 1 (``industry_screen``) so it survives the Tier-3 skip and the
size band. Kept in lock-step with ``industry._MEMORY_STORAGE_TICKERS`` (the seed-path
anchor) — both name the same memory/storage cohort.
"""

from __future__ import annotations

from typing import Any, Final

from finrobot.engine.compute.operators.peer_screen import PeerScreenResult, screen_peers

# Commodity-cyclical cohorts that互为同行. Each ticker maps to the full peer group
# (itself included; the caller drops the target). Normalized (upper, no exchange
# suffix). Future cohorts (steel / oil&gas / shipping) slot in as new keys.
_CYCLICAL_PEER_MAP: Final[dict[str, tuple[str, ...]]] = {
    # Memory / storage — DRAM/NAND/HDD price-cycle peers. SNDK (2025 spin from WDC)
    # has only 1y of standalone history → fine as a CURRENT-multiple comp (P/B), but
    # the through-cycle medians exclude it (no cycle history) downstream.
    "MU": ("MU", "WDC", "STX", "SNDK"),
    "WDC": ("MU", "WDC", "STX", "SNDK"),
    "STX": ("MU", "WDC", "STX", "SNDK"),
    "SNDK": ("MU", "WDC", "STX", "SNDK"),
}


def cyclical_peer_group(ticker: str) -> tuple[str, ...]:
    """The curated cyclical peer group for ``ticker`` (excluding the ticker itself).

    Returns an empty tuple when the ticker is not in a curated cohort — the caller
    then leaves the provider's screen untouched. The target is dropped from the
    group so a caller can splice the rest straight into a peer pool.
    """
    group = _CYCLICAL_PEER_MAP.get(ticker.strip().upper())
    if not group:
        return ()
    t = ticker.strip().upper()
    return tuple(p for p in group if p != t)


def inject_cyclical_peers(payload: dict[str, Any], ticker: str) -> dict[str, Any]:
    """Splice the curated commodity-cyclical peer group into Tier 1 (industry_screen).

    A memory/storage cyclical's real comps (WDC/STX/SNDK for MU) sit ONLY in the
    provider's ``sector_screen`` (Tier 3), which ``screen_peers`` skips once the
    high-affinity tiers field ≥3 logic-semis candidates — so MU's auto-comps are
    growth-stock logic semis whose forward P/E × MU's cycle-peak EPS prints $2199
    (scripts/_cyclical_probe_peers.py). Prepending the curated group to Tier 1 lands
    it in the high-affinity tier (wide 200x floor band, never the Tier-3 skip), so
    the storage cohort survives. Returns the payload unchanged for a non-cyclical
    target; otherwise a shallow copy with ``industry_screen`` rewritten (the cached
    payload dict is never mutated). A spliced peer still needs a provider quote to
    pass ``screen_peers`` — if the provider omitted it the peer is dropped, same as
    any candidate (fail-safe to the existing behaviour).
    """
    group = cyclical_peer_group(ticker)
    if not group:
        return payload
    existing = [str(s).upper() for s in (payload.get("industry_screen") or [])]
    # Prepend the curated cohort (dedup, preserve provider order after).
    seen: set[str] = set()
    merged: list[str] = []
    for sym in (*group, *existing):
        up = sym.upper()
        if up not in seen:
            seen.add(up)
            merged.append(up)
    new_payload = dict(payload)
    new_payload["industry_screen"] = merged
    return new_payload


def screen_peers_with_cyclical(payload: dict[str, Any], ticker: str) -> PeerScreenResult:
    """Single entry point for comps peer selection: cyclical injection + protected
    screen. Every consumer (the comps pipeline AND the orchestrator/analysis prompt
    path) MUST go through here so they yield the identical set — a memory/storage
    target that gets the cohort injected on one path but raw-screened on the other
    would print two different peer sheets for the same ticker. Curated cohort
    members are both injected into Tier 1 AND marked protected (bypass the role gate
    + pinned ahead of the size-proximity race) — see ``screen_peers``.
    """
    injected = inject_cyclical_peers(payload, ticker)
    protected = frozenset(cyclical_peer_group(ticker))
    return screen_peers(injected, ticker, protected_peers=protected)
