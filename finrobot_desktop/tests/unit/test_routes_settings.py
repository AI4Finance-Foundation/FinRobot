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
import os
import stat
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from finrobot.config import FinRobotSettings, get_settings
from finrobot.routes.settings import (
    _DATA_PROBES,
    _merge_non_secret_settings,
    load_non_secret_settings,
    load_non_secret_settings_with_error,
    router as settings_router,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeSkillRuntime:
    """Stub passed to create_lead_agent / create_sub_agents — not used here."""


def _settings(**overrides: Any) -> FinRobotSettings:
    """Default settings for the app: openai model with its provider key set."""
    provider_keys = overrides.pop("provider_keys", {"openai": "dev-key"})
    overrides.setdefault("model_name", "openai:gpt-4o")
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
    # CRITICAL: sec_user_agent / custom_providers / ... must NOT be present.
    assert "sec_user_agent" not in content
    assert "custom_providers" not in content
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


def test_merge_accepts_peer_sticky_window(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"

    _merge_non_secret_settings(path, {"peer_sticky_max_age_days": 0})

    content = json.loads(path.read_text())
    assert content == {"peer_sticky_max_age_days": 0}


# ---------------------------------------------------------------------------
# settings.json torn-write resilience — atomic write side
# (Tauri SIGKILLs the sidecar at exit; a bare write_text could leave a
# truncated file that then killed every subsequent boot.)
# ---------------------------------------------------------------------------


def test_merge_writes_via_atomic_replace_and_leaves_no_temp(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """The write goes through os.replace (temp + rename), and no .tmp survives."""
    path = tmp_path / "settings.json"
    replace_calls: list[tuple[str, str]] = []
    real_replace = os.replace

    def _spy(src: Any, dst: Any) -> None:
        replace_calls.append((str(src), str(dst)))
        real_replace(src, dst)

    monkeypatch.setattr("os.replace", _spy)
    _merge_non_secret_settings(path, {"model_name": "openai:gpt-4o"})

    assert replace_calls and replace_calls[0][1] == str(path)
    assert json.loads(path.read_text()) == {"model_name": "openai:gpt-4o"}
    # The temp file was renamed into place, never left behind.
    assert sorted(tmp_path.iterdir()) == [path]


def test_merge_failure_leaves_existing_file_intact(tmp_path: Path, monkeypatch: Any) -> None:
    """If the final rename fails, the previous settings.json is untouched and the
    temp file is cleaned up — a failed save can no longer truncate the config."""
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"log_level": "DEBUG"}))

    def _boom(src: Any, dst: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("os.replace", _boom)
    with pytest.raises(OSError):
        _merge_non_secret_settings(path, {"model_name": "openai:gpt-4o"})

    assert json.loads(path.read_text()) == {"log_level": "DEBUG"}
    assert sorted(tmp_path.iterdir()) == [path]


def test_merge_enforces_0600_mode(tmp_path: Path) -> None:
    """The atomic rewrite forces 0600 (symmetric with .secrets) — it never
    preserves looser bits from the file it replaces, and a fresh file is born
    0600 too. settings.json carries the user's SEC identity and custom provider
    endpoints; other local users have no business reading it."""
    path = tmp_path / "settings.json"
    path.write_text("{}")
    os.chmod(path, 0o644)  # drifted-loose existing file

    _merge_non_secret_settings(path, {"model_name": "openai:gpt-4o"})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    fresh = tmp_path / "fresh-settings.json"
    _merge_non_secret_settings(fresh, {"model_name": "openai:gpt-4o"})
    assert stat.S_IMODE(fresh.stat().st_mode) == 0o600


def test_load_tightens_drifted_mode_on_boot_read(tmp_path: Path) -> None:
    """The boot read self-heals a loose settings.json immediately (mirroring
    FileSecretStore) instead of waiting for the next save."""
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"model_name": "openai:gpt-4o"}))
    os.chmod(path, 0o644)

    overrides, error = load_non_secret_settings_with_error(path)

    assert error is None
    assert overrides == {"model_name": "openai:gpt-4o"}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


# ---------------------------------------------------------------------------
# settings.json torn-write resilience — tolerant read side
# (the boot path get_settings(**load_non_secret_settings(...)) must never raise)
# ---------------------------------------------------------------------------


def test_load_with_error_tolerates_truncated_json(tmp_path: Path) -> None:
    """A half-written file degrades to ({}, error) instead of raising."""
    path = tmp_path / "settings.json"
    path.write_text('{"model_name": "openai:gp')  # torn write

    overrides, error = load_non_secret_settings_with_error(path)

    assert overrides == {}
    assert error is not None and "settings.json" in error
    # The exact boot-path expression must survive a corrupt file (the old crash):
    settings = get_settings(**load_non_secret_settings(path))
    assert settings.model_name == get_settings().model_name


