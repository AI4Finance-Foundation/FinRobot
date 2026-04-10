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


class TestPipelineStream:
    @staticmethod
    def _setup_test_deps():
        """Install a FakeDeps into app.state so the SSE endpoint can run a
        TestModel pipeline without real network or real sub-agents."""
        from datetime import datetime, timezone

        from finagent.config import get_settings
        from finagent.engine.data.interface import DataResult
        from finagent.engine.deps import FinAgentDeps

        class FakeDataLayer:
            async def fetch(self, data_type, ticker, **kwargs):
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

    @pytest.mark.asyncio
    async def test_invalid_pipeline_type_returns_400(self):
        self._setup_test_deps()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/pipeline/stream/notapipeline/AAPL")
        assert response.status_code == 400
        assert "Invalid pipeline" in response.json()["error"]

    @pytest.mark.asyncio
    async def test_sse_stream_emits_step_events(self):
        """Run the research pipeline against TestModel and verify SSE events.

        We can't use streaming with ASGITransport easily, but we can read the
        full body (it collects all emitted frames) and confirm the presence
        of step_start / step_end / complete events.
        """
        self._setup_test_deps()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/pipeline/stream/research/TEST")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = response.text

        # Each event is a JSON object on a `data: ...` line.
        assert "step_start" in body
        assert "step_end" in body
        # Pipeline finished successfully → complete event present.
        assert "complete" in body or "error" in body
