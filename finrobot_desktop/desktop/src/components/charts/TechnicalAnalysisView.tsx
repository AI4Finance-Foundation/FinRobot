import { useRef, useState, useMemo, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAppStore } from '../../stores/appStore'
import { BASE_URL } from '../../api/client'
import CandlestickChart from './CandlestickChart'
import TechnicalIndicators from './TechnicalIndicators'
import type { OHLCRow } from './CandlestickChart'

// ---------- Constants ----------

type TimeRange = '1M' | '3M' | '6M' | '1Y' | 'ALL'
const TIME_RANGES: TimeRange[] = ['1M', '3M', '6M', '1Y', 'ALL']

const PERIOD_MAP: Record<TimeRange, string> = {
  '1M': '1mo',
  '3M': '3mo',
  '6M': '6mo',
  '1Y': '1y',
  'ALL': 'max',
}

type Indicator = 'sma20' | 'sma50' | 'rsi' | 'bb'

const INDICATOR_LABELS: Record<Indicator, string> = {
  sma20: 'SMA 20',
  sma50: 'SMA 50',
  rsi: 'RSI',
  bb: 'Bollinger',
}

// ---------- Component ----------

export default function TechnicalAnalysisView() {
  const [range, setRange] = useState<TimeRange>('1Y')
  const [debouncedRange, setDebouncedRange] = useState<TimeRange>('1Y')
  const debounceRef = useRef<ReturnType<typeof setTimeout>>()
  const ticker = useAppStore((s) => s.ticker)

  const [activeIndicators, setActiveIndicators] = useState<Set<Indicator>>(
    () => new Set(['sma20']),
  )

  const handleRangeChange = useCallback((newRange: TimeRange) => {
    setRange(newRange)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => setDebouncedRange(newRange), 300)
  }, [])

  const toggleIndicator = useCallback((ind: Indicator) => {
    setActiveIndicators((prev) => {
      const next = new Set(prev)
      if (next.has(ind)) {
        next.delete(ind)
      } else {
        next.add(ind)
      }
      return next
    })
  }, [])

  // Fetch OHLCV data
  const { data: fetchedData, isLoading } = useQuery({
    queryKey: ['price-ohlcv', ticker, debouncedRange],
    queryFn: async () => {
      const resp = await fetch(
        `${BASE_URL}/api/data/${ticker}/price?period=${PERIOD_MAP[debouncedRange]}`,
      )
      if (!resp.ok) return []
      const json = await resp.json()
      return (json.history ?? []) as OHLCRow[]
    },
    enabled: !!ticker,
  })

  const chartData: OHLCRow[] = useMemo(() => fetchedData ?? [], [fetchedData])

  if (!ticker) return null

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">{ticker} Technical Analysis</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {/* Indicator toggle buttons */}
          <div className="indicator-toggles">
            {(Object.keys(INDICATOR_LABELS) as Indicator[]).map((ind) => (
              <button
                key={ind}
                className={`indicator-toggle-btn${activeIndicators.has(ind) ? ' active' : ''}`}
                onClick={() => toggleIndicator(ind)}
              >
                {INDICATOR_LABELS[ind]}
              </button>
            ))}
          </div>
          {/* Time range selector */}
          <div className="time-range-selector">
            {TIME_RANGES.map((r) => (
              <button
                key={r}
                className={`time-range-btn${range === r ? ' active' : ''}`}
                onClick={() => handleRangeChange(r)}
              >
                {r}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="card-body" style={{ padding: '8px 16px 4px' }}>
        {isLoading && chartData.length === 0 ? (
          <div className="loading-skeleton" style={{ height: 340 }} />
        ) : chartData.length === 0 ? (
          <div style={{ color: '#7A8299', textAlign: 'center', padding: 40 }}>
            No price data available
          </div>
        ) : (
          <>
            <CandlestickChart
              data={chartData}
              showSMA20={activeIndicators.has('sma20')}
              showSMA50={activeIndicators.has('sma50')}
              showBollinger={activeIndicators.has('bb')}
            />
            <TechnicalIndicators
              data={chartData}
              showRSI={activeIndicators.has('rsi')}
            />
          </>
        )}
      </div>
    </div>
  )
}