def test_load_with_error_tolerates_non_dict_json(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("[1, 2, 3]")

    overrides, error = load_non_secret_settings_with_error(path)

    assert overrides == {}
    assert error is not None and "settings.json" in error


def test_load_with_error_missing_file_reports_no_error(tmp_path: Path) -> None:
    overrides, error = load_non_secret_settings_with_error(tmp_path / "settings.json")
    assert overrides == {}
    assert error is None


def test_load_with_error_valid_file_reports_no_error(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"model_name": "openai:gpt-4o", "fmp_api_key": "leak"}))

    overrides, error = load_non_secret_settings_with_error(path)

    assert overrides == {"model_name": "openai:gpt-4o"}  # secret fields filtered
    assert error is None


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
    assert set(providers) == {"anthropic", "openai"}
    assert providers["openai"]["is_builtin"] is True
    # openai is the active model and its key is injected → key_set True.
    assert providers["openai"]["key_set"] is True
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

    # Switching to anthropic with no anthropic key is saved (200) and surfaced as
    # a non-blocking startup_error banner — it does NOT 400 (saving must never be
    # blocked by an incomplete LLM config).
    assert resp.status_code == 200, resp.text

    content = json.loads((tmp_path / "settings.json").read_text())
    # Only model_name should ever be persisted in this scenario.
    assert set(content.keys()) == {"model_name"}


@pytest.mark.asyncio
async def test_put_data_key_succeeds_without_llm_key(tmp_path: Path, monkeypatch: Any) -> None:
    """Regression: saving a data-source key must NOT 400 just because the active
    LLM model has no API key yet (chicken-and-egg that blocked every save)."""
    # openai model, NO provider key configured → validate_runtime_config fails.
    settings = get_settings(model_name="openai:gpt-4o", provider_keys={})
    secret_store = AsyncMock()
    secret_store.has = AsyncMock(return_value=False)
    secret_store.get = AsyncMock(return_value=None)
    secret_store.set = AsyncMock()
    secret_store.delete = AsyncMock()
    app = _make_app(tmp_path, settings=settings, secret_store=secret_store)
    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", AsyncMock())

    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"fmp_api_key": "fmp-key-123"})

    assert resp.status_code == 200, resp.text
    # The FMP key was stored despite the incomplete LLM config...
    secret_store.set.assert_any_await("fmp_api_key", "fmp-key-123")
    # ...and a MISSING LLM key is NOT a red banner — it's onboarding (the friendly
    # "add a key" notice + a 503 on AI routes via is_model_configured). The
    # startup_error stays None so picking a provider mid-setup never alarms.
    assert app.state.startup_error is None


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
async def test_put_strips_custom_provider_id_before_persisting(
    tmp_path: Path, monkeypatch: Any
) -> None:
    app = _make_app(tmp_path)

    async def _fake_replace(request: Any, candidate: Any) -> None:
        request.app.state.deps.settings = candidate

    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", _fake_replace)

    custom = [
        {
            "id": " myhost ",
            "label": "My vLLM",
            "kind": "openai-compatible",
            "base_url": "https://h/v1",
            "models": ["local-7b"],
        }
    ]
    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"custom_providers": custom})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["custom_providers"][0]["id"] == "myhost"
    content = json.loads((tmp_path / "settings.json").read_text())
    assert content["custom_providers"][0]["id"] == "myhost"


@pytest.mark.asyncio
async def test_put_lowercases_custom_provider_id_before_persisting(
    tmp_path: Path, monkeypatch: Any
) -> None:
    app = _make_app(tmp_path)

    async def _fake_replace(request: Any, candidate: Any) -> None:
        request.app.state.deps.settings = candidate

    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", _fake_replace)

    custom = [
        {
            "id": "MyHost",
            "label": "My vLLM",
            "kind": "openai-compatible",
            "base_url": "https://h/v1",
            "models": ["local-7b"],
        }
    ]
    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"custom_providers": custom})

    assert resp.status_code == 200, resp.text
    assert resp.json()["custom_providers"][0]["id"] == "myhost"
    content = json.loads((tmp_path / "settings.json").read_text())
    assert content["custom_providers"][0]["id"] == "myhost"


