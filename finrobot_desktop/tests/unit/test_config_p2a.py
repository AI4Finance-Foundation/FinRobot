from finagent.config import FinAgentSettings


def test_fmp_api_key_default_empty():
    s = FinAgentSettings(model_name="test:test")
    assert s.fmp_api_key == ""


def test_finnhub_api_key_default_empty():
    s = FinAgentSettings(model_name="test:test")
    assert s.finnhub_api_key == ""


def test_sec_user_agent_default():
    s = FinAgentSettings(model_name="test:test")
    assert "FinAgent" in s.sec_user_agent
    assert "@" in s.sec_user_agent


def test_fmp_api_key_from_kwargs():
    s = FinAgentSettings(model_name="test:test", fmp_api_key="abc123")
    assert s.fmp_api_key == "abc123"
