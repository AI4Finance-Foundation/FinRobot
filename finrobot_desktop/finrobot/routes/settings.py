from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.requests import Request

from finrobot.config import (
    BUILTIN_PROVIDERS,
    DATA_PROVIDER_SECRET_FIELDS,
    FinRobotSettings,
    ProviderConfig,
)
from finrobot.secret_store import SecretStorageMode
from finrobot.data_layer_factory import build_data_layer
from finrobot.engine.agents.factory import create_sub_agents
from finrobot.engine.orchestrator import create_lead_agent

router = APIRouter(prefix="/api/settings", tags=["settings"])

# DataProvider secrets (FMP / Finnhub / …) stored in the OS keychain (or
# FileSecretStore fallback) under their own field name. LLM provider API keys
# use the dynamic ``provider_key:<id>`` scheme instead — see _PROVIDER_KEY_PREFIX.
_DATA_SECRET_FIELDS: tuple[str, ...] = DATA_PROVIDER_SECRET_FIELDS

# Keychain key prefix for an LLM provider's API key: ``provider_key:<provider_id>``.
_PROVIDER_KEY_PREFIX = "provider_key:"

# Built-in provider ids cannot be deleted or shadowed by a custom provider.
_BUILTIN_PROVIDER_IDS: frozenset[str] = frozenset(p.id for p in BUILTIN_PROVIDERS)


def _provider_key_name(provider_id: str) -> str:
    return f"{_PROVIDER_KEY_PREFIX}{provider_id}"


# Non-secret fields are written into ``~/.finrobot/settings.json`` only when
# the user explicitly changes them. A field the user never touched stays out
# of settings.json so it keeps resolving to the built-in default — we only
# persist what the user actually set in the app.
_NON_SECRET_FIELDS: tuple[str, ...] = (
    "model_name",
    "custom_providers",  # user-added LLM providers (registry); keys live in keychain
    "sec_user_agent",
    "sec_identity_dismissed_at",  # 2026-05 EdgarTools — landing banner dismiss state
    "sec_holdings_auto_refresh",
    "log_level",
    "log_to_file",
    "log_retention_days",
)


class ProviderInfo(BaseModel):
    """One provider as seen by the Settings UI: the registry config plus whether
    its API key is stored and whether it's a built-in (non-deletable) provider."""

    id: str
    label: str
    kind: str
    base_url: str | None
    models: list[str]
    key_set: bool
    is_builtin: bool


class SettingsResponse(BaseModel):
    model_name: str
    # The effective LLM provider registry (built-ins + user customs), each with
    # key_set / is_builtin so the UI can render provider cards, gate the API-key
    # field, and disable delete on built-ins. Replaces the old hardcoded
    # ``valid_model_providers`` literal.
    providers: list[ProviderInfo]
    # The user's own custom providers (subset of ``providers``), echoed back so
    # the edit form can round-trip them.
    custom_providers: list[ProviderConfig]
    fmp_api_key_set: bool
    finnhub_api_key_set: bool
    alpha_vantage_api_key_set: bool
    adanos_api_key_set: bool
    sec_user_agent: str
    # Authoritative answer to "did the backend accept this identity?" — the
    # SAME gate (``_is_valid_identity``) that decides whether build_data_layer
    # registers the EdgarToolsProvider. The landing banner reads THIS boolean
    # instead of re-deriving validity from the raw string client-side, so the
    # UI can never disagree with what the backend actually did.
    sec_identity_active: bool
    # 2026-05 EdgarTools: ISO timestamp when user dismissed the "解锁 SEC 数据"
    # landing banner; null = never dismissed (banner still shows on landing).
    sec_identity_dismissed_at: datetime | None = None
    sec_holdings_auto_refresh: bool
    log_level: str
    log_to_file: bool
    log_retention_days: int
    available_providers: list[str]
    # If validate_runtime_config() failed at server boot, the error message
    # is surfaced here so the UI can show a banner. None = config is valid.
    startup_error: str | None = None
    # Indicates whether secrets are protected by the OS keychain or written to
    # a permission-locked plaintext JSON file.  "plaintext" means the user
    # should be warned that their API keys are stored unencrypted on disk.
    secret_storage_mode: SecretStorageMode = "keychain"


