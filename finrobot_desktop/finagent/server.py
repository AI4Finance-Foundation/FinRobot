from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from pydantic_ai.ui.vercel_ai import VercelAIAdapter

from finagent.config import get_settings
from finagent.engine.data.cache import DataCache
from finagent.engine.data.layer import DataLayer
from finagent.engine.data.providers.yfinance_provider import YFinanceProvider
from finagent.engine.deps import FinAgentDeps
from finagent.engine.orchestrator import create_lead_agent
from finagent.engine.skills.registry import SkillRegistry


@asynccontextmanager
async def lifespan(app):
    settings = get_settings()

    # Load skills if available
    skills_path = Path(settings.skills_dir)
    registry = SkillRegistry(skills_path) if skills_path.exists() else None

    # Create agent and deps
    agent = create_lead_agent(settings, skill_registry=registry)
    cache = DataCache(settings.cache_db_path)
    data_layer = DataLayer(providers=[YFinanceProvider()], cache=cache)
    deps = FinAgentDeps(data_layer=data_layer, settings=settings, skill_runtime=registry)

    app.state.agent = agent
    app.state.deps = deps
    yield
    await cache.close()


# WARNING: This server has no authentication. For local development only.
# Do not expose to public network without adding auth middleware.
app = FastAPI(title="FinAgent", lifespan=lifespan)


@app.post("/chat")
async def chat(request: Request) -> Response:
    return await VercelAIAdapter.dispatch_request(
        request, agent=request.app.state.agent, deps=request.app.state.deps
    )


@app.get("/health")
async def health():
    return {"status": "ready", "phase": "P1a"}
