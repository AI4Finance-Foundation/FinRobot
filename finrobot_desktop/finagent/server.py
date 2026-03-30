from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from pydantic_ai.ui.vercel_ai import VercelAIAdapter

from finagent.config import get_settings
from finagent.engine.data.cache import DataCache
from finagent.engine.data.layer import DataLayer
from finagent.engine.data.providers.yfinance_provider import YFinanceProvider
from finagent.engine.deps import FinAgentDeps
from finagent.engine.orchestrator import lead_agent

# Apply API keys from .env before any Agent is used
get_settings().apply_api_keys()

app = FastAPI(title="FinAgent")


def _build_deps() -> FinAgentDeps:
    settings = get_settings()
    data_layer = DataLayer(
        providers=[YFinanceProvider()],
        cache=DataCache(settings.cache_db_path),
    )
    return FinAgentDeps(data_layer=data_layer, settings=settings)


@app.post("/chat")
async def chat(request: Request) -> Response:
    deps = _build_deps()
    return await VercelAIAdapter.dispatch_request(request, agent=lead_agent, deps=deps)


@app.get("/health")
async def health():
    return {"status": "ready", "phase": "P0"}
