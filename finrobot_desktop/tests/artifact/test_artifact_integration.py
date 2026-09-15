"""Integration tests: Pipeline.execute() auto-persists Artifact.

Tests that:
1. A DCF pipeline execute() with artifact_store set saves an artifact
2. artifact.ticker, artifact.type, artifact.id are correct
3. artifact.inputs.raw_data contains FinancialData fields
4. artifact.assumptions.parameters has wacc-related fields
5. artifact.outputs.structured has implied_price
6. artifact.compute_version.formula_id is set correctly
7. Pipeline without artifact_builder does NOT crash when store is set
8. Pipeline with artifact_builder but no store skips save (no crash)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from finrobot.artifact.store import ArtifactStore
from finrobot.engine.data.interface import DataResult
from finrobot.engine.models.financial import (
    BalanceSheet,
    DCFInputs,
    DCFResult,
    FinancialData,
    IncomeStatement,
    MarketData,
    StepOutput,
    ValuationMetrics,
)
from finrobot.engine.pipelines.base import (
    Pipeline,
    PipelineStep,
    StructuredValidator,
    TextValidator,
)
from finrobot.engine.pipelines.validators import ValidationResult, validate_is_non_empty


UTC = timezone.utc


@pytest.fixture
async def artifact_store(tmp_store_dir: Path) -> AsyncIterator[ArtifactStore]:
    store = ArtifactStore(base_dir=tmp_store_dir)
    try:
        yield store
    finally:
        await store.close()


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


class FakeDataLayer:
    async def fetch(self, data_type: str, ticker: str, **kwargs) -> DataResult:
        return DataResult(
            data={
                "revenue": 394_328_000_000,
                "ebitda": 130_541_000_000,
                "net_income": 96_995_000_000,
                "market_cap": 2_800_000_000_000,
                "shares_outstanding": 15_550_000_000,
                "current_price": 180.0,
                "gross_margin": 0.438,
                "operating_margin": 0.302,
                "total_debt": 111_088_000_000,
                "total_cash": 29_965_000_000,
                "price_history": [{"close": 180.0}],
            },
            provider="fake",
            ticker=ticker,
            data_type=str(data_type),
            timestamp=datetime.now(tz=UTC),
        )


def _make_fake_financial_data(ticker: str = "AAPL") -> FinancialData:
    return FinancialData(
        ticker=ticker,
        timestamp=datetime(2026, 5, 13, 10, 0, 0, tzinfo=UTC),
        income=IncomeStatement(
            revenue=394_328_000_000,
            ebitda=130_541_000_000,
            net_income=96_995_000_000,
            gross_margin=0.438,
            operating_margin=0.302,
        ),
        balance=BalanceSheet(total_debt=111_088_000_000, total_cash=29_965_000_000),
        market=MarketData(
            market_cap=2_800_000_000_000,
            shares_outstanding=15_550_000_000,
            current_price=180.0,
        ),
        valuation=ValuationMetrics(),
        data_source="fake",
    )


def _make_fake_dcf_result() -> DCFResult:
    inputs = DCFInputs(
        revenue_base=394_328_000_000,
        revenue_growth_rates=[0.06, 0.05, 0.04, 0.03, 0.02],
        ebitda_margin=0.30,
        capex_pct_revenue=0.04,
        nwc_pct_revenue=0.02,
        tax_rate=0.21,
        risk_free_rate=0.045,
        beta=1.1,
        equity_risk_premium=0.055,
        cost_of_debt=0.04,
        debt_ratio=0.25,
        terminal_growth_rate=0.025,
        shares_outstanding=15_550_000_000,
        net_debt=81_123_000_000,
        da_pct_revenue=0.035,
    )
    return DCFResult(
        cost_of_equity=0.1055,
        wacc=0.082,
        projection_years=5,
        projected_revenue=[418_000_000_000] * 5,
        projected_ebitda=[125_400_000_000] * 5,
        projected_fcf=[85_000_000_000] * 5,
        terminal_value=2_100_000_000_000,
        pv_terminal=1_400_000_000_000,
        pv_fcf_total=330_000_000_000,
        enterprise_value=1_730_000_000_000,
        equity_value=1_648_000_000_000,
        implied_price=185.0,
        inputs=inputs,
    )


@dataclass
class FakeSettings:
    language: str = "en"

    def create_model(self) -> Any:
        return TestModel()

    def validate_runtime_config(self) -> None:
        pass


@dataclass
class FakeDeps:
    data_layer: FakeDataLayer = field(default_factory=FakeDataLayer)
    settings: FakeSettings = field(default_factory=FakeSettings)
    skill_runtime: Any = None
    artifact_store: ArtifactStore | None = None


def _make_agent(output_text: str = "analysis output") -> Agent:
    return Agent(TestModel(custom_output_text=output_text))


# ---------------------------------------------------------------------------
# Tests: DCF pipeline artifact integration
# ---------------------------------------------------------------------------


class TestDCFPipelineArtifact:
    """Verify that a DCF-like pipeline auto-persists an artifact."""

    def _build_minimal_dcf_pipeline(self, store: ArtifactStore) -> tuple[Pipeline, FakeDeps]:
        """Build a Pipeline that simulates the DCF pipeline's structured outputs."""
        fd = _make_fake_financial_data()
        dcf = _make_fake_dcf_result()

        # Step 1: historical_data — produces FinancialData
        async def exec_historical(agent, deps, prompt, sc, ticker):
            return StepOutput(text="Historical data collected.", structured=fd)

        # Step 2: dcf_calc — produces DCFResult
        async def exec_dcf_calc(agent, deps, prompt, sc, ticker):
            return StepOutput(text="DCF: $185/share, WACC 8.2%", structured=dcf)

        # Step 3: output_gen — produces text
        async def exec_output_gen(agent, deps, prompt, sc, ticker):
            return "DCF analysis complete."

        from finrobot.artifact.builders import build_dcf_artifact

        pipeline = Pipeline(
            artifact_builder=build_dcf_artifact,
            steps=[
                PipelineStep(
                    name="historical_data",
                    agent=_make_agent(),
                    validator=StructuredValidator(
                        lambda x: ValidationResult(passed=True),
                        validate_is_non_empty,
                    ),
                    executor=exec_historical,
                ),
                PipelineStep(
                    name="dcf_calc",
                    agent=_make_agent(),
                    validator=StructuredValidator(
                        lambda x: ValidationResult(passed=True),
                        validate_is_non_empty,
                    ),
                    executor=exec_dcf_calc,
                ),
                PipelineStep(
                    name="output_gen",
                    agent=_make_agent(),
                    validator=TextValidator(validate_is_non_empty),
                    executor=exec_output_gen,
                ),
            ],
        )
        deps = FakeDeps(artifact_store=store)
        return pipeline, deps

    @pytest.mark.asyncio
    async def test_artifact_is_persisted_after_execute(self, artifact_store: ArtifactStore) -> None:
        pipeline, deps = self._build_minimal_dcf_pipeline(artifact_store)

        result = await pipeline.execute(deps, "AAPL")

        # Verify PipelineResult carries the artifact_id
        assert result.artifact_id is not None
        assert result.artifact_id.startswith("art_")
        assert "AAPL" in result.artifact_id
        assert "dcf" in result.artifact_id

    @pytest.mark.asyncio
    async def test_artifact_is_retrievable(self, artifact_store: ArtifactStore) -> None:
        pipeline, deps = self._build_minimal_dcf_pipeline(artifact_store)

        result = await pipeline.execute(deps, "AAPL")
        assert result.artifact_id is not None

        artifact = await artifact_store.get(result.artifact_id)
        assert artifact is not None
        assert artifact.ticker == "AAPL"
        assert artifact.type == "dcf"

    @pytest.mark.asyncio
    async def test_artifact_inputs_contain_raw_data(self, artifact_store: ArtifactStore) -> None:
        pipeline, deps = self._build_minimal_dcf_pipeline(artifact_store)

        result = await pipeline.execute(deps, "AAPL")
        artifact = await artifact_store.get(result.artifact_id)  # type: ignore[arg-type]
        assert artifact is not None

        # raw_data should contain financial fields (FinancialData dump)
        assert "income" in artifact.inputs.raw_data
        assert artifact.inputs.data_source == "fake"

    @pytest.mark.asyncio
    async def test_artifact_assumptions_contain_wacc(self, artifact_store: ArtifactStore) -> None:
        pipeline, deps = self._build_minimal_dcf_pipeline(artifact_store)

        result = await pipeline.execute(deps, "AAPL")
        artifact = await artifact_store.get(result.artifact_id)  # type: ignore[arg-type]
        assert artifact is not None

        params = artifact.assumptions.parameters
        assert "wacc" in params or "risk_free_rate" in params, (
            f"Expected WACC-related field in assumptions, got: {list(params.keys())}"
        )

    @pytest.mark.asyncio
    async def test_artifact_outputs_contain_implied_price(
        self, artifact_store: ArtifactStore
    ) -> None:
        pipeline, deps = self._build_minimal_dcf_pipeline(artifact_store)

        result = await pipeline.execute(deps, "AAPL")
        artifact = await artifact_store.get(result.artifact_id)  # type: ignore[arg-type]
        assert artifact is not None

        assert artifact.outputs.structured.get("implied_price") == pytest.approx(185.0)

    @pytest.mark.asyncio
    async def test_artifact_compute_version_formula_id(self, artifact_store: ArtifactStore) -> None:
        pipeline, deps = self._build_minimal_dcf_pipeline(artifact_store)

        result = await pipeline.execute(deps, "AAPL")
        artifact = await artifact_store.get(result.artifact_id)  # type: ignore[arg-type]
        assert artifact is not None

        # Formula ID should reflect the FCF formula used. Post Phase B the
        # only path is `dcf_standard_with_da_v2` — the older simplified-FCF
        # branch (and its warning) was removed when D&A became the only
        # supported FCF computation. So we assert formula_id is the
        # standard v2 marker and that formula_warnings is a clean list
        # rather than insisting on the legacy "simplified" warning string.
        assert artifact.compute_version.formula_id == "dcf_standard_with_da_v2"
        assert isinstance(artifact.compute_version.formula_warnings, list)


