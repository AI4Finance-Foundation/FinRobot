import { NextResponse } from 'next/server'

// Forzar que esta ruta sea dinámica (no pre-renderizada)
export const dynamic = 'force-dynamic'
export const revalidate = 0

// Mapeo de tickers/ISINs a símbolos de Yahoo Finance
// Fondos sin cotización directa se omiten del mapeo
const YAHOO_SYMBOL_MAP: Record<string, string> = {
  // Tickers directos que funcionan en Yahoo
  'BRK.B': 'BRK-B',
  'LLY': 'LLY',
  'CEG': 'CEG',
  'GEV': 'GEV',

  // ETFs europeos
  'CSPX': 'CSPX.L',      // iShares Core S&P 500 (London)
  'EXXY': 'EXXY.DE',     // iShares Diversified Commodity
  'IS3V': 'IGIL.L',      // iShares Global Inflation Linked (proxy)
  'IS0E': 'IAUP.L',      // iShares Gold Producers (proxy)
  'GLDM': 'GDX',         // Gold Miners ETF (proxy)

  // Vanguard Indexa - usando proxies ETF
  'VUSA': 'VUAA.L',      // Vanguard S&P 500
  'VEUR': 'VEUR.AS',     // Vanguard European
  'VFEM': 'VFEM.L',      // Vanguard Emerging

  // Crypto
  'BTC': 'BTC-EUR',
  'ETH': 'ETH-EUR'
}

// Tickers que NO tienen cotización Yahoo (fondos, etc.)
const NO_YAHOO_TICKERS = ['MYSP500', 'WFECTR', 'CRYPTO', 'CASH', 'VWSC', 'VJPN', 'VPAC', 'VGOV', 'VCEB', 'VUSC', 'VINF', 'IEAG', 'VGAB']

