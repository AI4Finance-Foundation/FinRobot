from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import stat
import tempfile
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from starlette.requests import Request

from finrobot.config import (
    BUILTIN_PROVIDERS,
    DATA_PROVIDER_SECRET_FIELDS,
    FinRobotSettings,
    LogLevel,
    ProviderConfig,
)
from finrobot.llm_probe import LlmProbeGate, probe_model
from finrobot.secret_store import SecretStorageMode, SecretStoreError
from finrobot.engine.data.factory import build_data_layer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

# DataProvider secrets (FMP / Finnhub / …) stored in the OS keychain (or
# FileSecretStore fallback) under their own field name. LLM provider API keys
# use the dynamic ``provider_key:<id>`` scheme instead — see _PROVIDER_KEY_PREFIX.
_DATA_SECRET_FIELDS: tuple[str, ...] = DATA_PROVIDER_SECRET_FIELDS

# Keychain key prefix for an LLM provider's API key: ``provider_key:<provider_id>``.
_PROVIDER_KEY_PREFIX = "provider_key:"

# Built-in provider ids cannot be deleted or shadowed by a custom provider.
_BUILTIN_PROVIDER_IDS: frozenset[str] = frozenset(p.id for p in BUILTIN_PROVIDERS)


# Serialises every settings mutation (PUT and clear-secret). Both endpoints
# are read-modify-write over THREE stores at once (in-memory deps.settings,
# the keychain, settings.json) — two concurrent PUTs interleaving their reads
# silently drop one caller's fields from the merged candidate (lost update),
# and the settings.json merge below is itself a read-modify-write of the file.
# A single-process desktop server makes an in-process lock sufficient.
_settings_mutation_lock = asyncio.Lock()

# Grace period before a replaced DataLayer is actually closed. Pipelines read
# ``deps.data_layer`` afresh on every fetch (the deps object is mutated in
# place), so after a swap only fetches ALREADY awaiting on the old layer still
# use it — closing immediately yanks their connection pools mid-await and
# fails an in-flight run because the user saved an unrelated setting. A single
# in-flight fetch is bounded by the provider httpx timeouts (~15-30s) plus
# retries, so 120s comfortably drains it. Reference counting would need a
# DataLayer contract change; the deferred close gets the same safety from the
# route side alone.
_RETIRED_LAYER_GRACE_S = 120.0
# Strong refs so the deferred-close tasks aren't GC'd mid-flight.
_retired_layer_tasks: set[asyncio.Task[None]] = set()


async def _close_layer_after_grace(layer: Any) -> None:
    try:
        # Module attribute read at call time (not a bound default) so tests can
        # shrink the grace window via monkeypatch.
        await asyncio.sleep(_RETIRED_LAYER_GRACE_S)
    finally:
        # Runs even when the server shuts down mid-grace (task cancelled):
        # the retired layer's provider pools must still be closed, not leaked.
        with contextlib.suppress(Exception):
            await layer.close()


def _schedule_retired_layer_close(layer: Any) -> None:
    task = asyncio.get_running_loop().create_task(_close_layer_after_grace(layer))
    _retired_layer_tasks.add(task)
    task.add_done_callback(_retired_layer_tasks.discard)


def _provider_key_name(provider_id: str) -> str:
    return f"{_PROVIDER_KEY_PREFIX}{provider_id}"


def _normalize_provider_key_updates(provider_keys: dict[str, str] | None) -> dict[str, str]:
    updates: dict[str, str] = {}
    for raw_provider_id, value in (provider_keys or {}).items():
        provider_id = raw_provider_id.strip().lower()
        if not provider_id:
            raise HTTPException(status_code=400, detail="Provider key id must not be empty.")
        if provider_id in updates:
            raise HTTPException(status_code=400, detail=f"Duplicate provider key '{provider_id}'.")
        updates[provider_id] = value
    return updates


