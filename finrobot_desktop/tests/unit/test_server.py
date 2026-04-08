import pytest
import httpx
from httpx import ASGITransport, AsyncClient

from finagent.server import app


@pytest.fixture
async def client():
    # Use lifespan="on" to trigger app lifespan events (populates app.state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestHealthEndpoint:
    async def test_health_returns_200(self, client):
        response = await client.get("/health")
        assert response.status_code == 200

    async def test_health_returns_ready_status(self, client):
        response = await client.get("/health")
        data = response.json()
        assert data["status"] == "ready"
        assert data["phase"] == "P2c"


class TestChatEndpoint:
    async def test_chat_endpoint_exists_and_accepts_post(self):
        """Verify route exists by manually setting app.state before request.
        ASGITransport doesn't trigger lifespan events."""
        from pydantic_ai.models.test import TestModel

        from finagent.config import get_settings
        from finagent.engine.deps import FinAgentDeps
        from finagent.engine.orchestrator import create_lead_agent

        settings = get_settings(model_name="test")
        agent = create_lead_agent(settings)
        app.state.agent = agent
        app.state.deps = FinAgentDeps(
            data_layer=None, settings=settings  # type: ignore[arg-type]
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            response = await c.post("/chat", json={})
        assert response.status_code != 404
        assert response.status_code != 405


class TestReportEndpoints:
    @staticmethod
    def _setup_deps_with_cache(cache: dict | None = None):
        from finagent.config import get_settings
        from finagent.engine.deps import FinAgentDeps

        settings = get_settings(model_name="test")
        app.state.deps = FinAgentDeps(
            data_layer=None,  # type: ignore[arg-type]
            settings=settings,
            report_cache=cache or {},
        )

    @pytest.mark.asyncio
    async def test_report_html_returns_404_without_cache(self):
        self._setup_deps_with_cache()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/report/html?ticker=AAPL")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_report_html_requires_ticker(self):
        self._setup_deps_with_cache()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/report/html")
        assert response.status_code == 422  # FastAPI validation error

    @pytest.mark.asyncio
    async def test_report_pdf_returns_404_without_cache(self):
        self._setup_deps_with_cache()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/report/pdf?ticker=AAPL")
        assert response.status_code == 404
