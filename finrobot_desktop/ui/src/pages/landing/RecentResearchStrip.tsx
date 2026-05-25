// RecentResearchStrip — drawer cards: top-5 most recently touched tickers,
// each card listing the ticker's recent runs as clickable rows.
//
// 2026-05-23 (v2): row-based. Click a row → that artifact's detail page
// (/stocks/:ticker/runs/:artifact_id). Click the card header → ticker
// workspace. If the ticker has more than 5 runs in total, an overflow
// footer links to the workspace's full timeline.

import { useNavigate } from 'react-router-dom'
import {
  useDashboardRecentResearch,
  type RecentTickerItem,
  type RecentTickerRun,
  type Signal,
} from '../../hooks/useDashboardRecentResearch'
import { verdictLabel } from '../../utils/verdict'
import { useI18n } from '../../i18n'

// Pipeline key → human label. Keep this map aligned with the backend
// `ArtifactType` Literal (finagent/artifact/models.py); SDK-only pipelines
// (ic-memo / dcf / lbo / ddm / comps) still show up in old artifacts the
// user generated before research became the sole UI-facing pipeline.
const TYPE_SHORT: Record<string, string> = {
  research: '研报',
  equity_research: '研报',
  'ic-memo': '投委',
  ic_memo: '投委',
  earnings: '财报',
  dcf: 'DCF',
  lbo: 'LBO',
  ddm: 'DDM',
  comps: '同业',
  peer_research: '同业',
  ad_hoc: 'Ad hoc',
}

// Bump to 20 now that this strip is the sole landing-page surface
// for "my research library". Horizontal scroll handles the overflow.
const LANDING_TICKER_LIMIT = 20

export function RecentResearchStrip(): React.ReactElement {
  const navigate = useNavigate()
  const { t } = useI18n()
  const { data, isLoading, isError } = useDashboardRecentResearch(LANDING_TICKER_LIMIT)

  return (
    <section data-testid="recent-research-strip">
      <div className="cosmic-group-header" style={{ margin: 0, marginBottom: 16 }}>
        <span className="group-num">02</span>
        <span className="group-title" style={{ fontSize: 20, letterSpacing: 2.5 }}>
          Studied Tickers · 历史研究
        </span>
        <span style={{ flex: 1 }} />
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--text-muted)',
            letterSpacing: '0.06em',
          }}
        >
          {data && data.distinct_ticker_count > 0
            ? `${data.distinct_ticker_count} tickers · ${data.total_in_store} artifacts`
            : ''}
        </span>
      </div>

      {isError && (
        <div
          style={{
            padding: 24,
            border: '1px dashed var(--border-soft)',
            borderRadius: 'var(--radius-md)',
            color: 'var(--text-muted)',
            fontSize: 13,
            textAlign: 'center',
          }}
        >
          {t('landing.recentResearch.error')}
        </div>
      )}

      {isLoading && !data && <StripSkeleton />}

      {data && data.items.length === 0 && (
        <div
          style={{
            padding: 36,
            border: '1px dashed var(--border-soft)',
            borderRadius: 'var(--radius-md)',
            color: 'var(--text-muted)',
            fontSize: 13,
            textAlign: 'center',
          }}
        >
          {t('landing.recentResearch.empty')}
        </div>
      )}

      {data && data.items.length > 0 && (
        <div
          className="hide-scrollbar"
          style={{
            display: 'flex',
            gap: 14,
            overflowX: 'auto',
            paddingBottom: 8,
            alignItems: 'flex-start',
          }}
        >
          {data.items.map((item) => (
            <TickerDrawerCard
              key={item.ticker}
              item={item}
              onOpenWorkspace={() => navigate(`/stocks/${item.ticker}`)}
              onOpenRun={(run) => navigate(`/stocks/${item.ticker}/runs/${run.artifact_id}`)}
            />
          ))}
        </div>
      )}
    </section>
  )
}

