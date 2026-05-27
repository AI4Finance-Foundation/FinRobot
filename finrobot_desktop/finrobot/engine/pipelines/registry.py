"""Pipeline factory registry.

Extracted from server.py (Fix 4.4) to break the circular import:
  server → web → tasks → server

Now both server.py and tasks.py import from this module instead.
"""

from __future__ import annotations

from typing import Any, Callable

# Lazy-loaded pipeline factory map. Each factory takes a sub_agents dict and
# returns a Pipeline. Populated on first call, then cached.
_PIPELINE_FACTORIES: dict[str, Callable[..., Any]] | None = None


def get_pipeline_factories() -> dict[str, Callable[..., Any]]:
    """Return the pipeline factory map, importing lazily on first call."""
    global _PIPELINE_FACTORIES
    if _PIPELINE_FACTORIES is not None:
        return _PIPELINE_FACTORIES
    from finrobot.engine.pipelines.comps import create_comps_pipeline
    from finrobot.engine.pipelines.dcf import create_dcf_pipeline
    from finrobot.engine.pipelines.ddm import create_ddm_pipeline
    from finrobot.engine.pipelines.earnings_analysis import (
        create_earnings_analysis_pipeline,
    )
    from finrobot.engine.pipelines.equity_research import (
        create_equity_research_pipeline,
    )
    from finrobot.engine.pipelines.ic_memo import create_ic_memo_pipeline
    from finrobot.engine.pipelines.lbo import create_lbo_pipeline

    _PIPELINE_FACTORIES = {
        "research": create_equity_research_pipeline,
        "comps": create_comps_pipeline,
        "dcf": create_dcf_pipeline,
        "ddm": create_ddm_pipeline,
        "lbo": create_lbo_pipeline,
        "earnings": create_earnings_analysis_pipeline,
        "ic-memo": create_ic_memo_pipeline,
    }
    return _PIPELINE_FACTORIES
