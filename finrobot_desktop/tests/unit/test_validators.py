from finrobot.engine.pipelines.validators import (
    validate_has_fields,
    validate_is_non_empty,
    validate_has_peers,
    validate_has_thesis,
    validate_report_format,
    validate_has_comps_table,
    validate_dcf_output,
)


class TestValidateIsNonEmpty:
    def test_non_empty_string_passes(self):
        r = validate_is_non_empty("hello")
        assert r.passed is True
        assert r.error is None

    def test_empty_string_fails(self):
        r = validate_is_non_empty("")
        assert r.passed is False
        assert r.error is not None

    def test_whitespace_only_fails(self):
        r = validate_is_non_empty("   ")
        assert r.passed is False

    def test_newlines_only_fails(self):
        r = validate_is_non_empty("\n\n\t")
        assert r.passed is False

    def test_long_output_passes(self):
        r = validate_is_non_empty("Revenue: $100B\nEBITDA: $50B\n")
        assert r.passed is True


class TestValidateHasFields:
    def test_all_fields_present_passes(self):
        r = validate_has_fields("revenue is 100B, ebitda is 50B", ["revenue", "ebitda"])
        assert r.passed is True

    def test_missing_field_fails(self):
        r = validate_has_fields("revenue is 100B", ["revenue", "ebitda"])
        assert r.passed is False
        assert "ebitda" in r.error.lower()

    def test_all_missing_fails_with_all_in_error(self):
        r = validate_has_fields("nothing relevant here", ["revenue", "ebitda", "price_history"])
        assert r.passed is False
        assert "revenue" in r.error.lower()
        assert "ebitda" in r.error.lower()
        assert "price_history" in r.error.lower()

    def test_case_insensitive(self):
        r = validate_has_fields("REVENUE: $100B, EBITDA: $50B", ["revenue", "ebitda"])
        assert r.passed is True

    def test_underscore_matches_space(self):
        r = validate_has_fields("Price History: see chart below", ["price_history"])
        assert r.passed is True

    def test_underscore_matches_uppercase_spaced(self):
        r = validate_has_fields(
            "PRICE HISTORY and NET INCOME shown", ["price_history", "net_income"]
        )
        assert r.passed is True

    def test_empty_fields_list_passes(self):
        r = validate_has_fields("anything", [])
        assert r.passed is True


class TestValidateHasPeers:
    def test_with_3_tickers_passes(self):
        r = validate_has_peers("Peers: MSFT, GOOGL, META — all large-cap tech")
        assert r.passed is True

    def test_with_1_ticker_fails(self):
        r = validate_has_peers("The company's main competitor is MSFT in the market.")
        assert r.passed is False
        assert "ticker" in r.error.lower()

    def test_excludes_financial_acronyms(self):
        # WACC, DCF, EBITDA are NOT tickers
        r = validate_has_peers("We used WACC and DCF and EBITDA methods")
        assert r.passed is False

    def test_mixed_tickers_and_acronyms(self):
        r = validate_has_peers("MSFT, GOOGL, META with EBITDA and WACC analysis")
        assert r.passed is True


class TestValidateHasThesis:
    def test_recommendation_catalyst_risk_passes(self):
        r = validate_has_thesis(
            "We rate the stock Buy. Key catalyst: new product launch. "
            "Primary risk: regulatory headwinds."
        )
        assert r.passed is True

    def test_just_recommendation_fails(self):
        r = validate_has_thesis("Buy the stock.")
        assert r.passed is False


class TestValidateReportFormat:
    def test_proper_report_passes(self):
        report = "## Executive Summary\n\nWe rate AAPL Buy, target $250. " + "word " * 100 + "\n\n"
        report += "## Valuation\n\nDCF implies $240 at a 9% WACC. " + "word " * 80 + "\n\n"
        report += "## Risks\n\nFX exposure ~15% of revenue. " + "word " * 50
        r = validate_report_format(report)
        assert r.passed is True

    def test_chinese_report_passes(self):
        # Regression: a real Chinese report has CJK headers and no English
        # section keywords, and str.split() under-counts CJK ~10x. The old
        # validator false-failed every such report; the structural validator
        # must pass it. (See finrobot.log: "found 0 section keywords" loops.)
        report = (
            "## 执行摘要\n\n我们给予 AAPL 买入评级,目标价 250 美元。"
            "DCF、同业可比与 DDM 三种方法交叉验证后给出该结论。"
            * 8
            + "\n\n## 估值分析\n\n基于 9% 的 WACC,DCF 隐含价值约 240 美元。" * 8
            + "\n\n## 风险因素\n\n外汇敞口约占收入 15%,宏观波动构成主要下行风险。" * 8
        )
        r = validate_report_format(report)
        assert r.passed is True

    def test_no_headers_fails(self):
        r = validate_report_format("The stock is worth $250. " + "word " * 100)
        assert r.passed is False
        assert "header" in r.error.lower()

    def test_empty_or_stub_fails(self):
        r = validate_report_format("## Summary\n## Risk\n## Peer\nshort")
        assert r.passed is False
        assert "short" in r.error.lower()

    def test_no_numeric_data_fails(self):
        report = "## Summary\n\n" + "word " * 100 + "\n\n## Risk\n\n" + "word " * 100
        report += "\n\n## Outlook\n\n" + "word " * 50
        r = validate_report_format(report)
        assert r.passed is False
        assert "numeric" in r.error.lower()


class TestValidateHasCompsTable:
    def test_tickers_multiples_stats_passes(self):
        r = validate_has_comps_table(
            "MSFT: EV/EBITDA 20x, P/E 30x\n"
            "GOOGL: EV/EBITDA 18x, P/E 25x\n"
            "META: EV/EBITDA 15x, P/E 22x\n"
            "Median EV/EBITDA: 18x"
        )
        assert r.passed is True

    def test_missing_stats_fails(self):
        r = validate_has_comps_table("MSFT EV/EBITDA 20x, P/E 30x, GOOGL, META multiple comparison")
        assert r.passed is False
        assert "statistical" in r.error.lower() or "median" in r.error.lower()


class TestValidateDcfOutput:
    def test_3_components_passes(self):
        r = validate_dcf_output(
            "WACC: 10%, Terminal Value: $500B, Free Cash Flow projections, "
            "Sensitivity analysis shows range"
        )
        assert r.passed is True

    def test_just_dcf_mentioned_fails(self):
        r = validate_dcf_output("DCF analysis completed.")
        assert r.passed is False
        assert "component" in r.error.lower()
