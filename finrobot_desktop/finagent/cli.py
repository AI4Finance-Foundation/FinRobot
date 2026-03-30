import asyncio

import click


def _build_deps(model_name: str):
    from finagent.engine.data.cache import DataCache
    from finagent.engine.data.layer import DataLayer
    from finagent.engine.data.providers.yfinance_provider import YFinanceProvider
    from finagent.engine.deps import FinAgentDeps

    data_layer = DataLayer(providers=[YFinanceProvider()], cache=DataCache())
    return FinAgentDeps(data_layer=data_layer, model_name=model_name)


@click.group()
def cli() -> None:
    """FinAgent — financial AI agent platform."""


@cli.command()
@click.argument("question")
@click.option("--model", default="anthropic:claude-sonnet-4-6", show_default=True)
def run(question: str, model: str) -> None:
    """Ask a quick financial question (Mode A)."""
    from finagent.engine.orchestrator import lead_agent

    deps = _build_deps(model)
    result = lead_agent.run_sync(question, deps=deps)
    click.echo(result.output)


@cli.command()
@click.argument("ticker")
@click.option("--model", default="anthropic:claude-sonnet-4-6", show_default=True)
def research(ticker: str, model: str) -> None:
    """Run equity research pipeline on a ticker (Mode B)."""
    from finagent.engine.orchestrator import lead_agent
    from finagent.engine.pipelines.equity_research import create_equity_research_pipeline

    deps = _build_deps(model)
    pipeline = create_equity_research_pipeline(lead_agent)

    class FakeCtx:
        pass
    fake_ctx = FakeCtx()
    fake_ctx.deps = deps

    async def _run():
        result = await pipeline.execute(fake_ctx, ticker)
        click.echo(result.format_summary())

    asyncio.run(_run())


@cli.command()
@click.option("--port", default=8000, show_default=True)
def serve(port: int) -> None:
    """Start the FinAgent server."""
    import uvicorn
    from finagent.server import app
    uvicorn.run(app, host="0.0.0.0", port=port)
