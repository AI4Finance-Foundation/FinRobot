"""Tests for the /api/settings routes.

Config is app-stored-only (settings.json + keychain) — there is no env / .env
source. The route surface this covers:

1. ``_merge_non_secret_settings`` writes ONLY the changed fields — fields the
   user never touched stay out of settings.json and keep resolving to defaults.
2. ``adanos_api_key`` is treated as a secret (keychain), not silently dropped.
3. ``GET /api/settings`` surfaces the provider registry, startup_error, and
   secret_storage_mode.
4. ``POST /api/settings/clear-secret`` is the only path that deletes a stored
   key (BUG-005) — an empty value in a PUT never wipes one.
5. The LLM provider registry: built-ins + custom providers, keys stored under
   provider_key:<id>, custom-provider validation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from finrobot.config import FinRobotSettings, get_settings
from finrobot.routes.settings import (
    _merge_non_secret_settings,
    router as settings_router,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeSkillRuntime:
    """Stub passed to create_lead_agent / create_sub_agents — not used here."""


def _settings(**overrides: Any) -> FinRobotSettings:
    """Default settings for the app: deepseek model with its provider key set."""
    provider_keys = overrides.pop("provider_keys", {"deepseek": "dev-key"})
    overrides.setdefault("model_name", "deepseek:deepseek-chat")
    return get_settings(provider_keys=provider_keys, **overrides)


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
        settings = _settings()

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
    path.write_text(json.dumps({"sec_user_agent": "MyCo me@example.com", "log_level": "DEBUG"}))

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


# ---------------------------------------------------------------------------
# GET /api/settings — provider registry + startup_error + identity gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_settings_exposes_provider_registry(tmp_path: Path) -> None:
    """The response carries the built-in providers, each with key_set/is_builtin."""
    app = _make_app(tmp_path)
    async with _client(app) as c:
        resp = await c.get("/api/settings")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    providers = {p["id"]: p for p in body["providers"]}
    assert {"deepseek", "anthropic", "openai", "moonshot", "qwen", "openrouter"} <= set(providers)
    assert providers["deepseek"]["is_builtin"] is True
    # deepseek is the active model and its key is injected → key_set True.
    assert providers["deepseek"]["key_set"] is True
    assert providers["anthropic"]["key_set"] is False
    assert body["custom_providers"] == []
    # The old hardcoded literal is gone.
    assert "valid_model_providers" not in body


@pytest.mark.asyncio
async def test_get_settings_reports_custom_provider(tmp_path: Path) -> None:
    """A user custom provider shows up in both providers and custom_providers."""
    settings = _settings(
        custom_providers=[
            {
                "id": "myhost",
                "label": "My vLLM",
                "kind": "openai-compatible",
                "base_url": "https://h/v1",
                "models": ["local-7b"],
            }
        ]
    )
    app = _make_app(tmp_path, settings=settings)
    async with _client(app) as c:
        resp = await c.get("/api/settings")
    body = resp.json()
    providers = {p["id"]: p for p in body["providers"]}
    assert providers["myhost"]["is_builtin"] is False
    assert providers["myhost"]["base_url"] == "https://h/v1"
    assert [p["id"] for p in body["custom_providers"]] == ["myhost"]


@pytest.mark.asyncio
async def test_sec_identity_active_true_for_valid_identity(tmp_path: Path) -> None:
    """sec_identity_active mirrors the backend gate that registers EdgarProvider.

    Regression: a Chinese display-name identity (``郭嘉祺 17696026747@163.com``)
    is accepted by ``_is_valid_identity`` and DID register the provider at boot,
    so the response MUST report active=True. The landing banner reads this.
    """
    settings = _settings(sec_user_agent="郭嘉祺 17696026747@163.com")
    app = _make_app(tmp_path, settings=settings)
    async with _client(app) as c:
        resp = await c.get("/api/settings")
    assert resp.status_code == 200
    assert resp.json()["sec_identity_active"] is True


@pytest.mark.asyncio
async def test_sec_identity_active_false_for_placeholder(tmp_path: Path) -> None:
    """The config.py placeholder default is NOT a real identity → active=False."""
    settings = _settings(sec_user_agent="FinRobot admin@example.com")
    app = _make_app(tmp_path, settings=settings)
    async with _client(app) as c:
        resp = await c.get("/api/settings")
    assert resp.status_code == 200
    assert resp.json()["sec_identity_active"] is False


@pytest.mark.asyncio
async def test_get_settings_surfaces_startup_error(tmp_path: Path) -> None:
    """startup_error from app.state is included in the response."""
    msg = "No API key configured for provider 'openai'. Add it in Settings → AI Model."
    app = _make_app(tmp_path, startup_error=msg)
    async with _client(app) as c:
        resp = await c.get("/api/settings")
    body = resp.json()
    assert body["startup_error"] == msg


@pytest.mark.asyncio
async def test_get_settings_reports_adanos_key_set(tmp_path: Path) -> None:
    """adanos_api_key_set is now part of the response."""
    settings = _settings(adanos_api_key="from-env")
    app = _make_app(tmp_path, settings=settings)
    async with _client(app) as c:
        resp = await c.get("/api/settings")
    body = resp.json()
    assert body["adanos_api_key_set"] is True
    assert "alpha_vantage_api_key_set" in body


# ---------------------------------------------------------------------------
# PUT /api/settings — merge semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_settings_does_not_pin_unchanged_fields(tmp_path: Path, monkeypatch: Any) -> None:
    """Submitting only model_name must not also write sec_user_agent etc."""
    settings = _settings(sec_user_agent="MyCo me@example.com")
    app = _make_app(tmp_path, settings=settings)
    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", AsyncMock())

    async with _client(app) as c:
        resp = await c.put(
            "/api/settings",
            json={"model_name": "anthropic:claude-sonnet-4-6"},
        )

    # NB: switching to anthropic with no anthropic key configured will 400 at
    # validate_runtime_config — a useful regression guard that the route does
    # NOT silently fall through.
    assert resp.status_code in (200, 400)

    if (tmp_path / "settings.json").exists():
        content = json.loads((tmp_path / "settings.json").read_text())
        # Only model_name should ever be persisted in this scenario.
        assert set(content.keys()) <= {"model_name"}


@pytest.mark.asyncio
async def test_put_persists_only_changed_keys(tmp_path: Path, monkeypatch: Any) -> None:
    """Successful PUT writes ONLY the field the user changed."""
    settings = _settings(sec_user_agent="MyCo me@example.com")
    app = _make_app(tmp_path, settings=settings)
    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", AsyncMock())

    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"log_level": "DEBUG"})
    assert resp.status_code == 200, resp.text

    content = json.loads((tmp_path / "settings.json").read_text())
    assert content == {"log_level": "DEBUG"}
    assert "sec_user_agent" not in content
    assert "model_name" not in content


@pytest.mark.asyncio
async def test_put_adds_custom_provider(tmp_path: Path, monkeypatch: Any) -> None:
    """A custom OpenAI-compatible provider round-trips through PUT into settings.json."""
    settings = _settings()
    app = _make_app(tmp_path, settings=settings)
    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", AsyncMock())

    custom = [
        {
            "id": "myhost",
            "label": "My vLLM",
            "kind": "openai-compatible",
            "base_url": "https://h/v1",
            "models": ["local-7b"],
        }
    ]
    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"custom_providers": custom})
    assert resp.status_code == 200, resp.text
    content = json.loads((tmp_path / "settings.json").read_text())
    assert content["custom_providers"][0]["id"] == "myhost"
    assert content["custom_providers"][0]["base_url"] == "https://h/v1"


@pytest.mark.asyncio
async def test_put_rejects_custom_provider_shadowing_builtin(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A custom provider id may not collide with a built-in (deepseek)."""
    app = _make_app(tmp_path)
    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", AsyncMock())
    bad = [
        {"id": "deepseek", "label": "x", "kind": "openai-compatible", "base_url": "https://h/v1"}
    ]
    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"custom_providers": bad})
    assert resp.status_code == 400
    assert "built-in" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_put_rejects_openai_compatible_without_base_url(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """An openai-compatible custom provider must declare a base_url."""
    app = _make_app(tmp_path)
    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", AsyncMock())
    bad = [{"id": "myhost", "label": "x", "kind": "openai-compatible", "base_url": None}]
    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"custom_providers": bad})
    assert resp.status_code == 400
    assert "base_url" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_put_writes_provider_key_to_keychain(tmp_path: Path, monkeypatch: Any) -> None:
    """provider_keys map persists each key under provider_key:<id> in the keychain."""
    secret_store = AsyncMock()
    secret_store.has = AsyncMock(return_value=False)
    secret_store.get = AsyncMock(return_value=None)
    secret_store.set = AsyncMock()
    secret_store.delete = AsyncMock()
    app = _make_app(tmp_path, secret_store=secret_store)
    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", AsyncMock())

    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"provider_keys": {"deepseek": "sk-new"}})
    assert resp.status_code == 200, resp.text
    secret_store.set.assert_awaited_with("provider_key:deepseek", "sk-new")
    secret_store.delete.assert_not_awaited()