class SettingsUpdate(BaseModel):
    model_name: str | None = None
    # Full replacement of the user's custom provider list (the UI sends the whole
    # list on every add/edit/delete — no separate CRUD endpoints).
    custom_providers: list[ProviderConfig] | None = None
    sec_user_agent: str | None = None
    sec_identity_dismissed_at: datetime | None = None
    sec_holdings_auto_refresh: bool | None = None
    log_level: str | None = None
    log_to_file: bool | None = None
    log_retention_days: int | None = None

    # LLM provider API keys keyed by provider id ({"deepseek": "sk-…"}). Written
    # to the keychain under provider_key:<id>. A blank value is "no change", not
    # "delete" (BUG-005) — clearing is the explicit clear-secret endpoint.
    provider_keys: dict[str, str] | None = Field(default=None, repr=False)
    fmp_api_key: str | None = Field(default=None, repr=False)
    finnhub_api_key: str | None = Field(default=None, repr=False)
    alpha_vantage_api_key: str | None = Field(default=None, repr=False)
    adanos_api_key: str | None = Field(default=None, repr=False)


class ClearSecretRequest(BaseModel):
    """A single secret field to delete from the keychain.

    ``clear-secret`` is the explicit "wipe this stored API key" action. It is
    its own endpoint so deleting a secret can NEVER happen as a side effect of
    an empty value in a PUT (BUG-005) — the destructive path needs deliberate
    intent.
    """

    field: str


def _validate_custom_providers(providers: list[ProviderConfig]) -> None:
    """Reject custom providers that would corrupt the registry.

    A custom provider must have a non-empty id that does not shadow a built-in
    or duplicate another custom one, and an ``openai-compatible`` provider needs
    a base_url (there is no canonical endpoint to fall back to). Raises HTTP 400.
    """
    seen: set[str] = set()
    for provider in providers:
        pid = provider.id.strip()
        if not pid:
            raise HTTPException(status_code=400, detail="Provider id must not be empty.")
        if pid in _BUILTIN_PROVIDER_IDS:
            raise HTTPException(
                status_code=400,
                detail=f"Provider id '{pid}' is built-in and cannot be redefined.",
            )
        if pid in seen:
            raise HTTPException(status_code=400, detail=f"Duplicate provider id '{pid}'.")
        seen.add(pid)
        if provider.kind == "openai-compatible" and not (provider.base_url or "").strip():
            raise HTTPException(
                status_code=400,
                detail=f"Provider '{pid}' (openai-compatible) requires a base_url.",
            )


@router.get("", response_model=SettingsResponse)
async def get_settings_route(request: Request) -> SettingsResponse:
    return await _build_response(request)


