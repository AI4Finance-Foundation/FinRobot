"""
Central Configuration for the Portfolio Management System.

This module provides configuration for risk profiles, asset categories,
and recommended ETFs for the family portfolio tracking system.
"""
import os
import json
from typing import Dict, Any, Optional

# ═══════════════════════════════════════════════════════════════════════════════
# PATHS
# ═══════════════════════════════════════════════════════════════════════════════
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')
FINROBOT_DIR = os.path.dirname(BASE_DIR)  # ~/Desktop/FinRobot

# Create directories if they don't exist
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

# ═══════════════════════════════════════════════════════════════════════════════
# API KEYS
# ═══════════════════════════════════════════════════════════════════════════════
def get_openai_api_key() -> Optional[str]:
    """Get OpenAI API key from configuration file."""
    config_path = os.path.join(FINROBOT_DIR, "OAI_CONFIG_LIST")
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        return config[0]['api_key']
    except (FileNotFoundError, json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"⚠️ Error reading API key: {e}")
        return None

# ═══════════════════════════════════════════════════════════════════════════════
# RISK PROFILES
# ═══════════════════════════════════════════════════════════════════════════════
RISK_PROFILES: Dict[str, Dict[str, Any]] = {
    'conservative': {
        'name': 'Conservative',
        'description': 'Prioritizes capital preservation with moderate growth',
        'allocation': {
            'equities': 0.30,
            'fixed_income': 0.50,
            'gold': 0.10,
            'crypto': 0.00,
            'cash': 0.10,
        },
        'max_volatility': 10,
    },
    'moderate': {
        'name': 'Moderate',
        'description': 'Balance between growth and protection',
        'allocation': {
            'equities': 0.50,
            'fixed_income': 0.30,
            'gold': 0.08,
            'crypto': 0.02,
            'cash': 0.10,
        },
        'max_volatility': 15,
    },
    'aggressive': {
        'name': 'Aggressive',
        'description': 'Maximizes growth accepting higher volatility',
        'allocation': {
            'equities': 0.70,
            'fixed_income': 0.15,
            'gold': 0.05,
            'crypto': 0.05,
            'cash': 0.05,
        },
        'max_volatility': 25,
    },
    'very_aggressive': {
        'name': 'Very Aggressive',
        'description': 'Maximum exposure to high-growth assets',
        'allocation': {
            'equities': 0.75,
            'fixed_income': 0.05,
            'gold': 0.05,
            'crypto': 0.10,
            'cash': 0.05,
        },
        'max_volatility': 35,
    },
}

# Legacy alias for backward compatibility
PERFILES_RIESGO = RISK_PROFILES

# ═══════════════════════════════════════════════════════════════════════════════
# ASSET CATEGORIES
# ═══════════════════════════════════════════════════════════════════════════════
ASSET_CATEGORIES: Dict[str, Dict[str, Any]] = {
    'equities': {
        'name': 'Equities',
        'color': '#3B82F6',  # Blue
        'emoji': '📈',
        'types': ['ETF', 'Stock', 'Equity Fund', 'Index Fund'],
    },
    'fixed_income': {
        'name': 'Fixed Income',
        'color': '#10B981',  # Green
        'emoji': '🏦',
        'types': ['Bond Fund', 'Bond', 'T-Bill'],
    },
    'gold': {
        'name': 'Gold',
        'color': '#F59E0B',  # Yellow
        'emoji': '🥇',
        'types': ['Gold ETF', 'Physical Gold'],
    },
    'crypto': {
        'name': 'Cryptocurrency',
        'color': '#8B5CF6',  # Purple
        'emoji': '₿',
        'types': ['Bitcoin', 'Ethereum', 'Altcoin'],
    },
    'cash': {
        'name': 'Cash',
        'color': '#6B7280',  # Gray
        'emoji': '💵',
        'types': ['Cash', 'Checking Account', 'Deposit'],
    },
}

# Legacy alias for backward compatibility
CATEGORIAS_ACTIVOS = ASSET_CATEGORIES

# ═══════════════════════════════════════════════════════════════════════════════
# RECOMMENDED ETFs BY CATEGORY
# ═══════════════════════════════════════════════════════════════════════════════
RECOMMENDED_ETFS: Dict[str, list] = {
    'equities': [
        {'ticker': 'IWDA.AS', 'name': 'iShares MSCI World', 'description': 'Global Developed Equities', 'ter': 0.20},
        {'ticker': 'EIMI.AS', 'name': 'iShares Core EM IMI', 'description': 'Emerging Markets Equities', 'ter': 0.18},
        {'ticker': 'CSPX.AS', 'name': 'iShares Core S&P 500', 'description': 'USA Large Cap', 'ter': 0.07},
        {'ticker': 'QQQ', 'name': 'Invesco QQQ', 'description': 'Nasdaq 100 Tech', 'ter': 0.20},
        {'ticker': 'IWM', 'name': 'iShares Russell 2000', 'description': 'USA Small Cap', 'ter': 0.19},
        {'ticker': 'INDA', 'name': 'iShares MSCI India', 'description': 'India Equities', 'ter': 0.64},
    ],
    'fixed_income': [
        {'ticker': 'VGEA.DE', 'name': 'Vanguard EUR Gov Bond', 'description': 'Eurozone Government Bonds', 'ter': 0.07},
        {'ticker': 'IEAC.AS', 'name': 'iShares Core EUR Corp', 'description': 'Euro Corporate Bonds', 'ter': 0.20},
        {'ticker': 'AGGH.AS', 'name': 'iShares Global Aggregate', 'description': 'Global Fixed Income', 'ter': 0.10},
    ],
    'gold': [
        {'ticker': 'SGLD.AS', 'name': 'Invesco Physical Gold', 'description': 'Physical Gold', 'ter': 0.12},
        {'ticker': 'GLD', 'name': 'SPDR Gold Shares', 'description': 'Physical Gold USA', 'ter': 0.40},
    ],
    'crypto': [
        {'ticker': 'BTC-USD', 'name': 'Bitcoin', 'description': 'Primary Cryptocurrency', 'ter': 0},
        {'ticker': 'ETH-USD', 'name': 'Ethereum', 'description': 'Smart Contracts Platform', 'ter': 0},
    ],
}

# Legacy alias for backward compatibility
ETFS_RECOMENDADOS = RECOMMENDED_ETFS

