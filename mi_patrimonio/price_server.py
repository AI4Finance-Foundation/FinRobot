"""
Servidor de Precios en Vivo con OpenBB
API REST para obtener cotizaciones en tiempo real.

Ejecutar con: python price_server.py
El servidor corre en http://localhost:8000
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import json

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
import uvicorn
import re


# ═══════════════════════════════════════════════════════════════════════════════
# INPUT VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════

MAX_TICKERS_PER_REQUEST = 50
TICKER_PATTERN = re.compile(r'^[A-Z0-9._=-]{1,20}$')


def validate_ticker(ticker: str) -> str:
    """Validate a single ticker symbol."""
    ticker = ticker.strip().upper()
    if not ticker:
        raise ValueError("Ticker cannot be empty")
    if len(ticker) > 20:
        raise ValueError(f"Ticker too long: {ticker}")
    if not TICKER_PATTERN.match(ticker):
        raise ValueError(f"Invalid ticker format: {ticker}")
    return ticker


def validate_ticker_list(tickers_str: str) -> list[str]:
    """Parse and validate a comma-separated ticker list."""
    if not tickers_str or not tickers_str.strip():
        raise ValueError("No tickers specified")

    ticker_list = [t.strip().upper() for t in tickers_str.split(",") if t.strip()]

    if not ticker_list:
        raise ValueError("No valid tickers found")

    if len(ticker_list) > MAX_TICKERS_PER_REQUEST:
        raise ValueError(f"Too many tickers ({len(ticker_list)}). Max: {MAX_TICKERS_PER_REQUEST}")

    validated = []
    for ticker in ticker_list:
        validated.append(validate_ticker(ticker))

    return validated

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("PriceServer")

# ═══════════════════════════════════════════════════════════════════════════════
# MAPEO DE TICKERS
# ═══════════════════════════════════════════════════════════════════════════════

# Mapeo de identificadores internos a tickers de Yahoo Finance
TICKER_MAPPING = {
    # ─────────────────────────────────────────────────────────────────────────
    # FONDOS INDEXA CAPITAL (Vanguard Institutional)
    # Nota: Los fondos de Indexa no cotizan públicamente, usamos ETFs equivalentes
    # ─────────────────────────────────────────────────────────────────────────
    'VUSA': 'VUAA.L',           # Vanguard S&P 500 UCITS ETF (USD) Acc
    'VEUR': 'VEUR.AS',          # Vanguard FTSE Developed Europe ETF
    'VFEM': 'VFEM.L',           # Vanguard FTSE Emerging Markets ETF
    'VJPN': 'VJPN.L',           # Vanguard FTSE Japan ETF
    'VPAC': 'VPAC.L',           # Vanguard FTSE Developed Asia Pacific ex Japan
    'VGOV': 'VGOV.L',           # Vanguard EUR Eurozone Government Bond ETF
    'VAGF': 'VAGF.L',           # Vanguard EUR Corporate Bond ETF
    'VGEA': 'VGEA.L',           # Vanguard EUR Eurozone Government Bond
    'VECP': 'VECP.L',           # Vanguard EUR Corporate Bond

    # ─────────────────────────────────────────────────────────────────────────
    # ETFs BANKINTER / MYINVESTOR
    # ─────────────────────────────────────────────────────────────────────────
    'VUAA': 'VUAA.L',           # Vanguard S&P 500 UCITS ETF Acc
    'VOOV': 'VOOV',             # Vanguard S&P 500 Value ETF (US)
    'VOO': 'VOO',               # Vanguard S&P 500 ETF
    'SPY': 'SPY',               # SPDR S&P 500 ETF
    'QQQ': 'QQQ',               # Invesco QQQ (Nasdaq 100)
    'VTI': 'VTI',               # Vanguard Total Stock Market
    'IWDA': 'IWDA.AS',          # iShares Core MSCI World
    'EUNL': 'EUNL.DE',          # iShares Core MSCI World (EUR)
    'CSPX': 'CSPX.L',           # iShares Core S&P 500 (USD) Acc

    # Sectoriales
    'WTEC': 'WTEC.L',           # Lyxor MSCI World Technology
    'SEMI': 'SEMI',             # VanEck Semiconductor ETF
    'SMH': 'SMH',               # VanEck Semiconductor ETF
    'SOXX': 'SOXX',             # iShares Semiconductor ETF
    'BOTZ': 'BOTZ',             # Global X Robotics & AI ETF
    'ARKK': 'ARKK',             # ARK Innovation ETF
    'XLK': 'XLK',               # Technology Select Sector SPDR
    'XLF': 'XLF',               # Financial Select Sector SPDR
    'XLE': 'XLE',               # Energy Select Sector SPDR
    'XLV': 'XLV',               # Health Care Select Sector SPDR

    # Value / Dividendos
    'VTV': 'VTV',               # Vanguard Value ETF
    'SCHD': 'SCHD',             # Schwab US Dividend Equity
    'VYM': 'VYM',               # Vanguard High Dividend Yield
    'DVY': 'DVY',               # iShares Select Dividend

    # Renta Fija
    'BND': 'BND',               # Vanguard Total Bond Market
    'AGG': 'AGG',               # iShares Core US Aggregate Bond
    'TLT': 'TLT',               # iShares 20+ Year Treasury Bond
    'LQD': 'LQD',               # iShares iBoxx Investment Grade Corporate
    'HYG': 'HYG',               # iShares iBoxx High Yield Corporate

    # ─────────────────────────────────────────────────────────────────────────
    # ACCIONES INDIVIDUALES
    # ─────────────────────────────────────────────────────────────────────────
    'NVDA': 'NVDA',
    'AAPL': 'AAPL',
    'MSFT': 'MSFT',
    'GOOGL': 'GOOGL',
    'AMZN': 'AMZN',
    'META': 'META',
    'TSLA': 'TSLA',
    'BRK-B': 'BRK-B',
    'JPM': 'JPM',
    'V': 'V',

    # ─────────────────────────────────────────────────────────────────────────
    # CRIPTO (via Yahoo Finance)
    # ─────────────────────────────────────────────────────────────────────────
    'BTC': 'BTC-EUR',
    'ETH': 'ETH-EUR',
    'BTC-USD': 'BTC-USD',
    'ETH-USD': 'ETH-USD',

    # ─────────────────────────────────────────────────────────────────────────
    # ÍNDICES
    # ─────────────────────────────────────────────────────────────────────────
    '^GSPC': '^GSPC',           # S&P 500
    '^IXIC': '^IXIC',           # Nasdaq Composite
    '^DJI': '^DJI',             # Dow Jones
    '^STOXX50E': '^STOXX50E',   # Euro Stoxx 50
    '^GDAXI': '^GDAXI',         # DAX
    '^IBEX': '^IBEX',           # IBEX 35
}

# Mapeo inverso para nombres legibles
TICKER_NAMES = {
    'VUSA': 'Vanguard US 500 (Indexa)',
    'VEUR': 'Vanguard Europe (Indexa)',
    'VFEM': 'Vanguard Emerging Markets (Indexa)',
    'VUAA': 'Vanguard S&P 500 UCITS',
    'VOOV': 'Vanguard S&P 500 Value',
    'IWDA': 'iShares MSCI World',
    'WTEC': 'Lyxor World Technology',
    'SEMI': 'VanEck Semiconductor',
    'BTC': 'Bitcoin',
    'ETH': 'Ethereum',
}


# ═══════════════════════════════════════════════════════════════════════════════
# PROVEEDOR DE DATOS CON OPENBB
# ═══════════════════════════════════════════════════════════════════════════════

class OpenBBPriceProvider:
    """Proveedor de precios usando OpenBB"""

    def __init__(self):
        self.cache: Dict[str, tuple] = {}
        self.cache_duration = timedelta(minutes=5)
        self.eur_usd_rate = 0.92
        self.obb = None
        self._init_openbb()

    def _init_openbb(self):
        """Inicializa OpenBB"""
        try:
            from openbb import obb
            self.obb = obb
            logger.info("OpenBB inicializado correctamente")
        except ImportError:
            logger.warning("OpenBB no disponible, usando yfinance directamente")
            self.obb = None

    def _get_yahoo_ticker(self, ticker: str) -> str:
        """Convierte ticker interno a ticker de Yahoo Finance"""
        return TICKER_MAPPING.get(ticker, ticker)

    def get_quote(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Obtiene cotización de un activo"""

        # Verificar cache
        cache_key = f"quote_{ticker}"
        if cache_key in self.cache:
            cached_data, cached_time = self.cache[cache_key]
            if datetime.now() - cached_time < self.cache_duration:
                logger.info(f"Cache hit: {ticker}")
                return cached_data

        yahoo_ticker = self._get_yahoo_ticker(ticker)

        try:
            if self.obb:
                return self._get_quote_openbb(ticker, yahoo_ticker)
            else:
                return self._get_quote_yfinance(ticker, yahoo_ticker)
        except Exception as e:
            logger.error(f"Error obteniendo {ticker}: {e}")
            return None

    def _get_quote_openbb(self, original_ticker: str, yahoo_ticker: str) -> Optional[Dict]:
        """Obtiene cotización usando OpenBB"""
        try:
            logger.info(f"OpenBB: Consultando {yahoo_ticker}...")
            quote = self.obb.equity.price.quote(yahoo_ticker, provider='yfinance')

            if quote and len(quote.results) > 0:
                q = quote.results[0]
                precio = getattr(q, 'last_price', None) or getattr(q, 'prev_close', None)

                if precio:
                    # Detectar moneda
                    is_eur = yahoo_ticker.endswith(('.AS', '.DE', '.MC', '.PA', '.L')) or '-EUR' in yahoo_ticker

                    result = {
                        'ticker': original_ticker,
                        'yahoo_ticker': yahoo_ticker,
                        'price': float(precio),
                        'change': float(getattr(q, 'change', 0) or 0),
                        'change_percent': float(getattr(q, 'change_percent', 0) or 0),
                        'currency': 'EUR' if is_eur else 'USD',
                        'name': TICKER_NAMES.get(original_ticker, getattr(q, 'name', original_ticker)),
                        'timestamp': datetime.now().isoformat(),
                        'source': 'openbb'
                    }

                    # Guardar en cache
                    self.cache[f"quote_{original_ticker}"] = (result, datetime.now())
                    logger.info(f"OpenBB: {original_ticker} = {precio:.2f} {result['currency']}")
                    return result

        except Exception as e:
            logger.error(f"OpenBB error para {yahoo_ticker}: {e}")

        return None

    def _get_quote_yfinance(self, original_ticker: str, yahoo_ticker: str) -> Optional[Dict]:
        """Obtiene cotización usando yfinance directamente"""
        try:
            import yfinance as yf

            logger.info(f"yfinance: Consultando {yahoo_ticker}...")
            stock = yf.Ticker(yahoo_ticker)
            info = stock.info

            precio = info.get('regularMarketPrice') or info.get('previousClose')

            if precio:
                is_eur = yahoo_ticker.endswith(('.AS', '.DE', '.MC', '.PA', '.L')) or '-EUR' in yahoo_ticker

                result = {
                    'ticker': original_ticker,
                    'yahoo_ticker': yahoo_ticker,
                    'price': float(precio),
                    'change': float(info.get('regularMarketChange', 0)),
                    'change_percent': float(info.get('regularMarketChangePercent', 0)),
                    'currency': 'EUR' if is_eur else 'USD',
                    'name': TICKER_NAMES.get(original_ticker, info.get('shortName', original_ticker)),
                    'timestamp': datetime.now().isoformat(),
                    'source': 'yfinance'
                }

                self.cache[f"quote_{original_ticker}"] = (result, datetime.now())
                logger.info(f"yfinance: {original_ticker} = {precio:.2f} {result['currency']}")
                return result

        except Exception as e:
            logger.error(f"yfinance error para {yahoo_ticker}: {e}")

        return None

    def get_quotes_batch(self, tickers: List[str]) -> Dict[str, Dict]:
        """Obtiene cotizaciones de múltiples activos"""
        results = {}
        for ticker in tickers:
            quote = self.get_quote(ticker)
            if quote:
                results[ticker] = quote
        return results

    def get_exchange_rate(self) -> float:
        """Obtiene tipo de cambio EUR/USD"""
        try:
            quote = self.get_quote('EURUSD=X')
            if quote and quote.get('price'):
                self.eur_usd_rate = 1 / quote['price']
        except Exception as e:
            logger.warning(f"Error fetching EUR/USD rate: {e}")
        return self.eur_usd_rate

    def clear_cache(self):
        """Limpia el cache"""
        self.cache.clear()
        logger.info("Cache limpiado")