def _normalize_model_name_update(model_name: str | None) -> str | None:
    """Normalize only the provider prefix in ``provider:model_id`` updates.

    Provider ids are case-insensitive at the settings boundary (custom provider
    ids and provider_keys are already lowercased here), but model ids are owned
    by upstream providers and may be case-sensitive. Keep the right-hand side as
    typed while making the left-hand side match the persisted provider registry.
    """
    if model_name is None:
        return None
    provider_id, sep, model_id = model_name.partition(":")
    provider_id = provider_id.strip().lower()
    if not provider_id:
        return model_name.strip()
    return f"{provider_id}:{model_id.strip()}" if sep else provider_id


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
    "peer_sticky_max_age_days",
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
    # NB: an empty model_name (first-run) is NOT a startup_error — it leaves this
    # null and is reflected by ``model_configured: false`` instead.
    startup_error: str | None = None
    # True when a usable LLM is selected (model chosen AND its provider keyed).
    # False on a fresh install (no model yet) — the UI treats that as a friendly
    # onboarding state (overlay + AI-CTA preflight), distinct from startup_error
    # which only fires for a chosen-but-broken model.
    model_configured: bool = False
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
    log_level: LogLevel | None = None
    log_to_file: bool | None = None
    log_retention_days: int | None = Field(default=None, ge=0)

    # LLM provider API keys keyed by provider id ({"deepseek": "sk-…"}). Written
    # to the keychain under provider_key:<id>. A blank value is "no change", not
    # "delete" (BUG-005) — clearing is the explicit clear-secret endpoint.
    provider_keys: dict[str, str] | None = Field(default=None, repr=False)
    fmp_api_key: str | None = Field(default=None, repr=False)
    finnhub_api_key: str | None = Field(default=None, repr=False)
    alpha_vantage_api_key: str | None = Field(default=None, repr=False)
    adanos_api_key: str | None = Field(default=None, repr=False)

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().upper()
        return value


class ClearSecretRequest(BaseModel):
    """A single secret field to delete from the keychain.

    ``clear-secret`` is the explicit "wipe this stored API key" action. It is
    its own endpoint so deleting a secret can NEVER happen as a side effect of
    an empty value in a PUT (BUG-005) — the destructive path needs deliberate
    intent.
    """

    field: str


def _normalize_custom_providers(providers: list[ProviderConfig]) -> list[ProviderConfig]:
    """Return custom providers in the persisted registry shape.

    A custom provider must have a non-empty id that does not shadow a built-in
    or duplicate another custom one, and an ``openai-compatible`` provider needs
    a base_url (there is no canonical endpoint to fall back to). Raises HTTP 400.
    """
    seen: set[str] = set()
    normalized: list[ProviderConfig] = []
    for provider in providers:
        pid = provider.id.strip().lower()
        if not pid:
            raise HTTPException(status_code=400, detail="Provider id must not be empty.")
        if ":" in pid:
            # The id is the "<id>:<model>" prefix in model_name — a colon would
            # break that split (the UI uses the provider name as its id).
            raise HTTPException(status_code=400, detail="Provider name must not contain ':'.")
        if pid in _BUILTIN_PROVIDER_IDS:
            raise HTTPException(
                status_code=400,
                detail=f"Provider id '{pid}' is built-in and cannot be redefined.",
            )
        if pid in seen:
            raise HTTPException(status_code=400, detail=f"Duplicate provider id '{pid}'.")
        seen.add(pid)
        label = provider.label.strip()
        if not label:
            raise HTTPException(
                status_code=400, detail=f"Provider '{pid}' label must not be empty."
            )
        if provider.kind == "openai-compatible" and not (provider.base_url or "").strip():
            raise HTTPException(
                status_code=400,
                detail=f"Provider '{pid}' (openai-compatible) requires a base_url.",
            )
        normalized.append(provider.model_copy(update={"id": pid, "label": label}))
    return normalized


@router.get("", response_model=SettingsResponse)
async def get_settings_route(request: Request) -> SettingsResponse:
    return await _build_response(request)


@router.put("", response_model=SettingsResponse)
async def put_settings_route(update: SettingsUpdate, request: Request) -> SettingsResponse:
    """Apply a settings update. Serialised by ``_settings_mutation_lock`` —
    the body is a read-modify-write over deps.settings + keychain +
    settings.json, so concurrent PUTs would silently drop one caller's fields."""
    async with _settings_mutation_lock:
        return await _put_settings_locked(update, request)


