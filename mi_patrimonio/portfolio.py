"""
Portfolio Management and Analysis.

Defines data structures and analysis logic for investment portfolios.
"""
import json
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict

from config import DATA_DIR, ASSET_CATEGORIES, RISK_PROFILES
from data_provider import get_data_provider

logger = logging.getLogger("Portfolio")


@dataclass
class InvestorProfile:
    """Investor profile with risk tolerance and investment objectives."""
    name: str
    age: int
    investment_horizon_years: int
    risk_tolerance: str  # conservative, moderate, aggressive, very_aggressive
    objective: str  # preservation, moderate_growth, aggressive_growth
    monthly_contribution: float = 0
    restrictions: List[str] = field(default_factory=list)  # e.g., ["no_crypto", "no_sell_X"]

    def get_target_allocation(self) -> Dict[str, float]:
        """Get target allocation based on risk profile."""
        profile = RISK_PROFILES.get(self.risk_tolerance, RISK_PROFILES['moderate'])
        return profile['allocation']

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'InvestorProfile':
        return cls(**data)

# Legacy alias for backward compatibility
PerfilInversor = InvestorProfile


@dataclass
class Position:
    """A position in the portfolio."""
    id: str
    name: str
    ticker: Optional[str]
    asset_type: str  # ETF, Stock, Equity Fund, Bond Fund, Mixed Fund, Crypto, Cash
    category: str  # equities, fixed_income, gold, crypto, cash
    current_value: float
    cost_basis: float
    shares: float = 0
    currency: str = 'EUR'
    account: str = ''
    composition: Optional[Dict[str, float]] = None  # For mixed funds: {'equities': 0.25, 'fixed_income': 0.75}

    @property
    def pnl(self) -> float:
        """Profit/Loss in euros."""
        return self.current_value - self.cost_basis

    @property
    def pnl_pct(self) -> float:
        """Profit/Loss in percentage."""
        if self.cost_basis == 0:
            return 0
        return ((self.current_value / self.cost_basis) - 1) * 100

    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'name': self.name,
            'ticker': self.ticker,
            'asset_type': self.asset_type,
            'category': self.category,
            'current_value': self.current_value,
            'cost_basis': self.cost_basis,
            'shares': self.shares,
            'currency': self.currency,
            'account': self.account,
            'composition': self.composition,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'Position':
        return cls(**data)

# Legacy alias for backward compatibility
Posicion = Position


