// HitRateBanner — Track Record · forecast accuracy snapshot on /stocks.
//
// Three window chips (30d / 90d / all) drive a single useDashboardHitRate
// call. When `n_closed === 0` the banner shows an "insufficient sample"
// hint instead of fabricating a number — no fake confidence here.

import { useState } from 'react'
import { useDashboardHitRate, type HitRateWindow } from '../../hooks/useDashboardHitRate'
import { verdictLabel } from '../../utils/verdict'

const WINDOWS: { value: HitRateWindow; label: string }[] = [
  { value: '30d', label: '30 天' },
  { value: '90d', label: '90 天' },
  { value: 'all', label: '全部' },
]

export function HitRateBanner(): React.ReactElement {
  const [window, setWindow] = useState<HitRateWindow>('all')
  const { data, isLoading, isError } = useDashboardHitRate(window)

  return (
    <section
      data-testid="hit-rate-banner"
      className="cosmic-card cosmic-card-glass"
      style={{ padding: 28 }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 20 }}>
        <span
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 12,
            letterSpacing: 3,
            color: 'var(--accent-cyan)',
            padding: '4px 10px',
            border: '1px solid rgba(34,211,238,0.4)',
            borderRadius: 6,
            boxShadow: 'inset 0 0 12px rgba(34,211,238,0.15)',
          }}
        >
          01
        </span>
        <h2
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 20,
            letterSpacing: 2.5,
            color: 'var(--text-primary)',
            margin: 0,
          }}
        >
          Track Record · 命中率
        </h2>
        <span style={{ flex: 1 }} />
        <div style={{ display: 'flex', gap: 4 }}>
          {WINDOWS.map((w) => (
            <button
              key={w.value}
              type="button"
              onClick={() => setWindow(w.value)}
              style={{
                padding: '6px 14px',
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                letterSpacing: '0.06em',
                color: window === w.value ? 'var(--primary)' : 'var(--text-muted)',
                background: window === w.value ? 'var(--primary-soft)' : 'transparent',
                border: `1px solid ${window === w.value ? 'var(--border-glow)' : 'var(--border-soft)'}`,
                borderRadius: 'var(--radius-sm)',
                cursor: 'pointer',
                transition: 'all 0.15s',
              }}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>

      {isError && (
        <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>
          数据加载失败，请稍后刷新页面。
        </p>
      )}

      {isLoading && !data && <BannerSkeleton />}

      {data && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'minmax(0, 1.4fr) repeat(3, minmax(0, 1fr))',
            gap: 16,
            alignItems: 'stretch',
          }}
        >
          <OverallTile bucket={data.overall} />
          <VerdictTile label={verdictLabel('BUY')} tone="success" bucket={data.by_verdict.BUY} />
          <VerdictTile label={verdictLabel('HOLD')} tone="warning" bucket={data.by_verdict.HOLD} />
          <VerdictTile label={verdictLabel('SELL')} tone="danger" bucket={data.by_verdict.SELL} />
        </div>
      )}
    </section>
  )
}

function OverallTile({
  bucket,
}: {
  bucket: { n_total: number; n_closed: number; n_hit: number; hit_rate: number | null }
}): React.ReactElement {
  const insufficient = bucket.n_closed === 0
  return (
    <div
      style={{
        padding: '18px 22px',
        background: 'rgba(10,10,24,0.55)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-md)',
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
      }}
    >
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          letterSpacing: '0.12em',
          color: 'var(--text-muted)',
          textTransform: 'uppercase',
        }}
      >
        Overall · settled {bucket.n_closed} / total {bucket.n_total}
      </div>
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 48,
          fontWeight: 600,
          color: insufficient ? 'var(--text-muted)' : 'var(--text-primary)',
          letterSpacing: '-0.02em',
          lineHeight: 1,
        }}
      >
        {insufficient ? '—' : `${(bucket.hit_rate! * 100).toFixed(1)}%`}
      </div>
      <div
        style={{
          fontFamily: 'var(--font-body)',
          fontSize: 12,
          color: insufficient ? 'var(--text-muted)' : 'var(--text-secondary)',
        }}
      >
        {insufficient
          ? 'Insufficient track record · need ≥1 settled position to compute hit rate'
          : `${bucket.n_hit} of ${bucket.n_closed} settled positions hit target`}
      </div>
    </div>
  )
}

function VerdictTile({
  label,
  tone,
  bucket,
}: {
  label: string
  tone: 'success' | 'warning' | 'danger'
  bucket: { n_total: number; n_closed: number; n_hit: number; hit_rate: number | null }
}): React.ReactElement {
  const colorMap = {
    success: { fg: 'var(--success)', glow: 'var(--success-glow)' },
    warning: { fg: 'var(--accent-amber)', glow: 'rgba(217,119,6,0.45)' },
    danger: { fg: 'var(--danger)', glow: 'var(--danger-glow)' },
  } as const
  const c = colorMap[tone]
  const insufficient = bucket.n_closed === 0
  return (
    <div
      style={{
        padding: '14px 16px',
        background: 'rgba(10,10,24,0.4)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-md)',
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        minWidth: 0,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 12,
            letterSpacing: 2,
            color: c.fg,
            textShadow: `0 0 10px ${c.glow}`,
          }}
        >
          {label}
        </span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)' }}>
          n={bucket.n_total}
        </span>
      </div>
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 28,
          fontWeight: 600,
          color: insufficient ? 'var(--text-muted)' : c.fg,
          letterSpacing: '-0.02em',
        }}
      >
        {insufficient ? '—' : `${(bucket.hit_rate! * 100).toFixed(0)}%`}
      </div>
      <div style={{ fontFamily: 'var(--font-body)', fontSize: 11, color: 'var(--text-muted)' }}>
        {bucket.n_hit}/{bucket.n_closed} hits
      </div>
    </div>
  )
}

function BannerSkeleton(): React.ReactElement {
  return (
    <div style={{ display: 'flex', gap: 16 }}>
      {[1.4, 1, 1, 1].map((flex, i) => (
        <div
          key={i}
          style={{
            flex,
            height: 96,
            borderRadius: 'var(--radius-md)',
            background:
              'linear-gradient(110deg, rgba(15,15,34,0.6) 25%, rgba(34,211,238,0.05) 50%, rgba(15,15,34,0.6) 75%)',
            backgroundSize: '200% 100%',
            animation: 'cosmic-shimmer 2s linear infinite',
            border: '1px solid var(--border-faint)',
          }}
        />
      ))}
    </div>
  )
}
