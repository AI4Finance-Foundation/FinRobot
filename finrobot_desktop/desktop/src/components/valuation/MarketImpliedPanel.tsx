// MarketImpliedPanel — the "market-implied expectations" reverse-DCF probe.
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
// A ticker-level live probe (seeds its own DCF from current price, NOT a frozen
// artifact). Lives in the stock workspace next to the live market data.
// Default-collapsed: the analyst opens it to interrogate what today's price
// requires to believe.

import { useCallback, useEffect, useRef, useState } from 'react'
import { Line, LineChart, ReferenceDot, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { BASE_URL } from '../../api/client'
import { extractErrorDetail } from '../../api/errors'
import { fetchWithTimeout } from '../../api/fetch'
import { useI18n } from '../../i18n'
import { FetchHttpError, mapErrorToUserMessage } from '../../utils/errorMessage'
import { CosmicTooltipShell } from '../charts/chartTooltip'
import { SkelBar } from '../Skeleton'

// The reverse solver's outcome code (mirrors backend ReverseSolveReason). The
// operator emits this machine code, not prose — the localized sentence is built
// here so it goes through i18n instead of rendering a raw backend string.
type ReverseReasonCode =
  | 'solved'
  | 'not_converged'
  | 'target_above_range'
  | 'target_below_range'
  | 'out_of_wacc_range'
  | 'gordon_undefined'

interface ReverseResult {
  solve_for: string
  implied_growth: number | null
  implied_wacc: number | null
  implied_horizon: number | null
  assumed_growth: number | null
  wacc: number | null
  terminal_growth: number
  target_price: number
  horizon_years: number
  bracket: number[]
  price_at_lo: number
  price_at_hi: number
  reason_code: ReverseReasonCode | null
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

async function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const res = await fetchWithTimeout(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok) {
    // Carry the backend's user-facing `detail` into the typed error so the
    // panel surfaces the real reason via mapErrorToUserMessage instead of a
    // dev string like "/api/compute/dcf-seed → 503".
    throw new FetchHttpError(res.status, res.statusText, await extractErrorDetail(res, ''))
  }
  return (await res.json()) as T
}

// Abort (unmount / ticker switch / superseded slider fetch) is a cancellation,
// never an error to render red.
function isAbortError(e: unknown): boolean {
  return e instanceof DOMException && e.name === 'AbortError'
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

// Map the operator's structured reason_code to a localized sentence, filling the
// numbers from the same result fields the solver already returned (no value is
// recomputed for display). Returns null when there is no code to surface — the
// growth/wacc solvers omit a code on a clean solve, so their cards show only the
// headline value. above/below-range and the success path are axis-specific
// because the original prose framed growth, WACC and horizon differently.
function reasonText(
  r: ReverseResult,
  t: (key: string, params?: Record<string, string | number>) => string,
): string | null {
  if (!r.reason_code) return null
  const pct0 = (x: number): string => (x * 100).toFixed(0)
  const pct1 = (x: number): string => (x * 100).toFixed(1)
  const usd = (x: number): string => x.toFixed(2)
  const [lo, hi] = r.bracket
  switch (r.reason_code) {
    case 'solved':
      return t('valuation.implied.reason.solved', {
        growth: pct0(r.assumed_growth ?? 0),
        wacc: pct1(r.wacc ?? 0),
        target: usd(r.target_price),
        horizon: (r.implied_horizon ?? 0).toFixed(1),
      })
    case 'not_converged':
      return t('valuation.implied.reason.notConverged')
    case 'out_of_wacc_range':
      return t('valuation.implied.reason.outOfWaccRange', {
        target: usd(r.target_price),
        lo: pct0(lo),
        hi: pct0(hi),
        priceLo: usd(r.price_at_lo),
        priceHi: usd(r.price_at_hi),
      })
    case 'gordon_undefined':
      return t('valuation.implied.reason.gordonUndefined', {
        growth: pct0(r.assumed_growth ?? 0),
        tg: pct1(r.terminal_growth),
        wacc: pct1(r.wacc ?? 0),
      })
    case 'target_above_range':
    case 'target_below_range': {
      const above = r.reason_code === 'target_above_range'
      if (r.solve_for === 'horizon') {
        // Horizon bracket carries integer years; prose frames it against the
        // fixed growth and the 1–Ny reachable price band.
        return t(
          above
            ? 'valuation.implied.reason.horizon.aboveRange'
            : 'valuation.implied.reason.horizon.belowRange',
          {
            growth: pct0(r.assumed_growth ?? 0),
            target: usd(r.target_price),
            maxHorizon: r.horizon_years,
            priceLo: usd(r.price_at_lo),
            priceHi: usd(r.price_at_hi),
          },
        )
      }
      return t(
        above
          ? 'valuation.implied.reason.growth.aboveRange'
          : 'valuation.implied.reason.growth.belowRange',
        {
          target: usd(r.target_price),
          lo: pct0(lo),
          hi: pct0(hi),
          priceLo: usd(r.price_at_lo),
          priceHi: usd(r.price_at_hi),
        },
      )
    }
  }
}

interface Props {
  ticker: string
  /** Override target price; defaults to the backend's current price. */
  targetPrice?: number | null
}

export function MarketImpliedPanel({ ticker }: Props): React.ReactElement | null {
  const { t } = useI18n()
  // Expanded by default — this probe is a primary valuation surface in the
  // workspace, not an opt-in drill-down. The toggle still lets the analyst
  // collapse it when the data rail gets long.
  const [open, setOpen] = useState(true)
  const [seed, setSeed] = useState<SeedReverse | null>(null)
  const [line, setLine] = useState<EquivLine | null>(null)
  const [wacc, setWacc] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Cold-start 503: the compute engine is still warming (~2s post-boot). Show a
  // CALM state + auto-retry, never a red error — this panel is a manual fetch
  // (no react-query refetchInterval), so it must drive its own self-heal the way
  // the live-data cards do. `retry` bumps to re-trigger the lazy-load effect.
  const [warming, setWarming] = useState(false)
  const [retry, setRetry] = useState(0)
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null)
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  // In-flight equivalence-line POST. Each new fetch aborts the previous one —
  // only the latest WACC matters, and a stale multi-second POST would
  // otherwise keep holding a heavy-lane slot (and a browser socket) after
  // unmount / ticker switch / a superseding slider drag.
  const lineAbort = useRef<AbortController | null>(null)

  const fetchLine = useCallback(
    async (waccOverride: number | null) => {
      lineAbort.current?.abort()
      const controller = new AbortController()
      lineAbort.current = controller
      try {
        const l = await postJson<EquivLine>(
          '/api/compute/dcf-equivalence-line',
          {
            ticker,
            wacc_override: waccOverride,
            growth_lo: 0.2,
            growth_hi: 0.5,
            steps: 13,
          },
          controller.signal,
        )
        setLine(l)
        if (waccOverride === null) setWacc(l.wacc)
      } catch (e) {
        if (isAbortError(e)) return
        setError(mapErrorToUserMessage(e))
      }
    },
    [ticker],
  )

  // Reset the cached probe state when the ticker changes. The lazy-load
  // effect below guards on `seed`, so without this reset a mount point that
  // survives navigation (/stocks/AAPL → /stocks/MSFT renders the same element)
  // kept showing AAPL's market-implied growth/WACC under MSFT's header — a
  // wrong-ticker number on an analyst-facing panel.
  const lastTicker = useRef(ticker)
  useEffect(() => {
    if (lastTicker.current === ticker) return
    lastTicker.current = ticker
    // Stay expanded across ticker changes (default-open); just drop the cached
    // numbers so the effect below re-fetches for the new ticker.
    setOpen(true)
    setSeed(null)
    setLine(null)
    setWacc(null)
    setError(null)
    setWarming(false)
    if (retryTimer.current) clearTimeout(retryTimer.current)
    // The old ticker's line fetch must not keep holding a socket (or land its
    // stale curve) under the new ticker's header.
    lineAbort.current?.abort()
  }, [ticker])

  // Fetch when open and not yet seeded. Open defaults true, so this fires on
  // mount; collapsing then re-opening reuses the cached seed.
  useEffect(() => {
    if (!open || seed) return
    let cancelled = false
    // Abortable so cleanup actually CANCELS the in-flight POST (frees its
    // heavy-lane slot + browser socket) instead of merely ignoring the result:
    // StrictMode's dev double-mount fired a duplicate dcf-seed that ran to
    // completion, and a ticker switch left the old ticker's multi-second
    // compute holding a connection under the new page.
    const controller = new AbortController()
    // Clear any prior error before each attempt so a recovered fetch never
    // double-renders the stale red message alongside fresh data.
    setError(null)
    void (async () => {
      try {
        const s = await postJson<SeedReverse>(
          '/api/compute/dcf-seed',
          {
            ticker,
            include_reverse: true,
          },
          controller.signal,
        )
        if (cancelled) return
        setWarming(false)
        setSeed(s)
        await fetchLine(null)
      } catch (e) {
        if (cancelled || isAbortError(e)) return
        if (e instanceof FetchHttpError && e.status === 503) {
          // Engine still warming — calm "starting" state + auto-retry in ~2s,
          // never red. Self-resolves the moment the provider chain is wired.
          setWarming(true)
          retryTimer.current = setTimeout(() => setRetry((n) => n + 1), 2000)
        } else {
          setWarming(false)
          setError(mapErrorToUserMessage(e))
        }
      }
    })()
    return () => {
      cancelled = true
      // Abort ONLY this run's seed POST. The equivalence-line fetch is NOT
      // aborted here: setSeed re-runs this effect (seed is a dep) and this
      // cleanup fires while fetchLine(null) is mid-flight — killing it here
      // would mean the line never loads. lineAbort is handled by the
      // ticker-reset effect and the unmount effect below.
      controller.abort()
      if (retryTimer.current) clearTimeout(retryTimer.current)
    }
  }, [open, seed, ticker, fetchLine, retry])

  // Unmount: cancel whatever line fetch is still in flight so it releases its
  // heavy-lane slot + socket instead of running to a discarded completion.
  useEffect(
    () => () => {
      lineAbort.current?.abort()
    },
    [],
  )

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
        background: 'var(--surface-panel-50)',
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
        {t('valuation.implied.title')}
        <span style={{ color: 'var(--text-dim)', textTransform: 'none', letterSpacing: 0 }}>
          {t('valuation.implied.subtitle')}
        </span>
        <span style={{ marginLeft: 'auto', color: 'var(--text-muted)' }}>{open ? '▾' : '▸'}</span>
      </button>

      {open && (
        <div style={{ padding: '4px 16px 18px' }}>
          {/* Cold-start 503 → calm "engine starting" + pulse dot, never red
              (mirrors the live-data cards' CardError 503 path); auto-retries. */}
          {warming && !seed && (
            <span
              data-testid="market-implied-starting"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                color: 'var(--text-secondary)',
              }}
            >
              <span
                aria-hidden="true"
                className="cosmic-pulse-dot"
                style={{
                  width: 6,
                  height: 6,
                  background: 'var(--primary)',
                  boxShadow: '0 0 10px var(--primary-soft)',
                }}
              />
              {t('workspace.market.engineStarting')}
            </span>
          )}
          {error && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
              <span
                style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--danger)' }}
              >
                ⚠ {error}
              </span>
              <button
                type="button"
                onClick={() => {
                  setError(null)
                  setRetry((n) => n + 1)
                }}
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 10.5,
                  color: 'var(--danger)',
                  background: 'var(--negative-bg)',
                  border: '1px solid var(--danger)',
                  borderRadius: 4,
                  padding: '3px 11px',
                  cursor: 'pointer',
                  letterSpacing: '0.04em',
                }}
              >
                {t('workspace.market.retry')}
              </button>
            </div>
          )}
          {!error && !warming && !seed && (
            <MarketImpliedSkeleton label={t('valuation.implied.loading')} />
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
                {t('valuation.implied.lede')}
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
                  axis={t('valuation.implied.axis.growth')}
                  verdict={growthVerdict(seed.reverse_growth?.implied_growth ?? null)}
                  value={
                    seed.reverse_growth?.implied_growth != null
                      ? `${(seed.reverse_growth.implied_growth * 100).toFixed(0)}%`
                      : t('valuation.implied.unreachable')
                  }
                  message={seed.reverse_growth ? reasonText(seed.reverse_growth, t) : null}
                />
                <AnchorCard
                  axis={t('valuation.implied.axis.wacc')}
                  verdict={waccVerdict(seed.reverse_wacc?.implied_wacc ?? null)}
                  value={
                    seed.reverse_wacc?.implied_wacc != null
                      ? `${(seed.reverse_wacc.implied_wacc * 100).toFixed(1)}%`
                      : '—'
                  }
                  message={seed.reverse_wacc ? reasonText(seed.reverse_wacc, t) : null}
                />
                <AnchorCard
                  axis={t('valuation.implied.axis.horizon')}
                  verdict={horizonVerdict(seed.reverse_horizon?.implied_horizon ?? null)}
                  value={
                    seed.reverse_horizon?.implied_horizon != null
                      ? `${seed.reverse_horizon.implied_horizon.toFixed(1)} ${t('valuation.implied.years')}`
                      : t('valuation.implied.unreachable')
                  }
                  message={seed.reverse_horizon ? reasonText(seed.reverse_horizon, t) : null}
                />
              </div>

              {/* Equivalence line — guard on points so a partial/malformed
                  response (no points array) degrades to no-chart, never a crash. */}
              {line?.points && (
                <div>
                  <div
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: 10.5,
                      color: 'var(--text-muted)',
                      marginBottom: 6,
                    }}
                  >
                    {t('valuation.implied.lineTitle')} ·{' '}
                    <span style={{ color: 'var(--accent-cyan)' }}>
                      {t('valuation.implied.fixedWacc')} {((wacc ?? line.wacc) * 100).toFixed(1)}%
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
                        content={<LineTooltip />}
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
                    <span>{t('valuation.implied.waccSlider')}</span>
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
                ⓘ {t('valuation.implied.priorNote')}
              </p>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// Fixed-height placeholder for the normal dcf-seed fetch window (the cold-start
// 503 "engine starting" + the error path have their own states above). Mirrors
// the seeded layout block-for-block — lede line, three anchor cards (same chrome
// as AnchorCard), the equivalence-line chart area (190px, matching its
// ResponsiveContainer), the WACC slider, and the prior note — so the panel body
// holds its height and the data column doesn't reflow when the probe resolves.
function MarketImpliedSkeleton({ label }: { label: string }): React.ReactElement {
  return (
    <div data-testid="market-implied-skeleton" aria-busy="true" aria-label={label}>
      {/* lede */}
      <div style={{ margin: '8px 0 14px' }}>
        <SkelBar height={11} width="92%" />
        <div style={{ marginTop: 6 }}>
          <SkelBar height={11} width="64%" />
        </div>
      </div>

      {/* three anchor cards — same grid + card chrome as the seeded render */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: 10,
          marginBottom: 18,
        }}
      >
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            style={{
              border: '1px solid var(--border-soft)',
              borderRadius: 'var(--radius-sm)',
              padding: '10px 12px',
              background: 'color-mix(in srgb, var(--primary) 4%, transparent)',
            }}
          >
            <SkelBar height={9} width="56%" />
            <div style={{ margin: '8px 0' }}>
              <SkelBar height={18} width="46%" />
            </div>
            {/* anchor cards carry a ~5-line reason prose under the value — match
                that line count so the card height tracks the loaded render. */}
            <SkelBar height={9} width="92%" />
            <div style={{ marginTop: 5 }}>
              <SkelBar height={9} width="88%" />
            </div>
            <div style={{ marginTop: 5 }}>
              <SkelBar height={9} width="84%" />
            </div>
            <div style={{ marginTop: 5 }}>
              <SkelBar height={9} width="76%" />
            </div>
            <div style={{ marginTop: 5 }}>
              <SkelBar height={9} width="54%" />
            </div>
          </div>
        ))}
      </div>

      {/* equivalence-line chart area */}
      <div style={{ marginBottom: 6 }}>
        <SkelBar height={10} width="56%" />
      </div>
      <SkelBar height={190} width="100%" />
      <div style={{ marginTop: 8 }}>
        <SkelBar height={10} width="100%" radius={999} />
      </div>

      {/* prior note (two lines, matching the wrapped footnote) */}
      <div style={{ marginTop: 14, borderTop: '1px solid var(--border-soft)', paddingTop: 10 }}>
        <SkelBar height={8} width="96%" />
        <div style={{ marginTop: 5 }}>
          <SkelBar height={8} width="62%" />
        </div>
      </div>
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
}: {
  active?: boolean
  payload?: LineTooltipItem[]
}): React.ReactElement | null {
  const { t } = useI18n()
  if (!active || !payload || payload.length === 0) return null
  const p = payload[0].payload
  return (
    <CosmicTooltipShell label={t('valuation.implied.tooltip.growth', { g: p.g.toFixed(0) })}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16 }}>
        <span style={{ color: 'var(--text-secondary)' }}>
          {t('valuation.implied.tooltip.impliedYears')}
        </span>
        <span style={{ color: 'var(--text-primary)', fontVariantNumeric: 'tabular-nums' }}>
          {p.h != null
            ? `${p.h.toFixed(1)} ${t('valuation.implied.years')}`
            : t('valuation.implied.unreachable')}
        </span>
      </div>
    </CosmicTooltipShell>
  )
}