async def _put_settings_locked(update: SettingsUpdate, request: Request) -> SettingsResponse:
    secret_store = request.app.state.secret_store
    current: FinRobotSettings = request.app.state.deps.settings
    payload = update.model_dump(exclude_unset=True)

    non_secret_updates = {k: v for k, v in payload.items() if k in _NON_SECRET_FIELDS}
    if "model_name" in non_secret_updates:
        non_secret_updates["model_name"] = _normalize_model_name_update(
            non_secret_updates["model_name"]
        )
    data_secret_updates = {k: v for k, v in payload.items() if k in _DATA_SECRET_FIELDS}
    provider_key_updates = _normalize_provider_key_updates(update.provider_keys)

    # Reject malformed / colliding custom providers before they reach the registry.
    custom_providers: list[ProviderConfig] | None = None
    if update.custom_providers is not None:
        custom_providers = _normalize_custom_providers(update.custom_providers)
        non_secret_updates["custom_providers"] = [p.model_dump() for p in custom_providers]

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
    if custom_providers is not None:
        candidate_update["custom_providers"] = custom_providers
    candidate = current.model_copy(update=candidate_update)
    provider_ids = {provider.id for provider in candidate.providers}
    unknown_provider_keys = sorted(set(provider_key_updates) - provider_ids)
    if unknown_provider_keys:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider key id(s): {', '.join(unknown_provider_keys)}.",
        )

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
    try:
        for key, value in data_secret_updates.items():
            if value:
                await secret_store.set(key, value)
        for provider_id, value in provider_key_updates.items():
            if value:
                await secret_store.set(_provider_key_name(provider_id), value)
    except SecretStoreError as exc:
        # The keychain refused the write (user denied the OS prompt / keychain
        # locked). The key was NOT saved — say so explicitly instead of letting
        # an opaque 500 pretend "something broke somewhere". Runtime settings
        # are intentionally untouched: nothing was persisted, so nothing changes.
        raise HTTPException(status_code=500, detail=str(exc)) from exc

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
    # Reflect config validity in the startup_error banner. runtime_config_error
    # (not validate directly): saving an unrelated field while no model is chosen
    # yet must NOT raise a banner — empty model_name is onboarding, returns None.
    # Only a chosen-but-broken model sets the banner; LLM routes still 503 on the
    # empty case via is_model_configured.
    request.app.state.startup_error = candidate.runtime_config_error()
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

    Serialised by ``_settings_mutation_lock`` like PUT — the rebuild reads the
    keychain + settings.json and replaces runtime state, so racing a PUT could
    resurrect the just-cleared key or drop the PUT's fields.
    """
    async with _settings_mutation_lock:
        return await _clear_secret_locked(body, request)


async def _clear_secret_locked(body: ClearSecretRequest, request: Request) -> SettingsResponse:
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

    try:
        await secret_store.delete(body.field)
    except SecretStoreError as exc:
        # Keychain refused the delete — the secret is still stored, so the
        # clear must fail loudly with the real reason, not pretend success.
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Rebuild settings so the cleared secret is dropped from the in-memory
    # object. Mirrors /reset: pydantic-settings only re-reads .env on
    # construction, so we reconstruct rather than patch.
    from finrobot.config import get_settings

    rebuilt = get_settings(**load_non_secret_settings(settings_path))
    from finrobot.server import hydrate_settings_from_secrets

    rebuilt = await hydrate_settings_from_secrets(rebuilt, secret_store)

    await _replace_runtime_settings(request, rebuilt)

    # Re-validate: clearing a key may have broken (or, rarely, fixed) the config.
    # runtime_config_error keeps the empty-model case banner-free (onboarding).
    request.app.state.startup_error = rebuilt.runtime_config_error()

    return await _build_response(request)


class TestProviderRequest(BaseModel):
    """Live connectivity check for a provider's saved key / base_url / model."""

    provider_id: str
    model_id: str | None = None


