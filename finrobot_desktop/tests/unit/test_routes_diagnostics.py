import io
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from finrobot.routes.diagnostics import router


def _client(logs_dir) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.logs_dir = logs_dir
    return TestClient(app)


def test_export_returns_zip_with_logs(tmp_path) -> None:
    (tmp_path / "finrobot.log").write_text('{"msg":"hi"}\n')
    (tmp_path / "finrobot.log.2026-05-28").write_text('{"msg":"old"}\n')
    resp = _client(tmp_path).get("/api/diagnostics/logs/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = set(zf.namelist())
    assert "finrobot.log" in names
    assert "finrobot.log.2026-05-28" in names


def test_export_empty_dir_returns_empty_zip(tmp_path) -> None:
    resp = _client(tmp_path).get("/api/diagnostics/logs/export")
    assert resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    assert zf.namelist() == []
