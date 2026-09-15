"""Industry-relative beta sanity: a vendor beta implausibly far below a NORMAL-beta
industry is a short-window regression artifact → use the industry proxy. Must NOT be
an absolute floor — genuinely low-beta defensive sectors (low industry beta) are
structurally exempt and keep their raw low beta (dcf-recall red line).
"""

from __future__ import annotations

from finrobot.engine.compute.operators.dcf_seed import (
    _BETA_IMPLAUSIBLY_LOW_REASON,
    _BETA_RELATIVE_FLOOR,
    _BETA_RELATIVE_INDUSTRY_MIN,
    _pick_with_provenance,
)


def _pick(ticker_beta: float, industry_beta: float) -> tuple[float, str]:
    return _pick_with_provenance(
        ticker_value=ticker_beta,
        ticker_label="provider beta",
        industry_value=industry_beta,
        industry_label="industry levered beta",
        floor=0.0,
        ceiling=5.0,
        reject_value_fmt="{:.2f}",
        relative_floor=_BETA_RELATIVE_FLOOR,
        relative_floor_industry_min=_BETA_RELATIVE_INDUSTRY_MIN,
        relative_reject_reason=_BETA_IMPLAUSIBLY_LOW_REASON,
    )


def test_mtb_low_beta_in_normal_industry_uses_proxy() -> None:
    # MTB β 0.59 in Banks-Regional β 0.91 → vendor noise → proxy. (0.59 < 0.7×0.91.)
    value, source = _pick(0.587, 0.9121)
    assert value == 0.9121
    assert "implausibly low" in source


def test_normal_bank_beta_kept_raw() -> None:
    # PNC β 0.92 ≈ its 0.91 industry → kept raw (not below 0.7×0.91).
    value, source = _pick(0.918, 0.9121)
    assert value == 0.918
    assert source == "provider beta"


def test_low_beta_defensive_sector_is_exempt() -> None:
    # A utility β 0.40 in a LOW-beta industry (β 0.50 < 0.8 guard) is real, not noise:
    # the relative check does not fire, the raw low beta is kept (NOT floored up).
    value, source = _pick(0.40, 0.50)
    assert value == 0.40
    assert source == "provider beta"


def test_deep_low_beta_in_low_industry_still_exempt() -> None:
    # Even a very low utility β 0.30 vs its 0.50 industry stays raw — the industry-min
    # guard (0.8) exempts the whole low-beta sector, so true low-beta is never误伤ed.
    value, source = _pick(0.30, 0.50)
    assert value == 0.30
    assert source == "provider beta"