class TestProviderResponse(BaseModel):
    ok: bool
    # Stable code the UI localizes: ok | no_key | no_model | auth | connect |
    # not_found | http | unknown. ``detail`` is the raw English message (shown
    # verbatim for the http/unknown cases, useful for debugging).
    code: str
    detail: str = ""


@router.post("/test-provider", response_model=TestProviderResponse)
async def test_provider_route(body: TestProviderRequest, request: Request) -> TestProviderResponse:
    """Make a tiny live LLM call to verify a provider's key / base_url / model.

    Uses the currently-saved runtime config (the key the user just stored). This
    is how a wrong key / bad base_url / unknown model is caught with a clear
    message at config time, instead of failing 60s later inside an analysis run.
    """
    settings: FinRobotSettings = request.app.state.deps.settings
    cfg = settings.provider_by_id(body.provider_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{body.provider_id}'.")
    if cfg.kind != "test" and not settings.provider_key(body.provider_id):
        return TestProviderResponse(ok=False, code="no_key")
    model_id = (body.model_id or "").strip()
    if not model_id:
        return TestProviderResponse(ok=False, code="no_model")

    ok, code, detail = await probe_model(settings, body.provider_id, model_id)
    if ok:
        # Seed the run-submit gate: a green Settings test on the SELECTED model
        # is the same evidence the gate would buy with its own ping — don't make
        # the first run pay for a second one.
        gate: LlmProbeGate | None = getattr(request.app.state, "llm_probe_gate", None)
        if gate is not None:
            gate.mark_verified(settings, body.provider_id, model_id)
    return TestProviderResponse(ok=ok, code=code, detail=detail)


# ── Data-source connectivity test ────────────────────────────────────────────
# Mirrors test_provider_route, but for a DataProvider API key (FMP / Finnhub /
# …). Each probe makes ONE minimal authenticated call (a single AAPL lookup) so a
# wrong / expired data key is caught here at config time, instead of silently
# surfacing as missing data 60s into an analysis run. Reuses the same stable
# ``code`` vocabulary the UI already localizes.
#
# SECURITY: FMP / Alpha Vantage carry the key in the request URL (``?apikey=…``),
# and httpx bakes that URL into its exception ``str()``. So unlike the LLM
# classifier, _classify_data_provider_error NEVER returns a raw exception string —
# detail is synthesised from the status code / a key-free note only.

_DATA_PROBE_TICKER = "AAPL"  # stable, always-present on every source


async def _probe_fmp(key: str) -> None:
    from finrobot.engine.data.providers.fmp_provider import FMPProvider

    # stable /profile: free-plan full coverage, so a healthy key always passes
    # regardless of tier (the plan-gated endpoints would false-fail free keys).
    provider = FMPProvider(api_key=key)
    try:
        await provider._get("/profile", params={"symbol": _DATA_PROBE_TICKER})
    finally:
        await provider.close()


async def _probe_finnhub(key: str) -> None:
    from finrobot.engine.data.providers.finnhub_provider import FinnhubProvider

    provider = FinnhubProvider(api_key=key)
    try:
        await provider._get("/stock/profile2", params={"symbol": _DATA_PROBE_TICKER})
    finally:
        await provider.close()


async def _probe_adanos(key: str) -> None:
    from finrobot.engine.data.providers.adanos_provider import AdanosProvider

    provider = AdanosProvider(api_key=key)
    try:
        await provider._get(
            "/reddit/stocks/v1/compare", params={"tickers": _DATA_PROBE_TICKER, "days": 1}
        )
    finally:
        await provider.close()


async def _probe_alpha_vantage(key: str) -> None:
    import httpx

    from finrobot.engine.data.interface import ProviderError

    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": _DATA_PROBE_TICKER,
        "apikey": key,
        "limit": "1",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get("https://www.alphavantage.co/query", params=params)
        resp.raise_for_status()
        data = resp.json()
    # Alpha Vantage answers HTTP 200 with a note (not an error status) when the key
    # is invalid or rate-limited. The note text is key-free, so it's safe to surface.
    if "feed" not in data:
        note = data.get("Error Message") or data.get("Information") or data.get("Note")
        raise ProviderError(str(note) if note else "Alpha Vantage returned no feed")


# provider id → (settings key attribute, probe). Keyed off the same data-secret
# fields the rest of this module uses; adding a new keyed source is one entry.
_DATA_PROBES: dict[str, tuple[str, Callable[[str], Awaitable[None]]]] = {
    "fmp": ("fmp_api_key", _probe_fmp),
    "finnhub": ("finnhub_api_key", _probe_finnhub),
    "adanos": ("adanos_api_key", _probe_adanos),
    "alpha_vantage": ("alpha_vantage_api_key", _probe_alpha_vantage),
}


def _classify_data_provider_error(exc: BaseException) -> tuple[str, str]:
    """Map a data-provider probe failure to (code, key-free detail).

    Returns the same ``code`` vocabulary as llm_probe.classify_provider_error so the UI
    reuses one set of localized strings. NEVER returns the raw exception text:
    the request URL (which httpx embeds in the message) carries the live key.
    """
    import httpx

    from finrobot.engine.data.interface import ProviderError, ProviderPlanError

    if isinstance(exc, ProviderPlanError):
        # Typed by the provider itself (key valid, endpoint outside the plan) —
        # classify before the generic ProviderError sniffing below.
        return "plan", str(exc)[:200]
    if isinstance(exc, httpx.HTTPStatusError):
        sc = exc.response.status_code
        if sc == 403:
            # FMP answers 403 with a key-free "Legacy Endpoint" / "Exclusive
            # Endpoint" body when the key is VALID but the account's plan can't
            # use the endpoint (accounts created after 2025-08-31 lost /api/v3).
            # Calling that "invalid key" sends the user chasing the wrong fix.
            try:
                body = exc.response.text[:500].lower()
            except httpx.ResponseNotRead:
                body = ""
            if any(s in body for s in ("legacy endpoint", "exclusive endpoint", "subscription")):
                return "plan", f"HTTP {sc}"
            return "auth", f"HTTP {sc}"
        if sc == 401:
            return "auth", f"HTTP {sc}"
        if sc == 404:
            return "not_found", f"HTTP {sc}"
        if sc == 429:
            return "rate_limited", f"HTTP {sc}"
        return "http", f"HTTP {sc}"
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.TimeoutException)):
        return "connect", type(exc).__name__
    if isinstance(exc, ProviderError):
        # Alpha Vantage's 200-with-note path. The note text is key-free.
        msg = str(exc)[:200]
        low = msg.lower()
        if any(s in low for s in ("api key", "apikey", "invalid", "unauthorized")):
            return "auth", msg
        return "http", msg
    return "unknown", type(exc).__name__


