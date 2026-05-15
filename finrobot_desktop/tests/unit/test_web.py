"""Tests for the FinAgent web UI (D.1-D.4)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from finagent.server import app
from finagent.web.tasks import clear_tasks


def _setup_test_deps() -> None:
    """Install minimal FakeDeps into app.state for web endpoint tests."""
    from datetime import datetime, timezone

    from finagent.config import get_settings
    from finagent.engine.agents.factory import create_sub_agents
    from finagent.engine.data.interface import DataResult
    from finagent.engine.deps import FinAgentDeps

    class FakeDataLayer:
        async def fetch(self, data_type: object, ticker: str, **kwargs: object) -> DataResult:
            return DataResult(
                data={
                    "revenue": 1e9,
                    "ebitda": 2e8,
                    "net_income": 1e8,
                    "market_cap": 5e9,
                    "shares_outstanding": 1e8,
                    "current_price": 50.0,
                    "gross_margin": 0.4,
                    "operating_margin": 0.15,
                    "price_history": [{"close": 50.0}],
                },
                provider="test",
                ticker=ticker,
                data_type=str(data_type),
                timestamp=datetime.now(tz=timezone.utc),
            )

    settings = get_settings(model_name="test")
    app.state.deps = FinAgentDeps(
        data_layer=FakeDataLayer(),  # type: ignore[arg-type]
        settings=settings,
        skill_runtime=None,
    )
    app.state.sub_agents = create_sub_agents(settings, skill_registry=None)


@pytest.fixture(autouse=True)
def _clean_tasks() -> None:
    """Clear the in-memory task store before each test."""
    clear_tasks()


class TestWebRouterImport:
    def test_web_router_can_be_imported(self) -> None:
        from finagent.web import web_router as router

        assert router is not None
        assert hasattr(router, "routes")


class TestIndexPage:
    @pytest.mark.asyncio
    async def test_index_returns_200_with_html(self) -> None:
        _setup_test_deps()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/web/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "FinAgent" in response.text
        assert "ticker" in response.text.lower()

    @pytest.mark.asyncio
    async def test_index_contains_pipeline_options(self) -> None:
        _setup_test_deps()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/web/")
        for pipeline in ("research", "comps", "dcf", "lbo", "earnings", "ic-memo"):
            assert pipeline in response.text


class TestRunEndpoint:
    @pytest.mark.asyncio
    async def test_run_returns_task_id(self) -> None:
        _setup_test_deps()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/web/run",
                json={"ticker": "AAPL", "pipeline_type": "research"},
            )
        assert response.status_code == 201
        data = response.json()
        assert "task_id" in data
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_run_rejects_invalid_pipeline(self) -> None:
        _setup_test_deps()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/web/run",
                json={"ticker": "AAPL", "pipeline_type": "invalid"},
            )
        assert response.status_code == 400
        assert "Invalid" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_run_rejects_empty_ticker(self) -> None:
        _setup_test_deps()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/web/run",
                json={"ticker": "  ", "pipeline_type": "research"},
            )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_run_returns_429_when_too_many_running(self) -> None:
        from finagent.web.tasks import TaskStatus, create_task

        _setup_test_deps()
        # Manually create 3 tasks in running state
        for i in range(3):
            t = create_task(f"T{i}", "research")
            t.status = TaskStatus.RUNNING

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/web/run",
                json={"ticker": "AAPL", "pipeline_type": "research"},
            )
        assert response.status_code == 429
        assert "Too many running tasks" in response.json()["error"]


class TestStatusEndpoint:
    @pytest.mark.asyncio
    async def test_status_returns_task_info(self) -> None:
        _setup_test_deps()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Create a task first
            run_resp = await client.post(
                "/api/web/run",
                json={"ticker": "MSFT", "pipeline_type": "dcf"},
            )
            task_id = run_resp.json()["task_id"]

            # Check status
            status_resp = await client.get(f"/api/web/status/{task_id}")
        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data["task_id"] == task_id
        assert data["ticker"] == "MSFT"
        assert data["pipeline_type"] == "dcf"
        assert data["status"] in ("pending", "running", "complete", "error")
        assert isinstance(data["logs"], list)

    @pytest.mark.asyncio
    async def test_status_404_for_unknown_task(self) -> None:
        _setup_test_deps()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/web/status/nonexistent")
        assert response.status_code == 404


class TestHistoryEndpoint:
    @pytest.mark.asyncio
    async def test_history_returns_list(self) -> None:
        _setup_test_deps()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/web/history")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_history_includes_created_task(self) -> None:
        _setup_test_deps()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                "/api/web/run",
                json={"ticker": "GOOG", "pipeline_type": "comps"},
            )
            response = await client.get("/api/web/history")
        data = response.json()
        assert len(data) >= 1
        tickers = [t["ticker"] for t in data]
        assert "GOOG" in tickers


class TestReportsPage:
    @pytest.mark.asyncio
    async def test_reports_page_returns_200(self) -> None:
        _setup_test_deps()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/web/reports")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestReportViewPage:
    @pytest.mark.asyncio
    async def test_report_view_404_for_unknown_task(self) -> None:
        _setup_test_deps()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/web/report/nonexistent")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_report_view_200_for_existing_task(self) -> None:
        _setup_test_deps()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            run_resp = await client.post(
                "/api/web/run",
                json={"ticker": "TSLA", "pipeline_type": "research"},
            )
            task_id = run_resp.json()["task_id"]
            response = await client.get(f"/web/report/{task_id}")
        assert response.status_code == 200
        assert "iframe" in response.text
        assert "TSLA" in response.text