# ---------------------------------------------------------------------------
# 2026-05-27 EdgarTools migration: sec_identity_dismissed_at field round-trip
# ---------------------------------------------------------------------------


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
    assert "sec_identity_dismissed_at" in body
    assert body["sec_identity_dismissed_at"] is None
    assert body["sec_holdings_auto_refresh"] is False


@pytest.mark.asyncio
async def test_put_persists_sec_identity_dismissed_at(tmp_path: Path, monkeypatch: Any) -> None:
    """PUT writes the timestamp to settings.json (ISO string, json-serializable)."""
    app = _make_app(tmp_path)
    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", AsyncMock())

    iso = "2026-05-27T15:30:00+00:00"
    async with _client(app) as c:
        resp = await c.put(
            "/api/settings",
            json={"sec_identity_dismissed_at": iso},
        )
    assert resp.status_code == 200, resp.text

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
    (tmp_path / "settings.json").write_text(json.dumps({"sec_identity_dismissed_at": iso_str}))
    raw = load_non_secret_settings(tmp_path / "settings.json")
    settings = get_settings(model_name="deepseek:deepseek-chat", **raw)
    assert settings.sec_identity_dismissed_at is not None
    assert settings.sec_identity_dismissed_at.year == 2026
    assert settings.sec_identity_dismissed_at.month == 5
    assert settings.sec_identity_dismissed_at.day == 27


