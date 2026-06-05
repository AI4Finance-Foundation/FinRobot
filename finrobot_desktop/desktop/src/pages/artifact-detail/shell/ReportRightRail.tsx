import { useCallback, useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { BASE_URL } from '../../../api/client'
import { fetchWithTimeout, HEAVY_API_TIMEOUT_MS } from '../../../api/fetch'
import type { ArtifactSummaryV5, Signal } from '../../../types/v5'
import { useI18n, type Locale } from '../../../i18n'
import { formatDate } from '../../../utils/format'
import { verdictLabel, verdictTone } from '../../../utils/verdict'

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

interface DcfWhatIfResponse {
  artifact_id: string
  inputs: { wacc?: number; terminal_growth_rate?: number } & Record<string, unknown>
  result: { implied_price: number; wacc: number }
  base_implied_price: number
}

interface PostDcfWhatIfBody {
  artifactId: string
  wacc_override: number
  tg_override: number
  growth_scale_override: number | null
}

/**
 * Replay the CURRENT artifact's FROZEN DCF inputs, overriding only the slider
 * field(s). Hits /api/compute/artifacts/{id}/what-if/dcf — NOT the live
 * /dcf-seed reseed path — so the BASE→NEW delta is attributable solely to the
 * slider, never to data drift (latest price/financials/Damodaran fallback).
 */
async function postDcfWhatIf({
  artifactId,
  ...overrides
}: PostDcfWhatIfBody): Promise<DcfWhatIfResponse> {
  const resp = await fetchWithTimeout(
    `${BASE_URL}/api/compute/artifacts/${encodeURIComponent(artifactId)}/what-if/dcf`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...overrides, mid_year: false }),
    },
    HEAVY_API_TIMEOUT_MS,
  )
  if (!resp.ok) {
    const detail = await resp.text().catch(() => '')
    throw new Error(`${resp.status} ${detail.slice(0, 160)}`)
  }
  return (await resp.json()) as DcfWhatIfResponse
}

// How many of the newest same-type versions the rail timeline renders. The
// total count still shows in the panel header, so the cap never reads as
// "this is all of them".
const MAX_TIMELINE_ROWS = 8

// Distance (px) from a row's top edge to its dot centre — kept in one place so
// the connecting spine segments line up exactly with the dots.
const DOT_CENTER = 16

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
      <RailPanel
        title={t('report.rightRail.timeline')}
        headerAction={
          sameType.length > 0 ? (
            <span style={{ color: 'var(--text-muted)', fontWeight: 400, letterSpacing: '0.04em' }}>
              {t('report.timeline.versionCount', { count: sameType.length })}
            </span>
          ) : undefined
        }
      >
        {sameType.length === 0 ? (
          <p style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
            {t('report.timeline.empty')}
          </p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {sameType.slice(0, MAX_TIMELINE_ROWS).map((a, i, rows) => (
              <TimelineRow
                key={a.id}
                artifact={a}
                // Version number counts from the FULL same-type history (newest
                // = vN), not the sliced window — so the cap never renumbers.
                version={sameType.length - i}
                current={a.id === currentArtifactId}
                isFirst={i === 0}
                isLast={i === rows.length - 1}
                locale={locale}
                t={t}
                onClick={() => navigate(`/stocks/${ticker}/runs/${a.id}`)}
              />
            ))}
          </div>
        )}
      </RailPanel>

      {/* key={currentArtifactId} forces a fresh remount when the report version
          changes, so the sliders reset to the NEW artifact's base assumptions
          instead of keeping the previous report's WACC/TG (BUG-007). */}
      <WhatIfEditor
        key={currentArtifactId}
        artifactId={currentArtifactId}
        initialWacc={wacc}
        initialTg={terminalGrowth}
        originalImpliedPrice={originalImpliedPrice}
      />
    </aside>
  )
}

