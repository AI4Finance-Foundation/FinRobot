'use client'

import { useState, useEffect } from 'react'
import { PerformanceMetrics, PortfolioSnapshot, calculatePerformanceMetrics } from './portfolioSnapshot'
import { getTotalStats } from './portfolioTracking'

export function usePerformanceMetrics() {
  const [metrics, setMetrics] = useState<PerformanceMetrics | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchMetrics()
  }, [])

  async function fetchMetrics() {
    try {
      setLoading(true)
      setError(null)

      // Primero intentar obtener métricas calculadas con Yahoo Finance
      try {
        const historicalResponse = await fetch('/api/historical-metrics')
        if (historicalResponse.ok) {
          const historicalData = await historicalResponse.json()
          if (historicalData.success && historicalData.metrics) {
            // Obtener datos actuales para complementar
            const currentStats = getTotalStats()
            const currentValue = parseFloat(currentStats.totalValue)
            const totalCost = parseFloat(currentStats.totalCost)

            // Recalcular con valor actual real
            const ytdReturn = currentValue - historicalData.metrics.ytdStartValue
            const ytdReturnPct = historicalData.metrics.ytdStartValue > 0
              ? (ytdReturn / historicalData.metrics.ytdStartValue) * 100
              : 0

            const dailyReturn = currentValue - historicalData.metrics.yesterdayValue
            const dailyReturnPct = historicalData.metrics.yesterdayValue > 0
              ? (dailyReturn / historicalData.metrics.yesterdayValue) * 100
              : 0

            setMetrics({
              totalReturn: currentValue - totalCost,
              totalReturnPct: ((currentValue - totalCost) / totalCost) * 100,
              ytdReturn,
              ytdReturnPct,
              ytdStartValue: historicalData.metrics.ytdStartValue,
              dailyReturn,
              dailyReturnPct,
              yesterdayValue: historicalData.metrics.yesterdayValue,
              bestDay: null,
              worstDay: null
            })
            return
          }
        }
      } catch (historicalError) {
        console.warn('Historical metrics API failed, falling back to snapshots:', historicalError)
      }

      // Fallback: Obtener snapshots históricos
      const response = await fetch('/api/snapshot?days=365')

      if (!response.ok) {
        throw new Error('Error obteniendo snapshots')
      }

      const data = await response.json()
      const snapshots: PortfolioSnapshot[] = data.snapshots || []

      // Obtener datos actuales
      const currentStats = getTotalStats()

      // Crear snapshot actual
      const currentSnapshot: PortfolioSnapshot = {
        timestamp: new Date().toISOString(),
        date: new Date().toISOString().split('T')[0],
        totalValue: parseFloat(currentStats.totalValue),
        totalCost: parseFloat(currentStats.totalCost),
        totalPnL: parseFloat(currentStats.totalPnL),
        totalPnLPct: parseFloat(currentStats.totalPnLPct),
        rvValue: 0,
        rvCost: 0,
        rvPnL: 0,
        rvPnLPct: 0,
        rfValue: 0,
        rfCost: 0,
        rfPnL: 0,
        rfPnLPct: 0,
        indexaValue: 0,
        indexaPnL: 0,
        bankinterValue: 0,
        bankinterPnL: 0,
        andbankValue: 0,
        andbankPnL: 0,
        oroValue: 0,
        oroPnL: 0,
        criptoValue: 0,
        criptoPnL: 0,
        liquidezValue: 0,
        positions: []
      }

      // Calcular métricas
      const calculatedMetrics = calculatePerformanceMetrics(snapshots, currentSnapshot)
      setMetrics(calculatedMetrics)

    } catch (err: any) {
      console.error('Error fetching metrics:', err)
      setError(err.message)

      // Métricas por defecto si hay error
      const currentStats = getTotalStats()
      setMetrics({
        totalReturn: parseFloat(currentStats.totalPnL),
        totalReturnPct: parseFloat(currentStats.totalPnLPct),
        ytdReturn: 0,
        ytdReturnPct: 0,
        ytdStartValue: parseFloat(currentStats.totalValue),
        dailyReturn: 0,
        dailyReturnPct: 0,
        yesterdayValue: parseFloat(currentStats.totalValue),
        bestDay: null,
        worstDay: null
      })
    } finally {
      setLoading(false)
    }
  }

  return { metrics, loading, error, refetch: fetchMetrics }
}

// Hook para guardar snapshot actual
export function useSaveSnapshot() {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function saveSnapshot(snapshot: PortfolioSnapshot) {
    try {
      setSaving(true)
      setError(null)

      const response = await fetch('/api/snapshot', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(snapshot)
      })

      if (!response.ok) {
        throw new Error('Error guardando snapshot')
      }

      const data = await response.json()
      return data

    } catch (err: any) {
      console.error('Error saving snapshot:', err)
      setError(err.message)
      throw err
    } finally {
      setSaving(false)
    }
  }

  return { saveSnapshot, saving, error }
}

// Hook para actualizar precios
export function useUpdatePrices() {
  const [updating, setUpdating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function updatePrices(tickers: string[]) {
    try {
      setUpdating(true)
      setError(null)

      const tickersParam = tickers.join(',')
      const response = await fetch(`/api/prices?tickers=${tickersParam}`)

      if (!response.ok) {
        throw new Error('Error actualizando precios')
      }

      const data = await response.json()
      return data.prices

    } catch (err: any) {
      console.error('Error updating prices:', err)
      setError(err.message)
      throw err
    } finally {
      setUpdating(false)
    }
  }

  return { updatePrices, updating, error }
}
