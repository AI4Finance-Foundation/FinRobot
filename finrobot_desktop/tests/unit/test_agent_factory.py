from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import Agent, ModelRetry

from finrobot.config import get_settings
from finrobot.engine.agents.factory import create_sub_agents
from finrobot.engine.data.types import DataType
from finrobot.engine.orchestrator import create_lead_agent


def _settings():
    return get_settings(model_name="test")


class TestCreateSubAgents:
    def test_returns_dict_with_5_keys(self):
        agents = create_sub_agents(_settings())
        assert set(agents.keys()) == {"data", "analysis", "modeling", "synthesis", "report"}

    def test_each_value_is_agent(self):
        agents = create_sub_agents(_settings())
        for role, agent in agents.items():
            assert isinstance(agent, Agent), f"{role} is not an Agent"

    def test_data_agent_has_query_financial_data_tool(self):
        agents = create_sub_agents(_settings())
        tool_names = set(agents["data"]._function_toolset.tools.keys())
        assert "query_financial_data" in tool_names

    @pytest.mark.asyncio
    async def test_query_financial_data_uses_canonical_for_price(self):
        """PRICE/FINANCIALS must route through fetch_canonical (the structured
        layer's single source of truth), NOT bare fetch() — otherwise the agent
        narrates a divergent quote ($391 vs structured $408.95, 2026-06-09 TSLA).
        NEWS has no canonical contract and stays on raw fetch()."""
        agents = create_sub_agents(_settings())
        fn = agents["data"]._function_toolset.tools["query_financial_data"].function

        ctx = MagicMock()
        normalized = MagicMock()
        normalized.model_dump_json.return_value = '{"current_price": 408.95}'
        ctx.deps.data_layer.fetch_canonical = AsyncMock(return_value=normalized)
        ctx.deps.data_layer.fetch = AsyncMock(
            return_value=MagicMock(to_context_string=lambda: "news text")
        )

        out_price = await fn(ctx, "TSLA", "price")
        ctx.deps.data_layer.fetch_canonical.assert_awaited_once_with(DataType.PRICE, "TSLA")
        ctx.deps.data_layer.fetch.assert_not_awaited()
        assert "canonical" in out_price and "408.95" in out_price

        # NEWS falls through to raw fetch() — with the coerced enum, not the
        # raw LLM string.
        out_news = await fn(ctx, "TSLA", "news")
        ctx.deps.data_layer.fetch.assert_awaited_once_with(DataType.NEWS, "TSLA")
        assert out_news == "news text"

    @pytest.mark.asyncio
    async def test_query_financial_data_bad_data_type_raises_model_retry(self):
        """An LLM-invented data_type must surface as ModelRetry (fed back to the
        model to self-correct, per pydantic-ai docs) — NOT a bare ValueError,
        which pydantic-ai does not catch and which would kill the whole
        sub-agent run / pipeline step. Mirror of the lead orchestrator's
        same-named tool."""
        agents = create_sub_agents(_settings())
        fn = agents["data"]._function_toolset.tools["query_financial_data"].function

        ctx = MagicMock()
        ctx.deps.data_layer.fetch_canonical = AsyncMock()
        ctx.deps.data_layer.fetch = AsyncMock()

        with pytest.raises(ModelRetry) as excinfo:
            await fn(ctx, "AAPL", "balance_sheet")
        # The retry message must teach the model the valid vocabulary.
        assert "balance_sheet" in str(excinfo.value)
        assert "financials" in str(excinfo.value)
        ctx.deps.data_layer.fetch.assert_not_awaited()
        ctx.deps.data_layer.fetch_canonical.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_query_financial_data_bad_ticker_returns_error_string(self):
        """A junk LLM-chosen ticker must never become a fetch parameter / cache
        key — it is rejected by validate_ticker and RETURNED as an error string
        (the model cannot self-correct a hallucinated symbol, so let it narrate)."""
        agents = create_sub_agents(_settings())
        fn = agents["data"]._function_toolset.tools["query_financial_data"].function

        ctx = MagicMock()
        ctx.deps.data_layer.fetch_canonical = AsyncMock()
        ctx.deps.data_layer.fetch = AsyncMock()

        out = await fn(ctx, "苹果", "price")
        assert "Invalid ticker" in out
        ctx.deps.data_layer.fetch.assert_not_awaited()
        ctx.deps.data_layer.fetch_canonical.assert_not_awaited()

    def test_non_data_agents_do_not_have_query_financial_data(self):
        agents = create_sub_agents(_settings())
        for role in ["analysis", "modeling", "synthesis", "report"]:
            tool_names = set(agents[role]._function_toolset.tools.keys())
            assert "query_financial_data" not in tool_names, (
                f"{role} agent should NOT have query_financial_data"
            )

    def test_all_agents_use_settings_model(self):
        from pydantic_ai.models.test import TestModel

        settings = _settings()
        agents = create_sub_agents(settings)
        for role, agent in agents.items():
            assert isinstance(agent.model, TestModel), (
                f"{role} agent should use TestModel from settings.create_model()"
            )


