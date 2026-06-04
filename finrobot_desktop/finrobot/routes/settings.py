from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.requests import Request

from finrobot.config import (
    FinRobotSettings,
    is_field_from_environ,
)
from finrobot.secret_store import SecretStorageMode
from finrobot.data_layer_factory import build_data_layer
from finrobot.engine.agents.factory import create_sub_agents
from finrobot.engine.orchestrator import create_lead_agent

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Secret fields are stored in the OS keychain (or FileSecretStore fallback),
# never in settings.json. ``adanos_api_key`` was historically missing from
# both lists — that meant the PUT endpoint silently dropped updates to it
# and the GET endpoint could not report it. Treat it as a secret.
_SECRET_FIELDS: tuple[str, ...] = (
    "anthropic_api_key",
    "deepseek_api_key",
    "openai_api_key",
    "fmp_api_key",
    "finnhub_api_key",
    "alpha_vantage_api_key",
    "adanos_api_key",
)

# Non-secret fields are written into ``~/.finrobot/settings.json`` only when
# the user explicitly changes them. A field that has never been touched
# from the UI MUST stay out of settings.json so .env / env-vars keep winning.
# This is what got users into trouble before: writing every field with its
# current effective value caused .env to be silently shadowed forever.
_NON_SECRET_FIELDS: tuple[str, ...] = (
    "model_name",
    "model_data",
    "model_analysis",
    "model_modeling",
    "model_synthesis",
    "model_report",
    "sec_user_agent",
    "sec_identity_dismissed_at",  # 2026-05 EdgarTools — landing banner dismiss state
    "sec_holdings_auto_refresh",
    "log_level",
    "log_to_file",
    "log_retention_days",
)

# Source labels exposed to the UI. Keep this list of literals in sync with
# the ``SettingsSource`` type on the frontend.
SettingsSource = Literal["keychain", "settings_json", "env", "default"]


class SettingsResponse(BaseModel):
    model_name: str
    model_data: str | None = None
    model_analysis: str | None = None
    model_modeling: str | None = None
    model_synthesis: str | None = None
    model_report: str | None = None
    anthropic_api_key_set: bool
    deepseek_api_key_set: bool
    openai_api_key_set: bool
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
    valid_model_providers: list[Literal["anthropic", "deepseek", "openai"]]
    # Per-field source map. Key = field name (e.g. "model_name",
    # "anthropic_api_key"); value = where the effective value came from.
    # The UI uses this to render "[来自 .env]" / "[来自 settings.json]" /
    # "[来自 keychain]" / "[默认值]" badges next to each input.
    field_sources: dict[str, SettingsSource]
    # If validate_runtime_config() failed at server boot, the error message
    # is surfaced here so the UI can show a banner. None = config is valid.
    startup_error: str | None = None
    # Indicates whether secrets are protected by the OS keychain or written to
    # a permission-locked plaintext JSON file.  "plaintext" means the user
    # should be warned that their API keys are stored unencrypted on disk.
    secret_storage_mode: SecretStorageMode = "keychain"


class SettingsUpdate(BaseModel):
    model_name: str | None = None
    model_data: str | None = None
    model_analysis: str | None = None
    model_modeling: str | None = None
    model_synthesis: str | None = None
    model_report: str | None = None
    sec_user_agent: str | None = None
    sec_identity_dismissed_at: datetime | None = None
    sec_holdings_auto_refresh: bool | None = None
    log_level: str | None = None
    log_to_file: bool | None = None
    log_retention_days: int | None = None

    anthropic_api_key: str | None = Field(default=None, repr=False)
    deepseek_api_key: str | None = Field(default=None, repr=False)
    openai_api_key: str | None = Field(default=None, repr=False)
    fmp_api_key: str | None = Field(default=None, repr=False)
    finnhub_api_key: str | None = Field(default=None, repr=False)
    alpha_vantage_api_key: str | None = Field(default=None, repr=False)
    adanos_api_key: str | None = Field(default=None, repr=False)


class SettingsResetRequest(BaseModel):
    """Fields to clear from settings.json so .env / env-vars regain priority."""

    fields: list[str] = Field(default_factory=list)


class ClearSecretRequest(BaseModel):
    """A single secret field to delete from the keychain.

    Distinct from ``/reset``: ``/reset`` re-empowers .env (clears settings.json
    AND keychain), whereas ``clear-secret`` is the explicit "wipe this stored
    API key" action. It exists so deleting a secret can NEVER happen as a side
    effect of an empty value in a PUT (BUG-005) — the destructive path is its
    own endpoint with its own intent.
    """

    field: str


@router.get("", response_model=SettingsResponse)
async def get_settings_route(request: Request) -> SettingsResponse:
    return await _build_response(request)


