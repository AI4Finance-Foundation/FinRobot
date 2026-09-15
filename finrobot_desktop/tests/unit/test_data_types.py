from finrobot.engine.data.types import DataType


def test_data_type_values():
    assert DataType.FINANCIALS == "financials"
    assert DataType.PRICE == "price"
    assert DataType.NEWS == "news"
    assert DataType.EARNINGS == "earnings"
    assert DataType.FILINGS == "filings"
    assert DataType.PROFILE == "profile"
    assert DataType.RAG_10K == "10k_rag"


def test_data_type_is_str():
    assert isinstance(DataType.FINANCIALS, str)
    assert f"type={DataType.FINANCIALS}" == "type=financials"


def test_data_type_comparison_with_str():
    assert DataType.FINANCIALS == "financials"
    assert "price" == DataType.PRICE
