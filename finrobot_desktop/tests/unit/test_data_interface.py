from datetime import datetime, timezone

import pytest

from finrobot.engine.data.interface import DataProvider, DataResult, ProviderError


def make_result(**kwargs) -> DataResult:
    defaults = dict(
        data={"revenue": 1_000_000},
        provider="test",
        ticker="AAPL",
        data_type="financials",
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return DataResult(**defaults)


class TestDataResult:
    def test_to_context_string_readable(self):
        result = make_result()
        s = result.to_context_string()
        assert "AAPL" in s
        assert "financials" in s
        assert "revenue" in s
        assert "1000000" in s

    def test_to_context_string_includes_warnings(self):
        result = make_result(warnings=["stale data from cache"])
        s = result.to_context_string()
        assert "stale data from cache" in s

    def test_to_context_string_no_warnings_section_when_empty(self):
        result = make_result(warnings=[])
        s = result.to_context_string()
        assert "Warnings" not in s


class TestDataProvider:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            DataProvider()  # type: ignore

    def test_subclass_without_abstractmethods_raises(self):
        class Incomplete(DataProvider):
            pass

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore

    def test_concrete_subclass_works(self):
        class Concrete(DataProvider):
            @property
            def name(self) -> str:
                return "concrete"

            def capabilities(self) -> list[str]:
                return ["financials"]

            async def fetch(self, ticker: str, data_type: str, **kwargs) -> DataResult:
                return make_result(ticker=ticker, data_type=data_type)

        provider = Concrete()
        assert provider.name == "concrete"
        assert provider.capabilities() == ["financials"]


class TestProviderError:
    def test_is_exception(self):
        err = ProviderError("something failed")
        assert isinstance(err, Exception)
        assert str(err) == "something failed"

    def test_can_raise_and_catch(self):
        with pytest.raises(ProviderError, match="fetch failed"):
            raise ProviderError("fetch failed")
