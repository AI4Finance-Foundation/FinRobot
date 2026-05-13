import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { useAppStore } from '../stores/appStore'

export default function TickerInput() {
  const [input, setInput] = useState('')
  const { setTicker, setPhase, setWarnings, setCurrentPrice, setDataFetchedAt, phase } = useAppStore()

  const handleLoad = () => {
    const t = input.trim().toUpperCase()
    if (!t) return
    setTicker(t)
    setPhase('loading_data')
  }

  // Fetch financials when phase is loading_data
  const ticker = useAppStore((s) => s.ticker)
  const { isFetching, isError, error } = useQuery({
    queryKey: ['financials', ticker],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/data/{ticker}/financials', {
        params: { path: { ticker } },
      })
      if (error) throw new Error((error as { detail?: string }).detail || 'Failed to load data')
      if (data) {
        setWarnings(data.warnings || [])
        if (data.market?.current_price != null) {
          setCurrentPrice(data.market.current_price)
        }
        setDataFetchedAt(Date.now())
        setPhase('data_ready')
      }
      return data
    },
    enabled: !!ticker && phase === 'loading_data',
    retry: 1,
  })

  // If fetch fails, reset phase so user isn't stuck on loading_data
  useEffect(() => {
    if (isError && phase === 'loading_data') {
      setPhase('idle')
    }
  }, [isError, phase, setPhase])

  return (
    <div className="ticker-display">
      <input
        type="text"
        className="ticker-input"
        value={input}
        onChange={(e) => setInput(e.target.value.toUpperCase())}
        onKeyDown={(e) => e.key === 'Enter' && handleLoad()}
        placeholder="AAPL"
      />
      <button
        className="btn btn-primary"
        onClick={handleLoad}
        disabled={!input.trim() || phase === 'loading_data'}
        style={{ padding: '4px 12px', fontSize: '0.78rem' }}
      >
        {isFetching ? 'Loading...' : 'Load'}
      </button>
      {isError && (
        <span style={{ color: 'var(--negative)', fontSize: '0.72rem' }}>
          {(error as Error)?.message || 'Failed to load. Check backend is running.'}
        </span>
      )}
    </div>
  )
}
