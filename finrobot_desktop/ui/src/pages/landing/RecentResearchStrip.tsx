// RecentResearchStrip — top-5 latest artifacts (horizontal cards).
//
// Each card surfaces: ticker / verdict / signal lamp / entry → target →
// current / delta-to-target / age. Click jumps to the ticker workspace.

import { useNavigate } from 'react-router-dom'
import {
  useDashboardRecentResearch,
  type RecentResearchItem,
  type Signal,
} from '../../hooks/useDashboardRecentResearch'

export function RecentResearchStrip(): React.ReactElement {
  const navigate = useNavigate()
  const { data, isLoading, isError } = useDashboardRecentResearch(5)

  return (
    <section data-testid="recent-research-strip">
      <div
        className="cosmic-group-header"
        style={{ margin: 0, marginBottom: 16 }}
      >
        <span className="group-num">02</span>
        <span className="group-title" style={{ fontSize: 20, letterSpacing: 2.5 }}>
          最近研究
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
          {data?.total_in_store ? `共 ${data.total_in_store} 份在库` : ''}
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
          后端无响应 · 启动 FinAgent server 后刷新页面。
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
          还没有分析记录 · 顶部输入框搜个 ticker 试试。
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
          }}
        >
          {data.items.map((item) => (
            <ResearchCard
              key={item.artifact_id}
              item={item}
              onClick={() => {
                if (item.ticker) navigate(`/stocks/${item.ticker}`)
              }}
            />
          ))}
        </div>
      )}
    </section>
  )
}

function ResearchCard({
  item,
  onClick,
}: {
  item: RecentResearchItem
  onClick: () => void
}): React.ReactElement {
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid="recent-research-card"
      className="cosmic-card"
      style={{
        width: 260,
        flexShrink: 0,
        padding: 18,
        textAlign: 'left',
        cursor: 'pointer',
        background: 'rgba(15,15,34,0.6)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-lg)',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
        transition: 'border-color 0.18s, transform 0.18s',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = 'var(--border-glow)'
        e.currentTarget.style.transform = 'translateY(-2px)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = 'var(--border-soft)'
        e.currentTarget.style.transform = 'translateY(0)'
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 16,
            letterSpacing: 2,
            color: 'var(--text-primary)',
          }}
        >
          {item.ticker ?? item.cross_tickers.join(' · ') ?? '—'}
        </span>
        {item.verdict && <VerdictPill verdict={item.verdict} />}
        <span style={{ flex: 1 }} />
        {item.signal && <SignalLamp signal={item.signal} />}
      </div>

      <div
        style={{
          fontFamily: 'var(--font-body)',
          fontSize: 12,
          fontWeight: 400,
          color: 'var(--text-secondary)',
          lineHeight: 1.45,
          minHeight: 36,
          display: '-webkit-box',
          WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical',
          overflow: 'hidden',
        }}
      >
        {item.headline}
      </div>

      {(item.entry_price && item.target_price && item.current_price) ? (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
            gap: 6,
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          <PriceBox label="入场" value={item.entry_price} />
          <PriceBox label="目标" value={item.target_price} tone="primary" />
          <PriceBox label="当前" value={item.current_price} tone="cyan" />
        </div>
      ) : (
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
          无目标价 · 信号不可判定
        </div>
      )}

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginTop: 4,
        }}
      >
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', letterSpacing: '0.06em' }}>
          {item.age_label.toUpperCase()}
        </span>
        {item.delta_to_target_pct !== null && (
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color:
                item.delta_to_target_pct >= 0.5
                  ? 'var(--success)'
                  : item.delta_to_target_pct < 0
                    ? 'var(--danger)'
                    : 'var(--accent-cyan)',
            }}
          >
            {item.delta_to_target_pct >= 0 ? '+' : ''}
            {(item.delta_to_target_pct * 100).toFixed(0)}% → 目标
          </span>
        )}
      </div>
    </button>
  )
}

function VerdictPill({ verdict }: { verdict: 'BUY' | 'HOLD' | 'SELL' }): React.ReactElement {
  const colors: Record<typeof verdict, { fg: string; bg: string }> = {
    BUY: { fg: 'var(--success)', bg: 'rgba(22,163,74,0.14)' },
    HOLD: { fg: '#F59E0B', bg: 'rgba(217,119,6,0.14)' },
    SELL: { fg: 'var(--danger)', bg: 'rgba(220,38,38,0.14)' },
  }
  const c = colors[verdict]
  return (
    <span
      style={{
        fontFamily: 'var(--font-display)',
        fontSize: 9,
        letterSpacing: 2,
        color: c.fg,
        background: c.bg,
        padding: '3px 8px',
        borderRadius: 4,
      }}
    >
      {verdict}
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

function PriceBox({
  label,
  value,
  tone,
}: {
  label: string
  value: number
  tone?: 'primary' | 'cyan'
}): React.ReactElement {
  const fg = tone === 'primary'
    ? 'var(--primary)'
    : tone === 'cyan'
      ? 'var(--accent-cyan)'
      : 'var(--text-secondary)'
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
      <span style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
        {label}
      </span>
      <span style={{ fontSize: 13, color: fg, fontWeight: 600 }}>
        ${value.toFixed(2)}
      </span>
    </div>
  )
}

function StripSkeleton(): React.ReactElement {
  return (
    <div className="hide-scrollbar" style={{ display: 'flex', gap: 14, overflowX: 'auto' }}>
      {[0, 1, 2, 3, 4].map((i) => (
        <div
          key={i}
          style={{
            width: 260,
            height: 168,
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
