// Standalone valuation INSTRUMENTS — the second run entry beside the flagship
// 13-chapter research CTA. The four single-method valuations (DCF / DDM / LBO /
// Comps) as live instruments: each tile shows its LATEST reading + version, an
// idle "run" affordance, or — while running — inline progress INSIDE the tile.
//
// Design contract (approved D-hybrid mock, 2026-06-25): an instrument run
// renders HERE, in place. It never takes over the flagship report's top progress
// panel (that is reserved for the equity_research run). Reports and the four
// valuations are symmetric versioned artifact chains (each rerun = a new
// immutable artifact); the report is the flagship you track for thesis drift,
// the valuations are reference instruments — same versioning, asymmetric
// prominence. Numbers are read from the SAME field paths the detail page uses
// (CompactArtifactViewer.deriveHeadline) so a card and its detail never drift:
//   dcf  → summary.target_price (== structured.implied_price, USD-normalised)
//   ddm  → summary.target_price (== structured.equity_value_per_share)
//   lbo  → detail.structured.irr / .moic   (returns model, no single price)
//   comps→ detail.structured.median_ev_ebitda / .median_pe / .median_pb
// A method that did not compute (None / withheld) shows "withheld", never a
// fabricated number.

import { useNavigate } from 'react-router-dom'
import { useArtifactDetail } from '../../hooks/useV5Artifacts'
import { formatCurrency, formatPercent, formatAge } from '../../utils/format'
import type { Locale } from '../../i18n'
import type { ArtifactSummaryV5 } from '../../types/v5'
import type { RunState } from '../../stores/runStreamStore'
import { artifactTypeLabel } from './artifactLabels'
import { SETTINGS_ALLOWED } from '../../config/deployment'

// Inline union (1-line) per the codebase's VersionDiffBanner precedent — avoids
// a circular import back to AIZone, which owns the canonical preflight machinery.
export type PreflightReason = 'offline' | 'needsModel' | 'config' | 'providers' | null

/**
 * What a blocked run CTA should say.
 *
 * On a hosted deployment (SETTINGS_ALLOWED=false) the configuration is shared
 * by everyone and only an administrator may change it, so the viewer has no
 * Settings door at all. Telling them to fix it there would make the CTA a dead
 * end — a button that navigates nowhere. State the condition instead of
 * prescribing a remedy they cannot apply.
 */
export function blockedCtaLabel(reason: PreflightReason, zh: boolean): string {
  if (reason === 'offline') {
    return SETTINGS_ALLOWED
      ? zh
        ? '⚠ 后端未连接 · 重试数据源'
        : '⚠ Backend offline · retry data source'
      : zh
        ? '⚠ 后端未连接'
        : '⚠ Backend offline'
  }
  return SETTINGS_ALLOWED
    ? zh
      ? '⚠ 去设置补全配置'
      : '⚠ Fix config in Settings'
    : zh
      ? '⚠ AI 分析暂不可用'
      : '⚠ AI analysis unavailable'
}

export const VALUATION_TYPES = ['dcf', 'ddm', 'lbo', 'comps'] as const

// Distinct geometric glyphs per method (inline SVG per the project's icon
// convention — Recharts is reserved for real charts). stroke=currentColor so
// each picks up the icon-box accent (blue --primary).
const ICON_DCF = (
  <svg
    width="18"
    height="18"
    viewBox="0 0 20 20"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.6"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M3 3v14h14" />
    <path d="M6 13l3-3 3 1.5 4-6" />
  </svg>
)
const ICON_DDM = (
  <svg
    width="18"
    height="18"
    viewBox="0 0 20 20"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.6"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <circle cx="10" cy="10" r="6.5" />
    <path d="M10 6v8" />
    <path d="M12 8c-.4-.7-1.1-1.1-2-1.1-1.1 0-1.9.6-1.9 1.5 0 2 3.9 1 3.9 3 0 .9-.8 1.6-2 1.6-.9 0-1.7-.4-2.1-1.1" />
  </svg>
)
const ICON_LBO = (
  <svg
    width="18"
    height="18"
    viewBox="0 0 20 20"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.6"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <rect x="3.5" y="4.5" width="13" height="3.5" rx="1" />
    <rect x="3.5" y="11.5" width="13" height="3.5" rx="1" />
    <path d="M10 8v3.5" />
  </svg>
)
const ICON_COMPS = (
  <svg
    width="18"
    height="18"
    viewBox="0 0 20 20"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.6"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <rect x="3.5" y="3.5" width="5.5" height="5.5" rx="1" />
    <rect x="11" y="3.5" width="5.5" height="5.5" rx="1" />
    <rect x="3.5" y="11" width="5.5" height="5.5" rx="1" />
    <rect x="11" y="11" width="5.5" height="5.5" rx="1" />
  </svg>
)

