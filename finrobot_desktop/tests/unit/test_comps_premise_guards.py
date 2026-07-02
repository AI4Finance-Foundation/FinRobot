"""comps_pe 方法级前提守卫:n<3 的「中位数」与极端倍数错位必须诚实退出。

实证背景(2026-06-10,art_…TSLA_equity_research_0f4251):TSLA 的同业集只剩
TM/GM 两家,其中只有 GM 带 forward P/E——「同业中位 forward P/E 5.8x」实为
GM 一家的倍数,乘 TSLA forward EPS $1.88 印出 $10.93;同时 TSLA 自身 forward
P/E 322x 与 5.8x 相差 55 倍,「向同业收敛」的方法前提被市场十几年定价持续
否定。两道守卫都在 ``_comps_pe_method``(唯一权威构建点)内,退出原因进
aggregate_valuation 的 warnings。
"""

from __future__ import annotations

from finrobot.engine.compute.operators.valuation_aggregator import _comps_pe_method
from finrobot.engine.models.financial import CompanyFinancials, PeerComps


def _comps(
    *,
    median_forward_pe: float | None = None,
    forward_pe_sample_n: int = 0,
    target_forward_pe: float | None = None,
    median_pe: float | None = None,
    pe_sample_n: int = 0,
    target_pe: float | None = None,
) -> PeerComps:
    target = CompanyFinancials(
        ticker="TGT",
        revenue=100e9,
        market_cap=500e9,
        net_income=10e9,
        forward_pe=target_forward_pe,
        pe_ratio=target_pe,
        reporting_currency="USD",
    )
    peer = CompanyFinancials(
        ticker="PEER", revenue=120e9, market_cap=80e9, reporting_currency="USD"
    )
    return PeerComps(
        target=target,
        peers=[peer],
        median_forward_pe=median_forward_pe,
        forward_pe_sample_n=forward_pe_sample_n,
        median_pe=median_pe,
        pe_sample_n=pe_sample_n,
    )


class TestThinSampleGuard:
    def test_forward_median_of_one_peer_refuses(self):
        """TSLA 形状:forward P/E 中位数背后只有 1 家(GM)→ 方法退出 + 原因进 warnings。"""
        warnings: list[str] = []
        comps = _comps(median_forward_pe=5.8, forward_pe_sample_n=1)
        m = _comps_pe_method(comps, 1.88, shares_outstanding=3.2e9, warnings=warnings)
        assert m is None
        assert any("sample is only 1" in w for w in warnings)

    def test_forward_median_of_three_passes_but_downweighted(self):
        """3 家中位数越过 n<3 硬闸 → 方法保留、mid 正确,但样本薄(<4)→ 置信降权
        + 一句可读披露(降权不砍方法,contract ②)。"""
        warnings: list[str] = []
        comps = _comps(median_forward_pe=33.0, forward_pe_sample_n=3)
        m = _comps_pe_method(comps, 7.47, shares_outstanding=1.6e9, warnings=warnings)
        assert m is not None
        assert abs(m.mid - 33.0 * 7.47) < 1e-9
        # Method retained, confidence DOWNWEIGHTED (0.80 → 0.80 × 0.7 = 0.56).
        assert m.confidence == round(0.80 * 0.7, 3)
        assert any("thin sample" in w and "confidence reduced" in w for w in warnings)
        # NOT a "method withheld" line — it must not be forwarded to the synthesis
        # basis prose (which only picks up withheld reasons).
        assert not any("method withheld" in w for w in warnings)

    def test_forward_median_of_four_full_confidence_no_downweight(self):
        """n≥4(KO=6 / JPM=6 形状)→ 满置信,零降权、零披露。"""
        warnings: list[str] = []
        comps = _comps(median_forward_pe=33.0, forward_pe_sample_n=4)
        m = _comps_pe_method(comps, 7.47, shares_outstanding=1.6e9, warnings=warnings)
        assert m is not None
        assert m.confidence == 0.80
        assert warnings == []

    def test_sample_n_zero_means_unknown_and_trusts_median(self):
        """手工构造 / 旧缓存的 PeerComps 没有样本数(默认 0)——计数未知时不拒绝,
        与历史行为一致(test_cross_currency_valuation 的构造方式)。"""
        comps = _comps(median_forward_pe=22.0, forward_pe_sample_n=0)
        m = _comps_pe_method(comps, 3.10, shares_outstanding=5.2e9)
        assert m is not None

    def test_trailing_median_thin_sample_refuses_symmetrically(self):
        """兄弟分支同闸:forward 不可得走 trailing as-reported,样本同样要 ≥3。"""
        warnings: list[str] = []
        comps = _comps(median_pe=19.4, pe_sample_n=2)
        m = _comps_pe_method(comps, None, shares_outstanding=3.2e9, warnings=warnings)
        assert m is None
        assert any("sample is only 2" in w for w in warnings)


class TestMultipleMismatchGuard:
    def test_tsla_shaped_55x_mismatch_refuses(self):
        """标的自身 322x vs 同业中位 5.8x = 55 倍——收敛前提不适用,方法退出。"""
        warnings: list[str] = []
        comps = _comps(median_forward_pe=5.8, forward_pe_sample_n=4, target_forward_pe=322.4)
        m = _comps_pe_method(comps, 1.88, shares_outstanding=3.2e9, warnings=warnings)
        assert m is None
        assert any("56x away" in w or "55x away" in w for w in warnings)

    def test_amd_shaped_2x_premium_passes(self):
        """正常龙头溢价(AMD 63.6x vs 33x = 1.9x)必须继续定价——守卫只拦荒谬错位。"""
        comps = _comps(median_forward_pe=33.0, forward_pe_sample_n=6, target_forward_pe=63.6)
        m = _comps_pe_method(comps, 7.47, shares_outstanding=1.6e9)
        assert m is not None

    def test_mu_shaped_2_4x_discount_passes(self):
        """MU 15.7x vs 37.3x = 2.4x 折价——同样放行(周期错配由周期股正常化解决,
        单方法校准带兜底,不靠这道守卫误杀)。"""
        comps = _comps(median_forward_pe=37.3, forward_pe_sample_n=6, target_forward_pe=15.7)
        m = _comps_pe_method(comps, 58.92, shares_outstanding=1.1e9)
        assert m is not None

    def test_target_multiple_unavailable_skips_premise_check(self):
        """标的自身倍数缺失(亏损等)无法评估前提——不误杀,照常定价。"""
        comps = _comps(median_forward_pe=20.0, forward_pe_sample_n=5, target_forward_pe=None)
        m = _comps_pe_method(comps, 2.0, shares_outstanding=1e9)
        assert m is not None