# ═══════════════════════════════════════════════════════════════════════════════
# API REST CON FASTAPI
# ═══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="FinRobot Price Server",
    description="API de precios en vivo usando OpenBB",
    version="1.0.0"
)

# Configurar CORS para permitir llamadas desde el frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Instancia global del proveedor
price_provider = OpenBBPriceProvider()


@app.get("/")
async def root():
    """Health check"""
    return {
        "status": "ok",
        "service": "FinRobot Price Server",
        "timestamp": datetime.now().isoformat(),
        "openbb_available": price_provider.obb is not None
    }


@app.get("/api/prices")
async def get_prices(
    tickers: str = Query(..., description="Comma-separated tickers (e.g., VUSA,VUAA,BTC)")
):
    """
    Get live prices for the specified tickers.

    Example: /api/prices?tickers=VUSA,VUAA,BTC,ETH
    """
    try:
        ticker_list = validate_ticker_list(tickers)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info(f"Requesting prices for: {ticker_list}")

    quotes = price_provider.get_quotes_batch(ticker_list)

    return {
        "prices": quotes,
        "requested": ticker_list,
        "found": list(quotes.keys()),
        "missing": [t for t in ticker_list if t not in quotes],
        "timestamp": datetime.now().isoformat(),
        "eur_usd_rate": price_provider.eur_usd_rate
    }