function TickerDrawerCard({
  item,
  onOpenWorkspace,
  onOpenRun,
}: {
  item: RecentTickerItem
  onOpenWorkspace: () => void
  onOpenRun: (run: RecentTickerRun) => void
}): React.ReactElement {
  const overflow = item.run_count - item.runs.length
  return (
    <div
      data-testid={`recent-research-card-${item.ticker}`}
      className="cosmic-card"
      style={{
        width: 304,
        flexShrink: 0,
        textAlign: 'left',
        background: 'rgba(15,15,34,0.6)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-lg)',
        display: 'flex',
        flexDirection: 'column',
        transition: 'border-color 0.18s',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = 'var(--border-glow)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = 'var(--border-soft)'
      }}
    >
      <button
        type="button"
        data-testid={`recent-research-card-${item.ticker}-header`}
        onClick={onOpenWorkspace}
        title={`打开 ${item.ticker} 工作区`}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '14px 16px 12px',
          background: 'transparent',
          border: 'none',
          borderBottom: '1px solid var(--border-faint)',
          cursor: 'pointer',
          color: 'inherit',
          font: 'inherit',
          width: '100%',
          textAlign: 'left',
        }}
      >
        <span
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 17,
            letterSpacing: 2,
            color: 'var(--text-primary)',
          }}
        >
          {item.ticker}
        </span>
        {item.latest_signal && <SignalLamp signal={item.latest_signal} />}
        <span style={{ flex: 1 }} />
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--text-muted)',
            letterSpacing: '0.04em',
          }}
        >
          {item.run_count} 份 ›
        </span>
      </button>

      <ul
        style={{
          listStyle: 'none',
          margin: 0,
          padding: '4px 0',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {item.runs.map((run) => (
          <li key={run.artifact_id}>
            <RunRow run={run} onClick={() => onOpenRun(run)} />
          </li>
        ))}
      </ul>

      {overflow > 0 && (
        <button
          type="button"
          data-testid={`recent-research-card-${item.ticker}-overflow`}
          onClick={onOpenWorkspace}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 6,
            padding: '8px 16px 12px',
            background: 'transparent',
            border: 'none',
            borderTop: '1px solid var(--border-faint)',
            cursor: 'pointer',
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--accent-cyan)',
            letterSpacing: '0.04em',
          }}
        >
          + 还有 {overflow} 份历史 · 查看全部 →
        </button>
      )}
    </div>
  )
}

function RunRow({
  run,
  onClick,
}: {
  run: RecentTickerRun
  onClick: () => void
}): React.ReactElement {
  const typeLabel = TYPE_SHORT[run.type] ?? run.type.slice(0, 6)
  return (
    <button
      type="button"
      data-testid={`recent-research-run-${run.artifact_id}`}
      onClick={onClick}
      title={`打开 ${typeLabel} 报告详情`}
      style={{
        display: 'grid',
        gridTemplateColumns: '52px 56px 1fr auto',
        alignItems: 'center',
        gap: 8,
        width: '100%',
        padding: '8px 16px',
        background: 'transparent',
        border: 'none',
        borderRadius: 0,
        cursor: 'pointer',
        color: 'inherit',
        font: 'inherit',
        textAlign: 'left',
        transition: 'background 0.15s',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = 'rgba(59,130,246,0.06)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = 'transparent'
      }}
    >
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--text-secondary)',
          padding: '2px 7px',
          background: 'rgba(59,130,246,0.08)',
          border: '1px solid rgba(59,130,246,0.18)',
          borderRadius: 999,
          letterSpacing: '0.04em',
          textAlign: 'center',
        }}
      >
        {typeLabel}
      </span>
      <VerdictText verdict={run.verdict} />
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--text-muted)',
          letterSpacing: '0.04em',
        }}
      >
        {run.age_label}
      </span>
      <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>›</span>
    </button>
  )
}

function VerdictText({ verdict }: { verdict: 'BUY' | 'HOLD' | 'SELL' | null }): React.ReactElement {
  if (!verdict) {
    return <span style={{ color: 'var(--text-faint)', fontSize: 11 }}>—</span>
  }
  const fg =
    verdict === 'BUY'
      ? 'var(--success)'
      : verdict === 'SELL'
        ? 'var(--danger)'
        : 'var(--accent-amber)'
  return (
    <span
      style={{
        fontFamily: 'var(--font-display)',
        fontSize: 10,
        letterSpacing: 1.4,
        color: fg,
      }}
    >
      {verdictLabel(verdict)}
    </span>
  )
}

function SignalLamp({ signal }: { signal: Signal }): React.ReactElement {
  const colors = {
    hit: { fg: 'var(--success)', glow: 'var(--success-glow)' },
    watching: { fg: 'var(--accent-cyan)', glow: 'var(--glow-cyan)' },
    failed: { fg: 'var(--danger)', glow: 'var(--danger-glow)' },
  } as const
  const c = colors[signal]
  return (
    <span
      title={signal}
      aria-label={signal}
      style={{
        width: 8,
        height: 8,
        borderRadius: '50%',
        background: c.fg,
        boxShadow: `0 0 12px ${c.glow}`,
        animation: signal === 'watching' ? 'cosmic-pulse-dot 1.6s ease-in-out infinite' : undefined,
      }}
    />
  )
}

function StripSkeleton(): React.ReactElement {
  return (
    <div className="hide-scrollbar" style={{ display: 'flex', gap: 14, overflowX: 'auto' }}>
      {[0, 1, 2, 3, 4].map((i) => (
        <div
          key={i}
          style={{
            width: 304,
            height: 220,
            flexShrink: 0,
            borderRadius: 'var(--radius-lg)',
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