export function WhatIfEditor({
  artifactId,
  initialWacc,
  initialTg,
  originalImpliedPrice,
}: {
  artifactId: string
  initialWacc: number | null
  initialTg: number | null
  originalImpliedPrice: number | null
}): React.ReactElement {
  const { t } = useI18n()
  const baseWacc = initialWacc ?? 0.1
  const baseTg = initialTg ?? 0.025

  const [waccPct, setWaccPct] = useState<number>(baseWacc * 100)
  const [tgPct, setTgPct] = useState<number>(baseTg * 100)
  // Revenue growth scale: 0 = seeded growth schedule untouched.
  // Slider is in percent (-50 .. +50) → backend gets it as fraction (-0.5 .. +0.5).
  const [growthScalePct, setGrowthScalePct] = useState<number>(0)

  const mutation = useMutation({
    mutationFn: postDcfWhatIf,
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
        artifactId,
        wacc_override: waccPct / 100,
        tg_override: tgPct / 100,
        growth_scale_override: growthDirty ? growthScalePct / 100 : null,
      })
    }, 380)
    return () => clearTimeout(handle)
  }, [waccPct, tgPct, growthScalePct, artifactId, baseWacc, baseTg])

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
      title={t('report.rightRail.whatif')}
      headerAction={
        dirty ? (
          <button
            type="button"
            onClick={handleReset}
            style={resetButtonStyle}
            title={t('report.rightRail.resetTitle')}
            data-testid="whatif-reset"
          >
            {t('report.rightRail.reset')}
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
        label={t('report.rightRail.terminalGrowth')}
        valueLabel={`${tgPct.toFixed(2)}%`}
        min={-2}
        max={5}
        step={0.1}
        value={tgPct}
        onChange={setTgPct}
        testid="whatif-slider-tg"
      />
      <SliderRow
        label={t('report.rightRail.revenueGrowthScale')}
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
  const { t } = useI18n()
  return (
    <div
      data-testid="whatif-compare"
      style={{
        marginTop: 12,
        padding: '10px 12px',
        background: 'var(--bg-card-deep)',
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
          letterSpacing: 0,
        }}
      >
        →
      </span>

      {isError ? (
        <div
          style={{ fontSize: 10.5, color: 'var(--danger)', textAlign: 'right' }}
          data-testid="whatif-error"
        >
          {t('report.rightRail.recomputeError')}
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
            {isPending
              ? t('report.rightRail.computing')
              : newImplied !== null
                ? `$${newImplied.toFixed(2)}`
                : '—'}
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

/**
 * One version on the rail timeline: spine segment + status dot on the left,
 * `vN` / NOW|ARCH / date on the first line, and `$target` / verdict / outcome
 * on the second. Every value is real persisted/computed data — no placeholders.
 */
function TimelineRow({
  artifact: a,
  version,
  current,
  isFirst,
  isLast,
  locale,
  t,
  onClick,
}: {
  artifact: ArtifactSummaryV5
  version: number
  current: boolean
  isFirst: boolean
  isLast: boolean
  locale: Locale
  t: ReturnType<typeof useI18n>['t']
  onClick: () => void
}): React.ReactElement {
  const target = a.target_price
  const hasTarget = target !== null && target !== undefined
  return (
    <button
      type="button"
      data-testid={`timeline-${a.id}`}
      onClick={onClick}
      style={{
        display: 'grid',
        gridTemplateColumns: '20px 1fr',
        gap: 6,
        width: '100%',
        textAlign: 'left',
        // No row gap: vertical padding instead, so adjacent rail cells touch and
        // the spine reads as one continuous line through the dots.
        padding: '8px 6px 14px',
        background: current
          ? 'color-mix(in srgb, var(--secondary) 7%, transparent)'
          : 'transparent',
        border: 'none',
        borderRadius: 6,
        cursor: current ? 'default' : 'pointer',
        fontFamily: 'var(--font-mono)',
        color: 'var(--text-primary)',
        // Dim retired (stale-archived) versions so they read as history, not as
        // the current track record (BUG-055).
        opacity: a.archived && !current ? 0.55 : 1,
      }}
    >
      <span style={{ position: 'relative', display: 'block' }} aria-hidden>
        {!(isFirst && isLast) && (
          <span
            style={{
              position: 'absolute',
              left: '50%',
              transform: 'translateX(-50%)',
              width: 2,
              background: 'var(--border-soft)',
              top: isFirst ? DOT_CENTER : 0,
              ...(isLast ? { height: DOT_CENTER } : { bottom: 0 }),
            }}
          />
        )}
        <VersionDot current={current} signal={a.signal} />
      </span>

      <span style={{ display: 'block', minWidth: 0 }}>
        <span style={{ display: 'flex', alignItems: 'baseline', gap: 6, fontSize: 12 }}>
          <span style={{ fontWeight: 600 }}>v{version}</span>
          {current ? (
            <StatusPill tone="now" label={t('report.timeline.current')} />
          ) : a.archived ? (
            <StatusPill tone="arch" label={t('report.timeline.archived')} />
          ) : null}
          <span
            style={{
              marginLeft: 'auto',
              fontSize: 10,
              fontWeight: 400,
              color: 'var(--text-dim)',
              whiteSpace: 'nowrap',
            }}
          >
            {formatDate(a.created_at, locale, 'short')}
          </span>
        </span>
        <span
          style={{
            display: 'flex',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: 6,
            marginTop: 4,
          }}
        >
          <span
            style={{
              fontSize: 12.5,
              color: hasTarget ? 'var(--text-secondary)' : 'var(--text-dim)',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {target !== null && target !== undefined ? `$${target.toFixed(2)}` : '—'}
          </span>
          <VerdictBadge verdict={a.verdict} />
          <SignalBadge signal={a.signal} t={t} />
        </span>
      </span>
    </button>
  )
}

/**
 * Status dot. Current = filled cyan (the live version); past versions = a
 * hollow ring coloured by realised outcome (hit→green, failed→red,
 * watching/withheld→muted) so colour reads as a marker, not a heavy bullet.
 */
function VersionDot({
  current,
  signal,
}: {
  current: boolean
  signal: Signal | null | undefined
}): React.ReactElement {
  const size = current ? 11 : 10
  const color = current
    ? 'var(--accent-cyan)'
    : signal === 'hit'
      ? 'var(--success)'
      : signal === 'failed'
        ? 'var(--danger)'
        : 'var(--text-muted)'
  return (
    <span
      style={{
        position: 'absolute',
        left: '50%',
        top: DOT_CENTER,
        transform: 'translate(-50%, -50%)',
        width: size,
        height: size,
        borderRadius: '50%',
        background: current ? color : 'var(--bg-card)',
        border: `2px solid ${color}`,
        boxShadow: current ? `0 0 8px ${color}` : 'none',
      }}
    />
  )
}

/** NOW (current version) / ARCH (stale-archived) marker pill. */
function StatusPill({ tone, label }: { tone: 'now' | 'arch'; label: string }): React.ReactElement {
  const now = tone === 'now'
  return (
    <span
      style={{
        fontSize: 9,
        padding: '1px 5px',
        borderRadius: 3,
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
        whiteSpace: 'nowrap',
        color: now ? 'var(--accent-cyan)' : 'var(--text-dim)',
        border: `1px solid ${
          now ? 'color-mix(in srgb, var(--accent-cyan) 50%, transparent)' : 'var(--text-dim)'
        }`,
        background: now ? 'color-mix(in srgb, var(--accent-cyan) 12%, transparent)' : 'transparent',
      }}
    >
      {label}
    </span>
  )
}

/** BUY / HOLD / SELL / REVIEW recommendation badge (localised; shared tone). */
function VerdictBadge({
  verdict,
}: {
  verdict: string | null | undefined
}): React.ReactElement | null {
  if (!verdict) return null
  const tone = verdictTone(verdict)
  return (
    <span
      style={{
        fontSize: 9.5,
        padding: '1px 6px',
        borderRadius: 3,
        background: tone.bg,
        color: tone.fg,
        border: `1px solid ${tone.border}`,
        letterSpacing: '0.06em',
        whiteSpace: 'nowrap',
      }}
    >
      {verdictLabel(verdict)}
    </span>
  )
}

/** Realised-vs-target outcome badge (hit / watching / failed), localised. */
function SignalBadge({
  signal,
  t,
}: {
  signal: Signal | null | undefined
  t: ReturnType<typeof useI18n>['t']
}): React.ReactElement | null {
  if (!signal) return null
  const colors = {
    hit: { bg: 'var(--success-soft)', fg: 'var(--success)' },
    watching: { bg: 'var(--warning-soft)', fg: 'var(--warning)' },
    failed: { bg: 'var(--danger-soft)', fg: 'var(--danger)' },
  } as const
  const c = colors[signal]
  return (
    <span
      style={{
        fontSize: 9.5,
        padding: '1px 6px',
        borderRadius: 3,
        background: c.bg,
        color: c.fg,
        letterSpacing: '0.06em',
        whiteSpace: 'nowrap',
      }}
    >
      {t(`signal.${signal}`)}
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
