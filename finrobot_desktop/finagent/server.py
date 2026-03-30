from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from pydantic_ai.ui.vercel_ai import VercelAIAdapter

from finagent.engine.data.cache import DataCache
from finagent.engine.data.layer import DataLayer
from finagent.engine.data.providers.yfinance_provider import YFinanceProvider
from finagent.engine.deps import FinAgentDeps
from finagent.engine.orchestrator import lead_agent

app = FastAPI(title="FinAgent")


def _build_deps() -> FinAgentDeps:
    data_layer = DataLayer(
        providers=[YFinanceProvider()],
        cache=DataCache(),
    )
    return FinAgentDeps(data_layer=data_layer)


@app.post("/chat")
async def chat(request: Request) -> Response:
    deps = _build_deps()
    return await VercelAIAdapter.dispatch_request(request, agent=lead_agent, deps=deps)


@app.get("/health")
async def health():
    return {"status": "ready", "phase": "P0"}
