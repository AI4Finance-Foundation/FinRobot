from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.requests import Request

from finagent.config import FinAgentSettings
from finagent.data_layer_factory import build_data_layer
from finagent.engine.agents.factory import create_sub_agents
from finagent.engine.orchestrator import create_lead_agent

router = APIRouter(prefix="/api/settings", tags=["settings"])

_SECRET_FIELDS = (
    "anthropic_api_key",
    "deepseek_api_key",
    "openai_api_key",
    "fmp_api_key",
    "finnhub_api_key",
    "alpha_vantage_api_key",
)

_NON_SECRET_FIELDS = (
    "model_name",
    "model_data",
    "model_analysis",
    "model_modeling",
    "model_synthesis",
    "model_report",
    "sec_user_agent",
    "log_level",
)


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
    sec_user_agent: str
    log_level: str
    available_providers: list[str]
    valid_model_providers: list[Literal["anthropic", "deepseek", "openai"]]


class SettingsUpdate(BaseModel):
    model_name: str | None = None
    model_data: str | None = None
    model_analysis: str | None = None
    model_modeling: str | None = None
    model_synthesis: str | None = None
    model_report: str | None = None
    sec_user_agent: str | None = None
    log_level: str | None = None

    anthropic_api_key: str | None = Field(default=None, repr=False)
    deepseek_api_key: str | None = Field(default=None, repr=False)
    openai_api_key: str | None = Field(default=None, repr=False)
    fmp_api_key: str | None = Field(default=None, repr=False)
    finnhub_api_key: str | None = Field(default=None, repr=False)
    alpha_vantage_api_key: str | None = Field(default=None, repr=False)


@router.get("", response_model=SettingsResponse)
async def get_settings_route(request: Request) -> SettingsResponse:
    return await _build_response(request)


@router.put("", response_model=SettingsResponse)
async def put_settings_route(
    update: SettingsUpdate, request: Request
) -> SettingsResponse:
    secret_store = request.app.state.secret_store
    current = request.app.state.deps.settings
    payload = update.model_dump(exclude_unset=True)

    non_secret_updates = {
        k: v for k, v in payload.items() if k in _NON_SECRET_FIELDS
    }
    secret_updates = {k: v for k, v in payload.items() if k in _SECRET_FIELDS}

    secret_merge: dict[str, str] = {}
    for key in _SECRET_FIELDS:
        value = secret_updates.get(key)
        if value is None:
            value = await secret_store.get(key)
        secret_merge[key] = value or ""
    candidate = current.model_copy(update={**non_secret_updates, **secret_merge})

    try:
        candidate.validate_runtime_config()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    for key, value in secret_updates.items():
        if value:
            await secret_store.set(key, value)
        else:
            await secret_store.delete(key)

    _write_non_secret_settings(
        request.app.state.settings_path,
        candidate,
    )
    await _replace_runtime_settings(request, candidate)
    return await _build_response(request)


async def _build_response(request: Request) -> SettingsResponse:
    settings: FinAgentSettings = request.app.state.deps.settings
    secret_store = request.app.state.secret_store

    async def _has_key(secret_key: str, settings_field: str) -> bool:
        """Check keychain first, then fall back to settings (.env)."""
        if await secret_store.has(secret_key):
            return True
        return bool(getattr(settings, settings_field, ""))

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
        sec_user_agent=settings.sec_user_agent,
        log_level=settings.log_level,
        available_providers=providers,
        valid_model_providers=["deepseek", "anthropic", "openai"],
    )


async def _replace_runtime_settings(
    request: Request, settings: FinAgentSettings
) -> None:
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
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"Settings file {path} is malformed")
    return {k: v for k, v in raw.items() if k in _NON_SECRET_FIELDS}


def _write_non_secret_settings(path: Path, settings: FinAgentSettings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {k: getattr(settings, k) for k in _NON_SECRET_FIELDS}
    path.write_text(json.dumps(data, indent=2, sort_keys=True))