@pytest.mark.asyncio
async def test_put_normalizes_model_name_provider_prefix_with_custom_provider(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A single PUT that adds ``OpenRouter`` and selects ``OpenRouter:model``
    must persist a coherent lower-case provider id everywhere.

    Regression: custom_providers[].id was normalized to ``openrouter`` while
    model_name stayed ``OpenRouter:...``, leaving the saved config unable to
    find its own provider.
    """
    secret_store = AsyncMock()
    secret_store.has = AsyncMock(return_value=False)
    secret_store.get = AsyncMock(return_value=None)
    secret_store.set = AsyncMock()
    secret_store.delete = AsyncMock()
    app = _make_app(tmp_path, settings=get_settings(model_name=""), secret_store=secret_store)

    async def _fake_replace(request: Any, candidate: Any) -> None:
        request.app.state.deps.settings = candidate

    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", _fake_replace)

    custom = [
        {
            "id": "OpenRouter",
            "label": "OpenRouter",
            "kind": "openai-compatible",
            "base_url": "https://openrouter.ai/api/v1",
            "models": ["openai/gpt-4o-mini"],
        }
    ]
    async with _client(app) as c:
        resp = await c.put(
            "/api/settings",
            json={
                "custom_providers": custom,
                "model_name": "OpenRouter:openai/gpt-4o-mini",
                "provider_keys": {"OpenRouter": "sk-test"},
            },
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["model_name"] == "openrouter:openai/gpt-4o-mini"
    assert body["custom_providers"][0]["id"] == "openrouter"
    assert body["model_configured"] is True
    assert body["startup_error"] is None
    secret_store.set.assert_awaited_with("provider_key:openrouter", "sk-test")
    content = json.loads((tmp_path / "settings.json").read_text())
    assert content["model_name"] == "openrouter:openai/gpt-4o-mini"


@pytest.mark.asyncio
async def test_put_strips_custom_provider_label_before_persisting(
    tmp_path: Path, monkeypatch: Any
) -> None:
    app = _make_app(tmp_path)

    async def _fake_replace(request: Any, candidate: Any) -> None:
        request.app.state.deps.settings = candidate

    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", _fake_replace)

    custom = [
        {
            "id": "myhost",
            "label": " My vLLM ",
            "kind": "openai-compatible",
            "base_url": "https://h/v1",
            "models": ["local-7b"],
        }
    ]
    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"custom_providers": custom})

    assert resp.status_code == 200, resp.text
    assert resp.json()["custom_providers"][0]["label"] == "My vLLM"
    content = json.loads((tmp_path / "settings.json").read_text())
    assert content["custom_providers"][0]["label"] == "My vLLM"


@pytest.mark.asyncio
async def test_put_rejects_blank_custom_provider_label(tmp_path: Path, monkeypatch: Any) -> None:
    app = _make_app(tmp_path)
    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", AsyncMock())
    bad = [
        {
            "id": "myhost",
            "label": "   ",
            "kind": "openai-compatible",
            "base_url": "https://h/v1",
        }
    ]
    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"custom_providers": bad})

    assert resp.status_code == 400
    assert "label" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_put_rejects_custom_provider_shadowing_builtin(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A custom provider id may not collide with a built-in (openai)."""
    app = _make_app(tmp_path)
    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", AsyncMock())
    bad = [{"id": "openai", "label": "x", "kind": "openai-compatible", "base_url": "https://h/v1"}]
    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"custom_providers": bad})
    assert resp.status_code == 400
    assert "built-in" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_put_rejects_custom_provider_shadowing_builtin_case_insensitive(
    tmp_path: Path, monkeypatch: Any
) -> None:
    app = _make_app(tmp_path)
    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", AsyncMock())
    bad = [{"id": "OpenAI", "label": "x", "kind": "openai-compatible", "base_url": "https://h/v1"}]
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
        resp = await c.put("/api/settings", json={"provider_keys": {"anthropic": "sk-new"}})
    assert resp.status_code == 200, resp.text
    secret_store.set.assert_awaited_with("provider_key:anthropic", "sk-new")
    secret_store.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_put_writes_provider_key_under_normalized_id(
    tmp_path: Path, monkeypatch: Any
) -> None:
    secret_store = AsyncMock()
    secret_store.has = AsyncMock(return_value=False)
    secret_store.get = AsyncMock(return_value=None)
    secret_store.set = AsyncMock()
    secret_store.delete = AsyncMock()
    app = _make_app(tmp_path, secret_store=secret_store)
    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", AsyncMock())

    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"provider_keys": {" Anthropic ": "sk-new"}})

    assert resp.status_code == 200, resp.text
    secret_store.set.assert_awaited_with("provider_key:anthropic", "sk-new")
    secret_store.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_put_rejects_unknown_provider_key(tmp_path: Path, monkeypatch: Any) -> None:
    secret_store = AsyncMock()
    secret_store.has = AsyncMock(return_value=False)
    secret_store.get = AsyncMock(return_value=None)
    secret_store.set = AsyncMock()
    secret_store.delete = AsyncMock()
    app = _make_app(tmp_path, secret_store=secret_store)
    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", AsyncMock())

    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"provider_keys": {"ghost": "sk-ghost"}})

    assert resp.status_code == 400
    assert "ghost" in resp.json()["detail"]
    secret_store.set.assert_not_awaited()


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
    settings = get_settings(model_name="openai:gpt-4o", **raw)
    assert settings.sec_identity_dismissed_at is not None
    assert settings.sec_identity_dismissed_at.year == 2026
    assert settings.sec_identity_dismissed_at.month == 5
    assert settings.sec_identity_dismissed_at.day == 27


