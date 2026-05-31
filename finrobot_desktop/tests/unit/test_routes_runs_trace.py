"""_run_pipeline must bind run_id so downstream logs carry it."""

import inspect

import finrobot.routes.runs as runs_mod
from finrobot.obs.context import bind_run, current_trace


def test_run_pipeline_source_binds_run_id() -> None:
    src = inspect.getsource(runs_mod._run_pipeline)
    assert "bind_run(run_id)" in src, "_run_pipeline must bind run_id for trace logging"


def test_bind_run_sets_trace() -> None:
    rec_run = current_trace()["run_id"]
    assert rec_run == "-"
    with bind_run("r_xyz"):
        assert current_trace()["run_id"] == "r_xyz"
    assert current_trace()["run_id"] == "-"
