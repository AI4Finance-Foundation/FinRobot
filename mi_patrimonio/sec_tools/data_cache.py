#!/usr/bin/env python3
"""
Advanced Data Caching and Persistence for Financial MCPs
Implements intelligent caching with TTL and data versioning
"""

import json
import logging
import sqlite3
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
import pickle
import asyncio
from functools import wraps

logger = logging.getLogger(__name__)


class FinancialDataCache:
    """Intelligent caching system for financial data"""
    
    def __init__(self, cache_dir: str = "/tmp/financial_mcp_cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize SQLite for metadata
        self.db_path = self.cache_dir / "cache_metadata.db"
        self._init_database()
        
        # Cache configuration
        self.ttl_config = {
            'price_data': timedelta(minutes=5),
            'financial_statements': timedelta(days=90),
            'news': timedelta(hours=1),
            'analyst_ratings': timedelta(days=7),
            'market_data': timedelta(minutes=15),
            'research_reports': timedelta(days=30),
            'xbrl_data': timedelta(days=90)
        }
    
    def _init_database(self):
        """Initialize cache metadata database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cache_entries (
                cache_key TEXT PRIMARY KEY,
                data_type TEXT,
                ticker TEXT,
                created_at TIMESTAMP,
                expires_at TIMESTAMP,
                access_count INTEGER DEFAULT 0,
                last_accessed TIMESTAMP,
                data_size INTEGER,
                version TEXT
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ticker ON cache_entries(ticker)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_expires ON cache_entries(expires_at)
        """)
        
        conn.commit()
        conn.close()
    
    def _generate_cache_key(self, data_type: str, ticker: str, 
                          params: Optional[Dict] = None) -> str:
        """Generate unique cache key"""
        key_parts = [data_type, ticker]
        
        if params:
            # Sort params for consistent keys
            sorted_params = sorted(params.items())
            key_parts.append(str(sorted_params))
        
        key_string = "|".join(key_parts)
        return hashlib.md5(key_string.encode()).hexdigest()
    
    async def get(self, data_type: str, ticker: str, 
                  params: Optional[Dict] = None) -> Optional[Any]:
        """Retrieve data from cache"""
        cache_key = self._generate_cache_key(data_type, ticker, params)
        
        # Check if entry exists and is valid
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT expires_at, data_size FROM cache_entries 
            WHERE cache_key = ? AND expires_at > ?
        """, (cache_key, datetime.now()))
        
        result = cursor.fetchone()
        
        if result:
            # Update access stats
            cursor.execute("""
                UPDATE cache_entries 
                SET access_count = access_count + 1, 
                    last_accessed = ?
                WHERE cache_key = ?
            """, (datetime.now(), cache_key))
            conn.commit()
            
            # Load cached data
            cache_file = self.cache_dir / f"{cache_key}.pkl"
            if cache_file.exists():
                try:
                    with open(cache_file, 'rb') as f:
                        data = pickle.load(f)
                    conn.close()
                    return data
                except (pickle.UnpicklingError, EOFError, OSError) as e:
                    logger.warning("Cache read error for %s: %s", cache_key, e)
        
        conn.close()
        return None
    
    async def set(self, data_type: str, ticker: str, data: Any,
                  params: Optional[Dict] = None, 
                  custom_ttl: Optional[timedelta] = None):
        """Store data in cache"""
        cache_key = self._generate_cache_key(data_type, ticker, params)
        
        # Determine TTL
        ttl = custom_ttl or self.ttl_config.get(data_type, timedelta(hours=1))
        expires_at = datetime.now() + ttl
        
        # Save data to file
        cache_file = self.cache_dir / f"{cache_key}.pkl"
        try:
            with open(cache_file, 'wb') as f:
                pickle.dump(data, f)
            
            data_size = cache_file.stat().st_size
            
            # Update metadata
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO cache_entries 
                (cache_key, data_type, ticker, created_at, expires_at, 
                 access_count, last_accessed, data_size, version)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)
            """, (cache_key, data_type, ticker, datetime.now(), expires_at,
                  datetime.now(), data_size, "1.0"))
            
            conn.commit()
            conn.close()
            
        except (OSError, sqlite3.Error) as e:
            logger.warning("Cache write error for %s/%s: %s", data_type, ticker, e)

    async def invalidate(self, ticker: Optional[str] = None, 
                        data_type: Optional[str] = None):
        """Invalidate cache entries"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if ticker and data_type:
            cursor.execute("""
                DELETE FROM cache_entries 
                WHERE ticker = ? AND data_type = ?
            """, (ticker, data_type))
        elif ticker:
            cursor.execute("""
                DELETE FROM cache_entries WHERE ticker = ?
            """, (ticker,))
        elif data_type:
            cursor.execute("""
                DELETE FROM cache_entries WHERE data_type = ?
            """, (data_type,))
        
        # Get affected cache keys
        cursor.execute("""
            SELECT cache_key FROM cache_entries 
            WHERE ticker = ? OR data_type = ?
        """, (ticker or '', data_type or ''))
        
        for row in cursor.fetchall():
            cache_file = self.cache_dir / f"{row[0]}.pkl"
            if cache_file.exists():
                cache_file.unlink()
        
        conn.commit()
        conn.close()
    
    async def cleanup_expired(self):
        """Remove expired cache entries"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get expired entries
        cursor.execute("""
            SELECT cache_key FROM cache_entries 
            WHERE expires_at < ?
        """, (datetime.now(),))
        
        expired_keys = cursor.fetchall()
        
        # Delete files
        for key_row in expired_keys:
            cache_file = self.cache_dir / f"{key_row[0]}.pkl"
            if cache_file.exists():
                cache_file.unlink()
        
        # Delete metadata
        cursor.execute("""
            DELETE FROM cache_entries WHERE expires_at < ?
        """, (datetime.now(),))
        
        conn.commit()
        conn.close()
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Overall stats
        cursor.execute("""
            SELECT 
                COUNT(*) as total_entries,
                SUM(data_size) as total_size,
                AVG(access_count) as avg_access_count
            FROM cache_entries
        """)
        
        overall = cursor.fetchone()
        
        # Stats by data type
        cursor.execute("""
            SELECT 
                data_type,
                COUNT(*) as entries,
                SUM(data_size) as size,
                AVG(access_count) as avg_access
            FROM cache_entries
            GROUP BY data_type
        """)
        
        by_type = cursor.fetchall()
        
        # Most accessed
        cursor.execute("""
            SELECT ticker, data_type, access_count
            FROM cache_entries
            ORDER BY access_count DESC
            LIMIT 10
        """)
        
        most_accessed = cursor.fetchall()
        
        conn.close()
        
        return {
            'total_entries': overall[0] or 0,
            'total_size_mb': (overall[1] or 0) / 1024 / 1024,
            'avg_access_count': overall[2] or 0,
            'by_data_type': [
                {
                    'type': row[0],
                    'entries': row[1],
                    'size_mb': row[2] / 1024 / 1024,
                    'avg_access': row[3]
                }
                for row in by_type
            ],
            'most_accessed': [
                {
                    'ticker': row[0],
                    'data_type': row[1],
                    'access_count': row[2]
                }
                for row in most_accessed
            ]
        }


