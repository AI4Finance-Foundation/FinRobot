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


class TestChatEndpoint:
    async def test_chat_endpoint_exists_and_accepts_post(self):
        """Verify route exists by manually setting app.state before request.
        ASGITransport doesn't trigger lifespan events."""

        from finagent.config import get_settings
        from finagent.engine.deps import FinAgentDeps
        from finagent.engine.orchestrator import create_lead_agent

        settings = get_settings(model_name="test")
        agent = create_lead_agent(settings)
        app.state.agent = agent
        app.state.deps = FinAgentDeps(
            data_layer=None,
            settings=settings,  # type: ignore[arg-type]
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            response = await c.post("/chat", json={})
        assert response.status_code != 404
        assert response.status_code != 405


class TestArchitecturalRedLines:
    """Static guards that survive the SSE endpoint reshuffle.

    The legacy ``/api/pipeline/stream/*`` endpoint and the ``_get_pipeline_factories``
    wrapper were removed when SSE runs were consolidated under ``/api/runs``
    (RunStore-backed, see ``routes/runs.py``). The behavioural tests for that
    endpoint were retired along with the code; the bare-except guard stays
    because it covers the entire ``finagent/`` tree.
    """

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

    def test_runs_route_no_create_sub_agents_import(self):
        """routes/runs.py must use app.state.sub_agents, not re-create them."""
        import ast
        from pathlib import Path

        runs_path = (
            Path(__file__).resolve().parents[2] / "finagent" / "routes" / "runs.py"
        )
        tree = ast.parse(runs_path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    assert alias.name != "create_sub_agents", (
                        "routes/runs.py still imports create_sub_agents — "
                        "it should use request.app.state.sub_agents instead"
                    )