def test_load_non_secret_settings_keeps_peer_sticky_window(tmp_path: Path) -> None:
    from finrobot.routes.settings import load_non_secret_settings

    (tmp_path / "settings.json").write_text(json.dumps({"peer_sticky_max_age_days": 3}))
    raw = load_non_secret_settings(tmp_path / "settings.json")
    settings = get_settings(model_name="openai:gpt-4o", **raw)
    assert settings.peer_sticky_max_age_days == 3


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
async def test_settings_update_rejects_negative_log_retention_days(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"log_retention_days": -1})
    assert resp.status_code == 422


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


@pytest.mark.asyncio
async def test_settings_update_normalizes_log_level(tmp_path: Path, monkeypatch: Any) -> None:
    app = _make_app(tmp_path)

    async def _fake_replace(request: Any, candidate: Any) -> None:
        request.app.state.deps.settings = candidate

    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", _fake_replace)
    calls: list[Any] = []
    monkeypatch.setattr(
        "finrobot.obs.setup_logging",
        lambda candidate, *, force=False: calls.append((candidate.log_level, force)),
    )

    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"log_level": " debug "})

    assert resp.status_code == 200, resp.text
    assert resp.json()["log_level"] == "DEBUG"
    assert calls == [("DEBUG", True)]
    content = json.loads((tmp_path / "settings.json").read_text())
    assert content["log_level"] == "DEBUG"


@pytest.mark.asyncio
async def test_settings_update_rejects_unknown_log_level(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"log_level": "TRACE"})
    assert resp.status_code == 422


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
        resp = await c.put("/api/settings", json={"provider_keys": {"anthropic": ""}})
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
        resp = await c.put("/api/settings", json={"provider_keys": {"anthropic": "new-key"}})
    assert resp.status_code == 200, resp.text
    secret_store.set.assert_awaited_with("provider_key:anthropic", "new-key")
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
        resp = await c.post("/api/settings/clear-secret", json={"field": "provider_key:anthropic"})
    assert resp.status_code == 200, resp.text
    secret_store.delete.assert_awaited_with("provider_key:anthropic")


@pytest.mark.asyncio
async def test_replace_runtime_settings_skips_agents_when_config_invalid(
    monkeypatch: Any,
) -> None:
    """Regression: clearing the active provider's last key leaves the runtime
    config invalid, and the LLM provider constructor raises on a missing key —
    so rebuilding the lead agent must be SKIPPED, not attempted. Before the fix
    ``_replace_runtime_settings`` called create_lead_agent unconditionally and
    500'd the clear-secret request. Mirror the boot path: no agents while invalid,
    agent=None for the 503 guard, and don't raise.
    """
    from finrobot.routes.settings import _replace_runtime_settings

    called = {"lead": 0, "sub": 0}
    monkeypatch.setattr(
        "finrobot.engine.orchestrator.create_lead_agent",
        lambda *a, **k: called.__setitem__("lead", called["lead"] + 1),
    )
    monkeypatch.setattr(
        "finrobot.engine.agents.factory.create_sub_agents",
        lambda *a, **k: called.__setitem__("sub", called["sub"] + 1),
    )
    monkeypatch.setattr("finrobot.routes.settings.build_data_layer", lambda _s: MagicMock())

    # anthropic model with NO provider key → validate_runtime_config raises.
    settings = get_settings(model_name="anthropic:claude-sonnet-4-6", provider_keys={})
    request = MagicMock()
    request.app.state.deps.data_layer.close = AsyncMock()
    request.app.state.deps.skill_runtime = None

    await _replace_runtime_settings(request, settings)  # must NOT raise

    assert called == {"lead": 0, "sub": 0}, "agents must not be built on invalid config"
    assert request.app.state.agent is None
    assert request.app.state.sub_agents == {}