# ---------------------------------------------------------------------------
# Instruction-file encoding (BUG-078)
#
# Several instruction .md files contain UTF-8 Chinese (bull/bear/judge/modeling/
# report/synthesis + the lead instructions.md). Under a non-UTF-8 locale
# (bare Docker LANG=C / Windows cp1252), Path.read_text() with no encoding
# decodes with the locale codec and raises UnicodeDecodeError, crashing agent
# creation. Both factory and orchestrator must pass encoding="utf-8" explicitly.
# ---------------------------------------------------------------------------


class TestInstructionEncoding:
    def test_sub_agent_instructions_loaded_with_utf8_encoding(self, monkeypatch):
        """create_sub_agents must read every instruction file as UTF-8."""
        seen: list[str | None] = []
        original = Path.read_text

        def spy_read_text(self, *args, encoding=None, **kwargs):  # type: ignore[no-untyped-def]
            seen.append(encoding)
            # Force UTF-8 so a missing encoding (None) would raise here under a
            # non-UTF-8 locale — proving the call site must pass it explicitly.
            return original(self, encoding="utf-8")

        monkeypatch.setattr(Path, "read_text", spy_read_text)
        create_sub_agents(_settings())

        # Every instruction read for the 5 roles must request utf-8.
        instruction_reads = [e for e in seen]
        assert instruction_reads, "expected at least one instruction file read"
        assert all(enc == "utf-8" for enc in instruction_reads), (
            f"instruction reads must pass encoding='utf-8', saw: {instruction_reads}"
        )

    def test_lead_instructions_loaded_with_utf8_encoding(self, monkeypatch):
        """create_lead_agent must read instructions.md as UTF-8."""
        seen: list[str | None] = []
        original = Path.read_text

        def spy_read_text(self, *args, encoding=None, **kwargs):  # type: ignore[no-untyped-def]
            seen.append(encoding)
            return original(self, encoding="utf-8")

        monkeypatch.setattr(Path, "read_text", spy_read_text)
        create_lead_agent(_settings())

        assert "utf-8" in seen, "create_lead_agent must read instructions.md as utf-8"
        assert all(enc == "utf-8" for enc in seen), (
            f"all reads during lead-agent creation must pass utf-8, saw: {seen}"
        )

    def test_instruction_files_decode_under_ascii_locale(self):
        """Direct UTF-8 reads of the Chinese instruction files succeed.

        Reading without encoding under LANG=C would raise UnicodeDecodeError;
        passing encoding='utf-8' (the fix) decodes the Chinese content cleanly.
        """
        base = Path(__file__).parent.parent.parent / "finrobot" / "engine"
        targets = [
            base / "instructions.md",
            base / "agents" / "instructions" / "modeling_agent.md",
            base / "agents" / "instructions" / "report_agent.md",
            base / "agents" / "instructions" / "synthesis_agent.md",
        ]
        for path in targets:
            text = path.read_text(encoding="utf-8")
            assert text  # decodes without raising