const ICON_CHEVRON = (
  <svg
    width="14"
    height="14"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.6"
  >
    <path d="M6 4l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)
const ICON_RERUN = (
  <svg
    width="13"
    height="13"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
  >
    <path d="M13 8a5 5 0 1 1-1.5-3.5M13 2v3h-3" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

const STANDALONE_METHODS: {
  type: string
  glyph: React.ReactNode
  hint: { zh: string; en: string }
}[] = [
  { type: 'dcf', glyph: ICON_DCF, hint: { zh: '现金流折现内在价值', en: 'Intrinsic value · DCF' } },
  {
    type: 'ddm',
    glyph: ICON_DDM,
    hint: { zh: '股利贴现 · 银行/分红股', en: 'Dividend discount · payers' },
  },
  {
    type: 'lbo',
    glyph: ICON_LBO,
    hint: { zh: '杠杆收购回报 IRR/MOIC', en: 'Buyout returns · IRR/MOIC' },
  },
  {
    type: 'comps',
    glyph: ICON_COMPS,
    hint: { zh: '同业倍数相对估值', en: 'Relative value · peers' },
  },
]

type Tone = 'pos' | 'neg' | 'neutral'

type InstrumentReading =
  | { kind: 'idle' }
  | { kind: 'pending' } // lbo / comps detail still loading
  | {
      kind: 'value'
      primary: string
      secondary?: string
      tone: Tone
      version: number
      age: string
      source?: string
      artifactId: string
    }
  | { kind: 'withheld'; version: number; age: string; artifactId: string }

function toneColor(tone: Tone): string {
  return tone === 'pos'
    ? 'var(--card-buy-fg)'
    : tone === 'neg'
      ? 'var(--card-sell-fg)'
      : 'var(--text-secondary)'
}

function plainNum(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

// Derive the card reading from the timeline summary (+ the full artifact for
// lbo/comps, which carry no single price). Mirrors deriveHeadline's field paths.
function deriveReading(
  type: string,
  summary: ArtifactSummaryV5 | null,
  detail: { outputs?: Record<string, unknown> } | undefined,
  detailLoading: boolean,
  versionCount: number,
  nowPrice: number | null,
  locale: Locale,
): InstrumentReading {
  if (!summary) return { kind: 'idle' }
  const base = { version: versionCount, age: formatAge(summary.created_at), artifactId: summary.id }
  const source = summary.primary_provider ?? undefined

  if (type === 'dcf' || type === 'ddm') {
    // summary.target_price IS the per-share value (USD-normalised invariant).
    const v = summary.target_price
    if (v == null) return { kind: 'withheld', ...base }
    // Delta vs the LIVE USD quote ONLY. When there's no live anchor (provider
    // outage, or a foreign local listing whose live price was dropped upstream),
    // omit the delta rather than silently anchoring to the stale creation price:
    // this tiny secondary string has no room to disclose "vs creation", so
    // degrade = omit (the same honesty rule the AIZone gauge follows when it
    // drops the gauge for a missing now-anchor). livePrice is already USD.
    const ref = nowPrice
    const delta = ref != null && ref !== 0 ? (v - ref) / ref : null
    const tone: Tone = delta == null ? 'neutral' : delta > 0 ? 'pos' : delta < 0 ? 'neg' : 'neutral'
    return {
      kind: 'value',
      primary: formatCurrency(v, 'USD', locale, 2),
      secondary:
        delta != null ? `${delta > 0 ? '+' : ''}${formatPercent(delta, locale)}` : undefined,
      tone,
      source,
      ...base,
    }
  }

  // lbo / comps: the headline lives in the full artifact's structured outputs.
  if (!detail) return detailLoading ? { kind: 'pending' } : { kind: 'withheld', ...base }
  const s = ((detail.outputs as Record<string, unknown> | undefined)?.structured ?? {}) as Record<
    string,
    unknown
  >

  if (type === 'lbo') {
    const irr = plainNum(s.irr)
    const moic = plainNum(s.moic)
    if (irr == null && moic == null) return { kind: 'withheld', ...base }
    // A deal that does not deleverage (backend self_financing === false): projected
    // levered FCF is negative across the hold, so net debt rises on revolver draws and
    // the MOIC / IRR are pure exit-multiple artifacts, not achievable returns. Lead with
    // the verdict and demote the numbers so this headline chip never reports an unearned
    // IRR — the detail page's capital_structure_warning carries the full prose.
    if (s.self_financing === false) {
      return {
        kind: 'value',
        primary: 'Not self-financing',
        secondary:
          irr != null ? `${formatPercent(irr, locale, 0)} IRR · exit-multiple only` : undefined,
        tone: 'neg',
        source,
        ...base,
      }
    }
    return {
      kind: 'value',
      primary: irr != null ? `${formatPercent(irr, locale, 0)} IRR` : '—',
      secondary: moic != null ? `${moic.toFixed(2)}× MOIC` : undefined,
      tone: 'neutral',
      source,
      ...base,
    }
  }

  // comps — lead with whatever multiple the artifact carries (EV/EBITDA for most;
  // P/E or P/B for financials where EV/EBITDA is nulled upstream).
  const ev = plainNum(s.median_ev_ebitda)
  const pe = plainNum(s.median_pe)
  const pb = plainNum(s.median_pb)
  const lead = ev ?? pe ?? pb
  if (lead == null) return { kind: 'withheld', ...base }
  return {
    kind: 'value',
    primary: `${lead.toFixed(1)}×`,
    secondary: ev != null ? 'EV/EBITDA' : pe != null ? 'P/E' : 'P/B',
    tone: 'neutral',
    source,
    ...base,
  }
}

const cardBase: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 8,
  padding: '13px 14px',
  background: 'var(--bg-elevated)',
  border: '1px solid var(--border-soft)',
  borderRadius: 'var(--radius-lg)',
  textAlign: 'left',
  color: 'var(--text-primary)',
  minWidth: 0,
}

function IconBox({ glyph }: { glyph: React.ReactNode }): React.ReactElement {
  return (
    <span
      style={{
        width: 34,
        height: 34,
        borderRadius: 'var(--radius-md)',
        background: 'var(--primary-soft)',
        border: '1px solid color-mix(in srgb, var(--primary) 18%, transparent)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: 'var(--primary)',
        flexShrink: 0,
      }}
    >
      {glyph}
    </span>
  )
}

function TileHeader({
  glyph,
  title,
  right,
}: {
  glyph: React.ReactNode
  title: string
  right?: React.ReactNode
}): React.ReactElement {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
      <IconBox glyph={glyph} />
      <span
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 13.5,
          fontWeight: 600,
          color: 'var(--text-primary)',
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {title}
      </span>
      {right != null && <span style={{ marginLeft: 'auto', display: 'flex' }}>{right}</span>}
    </div>
  )
}

const metaLine: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 10,
  color: 'var(--text-muted)',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
}

