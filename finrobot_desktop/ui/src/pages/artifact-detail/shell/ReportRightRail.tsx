import { useCallback, useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { BASE_URL } from '../../../api/client'
import type { ArtifactSummaryV5 } from '../../../types/v5'
import { useI18n } from '../../../i18n'
import { formatDate } from '../../../utils/format'

interface ReportRightRailProps {
  ticker: string
  currentArtifactId: string
  timeline: ArtifactSummaryV5[]
  reportType: string
  wacc: number | null
  terminalGrowth: number | null
  /** Baseline implied price from the artifact — used as the "original" benchmark. */
  originalImpliedPrice: number | null
}

interface DcfSeedResponse {
  inputs: { wacc?: number; terminal_growth_rate?: number } & Record<string, unknown>
  result: { implied_price: number; wacc: number }
  current_price: number | null
}

async function postDcfSeed(body: {
  ticker: string
  wacc_override: number
  tg_override: number
}): Promise<DcfSeedResponse> {
  const resp = await fetch(`${BASE_URL}/api/compute/dcf-seed`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...body, mid_year: false, include_reverse: false }),
  })
  if (!resp.ok) {
    const detail = await resp.text().catch(() => '')
    throw new Error(`${resp.status} ${detail.slice(0, 160)}`)
  }
  return (await resp.json()) as DcfSeedResponse
}

