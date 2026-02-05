'use client'

import { useState, useEffect, useCallback } from 'react'
import { ALL_TRACKED_POSITIONS, TrackedPosition } from './portfolioTracking'

// URL del servidor de precios OpenBB (Python) - solo para desarrollo local
const PRICE_SERVER_URL = process.env.NEXT_PUBLIC_PRICE_SERVER_URL || 'http://localhost:8000'

// Detectar si estamos en Vercel (producción) o en desarrollo local
const IS_VERCEL = typeof window !== 'undefined' && !window.location.hostname.includes('localhost')

export type LivePosition = TrackedPosition & {
  livePrice?: number
  liveValue?: number
  livePnL?: number
  livePnLPct?: number
  priceChange?: number
  priceChangePct?: number
  priceSource?: string
}

export type PriceServerStatus = 'connected' | 'disconnected' | 'checking'

export function useLivePrices(autoRefreshInterval?: number) {
  const [positions, setPositions] = useState<LivePosition[]>(ALL_TRACKED_POSITIONS)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)
  const [serverStatus, setServerStatus] = useState<PriceServerStatus>('checking')
  const [eurUsdRate, setEurUsdRate] = useState<number>(0.92)

  // Verificar si el servidor de precios está disponible
  const checkServerStatus = useCallback(async (): Promise<boolean> => {
    try {
      const response = await fetch(`${PRICE_SERVER_URL}/`, {
        method: 'GET',
        signal: AbortSignal.timeout(3000)
      })
      if (response.ok) {
        setServerStatus('connected')
        return true
      }
    } catch {
      setServerStatus('disconnected')
    }
    return false
  }, [])

  // Obtener precios del servidor OpenBB
  const fetchFromOpenBB = async (tickers: string[]): Promise<Record<string, any>> => {
    const tickersParam = tickers.join(',')
    const response = await fetch(`${PRICE_SERVER_URL}/api/prices?tickers=${tickersParam}`, {
      signal: AbortSignal.timeout(30000)
    })

    if (!response.ok) {
      throw new Error(`OpenBB server error: ${response.statusText}`)
    }

    const data = await response.json()

    if (data.eur_usd_rate) {
      setEurUsdRate(data.eur_usd_rate)
    }

    return data.prices || {}
  }

  // Fallback: usar la API local de Next.js
  const fetchFromLocalAPI = async (tickers: string[]): Promise<Record<string, any>> => {
    const tickersParam = tickers.join(',')
    const response = await fetch(`/api/prices?tickers=${tickersParam}`)

    if (!response.ok) {
      throw new Error('Local API error')
    }

    const data = await response.json()
    return data.prices || {}
  }

  // Función principal para obtener precios
  const fetchLivePrices = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)

      // Obtener todos los tickers únicos
      const tickers = Array.from(new Set(ALL_TRACKED_POSITIONS.map(p => p.ticker)))

      let prices: Record<string, any> = {}
      let source = 'static'

      // En Vercel, usar directamente la API de Next.js (no hay servidor local)
      if (IS_VERCEL) {
        try {
          prices = await fetchFromLocalAPI(tickers)
          source = 'yahoo'
          setServerStatus('connected')
          console.log('Precios obtenidos de API Vercel:', Object.keys(prices).length)
        } catch (e) {
          console.warn('API Vercel falló:', e)
          setServerStatus('disconnected')
        }
      } else {
        // En desarrollo local, intentar primero con el servidor OpenBB
        const serverAvailable = await checkServerStatus()

        if (serverAvailable) {
          try {
            prices = await fetchFromOpenBB(tickers)
            source = 'openbb'
            console.log('Precios obtenidos de OpenBB:', Object.keys(prices).length)
          } catch (e) {
            console.warn('OpenBB falló, intentando API local:', e)
            setServerStatus('disconnected')
          }
        }

        // Si OpenBB falló, intentar con API local
        if (Object.keys(prices).length === 0) {
          try {
            prices = await fetchFromLocalAPI(tickers)
            source = 'yahoo'
            console.log('Precios obtenidos de API local:', Object.keys(prices).length)
          } catch (e) {
            console.warn('API local también falló:', e)
          }
        }
      }

      // Actualizar posiciones con precios obtenidos
      const updatedPositions = ALL_TRACKED_POSITIONS.map(position => {
        const priceData = prices[position.ticker]

        if (priceData && priceData.price) {
          const livePrice = priceData.price

          // Convertir a EUR si es necesario
          let adjustedPrice = livePrice
          if (priceData.currency === 'USD' && position.currency === 'EUR') {
            adjustedPrice = livePrice * eurUsdRate
          }

          const liveValue = position.shares * adjustedPrice
          const livePnL = liveValue - position.totalCost
          const livePnLPct = position.totalCost > 0 ? (livePnL / position.totalCost) * 100 : 0
          const priceChange = adjustedPrice - position.avgCost
          const priceChangePct = position.avgCost > 0 ? (priceChange / position.avgCost) * 100 : 0

          return {
            ...position,
            livePrice: adjustedPrice,
            liveValue,
            livePnL,
            livePnLPct,
            priceChange,
            priceChangePct,
            priceSource: source
          }
        }

        // Si no hay datos de precio, usar los valores del tracker
        return {
          ...position,
          livePrice: position.currentPrice,
          liveValue: position.currentValue,
          livePnL: position.pnl,
          livePnLPct: position.pnlPct,
          priceChange: 0,
          priceChangePct: 0,
          priceSource: 'static'
        }
      })

      setPositions(updatedPositions)
      setLastUpdate(new Date())

      // Contar cuántos precios se actualizaron
      const liveCount = updatedPositions.filter(p => p.priceSource !== 'static').length
      if (liveCount > 0) {
        console.log(`Actualizados ${liveCount}/${updatedPositions.length} precios en vivo`)
      }

    } catch (err: any) {
      console.error('Error fetching live prices:', err)
      setError(err.message)

      // En caso de error total, usar precios estáticos
      setPositions(ALL_TRACKED_POSITIONS.map(p => ({
        ...p,
        livePrice: p.currentPrice,
        liveValue: p.currentValue,
        livePnL: p.pnl,
        livePnLPct: p.pnlPct,
        priceChange: 0,
        priceChangePct: 0,
        priceSource: 'static'
      })))
    } finally {
      setLoading(false)
    }
  }, [checkServerStatus, eurUsdRate])

  // Efecto inicial y auto-refresh
  useEffect(() => {
    fetchLivePrices()

    // Auto-refresh si se especifica intervalo
    if (autoRefreshInterval && autoRefreshInterval > 0) {
      const interval = setInterval(fetchLivePrices, autoRefreshInterval)
      return () => clearInterval(interval)
    }
  }, [fetchLivePrices, autoRefreshInterval])

  return {
    positions,
    loading,
    error,
    lastUpdate,
    serverStatus,
    eurUsdRate,
    refetch: fetchLivePrices
  }
}

