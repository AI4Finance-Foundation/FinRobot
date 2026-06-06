// MarketImpliedPanel — the IC-debate "market-implied expectations" expert probe.
//
// Reverse DCF, presented honestly. The market price doesn't imply ONE valuation
// — it implies a whole family of (growth, horizon) combinations at a given
// discount rate. This panel shows:
//   1. Three anchor cards — each reverse solver holding two axes fixed, solving
//      the third. Every card carries the axes it fixed (the visible prefix) and
//      a credibility prior (✓ arguable / ⚠ distorted), explicitly labelled as a
//      prior, not an objective verdict.
//   2. The (growth → implied horizon) equivalence line at a fixed WACC — the
//      family itself. The WACC slider shifts the whole line (the third axis).
//
// It is NOT a verdict and never enters SWING_FACTOR. Default-collapsed: the
// analyst opens it to interrogate the judge's one-line swing factor.

import { useCallback, useEffect, useRef, useState } from 'react'
import { Line, LineChart, ReferenceDot, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { BASE_URL } from '../../api/client'
import { fetchWithTimeout } from '../../api/fetch'
import { useI18n } from '../../i18n'
import { CosmicTooltipShell } from '../charts/chartTooltip'

interface ReverseResult {
  implied_growth: number | null
  implied_wacc: number | null
  implied_horizon: number | null
  assumed_growth: number | null
  wacc: number | null
  terminal_growth: number
  message: string | null
}

interface SeedReverse {
  reverse_growth: ReverseResult | null
  reverse_wacc: ReverseResult | null
  reverse_horizon: ReverseResult | null
  current_price: number | null
}

interface EquivPoint {
  growth: number
  implied_horizon: number | null
}

interface EquivLine {
  ticker: string
  target_price: number
  wacc: number
  terminal_growth: number
  points: EquivPoint[]
}

const AXIS_TICK = {
  fill: 'var(--text-muted)',
  fontSize: 10,
  fontFamily: 'var(--font-mono)',
} as const

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetchWithTimeout(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${path} → ${res.status}`)
  return (await res.json()) as T
}

// Credibility priors — these ARE analyst judgement, surfaced (not hidden in the
// algorithm). A bond-grade implied cost of equity is almost certainly a
// short-window artifact; a 5–12y high-growth runway is arguable for a leader.
function waccVerdict(w: number | null): 'distorted' | 'arguable' | 'unreachable' {
  if (w === null) return 'unreachable'
  return w < 0.09 ? 'distorted' : 'arguable'
}
function horizonVerdict(h: number | null): 'distorted' | 'arguable' | 'unreachable' {
  if (h === null) return 'unreachable'
  return h >= 5 && h <= 12 ? 'arguable' : 'distorted'
}
function growthVerdict(g: number | null): 'distorted' | 'arguable' | 'unreachable' {
  if (g === null) return 'unreachable'
  return g > 0.5 ? 'distorted' : 'arguable'
}

function badge(v: 'distorted' | 'arguable' | 'unreachable'): { mark: string; color: string } {
  if (v === 'arguable') return { mark: '✓', color: 'var(--success)' }
  return { mark: '⚠', color: 'var(--warning)' }
}

interface Props {
  ticker: string
  /** Override target price; defaults to the backend's current price. */
  targetPrice?: number | null
}

export function MarketImpliedPanel({ ticker }: Props): React.ReactElement | null {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [seed, setSeed] = useState<SeedReverse | null>(null)
  const [line, setLine] = useState<EquivLine | null>(null)
  const [wacc, setWacc] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null)

  const fetchLine = useCallback(
    async (waccOverride: number | null) => {
      try {
        const l = await postJson<EquivLine>('/api/compute/dcf-equivalence-line', {
          ticker,
          wacc_override: waccOverride,
          growth_lo: 0.2,
          growth_hi: 0.5,
          steps: 13,
        })
        setLine(l)
        if (waccOverride === null) setWacc(l.wacc)
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      }
    },
    [ticker],
  )

  // Lazy: only fetch when the analyst opens the probe.
  useEffect(() => {
    if (!open || seed) return
    void (async () => {
      try {
        const s = await postJson<SeedReverse>('/api/compute/dcf-seed', {
          ticker,
          include_reverse: true,
        })
        setSeed(s)
        await fetchLine(null)
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      }
    })()
  }, [open, seed, ticker, fetchLine])

  const onWacc = useCallback(
    (next: number) => {
      setWacc(next)
      if (debounce.current) clearTimeout(debounce.current)
      debounce.current = setTimeout(() => void fetchLine(next), 220)
    },
    [fetchLine],
  )

  return (
    <div
      data-testid="market-implied-panel"
      style={{
        margin: '0 0 24px',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-md)',
        background: 'rgba(15,15,34,0.5)',
        backdropFilter: 'blur(12px)',
        overflow: 'hidden',
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '12px 16px',
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          letterSpacing: '0.08em',
          color: 'var(--text-secondary)',
          textTransform: 'uppercase',
        }}
      >
        <span style={{ color: 'var(--accent-violet, var(--primary))' }}>⌖</span>
        {t('ic.implied.title')}
        <span style={{ color: 'var(--text-dim)', textTransform: 'none', letterSpacing: 0 }}>
          {t('ic.implied.subtitle')}
        </span>
        <span style={{ marginLeft: 'auto', color: 'var(--text-muted)' }}>{open ? '▾' : '▸'}</span>
      </button>

      {open && (
        <div style={{ padding: '4px 16px 18px' }}>
          {error && (
            <p style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--danger)' }}>
              {error}
            </p>
          )}
          {!error && !seed && (
            <p style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
              {t('ic.implied.loading')}
            </p>
          )}

          {seed && (
            <>
              <p
                style={{
                  fontFamily: 'var(--font-body)',
                  fontSize: 12.5,
                  lineHeight: 1.6,
                  color: 'var(--text-secondary)',
                  margin: '8px 0 14px',
                }}
              >
                {t('ic.implied.lede')}
              </p>

              {/* Three anchor cards */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                  gap: 10,
                  marginBottom: 18,
                }}
              >
                <AnchorCard
                  axis={t('ic.implied.axis.growth')}
                  verdict={growthVerdict(seed.reverse_growth?.implied_growth ?? null)}
                  value={
                    seed.reverse_growth?.implied_growth != null
                      ? `${(seed.reverse_growth.implied_growth * 100).toFixed(0)}%`
                      : t('ic.implied.unreachable')
                  }
                  message={seed.reverse_growth?.message ?? null}
                />
                <AnchorCard
                  axis={t('ic.implied.axis.wacc')}
                  verdict={waccVerdict(seed.reverse_wacc?.implied_wacc ?? null)}
                  value={
                    seed.reverse_wacc?.implied_wacc != null
                      ? `${(seed.reverse_wacc.implied_wacc * 100).toFixed(1)}%`
                      : '—'
                  }
                  message={seed.reverse_wacc?.message ?? null}
                />
                <AnchorCard
                  axis={t('ic.implied.axis.horizon')}
                  verdict={horizonVerdict(seed.reverse_horizon?.implied_horizon ?? null)}
                  value={
                    seed.reverse_horizon?.implied_horizon != null
                      ? `${seed.reverse_horizon.implied_horizon.toFixed(1)} ${t('ic.implied.years')}`
                      : t('ic.implied.unreachable')
                  }
                  message={seed.reverse_horizon?.message ?? null}
                />
              </div>

              {/* Equivalence line */}
              {line && (
                <div>
                  <div
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: 10.5,
                      color: 'var(--text-muted)',
                      marginBottom: 6,
                    }}
                  >
                    {t('ic.implied.lineTitle')} ·{' '}
                    <span style={{ color: 'var(--accent-cyan)' }}>
                      {t('ic.implied.fixedWacc')} {((wacc ?? line.wacc) * 100).toFixed(1)}%
                    </span>
                  </div>
                  <ResponsiveContainer width="100%" height={190}>
                    <LineChart
                      data={line.points.map((p) => ({
                        g: p.growth * 100,
                        h: p.implied_horizon,
                      }))}
                      margin={{ top: 8, right: 12, bottom: 4, left: 0 }}
                    >
                      <XAxis
                        dataKey="g"
                        type="number"
                        domain={['dataMin', 'dataMax']}
                        tickFormatter={(v: number) => `${v.toFixed(0)}%`}
                        tick={AXIS_TICK}
                        axisLine={{ stroke: 'var(--border-soft)' }}
                        tickLine={false}
                      />
                      <YAxis
                        orientation="left"
                        width={42}
                        tickFormatter={(v: number) => `${v.toFixed(0)}y`}
                        tick={AXIS_TICK}
                        axisLine={false}
                        tickLine={false}
                        tickCount={5}
                      />
                      <Tooltip
                        content={<LineTooltip yearsLabel={t('ic.implied.years')} />}
                        cursor={{ stroke: 'var(--border-glow)' }}
                      />
                      <Line
                        type="monotone"
                        dataKey="h"
                        stroke="var(--accent-violet, var(--primary))"
                        strokeWidth={1.8}
                        dot={false}
                        connectNulls={false}
                        isAnimationActive={false}
                      />
                      {seed.reverse_horizon?.assumed_growth != null &&
                        seed.reverse_horizon.implied_horizon != null && (
                          <ReferenceDot
                            x={seed.reverse_horizon.assumed_growth * 100}
                            y={seed.reverse_horizon.implied_horizon}
                            r={4}
                            fill="var(--accent-cyan)"
                            stroke="var(--bg-deep)"
                            strokeWidth={1.5}
                          />
                        )}
                    </LineChart>
                  </ResponsiveContainer>

                  {/* WACC slider — shifts the whole line (the third axis) */}
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 12,
                      marginTop: 8,
                      fontFamily: 'var(--font-mono)',
                      fontSize: 10.5,
                      color: 'var(--text-muted)',
                    }}
                  >
                    <span>{t('ic.implied.waccSlider')}</span>
                    <input
                      type="range"
                      min={6}
                      max={20}
                      step={0.5}
                      value={(wacc ?? line.wacc) * 100}
                      onChange={(e) => onWacc(Number(e.target.value) / 100)}
                      style={{ flex: 1, accentColor: 'var(--accent-violet, var(--primary))' }}
                    />
                    <span
                      style={{ color: 'var(--text-secondary)', fontVariantNumeric: 'tabular-nums' }}
                    >
                      {((wacc ?? line.wacc) * 100).toFixed(1)}%
                    </span>
                  </div>
                </div>
              )}

              <p
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 10,
                  lineHeight: 1.6,
                  color: 'var(--text-dim)',
                  margin: '14px 0 0',
                  borderTop: '1px solid var(--border-soft)',
                  paddingTop: 10,
                }}
              >
                ⓘ {t('ic.implied.priorNote')}
              </p>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function AnchorCard({
  axis,
  verdict,
  value,
  message,
}: {
  axis: string
  verdict: 'distorted' | 'arguable' | 'unreachable'
  value: string
  message: string | null
}): React.ReactElement {
  const b = badge(verdict)
  return (
    <div
      style={{
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-sm)',
        padding: '10px 12px',
        background: 'color-mix(in srgb, var(--primary) 4%, transparent)',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          gap: 6,
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          letterSpacing: '0.06em',
          color: 'var(--text-muted)',
          textTransform: 'uppercase',
        }}
      >
        {axis}
        <span style={{ marginLeft: 'auto', color: b.color }}>{b.mark}</span>
      </div>
      <div
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 20,
          color: 'var(--text-primary)',
          margin: '4px 0 6px',
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {value}
      </div>
      {message && (
        <div
          style={{
            fontFamily: 'var(--font-body)',
            fontSize: 11,
            lineHeight: 1.5,
            color: 'var(--text-dim)',
          }}
        >
          {message}
        </div>
      )}
    </div>
  )
}

interface LineTooltipItem {
  payload: { g: number; h: number | null }
}
function LineTooltip({
  active,
  payload,
  yearsLabel,
}: {
  active?: boolean
  payload?: LineTooltipItem[]
  yearsLabel?: string
}): React.ReactElement | null {
  if (!active || !payload || payload.length === 0) return null
  const p = payload[0].payload
  return (
    <CosmicTooltipShell label={`${p.g.toFixed(0)}% 增长`}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16 }}>
        <span style={{ color: 'var(--text-secondary)' }}>隐含年限</span>
        <span style={{ color: 'var(--text-primary)', fontVariantNumeric: 'tabular-nums' }}>
          {p.h != null ? `${p.h.toFixed(1)} ${yearsLabel ?? 'y'}` : '够不着'}
        </span>
      </div>
    </CosmicTooltipShell>
  )
}