class TestPipelineWithoutArtifactBuilder:
    """Pipeline with no artifact_builder but store is set — should not crash."""

    @pytest.mark.asyncio
    async def test_no_artifact_builder_does_not_crash(self, artifact_store: ArtifactStore) -> None:
        pipeline = Pipeline(
            artifact_builder=None,  # explicitly no builder
            steps=[
                PipelineStep(
                    name="step1",
                    agent=_make_agent("hello"),
                    validator=TextValidator(validate_is_non_empty),
                ),
            ],
        )
        deps = FakeDeps(artifact_store=artifact_store)
        result = await pipeline.execute(deps, "AAPL")

        assert result.artifact_id is None
        # No artifacts in store
        summaries = await artifact_store.list_by_ticker()
        assert summaries == []


class TestPipelineWithBuilderNoStore:
    """Pipeline has a builder but deps.artifact_store is None — no crash."""

    @pytest.mark.asyncio
    async def test_no_store_does_not_crash(self) -> None:
        from finrobot.artifact.builders import build_dcf_artifact

        pipeline = Pipeline(
            artifact_builder=build_dcf_artifact,
            steps=[
                PipelineStep(
                    name="step1",
                    agent=_make_agent("hello"),
                    validator=TextValidator(validate_is_non_empty),
                ),
            ],
        )
        deps = FakeDeps(artifact_store=None)  # no store
        result = await pipeline.execute(deps, "AAPL")

        # Result returned normally, no artifact_id
        assert result.artifact_id is None
        assert "step1" in result.steps