// Posiciones con TODAS las fechas de compra correctas
const PORTFOLIO_POSITIONS = [
  // ═══════════════════════════════════════════════════════════════
  // INDEXA CAPITAL - Comprados en 2020 (antes de 2026)
  // ═══════════════════════════════════════════════════════════════
  { id: 'indexa_us500', ticker: 'VUSA', shares: 110.0, avgCost: 524.40, totalCost: 57684, fechaCompra: '2020-01-01', currency: 'EUR' },
  { id: 'indexa_europe', ticker: 'VEUR', shares: 129.7, avgCost: 266.81, totalCost: 34605, fechaCompra: '2020-01-01', currency: 'EUR' },
  { id: 'indexa_em', ticker: 'VFEM', shares: 62.0, avgCost: 224.17, totalCost: 13899, fechaCompra: '2020-01-01', currency: 'EUR' },
  { id: 'indexa_smallcap', ticker: 'VWSC', shares: 42.2, avgCost: 313.23, totalCost: 13218, fechaCompra: '2020-01-01', currency: 'EUR' },
  { id: 'indexa_japan', ticker: 'VJPN', shares: 41.5, avgCost: 273.10, totalCost: 11334, fechaCompra: '2020-01-01', currency: 'EUR' },
  { id: 'indexa_pacific', ticker: 'VPAC', shares: 22.3, avgCost: 215.05, totalCost: 4796, fechaCompra: '2020-01-01', currency: 'EUR' },
  // RF Indexa
  { id: 'indexa_goveur', ticker: 'VGOV', shares: 356.72, avgCost: 107.60, totalCost: 38383, fechaCompra: '2020-01-01', currency: 'EUR' },
  { id: 'indexa_corpeur', ticker: 'VCEB', shares: 82.79, avgCost: 115.21, totalCost: 9539, fechaCompra: '2020-01-01', currency: 'EUR' },
  { id: 'indexa_corpusd', ticker: 'VUSC', shares: 113.6, avgCost: 110.20, totalCost: 12519, fechaCompra: '2020-01-01', currency: 'EUR' },
  { id: 'indexa_inflation', ticker: 'VINF', shares: 64.4, avgCost: 130.36, totalCost: 8395, fechaCompra: '2020-01-01', currency: 'EUR' },
  { id: 'indexa_emgov', ticker: 'IEAG', shares: 368.0, avgCost: 11.60, totalCost: 4269, fechaCompra: '2020-01-01', currency: 'EUR' },
  { id: 'indexa_global', ticker: 'VGAB', shares: 110.86, avgCost: 100.28, totalCost: 11117, fechaCompra: '2020-01-01', currency: 'EUR' },

  // ═══════════════════════════════════════════════════════════════
  // ANDBANK - Varias fechas
  // ═══════════════════════════════════════════════════════════════
  { id: 'andbank_wf', ticker: 'WFECTR', shares: 1135.71, avgCost: 141.58, totalCost: 160794, fechaCompra: '2022-01-01', currency: 'EUR' },
  { id: 'andbank_myinvestor', ticker: 'MYSP500', shares: 41433.24, avgCost: 1.207, totalCost: 50000, fechaCompra: '2024-01-01', currency: 'EUR' },
  // Comprados HOY (14 Enero 2026)
  { id: 'andbank_lly', ticker: 'LLY', shares: 22, avgCost: 925.50, totalCost: 20361, fechaCompra: '2026-01-14', currency: 'USD' },
  { id: 'andbank_ceg', ticker: 'CEG', shares: 71, avgCost: 330.94, totalCost: 23496, fechaCompra: '2026-01-14', currency: 'USD' },
  { id: 'andbank_gev', ticker: 'GEV', shares: 19, avgCost: 651.31, totalCost: 12375, fechaCompra: '2026-01-14', currency: 'USD' },
  { id: 'andbank_cspx', ticker: 'CSPX', shares: 100, avgCost: 637.45, totalCost: 63745, fechaCompra: '2026-01-14', currency: 'EUR' },
  { id: 'andbank_ihe', ticker: 'IHE', shares: 2000, avgCost: 10.854, totalCost: 21708, fechaCompra: '2026-01-14', currency: 'EUR' },
  { id: 'andbank_dfen', ticker: 'DFEN', shares: 200, avgCost: 62.40, totalCost: 12480, fechaCompra: '2026-01-14', currency: 'EUR' },

  // ═══════════════════════════════════════════════════════════════
  // BANKINTER - Diferentes fechas
  // ═══════════════════════════════════════════════════════════════
  // Comprados en 2024 (antes de 2026)
  { id: 'bankinter_brkb', ticker: 'BRK.B', shares: 20, avgCost: 470.60, totalCost: 9412, fechaCompra: '2024-12-09', currency: 'USD' },
  { id: 'bankinter_gldm', ticker: 'GLDM', shares: 400, avgCost: 28.00, totalCost: 11200, fechaCompra: '2024-12-09', currency: 'EUR' },
  // Comprados el 5 Enero 2026
  { id: 'bankinter_exxy', ticker: 'EXXY', shares: 120, avgCost: 27.26, totalCost: 3271, fechaCompra: '2026-01-05', currency: 'EUR' },
  { id: 'bankinter_is3v', ticker: 'IS3V', shares: 2208, avgCost: 4.53, totalCost: 10002, fechaCompra: '2026-01-05', currency: 'EUR' },
  { id: 'bankinter_is0e', ticker: 'IS0E', shares: 270, avgCost: 34.345, totalCost: 9273, fechaCompra: '2026-01-05', currency: 'EUR' },
  { id: 'bankinter_nukl', ticker: 'NUKL', shares: 100, avgCost: 49.97, totalCost: 4997, fechaCompra: '2026-01-05', currency: 'EUR' },

  // ═══════════════════════════════════════════════════════════════
  // CRIPTO Y LIQUIDEZ
  // ═══════════════════════════════════════════════════════════════
  { id: 'cripto_gdaf', ticker: 'CRYPTO', shares: 1, avgCost: 205000, totalCost: 205000, currentValue: 97321, fechaCompra: '2023-04-01', currency: 'EUR' },
  { id: 'liquidez', ticker: 'CASH', shares: 1, avgCost: 188732, totalCost: 188732, currentValue: 188732, fechaCompra: '2020-01-01', currency: 'EUR' }
]