@router.put("", response_model=SettingsResponse)
async def put_settings_route(update: SettingsUpdate, request: Request) -> SettingsResponse:
    secret_store = request.app.state.secret_store
    current = request.app.state.deps.settings
    payload = update.model_dump(exclude_unset=True)

    non_secret_updates = {k: v for k, v in payload.items() if k in _NON_SECRET_FIELDS}
    secret_updates = {k: v for k, v in payload.items() if k in _SECRET_FIELDS}

    secret_merge: dict[str, str] = {}
    for key in _SECRET_FIELDS:
        value = secret_updates.get(key)
        # A falsy incoming value (absent OR empty string) means "no change":
        # fall back to the stored keychain value, then the current effective
        # value (loaded from .env at boot). An empty password field in the
        # settings form must NEVER null out the merge candidate — otherwise
        # validate_runtime_config below would 400 a user who only edited an
        # unrelated field, and a write of "" would wipe the stored key
        # (BUG-005). Clearing a secret is the explicit clear-secret endpoint.
        if not value:
            value = await secret_store.get(key)
            if value is None:
                value = getattr(current, key, "") or ""
        secret_merge[key] = value or ""
    candidate = current.model_copy(update={**non_secret_updates, **secret_merge})

    try:
        candidate.validate_runtime_config()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Only WRITE secrets that arrived with a truthy value. A falsy/empty value
    # in a PUT is treated as "no change", NOT "delete" — a client that submits
    # the settings form with a blank password field (the common case: the user
    # edited an unrelated field, leaving the masked key input empty) must never
    # silently wipe a stored API key (BUG-005). Deleting a secret is now an
    # explicit, separate action — POST /api/settings/clear-secret.
    for key, value in secret_updates.items():
        if value:
            await secret_store.set(key, value)

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
    # A successful PUT means whatever validate-time error happened at boot
    # may now be resolved — clear the startup banner so the UI stops nagging.
    if getattr(request.app.state, "startup_error", None):
        try:
            candidate.validate_runtime_config()
            request.app.state.startup_error = None
        except ValueError:
            pass  # keep the existing banner
    return await _build_response(request)


