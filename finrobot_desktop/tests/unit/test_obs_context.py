from finrobot.obs.context import bind_run, bind_session, bind_request, current_trace


def test_trace_empty_by_default() -> None:
    assert current_trace() == {"request_id": "-", "session_id": "-", "run_id": "-"}


def test_bind_run_sets_and_resets() -> None:
    assert current_trace()["run_id"] == "-"
    with bind_run("r_42"):
        assert current_trace()["run_id"] == "r_42"
    assert current_trace()["run_id"] == "-"


def test_bind_resets_on_exception() -> None:
    try:
        with bind_session("s_1"):
            assert current_trace()["session_id"] == "s_1"
            raise ValueError("boom")
    except ValueError:
        pass
    assert current_trace()["session_id"] == "-"


def test_binds_nest_independently() -> None:
    with bind_request("req_1"), bind_session("s_1"), bind_run("r_1"):
        assert current_trace() == {
            "request_id": "req_1",
            "session_id": "s_1",
            "run_id": "r_1",
        }


def test_nested_same_var_unwinds_correctly() -> None:
    with bind_run("outer"):
        with bind_run("inner"):
            assert current_trace()["run_id"] == "inner"
        assert current_trace()["run_id"] == "outer"
    assert current_trace()["run_id"] == "-"


async def test_bind_propagates_to_child_task() -> None:
    import asyncio

    async def reader() -> str:
        return current_trace()["run_id"]

    with bind_run("async_r"):
        result = await asyncio.create_task(reader())
    assert result == "async_r"
