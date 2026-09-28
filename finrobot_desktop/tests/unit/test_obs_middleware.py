from fastapi import FastAPI
from fastapi.testclient import TestClient

from finrobot.obs.context import current_trace
from finrobot.obs.middleware import RequestTraceMiddleware


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestTraceMiddleware)

    @app.get("/probe")
    async def probe() -> dict[str, str]:
        return {"rid": current_trace()["request_id"]}

    return app


def test_request_id_bound_during_handler_and_in_header() -> None:
    client = TestClient(_app())
    resp = client.get("/probe")
    assert resp.status_code == 200
    rid = resp.json()["rid"]
    assert rid != "-"
    assert resp.headers["X-Request-ID"] == rid


def test_context_resets_after_request() -> None:
    client = TestClient(_app())
    client.get("/probe")
    assert current_trace()["request_id"] == "-"


def test_incoming_request_id_header_is_honored() -> None:
    client = TestClient(_app())
    resp = client.get("/probe", headers={"X-Request-ID": "client-supplied-id"})
    assert resp.json()["rid"] == "client-supplied-id"
    assert resp.headers["X-Request-ID"] == "client-supplied-id"