def cache_result(data_type: str, ttl: Optional[timedelta] = None):
    """Decorator for caching function results"""
    def decorator(func):
        @wraps(func)
        async def wrapper(self, ticker: str, *args, **kwargs):
            # Get or create cache instance
            if not hasattr(self, '_cache'):
                self._cache = FinancialDataCache()
            
            # Try to get from cache
            cache_params = {'args': args, 'kwargs': kwargs}
            cached_data = await self._cache.get(data_type, ticker, cache_params)
            
            if cached_data is not None:
                return cached_data
            
            # Call original function
            result = await func(self, ticker, *args, **kwargs)
            
            # Cache the result
            if result and not isinstance(result, dict) or 'error' not in result:
                await self._cache.set(data_type, ticker, result, 
                                    cache_params, custom_ttl=ttl)
            
            return result
        
        return wrapper
    return decorator


class DataVersionManager:
    """Manage data versions for tracking changes"""
    
    def __init__(self, db_path: str = "/tmp/financial_mcp_cache/versions.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize version tracking database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS data_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT,
                data_type TEXT,
                version_hash TEXT,
                created_at TIMESTAMP,
                change_summary TEXT,
                data_snapshot TEXT
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ticker_type 
            ON data_versions(ticker, data_type)
        """)
        
        conn.commit()
        conn.close()
    
    def track_version(self, ticker: str, data_type: str, 
                     data: Any, change_summary: Optional[str] = None):
        """Track a new version of data"""
        # Generate hash of data
        data_str = json.dumps(data, sort_keys=True)
        version_hash = hashlib.sha256(data_str.encode()).hexdigest()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check if this version already exists
        cursor.execute("""
            SELECT id FROM data_versions 
            WHERE ticker = ? AND data_type = ? AND version_hash = ?
            ORDER BY created_at DESC LIMIT 1
        """, (ticker, data_type, version_hash))
        
        if not cursor.fetchone():
            # New version - store it
            cursor.execute("""
                INSERT INTO data_versions 
                (ticker, data_type, version_hash, created_at, 
                 change_summary, data_snapshot)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (ticker, data_type, version_hash, datetime.now(),
                  change_summary, data_str[:1000]))  # Store partial snapshot
            
            conn.commit()
        
        conn.close()
    
    def get_version_history(self, ticker: str, data_type: str, 
                          limit: int = 10) -> List[Dict[str, Any]]:
        """Get version history for a ticker/data_type"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT version_hash, created_at, change_summary
            FROM data_versions
            WHERE ticker = ? AND data_type = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (ticker, data_type, limit))
        
        history = [
            {
                'version_hash': row[0],
                'created_at': row[1],
                'change_summary': row[2]
            }
            for row in cursor.fetchall()
        ]
        
        conn.close()
        return history
    
    def detect_significant_changes(self, ticker: str, data_type: str,
                                 old_data: Dict, new_data: Dict) -> List[str]:
        """Detect significant changes between data versions"""
        changes = []
        
        # For financial data, check key metrics
        if data_type == 'financial_statements':
            metrics_to_check = ['revenue', 'net_income', 'eps', 'total_assets']
            for metric in metrics_to_check:
                if metric in old_data and metric in new_data:
                    old_val = old_data[metric]
                    new_val = new_data[metric]
                    if old_val and new_val and abs((new_val - old_val) / old_val) > 0.05:
                        change_pct = (new_val - old_val) / old_val * 100
                        changes.append(f"{metric} changed by {change_pct:.1f}%")
        
        elif data_type == 'analyst_ratings':
            if old_data.get('consensus') != new_data.get('consensus'):
                changes.append(f"Consensus changed from {old_data.get('consensus')} to {new_data.get('consensus')}")
        
        return changes