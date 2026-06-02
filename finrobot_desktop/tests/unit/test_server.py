import pytest
from httpx import ASGITransport, AsyncClient

from finrobot.server import app


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

        from finrobot.config import get_settings
        from finrobot.engine.deps import FinRobotDeps
        from finrobot.engine.orchestrator import create_lead_agent

        settings = get_settings(model_name="test")
        agent = create_lead_agent(settings)
        app.state.agent = agent
        app.state.deps = FinRobotDeps(
            data_layer=None,
            settings=settings,  # type: ignore[arg-type]
        )

        app.state.startup_error = None
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            response = await c.post("/chat", json={})
        assert response.status_code != 404
        assert response.status_code != 405

    async def test_chat_returns_503_when_startup_error_set(self):
        """BUG-20260602-056: a broken runtime config (startup_error set) must
        make /chat reply 503 BEFORE entering the stream, honouring the
        SettingsView contract instead of failing deep in the pipeline."""
        try:
            app.state.startup_error = "DEEPSEEK_API_KEY is required but not set"
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                response = await c.post(
                    "/chat", json={"messages": [{"role": "user", "content": "hi"}]}
                )
            assert response.status_code == 503, response.text
            assert "DEEPSEEK_API_KEY" in response.json()["detail"]
        finally:
            app.state.startup_error = None


class TestArchitecturalRedLines:
    """Static guards that survive the SSE endpoint reshuffle.

    The legacy ``/api/pipeline/stream/*`` endpoint and the ``_get_pipeline_factories``
    wrapper were removed when SSE runs were consolidated under ``/api/runs``
    (RunStore-backed, see ``routes/runs.py``). The behavioural tests for that
    endpoint were retired along with the code; the bare-except guard stays
    because it covers the entire ``finrobot/`` tree.
    """

    def test_no_bare_except_exception_in_finrobot(self):
        """Regression guard for P3 audit D1 / CLAUDE.md N2 discipline.

        The SSE endpoint previously used `except Exception as e:` which
        swallowed BaseException subclasses (KeyboardInterrupt, SystemExit,
        MemoryError) and, worse, CancelledError — breaking client-disconnect
        cleanup. This test fails the moment someone reintroduces a bare
        `except Exception` anywhere under finrobot/.
        """
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[2] / "finrobot"
        offenders: list[str] = []
        for py in root.rglob("*.py"):
            for lineno, line in enumerate(py.read_text().splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "except Exception" in stripped and "BaseException" not in stripped:
                    offenders.append(f"{py.relative_to(root.parent)}:{lineno}: {stripped}")
        assert offenders == [], (
            "`except Exception` is banned in finrobot/ (P3 audit D1). "
            "Catch concrete exception types and re-raise CancelledError. "
            f"Found: {offenders}"
        )

    # The 13F-refresh "don't block the lifespan" red line lives in
    # tests/audit/test_architecture.py::TestEventLoopNotBlocked. That guard is
    # AST-based and accepts any off-loop offload (asyncio.to_thread /
    # run_in_executor / subprocess). A former textual twin here mandated
    # `asyncio.create_subprocess_exec` specifically — which the frozen desktop
    # sidecar cannot use (sys.executable is the bundled binary, no repo tree),
    # so the parse is offloaded via asyncio.to_thread instead. Removed to keep
    # one authoritative invariant rather than two that drift apart.

    def test_tauri_sidecar_does_not_enable_python_reload_by_default(self):
        """Desktop startup must not pay the uvicorn reloader/watchdog cost.

        The sidecar is a frozen PyInstaller binary; its entry point
        (src-tauri/sidecar/entry.py) injects the ``serve`` subcommand and hands
        off to the Click CLI. It must never inject ``--reload`` — that would
        spin up uvicorn's file-watching reloader inside the shipped desktop app.
        (The previous artifact was a uv shell shim with a FINROBOT_SERVER_RELOAD
        opt-in; the frozen sidecar dropped both the shim and the env hook.)
        """
        from pathlib import Path

        entry_path = (
            Path(__file__).resolve().parents[2] / "src-tauri" / "sidecar" / "entry.py"
        )
        source = entry_path.read_text()
        assert '"serve"' in source  # the serve subcommand is injected
        assert "--reload" not in source  # the dev-only reloader is never enabled


class TestTranscriptWriterLRU:
    """B2 — transcript_writers dict is bounded by LRU eviction."""

    @pytest.mark.asyncio
    async def test_lru_evicts_oldest_when_cap_reached(self) -> None:
        """When the cap is hit, the oldest writer is evicted from the dict."""

        from finrobot.server import _TRANSCRIPT_WRITERS_MAX, _get_or_create_writer

        class _FakeState:
            pass

        state = _FakeState()
        # Fill up to exactly the cap using unique session IDs.
        for i in range(_TRANSCRIPT_WRITERS_MAX):
            await _get_or_create_writer(state, f"session-{i}", "test-model")

        assert len(state.transcript_writers) == _TRANSCRIPT_WRITERS_MAX
        # The next insertion must evict session-0 (oldest) and keep session-1…cap-1 + new.
        await _get_or_create_writer(state, "session-overflow", "test-model")
        assert len(state.transcript_writers) == _TRANSCRIPT_WRITERS_MAX
        assert "session-0" not in state.transcript_writers
        assert "session-overflow" in state.transcript_writers

    @pytest.mark.asyncio
    async def test_lru_moves_accessed_session_to_end(self) -> None:
        """Accessing an existing session promotes it to MRU so it isn't evicted first."""
        from finrobot.server import _TRANSCRIPT_WRITERS_MAX, _get_or_create_writer

        class _FakeState:
            pass

        state = _FakeState()
        for i in range(_TRANSCRIPT_WRITERS_MAX):
            await _get_or_create_writer(state, f"session-{i}", "test-model")

        # Re-access session-0 to make it MRU.
        await _get_or_create_writer(state, "session-0", "test-model")

        # Adding a new entry must evict session-1 (now oldest), not session-0.
        await _get_or_create_writer(state, "session-new", "test-model")
        assert "session-1" not in state.transcript_writers
        assert "session-0" in state.transcript_writers
        assert "session-new" in state.transcript_writers

    @pytest.mark.asyncio
    async def test_lru_creates_dict_when_state_missing(self) -> None:
        """Defensively creates transcript_writers if not present on app_state."""
        from finrobot.server import _get_or_create_writer

        class _FakeState:
            pass

        state = _FakeState()
        writer = await _get_or_create_writer(state, "s1", "model")
        assert hasattr(state, "transcript_writers")
        assert "s1" in state.transcript_writers
        assert writer.session_id == "s1"


class TestRequestTraceMiddleware:
    def test_response_has_request_id_header(self) -> None:
        from fastapi.testclient import TestClient

        from finrobot.server import app

        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.headers.get("X-Request-ID")


class TestSubAgentsCaching:
    """I1: sub-agents created once in lifespan, not per-request."""

    @pytest.mark.asyncio
    async def test_app_state_has_sub_agents_after_setup(self):
        from finrobot.config import get_settings
        from finrobot.engine.agents.factory import create_sub_agents

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
            Path(__file__).resolve().parents[2] / "finrobot" / "routes" / "runs.py"
        )
        tree = ast.parse(runs_path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    assert alias.name != "create_sub_agents", (
                        "routes/runs.py still imports create_sub_agents — "
                        "it should use request.app.state.sub_agents instead"
                    )
