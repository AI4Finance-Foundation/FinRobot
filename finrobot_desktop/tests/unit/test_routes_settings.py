"""Tests for the /api/settings routes.

Covers the bug fixes shipped with the "config-chain transparency + sidecar
error visibility + startup validate" change:

1. ``_merge_non_secret_settings`` writes ONLY the changed fields — fields the
   user never touched stay out of settings.json so .env keeps winning.
2. ``adanos_api_key`` is treated as a secret (keychain), not silently dropped.
3. ``POST /api/settings/reset`` clears the listed fields from settings.json
   (and from keychain for secrets) so .env / env-vars regain priority.
4. ``GET /api/settings`` reports ``field_sources`` and ``startup_error``.
5. ``_write_non_secret_settings`` is the deprecated alias that explicitly
   refuses to run, so a regression to "write every field" cannot happen.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from finrobot.config import FinRobotSettings
from finrobot.routes.settings import (
    _merge_non_secret_settings,
    _write_non_secret_settings,
    router as settings_router,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeSkillRuntime:
    """Stub passed to create_lead_agent / create_sub_agents — not used here."""


def _make_app(
    tmp_path: Path,
    *,
    settings: FinRobotSettings | None = None,
    secret_store: AsyncMock | None = None,
    startup_error: str | None = None,
) -> FastAPI:
    """Build a minimal FastAPI app wired with the settings router only."""
    app = FastAPI()
    app.include_router(settings_router)

    if settings is None:
        settings = FinRobotSettings(
            model_name="deepseek:deepseek-chat",
            deepseek_api_key="dev-key",
        )

    if secret_store is None:
        secret_store = AsyncMock()
        secret_store.has = AsyncMock(return_value=False)
        secret_store.get = AsyncMock(return_value=None)
        secret_store.set = AsyncMock()
        secret_store.delete = AsyncMock()

    deps = MagicMock()
    deps.settings = settings
    deps.data_layer = MagicMock()
    deps.data_layer.close = AsyncMock()
    deps.skill_runtime = _FakeSkillRuntime()

    app.state.deps = deps
    app.state.secret_store = secret_store
    app.state.settings_path = tmp_path / "settings.json"
    app.state.startup_error = startup_error
    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# _merge_non_secret_settings — the centrepiece of the fix
# ---------------------------------------------------------------------------


def test_merge_writes_only_changed_fields(tmp_path: Path) -> None:
    """Updating model_name does NOT pin every other field into settings.json."""
    path = tmp_path / "settings.json"

    _merge_non_secret_settings(path, {"model_name": "anthropic:claude-sonnet-4-6"})

    content = json.loads(path.read_text())
    assert content == {"model_name": "anthropic:claude-sonnet-4-6"}
    # CRITICAL: sec_user_agent / model_data / ... must NOT be present.
    assert "sec_user_agent" not in content
    assert "model_data" not in content
    assert "log_level" not in content


def test_merge_preserves_existing_fields(tmp_path: Path) -> None:
    """Existing settings.json entries survive an unrelated update."""
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"sec_user_agent": "MyCo me@example.com", "log_level": "DEBUG"})
    )

    _merge_non_secret_settings(path, {"model_name": "openai:gpt-4o"})

    content = json.loads(path.read_text())
    assert content == {
        "sec_user_agent": "MyCo me@example.com",
        "log_level": "DEBUG",
        "model_name": "openai:gpt-4o",
    }


def test_merge_with_empty_updates_is_noop(tmp_path: Path) -> None:
    """No updates -> no file written (we don't even create the file)."""
    path = tmp_path / "settings.json"
    _merge_non_secret_settings(path, {})
    assert not path.exists()


def test_merge_ignores_unknown_fields(tmp_path: Path) -> None:
    """Random kwargs are silently dropped — only the allowlist is written."""
    path = tmp_path / "settings.json"
    _merge_non_secret_settings(
        path,
        {"model_name": "openai:gpt-4o", "definitely_not_a_setting": "bad"},
    )
    content = json.loads(path.read_text())
    assert content == {"model_name": "openai:gpt-4o"}


def test_deprecated_write_non_secret_raises(tmp_path: Path) -> None:
    """Regression guard: the old "write every field" function refuses to run."""
    settings = FinRobotSettings(model_name="deepseek:deepseek-chat", deepseek_api_key="x")
    with pytest.raises(RuntimeError, match="deprecated"):
        _write_non_secret_settings(tmp_path / "settings.json", settings)


# ---------------------------------------------------------------------------
# GET /api/settings — source attribution + startup_error surfacing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_settings_includes_field_sources(tmp_path: Path) -> None:
    """field_sources maps every known field to its origin."""
    settings = FinRobotSettings(
        model_name="deepseek:deepseek-chat",
        deepseek_api_key="env-key",
    )
    app = _make_app(tmp_path, settings=settings)
    async with _client(app) as c:
        resp = await c.get("/api/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert "field_sources" in body
    # adanos_api_key MUST appear now that we tracked it as a secret.
    assert "adanos_api_key" in body["field_sources"]
    # When nothing is in settings.json and keychain returns nothing,
    # a populated value is attributed to env (e.g. via .env load).
    assert body["field_sources"]["deepseek_api_key"] == "env"


@pytest.mark.asyncio
async def test_sec_identity_active_true_for_valid_identity(tmp_path: Path) -> None:
    """sec_identity_active mirrors the backend gate that registers EdgarProvider.

    Regression: a Chinese display-name identity (``郭嘉祺 17696026747@163.com``)
    is accepted by ``_is_valid_identity`` and DID register the provider at boot,
    so the response MUST report active=True. The landing banner reads this.
    """
    settings = FinRobotSettings(
        model_name="deepseek:deepseek-chat",
        deepseek_api_key="env-key",
        sec_user_agent="郭嘉祺 17696026747@163.com",
    )
    app = _make_app(tmp_path, settings=settings)
    async with _client(app) as c:
        resp = await c.get("/api/settings")
    assert resp.status_code == 200
    assert resp.json()["sec_identity_active"] is True


@pytest.mark.asyncio
async def test_sec_identity_active_false_for_placeholder(tmp_path: Path) -> None:
    """The config.py placeholder default is NOT a real identity → active=False."""
    settings = FinRobotSettings(
        model_name="deepseek:deepseek-chat",
        deepseek_api_key="env-key",
        sec_user_agent="FinRobot admin@example.com",
    )
    app = _make_app(tmp_path, settings=settings)
    async with _client(app) as c:
        resp = await c.get("/api/settings")
    assert resp.status_code == 200
    assert resp.json()["sec_identity_active"] is False


@pytest.mark.asyncio
async def test_get_settings_marks_settings_json_source(tmp_path: Path) -> None:
    """A field present in settings.json wins source attribution."""
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"model_name": "openai:gpt-4o"}))
    settings = FinRobotSettings(
        model_name="openai:gpt-4o",
        openai_api_key="x",
    )
    app = _make_app(tmp_path, settings=settings)
    async with _client(app) as c:
        resp = await c.get("/api/settings")
    body = resp.json()
    assert body["field_sources"]["model_name"] == "settings_json"


