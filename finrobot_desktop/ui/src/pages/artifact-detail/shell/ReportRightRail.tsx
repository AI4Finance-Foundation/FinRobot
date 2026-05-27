import { useCallback, useEffect, useRef, useState } from 'react'
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

interface PostDcfSeedBody {
  ticker: string
  wacc_override: number
  tg_override: number
  growth_scale_override: number | null
}

async function postDcfSeed(body: PostDcfSeedBody): Promise<DcfSeedResponse> {
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
                    {current
                      ? t('report.timeline.current')
                      : formatDate(a.created_at, locale, 'short')}
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

export function WhatIfEditor({
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
  const baseWacc = initialWacc ?? 0.1
  const baseTg = initialTg ?? 0.025

  const [waccPct, setWaccPct] = useState<number>(baseWacc * 100)
  const [tgPct, setTgPct] = useState<number>(baseTg * 100)
  // Revenue growth scale: 0 = seeded growth schedule untouched.
  // Slider is in percent (-50 .. +50) → backend gets it as fraction (-0.5 .. +0.5).
  const [growthScalePct, setGrowthScalePct] = useState<number>(0)

  const mutation = useMutation({
    mutationFn: postDcfSeed,
  })

  // Capture latest mutation methods so the debounce effect can stay free of
  // mutation refs (which churn on every render).
  const mutationRef = useRef(mutation)
  useEffect(() => {
    mutationRef.current = mutation
  }, [mutation])

  // Debounce slider changes so dragging doesn't fire 50 requests.
  useEffect(() => {
    const handle = setTimeout(() => {
      const waccDirty = Math.abs(waccPct / 100 - baseWacc) > 1e-4
      const tgDirty = Math.abs(tgPct / 100 - baseTg) > 1e-4
      const growthDirty = Math.abs(growthScalePct) > 0.1
      if (!waccDirty && !tgDirty && !growthDirty) {
        mutationRef.current.reset()
        return
      }
      mutationRef.current.mutate({
        ticker,
        wacc_override: waccPct / 100,
        tg_override: tgPct / 100,
        growth_scale_override: growthDirty ? growthScalePct / 100 : null,
      })
    }, 380)
    return () => clearTimeout(handle)
  }, [waccPct, tgPct, growthScalePct, ticker, baseWacc, baseTg])

  const handleReset = useCallback(() => {
    setWaccPct(baseWacc * 100)
    setTgPct(baseTg * 100)
    setGrowthScalePct(0)
    mutationRef.current.reset()
  }, [baseWacc, baseTg])

  const newImplied = mutation.data?.result?.implied_price ?? null
  const dirty =
    Math.abs(waccPct / 100 - baseWacc) > 1e-4 ||
    Math.abs(tgPct / 100 - baseTg) > 1e-4 ||
    Math.abs(growthScalePct) > 0.1
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
            title="重置到研报原始假设"
            data-testid="whatif-reset"
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
        testid="whatif-slider-wacc"
      />
      <SliderRow
        label="Terminal Growth"
        valueLabel={`${tgPct.toFixed(2)}%`}
        min={-2}
        max={5}
        step={0.1}
        value={tgPct}
        onChange={setTgPct}
        testid="whatif-slider-tg"
      />
      <SliderRow
        label="Revenue Growth Scale"
        valueLabel={`${growthScalePct >= 0 ? '+' : ''}${growthScalePct.toFixed(0)}%`}
        min={-50}
        max={50}
        step={5}
        value={growthScalePct}
        onChange={setGrowthScalePct}
        testid="whatif-slider-growth"
      />

      <ComparePanel
        original={originalImpliedPrice}
        newImplied={newImplied}
        delta={delta}
        deltaUp={deltaUp}
        isPending={mutation.isPending}
        isError={mutation.isError}
      />
    </RailPanel>
  )
}

function ComparePanel({
  original,
  newImplied,
  delta,
  deltaUp,
  isPending,
  isError,
}: {
  original: number | null
  newImplied: number | null
  delta: number | null
  deltaUp: boolean
  isPending: boolean
  isError: boolean
}): React.ReactElement {
  return (
    <div
      data-testid="whatif-compare"
      style={{
        marginTop: 12,
        padding: '10px 12px',
        background: 'rgba(15, 15, 34, 0.6)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-sm)',
        fontFamily: 'var(--font-mono)',
        display: 'grid',
        gridTemplateColumns: '1fr auto 1fr',
        alignItems: 'center',
        gap: 10,
      }}
    >
      <ComparePrice
        label="BASE"
        price={original}
        accent="var(--text-secondary)"
        testid="whatif-base-price"
      />

      <span
        aria-hidden
        style={{
          color: 'var(--text-dim)',
          fontSize: 16,
          padding: '0 4px',
          letterSpacing: '-0.05em',
        }}
      >
        →
      </span>

      {isError ? (
        <div
          style={{ fontSize: 10.5, color: 'var(--danger)', textAlign: 'right' }}
          data-testid="whatif-error"
        >
          重算失败 · 检查参数范围
        </div>
      ) : (
        <div style={{ textAlign: 'right' }}>
          <div
            style={{
              fontSize: 9.5,
              color: 'var(--text-muted)',
              letterSpacing: '0.1em',
              marginBottom: 2,
            }}
          >
            NEW
          </div>
          <div
            data-testid="whatif-new-price"
            style={{
              fontSize: 18,
              color: isPending
                ? 'var(--text-muted)'
                : newImplied !== null
                  ? 'var(--accent-cyan)'
                  : 'var(--text-dim)',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {isPending ? 'computing…' : newImplied !== null ? `$${newImplied.toFixed(2)}` : '—'}
          </div>
          {!isPending && delta !== null && (
            <div
              data-testid="whatif-delta"
              style={{
                fontSize: 10.5,
                color: deltaUp ? 'var(--success)' : 'var(--danger)',
                fontVariantNumeric: 'tabular-nums',
                marginTop: 2,
              }}
            >
              {deltaUp ? '+' : ''}
              {delta.toFixed(1)}%
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ComparePrice({
  label,
  price,
  accent,
  testid,
}: {
  label: string
  price: number | null
  accent: string
  testid?: string
}): React.ReactElement {
  return (
    <div>
      <div
        style={{
          fontSize: 9.5,
          color: 'var(--text-muted)',
          letterSpacing: '0.1em',
          marginBottom: 2,
        }}
      >
        {label}
      </div>
      <div
        data-testid={testid}
        style={{
          fontSize: 18,
          color: accent,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {price !== null ? `$${price.toFixed(2)}` : '—'}
      </div>
    </div>
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
  testid,
}: {
  label: string
  valueLabel: string
  min: number
  max: number
  step: number
  value: number
  onChange: (v: number) => void
  testid?: string
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
        data-testid={testid}
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