@router.post("/reset", response_model=SettingsResponse)
async def reset_settings_route(body: SettingsResetRequest, request: Request) -> SettingsResponse:
    """Remove the listed fields from ``~/.finrobot/settings.json``.

    This re-empowers .env / FINROBOT_* environment variables as the source
    of truth for those fields. Secret fields are routed to the keychain
    instead: ``reset`` deletes them from the keychain so .env values can
    take over on the next request cycle.

    Reset semantics: clear-from-settings.json (and clear-from-keychain for
    secret fields). It does NOT copy .env values back into settings.json.
    """
    if not body.fields:
        raise HTTPException(status_code=400, detail="No fields to reset.")

    unknown = [f for f in body.fields if f not in _NON_SECRET_FIELDS + _SECRET_FIELDS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown reset fields: {sorted(unknown)}",
        )

    settings_path: Path = request.app.state.settings_path
    secret_store = request.app.state.secret_store

    # Strip non-secret fields out of settings.json in place.
    non_secret_to_clear = [f for f in body.fields if f in _NON_SECRET_FIELDS]
    if non_secret_to_clear and settings_path.exists():
        try:
            current_json: dict[str, Any] = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current_json = {}
        if isinstance(current_json, dict):
            mutated = False
            for field in non_secret_to_clear:
                if field in current_json:
                    current_json.pop(field, None)
                    mutated = True
            if mutated:
                settings_path.parent.mkdir(parents=True, exist_ok=True)
                settings_path.write_text(
                    json.dumps(current_json, indent=2, sort_keys=True),
                    encoding="utf-8",
                )

    # Clear secret fields from the keychain so .env wins on next reload.
    for field in body.fields:
        if field in _SECRET_FIELDS:
            await secret_store.delete(field)

    # Rebuild settings from scratch so the new (lower-priority) sources kick
    # in. We deliberately rebuild instead of patching the in-memory object
    # because pydantic-settings only re-reads .env on construction.
    from finrobot.config import get_settings

    rebuilt = get_settings(**load_non_secret_settings(settings_path))
    from finrobot.server import hydrate_settings_from_secrets

    rebuilt = await hydrate_settings_from_secrets(rebuilt, secret_store)

    await _replace_runtime_settings(request, rebuilt)

    # Re-run validation; clear the banner if config is now coherent.
    try:
        rebuilt.validate_runtime_config()
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

    After deletion we rebuild runtime settings from scratch (settings.json +
    .env, then re-hydrate the remaining keychain secrets) so the in-memory
    FinRobotSettings stops carrying the cleared value. If clearing the key
    leaves the runtime config invalid (e.g. the active LLM provider lost its
    key), the startup_error banner is set so the UI tells the user.
    """
    if body.field not in _SECRET_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown or non-secret field: {body.field}. "
            f"Clearable secrets: {sorted(_SECRET_FIELDS)}",
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
    settings_path: Path = request.app.state.settings_path

    # Snapshot of settings.json so we can attribute each field's source
    # without re-parsing on every field check.
    settings_json: dict[str, Any] = {}
    if settings_path.exists():
        try:
            raw = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                settings_json = raw
        except (OSError, ValueError):
            settings_json = {}

    async def _has_key(secret_key: str, settings_field: str) -> bool:
        """Check keychain first, then fall back to settings (.env)."""
        if await secret_store.has(secret_key):
            return True
        return bool(getattr(settings, settings_field, ""))

    # Cache keychain lookups so we don't query the OS multiple times per
    # field during source attribution.
    keychain_presence: dict[str, bool] = {}
    for key in _SECRET_FIELDS:
        keychain_presence[key] = await secret_store.has(key)

    field_sources: dict[str, SettingsSource] = {}
    for field in _NON_SECRET_FIELDS:
        field_sources[field] = _detect_non_secret_source(field, settings, settings_json)
    for field in _SECRET_FIELDS:
        field_sources[field] = _detect_secret_source(
            field, settings, in_keychain=keychain_presence[field]
        )

    providers: list[str] = []
    if await _has_key("fmp_api_key", "fmp_api_key"):
        providers.append("fmp")
    if await _has_key("finnhub_api_key", "finnhub_api_key"):
        providers.append("finnhub")
    providers.extend(["yfinance", "sec_edgar"])
    # News aggregator is always available (Yahoo RSS); Alpha Vantage is optional
    providers.append("news_aggregator")
    if await _has_key("alpha_vantage_api_key", "alpha_vantage_api_key"):
        providers.append("alpha_vantage")
    if keychain_presence.get("adanos_api_key", False) or settings.adanos_api_key:
        providers.append("adanos")

    return SettingsResponse(
        model_name=settings.model_name,
        model_data=settings.model_data,
        model_analysis=settings.model_analysis,
        model_modeling=settings.model_modeling,
        model_synthesis=settings.model_synthesis,
        model_report=settings.model_report,
        anthropic_api_key_set=await _has_key("anthropic_api_key", "anthropic_api_key"),
        deepseek_api_key_set=await _has_key("deepseek_api_key", "deepseek_api_key"),
        openai_api_key_set=await _has_key("openai_api_key", "openai_api_key"),
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
        available_providers=providers,
        valid_model_providers=["deepseek", "anthropic", "openai"],
        field_sources=field_sources,
        startup_error=getattr(request.app.state, "startup_error", None),
        secret_storage_mode=getattr(request.app.state, "secret_storage_mode", "keychain"),
    )


def _detect_non_secret_source(
    field: str, settings: FinRobotSettings, settings_json: dict[str, Any]
) -> SettingsSource:
    """Attribute a non-secret field's effective value to its source.

    Priority mirrors pydantic-settings + our load order in server.lifespan:
      settings.json (highest, applied as constructor kwarg)
        > FINROBOT_* env var
          > .env file
            > class default

    We can't distinguish .env from a real environment variable after the
    fact (both end up in the OS environment once pydantic-settings reads
    them on import), so they collapse into a single ``"env"`` label.
    That's accurate enough for the UI's purpose: "not coming from
    settings.json".
    """
    if field in settings_json:
        return "settings_json"
    if is_field_from_environ(field):
        return "env"
    # Compare with the class default — if the value matches the default,
    # we treat it as "default". This is imperfect (env could legitimately
    # set the same value as the default), but for retail users it's a
    # useful disambiguation.
    default_value = FinRobotSettings.model_fields[field].default
    current_value = getattr(settings, field, None)
    if current_value == default_value:
        return "default"
    # Value differs from default but isn't in settings.json or env vars —
    # most likely came from .env via pydantic-settings.
    return "env"


def _detect_secret_source(
    field: str, settings: FinRobotSettings, *, in_keychain: bool
) -> SettingsSource:
    """Attribute a secret field's source.

    Keychain takes precedence (it's loaded last in hydrate_settings_from_secrets),
    then env / .env. ``"default"`` here means the value is empty.
    """
    if in_keychain:
        return "keychain"
    if is_field_from_environ(field):
        return "env"
    if getattr(settings, field, ""):
        # Value present but not in keychain and not in the OS environment —
        # came from .env via pydantic-settings.
        return "env"
    return "default"


async def _replace_runtime_settings(request: Request, settings: FinRobotSettings) -> None:
    old_data_layer = request.app.state.deps.data_layer
    data_layer = build_data_layer(settings)
    request.app.state.deps.settings = settings
    request.app.state.deps.data_layer = data_layer
    request.app.state.agent = create_lead_agent(
        settings, skill_registry=request.app.state.deps.skill_runtime
    )
    request.app.state.sub_agents = create_sub_agents(
        settings, skill_registry=request.app.state.deps.skill_runtime
    )
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


# Kept as a deprecation-friendly alias because there may be importers in
# integration tests / scripts. New code should call _merge_non_secret_settings.
def _write_non_secret_settings(path: Path, settings: FinRobotSettings) -> None:
    """DEPRECATED — use ``_merge_non_secret_settings`` instead.

    The old contract (write every field unconditionally) is the exact bug
    we just fixed; this alias intentionally does nothing so accidental
    callers do not regress the fix. Tests that need to seed settings.json
    should write the JSON directly.
    """
    raise RuntimeError(
        "_write_non_secret_settings is deprecated. "
        "Use _merge_non_secret_settings(path, {field: value, ...}) instead."
    )