class TestDataProviderRequest(BaseModel):
    """Live connectivity check for a data-source API key (FMP / Finnhub / …)."""

    provider: str  # fmp | finnhub | adanos | alpha_vantage


@router.post("/test-data-provider", response_model=TestProviderResponse)
async def test_data_provider_route(
    body: TestDataProviderRequest, request: Request
) -> TestProviderResponse:
    """Make a tiny live call to verify a saved data-source API key actually works.

    The key tested is the one currently in runtime settings (the value the just-
    completed save persisted), so a wrong / expired data key is caught here with a
    clear message rather than as missing data inside an analysis run.
    """
    probe = _DATA_PROBES.get(body.provider)
    if probe is None:
        raise HTTPException(status_code=404, detail=f"Unknown data provider '{body.provider}'.")
    key_attr, probe_fn = probe
    settings: FinRobotSettings = request.app.state.deps.settings
    key = (getattr(settings, key_attr, "") or "").strip()
    if not key:
        return TestProviderResponse(ok=False, code="no_key")
    try:
        await probe_fn(key)
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise  # never swallow control-flow / shutdown signals (red-line N2)
    except BaseException as exc:  # noqa: BLE001 — classify any probe failure for the UI
        code, detail = _classify_data_provider_error(exc)
        if code == "rate_limited":
            _record_data_probe_health(request, body.provider, ok=False, code=code)
        return TestProviderResponse(ok=False, code=code, detail=detail)
    _record_data_probe_health(request, body.provider, ok=True, code="ok")
    return TestProviderResponse(ok=True, code="ok")


