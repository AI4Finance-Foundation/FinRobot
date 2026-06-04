from pathlib import Path

from pydantic_ai import Agent

from finrobot.config import get_settings
from finrobot.engine.agents.factory import create_sub_agents
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