@app.get("/api/price/{ticker}")
async def get_single_price(ticker: str):
    """
    Get price for a single ticker.

    Example: /api/price/NVDA
    """
    try:
        ticker = validate_ticker(ticker)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    quote = price_provider.get_quote(ticker)

    if not quote:
        raise HTTPException(status_code=404, detail=f"Could not get price for {ticker}")

    return quote


@app.get("/api/exchange-rate")
async def get_exchange_rate():
    """Obtiene tipo de cambio EUR/USD"""
    rate = price_provider.get_exchange_rate()
    return {
        "eur_usd": rate,
        "usd_eur": 1 / rate if rate else None,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/market-summary")
async def get_market_summary():
    """Obtiene resumen de mercado (principales índices)"""
    indices = ['SPY', 'QQQ', 'IWDA', 'BTC', 'ETH']
    quotes = price_provider.get_quotes_batch(indices)

    return {
        "indices": quotes,
        "eur_usd": price_provider.eur_usd_rate,
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/cache/clear")
async def clear_cache():
    """Limpia el cache de precios"""
    price_provider.clear_cache()
    return {"status": "ok", "message": "Cache limpiado"}


@app.get("/api/tickers")
async def list_supported_tickers():
    """Lista todos los tickers soportados con su mapeo"""
    return {
        "tickers": TICKER_MAPPING,
        "names": TICKER_NAMES,
        "count": len(TICKER_MAPPING)
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("""
    ╔═══════════════════════════════════════════════════════════════╗
    ║           FINROBOT PRICE SERVER - OpenBB                      ║
    ║                                                               ║
    ║   API de precios en vivo para el dashboard                    ║
    ║                                                               ║
    ║   Endpoints:                                                  ║
    ║   - GET  /api/prices?tickers=VUSA,BTC,ETH                    ║
    ║   - GET  /api/price/{ticker}                                  ║
    ║   - GET  /api/exchange-rate                                   ║
    ║   - GET  /api/market-summary                                  ║
    ║   - GET  /api/tickers                                         ║
    ║   - POST /api/cache/clear                                     ║
    ║                                                               ║
    ║   Documentación: http://localhost:8000/docs                   ║
    ╚═══════════════════════════════════════════════════════════════╝
    """)

    uvicorn.run(
        "price_server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