@router.put("", response_model=SettingsResponse)
async def put_settings_route(update: SettingsUpdate, request: Request) -> SettingsResponse:
    secret_store = request.app.state.secret_store
    current: FinRobotSettings = request.app.state.deps.settings
    payload = update.model_dump(exclude_unset=True)

    non_secret_updates = {k: v for k, v in payload.items() if k in _NON_SECRET_FIELDS}
    data_secret_updates = {k: v for k, v in payload.items() if k in _DATA_SECRET_FIELDS}
    provider_key_updates = update.provider_keys or {}

    # Reject malformed / colliding custom providers before they reach the registry.
    if update.custom_providers is not None:
        _validate_custom_providers(update.custom_providers)

    # DataProvider secret merge: a falsy incoming value (absent OR empty string)
    # means "no change" — fall back to the stored keychain value, then the current
    # effective value. An empty password field must NEVER null out the merge
    # candidate, or validate_runtime_config below would 400 a user who only edited
    # an unrelated field, and a write of "" would wipe the stored key (BUG-005).
    data_secret_merge: dict[str, str] = {}
    for key in _DATA_SECRET_FIELDS:
        value = data_secret_updates.get(key)
        if not value:
            value = await secret_store.get(key)
            if value is None:
                value = getattr(current, key, "") or ""
        data_secret_merge[key] = value or ""

    # Build the candidate. model_copy does NOT coerce dict -> ProviderConfig, so
    # pass the parsed objects from ``update`` rather than the dumped payload.
    candidate_update: dict[str, Any] = {**non_secret_updates, **data_secret_merge}
    if update.custom_providers is not None:
        candidate_update["custom_providers"] = update.custom_providers
    candidate = current.model_copy(update=candidate_update)

    # LLM provider key merge — same no-wipe semantics, for every provider in the
    # candidate registry: incoming -> stored keychain -> current runtime value.
    provider_key_merge: dict[str, str] = {}
    for provider in candidate.providers:
        value = provider_key_updates.get(provider.id)
        if not value:
            value = await secret_store.get(_provider_key_name(provider.id))
            if value is None:
                value = current.provider_key(provider.id) or ""
        if value:
            provider_key_merge[provider.id] = value
    candidate = candidate.with_provider_keys(provider_key_merge)

    # NB: we do NOT 400 on validate_runtime_config failure here. Saving an
    # unrelated field (e.g. a data-source key) must never be blocked because the
    # LLM model has no key yet — that chicken-and-egg made every save fail with
    # "No API key configured for provider 'openai'". Instead we persist the
    # change and reflect config validity in the non-blocking startup_error
    # banner, exactly like the boot path. _replace_runtime_settings skips agent
    # construction while the config is invalid, so nothing crashes. (Structural
    # errors in custom_providers are still a hard 400 — see _validate_custom_providers.)

    # Only WRITE secrets that arrived with a truthy value. A falsy/empty value in a
    # PUT is "no change", NOT "delete" (BUG-005) — the common case is the user
    # editing an unrelated field with the masked key input left blank. Deleting a
    # secret is the explicit POST /api/settings/clear-secret action.
    for key, value in data_secret_updates.items():
        if value:
            await secret_store.set(key, value)
    for provider_id, value in provider_key_updates.items():
        if value:
            await secret_store.set(_provider_key_name(provider_id), value)

    _merge_non_secret_settings(
        request.app.state.settings_path,
        non_secret_updates,
    )
    await _replace_runtime_settings(request, candidate)
    # Logging is configured once at boot from these fields (finrobot.obs.setup
    # reads log_level / log_to_file / log_retention_days). setup_logging is
    # idempotent, so a settings change is otherwise inert until the next
    # restart — re-apply it immediately when any logging field actually moved
    # so the PUT does what it claims.
    if non_secret_updates.keys() & {"log_level", "log_to_file", "log_retention_days"}:
        from finrobot.obs import setup_logging

        setup_logging(candidate, force=True)
    # Reflect config validity in the startup_error banner: set it when the LLM
    # config is incomplete/invalid (so LLM routes 503 with a clear message),
    # clear it once the user has filled in what was missing.
    try:
        candidate.validate_runtime_config()
        request.app.state.startup_error = None
    except ValueError as e:
        request.app.state.startup_error = str(e)
    return await _build_response(request)


