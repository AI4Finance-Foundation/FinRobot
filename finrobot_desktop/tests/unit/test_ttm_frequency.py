"""FMP TTM aggregation-window sizing: sum 4 quarters for a quarterly filer, 2
half-years for a semi-annual one, so a semi-annual issuer's TTM isn't double-counted.

Anchored to live FMP `period=quarter` payloads (2026-07-06): UL/RIO/BHP/DEO return
6-month rows dated ~Dec-31 / ~Jun-30 (labelled Q4/Q2), while AAPL/KO/JPM/TSM return
4 three-month rows. The detector reads the cadence off the fiscal period-end dates.
"""

from finrobot.engine.data.providers.fmp_provider import (
    _period_end_months_apart,
    _ttm_trailing_row_count,
)


def _rows(dates: list[str]) -> list[dict[str, str]]:
    return [{"date": d} for d in dates]


class TestPeriodEndMonthsApart:
    def test_quarterly_gap(self):
        assert _period_end_months_apart("2025-12-31", "2025-09-30") == 3

    def test_semiannual_gap(self):
        assert _period_end_months_apart("2025-12-31", "2025-06-30") == 6

    def test_year_boundary(self):
        assert _period_end_months_apart("2026-03-31", "2025-12-31") == 3

    def test_unparseable_returns_none(self):
        assert _period_end_months_apart("not-a-date", "2025-06-30") is None
        assert _period_end_months_apart("2025-12-31", "") is None


class TestTtmTrailingRowCount:
    def test_quarterly_four_rows_uses_four(self):
        # AAPL-like: consecutive ~3-month period-ends → sum 4 (byte-identical path).
        rows = _rows(["2026-03-28", "2025-12-27", "2025-09-27", "2025-06-28"])
        assert _ttm_trailing_row_count(rows) == 4

    def test_semiannual_four_rows_uses_two(self):
        # UL/RIO/BHP-like: consecutive ~6-month period-ends → sum 2 (= 12 months),
        # not 4 (= 24 months, the doubling bug).
        rows = _rows(["2025-12-31", "2025-06-30", "2024-12-31", "2024-06-30"])
        assert _ttm_trailing_row_count(rows) == 2

    def test_semiannual_three_rows_uses_two(self):
        rows = _rows(["2025-12-31", "2025-06-30", "2024-12-31"])
        assert _ttm_trailing_row_count(rows) == 2

    def test_quarterly_missing_one_quarter_stays_four(self):
        # THE trap: a quarterly filer missing Dec-2025 → gaps [6, 3, 3] months. A
        # single fake 6-month gap must NOT be read as semi-annual and halve the TTM.
        rows = _rows(["2026-03-31", "2025-09-30", "2025-06-30", "2025-03-31"])
        assert _ttm_trailing_row_count(rows) == 4

    def test_too_few_rows_defaults_quarterly(self):
        # <3 dated rows can't establish a consistent cadence → default 4 (the norm;
        # and 2 six-month rows already sum to 12 months under a 4-window slice anyway).
        assert _ttm_trailing_row_count(_rows(["2025-12-31", "2025-06-30"])) == 4
        assert _ttm_trailing_row_count(_rows(["2025-12-31"])) == 4
        assert _ttm_trailing_row_count([]) == 4

    def test_missing_date_fields_default_quarterly(self):
        rows = [{"revenue": 1.0}, {"revenue": 2.0}, {"revenue": 3.0}]
        assert _ttm_trailing_row_count(rows) == 4  # type: ignore[arg-type]