// Obtener precio histórico de Yahoo Finance
async function getHistoricalPrice(symbol: string, date: string): Promise<number | null> {
  try {
    const targetDate = new Date(date)
    const period1 = Math.floor(targetDate.getTime() / 1000)
    const period2 = period1 + 86400 * 7 // 7 días para asegurar datos

    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?period1=${period1}&period2=${period2}&interval=1d`

    const response = await fetch(url, {
      headers: { 'User-Agent': 'Mozilla/5.0' }
    })

    if (!response.ok) return null

    const data = await response.json()
    const result = data?.chart?.result?.[0]

    if (result?.indicators?.quote?.[0]?.close) {
      const closes = result.indicators.quote[0].close
      for (const close of closes) {
        if (close !== null) return close
      }
    }
    return null
  } catch {
    return null
  }
}

// Obtener precio actual
async function getCurrentPrice(symbol: string): Promise<number | null> {
  try {
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?interval=1d&range=1d`
    const response = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0' } })
    if (!response.ok) return null
    const data = await response.json()
    return data?.chart?.result?.[0]?.meta?.regularMarketPrice || null
  } catch {
    return null
  }
}

// GET - Calcular métricas históricas CON LÓGICA DE FECHAS CORRECTA
export async function GET() {
  const EUR_USD_RATE = 0.92

  try {
    const today = new Date()
    const todayStr = today.toISOString().split('T')[0]
    const ytdBaseDate = '2026-01-02' // 2 Enero (mercados cerrados 1 Enero)

    // Fecha de ayer
    const yesterday = new Date(today)
    yesterday.setDate(yesterday.getDate() - 1)
    // Si ayer fue fin de semana, retroceder al viernes
    while (yesterday.getDay() === 0 || yesterday.getDay() === 6) {
      yesterday.setDate(yesterday.getDate() - 1)
    }
    const yesterdayStr = yesterday.toISOString().split('T')[0]

    let ytdStartValue = 0  // Valor base para calcular YTD
    let yesterdayValue = 0 // Valor de ayer
    let currentValue = 0   // Valor actual
    let totalCost = 0      // Coste total de compra

    const details: any[] = []

    for (const position of PORTFOLIO_POSITIONS) {
      const purchaseDate = new Date(position.fechaCompra)
      const purchaseDateStr = position.fechaCompra
      const ytdBase = new Date(ytdBaseDate)

      // Determinar si el activo existía antes del 1 Enero 2026
      const existedBeforeYTD = purchaseDate < ytdBase
      const existedYesterday = purchaseDate <= yesterday

      // Obtener símbolo de Yahoo (si existe)
      const yahooSymbol = NO_YAHOO_TICKERS.includes(position.ticker) ? null : YAHOO_SYMBOL_MAP[position.ticker]

      // Precio actual
      let currentPrice = (position as any).currentValue || position.avgCost * position.shares
      if (yahooSymbol) {
        const livePrice = await getCurrentPrice(yahooSymbol)
        if (livePrice) {
          currentPrice = position.currency === 'USD'
            ? livePrice * EUR_USD_RATE * position.shares
            : livePrice * position.shares
        }
      } else if (position.ticker === 'CASH') {
        currentPrice = 188732
      } else if (position.ticker === 'CRYPTO') {
        currentPrice = 97321
      } else {
        // Fondos sin cotización: usar valor actual conocido o coste
        currentPrice = (position as any).currentValue || position.totalCost
      }

      // ═══════════════════════════════════════════════════════════════
      // LÓGICA YTD CORRECTA
      // ═══════════════════════════════════════════════════════════════
      let ytdBaseValue: number

      if (!existedBeforeYTD) {
        // Comprado EN 2026 -> YTD base = precio de compra
        ytdBaseValue = position.totalCost
      } else {
        // Comprado ANTES de 2026 -> YTD base = valor a 1 Enero 2026
        if (yahooSymbol) {
          const jan1Price = await getHistoricalPrice(yahooSymbol, ytdBaseDate)
          if (jan1Price) {
            ytdBaseValue = position.currency === 'USD'
              ? jan1Price * EUR_USD_RATE * position.shares
              : jan1Price * position.shares
          } else {
            // Fallback: usar coste como aproximación
            ytdBaseValue = position.totalCost
          }
        } else {
          // Sin cotización Yahoo: aproximar con coste
          ytdBaseValue = position.totalCost
        }
      }

      // ═══════════════════════════════════════════════════════════════
      // LÓGICA AYER CORRECTA
      // ═══════════════════════════════════════════════════════════════
      let yesterdayBaseValue: number

      if (!existedYesterday) {
        // Comprado HOY -> ayer no existía, usar precio de compra
        yesterdayBaseValue = position.totalCost
      } else {
        // Existía ayer -> obtener precio de ayer
        if (yahooSymbol) {
          const yestPrice = await getHistoricalPrice(yahooSymbol, yesterdayStr)
          if (yestPrice) {
            yesterdayBaseValue = position.currency === 'USD'
              ? yestPrice * EUR_USD_RATE * position.shares
              : yestPrice * position.shares
          } else {
            yesterdayBaseValue = position.totalCost
          }
        } else {
          yesterdayBaseValue = position.totalCost
        }
      }

      // Acumular totales
      ytdStartValue += ytdBaseValue
      yesterdayValue += yesterdayBaseValue
      currentValue += currentPrice
      totalCost += position.totalCost

      details.push({
        id: position.id,
        ticker: position.ticker,
        fechaCompra: purchaseDateStr,
        existedBeforeYTD,
        ytdBaseValue: ytdBaseValue.toFixed(2),
        yesterdayValue: yesterdayBaseValue.toFixed(2),
        currentValue: currentPrice.toFixed(2),
        totalCost: position.totalCost
      })

      // Rate limiting
      await new Promise(resolve => setTimeout(resolve, 50))
    }

    // Calcular métricas finales
    const ytdReturn = currentValue - ytdStartValue
    const ytdReturnPct = ytdStartValue > 0 ? (ytdReturn / ytdStartValue) * 100 : 0

    const dailyReturn = currentValue - yesterdayValue
    const dailyReturnPct = yesterdayValue > 0 ? (dailyReturn / yesterdayValue) * 100 : 0

    const totalReturn = currentValue - totalCost
    const totalReturnPct = totalCost > 0 ? (totalReturn / totalCost) * 100 : 0

    return NextResponse.json({
      success: true,
      metrics: {
        // Rentabilidad Total (desde compra)
        totalReturn,
        totalReturnPct,
        totalCost,

        // YTD (con lógica de fechas correcta)
        ytdReturn,
        ytdReturnPct,
        ytdStartValue,

        // Hoy vs Ayer
        dailyReturn,
        dailyReturnPct,
        yesterdayValue,

        // Valor actual
        currentValue
      },
      dates: {
        ytdBaseDate,
        yesterdayDate: yesterdayStr,
        today: todayStr
      },
      explanation: {
        ytd: 'Para activos comprados antes de 2026: base = precio 1 Enero. Para activos comprados en 2026: base = precio de compra.',
        daily: 'Para activos comprados hoy: cambio = 0. Para activos que existían ayer: valor ayer vs valor hoy.'
      },
      source: 'yahoo_finance_with_purchase_dates'
    })

  } catch (error: any) {
    console.error('Error calculating historical metrics:', error)
    return NextResponse.json(
      { error: 'Error calculando métricas', details: error.message },
      { status: 500 }
    )
  }
}