@router.post("/clear-secret", response_model=SettingsResponse)
async def clear_secret_route(body: ClearSecretRequest, request: Request) -> SettingsResponse:
    """Explicitly delete one secret field from the keychain.

    This is the ONLY path that deletes a stored API key. Splitting it out of the
    PUT endpoint means an empty value in a settings form can never silently wipe
    a key (BUG-005) — a destructive action requires a deliberate call here.

    Clearable fields: a DataProvider secret (``fmp_api_key`` …) or an LLM
    provider key (``provider_key:<id>``).

    After deletion we rebuild runtime settings from scratch (settings.json, then
    re-hydrate the remaining keychain secrets) so the in-memory FinRobotSettings
    stops carrying the cleared value. If clearing the key leaves the runtime
    config invalid (e.g. the active LLM provider lost its key), the startup_error
    banner is set so the UI tells the user.
    """
    is_data_secret = body.field in _DATA_SECRET_FIELDS
    is_provider_key = body.field.startswith(_PROVIDER_KEY_PREFIX)
    if not (is_data_secret or is_provider_key):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown or non-secret field: {body.field}. Clearable: "
            f"{sorted(_DATA_SECRET_FIELDS)} or 'provider_key:<id>'.",
        )

    secret_store = request.app.state.secret_store
    settings_path: Path = request.app.state.settings_path

    await secret_store.delete(body.field)

    # Rebuild settings so the cleared secret is dropped from the in-memory
    # object. Mirrors /reset: pydantic-settings only re-reads .env on
    # construction, so we reconstruct rather than patch.
    from finrobot.config import get_settings

    rebuilt = get_settings(**load_non_secret_settings(settings_path))
    from finrobot.server import hydrate_settings_from_secrets

    rebuilt = await hydrate_settings_from_secrets(rebuilt, secret_store)

    await _replace_runtime_settings(request, rebuilt)

    # Re-validate: clearing a key may have broken (or, rarely, fixed) the config.
    try:
        rebuilt.validate_runtime_config()
        request.app.state.startup_error = None
    except ValueError as e:
        request.app.state.startup_error = str(e)

    return await _build_response(request)


async def _build_response(request: Request) -> SettingsResponse:
    # Same identity gate build_data_layer uses to register EdgarToolsProvider —
    # the single source of truth for sec_identity_active (no client-side mirror).
    from finrobot.engine.data.providers.edgar_provider import _is_valid_identity

    settings: FinRobotSettings = request.app.state.deps.settings
    secret_store = request.app.state.secret_store

    async def _has_key(secret_key: str, settings_field: str) -> bool:
        """True if the secret is stored in the keychain or present in settings."""
        if await secret_store.has(secret_key):
            return True
        return bool(getattr(settings, settings_field, ""))

    # Cache keychain lookups so we don't query the OS multiple times per field.
    keychain_presence: dict[str, bool] = {}
    for key in _DATA_SECRET_FIELDS:
        keychain_presence[key] = await secret_store.has(key)

    # Data layer providers that are actually available given configured keys.
    available: list[str] = []
    if await _has_key("fmp_api_key", "fmp_api_key"):
        available.append("fmp")
    if await _has_key("finnhub_api_key", "finnhub_api_key"):
        available.append("finnhub")
    available.extend(["yfinance", "sec_edgar"])
    # News aggregator is always available (Yahoo RSS); Alpha Vantage is optional
    available.append("news_aggregator")
    if await _has_key("alpha_vantage_api_key", "alpha_vantage_api_key"):
        available.append("alpha_vantage")
    if keychain_presence.get("adanos_api_key", False) or settings.adanos_api_key:
        available.append("adanos")

    # LLM provider registry: built-ins + user customs, each tagged with whether
    # its key is stored and whether it's a (non-deletable) built-in.
    provider_infos: list[ProviderInfo] = []
    for provider in settings.providers:
        key_set = await secret_store.has(_provider_key_name(provider.id)) or bool(
            settings.provider_key(provider.id)
        )
        provider_infos.append(
            ProviderInfo(
                id=provider.id,
                label=provider.label,
                kind=provider.kind,
                base_url=provider.base_url,
                models=provider.models,
                key_set=key_set,
                is_builtin=provider.id in _BUILTIN_PROVIDER_IDS,
            )
        )

    return SettingsResponse(
        model_name=settings.model_name,
        providers=provider_infos,
        custom_providers=settings.custom_providers,
        fmp_api_key_set=await _has_key("fmp_api_key", "fmp_api_key"),
        finnhub_api_key_set=await _has_key("finnhub_api_key", "finnhub_api_key"),
        alpha_vantage_api_key_set=await _has_key("alpha_vantage_api_key", "alpha_vantage_api_key"),
        adanos_api_key_set=keychain_presence.get("adanos_api_key", False)
        or bool(settings.adanos_api_key),
        sec_user_agent=settings.sec_user_agent,
        sec_identity_active=_is_valid_identity(settings.sec_user_agent),
        sec_identity_dismissed_at=settings.sec_identity_dismissed_at,
        sec_holdings_auto_refresh=settings.sec_holdings_auto_refresh,
        log_level=settings.log_level,
        log_to_file=settings.log_to_file,
        log_retention_days=settings.log_retention_days,
        available_providers=available,
        startup_error=getattr(request.app.state, "startup_error", None),
        secret_storage_mode=getattr(request.app.state, "secret_storage_mode", "keychain"),
    )


