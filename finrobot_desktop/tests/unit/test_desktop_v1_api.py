from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from finrobot.config import get_settings
from finrobot.engine.deps import FinRobotDeps
from finrobot.run_store import RunStore
from finrobot.secret_store import FileSecretStore
from finrobot.server import app


def _dcf_payload() -> dict[str, object]:
    return {
        "revenue_base": 1_000_000_000,
        "revenue_growth_rates": [0.05, 0.04, 0.03, 0.03, 0.02],
        "ebitda_margin": 0.30,
        "capex_pct_revenue": 0.04,
        "nwc_pct_revenue": 0.02,
        "da_pct_revenue": 0.03,
        "tax_rate": 0.21,
        "risk_free_rate": 0.04,
        "beta": 1.1,
        "equity_risk_premium": 0.055,
        "cost_of_debt": 0.05,
        "debt_ratio": 0.20,
        "terminal_growth_rate": 0.025,
        "shares_outstanding": 100_000_000,
        "net_debt": 50_000_000,
    }


class FakeDataLayer:
    async def close(self) -> None:
        return


class TestComputeRoutes:
    @pytest.mark.asyncio
    async def test_compute_dcf_returns_deterministic_result(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = await client.post("/api/compute/dcf", json=_dcf_payload())
            second = await client.post("/api/compute/dcf", json=_dcf_payload())

        assert first.status_code == 200
        assert second.status_code == 200
        first_data = first.json()
        second_data = second.json()
        assert first_data["implied_price"] == second_data["implied_price"]
        # fcf_formula field was removed in Phase B (standard-with-D&A is the
        # only formula now); deterministic check above is what mattered.
        # Verify the model produces a reasonable positive price
        assert first_data["implied_price"] > 0
        # Verify enterprise_value is computed
        assert first_data["enterprise_value"] > 0
        # Verify projected FCFs are present and non-empty
        assert len(first_data["projected_fcf"]) == 5

    @pytest.mark.asyncio
    async def test_compute_wacc(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/compute/wacc",
                json={
                    "risk_free_rate": 0.04,
                    "beta": 1.0,
                    "equity_risk_premium": 0.05,
                    "cost_of_debt": 0.06,
                    "tax_rate": 0.21,
                    "debt_ratio": 0.25,
                },
            )
        assert response.status_code == 200
        assert response.json()["cost_of_equity"] == pytest.approx(0.09)
        assert response.json()["wacc"] == pytest.approx(0.07935)


class TestSettingsRoutes:
    @pytest.mark.asyncio
    async def test_settings_get_masks_api_keys(self, tmp_path):
        settings = get_settings(model_name="test")
        secret_store = FileSecretStore(tmp_path / ".secrets")
        await secret_store.set("fmp_api_key", "secret-fmp-key")
        app.state.secret_store = secret_store
        app.state.settings_path = tmp_path / "settings.json"
        app.state.deps = FinRobotDeps(
            data_layer=FakeDataLayer(),  # type: ignore[arg-type]
            settings=settings,
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/settings")

        assert response.status_code == 200
        body = response.json()
        assert body["fmp_api_key_set"] is True
        assert "secret-fmp-key" not in response.text


class TestRunStore:
    @pytest.mark.asyncio
    async def test_create_run_persists_language(self, tmp_path):
        store = RunStore(tmp_path / "runs.db")
        run = await store.create_run("equity_research", "AAPL", language="en")
        assert run.language == "en"
        # Round-trip through the DB — _row_to_run must decode the new column.
        fetched = await store.get_run(run.run_id)
        assert fetched is not None
        assert fetched.language == "en"
        # Unspecified language persists as NULL → None (execute falls back).
        run2 = await store.create_run("dcf", "MSFT")
        fetched2 = await store.get_run(run2.run_id)
        assert fetched2 is not None and fetched2.language is None
        await store.close()

    @pytest.mark.asyncio
    async def test_run_store_replays_events_after_last_seq(self, tmp_path):
        store = RunStore(tmp_path / "runs.db")
        run = await store.create_run("dcf", "AAPL")
        await store.append_event(
            run.run_id,
            {
                "event": "run.started",
                "run_id": run.run_id,
                "pipeline_type": "dcf",
                "ticker": "AAPL",
                "total_steps": 1,
            },
        )
        await store.append_event(
            run.run_id,
            {
                "event": "run.completed",
                "run_id": run.run_id,
                "ticker": "AAPL",
                "duration_s": 1.0,
                "result_url": f"/api/runs/{run.run_id}",
            },
        )

        events = await store.get_events_after(run.run_id, last_seq=1)
        await store.close()

        assert len(events) == 1
        assert events[0].seq == 2
        assert events[0].event["event"] == "run.completed"


class TestRunsRoutes:
    @pytest.mark.asyncio
    async def test_runs_sse_emits_new_protocol_events(self, tmp_path):
        class FakePipeline:
            steps = [object()]

            async def execute(self, deps, ticker, progress, lang=None, **kwargs):
                # **kwargs tolerates execute() gaining keyword params (e.g.
                # source_artifact_id) without this fake drifting out of sync.
                await progress.on_step_start(1, 1, "dcf_calc")
                await progress.on_step_end(1, 1, "dcf_calc", 0.1)
                result = MagicMock()
                result.structured_data = {}
                result.failed_validations = []
                result.steps = []
                # artifact_id is str | None on the real PipelineResult; an
                # unconfigured MagicMock here is truthy AND non-serialisable,
                # which now poisons the completion event (it carries
                # artifact_id). This fake DCF persists no artifact → None.
                result.artifact_id = None
                result.format_summary.return_value = "summary"
                return result

        settings = get_settings(model_name="test")
        app.state.deps = FinRobotDeps(
            data_layer=FakeDataLayer(),  # type: ignore[arg-type]
            settings=settings,
        )
        app.state.sub_agents = {}
        app.state.run_store = RunStore(tmp_path / "runs.db")
        app.state.run_tasks = {}

        # Patch the binding inside routes.runs, not the source module.
        # `from finrobot.engine.pipelines.registry import get_pipeline_factories`
        # at runs.py:19 copied the reference; patching the source module leaves
        # the local name pointing at the real registry, the real `dcf` pipeline
        # ran with empty sub_agents/data_layer, never reached completed/failed,
        # and the SSE stream's poll loop never broke out → test hung forever.
        with patch(
            "finrobot.routes.runs.get_pipeline_factories",
            return_value={"dcf": lambda sub_agents: FakePipeline()},
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                created = await client.post(
                    "/api/runs", json={"pipeline_type": "dcf", "ticker": "AAPL"}
                )
                assert created.status_code == 200
                run_id = created.json()["run_id"]
                events = await client.get(f"/api/runs/{run_id}/events")

        await app.state.run_store.close()

        assert events.status_code == 200
        body = events.text
        assert "event: run.started" in body
        assert "event: step.started" in body
        assert "event: step.completed" in body
        assert "event: run.completed" in body
        assert "id: 1" in body