function humanizeStep(name: string | undefined): string {
  if (!name) return ''
  return name.replace(/_/g, ' ')
}

function InstrumentTile({
  method,
  reading,
  running,
  failed,
  runState,
  disabled,
  locale,
  onLaunch,
  onOpen,
}: {
  method: { type: string; glyph: React.ReactNode; hint: { zh: string; en: string } }
  reading: InstrumentReading
  running: boolean
  failed: boolean
  runState: RunState | null
  disabled: boolean
  locale: Locale
  onLaunch: (type: string) => void
  onOpen: (artifactId: string) => void
}): React.ReactElement {
  const zh = locale === 'zh'
  const title = artifactTypeLabel(method.type, locale)

  // ── Running: inline progress INSIDE the tile (never the top panel) ──────────
  if (running) {
    const steps = runState?.steps ?? []
    const total = steps.length || 3
    const done = steps.filter((s) => s.status === 'completed' || s.status === 'degraded').length
    const pct = total ? Math.min(1, done / total) : 0
    const current = humanizeStep(steps.find((s) => s.status === 'running')?.name)
    return (
      <div
        data-testid={`instrument-${method.type}`}
        data-state="running"
        style={{
          ...cardBase,
          borderColor: 'var(--border-glow)',
          boxShadow: 'var(--glow-blue)',
        }}
      >
        <TileHeader glyph={method.glyph} title={title} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: 'var(--primary)',
              display: 'flex',
              gap: 8,
              alignItems: 'baseline',
            }}
          >
            <span>{zh ? '运行中' : 'computing'}</span>
            <span style={{ color: 'var(--text-muted)' }}>
              {current || (zh ? '数据 → 模型 → 估值' : 'data → model → value')}
            </span>
            <span style={{ marginLeft: 'auto', color: 'var(--text-secondary)' }}>
              {done}/{total}
            </span>
          </div>
          <div
            style={{
              height: 3,
              borderRadius: 2,
              background: 'var(--border-soft)',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                width: `${Math.round(pct * 100)}%`,
                height: '100%',
                background: 'var(--primary)',
                borderRadius: 2,
                transition: 'width 0.25s ease',
              }}
            />
          </div>
        </div>
      </div>
    )
  }

  // ── Failed: the run ended in error (not user-cancelled) and produced no
  // artifact. Surface it HONESTLY instead of falling through to idle "not yet
  // computed", which disguises a failure as "never ran". A prior successful
  // artifact still wins (reading.kind === 'value' / 'withheld'); only the idle
  // case (this method never produced a successful artifact) is overridden. Amber,
  // not red — a failed run is recoverable (retry), not a broken product. ───────
  if (failed && reading.kind === 'idle') {
    return (
      <button
        type="button"
        data-testid={`instrument-${method.type}`}
        data-state="failed"
        onClick={() => onLaunch(method.type)}
        disabled={disabled}
        title={zh ? '上次运行失败,点击重试' : 'Last run failed — click to retry'}
        style={{
          ...cardBase,
          borderColor: 'var(--warning)',
          cursor: disabled ? 'not-allowed' : 'pointer',
          opacity: disabled ? 0.45 : 1,
        }}
      >
        <TileHeader glyph={method.glyph} title={title} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--warning)' }}>
            {zh ? '运行失败' : 'run failed'}
          </span>
          <span
            style={{
              marginLeft: 'auto',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
              fontFamily: 'var(--font-mono)',
              fontSize: 10.5,
              fontWeight: 600,
              letterSpacing: '0.08em',
              color: 'var(--warning)',
            }}
          >
            {ICON_RERUN}
            {zh ? '重试' : 'RETRY'}
          </span>
        </div>
        <div style={metaLine}>
          {runState?.error
            ? runState.error.slice(0, 80)
            : zh
              ? '管线未能完成'
              : 'pipeline did not complete'}
        </div>
      </button>
    )
  }

  // ── Idle: never run → the whole tile is the run affordance ──────────────────
  if (reading.kind === 'idle') {
    return (
      <button
        type="button"
        data-testid={`instrument-${method.type}`}
        data-state="idle"
        onClick={() => onLaunch(method.type)}
        disabled={disabled}
        title={zh ? method.hint.zh : method.hint.en}
        style={{
          ...cardBase,
          cursor: disabled ? 'not-allowed' : 'pointer',
          opacity: disabled ? 0.45 : 1,
        }}
      >
        <TileHeader glyph={method.glyph} title={title} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 18, color: 'var(--text-dim)' }}>
            —
          </span>
          <span
            style={{
              marginLeft: 'auto',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
              fontFamily: 'var(--font-mono)',
              fontSize: 10.5,
              fontWeight: 600,
              letterSpacing: '0.08em',
              color: 'var(--primary)',
            }}
          >
            <svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor">
              <path d="M4 3l9 5-9 5z" />
            </svg>
            {zh ? '运行' : 'RUN'}
          </span>
        </div>
        <div style={metaLine}>{zh ? '尚未计算' : 'not yet computed'}</div>
      </button>
    )
  }

  // ── Pending: lbo/comps detail still loading ─────────────────────────────────
  if (reading.kind === 'pending') {
    return (
      <div data-testid={`instrument-${method.type}`} data-state="pending" style={cardBase}>
        <TileHeader glyph={method.glyph} title={title} />
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text-dim)' }}>
          {zh ? '读取中…' : 'loading…'}
        </span>
      </div>
    )
  }

  // ── Withheld: ran but the method did not compute (None) — never fabricate ───
  if (reading.kind === 'withheld') {
    return (
      <button
        type="button"
        data-testid={`instrument-${method.type}`}
        data-state="withheld"
        onClick={() => onOpen(reading.artifactId)}
        disabled={disabled}
        style={{
          ...cardBase,
          cursor: disabled ? 'not-allowed' : 'pointer',
          opacity: disabled ? 0.6 : 1,
        }}
      >
        <TileHeader
          glyph={method.glyph}
          title={title}
          right={<span style={{ color: 'var(--text-dim)' }}>{ICON_CHEVRON}</span>}
        />
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            color: 'var(--warning)',
          }}
        >
          {zh ? '未给值 · 方法不适配' : 'withheld · not applicable'}
        </span>
        <div style={metaLine}>
          v{reading.version} · {reading.age}
        </div>
      </button>
    )
  }

  // ── Value: latest reading, click to open the full model / version history ───
  return (
    <div
      data-testid={`instrument-${method.type}`}
      data-state="value"
      onClick={() => !disabled && onOpen(reading.artifactId)}
      role="button"
      tabIndex={disabled ? -1 : 0}
      onKeyDown={(e) => {
        if (!disabled && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault()
          onOpen(reading.artifactId)
        }
      }}
      style={{
        ...cardBase,
        cursor: disabled ? 'default' : 'pointer',
        opacity: disabled ? 0.55 : 1,
      }}
    >
      <TileHeader
        glyph={method.glyph}
        title={title}
        right={
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            <button
              type="button"
              data-testid={`instrument-rerun-${method.type}`}
              title={zh ? '重新运行' : 'Re-run'}
              onClick={(e) => {
                e.stopPropagation()
                if (!disabled) onLaunch(method.type)
              }}
              disabled={disabled}
              style={{
                display: 'inline-flex',
                padding: 3,
                background: 'transparent',
                border: 'none',
                color: 'var(--text-muted)',
                cursor: disabled ? 'not-allowed' : 'pointer',
              }}
            >
              {ICON_RERUN}
            </button>
            <span style={{ color: 'var(--text-dim)', display: 'flex' }}>{ICON_CHEVRON}</span>
          </span>
        }
      />
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 20,
            fontWeight: 600,
            letterSpacing: '-0.01em',
            color: 'var(--text-primary)',
          }}
        >
          {reading.primary}
        </span>
        {reading.secondary != null && (
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 12,
              fontWeight: 600,
              color: toneColor(reading.tone),
            }}
          >
            {reading.secondary}
          </span>
        )}
      </div>
      <div style={metaLine}>
        v{reading.version} · {reading.age}
        {reading.source ? ` · ${reading.source}` : ''}
      </div>
    </div>
  )
}