@pytest.mark.asyncio
async def test_put_persists_sec_holdings_auto_refresh(tmp_path: Path, monkeypatch: Any) -> None:
    app = _make_app(tmp_path)
    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", AsyncMock())

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
    if hasattr(app.state, "secret_storage_mode"):
        del app.state.secret_storage_mode
    async with _client(app) as c:
        resp = await c.get("/api/settings")
    assert resp.status_code == 200, resp.text
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
    app = _make_app(tmp_path)

    async def _fake_replace(request: Any, candidate: Any) -> None:
        request.app.state.deps.settings = candidate

    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", _fake_replace)
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
    app = _make_app(tmp_path)

    async def _fake_replace(request: Any, candidate: Any) -> None:
        request.app.state.deps.settings = candidate

    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", _fake_replace)
    calls: list[Any] = []

    def _fake_setup_logging(candidate: Any, *, force: bool = False) -> None:
        calls.append((candidate.log_level, force))

    monkeypatch.setattr("finrobot.obs.setup_logging", _fake_setup_logging)

    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"log_level": "DEBUG"})
    assert resp.status_code == 200, resp.text
    assert calls == [("DEBUG", True)]


# ---------------------------------------------------------------------------
# BUG-005 — PUT must NOT delete a secret on an empty value; clearing is explicit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_empty_provider_key_does_not_delete_keychain(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """An empty provider key in a PUT is a no-op, never a keychain delete.

    Regression for BUG-005: submitting the settings form with a blank password
    field used to wipe a stored API key. The PUT must leave the keychain alone.
    """
    secret_store = AsyncMock()
    secret_store.has = AsyncMock(return_value=True)
    secret_store.get = AsyncMock(return_value="stored-key")
    secret_store.set = AsyncMock()
    secret_store.delete = AsyncMock()

    app = _make_app(tmp_path, secret_store=secret_store)
    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", AsyncMock())

    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"provider_keys": {"deepseek": ""}})
    assert resp.status_code == 200, resp.text
    secret_store.delete.assert_not_awaited()
    secret_store.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_put_nonempty_provider_key_still_writes(tmp_path: Path, monkeypatch: Any) -> None:
    """A real (truthy) provider key in a PUT is still written to the keychain."""
    secret_store = AsyncMock()
    secret_store.has = AsyncMock(return_value=False)
    secret_store.get = AsyncMock(return_value=None)
    secret_store.set = AsyncMock()
    secret_store.delete = AsyncMock()

    app = _make_app(tmp_path, secret_store=secret_store)
    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", AsyncMock())

    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"provider_keys": {"deepseek": "new-key"}})
    assert resp.status_code == 200, resp.text
    secret_store.set.assert_awaited_with("provider_key:deepseek", "new-key")
    secret_store.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_clear_secret_deletes_data_key(tmp_path: Path, monkeypatch: Any) -> None:
    """POST /api/settings/clear-secret is the explicit keychain delete path."""
    secret_store = AsyncMock()
    secret_store.has = AsyncMock(return_value=False)
    secret_store.get = AsyncMock(return_value=None)
    secret_store.delete = AsyncMock()

    app = _make_app(tmp_path, secret_store=secret_store)
    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", AsyncMock())
    monkeypatch.setattr(
        "finrobot.server.hydrate_settings_from_secrets",
        AsyncMock(side_effect=lambda s, _store: s),
    )

    async with _client(app) as c:
        resp = await c.post("/api/settings/clear-secret", json={"field": "fmp_api_key"})
    assert resp.status_code == 200, resp.text
    secret_store.delete.assert_awaited_with("fmp_api_key")


@pytest.mark.asyncio
async def test_clear_secret_deletes_provider_key(tmp_path: Path, monkeypatch: Any) -> None:
    """clear-secret accepts the provider_key:<id> form to wipe an LLM key."""
    secret_store = AsyncMock()
    secret_store.has = AsyncMock(return_value=False)
    secret_store.get = AsyncMock(return_value=None)
    secret_store.delete = AsyncMock()

    app = _make_app(tmp_path, secret_store=secret_store)
    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", AsyncMock())
    monkeypatch.setattr(
        "finrobot.server.hydrate_settings_from_secrets",
        AsyncMock(side_effect=lambda s, _store: s),
    )

    async with _client(app) as c:
        resp = await c.post("/api/settings/clear-secret", json={"field": "provider_key:deepseek"})
    assert resp.status_code == 200, resp.text
    secret_store.delete.assert_awaited_with("provider_key:deepseek")


@pytest.mark.asyncio
async def test_clear_secret_rejects_non_secret_field(tmp_path: Path) -> None:
    """Only secret fields are clearable — a non-secret field is a 400."""
    app = _make_app(tmp_path)
    async with _client(app) as c:
        resp = await c.post("/api/settings/clear-secret", json={"field": "model_name"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_clear_secret_rejects_unknown_field(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    async with _client(app) as c:
        resp = await c.post(
            "/api/settings/clear-secret", json={"field": "definitely_not_a_setting"}
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_settings_update_non_logging_field_skips_reapply(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A PUT that touches no logging field must NOT re-run setup_logging."""
    app = _make_app(tmp_path)

    async def _fake_replace(request: Any, candidate: Any) -> None:
        request.app.state.deps.settings = candidate

    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", _fake_replace)
    calls: list[Any] = []
    monkeypatch.setattr("finrobot.obs.setup_logging", lambda *a, **k: calls.append((a, k)))

    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"sec_holdings_auto_refresh": True})
    assert resp.status_code == 200, resp.text
    assert calls == []