def _record_data_probe_health(request: Request, provider: str, *, ok: bool, code: str) -> None:
    """Fold Settings' explicit probe verdict back into the live provider-health dot.

    A successful manual test is strong evidence that a previously-open breaker can
    close now; a 429 should open the cooldown immediately. Auth / plan failures
    stay in the row-level test verdict instead of poisoning the runtime breaker.
    Alpha Vantage is nested under NewsAggregatorProvider, so it has no standalone
    breaker row to update.
    """
    data_layer = getattr(request.app.state.deps, "data_layer", None)
    health = getattr(data_layer, "_health", None)
    if health is None:
        return
    provider_status = getattr(data_layer, "provider_status", None)
    if not callable(provider_status):
        return
    try:
        provider_names = {name for name, _available, _state in provider_status()}
    except (AttributeError, TypeError, ValueError):  # pragma: no cover - defensive test doubles
        return
    if provider not in provider_names:
        return
    if ok:
        health.record_success(provider)
    elif code == "rate_limited":
        health.record_failure(provider, rate_limited=True)


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
        model_configured=settings.is_model_configured,
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
    # is_model_configured is the precise gate: it's false for empty model
    # (onboarding), unknown provider, AND missing key — all three would crash
    # create_model. Mirrors the boot path (server.lifespan).
    if settings.is_model_configured:
        # Lazy: agent constructors pull the orchestrator's pydantic_ai stack; kept
        # off the sidecar cold-start import path (tests/unit/test_cold_import.py).
        from finrobot.engine.agents.factory import create_sub_agents
        from finrobot.engine.orchestrator import create_lead_agent

        sub_agents = create_sub_agents(
            settings, skill_registry=request.app.state.deps.skill_runtime
        )
        request.app.state.sub_agents = sub_agents
        request.app.state.agent = create_lead_agent(
            settings,
            skill_registry=request.app.state.deps.skill_runtime,
            sub_agents=sub_agents,
        )
    else:
        request.app.state.agent = None
        request.app.state.sub_agents = {}
    # Deferred close: pipelines re-read deps.data_layer per fetch, but a fetch
    # ALREADY awaiting on the old layer would have its connection pool yanked
    # mid-await by an immediate close — a settings save must never fail an
    # in-flight run. See _RETIRED_LAYER_GRACE_S for the drain-window reasoning.
    _schedule_retired_layer_close(old_data_layer)


def load_non_secret_settings_with_error(path: Path) -> tuple[dict[str, Any], str | None]:
    """Read the persisted non-secret overrides, tolerating a corrupt file.

    Returns ``(overrides, corruption_error)``. A truncated / malformed / unreadable
    settings.json degrades to ``({}, "<description>")`` instead of raising: the
    desktop sidecar gets SIGKILLed by the Tauri shell at exit, so a torn write
    was reachable before ``_atomic_write_text`` existed, and a crash here killed
    the server boot — leaving the user with no UI to repair anything from. The
    boot path (server.lifespan) surfaces the error string via the startup_error
    banner so the corruption is user-visible, never silent; any later Settings
    save rewrites the file clean. This mirrors the tolerance
    ``_merge_non_secret_settings`` below always had (same file, same risk).
    """
    if not path.exists():
        return {}, None
    # Self-heal permission drift on the boot read, mirroring FileSecretStore:
    # an existing install's settings.json predates the 0600 write path (or a
    # backup/restore loosened it), and waiting for the next save would leave it
    # group/other-readable indefinitely. Never fatal — perms are best-effort.
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            logger.warning("Settings file %s had mode %#o; tightened to 0600.", path, mode)
    except OSError:
        pass
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        error = (
            f"Settings file {path} is corrupt or unreadable ({exc}); it was ignored and "
            "non-secret settings reverted to defaults. Open Settings and save once to "
            "rewrite it."
        )
        logger.warning("%s", error)
        return {}, error
    if not isinstance(raw, dict):
        error = (
            f"Settings file {path} is malformed (expected a JSON object, got "
            f"{type(raw).__name__}); it was ignored and non-secret settings reverted to "
            "defaults. Open Settings and save once to rewrite it."
        )
        logger.warning("%s", error)
        return {}, error
    return {k: v for k, v in raw.items() if k in _NON_SECRET_FIELDS}, None


