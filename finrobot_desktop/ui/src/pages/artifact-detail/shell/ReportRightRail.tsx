// Right-side sticky rail. Surfaces P4-track desktop augmentations:
//   - Version Timeline (P4.1)  — visualises artifact timeline as
//     clickable rows so analysts can hop between versions without
//     opening the toolbar selector.
//   - What-if Editor (P4.2)    — placeholder for the live DCF re-compute
//     panel. Inputs render disabled until the wiring lands.

import { useNavigate } from 'react-router-dom'
import type { ArtifactSummaryV5 } from '../../../types/v5'

interface ReportRightRailProps {
  ticker: string
  currentArtifactId: string
  timeline: ArtifactSummaryV5[]
  reportType: string
  /** WACC pulled off DCFResult.inputs.wacc if present (for display-only). */
  wacc: number | null
  terminalGrowth: number | null
}

export function ReportRightRail({
  ticker,
  currentArtifactId,
  timeline,
  reportType,
  wacc,
  terminalGrowth,
}: ReportRightRailProps): React.ReactElement {
  const navigate = useNavigate()
  const sameType = timeline.filter((a) => a.type === reportType)

  return (
    <aside
      data-testid="report-right-rail"
      style={{
        position: 'sticky',
        top: 82,
        alignSelf: 'start',
        padding: '16px 0',
        fontSize: 12,
      }}
    >
      <RailPanel title="Version Timeline" badge="P4.1">
        {sameType.length === 0 ? (
          <p style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
            尚无历史版本 · 重跑 research 后将累积
          </p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {sameType.slice(0, 8).map((a) => {
              const current = a.id === currentArtifactId
              return (
                <button
                  key={a.id}
                  type="button"
                  data-testid={`timeline-${a.id}`}
                  onClick={() => navigate(`/stocks/${ticker}/runs/${a.id}`)}
                  style={{
                    textAlign: 'left',
                    padding: '8px 10px',
                    background: current ? 'rgba(139,92,246,0.08)' : 'rgba(15,15,34,0.5)',
                    border: 'none',
                    borderLeft: `2px solid ${current ? 'var(--secondary)' : 'var(--border-soft)'}`,
                    borderRadius: '0 6px 6px 0',
                    cursor: current ? 'default' : 'pointer',
                    fontFamily: 'var(--font-mono)',
                    fontSize: 11.5,
                    color: 'var(--text-primary)',
                  }}
                >
                  <span style={{ fontWeight: 600 }}>
                    {current ? 'current' : new Date(a.created_at).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })}
                  </span>
                  {a.target_price !== null && a.target_price !== undefined && (
                    <span style={{ marginLeft: 8, color: 'var(--text-secondary)' }}>
                      ${a.target_price.toFixed(0)}
                    </span>
                  )}
                  <SignalBadge signal={a.signal} />
                  <div style={{ color: 'var(--text-dim)', fontSize: 10, marginTop: 2 }}>
                    {new Date(a.created_at).toLocaleString('zh-CN', {
                      year: 'numeric',
                      month: '2-digit',
                      day: '2-digit',
                    })}
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </RailPanel>

      <RailPanel title="What-if Editor" badge="P4.2">
        <WhatIfRow label="WACC" value={wacc !== null ? `${(wacc * 100).toFixed(1)}%` : '—'} />
        <WhatIfRow
          label="Terminal Growth"
          value={terminalGrowth !== null ? `${(terminalGrowth * 100).toFixed(1)}%` : '—'}
        />
        <p
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            color: 'var(--text-muted)',
            marginTop: 8,
            lineHeight: 1.5,
          }}
        >
          改假设后调 <span style={{ color: 'var(--accent-cyan)' }}>/api/compute/dcf</span> 重算 ·
          落地中
        </p>
      </RailPanel>
    </aside>
  )
}

function RailPanel({
  title,
  badge,
  children,
}: {
  title: string
  badge: string
  children: React.ReactNode
}): React.ReactElement {
  return (
    <div
      style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-md)',
        padding: 14,
        marginBottom: 14,
      }}
    >
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          color: 'var(--secondary)',
          letterSpacing: '0.1em',
          textTransform: 'uppercase',
          marginBottom: 10,
          display: 'flex',
          alignItems: 'center',
          gap: 6,
        }}
      >
        {title}
        <span
          style={{
            fontSize: 8.5,
            padding: '1px 5px',
            borderRadius: 3,
            background: 'rgba(34, 211, 238, 0.18)',
            color: 'var(--accent-cyan)',
            letterSpacing: '0.1em',
          }}
        >
          {badge}
        </span>
      </div>
      {children}
    </div>
  )
}

function WhatIfRow({ label, value }: { label: string; value: string }): React.ReactElement {
  return (
    <div style={{ marginBottom: 10 }}>
      <label
        style={{
          display: 'block',
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          color: 'var(--text-muted)',
          marginBottom: 4,
        }}
      >
        {label}{' '}
        <span style={{ color: 'var(--accent-cyan)', fontFamily: 'var(--font-mono)' }}>{value}</span>
      </label>
      <input
        type="range"
        disabled
        style={{ width: '100%', accentColor: 'var(--secondary)', opacity: 0.5 }}
      />
    </div>
  )
}

function SignalBadge({
  signal,
}: {
  signal: 'hit' | 'watching' | 'failed' | null | undefined
}): React.ReactElement | null {
  if (!signal) return null
  const colors = {
    hit: { bg: 'rgba(22,163,74,0.18)', fg: 'var(--success)' },
    watching: { bg: 'rgba(217,119,6,0.18)', fg: 'var(--warning)' },
    failed: { bg: 'rgba(220,38,38,0.18)', fg: 'var(--danger)' },
  } as const
  const c = colors[signal]
  return (
    <span
      style={{
        marginLeft: 8,
        fontSize: 9.5,
        padding: '1px 5px',
        borderRadius: 3,
        background: c.bg,
        color: c.fg,
        letterSpacing: '0.06em',
      }}
    >
      {signal.toUpperCase()}
    </span>
  )
}