export function ValuationInstruments({
  timeline,
  runState,
  preflightBlocked,
  preflightReason,
  locale,
  livePrice,
  onLaunch,
  onOpen,
}: {
  timeline: ArtifactSummaryV5[]
  runState: RunState | null
  preflightBlocked: boolean
  preflightReason: PreflightReason
  locale: Locale
  livePrice: number | null
  onLaunch: (type: string) => void
  onOpen: (artifactId: string) => void
}): React.ReactElement {
  const navigate = useNavigate()
  const zh = locale === 'zh'

  const latestByType = (t: string): ArtifactSummaryV5 | null =>
    timeline.find((a) => a.type === t) ?? null
  const countByType = (t: string): number => timeline.filter((a) => a.type === t).length

  // lbo/comps carry no single price in the summary → read their latest full
  // artifact. Hooks are unconditional with a possibly-null id (disabled when
  // null); artifacts are immutable so these are cached hard.
  const latestLbo = latestByType('lbo')
  const latestComps = latestByType('comps')
  const lboDetail = useArtifactDetail(latestLbo?.id ?? null)
  const compsDetail = useArtifactDetail(latestComps?.id ?? null)

  const isRunning = runState?.status === 'running'
  const runningMethod =
    isRunning && runState && runState.pipelineType !== 'research' ? runState.pipelineType : null
  // The single run slot ended in error (not user-cancelled): light up the failed
  // tile so a failure isn't disguised as the idle "not yet computed" affordance.
  // Mutually exclusive with runningMethod (status is one value); research failures
  // don't belong to a standalone instrument tile.
  const failedMethod =
    runState && runState.status === 'failed' && runState.pipelineType !== 'research'
      ? runState.pipelineType
      : null
  // The store holds ONE run slot per ticker: while any run holds it (research or
  // an instrument), no other instrument can start — disable the rest, but keep
  // them VISIBLE (the running one shows its progress in place).
  const lockOthers = isRunning

  return (
    <div
      data-testid="ai-zone-standalone-launcher"
      style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-lg)',
        padding: '16px',
        height: '100%',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 13 }}>
        <span
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 12,
            fontWeight: 600,
            color: 'var(--text-muted)',
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
          }}
        >
          {zh ? '估值仪表' : 'Valuation Instruments'}
        </span>
        <span
          style={{
            marginLeft: 'auto',
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            color: 'var(--text-muted)',
          }}
        >
          {zh ? '无需完整研报' : 'no full report needed'}
        </span>
      </div>

      {preflightBlocked ? (
        <button
          type="button"
          data-testid="standalone-launcher-blocked"
          disabled={!SETTINGS_ALLOWED}
          onClick={SETTINGS_ALLOWED ? () => navigate('/settings') : undefined}
          style={{
            width: '100%',
            padding: '11px 14px',
            background: 'var(--warning-soft)',
            border: '1px solid var(--warning)',
            borderRadius: 8,
            color: 'var(--warning)',
            fontFamily: 'var(--font-mono)',
            fontSize: 11.5,
            fontWeight: 600,
            cursor: SETTINGS_ALLOWED ? 'pointer' : 'default',
          }}
        >
          {blockedCtaLabel(preflightReason, zh)}
        </button>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          {STANDALONE_METHODS.map((m) => {
            const summary = latestByType(m.type)
            const detail =
              m.type === 'lbo' ? lboDetail.data : m.type === 'comps' ? compsDetail.data : undefined
            const detailLoading =
              m.type === 'lbo'
                ? lboDetail.isLoading
                : m.type === 'comps'
                  ? compsDetail.isLoading
                  : false
            const reading = deriveReading(
              m.type,
              summary,
              detail,
              detailLoading,
              countByType(m.type),
              livePrice,
              locale,
            )
            const running = runningMethod === m.type
            const failed = failedMethod === m.type
            return (
              <InstrumentTile
                key={m.type}
                method={m}
                reading={reading}
                running={running}
                failed={failed}
                runState={running || failed ? runState : null}
                disabled={lockOthers && !running}
                locale={locale}
                onLaunch={onLaunch}
                onOpen={onOpen}
              />
            )
          })}
        </div>
      )}
    </div>
  )
}
