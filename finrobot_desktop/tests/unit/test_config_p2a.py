from finagent.config import FinAgentSettings


# Pass _env_file=None on every "default" assertion. Otherwise pydantic-settings
# reads the developer's real .env (now resolved as an absolute repo-root path,
# previously masked by cwd drift) and "default empty" turns into "whatever you
# happen to have in your shell".
def _defaults_only() -> FinAgentSettings:
    return FinAgentSettings(model_name="test:test", _env_file=None)


def test_fmp_api_key_default_empty():
    s = _defaults_only()
    assert s.fmp_api_key == ""


def test_finnhub_api_key_default_empty():
    s = _defaults_only()
    assert s.finnhub_api_key == ""


def test_sec_user_agent_default():
    s = _defaults_only()
    assert "FinAgent" in s.sec_user_agent
    assert "@" in s.sec_user_agent


def test_fmp_api_key_from_kwargs():
    s = FinAgentSettings(model_name="test:test", fmp_api_key="abc123", _env_file=None)
    assert s.fmp_api_key == "abc123"