@pytest.mark.asyncio
async def test_get_settings_marks_keychain_source(tmp_path: Path) -> None:
    """A secret present in the keychain wins attribution over env."""
    secret_store = AsyncMock()

    async def _has(k: str) -> bool:
        return k == "anthropic_api_key"

    secret_store.has = AsyncMock(side_effect=_has)
    secret_store.get = AsyncMock(return_value=None)

    settings = FinRobotSettings(
        model_name="anthropic:claude-sonnet-4-6",
        anthropic_api_key="hydrated",
    )
    app = _make_app(tmp_path, settings=settings, secret_store=secret_store)
    async with _client(app) as c:
        resp = await c.get("/api/settings")
    body = resp.json()
    assert body["field_sources"]["anthropic_api_key"] == "keychain"


@pytest.mark.asyncio
async def test_get_settings_surfaces_startup_error(tmp_path: Path) -> None:
    """startup_error from app.state is included in the response."""
    app = _make_app(tmp_path, startup_error="FINROBOT_OPENAI_API_KEY is not set")
    async with _client(app) as c:
        resp = await c.get("/api/settings")
    body = resp.json()
    assert body["startup_error"] == "FINROBOT_OPENAI_API_KEY is not set"


@pytest.mark.asyncio
async def test_get_settings_reports_adanos_key_set(tmp_path: Path) -> None:
    """adanos_api_key_set is now part of the response."""
    settings = FinRobotSettings(
        model_name="deepseek:deepseek-chat",
        deepseek_api_key="x",
        adanos_api_key="from-env",
    )
    app = _make_app(tmp_path, settings=settings)
    async with _client(app) as c:
        resp = await c.get("/api/settings")
    body = resp.json()
    assert body["adanos_api_key_set"] is True
    assert "alpha_vantage_api_key_set" in body