@pytest.mark.asyncio
async def test_replace_runtime_settings_shares_sub_agents_with_lead_agent(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Runtime settings hot reload mirrors boot: create sub-agents once, store
    that mapping, and pass the same object into the lead agent."""
    import asyncio as _asyncio

    from finrobot.routes import settings as settings_mod

    app = _make_app(tmp_path)
    old_layer = app.state.deps.data_layer
    new_layer = MagicMock()
    new_layer.close = AsyncMock()
    shared_sub_agents = {"market": MagicMock()}
    lead_agent = MagicMock()
    create_sub_agents = MagicMock(return_value=shared_sub_agents)
    create_lead_agent = MagicMock(return_value=lead_agent)

    monkeypatch.setattr(settings_mod, "build_data_layer", lambda _s: new_layer)
    monkeypatch.setattr(settings_mod, "_RETIRED_LAYER_GRACE_S", 0)
    monkeypatch.setattr("finrobot.engine.agents.factory.create_sub_agents", create_sub_agents)
    monkeypatch.setattr("finrobot.engine.orchestrator.create_lead_agent", create_lead_agent)

    request = MagicMock()
    request.app = app

    await settings_mod._replace_runtime_settings(request, app.state.deps.settings)

    create_sub_agents.assert_called_once_with(
        app.state.deps.settings, skill_registry=app.state.deps.skill_runtime
    )
    create_lead_agent.assert_called_once_with(
        app.state.deps.settings,
        skill_registry=app.state.deps.skill_runtime,
        sub_agents=shared_sub_agents,
    )
    assert app.state.deps.data_layer is new_layer
    assert app.state.sub_agents is shared_sub_agents
    assert app.state.agent is lead_agent

    await _asyncio.sleep(0.01)
    old_layer.close.assert_awaited_once()


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


# ---------------------------------------------------------------------------
# Keychain refusal at runtime — reads degrade (GET stays 200), writes surface
# a user-visible error (a failed key save must never look like success).
# ---------------------------------------------------------------------------


def _denied_keychain_store() -> Any:
    """A real KeychainSecretStore whose backend refuses every call (user hit
    "Deny" on the OS prompt), built without touching the actual OS keychain."""
    import keyring.errors

    from finrobot.secret_store import KeychainSecretStore

    class _RefusingKeyring:
        errors = keyring.errors

        def get_password(self, service: str, key: str) -> str | None:
            raise keyring.errors.KeyringLocked("user denied access")

        def set_password(self, service: str, key: str, value: str) -> None:
            raise keyring.errors.KeyringLocked("user denied access")

        def delete_password(self, service: str, key: str) -> None:
            raise keyring.errors.KeyringLocked("user denied access")

    store = KeychainSecretStore.__new__(KeychainSecretStore)
    store._keyring = _RefusingKeyring()  # type: ignore[assignment]
    store._service_name = "FinRobotTest"
    store._degraded_keys = set()
    return store


@pytest.mark.asyncio
async def test_get_settings_stays_200_when_keychain_denied(tmp_path: Path) -> None:
    """secret_store.has() refusal degrades to key_set=False instead of a 500."""
    app = _make_app(tmp_path, secret_store=_denied_keychain_store())
    async with _client(app) as c:
        resp = await c.get("/api/settings")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fmp_api_key_set"] is False
    # The active model's key is injected in runtime settings, so key_set stays
    # True via the settings fallback even though the keychain read degraded.
    providers = {p["id"]: p for p in body["providers"]}
    assert providers["openai"]["key_set"] is True


@pytest.mark.asyncio
async def test_put_keychain_set_failure_is_user_visible(tmp_path: Path, monkeypatch: Any) -> None:
    """A denied keychain write fails the PUT with the real reason — the key was
    NOT saved and the response must say so (no fake success, no opaque 500)."""
    app = _make_app(tmp_path, secret_store=_denied_keychain_store())
    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", AsyncMock())

    async with _client(app) as c:
        resp = await c.put("/api/settings", json={"fmp_api_key": "fmp-key-123"})

    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert "fmp_api_key" in detail and "keychain" in detail
    assert "fmp-key-123" not in detail  # the secret value never leaks


@pytest.mark.asyncio
async def test_clear_secret_keychain_failure_is_user_visible(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A keychain that refuses the delete must fail the clear loudly — the
    secret is still stored, so pretending success would lie to the user."""
    from finrobot.secret_store import SecretStoreError

    secret_store = AsyncMock()
    secret_store.has = AsyncMock(return_value=False)
    secret_store.get = AsyncMock(return_value=None)
    secret_store.delete = AsyncMock(
        side_effect=SecretStoreError("Failed to delete secret 'fmp_api_key' from the OS keychain")
    )
    app = _make_app(tmp_path, secret_store=secret_store)
    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", AsyncMock())

    async with _client(app) as c:
        resp = await c.post("/api/settings/clear-secret", json={"field": "fmp_api_key"})

    assert resp.status_code == 500
    assert "fmp_api_key" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/settings/test-provider — live connectivity check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_provider_unknown_is_404(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    async with _client(app) as c:
        resp = await c.post("/api/settings/test-provider", json={"provider_id": "nope"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_test_provider_no_key_returns_not_ok(tmp_path: Path) -> None:
    settings = get_settings(model_name="openai:gpt-4o", provider_keys={})
    app = _make_app(tmp_path, settings=settings)
    async with _client(app) as c:
        resp = await c.post(
            "/api/settings/test-provider", json={"provider_id": "openai", "model_id": "gpt-4o"}
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert body["code"] == "no_key"


@pytest.mark.asyncio
async def test_test_provider_blank_model_returns_no_model_without_first_suggestion(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """An empty model field must not silently probe the provider's first suggestion
    (OpenAI used to fall through to gpt-4o, which looked like an unwanted default)."""
    probe = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr("pydantic_ai.direct.model_request", probe)
    app = _make_app(tmp_path)  # openai keyed by default
    async with _client(app) as c:
        resp = await c.post(
            "/api/settings/test-provider", json={"provider_id": "openai", "model_id": ""}
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert body["code"] == "no_model"
    probe.assert_not_awaited()


@pytest.mark.asyncio
async def test_test_provider_success(tmp_path: Path, monkeypatch: Any) -> None:
    """A successful tiny model call returns ok=True (model_request mocked)."""
    monkeypatch.setattr("pydantic_ai.direct.model_request", AsyncMock(return_value=MagicMock()))
    app = _make_app(tmp_path)  # openai keyed by default
    async with _client(app) as c:
        resp = await c.post(
            "/api/settings/test-provider", json={"provider_id": "openai", "model_id": "gpt-4o"}
        )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "code": "ok", "detail": ""}


@pytest.mark.asyncio
async def test_test_provider_maps_auth_error(tmp_path: Path, monkeypatch: Any) -> None:
    """A 401 from the provider is classified as code 'auth'."""
    from pydantic_ai.exceptions import ModelHTTPError

    monkeypatch.setattr(
        "pydantic_ai.direct.model_request",
        AsyncMock(
            side_effect=ModelHTTPError(status_code=401, model_name="openai:gpt-4o", body="x")
        ),
    )
    app = _make_app(tmp_path)
    async with _client(app) as c:
        resp = await c.post(
            "/api/settings/test-provider", json={"provider_id": "openai", "model_id": "gpt-4o"}
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert body["code"] == "auth"


# ---------------------------------------------------------------------------
# POST /api/settings/test-data-provider — data-source key connectivity check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_data_provider_unknown_is_404(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    async with _client(app) as c:
        resp = await c.post("/api/settings/test-data-provider", json={"provider": "nope"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_test_data_provider_no_key_returns_not_ok(tmp_path: Path) -> None:
    """No FMP key stored → no_key, without ever calling the probe."""
    app = _make_app(tmp_path, settings=_settings(fmp_api_key=""))
    async with _client(app) as c:
        resp = await c.post("/api/settings/test-data-provider", json={"provider": "fmp"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert body["code"] == "no_key"


@pytest.mark.asyncio
async def test_test_data_provider_success(tmp_path: Path, monkeypatch: Any) -> None:
    """A successful probe (mocked) returns ok=True."""
    monkeypatch.setitem(_DATA_PROBES, "fmp", ("fmp_api_key", AsyncMock(return_value=None)))
    app = _make_app(tmp_path, settings=_settings(fmp_api_key="fmp-key-123"))
    async with _client(app) as c:
        resp = await c.post("/api/settings/test-data-provider", json={"provider": "fmp"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "code": "ok", "detail": ""}


@pytest.mark.asyncio
async def test_test_data_provider_success_closes_live_health_breaker(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A manual successful test should immediately turn an open status dot healthy."""
    from finrobot.engine.data.provider_health import ProviderHealth

    monkeypatch.setitem(_DATA_PROBES, "fmp", ("fmp_api_key", AsyncMock(return_value=None)))
    app = _make_app(tmp_path, settings=_settings(fmp_api_key="fmp-key-123"))
    health = ProviderHealth()
    health.record_failure("fmp", rate_limited=True)
    app.state.deps.data_layer._health = health
    app.state.deps.data_layer.provider_status.return_value = [
        ("fmp", False, health.snapshot("fmp"))
    ]
    assert health.is_available("fmp") is False

    async with _client(app) as c:
        resp = await c.post("/api/settings/test-data-provider", json={"provider": "fmp"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    assert health.is_available("fmp") is True
    assert health.snapshot("fmp").last_success is not None


@pytest.mark.asyncio
async def test_test_data_provider_maps_auth_and_hides_key(tmp_path: Path, monkeypatch: Any) -> None:
    """A 401 is classified 'auth', and the live key never leaks into ``detail``.

    httpx bakes the request URL (``?apikey=<key>``) into HTTPStatusError.str();
    _classify_data_provider_error must synthesise detail from the status only.
    """
    import httpx

    secret = "super-secret-fmp-key"
    request = httpx.Request(
        "GET", f"https://financialmodelingprep.com/api/v3/profile/AAPL?apikey={secret}"
    )
    response = httpx.Response(401, request=request)
    monkeypatch.setitem(
        _DATA_PROBES,
        "fmp",
        (
            "fmp_api_key",
            AsyncMock(side_effect=httpx.HTTPStatusError("401", request=request, response=response)),
        ),
    )
    app = _make_app(tmp_path, settings=_settings(fmp_api_key=secret))
    async with _client(app) as c:
        resp = await c.post("/api/settings/test-data-provider", json={"provider": "fmp"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert body["code"] == "auth"
    assert body["detail"] == "HTTP 401"
    assert secret not in body["detail"]


@pytest.mark.asyncio
async def test_test_data_provider_maps_plan_restriction(tmp_path: Path, monkeypatch: Any) -> None:
    """FMP's 403 "Legacy Endpoint" body means the key is VALID but the account's
    plan can't use the endpoint (post-2025-08-31 accounts lost /api/v3) — that
    must classify as 'plan', not 'auth', or the user chases the wrong fix."""
    import httpx

    secret = "valid-but-new-account-key"
    request = httpx.Request(
        "GET", f"https://financialmodelingprep.com/api/v3/profile/AAPL?apikey={secret}"
    )
    response = httpx.Response(
        403,
        request=request,
        text='{"Error Message": "Legacy Endpoint : Due to Legacy endpoints being no longer supported..."}',
    )
    monkeypatch.setitem(
        _DATA_PROBES,
        "fmp",
        (
            "fmp_api_key",
            AsyncMock(side_effect=httpx.HTTPStatusError("403", request=request, response=response)),
        ),
    )
    app = _make_app(tmp_path, settings=_settings(fmp_api_key=secret))
    async with _client(app) as c:
        resp = await c.post("/api/settings/test-data-provider", json={"provider": "fmp"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert body["code"] == "plan"
    assert body["detail"] == "HTTP 403"
    assert secret not in body["detail"]


@pytest.mark.asyncio
async def test_test_data_provider_maps_bare_403_to_auth(tmp_path: Path, monkeypatch: Any) -> None:
    """A 403 without a plan-restriction marker body still reads as 'auth'."""
    import httpx

    request = httpx.Request("GET", "https://example.com/probe?apikey=k")
    response = httpx.Response(403, request=request, text="Forbidden")
    monkeypatch.setitem(
        _DATA_PROBES,
        "fmp",
        (
            "fmp_api_key",
            AsyncMock(side_effect=httpx.HTTPStatusError("403", request=request, response=response)),
        ),
    )
    app = _make_app(tmp_path, settings=_settings(fmp_api_key="k"))
    async with _client(app) as c:
        resp = await c.post("/api/settings/test-data-provider", json={"provider": "fmp"})
    assert resp.json()["code"] == "auth"


@pytest.mark.asyncio
async def test_test_data_provider_maps_rate_limit(tmp_path: Path, monkeypatch: Any) -> None:
    """A 429 (e.g. FMP "Bandwidth Limit Reach") classifies as 'rate_limited'."""
    import httpx

    request = httpx.Request("GET", "https://example.com/probe?apikey=k")
    response = httpx.Response(429, request=request)
    monkeypatch.setitem(
        _DATA_PROBES,
        "fmp",
        (
            "fmp_api_key",
            AsyncMock(side_effect=httpx.HTTPStatusError("429", request=request, response=response)),
        ),
    )
    app = _make_app(tmp_path, settings=_settings(fmp_api_key="k"))
    async with _client(app) as c:
        resp = await c.post("/api/settings/test-data-provider", json={"provider": "fmp"})
    body = resp.json()
    assert body["ok"] is False
    assert body["code"] == "rate_limited"
    assert body["detail"] == "HTTP 429"


@pytest.mark.asyncio
async def test_test_data_provider_maps_connect_error(tmp_path: Path, monkeypatch: Any) -> None:
    import httpx

    monkeypatch.setitem(
        _DATA_PROBES,
        "finnhub",
        ("finnhub_api_key", AsyncMock(side_effect=httpx.ConnectError("no route"))),
    )
    app = _make_app(tmp_path, settings=_settings(finnhub_api_key="fh-key"))
    async with _client(app) as c:
        resp = await c.post("/api/settings/test-data-provider", json={"provider": "finnhub"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert body["code"] == "connect"


# ---------------------------------------------------------------------------
# Concurrency: lost updates + retired data-layer close (P2 audit 2026-06-10)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_puts_do_not_lose_updates(tmp_path: Path, monkeypatch: Any) -> None:
    """Two overlapping PUTs touching DIFFERENT fields must both land.

    The route body is a read-modify-write over deps.settings (plus keychain +
    settings.json): without the mutation lock, both requests read the same
    ``current``, and whichever commits last erases the other's field from the
    runtime settings. The slow secret_store.get forces the interleave window.
    """
    import asyncio as _asyncio

    settings = _settings(sec_user_agent="OldCo old@example.com")
    secret_store = AsyncMock()
    secret_store.has = AsyncMock(return_value=False)
    secret_store.set = AsyncMock()
    secret_store.delete = AsyncMock()

    async def slow_get(_key: str) -> None:
        await _asyncio.sleep(0.02)  # widen the read→write window
        return None

    secret_store.get = AsyncMock(side_effect=slow_get)
    app = _make_app(tmp_path, settings=settings, secret_store=secret_store)

    async def fake_replace(request: Any, new_settings: Any) -> None:
        await _asyncio.sleep(0)  # yield so the other request can interleave
        request.app.state.deps.settings = new_settings

    monkeypatch.setattr("finrobot.routes.settings._replace_runtime_settings", fake_replace)

    async with _client(app) as c:
        r1, r2 = await _asyncio.gather(
            c.put("/api/settings", json={"model_name": "openai:gpt-4o-mini"}),
            c.put("/api/settings", json={"sec_user_agent": "NewCo new@example.com"}),
        )

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    final = app.state.deps.settings
    assert final.model_name == "openai:gpt-4o-mini"
    assert final.sec_user_agent == "NewCo new@example.com"
    # And settings.json carries both (the file merge is also serialised).
    content = json.loads((tmp_path / "settings.json").read_text())
    assert content["model_name"] == "openai:gpt-4o-mini"
    assert content["sec_user_agent"] == "NewCo new@example.com"


@pytest.mark.asyncio
async def test_replace_runtime_settings_defers_old_layer_close(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """The replaced DataLayer must NOT be closed inline — an in-flight run's
    fetch awaiting on it would have its connection pool yanked mid-await. It is
    closed after the grace window instead."""
    import asyncio as _asyncio

    from finrobot.routes import settings as settings_mod

    # No LLM key → validate_runtime_config fails → agent construction skipped
    # (keeps the test offline); the layer-swap path is what we're pinning.
    app = _make_app(tmp_path, settings=get_settings(model_name="openai:gpt-4o", provider_keys={}))
    old_layer = app.state.deps.data_layer
    new_layer = MagicMock()
    new_layer.close = AsyncMock()
    monkeypatch.setattr(settings_mod, "build_data_layer", lambda _s: new_layer)
    monkeypatch.setattr(settings_mod, "_RETIRED_LAYER_GRACE_S", 0.05)

    request = MagicMock()
    request.app = app
    await settings_mod._replace_runtime_settings(request, app.state.deps.settings)

    assert app.state.deps.data_layer is new_layer
    old_layer.close.assert_not_awaited()  # NOT closed inline

    await _asyncio.sleep(0.2)  # let the grace window elapse
    old_layer.close.assert_awaited_once()


class TestClassifyProviderError:
    """The /test-provider verdict codes that drive the AI Model panel's ✗ + the
    auto-test-on-save feedback. A failed live probe must map to an ACTIONABLE
    code (auth / not_found / connect) so "the key is wrong" reads clearly at
    config time instead of a buried 500 mid-run."""

    def test_http_401_403_is_auth(self) -> None:
        from pydantic_ai.exceptions import ModelHTTPError

        from finrobot.llm_probe import classify_provider_error as _classify_provider_error

        for status in (401, 403):
            code, _ = _classify_provider_error(
                ModelHTTPError(status_code=status, model_name="m", body=None)
            )
            assert code == "auth"

    def test_http_404_is_not_found(self) -> None:
        from pydantic_ai.exceptions import ModelHTTPError

        from finrobot.llm_probe import classify_provider_error as _classify_provider_error

        code, _ = _classify_provider_error(
            ModelHTTPError(status_code=404, model_name="m", body=None)
        )
        assert code == "not_found"

    def test_other_http_is_http(self) -> None:
        from pydantic_ai.exceptions import ModelHTTPError

        from finrobot.llm_probe import classify_provider_error as _classify_provider_error

        code, _ = _classify_provider_error(
            ModelHTTPError(status_code=500, model_name="m", body=None)
        )
        assert code == "http"

    def test_connect_error_is_connect(self) -> None:
        import httpx

        from finrobot.llm_probe import classify_provider_error as _classify_provider_error

        code, _ = _classify_provider_error(httpx.ConnectError("refused"))
        assert code == "connect"

    def test_api_key_text_falls_back_to_auth(self) -> None:
        from finrobot.llm_probe import classify_provider_error as _classify_provider_error

        code, _ = _classify_provider_error(ValueError("Invalid api_key provided"))
        assert code == "auth"

    def test_unrecognised_is_unknown(self) -> None:
        from finrobot.llm_probe import classify_provider_error as _classify_provider_error

        code, detail = _classify_provider_error(RuntimeError("weird"))
        assert code == "unknown"
        assert "weird" in detail
