"""Field caliber registry — single source of truth for how each financial
field shown in the version-diff view is labelled, what unit it carries, in what
currency and accounting period, and which direction counts as an improvement.

WHY this exists (ADR-0010): ``DCFResult`` / ``PeerComps`` fields are bare floats
with no unit metadata (see ``engine/models/financial.py``). Formatting used to
live in the frontend, which guessed units from path substrings — so
``book_value_per_share`` matched the ``value`` substring and rendered as ``$B``.
That is a "报错一个数字 = 砸招牌" bug. This registry moves unit / caliber /
currency to a backend-owned table so every consumer formats a number from one
definition instead of guessing. The diff view is the first consumer; PDF export
and share-card are expected to收口 here next (tracked in ADR-0010).

LAYER (ADR-0005): this module lives in ``finrobot/artifact/`` — a CONSUMER layer
*above* ``compute/``. It must never be imported by ``compute/`` operators:
``label_*`` and ``formatter`` are presentation concerns and would pollute the
deterministic leaf layer.

CALIBER NOTE: ``period`` and ``currency_source`` are accounting口径, not cosmetics.
They drive the diff's comparability gate — comparing a TTM revenue against an
NTM revenue, or a quote-currency price against a reporting-currency one, is not a
like-for-like delta and the gate uses these tags to decide when to suppress the
delta and only show the two values side by side.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ── Vocabulary ───────────────────────────────────────────────────────────────

Unit = Literal[
    "percent",  # stored as a decimal (0.082) → displayed ×100 with "%"
    "currency_per_share",  # a per-share monetary amount in the quote currency
    "currency_abs",  # an absolute monetary amount (revenue, EV …) with B/M/K
    "ratio",  # a dimensionless ratio shown as-is
    "multiple",  # a valuation multiple shown with an "x" suffix (12.5x)
    "count",  # an integer count (shares, peers …)
    "years",  # a number of years
]

CurrencySource = Literal[
    "quote",  # market-quote currency — CompanyFinancials.quote_currency
    "reporting",  # income-statement currency — CompanyFinancials.reporting_currency
]

Period = Literal["TTM", "NTM", "FY"]

Direction = Literal["higher_better", "lower_better", "neutral"]


class FieldCaliber(BaseModel):
    """One field's display + accounting口径 definition.

    Immutable reference data; instances live in ``REGISTRY`` keyed by ``key``.
    """

    key: str
    label_zh: str
    label_en: str
    unit: Unit
    currency_source: CurrencySource | None = Field(
        default=None,
        description=(
            "Which artifact currency tag applies. MUST be set when unit is a "
            "currency_* unit, MUST be None otherwise (enforced by tests)."
        ),
    )
    period: Period | None = None
    decimals: int = 2
    direction_semantics: Direction = "neutral"
    sign_flip_sensitive: bool = Field(
        default=False,
        description=(
            "True when a sign change makes a percentage-change meaningless "
            "(e.g. EPS −1 → +1 is not '+200%'). Consumers must suppress "
            "pct_change for these fields when old and new straddle zero."
        ),
    )


# ── The registry ─────────────────────────────────────────────────────────────
# Only the fields the version-diff DIFF_SPEC actually references are登记 here.
# The structure is the system-wide SoT (PDF / share-card will add their fields
# later, ADR-0010), but this PR fills only the diff's working set.

_CALIBERS: tuple[FieldCaliber, ...] = (
    # — DCF assumptions —
    FieldCaliber(
        key="wacc",
        label_zh="WACC",
        label_en="WACC",
        unit="percent",
        decimals=1,
        direction_semantics="lower_better",
    ),
    FieldCaliber(
        key="terminal_growth",
        label_zh="永续增长率",
        label_en="Terminal growth",
        unit="percent",
        decimals=1,
        direction_semantics="higher_better",
    ),
    FieldCaliber(
        key="tax_rate",
        label_zh="税率",
        label_en="Tax rate",
        unit="percent",
        decimals=1,
        direction_semantics="lower_better",
    ),
    FieldCaliber(
        key="revenue_cagr",
        label_zh="营收 CAGR",
        label_en="Revenue CAGR",
        unit="percent",
        decimals=1,
        direction_semantics="higher_better",
    ),
    # — DCF / valuation outputs (per-share) —
    FieldCaliber(
        key="implied_price",
        label_zh="DCF 公允价值",
        label_en="DCF fair value",
        unit="currency_per_share",
        currency_source="quote",
        period="NTM",
        decimals=2,
    ),
    FieldCaliber(
        key="target_price",
        label_zh="目标价",
        label_en="Target price",
        unit="currency_per_share",
        currency_source="quote",
        period="NTM",
        decimals=2,
    ),
    FieldCaliber(
        key="current_price",
        label_zh="现价",
        label_en="Current price",
        unit="currency_per_share",
        currency_source="quote",
        decimals=2,
    ),
    FieldCaliber(
        key="book_value_per_share",
        # Pinned to per-share — this field撞过 the $B substring bug.
        label_zh="每股账面价值",
        label_en="Book value / share",
        unit="currency_per_share",
        currency_source="quote",
        decimals=2,
    ),
    FieldCaliber(
        key="upside",
        label_zh="上行空间",
        label_en="Upside",
        unit="percent",
        decimals=1,
        direction_semantics="higher_better",
    ),
    # Reverse-DCF: the annual revenue growth the CURRENT market price implies.
    # neutral direction — a rising market-implied growth is not "good" or "bad",
    # it just raises the bar the price already assumes. The diff promotes this
    # over DCF fair value in REVIEW state (where implied_price is withheld/None).
    FieldCaliber(
        key="implied_growth",
        label_zh="市场隐含增长",
        label_en="Market-implied growth",
        unit="percent",
        decimals=1,
        direction_semantics="neutral",
        sign_flip_sensitive=False,
    ),
    # — Valuation outputs (absolute) —
    FieldCaliber(
        key="equity_value",
        label_zh="股权价值",
        label_en="Equity value",
        unit="currency_abs",
        currency_source="reporting",
        decimals=1,
    ),
    FieldCaliber(
        key="enterprise_value",
        label_zh="企业价值",
        label_en="Enterprise value",
        unit="currency_abs",
        currency_source="reporting",
        decimals=1,
    ),
    # — Fundamentals (absolute, TTM → may drift across earnings seasons) —
    FieldCaliber(
        key="revenue",
        label_zh="营收",
        label_en="Revenue",
        unit="currency_abs",
        currency_source="reporting",
        period="TTM",
        decimals=1,
    ),
    FieldCaliber(
        key="ebitda",
        label_zh="EBITDA",
        label_en="EBITDA",
        unit="currency_abs",
        currency_source="reporting",
        period="TTM",
        decimals=1,
    ),
    FieldCaliber(
        key="net_income",
        label_zh="净利润",
        label_en="Net income",
        unit="currency_abs",
        currency_source="reporting",
        period="TTM",
        decimals=1,
        sign_flip_sensitive=True,
    ),
    # — Multiples (no $, no ×100, just "x") —
    FieldCaliber(
        key="forward_pe",
        label_zh="前瞻 P/E",
        label_en="Forward P/E",
        unit="multiple",
        period="NTM",
        decimals=1,
    ),
    FieldCaliber(
        key="ev_ebitda",
        label_zh="EV/EBITDA",
        label_en="EV/EBITDA",
        unit="multiple",
        period="NTM",
        decimals=1,
    ),
    FieldCaliber(
        key="median_pe",
        label_zh="同业中位 P/E",
        label_en="Median P/E",
        unit="multiple",
        period="TTM",
        decimals=1,
    ),
    FieldCaliber(
        key="median_ev_ebitda",
        label_zh="同业中位 EV/EBITDA",
        label_en="Median EV/EBITDA",
        unit="multiple",
        period="TTM",
        decimals=1,
    ),
    # — LBO returns —
    FieldCaliber(
        key="irr",
        label_zh="IRR",
        label_en="IRR",
        unit="percent",
        decimals=1,
        direction_semantics="higher_better",
    ),
    FieldCaliber(
        key="moic",
        label_zh="MOIC",
        label_en="MOIC",
        unit="multiple",
        decimals=2,
        direction_semantics="higher_better",
    ),
)

REGISTRY: dict[str, FieldCaliber] = {c.key: c for c in _CALIBERS}


# ── Currency symbols ─────────────────────────────────────────────────────────
# The currency CODE comes from the artifact (quote_currency / reporting_currency);
# the registry never assumes USD. Unknown codes fall back to a "<CODE> " prefix
# so we never silently mislabel a currency.

_CURRENCY_SYMBOLS: dict[str, str] = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "CNY": "¥",
    "HKD": "HK$",
    "KRW": "₩",
    "INR": "₹",
    "CAD": "C$",
    "AUD": "A$",
}


def _symbol(currency: str | None) -> str:
    if not currency:
        return ""
    code = currency.upper()
    sym = _CURRENCY_SYMBOLS.get(code)
    return sym if sym is not None else f"{code} "


def _fmt_abs_currency(value: float, symbol: str, decimals: int) -> str:
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    if abs_val >= 1e12:
        return f"{sign}{symbol}{abs_val / 1e12:,.{decimals}f}T"
    if abs_val >= 1e9:
        return f"{sign}{symbol}{abs_val / 1e9:,.{decimals}f}B"
    if abs_val >= 1e6:
        return f"{sign}{symbol}{abs_val / 1e6:,.{decimals}f}M"
    if abs_val >= 1e3:
        return f"{sign}{symbol}{abs_val / 1e3:,.{decimals}f}K"
    return f"{sign}{symbol}{abs_val:,.{decimals}f}"


def format_caliber_value(
    caliber: FieldCaliber,
    value: float | int | None,
    *,
    currency: str | None = None,
) -> str:
    """Format ``value`` per its ``caliber`` — the ONLY place a diff number turns
    into a display string. No path-substring guessing: ``caliber.unit`` decides.

    Args:
        caliber: the field's registry entry.
        value: the raw stored value (percent units are decimals, e.g. 0.082).
        currency: ISO 4217 code resolved from the artifact for currency units.
            Ignored for non-currency units. None → no symbol (never assume USD).

    Returns:
        A human display string; "—" for None.
    """
    if value is None:
        return "—"
    unit = caliber.unit
    if unit == "percent":
        return f"{value * 100:.{caliber.decimals}f}%"
    if unit == "currency_per_share":
        return f"{_symbol(currency)}{value:,.{caliber.decimals}f}"
    if unit == "currency_abs":
        return _fmt_abs_currency(float(value), _symbol(currency), caliber.decimals)
    if unit == "multiple":
        return f"{value:.{caliber.decimals}f}x"
    if unit == "count":
        return f"{value:,.0f}"
    if unit == "years":
        return f"{value:.0f}y"
    # ratio (and any future dimensionless unit)
    return f"{value:.{caliber.decimals}f}"
