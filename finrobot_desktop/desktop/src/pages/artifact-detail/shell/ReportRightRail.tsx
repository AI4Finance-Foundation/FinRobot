import { useNavigate } from 'react-router-dom'
import type { ArtifactSummaryV5, Signal } from '../../../types/v5'
import { useI18n, type Locale } from '../../../i18n'
import { formatDate } from '../../../utils/format'
import { verdictLabel, verdictTone } from '../../../utils/verdict'

interface ReportRightRailProps {
  ticker: string
  currentArtifactId: string
  timeline: ArtifactSummaryV5[]
  reportType: string
}

// Cap (px) on the timeline's scroll viewport — ~5–6 rows show before the body
// scrolls internally; the full count is always in the panel header.
const TIMELINE_MAX_HEIGHT = 320

// Distance (px) from a row's top edge to its dot centre — kept in one place so
// the connecting spine segments line up exactly with the dots.
const DOT_CENTER = 16

export function ReportRightRail({
  ticker,
  currentArtifactId,
  timeline,
  reportType,
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
          <div
            // Fixed-height scroll box: newest (current) version sits at the top
            // and shows without scrolling; older versions stay reachable by
            // scrolling instead of pushing the panel off-screen.
            data-testid="timeline-scroll"
            style={{
              display: 'flex',
              flexDirection: 'column',
              maxHeight: TIMELINE_MAX_HEIGHT,
              overflowY: 'auto',
            }}
          >
            {sameType.map((a, i, rows) => (
              <TimelineRow
                key={a.id}
                artifact={a}
                // Version number counts from the FULL same-type history
                // (newest = vN).
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
    </aside>
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

/** BUY / HOLD / SELL recommendation badge (localised; shared tone). Legacy
 * WITHHELD-token artifacts render neutral via the shared verdictTone. */
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
