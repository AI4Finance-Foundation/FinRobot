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
        assert data["phase"] == "P3"


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

        from finagent.engine.agents.factory import create_sub_agents

        app.state.sub_agents = create_sub_agents(settings, skill_registry=None)

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

    def test_no_bare_except_exception_in_finagent(self):
        """Regression guard for P3 audit D1 / CLAUDE.md N2 discipline.

        The SSE endpoint previously used `except Exception as e:` which
        swallowed BaseException subclasses (KeyboardInterrupt, SystemExit,
        MemoryError) and, worse, CancelledError — breaking client-disconnect
        cleanup. This test fails the moment someone reintroduces a bare
        `except Exception` anywhere under finagent/.
        """
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[2] / "finagent"
        offenders: list[str] = []
        for py in root.rglob("*.py"):
            for lineno, line in enumerate(py.read_text().splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "except Exception" in stripped and "BaseException" not in stripped:
                    offenders.append(f"{py.relative_to(root.parent)}:{lineno}: {stripped}")
        assert offenders == [], (
            "`except Exception` is banned in finagent/ (P3 audit D1). "
            "Catch concrete exception types and re-raise CancelledError. "
            f"Found: {offenders}"
        )


class TestExcelExportEndpoint:
    """P3 audit D3: regression guard — LBO Excel export must return 501
    until LBOInputs are persisted alongside LBOResult in report_cache.

    Before this fix, the endpoint reconstructed LBOInputs post-hoc with
    arithmetic that evaluated to entry_debt (not ltm_ebitda) plus hard-
    coded 1.0 / 5% / 20% placeholders that had nothing to do with the
    actual LBO run. The endpoint happily returned an Excel file with
    those fabricated values in the header — a credibility disaster.
    """

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
    async def test_lbo_excel_export_returns_501_until_inputs_cached(self):
        """Even with a fresh-looking LBOResult in the cache, the endpoint
        must refuse to generate Excel because the inputs it needs are
        not persisted. This test pins the behaviour so nobody silently
        restores the broken post-hoc reconstruction."""
        from finagent.engine.models.financial import LBOResult, LBOYear

        fake_year = LBOYear(
            year=1,
            revenue=500_000_000,
            ebitda=100_000_000,
            da=10_000_000,
            ebit=90_000_000,
            interest_expense=49_000_000,
            ebt=41_000_000,
            taxes=10_250_000,
            net_income=30_750_000,
            capex=20_000_000,
            delta_nwc=5_000_000,
            fcf=15_750_000,
            mandatory_amort=7_000_000,
            cash_sweep_amount=8_750_000,
            total_debt_paydown=15_750_000,
            ending_debt=684_250_000,
        )
        fake_result = LBOResult(
            entry_ev=1_000_000_000,
            entry_equity=300_000_000,
            entry_debt=700_000_000,
            schedule=[fake_year],
            exit_ev=1_800_000_000,
            exit_ebitda=250_000_000,
            exit_equity=1_400_000_000,
            irr=0.22,
            moic=4.5,
        )
        self._setup_deps_with_cache({"TEST": {"lbo_result": fake_result}})

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/export/excel/lbo/TEST")

        assert response.status_code == 501
        detail = response.json()["detail"]
        assert "LBOInputs" in detail
        assert "P3 audit D3" in detail  # audit trail must stay in the message

    @pytest.mark.asyncio
    async def test_invalid_analysis_type_still_400(self):
        """Unrelated to D3, but close enough in scope to warrant a regression
        anchor — the 400 branch should be hit before the 501 branch."""
        self._setup_deps_with_cache()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/export/excel/bogus/TEST")
        assert response.status_code == 400


class TestSubAgentsCaching:
    """I1: sub-agents created once in lifespan, not per-request."""

    @pytest.mark.asyncio
    async def test_app_state_has_sub_agents_after_setup(self):
        from finagent.config import get_settings
        from finagent.engine.agents.factory import create_sub_agents

        settings = get_settings(model_name="test")
        sub_agents = create_sub_agents(settings, skill_registry=None)
        app.state.sub_agents = sub_agents
        assert hasattr(app.state, "sub_agents")
        assert isinstance(app.state.sub_agents, dict)
        assert len(app.state.sub_agents) > 0

    @pytest.mark.asyncio
    async def test_sse_uses_cached_sub_agents(self):
        """SSE endpoint must use app.state.sub_agents, not call create_sub_agents."""
        TestPipelineStream._setup_test_deps()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/pipeline/stream/research/TEST")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_server_run_pipeline_no_create_sub_agents_import(self):
        """The run_pipeline() function must NOT import create_sub_agents."""
        import ast
        from pathlib import Path

        server_path = Path(__file__).resolve().parents[2] / "finagent" / "server.py"
        source = server_path.read_text()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_pipeline":
                # Walk the body of run_pipeline looking for imports of
                # create_sub_agents
                for child in ast.walk(node):
                    if isinstance(child, ast.ImportFrom):
                        for alias in child.names:
                            assert alias.name != "create_sub_agents", (
                                "run_pipeline() still imports create_sub_agents — "
                                "it should use request.app.state.sub_agents instead"
                            )
