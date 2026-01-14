import { NextResponse } from 'next/server'
import { TickerListSchema, ManualPriceUpdateSchema, validateRequest } from '@/lib/validation'

// Interfaces for API responses
interface YahooFinanceQuote {
  symbol: string
  regularMarketPrice: number
  regularMarketChange: number
  regularMarketChangePercent: number
}

interface CoinGeckoPrice {
  [key: string]: {
    eur: number
    eur_24h_change: number
  }
}

// GET - Get current prices for all assets
export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url)
    const tickersParam = searchParams.get('tickers') ?? ''

    // Validate tickers
    const validation = validateRequest(TickerListSchema, tickersParam)
    if (!validation.success) {
      return NextResponse.json(
        { error: validation.error },
        { status: 400 }
      )
    }
    const tickers = validation.data

    const prices: Record<string, any> = {}

    // Separar tickers por tipo
    const etfTickers: string[] = []
    const cryptoTickers: string[] = []

    tickers.forEach(ticker => {
      if (ticker === 'BTC' || ticker === 'ETH') {
        cryptoTickers.push(ticker)
      } else {
        etfTickers.push(ticker)
      }
    })

    // Obtener precios de ETFs/Fondos (Yahoo Finance)
    if (etfTickers.length > 0) {
      const etfPrices = await fetchYahooFinancePrices(etfTickers)
      Object.assign(prices, etfPrices)
    }

    // Obtener precios de Cripto (CoinGecko)
    if (cryptoTickers.length > 0) {
      const cryptoPrices = await fetchCoinGeckoPrices(cryptoTickers)
      Object.assign(prices, cryptoPrices)
    }

    return NextResponse.json({
      prices,
      timestamp: new Date().toISOString()
    })

  } catch (error) {
    console.error('Error fetching prices:', error)
    const message = error instanceof Error ? error.message : 'Unknown error'
    return NextResponse.json(
      { error: 'Error fetching prices', details: message },
      { status: 500 }
    )
  }
}

// Función para obtener precios de Yahoo Finance
async function fetchYahooFinancePrices(tickers: string[]): Promise<Record<string, any>> {
  const prices: Record<string, any> = {}

  // Yahoo Finance API (usando query1.finance.yahoo.com - endpoint público)
  // Nota: Para producción, considerar usar una API key de un servicio como Alpha Vantage

  for (const ticker of tickers) {
    try {
      // Agregar sufijo .L para ETFs europeos, .MC para españoles, etc.
      const yahooTicker = formatTickerForYahoo(ticker)

      const url = `https://query1.finance.yahoo.com/v8/finance/chart/${yahooTicker}?interval=1d&range=1d`

      const response = await fetch(url, {
        headers: {
          'User-Agent': 'Mozilla/5.0'
        }
      })

      if (!response.ok) {
        console.warn(`Yahoo Finance error for ${ticker}: ${response.statusText}`)
        prices[ticker] = {
          price: null,
          error: 'No disponible'
        }
        continue
      }

      const data = await response.json()
      const quote = data?.chart?.result?.[0]?.meta

      if (quote) {
        prices[ticker] = {
          price: quote.regularMarketPrice || quote.previousClose,
          change: quote.regularMarketPrice - quote.chartPreviousClose,
          changePercent: ((quote.regularMarketPrice - quote.chartPreviousClose) / quote.chartPreviousClose) * 100,
          currency: quote.currency || 'EUR',
          lastUpdate: new Date(quote.regularMarketTime * 1000).toISOString()
        }
      } else {
        prices[ticker] = {
          price: null,
          error: 'Sin datos'
        }
      }
    } catch (error) {
      console.error(`Error fetching ${ticker}:`, error)
      prices[ticker] = {
        price: null,
        error: 'Error de red'
      }
    }

    // Rate limiting
    await new Promise(resolve => setTimeout(resolve, 200))
  }

  return prices
}

// Función para obtener precios de Cripto (CoinGecko)
async function fetchCoinGeckoPrices(tickers: string[]): Promise<Record<string, any>> {
  const prices: Record<string, any> = {}

  try {
    // Mapear tickers a IDs de CoinGecko
    const coinIds = tickers.map(ticker => {
      if (ticker === 'BTC') return 'bitcoin'
      if (ticker === 'ETH') return 'ethereum'
      return ticker.toLowerCase()
    })

    const idsParam = coinIds.join(',')
    const url = `https://api.coingecko.com/api/v3/simple/price?ids=${idsParam}&vs_currencies=eur&include_24hr_change=true`

    const response = await fetch(url, {
      headers: {
        'Accept': 'application/json'
      }
    })

    if (!response.ok) {
      throw new Error(`CoinGecko API error: ${response.statusText}`)
    }

    const data: CoinGeckoPrice = await response.json()

    tickers.forEach((ticker, index) => {
      const coinId = coinIds[index]
      const coinData = data[coinId]

      if (coinData) {
        prices[ticker] = {
          price: coinData.eur,
          change24h: coinData.eur_24h_change,
          changePercent: coinData.eur_24h_change,
          currency: 'EUR',
          lastUpdate: new Date().toISOString()
        }
      } else {
        prices[ticker] = {
          price: null,
          error: 'Sin datos'
        }
      }
    })

  } catch (error) {
    console.error('Error fetching crypto prices:', error)
    tickers.forEach(ticker => {
      prices[ticker] = {
        price: null,
        error: 'Error CoinGecko'
      }
    })
  }

  return prices
}

// Helper para formatear tickers para Yahoo Finance
function formatTickerForYahoo(ticker: string): string {
  // Mapeo de tickers a formato Yahoo
  const mapping: Record<string, string> = {
    'EXXY': 'EXXY.DE', // iShares STOXX Europe 600 Basic Resources
    'ICOM': 'ICOM.L',  // iShares Diversified Commodity
    '2B76': '2B76.L',  // iShares MSCI Europe Basic Resources
    'NUKL': 'NUKL.L',  // VanEck Uranium
    'XRS2': 'XRS2.L',  // iShares Russell 2000
    'EXXV': 'EXXV.DE', // iShares Core MSCI World
    'EXXB': 'CSPX.L',  // iShares Core S&P 500
    // Vanguard Indexa (estos son más difíciles, puede requerir scraping de Indexa)
    'VUSA': 'VUAA.L',  // Vanguard S&P 500
    'VEUR': 'VEUR.AS', // Vanguard European Stock
    'VFEM': 'VFEM.L',  // Vanguard Emerging Markets
  }

  return mapping[ticker] || ticker
}

// POST - Endpoint to update prices manually
export async function POST(request: Request) {
  try {
    const body = await request.json()

    const validation = validateRequest(ManualPriceUpdateSchema, body)
    if (!validation.success) {
      return NextResponse.json(
        { error: validation.error },
        { status: 400 }
      )
    }

    const { ticker, price } = validation.data

    // Could save price to KV for historical tracking
    return NextResponse.json({
      success: true,
      ticker,
      price,
      timestamp: new Date().toISOString()
    })

  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    return NextResponse.json(
      { error: 'Error updating price', details: message },
      { status: 500 }
    )
  }
}
