from pydantic_ai import Agent

from finrobot.config import get_settings
from finrobot.engine.agents.factory import create_sub_agents


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
            assert (
                "query_financial_data" not in tool_names
            ), f"{role} agent should NOT have query_financial_data"

    def test_all_agents_use_settings_model(self):
        from pydantic_ai.models.test import TestModel

        settings = _settings()
        agents = create_sub_agents(settings)
        for role, agent in agents.items():
            assert isinstance(
                agent.model, TestModel
            ), f"{role} agent should use TestModel from settings.create_model()"