class Portfolio:
    """
    Represents a complete investment portfolio.
    Includes investor profile, positions, and analysis methods.
    """

    def __init__(self, id: str, name: str, profile: InvestorProfile):
        self.id = id
        self.name = name
        self.profile = profile
        self.positions: Dict[str, Position] = {}
        self.data_provider = get_data_provider()
        self.last_updated: Optional[datetime] = None

    def add_position(self, position: Position):
        """Add a position to the portfolio."""
        self.positions[position.id] = position
        logger.info(f"✅ Added position: {position.name} (€{position.current_value:,.0f})")

    def remove_position(self, position_id: str):
        """Remove a position from the portfolio."""
        if position_id in self.positions:
            del self.positions[position_id]
            logger.info(f"🗑️ Removed position: {position_id}")

    def update_prices(self):
        """Update prices for all positions with tickers using OpenBB."""
        logger.info(f"📊 Updating prices for portfolio {self.name}...")

        # Update exchange rate
        self.data_provider.get_exchange_rate()

        for pos_id, pos in self.positions.items():
            if pos.ticker:
                quote = self.data_provider.get_quote(pos.ticker)
                if quote and pos.shares > 0:
                    value = quote.price * pos.shares
                    # Convert to EUR if necessary
                    if quote.currency == 'USD':
                        value = self.data_provider.convert_to_eur(value)
                    pos.current_value = value
                    logger.info(f"  {pos.name}: €{value:,.0f}")

        self.last_updated = datetime.now()

    # Legacy method aliases for backward compatibility
    agregar_posicion = add_position
    eliminar_posicion = remove_position
    actualizar_precios = update_prices
    
    @property
    def total_value(self) -> float:
        """Total portfolio value in EUR."""
        return sum(p.current_value for p in self.positions.values())

    @property
    def total_cost(self) -> float:
        """Total portfolio cost basis in EUR."""
        return sum(p.cost_basis for p in self.positions.values())

    @property
    def total_pnl(self) -> float:
        """Total profit/loss in EUR."""
        return self.total_value - self.total_cost

    @property
    def total_pnl_pct(self) -> float:
        """Total profit/loss in percentage."""
        if self.total_cost == 0:
            return 0
        return ((self.total_value / self.total_cost) - 1) * 100

    # Legacy property aliases for backward compatibility
    @property
    def valor_total(self) -> float:
        return self.total_value

    @property
    def coste_total(self) -> float:
        return self.total_cost

    @property
    def pnl_total(self) -> float:
        return self.total_pnl

    @property
    def pnl_total_pct(self) -> float:
        return self.total_pnl_pct

    def calculate_distribution(self) -> Dict[str, Dict[str, float]]:
        """
        Calculate current distribution by asset class.
        Accounts for composition of mixed funds.

        Returns:
            {
                'equities': {'value': 100000, 'pct': 50.0},
                'fixed_income': {'value': 60000, 'pct': 30.0},
                ...
            }
        """
        total = self.total_value
        if total == 0:
            return {cat: {'value': 0, 'pct': 0} for cat in ASSET_CATEGORIES}

        distribution = {cat: 0.0 for cat in ASSET_CATEGORIES}

        for pos in self.positions.values():
            value = pos.current_value

            # If it has composition (mixed or index fund), split
            if pos.composition:
                for cat, pct in pos.composition.items():
                    # Map legacy keys: 'rv' -> 'equities', 'rf' -> 'fixed_income'
                    cat_full = 'equities' if cat == 'rv' else 'fixed_income' if cat == 'rf' else cat
                    if cat_full in distribution:
                        distribution[cat_full] += value * pct
            else:
                # Assign to category directly
                if pos.category in distribution:
                    distribution[pos.category] += value

        # Calculate percentages
        return {
            cat: {
                'value': value,
                'pct': (value / total * 100) if total > 0 else 0
            }
            for cat, value in distribution.items()
        }

    def calculate_deviations(self) -> Dict[str, Dict[str, float]]:
        """
        Calculate deviations from target allocation.

        Returns:
            {
                'equities': {'actual': 45.0, 'target': 60.0, 'deviation': -15.0},
                ...
            }
        """
        current_distribution = self.calculate_distribution()
        target_allocation = self.profile.get_target_allocation()

        deviations = {}
        for category in ASSET_CATEGORIES:
            actual = current_distribution.get(category, {}).get('pct', 0)
            target = target_allocation.get(category, 0) * 100
            deviations[category] = {
                'actual': actual,
                'target': target,
                'deviation': actual - target,
            }

        return deviations

    def needs_rebalancing(self, threshold_pct: float = 5.0) -> bool:
        """Check if any category is deviated more than the threshold."""
        deviations = self.calculate_deviations()
        for cat, data in deviations.items():
            if abs(data['deviation']) > threshold_pct:
                return True
        return False

    # Legacy method aliases for backward compatibility
    calcular_distribucion = calculate_distribution
    calcular_desviaciones = calculate_deviations
    necesita_rebalanceo = needs_rebalancing
    
    def generate_summary(self) -> Dict[str, Any]:
        """Generate a complete portfolio summary."""
        distribution = self.calculate_distribution()
        deviations = self.calculate_deviations()

        return {
            'id': self.id,
            'name': self.name,
            'date': datetime.now().isoformat(),
            'total_value': self.total_value,
            'total_cost': self.total_cost,
            'pnl': self.total_pnl,
            'pnl_pct': self.total_pnl_pct,
            'num_positions': len(self.positions),
            'distribution': distribution,
            'deviations': deviations,
            'needs_rebalancing': self.needs_rebalancing(),
            'profile': self.profile.to_dict(),
            'positions': {k: v.to_dict() for k, v in self.positions.items()},
            'eur_usd': self.data_provider.eur_usd_rate,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None,
        }

    def save(self):
        """Save the portfolio to a JSON file."""
        filepath = os.path.join(DATA_DIR, f'portfolio_{self.id}.json')
        data = {
            'id': self.id,
            'name': self.name,
            'profile': self.profile.to_dict(),
            'positions': {k: v.to_dict() for k, v in self.positions.items()},
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"💾 Portfolio saved: {filepath}")

    @classmethod
    def load(cls, portfolio_id: str) -> Optional['Portfolio']:
        """Load a portfolio from a JSON file."""
        filepath = os.path.join(DATA_DIR, f'portfolio_{portfolio_id}.json')
        if not os.path.exists(filepath):
            return None

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            profile = InvestorProfile.from_dict(data['profile'])
            portfolio = cls(data['id'], data['name'], profile)

            for pos_data in data.get('positions', {}).values():
                position = Position.from_dict(pos_data)
                portfolio.add_position(position)

            logger.info(f"📂 Portfolio loaded: {portfolio.name}")
            return portfolio

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error(f"❌ Error loading portfolio: {e}")
            return None

    # Legacy method aliases for backward compatibility
    generar_resumen = generate_summary
    guardar = save
    cargar = load


def list_portfolios() -> List[str]:
    """List saved portfolio IDs."""
    portfolios = []
    for f in os.listdir(DATA_DIR):
        if f.startswith('portfolio_') and f.endswith('.json'):
            portfolio_id = f.replace('portfolio_', '').replace('.json', '')
            portfolios.append(portfolio_id)
    return portfolios

# Legacy alias for backward compatibility
listar_portfolios = list_portfolios