def load_non_secret_settings(path: Path) -> dict[str, Any]:
    """Non-secret overrides from settings.json; corruption degrades to ``{}``.

    Convenience wrapper for callers that don't surface the corruption to a UI
    (clear-secret rebuild, diagnostic scripts). The boot path uses
    :func:`load_non_secret_settings_with_error` to also report the corruption.
    """
    overrides, _error = load_non_secret_settings_with_error(path)
    return overrides


def _atomic_write_text(path: Path, payload: str) -> None:
    """Write ``payload`` to ``path`` via temp file + ``os.replace`` (same directory).

    settings.json was previously written with a bare ``write_text`` (open-truncate-
    write), so a SIGKILL mid-write — routine when the Tauri shell tears down the
    sidecar — could leave a truncated file on disk. The rename is atomic on the
    same filesystem, so readers only ever observe the old or the new content.

    Mode is forced to 0600 — symmetric with the FileSecretStore's .secrets
    handling. settings.json holds no API keys, but it does hold the user's SEC
    identity (name + email in ``sec_user_agent``) and their provider registry
    (custom base_urls), which other local users have no business reading. The
    rewrite also self-heals a file that drifted looser (backup/restore, editor
    rewrites under the default umask).
    """
    mode = stat.S_IRUSR | stat.S_IWUSR  # 0600, always — never preserve looser bits
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f"{path.name}.", suffix=".tmp")
    try:
        os.write(fd, payload.encode("utf-8"))
        os.fsync(fd)
        os.close(fd)
        fd = -1  # mark as closed
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


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
    _atomic_write_text(path, json.dumps(existing, indent=2, sort_keys=True, default=str))


# ── Data Provider Status (门五②) ─────────────────────────────────────────────
# Read-only view over the live DataLayer's ProviderHealth breaker for the
# Settings「Data Provider Status」panel. Signals are the real circuit state —
# spec acceptance forbids a mocked all-green panel.

# Which settings field holds a provider's credential. yfinance has no key
# concept at all → key_required=False, key_configured=None (a fake "configured"
# chip on a keyless provider would be noise, not provenance).
_PROVIDER_KEY_FIELDS: dict[str, str] = {
    "fmp": "fmp_api_key",
    "finnhub": "finnhub_api_key",
    "edgar_tools": "sec_user_agent",
    "adanos": "adanos_api_key",
}


class ProviderHealthEntry(BaseModel):
    name: str
    key_required: bool
    key_configured: bool | None = None
    available: bool
    # Stable tokens the UI switches on (T8: backend Literal ⊆ frontend union).
    circuit_state: str = Field(pattern="^(closed|open)$")
    cooldown_until: datetime | None = None
    consecutive_failures: int = 0
    last_success: datetime | None = None
    last_failure: datetime | None = None
    last_rate_limited: bool = False


class ProviderHealthResponse(BaseModel):
    providers: list[ProviderHealthEntry]


@router.get("/provider-health", response_model=ProviderHealthResponse)
async def provider_health_route(request: Request) -> ProviderHealthResponse:
    """Per-provider circuit/freshness signals from the live ProviderHealth
    breaker — name, availability, cooldown window, last success/failure/429,
    and whether the provider's credential is configured."""
    data_layer = request.app.state.deps.data_layer
    settings = request.app.state.deps.settings
    entries: list[ProviderHealthEntry] = []
    for name, available, state in data_layer.provider_status():
        key_field = _PROVIDER_KEY_FIELDS.get(name)
        entries.append(
            ProviderHealthEntry(
                name=name,
                key_required=key_field is not None,
                key_configured=(
                    bool(getattr(settings, key_field, "")) if key_field is not None else None
                ),
                available=available,
                circuit_state="closed" if available else "open",
                cooldown_until=state.cooldown_until,
                consecutive_failures=state.consecutive_failures,
                last_success=state.last_success,
                last_failure=state.last_failure,
                last_rate_limited=state.last_rate_limited,
            )
        )
    return ProviderHealthResponse(providers=entries)