export function ReportRightRail({
  ticker,
  currentArtifactId,
  timeline,
  reportType,
  wacc,
  terminalGrowth,
  originalImpliedPrice,
}: ReportRightRailProps): React.ReactElement {
  const navigate = useNavigate()
  const { locale, t } = useI18n()
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
      <RailPanel title="版本时间线">
        {sameType.length === 0 ? (
          <p style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
            {t('report.timeline.empty')}
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
                    {current ? t('report.timeline.current') : formatDate(a.created_at, locale, 'short')}
                  </span>
                  {a.target_price !== null && a.target_price !== undefined && (
                    <span style={{ marginLeft: 8, color: 'var(--text-secondary)' }}>
                      ${a.target_price.toFixed(0)}
                    </span>
                  )}
                  <SignalBadge signal={a.signal} />
                  <div style={{ color: 'var(--text-dim)', fontSize: 10, marginTop: 2 }}>
                    {formatDate(a.created_at, locale, 'short')}
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </RailPanel>

      <WhatIfEditor
        ticker={ticker}
        initialWacc={wacc}
        initialTg={terminalGrowth}
        originalImpliedPrice={originalImpliedPrice}
      />
    </aside>
  )
}

function WhatIfEditor({
  ticker,
  initialWacc,
  initialTg,
  originalImpliedPrice,
}: {
  ticker: string
  initialWacc: number | null
  initialTg: number | null
  originalImpliedPrice: number | null
}): React.ReactElement {
  const baseWacc = initialWacc ?? 0.10
  const baseTg = initialTg ?? 0.025

  const [waccPct, setWaccPct] = useState<number>(baseWacc * 100)
  const [tgPct, setTgPct] = useState<number>(baseTg * 100)

  const mutation = useMutation({
    mutationFn: postDcfSeed,
  })

  // Debounce slider changes so dragging doesn't fire 50 requests.
  useEffect(() => {
    const handle = setTimeout(() => {
      if (
        Math.abs(waccPct / 100 - baseWacc) < 1e-4 &&
        Math.abs(tgPct / 100 - baseTg) < 1e-4
      ) {
        mutation.reset()
        return
      }
      mutation.mutate({
        ticker,
        wacc_override: waccPct / 100,
        tg_override: tgPct / 100,
      })
    }, 380)
    return () => clearTimeout(handle)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [waccPct, tgPct, ticker])

  const handleReset = useCallback(() => {
    setWaccPct(baseWacc * 100)
    setTgPct(baseTg * 100)
    mutation.reset()
  }, [baseWacc, baseTg, mutation])

  const newImplied = mutation.data?.result?.implied_price ?? null
  const dirty =
    Math.abs(waccPct / 100 - baseWacc) > 1e-4 ||
    Math.abs(tgPct / 100 - baseTg) > 1e-4
  const delta =
    newImplied !== null && originalImpliedPrice !== null
      ? ((newImplied - originalImpliedPrice) / originalImpliedPrice) * 100
      : null
  const deltaUp = delta !== null && delta >= 0

  return (
    <RailPanel
      title="What-if Editor"
      headerAction={
        dirty ? (
          <button
            type="button"
            onClick={handleReset}
            style={resetButtonStyle}
            title="重置到 artifact 原始假设"
          >
            重置
          </button>
        ) : undefined
      }
    >
      <SliderRow
        label="WACC"
        valueLabel={`${waccPct.toFixed(2)}%`}
        min={5}
        max={20}
        step={0.1}
        value={waccPct}
        onChange={setWaccPct}
      />
      <SliderRow
        label="Terminal Growth"
        valueLabel={`${tgPct.toFixed(2)}%`}
        min={-2}
        max={5}
        step={0.1}
        value={tgPct}
        onChange={setTgPct}
      />

      <div
        style={{
          marginTop: 10,
          padding: '10px 12px',
          background: 'rgba(15, 15, 34, 0.6)',
          border: '1px solid var(--border-soft)',
          borderRadius: 'var(--radius-sm)',
          fontFamily: 'var(--font-mono)',
        }}
      >
        <div style={{ fontSize: 9.5, color: 'var(--text-muted)', letterSpacing: '0.1em', marginBottom: 4 }}>
          IMPLIED PRICE
        </div>
        {mutation.isPending ? (
          <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>computing…</div>
        ) : mutation.isError ? (
          <div style={{ fontSize: 11, color: 'var(--danger)' }}>
            重算失败 · 检查参数范围或重试
          </div>
        ) : newImplied !== null ? (
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <span style={{ fontSize: 18, color: 'var(--accent-cyan)', fontVariantNumeric: 'tabular-nums' }}>
              ${newImplied.toFixed(2)}
            </span>
            {delta !== null && (
              <span
                style={{
                  fontSize: 11,
                  color: deltaUp ? 'var(--success)' : 'var(--danger)',
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {deltaUp ? '+' : ''}
                {delta.toFixed(1)}% vs base
              </span>
            )}
          </div>
        ) : (
          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            拖动滑块以重算 implied price
          </div>
        )}
      </div>

      {originalImpliedPrice !== null && (
        <p
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 9.5,
            color: 'var(--text-dim)',
            marginTop: 8,
            letterSpacing: '0.04em',
          }}
        >
          基准 ${originalImpliedPrice.toFixed(2)}
        </p>
      )}
    </RailPanel>
  )
}

function SliderRow({
  label,
  valueLabel,
  min,
  max,
  step,
  value,
  onChange,
}: {
  label: string
  valueLabel: string
  min: number
  max: number
  step: number
  value: number
  onChange: (v: number) => void
}): React.ReactElement {
  return (
    <div style={{ marginBottom: 10 }}>
      <label
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          color: 'var(--text-muted)',
          marginBottom: 4,
        }}
      >
        <span>{label}</span>
        <span style={{ color: 'var(--accent-cyan)' }}>{valueLabel}</span>
      </label>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ width: '100%', accentColor: 'var(--secondary)' }}
      />
    </div>
  )
}

function RailPanel({
  title,
  children,
  headerAction,
}: {
  title: string
  children: React.ReactNode
  headerAction?: React.ReactNode
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
          justifyContent: 'space-between',
        }}
      >
        <span>{title}</span>
        {headerAction}
      </div>
      {children}
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

const resetButtonStyle: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 9.5,
  padding: '2px 7px',
  borderRadius: 4,
  background: 'transparent',
  color: 'var(--text-muted)',
  border: '1px solid var(--border-soft)',
  cursor: 'pointer',
  letterSpacing: '0.04em',
}
