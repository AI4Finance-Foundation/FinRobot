"""Semantic version diff — turns two artifacts into an analyst-grade delta.

Replaces the old ``diff.py`` whole-tree ``model_dump`` recursion (which leaked
schema paths, guessed units from path substrings, and drowned the signal in
``data_fetched_at`` noise). This module answers the analyst's real question —
"why did my conclusion change, and how much did each assumption move it?" — with
a curated, opt-in white-list (``DIFF_SPEC``), backend-given units (via
``field_registry``), and确定性 attribution (single-factor re-pricing through the
existing ``compute_dcf_implied_price`` pure function — no LLM produces a number).

LAYER (ADR-0005 / ADR-0010): this is in ``finrobot/artifact/`` — a consumer above
``compute/``. It *calls into* compute (re-pricing) but adds no math of its own and
must not be imported by compute operators. Attribution numbers come only from the
deterministic re-pricer; if a contribution can't be re-priced it falls into an
explicit, named residual — never silently absorbed, never LLM-narrated.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from finrobot.artifact.field_registry import REGISTRY, FieldCaliber, format_caliber_value
from finrobot.artifact.models import Artifact
from finrobot.artifact.summary_extractor import (
    extract_entry_price,
    extract_target_price,
    extract_verdict,
)
from finrobot.engine.compute.operators.signal import _ensure_tz

# Period gap (days) beyond which two TTM snapshots likely straddle an earnings
# season and their absolute fundamentals are no longer like-for-like.
_PERIOD_DRIFT_DAYS = 80

# Numeric equality tolerance for "did this assumption actually move?".
_EPS = 1e-9

# A per-share contribution below this rounds to "$0.00" at display precision, so
# it is NOT a driver of the change — naming a $0.00 contributor as the "主因"
# (which a raw rank would do when only an un-attributable assumption like tax_rate
# moved) is misleading. Such near-zero contributions stay in the named residual.
_NEGLIGIBLE_CONTRIBUTION = 0.005


# ── Contract ─────────────────────────────────────────────────────────────────

Direction = Literal["up", "down", "flat", "added", "removed"]
Sentiment = Literal["positive", "negative", "neutral"]


class DeltaItem(BaseModel):
    """One compared field, fully formatted by the backend — the frontend renders
    ``formatted_*`` verbatim and uses the numeric fields only for colouring."""

    key: str
    label_zh: str
    label_en: str
    old_value: float | str | None
    new_value: float | str | None
    formatted_old: str
    formatted_new: str
    pct_change: float | None = None
    formatted_pct_change: str | None = None
    direction: Direction = "flat"
    sentiment: Sentiment = "neutral"
    comparable: bool = True
    caliber_note: str | None = None
    is_user_override: bool = False
    contribution: float | None = None
    formatted_contribution: str | None = None


class AttributionItem(BaseModel):
    driver_key: str
    label_zh: str
    label_en: str
    contribution: float
    formatted_contribution: str


class Attribution(BaseModel):
    """Single-factor decomposition of the DCF fair-value change. Each item holds
    all-else-constant and re-prices one assumption; the residual is the explicit,
    named remainder (DCF is non-linear, so contributions don't sum to the total)."""

    available: bool
    disabled_reason: str | None = None
    items: list[AttributionItem] = Field(default_factory=list)
    total_change: float = 0.0
    formatted_total: str = ""
    residual: float = 0.0
    formatted_residual: str = ""
    summary_zh: str = ""
    summary_en: str = ""


class ComparabilityFlag(BaseModel):
    kind: Literal["formula", "data_source", "period", "peer_set"]
    message_zh: str
    message_en: str
    blocks_attribution: bool = False


class DataFootnote(BaseModel):
    a_source: str
    b_source: str
    a_fetched_at: str
    b_fetched_at: str
    currency: str | None
    currency_assumed: bool


class SemanticDelta(BaseModel):
    a_id: str
    b_id: str
    a_label: str
    b_label: str
    report_type: str
    identical: bool
    conclusion: list[DeltaItem] = Field(default_factory=list)
    attribution: Attribution
    drivers: list[DeltaItem] = Field(default_factory=list)
    comparability: list[ComparabilityFlag] = Field(default_factory=list)
    data_footnote: DataFootnote


# ── DIFF_SPEC: the curated white-list ────────────────────────────────────────
# Drivers shown in the B-section. Only fields here are diffed — adding a field to
# the UI means登记 it, which is what keeps data_fetched_at noise and schema drift
# out. attribution="recompute" means the contribution comes from the re-pricer.

_DRIVER_SPEC: tuple[tuple[str, str], ...] = (
    # (registry key, attribution mode)
    ("wacc", "recompute"),
    ("terminal_growth", "recompute"),
    ("tax_rate", "none"),
    ("revenue_cagr", "none"),
    ("equity_value", "none"),
    ("enterprise_value", "none"),
)

# Rating rank for sentiment of a recommendation change.
_RATING_RANK: dict[str, int] = {
    "strong sell": 0,
    "sell": 1,
    "underperform": 1,
    "underweight": 1,
    "reduce": 1,
    "hold": 2,
    "neutral": 2,
    "market perform": 2,
    "equal-weight": 2,
    "buy": 3,
    "outperform": 3,
    "overweight": 3,
    "accumulate": 3,
    "strong buy": 4,
}


# ── Artifact accessors (per-type layout) ─────────────────────────────────────


def _dcf_result(art: Artifact) -> dict[str, Any] | None:
    """Locate the DCFResult dump inside an artifact, by type."""
    s = art.outputs.structured
    if art.type == "dcf":
        return s if isinstance(s, dict) and "implied_price" in s else None
    if art.type == "equity_research":
        fm = s.get("financial_modeling") if isinstance(s, dict) else None
        return fm if isinstance(fm, dict) and "implied_price" in fm else None
    if art.type == "ic_memo":
        dr = s.get("dcf_result") if isinstance(s, dict) else None
        return dr if isinstance(dr, dict) and "implied_price" in dr else None
    return None


def _dcf_inputs_dump(art: Artifact) -> dict[str, Any] | None:
    """Locate the DCFInputs dump (assumption parameters) inside an artifact."""
    params = art.assumptions.parameters
    if not isinstance(params, dict):
        return None
    if art.type == "ic_memo":
        di = params.get("dcf_inputs")
        return di if isinstance(di, dict) else None
    # dcf / equity_research: parameters IS the DCFInputs dump
    return params if "terminal_growth_rate" in params else None


def _revenue_cagr(inputs_dump: dict[str, Any] | None) -> float | None:
    """Geometric CAGR implied by the projected revenue growth schedule."""
    if not inputs_dump:
        return None
    rates = inputs_dump.get("revenue_growth_rates")
    if not isinstance(rates, list) or not rates:
        return None
    prod = 1.0
    for r in rates:
        if not isinstance(r, (int, float)):
            return None
        prod *= 1.0 + float(r)
    return float(prod ** (1.0 / len(rates)) - 1.0)


# ── Currency resolution ──────────────────────────────────────────────────────


def _resolve_currency(a: Artifact, b: Artifact) -> tuple[str | None, bool]:
    """Resolve the quote currency for per-share/absolute formatting.

    Today's artifacts don't carry a currency tag in the DCF path (it lives on
    CompanyFinancials, which isn't persisted). We look for an explicit tag first
    (forward-compatible for非美股 in 阶段3); absent that, we fall back to USD and
    report ``assumed=True`` so the UI can disclose the assumption rather than
    silently stamp "$". Disclosed assumption ≠ fabricated number.
    """
    for art in (b, a):  # prefer the newer artifact's tag
        inp = _dcf_inputs_dump(art)
        if inp and isinstance(inp.get("currency"), str):
            return inp["currency"], False
        raw = art.inputs.raw_data
        if isinstance(raw, dict):
            for key in ("quote_currency", "currency"):
                if isinstance(raw.get(key), str):
                    return raw[key], False
    return "USD", True


# ── Item builders ────────────────────────────────────────────────────────────


def _sentiment(direction: Direction, semantics: str) -> Sentiment:
    if direction in ("flat", "added", "removed"):
        return "neutral"
    if semantics == "neutral":
        return "neutral"
    good_up = semantics == "higher_better"
    if direction == "up":
        return "positive" if good_up else "negative"
    return "negative" if good_up else "positive"


def _numeric_item(
    caliber: FieldCaliber,
    old: float | None,
    new: float | None,
    *,
    currency: str | None,
    comparable: bool = True,
    caliber_note: str | None = None,
    is_user_override: bool = False,
) -> DeltaItem:
    direction: Direction
    pct: float | None = None
    if old is None and new is not None:
        direction = "added"
    elif new is None and old is not None:
        direction = "removed"
    elif old is None and new is None:
        direction = "flat"
    else:
        assert old is not None and new is not None
        delta = new - old
        direction = "up" if delta > _EPS else "down" if delta < -_EPS else "flat"
        straddles_zero = (old <= 0 <= new) or (new <= 0 <= old)
        if comparable and abs(old) > _EPS and not (caliber.sign_flip_sensitive and straddles_zero):
            pct = delta / abs(old)
    fmt_old = format_caliber_value(caliber, old, currency=currency)
    fmt_new = format_caliber_value(caliber, new, currency=currency)
    # If the change is invisible at display precision (e.g. 16.599% vs 16.601%
    # both render "16.6%"), don't show an arrow / pct the analyst can't see —
    # treat it as flat. Keeps the identical-version check honest too.
    if direction in ("up", "down") and fmt_old == fmt_new:
        direction = "flat"
    # A pct badge only means something on a move — a flat row (incl. an exact
    # 0.0 delta) carries no "+0.0%" noise next to two identical values.
    if direction != "up" and direction != "down":
        pct = None
    shown_pct = pct if comparable else None
    return DeltaItem(
        key=caliber.key,
        label_zh=caliber.label_zh,
        label_en=caliber.label_en,
        old_value=old,
        new_value=new,
        formatted_old=fmt_old,
        formatted_new=fmt_new,
        pct_change=shown_pct,
        # Backend owns every display string — the frontend renders this verbatim
        # rather than re-deriving "×100, sign, one decimal" itself.
        formatted_pct_change=(f"{shown_pct * 100:+.1f}%" if shown_pct is not None else None),
        direction=direction,
        sentiment=_sentiment(direction, caliber.direction_semantics),
        comparable=comparable,
        caliber_note=caliber_note,
        is_user_override=is_user_override,
    )


def _rating_item(old: str | None, new: str | None) -> DeltaItem:
    ro = _RATING_RANK.get((old or "").strip().lower())
    rn = _RATING_RANK.get((new or "").strip().lower())
    direction: Direction = "flat"
    sentiment: Sentiment = "neutral"
    if ro is not None and rn is not None and ro != rn:
        direction = "up" if rn > ro else "down"
        sentiment = "positive" if rn > ro else "negative"
    elif old != new:
        direction = "flat"  # changed wording but unknown rank → no colour claim
    return DeltaItem(
        key="recommendation",
        label_zh="评级",
        label_en="Rating",
        old_value=old,
        new_value=new,
        formatted_old=old or "—",
        formatted_new=new or "—",
        direction=direction,
        sentiment=sentiment,
    )


# ── Attribution ──────────────────────────────────────────────────────────────


def _build_attribution(
    a: Artifact,
    a_dcf: dict[str, Any] | None,
    b_dcf: dict[str, Any] | None,
    blocked_reason: str | None,
    currency: str | None,
    assumptions_moved: bool,
) -> Attribution:
    from finrobot.engine.compute.operators.dcf import compute_dcf_implied_price
    from finrobot.engine.models.financial import DCFInputs

    fair = REGISTRY["implied_price"]

    if a_dcf is None or b_dcf is None:
        return Attribution(available=False, disabled_reason="本类型不支持估值贡献拆解")
    a_implied = a_dcf.get("implied_price")
    b_implied = b_dcf.get("implied_price")
    if not isinstance(a_implied, (int, float)) or not isinstance(b_implied, (int, float)):
        return Attribution(available=False, disabled_reason="缺少 DCF 公允价值，无法归因")

    total = float(b_implied) - float(a_implied)
    fmt_total = format_caliber_value(fair, total, currency=currency)

    if blocked_reason is not None:
        # Formula differs → subtracting outputs of two different formulas is a
        # math error. Show the move but refuse to attribute it.
        return Attribution(
            available=False,
            disabled_reason=blocked_reason,
            total_change=total,
            formatted_total=fmt_total,
        )

    a_inputs_dump = _dcf_inputs_dump(a)
    if not a_inputs_dump:
        return Attribution(
            available=False,
            disabled_reason="缺少可复算的 DCF 假设",
            total_change=total,
            formatted_total=fmt_total,
        )
    try:
        a_inputs = DCFInputs(**a_inputs_dump)
    except (TypeError, ValueError):
        return Attribution(
            available=False,
            disabled_reason="DCF 假设无法复算",
            total_change=total,
            formatted_total=fmt_total,
        )

    items: list[AttributionItem] = []
    # (override key for re-pricer, old value, new value, registry key)
    plan: list[tuple[str, float | None, float | None, str]] = [
        ("wacc", _num(a_dcf.get("wacc")), _num(b_dcf.get("wacc")), "wacc"),
        (
            "terminal_growth",
            _num(a_inputs_dump.get("terminal_growth_rate")),
            _num(_b_param(b_dcf, "terminal_growth_rate")),
            "terminal_growth",
        ),
    ]
    attributed = 0.0
    for override_key, old_v, new_v, reg_key in plan:
        if old_v is None or new_v is None or abs(new_v - old_v) <= _EPS:
            continue
        try:
            repriced = compute_dcf_implied_price(a_inputs, {override_key: new_v})
        except (ValueError, KeyError):
            # e.g. terminal_growth >= wacc — can't isolate; leave in residual.
            continue
        contribution = repriced - float(a_implied)
        # The assumption moved but its price impact rounds to zero → not a driver
        # of the change. Drop it (it stays in the residual) rather than letting it
        # surface as a $0.00 "主因".
        if abs(contribution) < _NEGLIGIBLE_CONTRIBUTION:
            continue
        attributed += contribution
        cal = REGISTRY[reg_key]
        items.append(
            AttributionItem(
                driver_key=reg_key,
                label_zh=cal.label_zh,
                label_en=cal.label_en,
                contribution=contribution,
                formatted_contribution=format_caliber_value(fair, contribution, currency=currency),
            )
        )

    residual = total - attributed
    summary_zh, summary_en = _attribution_summary(
        total, items, residual, fair, currency, assumptions_moved
    )
    return Attribution(
        available=True,
        items=items,
        total_change=total,
        formatted_total=fmt_total,
        residual=residual,
        formatted_residual=format_caliber_value(fair, residual, currency=currency),
        summary_zh=summary_zh,
        summary_en=summary_en,
    )


def _attribution_summary(
    total: float,
    items: list[AttributionItem],
    residual: float,
    fair: FieldCaliber,
    currency: str | None,
    assumptions_moved: bool,
) -> tuple[str, str]:
    if not items:
        if abs(total) < _NEGLIGIBLE_CONTRIBUTION:
            return "公允价值基本未变。", "Fair value essentially unchanged."
        fmt = format_caliber_value(fair, total, currency=currency)
        if assumptions_moved:
            # Assumptions DID move, but only ones the re-pricer can't isolate yet
            # (e.g. tax_rate / revenue CAGR). Be honest about the limitation rather
            # than naming a $0.00 driver or falsely claiming "assumptions unchanged".
            return (
                f"公允价值变化 {fmt}，主要来自暂不支持逐项拆解的假设（如税率 / 营收增速）与数据重估。",
                f"Fair value moved {fmt}, mainly from assumptions not yet isolable "
                "(e.g. tax rate / revenue growth) and data re-basing.",
            )
        # No assumption moved at all → pure data-driven re-basing.
        return (
            f"假设未变，公允价值变化 {fmt} 来自数据基数（如实际财报数字）的更新。",
            f"Assumptions unchanged; the {fmt} fair-value move comes from updated data inputs.",
        )
    ranked = sorted(items, key=lambda it: abs(it.contribution), reverse=True)
    top = ranked[:2]
    parts_zh = "、".join(f"{it.label_zh}（{it.formatted_contribution}）" for it in top)
    parts_en = ", ".join(f"{it.label_en} ({it.formatted_contribution})" for it in top)
    resid_zh = (
        f"；其余 {format_caliber_value(fair, residual, currency=currency)} 来自交互项与数据重估"
        if abs(residual) > _EPS
        else ""
    )
    resid_en = (
        f"; the remaining {format_caliber_value(fair, residual, currency=currency)} "
        "is interaction terms and data re-basing"
        if abs(residual) > _EPS
        else ""
    )
    return (
        f"公允价值变化 {format_caliber_value(fair, total, currency=currency)}，主因 {parts_zh}{resid_zh}。",
        f"Fair value moved {format_caliber_value(fair, total, currency=currency)}, "
        f"driven by {parts_en}{resid_en}.",
    )


# ── Small helpers ────────────────────────────────────────────────────────────


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


def _b_param(b_dcf: dict[str, Any], key: str) -> Any:
    # terminal_growth_rate lives in the DCFInputs dump nested under the result.
    inp = b_dcf.get("inputs")
    if isinstance(inp, dict) and key in inp:
        return inp[key]
    return None


def _version_label(art: Artifact) -> str:
    created = art.meta.created_at
    return f"{art.type} · {created:%Y-%m-%d %H:%M}" if created else art.id[:16]


def _peer_tickers(art: Artifact) -> list[str]:
    s = art.outputs.structured
    if not isinstance(s, dict):
        return []
    peer_block = s.get("peer_analysis") or s.get("statistical_bench")
    if not isinstance(peer_block, dict):
        return []
    peers = peer_block.get("peers")
    if not isinstance(peers, list):
        return []
    out: list[str] = []
    for peer in peers:
        if isinstance(peer, dict) and isinstance(peer.get("ticker"), str):
            out.append(peer["ticker"].upper())
        elif isinstance(peer, str):
            out.append(peer.upper())
    return out


def _valuation_method_mid(art: Artifact, method_name: str) -> float | None:
    s = art.outputs.structured
    if not isinstance(s, dict):
        return None
    synth = s.get("valuation_synthesis")
    if not isinstance(synth, dict):
        return None
    methods = synth.get("methods")
    if not isinstance(methods, list):
        return None
    for method in methods:
        if not isinstance(method, dict):
            continue
        name = method.get("name") or method.get("method")
        if name == method_name:
            return _num(method.get("mid"))
    return None


def _peer_set_item(a: Artifact, b: Artifact) -> tuple[DeltaItem | None, ComparabilityFlag | None]:
    old = _peer_tickers(a)
    new = _peer_tickers(b)
    if not old and not new:
        return None, None
    if old == new:
        return None, None

    old_set = set(old)
    new_set = set(new)
    removed = [t for t in old if t not in new_set]
    added = [t for t in new if t not in old_set]
    note_parts = []
    if removed and added:
        note_parts.append(f"{'/'.join(removed)}→{'/'.join(added)}")
    elif removed:
        note_parts.append(f"剔除 {'/'.join(removed)}")
    elif added:
        note_parts.append(f"新增 {'/'.join(added)}")
    note = "；".join(note_parts) if note_parts else None

    item = DeltaItem(
        key="peer_set",
        label_zh="同业集合",
        label_en="Peer set",
        old_value=", ".join(old),
        new_value=", ".join(new),
        formatted_old=", ".join(old) or "—",
        formatted_new=", ".join(new) or "—",
        direction="flat",
        sentiment="neutral",
        comparable=False,
        caliber_note=note,
    )

    a_mid = _valuation_method_mid(a, "comps_pe")
    b_mid = _valuation_method_mid(b, "comps_pe")
    if a_mid is None or b_mid is None or abs(a_mid) <= _EPS:
        return item, None
    pct = (b_mid - a_mid) / abs(a_mid)
    if abs(pct) <= 0.10:
        return item, None

    fmt_pct = f"{pct * 100:+.1f}%"
    msg_zh = (
        f"同业集合变更：{note or item.formatted_old + ' → ' + item.formatted_new}；"
        f"comps_pe 中值变化 {fmt_pct}，版本差异含样本变化，不只是模型假设变化。"
    )
    msg_en = (
        f"Peer set changed: {note or item.formatted_old + ' -> ' + item.formatted_new}; "
        f"comps_pe mid moved {fmt_pct}. This version delta includes sample selection, "
        "not only model assumptions."
    )
    return item, ComparabilityFlag(
        kind="peer_set",
        message_zh=msg_zh,
        message_en=msg_en,
    )


# ── Entry point ──────────────────────────────────────────────────────────────


def build_semantic_delta(a: Artifact, b: Artifact) -> SemanticDelta:
    """Compare two artifacts (a = older/base, b = newer/compare) into a
    decision-oriented delta. See module docstring for the design contract."""
    currency, currency_assumed = _resolve_currency(a, b)

    # — comparability gate —
    flags: list[ComparabilityFlag] = []
    blocked_reason: str | None = None
    if a.compute_version.formula_id != b.compute_version.formula_id:
        blocked_reason = (
            f"计算公式不同（{a.compute_version.formula_id} → {b.compute_version.formula_id}），"
            "两版数字不可相减归因，仅并列展示。"
        )
        flags.append(
            ComparabilityFlag(
                kind="formula",
                message_zh=blocked_reason,
                message_en=(
                    f"Compute formula changed ({a.compute_version.formula_id} → "
                    f"{b.compute_version.formula_id}); values are shown side by side, "
                    "attribution disabled."
                ),
                blocks_attribution=True,
            )
        )
    if a.inputs.data_source != b.inputs.data_source:
        flags.append(
            ComparabilityFlag(
                kind="data_source",
                message_zh=(
                    f"数据源不同（{a.inputs.data_source} → {b.inputs.data_source}），"
                    "口径可能不一致。"
                ),
                message_en=(
                    f"Data source changed ({a.inputs.data_source} → {b.inputs.data_source}); "
                    "calibers may differ."
                ),
            )
        )
    # Normalise both timestamps before subtracting — JSON-round-tripped artifacts
    # may carry a naive data_fetched_at while a sibling carries a tz-aware one;
    # a bare subtraction would raise TypeError (offset-naive vs offset-aware).
    gap_days = abs(
        (_ensure_tz(b.inputs.data_fetched_at) - _ensure_tz(a.inputs.data_fetched_at)).days
    )
    if gap_days > _PERIOD_DRIFT_DAYS:
        flags.append(
            ComparabilityFlag(
                kind="period",
                message_zh=(f"两版数据相隔 {gap_days} 天，可能跨财报季，TTM 口径已滚动。"),
                message_en=(
                    f"Snapshots are {gap_days} days apart — likely across an earnings "
                    "season; TTM windows have rolled."
                ),
            )
        )

    peer_item, peer_flag = _peer_set_item(a, b)
    if peer_flag is not None:
        flags.append(peer_flag)

    a_dcf = _dcf_result(a)
    b_dcf = _dcf_result(b)
    a_inp = _dcf_inputs_dump(a)
    b_inp = _dcf_inputs_dump(b)
    period_drift = any(f.kind == "period" for f in flags)

    # — conclusion (A section) —
    conclusion: list[DeltaItem] = []
    rec_a, rec_b = extract_verdict(a), extract_verdict(b)
    if rec_a is not None or rec_b is not None:
        conclusion.append(_rating_item(rec_a, rec_b))
    tp_a, tp_b = extract_target_price(a), extract_target_price(b)
    cp_a, cp_b = extract_entry_price(a), extract_entry_price(b)
    conclusion.append(_numeric_item(REGISTRY["target_price"], tp_a, tp_b, currency=currency))
    conclusion.append(_numeric_item(REGISTRY["current_price"], cp_a, cp_b, currency=currency))
    up_a = _upside(tp_a, cp_a)
    up_b = _upside(tp_b, cp_b)
    if up_a is not None or up_b is not None:
        conclusion.append(_numeric_item(REGISTRY["upside"], up_a, up_b, currency=currency))
    # DCF fair value as a distinct row only where it differs from the headline
    # target (equity_research / ic_memo). For a plain DCF artifact the target IS
    # the implied price — showing it twice is noise.
    if a.type in ("equity_research", "ic_memo") and (a_dcf is not None or b_dcf is not None):
        conclusion.append(
            _numeric_item(
                REGISTRY["implied_price"],
                _num(a_dcf.get("implied_price")) if a_dcf else None,
                _num(b_dcf.get("implied_price")) if b_dcf else None,
                currency=currency,
            )
        )

    # — drivers (B section) —
    overrides_a = (
        a.assumptions.user_overrides if isinstance(a.assumptions.user_overrides, dict) else {}
    )
    overrides_b = (
        b.assumptions.user_overrides if isinstance(b.assumptions.user_overrides, dict) else {}
    )
    drivers: list[DeltaItem] = []
    for reg_key, _mode in _DRIVER_SPEC:
        old_v, new_v = _driver_values(reg_key, a, b, a_dcf, b_dcf, a_inp, b_inp)
        if old_v is None and new_v is None:
            continue
        cal = REGISTRY[reg_key]
        # absolute fundamentals across an earnings season aren't like-for-like
        comparable = not (period_drift and cal.unit == "currency_abs")
        note = "口径已变更（TTM 已滚动）" if not comparable else None
        is_override = reg_key in overrides_a or reg_key in overrides_b
        drivers.append(
            _numeric_item(
                cal,
                old_v,
                new_v,
                currency=currency,
                comparable=comparable,
                caliber_note=note,
                is_user_override=is_override,
            )
        )
    if peer_item is not None:
        drivers.append(peer_item)

    _ASSUMPTION_KEYS = {"wacc", "terminal_growth", "tax_rate", "revenue_cagr"}
    assumptions_moved = any(
        d.key in _ASSUMPTION_KEYS and d.direction in ("up", "down") for d in drivers
    )
    attribution = _build_attribution(a, a_dcf, b_dcf, blocked_reason, currency, assumptions_moved)

    identical = (
        all(it.direction == "flat" for it in conclusion)
        and all(it.direction == "flat" for it in drivers)
        and peer_item is None
    )

    return SemanticDelta(
        a_id=a.id,
        b_id=b.id,
        a_label=_version_label(a),
        b_label=_version_label(b),
        report_type=b.type,
        identical=identical,
        conclusion=conclusion,
        attribution=attribution,
        drivers=drivers,
        comparability=flags,
        data_footnote=DataFootnote(
            a_source=a.inputs.data_source,
            b_source=b.inputs.data_source,
            a_fetched_at=a.inputs.data_fetched_at.isoformat(),
            b_fetched_at=b.inputs.data_fetched_at.isoformat(),
            currency=currency,
            currency_assumed=currency_assumed,
        ),
    )


def _upside(tp: float | None, cp: float | None) -> float | None:
    if tp is None or cp is None or abs(cp) <= _EPS:
        return None
    return (tp - cp) / cp


def _driver_values(
    reg_key: str,
    a: Artifact,
    b: Artifact,
    a_dcf: dict[str, Any] | None,
    b_dcf: dict[str, Any] | None,
    a_inp: dict[str, Any] | None,
    b_inp: dict[str, Any] | None,
) -> tuple[float | None, float | None]:
    if reg_key == "wacc":
        return (
            _num(a_dcf.get("wacc")) if a_dcf else None,
            _num(b_dcf.get("wacc")) if b_dcf else None,
        )
    if reg_key == "terminal_growth":
        return (
            _num(a_inp.get("terminal_growth_rate")) if a_inp else None,
            _num(b_inp.get("terminal_growth_rate")) if b_inp else None,
        )
    if reg_key == "tax_rate":
        return (
            _num(a_inp.get("tax_rate")) if a_inp else None,
            _num(b_inp.get("tax_rate")) if b_inp else None,
        )
    if reg_key == "revenue_cagr":
        return _revenue_cagr(a_inp), _revenue_cagr(b_inp)
    if reg_key in ("equity_value", "enterprise_value"):
        return (
            _num(a_dcf.get(reg_key)) if a_dcf else None,
            _num(b_dcf.get(reg_key)) if b_dcf else None,
        )
    return None, None
