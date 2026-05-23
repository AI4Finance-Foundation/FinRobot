import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { extractErrorDetail } from '../api/errors'
import { useAppStore } from '../stores/appStore'
import { useI18n } from '../i18n'
import { formatDate } from '../utils/format'

interface EarningsCallTranscript {
  ticker: string
  quarter: number
  year: number
  date: string | null
  content: string
  summary: string | null
}

interface EarningsCallList {
  ticker: string
  transcripts: EarningsCallTranscript[]
}

interface EarningsCallPanelProps {
  /** When omitted, falls back to appStore.ticker (legacy v4 callsite). */
  ticker?: string
}

export default function EarningsCallPanel({ ticker: tickerProp }: EarningsCallPanelProps = {}) {
  const storeTicker = useAppStore((s) => s.ticker)
  const ticker = tickerProp ?? storeTicker
  const [selectedIdx, setSelectedIdx] = useState(0)
  const { locale } = useI18n()

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['earnings-calls', ticker],
    queryFn: async () => {
      const resp = await fetch(`${BASE_URL}/api/data/${ticker}/earnings-calls?limit=8`)
      if (!resp.ok) {
        throw new Error(await extractErrorDetail(resp, '无法加载财报电话会逐字稿'))
      }
      return resp.json() as Promise<EarningsCallList>
    },
    enabled: !!ticker,
    retry: false,
    // Transcripts are immutable once published — cache aggressively.
    staleTime: 60 * 60_000,
    gcTime: 24 * 60 * 60_000,
    refetchOnMount: false,
  })

  // The backend returns Chinese, user-actionable detail (e.g. "需要 FMP API
  // 密钥…请在 设置 → API 密钥 配置"). extractErrorDetail surfaces that
  // verbatim, so we can render error.message directly.
  if (isError) {
    const msg = (error as Error)?.message || '加载财报电话会逐字稿失败。'
    return (
      <div className="card animate-in">
        <div className="card-header">
          <span className="card-title">财报电话会逐字稿</span>
        </div>
        <div
          className="card-body"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            minHeight: 120,
            color: 'var(--text-muted)',
            fontSize: '0.82rem',
            textAlign: 'center',
            padding: 'var(--sp-6)',
          }}
        >
          {msg}
        </div>
      </div>
    )
  }

  // Only show skeleton on cold-start (no cache). Once data is in cache, switching
  // tabs should never re-flash skeleton.
  if (isLoading && !data) {
    return (
      <div className="card animate-in">
        <div className="card-header">
          <span className="card-title">财报电话会逐字稿</span>
        </div>
        <div className="card-body" style={{ padding: 'var(--sp-4)' }}>
          <div
            className="skeleton"
            style={{ width: '100%', height: 200, borderRadius: 'var(--r-md)' }}
          />
        </div>
      </div>
    )
  }

  const transcripts = data?.transcripts ?? []

  if (transcripts.length === 0) {
    return (
      <div className="card animate-in">
        <div className="card-header">
          <span className="card-title">财报电话会逐字稿</span>
        </div>
        <div
          className="card-body"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            minHeight: 120,
            color: 'var(--text-muted)',
            fontSize: '0.82rem',
          }}
        >
          No earnings call transcripts available for {ticker}.
        </div>
      </div>
    )
  }

  const selected = transcripts[selectedIdx] ?? transcripts[0]

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">财报电话会逐字稿</span>
        <span className="card-badge">{transcripts.length} available</span>
      </div>
      <div className="card-body" style={{ padding: 0 }}>
        {/* Quarter selector */}
        <div
          style={{
            display: 'flex',
            gap: 'var(--sp-2)',
            padding: 'var(--sp-3) var(--sp-4)',
            borderBottom: '1px solid var(--border-subtle)',
            overflowX: 'auto',
            flexWrap: 'wrap',
          }}
        >
          {transcripts.map((t, i) => (
            <button
              key={`${t.year}-Q${t.quarter}`}
              onClick={() => setSelectedIdx(i)}
              style={{
                padding: '4px 12px',
                fontSize: '0.75rem',
                fontFamily: 'var(--font-mono)',
                fontWeight: selectedIdx === i ? 600 : 400,
                color: selectedIdx === i ? 'var(--accent)' : 'var(--text-secondary)',
                background: selectedIdx === i ? 'var(--accent-dim)' : 'transparent',
                border: `1px solid ${selectedIdx === i ? 'var(--accent)' : 'var(--border)'}`,
                borderRadius: 'var(--r-sm)',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
                whiteSpace: 'nowrap',
              }}
            >
              Q{t.quarter} {t.year}
            </button>
          ))}
        </div>

        {/* Date info */}
        {selected.date && (
          <div
            style={{
              padding: 'var(--sp-2) var(--sp-4)',
              fontSize: '0.72rem',
              color: 'var(--text-muted)',
              borderBottom: '1px solid var(--border-subtle)',
            }}
          >
            {formatDate(selected.date, locale, 'long')}
          </div>
        )}

        {/* Transcript content */}
        <div
          style={{
            padding: 'var(--sp-4)',
            maxHeight: 400,
            overflowY: 'auto',
            fontSize: '0.8rem',
            lineHeight: 1.7,
            color: 'var(--text-primary)',
            whiteSpace: 'pre-wrap',
            fontFamily: 'var(--font-ui)',
          }}
        >
          {selected.content
            ? selected.content
            : 'Transcript content not available for this quarter.'}
        </div>
      </div>
    </div>
  )
}