# ---------------------------------------------------------------------------
# POST /api/settings/reset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_strips_field_from_settings_json(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Reset removes the listed field from settings.json (does NOT copy .env in)."""
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"model_name": "openai:gpt-4o", "sec_user_agent": "X"})
    )

    settings = FinRobotSettings(
        model_name="openai:gpt-4o",
        openai_api_key="x",
    )
    app = _make_app(tmp_path, settings=settings)

    # Patch the runtime-replacement helpers so reset doesn't try to spin up
    # real PydanticAI agents.
    monkeypatch.setattr(
        "finrobot.routes.settings._replace_runtime_settings",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "finrobot.server.hydrate_settings_from_secrets",
        AsyncMock(side_effect=lambda s, _store: s),
    )

    async with _client(app) as c:
        resp = await c.post(
            "/api/settings/reset", json={"fields": ["model_name"]}
        )
    assert resp.status_code == 200, resp.text

    content = json.loads(settings_path.read_text())
    assert "model_name" not in content
    # sec_user_agent untouched
    assert content["sec_user_agent"] == "X"


@pytest.mark.asyncio
async def test_reset_deletes_keychain_for_secrets(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Reset of a secret field clears it from the keychain."""
    secret_store = AsyncMock()
    secret_store.has = AsyncMock(return_value=True)
    secret_store.get = AsyncMock(return_value="keychain-value")
    secret_store.delete = AsyncMock()

    settings = FinRobotSettings(
        model_name="anthropic:claude-sonnet-4-6",
        anthropic_api_key="keychain-value",
    )
    app = _make_app(tmp_path, settings=settings, secret_store=secret_store)
    monkeypatch.setattr(
        "finrobot.routes.settings._replace_runtime_settings", AsyncMock()
    )
    monkeypatch.setattr(
        "finrobot.server.hydrate_settings_from_secrets",
        AsyncMock(side_effect=lambda s, _store: s),
    )

    async with _client(app) as c:
        resp = await c.post(
            "/api/settings/reset",
            json={"fields": ["anthropic_api_key"]},
        )
    assert resp.status_code == 200, resp.text
    secret_store.delete.assert_awaited_with("anthropic_api_key")


@pytest.mark.asyncio
async def test_reset_rejects_unknown_field(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    async with _client(app) as c:
        resp = await c.post(
            "/api/settings/reset", json={"fields": ["definitely_not_a_setting"]}
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_reset_with_empty_fields_400(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    async with _client(app) as c:
        resp = await c.post("/api/settings/reset", json={"fields": []})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# PUT /api/settings — merge semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_settings_does_not_pin_unchanged_fields(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Submitting only model_name must not also write sec_user_agent etc."""
    settings = FinRobotSettings(
        model_name="deepseek:deepseek-chat",
        deepseek_api_key="x",
        sec_user_agent="FromDotEnv me@example.com",
    )
    app = _make_app(tmp_path, settings=settings)
    monkeypatch.setattr(
        "finrobot.routes.settings._replace_runtime_settings", AsyncMock()
    )

    async with _client(app) as c:
        resp = await c.put(
            "/api/settings",
            json={"model_name": "anthropic:claude-sonnet-4-6"},
        )

    # NB: this PUT also implicitly carries any secret merge candidate built
    # by the route — but validate_runtime_config will reject "anthropic" with
    # no key in the test settings, so we expect 400 here. That itself is a
    # useful regression guard: the route does NOT silently fall through.
    assert resp.status_code in (200, 400)

    if (tmp_path / "settings.json").exists():
        content = json.loads((tmp_path / "settings.json").read_text())
        # Only model_name should ever be persisted in this scenario.
        assert set(content.keys()) <= {"model_name"}


@pytest.mark.asyncio
async def test_put_persists_only_changed_keys(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Successful PUT writes ONLY the field the user changed."""
    settings = FinRobotSettings(
        model_name="deepseek:deepseek-chat",
        deepseek_api_key="dev-key",
        sec_user_agent="FromDotEnv me@example.com",
    )
    app = _make_app(tmp_path, settings=settings)
    monkeypatch.setattr(
        "finrobot.routes.settings._replace_runtime_settings", AsyncMock()
    )

    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"log_level": "DEBUG"})
    assert resp.status_code == 200, resp.text

    content = json.loads((tmp_path / "settings.json").read_text())
    assert content == {"log_level": "DEBUG"}
    # sec_user_agent stays in .env / pydantic settings; must NOT be pinned.
    assert "sec_user_agent" not in content
    assert "model_name" not in content


# ---------------------------------------------------------------------------
# 2026-05-27 EdgarTools migration: sec_identity_dismissed_at field
# ---------------------------------------------------------------------------
#
# Why this trio of tests: ``sec_identity_dismissed_at`` is the first
# datetime-typed field in FinRobotSettings. json.dumps can't serialize
# datetime by default; _merge_non_secret_settings now passes default=str so
# the ISO-formatted timestamp persists, and pydantic-settings coerces the
# string back into a datetime on next boot. These tests seal that round
# trip end-to-end.


@pytest.mark.asyncio
async def test_get_settings_returns_sec_identity_dismissed_at_null(
    tmp_path: Path,
) -> None:
    """Default value is None — banner has never been dismissed."""
    app = _make_app(tmp_path)
    async with _client(app) as c:
        resp = await c.get("/api/settings")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Field present in the response payload (renders the landing banner state)
    assert "sec_identity_dismissed_at" in body
    assert body["sec_identity_dismissed_at"] is None
    assert body["sec_holdings_auto_refresh"] is False


@pytest.mark.asyncio
async def test_put_persists_sec_identity_dismissed_at(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """PUT writes the timestamp to settings.json (ISO string, json-serializable)."""
    app = _make_app(tmp_path)
    monkeypatch.setattr(
        "finrobot.routes.settings._replace_runtime_settings", AsyncMock()
    )

    iso = "2026-05-27T15:30:00+00:00"
    async with _client(app) as c:
        resp = await c.put(
            "/api/settings", json={"sec_identity_dismissed_at": iso},
        )
    assert resp.status_code == 200, resp.text

    # settings.json on disk contains the ISO string (json-safe via default=str).
    # ``_replace_runtime_settings`` is mocked so the GET-side runtime
    # settings don't reflect the PUT — coverage of the boot-time coerce
    # is in ``test_load_non_secret_settings_coerces_dismissed_at`` below.
    content = json.loads((tmp_path / "settings.json").read_text())
    assert "sec_identity_dismissed_at" in content
    assert "2026-05-27" in str(content["sec_identity_dismissed_at"])


@pytest.mark.asyncio
async def test_load_non_secret_settings_coerces_dismissed_at(
    tmp_path: Path,
) -> None:
    """Reboot path: ISO string in settings.json → datetime on FinRobotSettings."""
    from finrobot.routes.settings import load_non_secret_settings

    iso_str = "2026-05-27T15:30:00+00:00"
    (tmp_path / "settings.json").write_text(
        json.dumps({"sec_identity_dismissed_at": iso_str})
    )
    raw = load_non_secret_settings(tmp_path / "settings.json")
    # raw dict carries the ISO string; pydantic-settings coerces on
    # FinRobotSettings(**raw)
    settings = FinRobotSettings(
        model_name="deepseek:deepseek-chat",
        deepseek_api_key="dev-key",
        **raw,
    )
    assert settings.sec_identity_dismissed_at is not None
    assert settings.sec_identity_dismissed_at.year == 2026
    assert settings.sec_identity_dismissed_at.month == 5
    assert settings.sec_identity_dismissed_at.day == 27


@pytest.mark.asyncio
async def test_put_persists_sec_holdings_auto_refresh(tmp_path: Path, monkeypatch: Any) -> None:
    app = _make_app(tmp_path)
    monkeypatch.setattr(
        "finrobot.routes.settings._replace_runtime_settings", AsyncMock()
    )

    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"sec_holdings_auto_refresh": False})

    assert resp.status_code == 200, resp.text
    content = json.loads((tmp_path / "settings.json").read_text())
    assert content["sec_holdings_auto_refresh"] is False


# ---------------------------------------------------------------------------
# B1 — secret_storage_mode surfaced via GET /api/settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_settings_reports_keychain_mode(tmp_path: Path) -> None:
    """Default app.state.secret_storage_mode 'keychain' is reflected in response."""
    app = _make_app(tmp_path)
    # Simulate the value set by server.lifespan after create_secret_store().
    app.state.secret_storage_mode = "keychain"
    async with _client(app) as c:
        resp = await c.get("/api/settings")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "secret_storage_mode" in body
    assert body["secret_storage_mode"] == "keychain"


@pytest.mark.asyncio
async def test_get_settings_reports_plaintext_mode(tmp_path: Path) -> None:
    """When keychain is unavailable, 'plaintext' mode is reported so the UI can warn."""
    app = _make_app(tmp_path)
    app.state.secret_storage_mode = "plaintext"
    async with _client(app) as c:
        resp = await c.get("/api/settings")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["secret_storage_mode"] == "plaintext"


@pytest.mark.asyncio
async def test_get_settings_defaults_to_keychain_when_state_missing(tmp_path: Path) -> None:
    """If app.state.secret_storage_mode is absent (old test setup), defaults to 'keychain'."""
    app = _make_app(tmp_path)
    # Do NOT set app.state.secret_storage_mode — simulate missing state.
    if hasattr(app.state, "secret_storage_mode"):
        del app.state.secret_storage_mode
    async with _client(app) as c:
        resp = await c.get("/api/settings")
    assert resp.status_code == 200, resp.text
    # Default fallback must be 'keychain', not a crash.
    assert resp.json()["secret_storage_mode"] == "keychain"


# ---------------------------------------------------------------------------
# Task 11: log_to_file + log_retention_days surfaced through settings route
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_settings_exposes_logging_fields(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    async with _client(app) as c:
        resp = await c.get("/api/settings")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "log_to_file" in body
    assert "log_retention_days" in body


@pytest.mark.asyncio
async def test_settings_update_logging_fields(tmp_path: Path, monkeypatch: Any) -> None:
    settings = FinRobotSettings(
        model_name="deepseek:deepseek-chat",
        deepseek_api_key="dev-key",
    )
    app = _make_app(tmp_path, settings=settings)

    # Mock _replace_runtime_settings but still update deps.settings so
    # _build_response reads the candidate (updated) settings.
    async def _fake_replace(request: Any, candidate: Any) -> None:
        request.app.state.deps.settings = candidate

    monkeypatch.setattr(
        "finrobot.routes.settings._replace_runtime_settings", _fake_replace
    )
    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"log_retention_days": 14, "log_to_file": False})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["log_retention_days"] == 14
    assert body["log_to_file"] is False


@pytest.mark.asyncio
async def test_settings_update_logging_fields_reapplies_logging(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Changing a logging field re-runs setup_logging so the PUT takes effect
    immediately instead of silently waiting for the next server restart.
    """
    settings = FinRobotSettings(
        model_name="deepseek:deepseek-chat",
        deepseek_api_key="dev-key",
    )
    app = _make_app(tmp_path, settings=settings)

    async def _fake_replace(request: Any, candidate: Any) -> None:
        request.app.state.deps.settings = candidate

    monkeypatch.setattr(
        "finrobot.routes.settings._replace_runtime_settings", _fake_replace
    )
    calls: list[Any] = []

    def _fake_setup_logging(candidate: Any, *, force: bool = False) -> None:
        calls.append((candidate.log_level, force))

    monkeypatch.setattr("finrobot.obs.setup_logging", _fake_setup_logging)

    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"log_level": "DEBUG"})
    assert resp.status_code == 200, resp.text
    assert calls == [("DEBUG", True)]


@pytest.mark.asyncio
async def test_settings_update_non_logging_field_skips_reapply(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A PUT that touches no logging field must NOT re-run setup_logging."""
    settings = FinRobotSettings(
        model_name="deepseek:deepseek-chat",
        deepseek_api_key="dev-key",
    )
    app = _make_app(tmp_path, settings=settings)

    async def _fake_replace(request: Any, candidate: Any) -> None:
        request.app.state.deps.settings = candidate

    monkeypatch.setattr(
        "finrobot.routes.settings._replace_runtime_settings", _fake_replace
    )
    calls: list[Any] = []
    monkeypatch.setattr(
        "finrobot.obs.setup_logging", lambda *a, **k: calls.append((a, k))
    )

    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"sec_holdings_auto_refresh": True})
    assert resp.status_code == 200, resp.text
    assert calls == []
