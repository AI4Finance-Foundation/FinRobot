import importlib.util

from .finnhub_utils import FinnHubUtils
from .yfinance_utils import YFinanceUtils
from .fmp_utils import FMPUtils
from .sec_utils import SECUtils
from .reddit_utils import RedditUtils
from .cache_utils import (
    hybrid_cache,
    clear_all_caches,
    clear_category_cache,
    get_cache_stats,
    session_cache_get,
    session_cache_set,
    session_cache_clear,
)


__all__ = ["FinnHubUtils", "YFinanceUtils", "FMPUtils", "SECUtils", "hybrid_cache", "clear_all_caches", "get_cache_stats"]

if importlib.util.find_spec("finnlp") is not None:
    from .finnlp_utils import FinNLPUtils
    __all__.append("FinNLPUtils")
