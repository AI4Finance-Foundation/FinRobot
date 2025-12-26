"""
Hybrid Caching Utility for FinRobot Data Sources.

Implements a two-tier caching strategy:
1. In-memory LRU cache for instant access within the same session
2. Disk cache with TTL for persistence across sessions

TTL (Time-To-Live) settings:
- SEC 10-K filings: 30 days (annual, rarely change)
- SEC 10-Q filings: 7 days (quarterly)
- YFinance stock info: 1 day (daily changes)
- YFinance financials: 7 days (quarterly updates)
- FMP company profile: 7 days (infrequent changes)
- FMP financial data: 7 days (quarterly updates)
"""

import os
import json
import hashlib
import time
from functools import wraps, lru_cache
from typing import Any, Callable, Optional
from datetime import datetime
import pickle


# Cache configuration
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")

# TTL in seconds
TTL_CONFIG = {
    "sec_10k": 30 * 24 * 60 * 60,      # 30 days for annual filings
    "sec_10q": 7 * 24 * 60 * 60,       # 7 days for quarterly filings
    "sec_metadata": 7 * 24 * 60 * 60,  # 7 days for SEC metadata
    "yfinance_info": 1 * 24 * 60 * 60,   # 1 day for stock info
    "yfinance_financials": 7 * 24 * 60 * 60,  # 7 days for financials
    "yfinance_history": 1 * 24 * 60 * 60,  # 1 day for price history
    "fmp_profile": 7 * 24 * 60 * 60,   # 7 days for company profile
    "fmp_financials": 7 * 24 * 60 * 60,  # 7 days for financial data
    "fmp_quote": 5 * 60,               # 5 minutes for real-time quotes
    "default": 1 * 24 * 60 * 60,       # 1 day default
}


def get_cache_path(category: str, key: str) -> str:
    """Generate cache file path for a given category and key."""
    # Create hash of key for filename
    key_hash = hashlib.md5(key.encode()).hexdigest()
    cache_subdir = os.path.join(CACHE_DIR, category)
    os.makedirs(cache_subdir, exist_ok=True)
    return os.path.join(cache_subdir, f"{key_hash}.cache")


def is_cache_valid(cache_path: str, ttl_seconds: int) -> bool:
    """Check if cache file exists and is not expired."""
    if not os.path.exists(cache_path):
        return False

    file_mtime = os.path.getmtime(cache_path)
    current_time = time.time()

    return (current_time - file_mtime) < ttl_seconds


def read_disk_cache(cache_path: str) -> Optional[Any]:
    """Read data from disk cache."""
    try:
        with open(cache_path, "rb") as f:
            return pickle.load(f)
    except Exception as e:
        print(f"Cache read error: {e}")
        return None


def write_disk_cache(cache_path: str, data: Any) -> bool:
    """Write data to disk cache."""
    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "wb") as f:
            pickle.dump(data, f)
        return True
    except Exception as e:
        print(f"Cache write error: {e}")
        return False


def hybrid_cache(category: str, ttl_key: str = "default", maxsize: int = 128):
    """
    Decorator that implements hybrid caching (memory + disk).

    Args:
        category: Cache category (e.g., 'yfinance', 'fmp', 'sec')
        ttl_key: Key for TTL lookup in TTL_CONFIG
        maxsize: Maximum size for LRU memory cache

    Usage:
        @hybrid_cache("yfinance", "yfinance_financials")
        def get_income_stmt(ticker):
            ...
    """
    def decorator(func: Callable) -> Callable:
        # In-memory LRU cache
        memory_cache = {}

        @wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key from function name and arguments
            cache_key = f"{func.__name__}:{str(args)}:{str(sorted(kwargs.items()))}"

            # 1. Check memory cache first (fastest)
            if cache_key in memory_cache:
                cached_data, cached_time = memory_cache[cache_key]
                ttl = TTL_CONFIG.get(ttl_key, TTL_CONFIG["default"])
                if (time.time() - cached_time) < ttl:
                    return cached_data
                else:
                    # Expired, remove from memory
                    del memory_cache[cache_key]

            # 2. Check disk cache (second fastest)
            disk_path = get_cache_path(category, cache_key)
            ttl = TTL_CONFIG.get(ttl_key, TTL_CONFIG["default"])

            if is_cache_valid(disk_path, ttl):
                data = read_disk_cache(disk_path)
                if data is not None:
                    # Populate memory cache
                    if len(memory_cache) < maxsize:
                        memory_cache[cache_key] = (data, time.time())
                    return data

            # 3. Fetch fresh data from API
            result = func(*args, **kwargs)

            # Store in both caches
            if result is not None:
                # Memory cache
                if len(memory_cache) >= maxsize:
                    # Simple eviction: remove oldest
                    oldest_key = min(memory_cache, key=lambda k: memory_cache[k][1])
                    del memory_cache[oldest_key]
                memory_cache[cache_key] = (result, time.time())

                # Disk cache
                write_disk_cache(disk_path, result)

            return result

        # Attach cache control methods
        wrapper.clear_cache = lambda: memory_cache.clear()
        wrapper.cache_info = lambda: {
            "memory_size": len(memory_cache),
            "category": category,
            "ttl_key": ttl_key
        }

        return wrapper
    return decorator