// Calcular estadísticas totales con precios en vivo
export function calculateLiveStats(positions: LivePosition[]) {
  const totalCost = positions.reduce((sum, p) => sum + p.totalCost, 0)
  const totalValue = positions.reduce((sum, p) => sum + (p.liveValue || p.currentValue), 0)
  const totalPnL = positions.reduce((sum, p) => sum + (p.livePnL || p.pnl), 0)
  const totalPnLPct = totalCost > 0 ? (totalPnL / totalCost) * 100 : 0

  const liveCount = positions.filter(p => p.priceSource !== 'static').length

  return {
    totalCost: totalCost.toFixed(2),
    totalValue: totalValue.toFixed(2),
    totalPnL: totalPnL.toFixed(2),
    totalPnLPct: totalPnLPct.toFixed(2),
    positionsCount: positions.length,
    liveCount
  }
}

// Estadísticas por broker con precios en vivo
export function calculateLiveStatsByBroker(positions: LivePosition[], broker: 'Indexa' | 'Bankinter' | 'Andbank') {
  const filtered = positions.filter(p => p.broker === broker)
  const totalCost = filtered.reduce((sum, p) => sum + p.totalCost, 0)
  const totalValue = filtered.reduce((sum, p) => sum + (p.liveValue || p.currentValue), 0)
  const totalPnL = filtered.reduce((sum, p) => sum + (p.livePnL || p.pnl), 0)
  const totalPnLPct = totalCost > 0 ? (totalPnL / totalCost) * 100 : 0

  return {
    broker,
    totalCost: totalCost.toFixed(2),
    totalValue: totalValue.toFixed(2),
    totalPnL: totalPnL.toFixed(2),
    totalPnLPct: totalPnLPct.toFixed(2),
    positionsCount: filtered.length
  }
}

// Estadísticas por categoría con precios en vivo
export function calculateLiveStatsByCategory(positions: LivePosition[], categoria: 'RV' | 'RF') {
  const filtered = positions.filter(p => p.categoria === categoria)
  const totalCost = filtered.reduce((sum, p) => sum + p.totalCost, 0)
  const totalValue = filtered.reduce((sum, p) => sum + (p.liveValue || p.currentValue), 0)
  const totalPnL = filtered.reduce((sum, p) => sum + (p.livePnL || p.pnl), 0)
  const totalPnLPct = totalCost > 0 ? (totalPnL / totalCost) * 100 : 0

  return {
    categoria,
    totalCost: totalCost.toFixed(2),
    totalValue: totalValue.toFixed(2),
    totalPnL: totalPnL.toFixed(2),
    totalPnLPct: totalPnLPct.toFixed(2),
    positionsCount: filtered.length
  }
}