async def _replace_runtime_settings(request: Request, settings: FinRobotSettings) -> None:
    old_data_layer = request.app.state.deps.data_layer
    data_layer = build_data_layer(settings)
    request.app.state.deps.settings = settings
    request.app.state.deps.data_layer = data_layer
    # Build the LLM agents only when the config validates. Clearing the active
    # provider's key (POST /clear-secret) intentionally leaves the runtime
    # invalid — and the provider constructor (DeepSeekProvider/OpenAIProvider/…)
    # raises on a missing key, so rebuilding the lead agent here would 500 the
    # very request that's allowed to invalidate the config. Mirror the boot
    # path (server.lifespan): skip agent construction while invalid; the caller
    # sets startup_error, every LLM route 503s on it, and the next valid PUT
    # rebuilds both. Without this, "Clear" on the only configured key crashes.
    try:
        settings.validate_runtime_config()
        config_ok = True
    except ValueError:
        config_ok = False
    if config_ok:
        request.app.state.agent = create_lead_agent(
            settings, skill_registry=request.app.state.deps.skill_runtime
        )
        request.app.state.sub_agents = create_sub_agents(
            settings, skill_registry=request.app.state.deps.skill_runtime
        )
    else:
        request.app.state.agent = None
        request.app.state.sub_agents = {}
    await old_data_layer.close()


def load_non_secret_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Settings file {path} is malformed")
    return {k: v for k, v in raw.items() if k in _NON_SECRET_FIELDS}


def _merge_non_secret_settings(path: Path, updates: dict[str, Any]) -> None:
    """Merge ``updates`` into settings.json without touching unchanged fields.

    The previous implementation wrote every non-secret field with its
    *current effective value*, which permanently shadowed .env: once the
    user opened SettingsView and saved anything, every non-secret field
    got pinned into settings.json with whatever value happened to be in
    memory. From then on .env was dead and the user had no way to know.

    This version reads the current settings.json, applies only the keys
    the caller explicitly passed (i.e. the user actually changed in the UI),
    and writes the result back. Fields not in ``updates`` keep their
    previous status: if they were in settings.json they stay there, if they
    weren't they remain absent so .env / env-vars keep winning.
    """
    if not updates:
        return

    # Read current contents (if any) — tolerate missing/corrupt file.
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                existing = raw
        except (OSError, ValueError):
            existing = {}

    # Apply only the keys the caller passed AND that are non-secret.
    mutated = False
    for key, value in updates.items():
        if key not in _NON_SECRET_FIELDS:
            continue
        existing[key] = value
        mutated = True

    if not mutated:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    # default=str lets ``datetime`` / ``Path`` values serialize cleanly. On
    # the read side ``load_non_secret_settings`` returns the raw dict and
    # pydantic-settings coerces ISO strings back into ``datetime`` fields
    # (e.g. ``sec_identity_dismissed_at``) during ``FinRobotSettings(...)``.
    path.write_text(
        json.dumps(existing, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