def clear_all_caches():
    """Clear all disk caches."""
    import shutil
    if os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)
        os.makedirs(CACHE_DIR)
    print(f"Cleared all caches in {CACHE_DIR}")


def clear_category_cache(category: str):
    """Clear disk cache for a specific category."""
    import shutil
    category_path = os.path.join(CACHE_DIR, category)
    if os.path.exists(category_path):
        shutil.rmtree(category_path)
        os.makedirs(category_path)
    print(f"Cleared cache for category: {category}")


def get_cache_stats() -> dict:
    """Get statistics about the current cache."""
    stats = {"categories": {}, "total_size_mb": 0, "total_files": 0}

    if not os.path.exists(CACHE_DIR):
        return stats

    for category in os.listdir(CACHE_DIR):
        category_path = os.path.join(CACHE_DIR, category)
        if os.path.isdir(category_path):
            files = os.listdir(category_path)
            size = sum(
                os.path.getsize(os.path.join(category_path, f))
                for f in files
                if os.path.isfile(os.path.join(category_path, f))
            )
            stats["categories"][category] = {
                "files": len(files),
                "size_mb": round(size / (1024 * 1024), 2)
            }
            stats["total_files"] += len(files)
            stats["total_size_mb"] += size / (1024 * 1024)

    stats["total_size_mb"] = round(stats["total_size_mb"], 2)
    return stats


# Session-level cache for sharing data between agent calls
_session_cache = {}


def session_cache_get(key: str) -> Optional[Any]:
    """Get data from session cache."""
    return _session_cache.get(key)


def session_cache_set(key: str, value: Any):
    """Set data in session cache."""
    _session_cache[key] = value


def session_cache_clear():
    """Clear session cache."""
    _session_cache.clear()


# Convenience decorators for specific data types
def cache_sec_10k(func: Callable) -> Callable:
    """Cache decorator for SEC 10-K data (30 day TTL)."""
    return hybrid_cache("sec", "sec_10k")(func)


def cache_sec_10q(func: Callable) -> Callable:
    """Cache decorator for SEC 10-Q data (7 day TTL)."""
    return hybrid_cache("sec", "sec_10q")(func)


def cache_yfinance_info(func: Callable) -> Callable:
    """Cache decorator for YFinance stock info (1 day TTL)."""
    return hybrid_cache("yfinance", "yfinance_info")(func)


def cache_yfinance_financials(func: Callable) -> Callable:
    """Cache decorator for YFinance financials (7 day TTL)."""
    return hybrid_cache("yfinance", "yfinance_financials")(func)


def cache_fmp_profile(func: Callable) -> Callable:
    """Cache decorator for FMP company profile (7 day TTL)."""
    return hybrid_cache("fmp", "fmp_profile")(func)


def cache_fmp_financials(func: Callable) -> Callable:
    """Cache decorator for FMP financial data (7 day TTL)."""
    return hybrid_cache("fmp", "fmp_financials")(func)


def cache_fmp_quote(func: Callable) -> Callable:
    """Cache decorator for FMP quotes (5 minute TTL)."""
    return hybrid_cache("fmp", "fmp_quote")(func)
