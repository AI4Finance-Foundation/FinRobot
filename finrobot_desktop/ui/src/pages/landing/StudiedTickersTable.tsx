// StudiedTickersTable — every ticker I've analysed, in one rollup table.
//
// Distinguishes from RecentResearchStrip (top-5 latest artifacts) by
// being grouped: each row = one ticker, with run count + types + latest
// verdict. Click a row → /stocks/:ticker.

import { useNavigate } from 'react-router-dom'
import { useStudiedTickers, type StudiedTicker } from '../../hooks/useStudiedTickers'

const TYPE_SHORT: Record<string, string> = {
  equity_research: '研报',
  ic_memo: '投委',
  earnings_analysis: '财报',
  earnings: '财报',
  dcf: 'DCF',
  lbo: 'LBO',
  ddm: 'DDM',
  comps: '同业',
  peer_research: '同业',
  playground_snapshot: '手调',
  ad_hoc: 'Ad hoc',
}

export function StudiedTickersTable(): React.ReactElement {
  const navigate = useNavigate()
  const { data, isLoading, isError } = useStudiedTickers(100)
  const items = data?.items ?? []

  return (
    <section data-testid="studied-tickers-table">
      <div className="cosmic-group-header" style={{ margin: 0, marginBottom: 16 }}>
        <span className="group-num">03</span>
        <span className="group-title" style={{ fontSize: 20, letterSpacing: 2.5 }}>
          我研究过的所有股票
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
          {items.length > 0 ? `${items.length} 只 · 点行进工作区` : ''}
        </span>
      </div>

      {isError && <ErrorBox>后端无响应 · 启动 FinAgent server 后刷新。</ErrorBox>}
      {isLoading && !data && <Skeleton />}
      {data && items.length === 0 && (
        <ErrorBox>还没有研究记录 · 顶部输入一个 ticker 开跑分析。</ErrorBox>
      )}

      {items.length > 0 && (
        <div
          className="cosmic-card"
          style={{ padding: 0, overflow: 'hidden', borderRadius: 'var(--radius-lg)' }}
        >
          <div
            role="grid"
            aria-label="我研究过的所有股票"
            style={{
              display: 'grid',
              gridTemplateColumns:
                'minmax(72px, 0.8fr) minmax(80px, 0.7fr) minmax(140px, 1.6fr) minmax(60px, 0.5fr) minmax(90px, 0.7fr) minmax(80px, 0.6fr)',
              fontFamily: 'var(--font-mono)',
              fontSize: 12,
            }}
          >
            <HeaderCell>Ticker</HeaderCell>
            <HeaderCell>信号</HeaderCell>
            <HeaderCell>类型</HeaderCell>
            <HeaderCell align="right">次数</HeaderCell>
            <HeaderCell align="right">目标价</HeaderCell>
            <HeaderCell align="right">距今</HeaderCell>
            {items.map((row) => (
              <Row
                key={row.ticker}
                row={row}
                onClick={() => navigate(`/stocks/${row.ticker}`)}
              />
            ))}
          </div>
        </div>
      )}
    </section>
  )
}

function HeaderCell({
  children,
  align,
}: {
  children: React.ReactNode
  align?: 'right'
}): React.ReactElement {
  return (
    <div
      style={{
        padding: '10px 14px',
        fontSize: 10,
        letterSpacing: '0.12em',
        color: 'var(--text-muted)',
        textTransform: 'uppercase',
        textAlign: align ?? 'left',
        borderBottom: '1px solid var(--border-faint)',
        background: 'rgba(10,10,24,0.6)',
      }}
    >
      {children}
    </div>
  )
}

function Row({
  row,
  onClick,
}: {
  row: StudiedTicker
  onClick: () => void
}): React.ReactElement {
  const cells: { content: React.ReactNode; align?: 'right' }[] = [
    {
      content: (
        <span
          style={{
            fontFamily: 'var(--font-display)',
            letterSpacing: 1.5,
            color: 'var(--text-primary)',
            fontSize: 13,
          }}
        >
          {row.ticker}
        </span>
      ),
    },
    {
      content: <SignalLamp signal={row.latest_signal} />,
    },
    {
      content: (
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {row.types.map((t) => (
            <span
              key={t}
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                color: 'var(--text-secondary)',
                padding: '2px 6px',
                background: 'rgba(59,130,246,0.08)',
                border: '1px solid rgba(59,130,246,0.18)',
                borderRadius: 999,
              }}
            >
              {TYPE_SHORT[t] ?? t.slice(0, 6)}
            </span>
          ))}
        </div>
      ),
    },
    {
      align: 'right',
      content: (
        <span style={{ color: 'var(--text-secondary)' }}>{row.run_count}</span>
      ),
    },
    {
      align: 'right',
      content:
        row.latest_target_price !== null ? (
          <span style={{ color: 'var(--accent-cyan)', fontVariantNumeric: 'tabular-nums' }}>
            ${row.latest_target_price.toFixed(2)}
          </span>
        ) : (
          <span style={{ color: 'var(--text-muted)' }}>—</span>
        ),
    },
    {
      align: 'right',
      content: (
        <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
          {formatRelative(row.latest_created_at)}
        </span>
      ),
    },
  ]

  return (
    <>
      {cells.map((cell, i) => (
        <button
          key={`${row.ticker}-${i}`}
          type="button"
          onClick={onClick}
          aria-label={i === 0 ? `View ${row.ticker}` : undefined}
          style={{
            padding: '12px 14px',
            background: 'transparent',
            border: 'none',
            borderBottom: '1px solid var(--border-faint)',
            color: 'inherit',
            textAlign: cell.align ?? 'left',
            cursor: 'pointer',
            font: 'inherit',
            transition: 'background 0.15s',
          }}
          onMouseEnter={(e) => {
            // Highlight the whole row — find siblings with the same ticker key.
            const siblings = document.querySelectorAll<HTMLElement>(
              `button[aria-label-row="${row.ticker}"]`,
            )
            siblings.forEach((el) => {
              el.style.background = 'rgba(59,130,246,0.06)'
            })
            ;(e.currentTarget as HTMLElement).style.background = 'rgba(59,130,246,0.06)'
          }}
          onMouseLeave={(e) => {
            ;(e.currentTarget as HTMLElement).style.background = 'transparent'
          }}
        >
          {cell.content}
        </button>
      ))}
    </>
  )
}

function SignalLamp({
  signal,
}: {
  signal: 'hit' | 'watching' | 'failed' | null
}): React.ReactElement {
  if (!signal) {
    return <span style={{ color: 'var(--text-muted)' }}>—</span>
  }
  const colors = {
    hit: { fg: 'var(--success)', glow: 'var(--success-glow)', label: '命中' },
    watching: { fg: 'var(--accent-cyan)', glow: 'var(--glow-cyan)', label: '观察' },
    failed: { fg: 'var(--danger)', glow: 'var(--danger-glow)', label: '未中' },
  } as const
  const c = colors[signal]
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span
        aria-label={signal}
        style={{
          width: 7,
          height: 7,
          borderRadius: '50%',
          background: c.fg,
          boxShadow: `0 0 10px ${c.glow}`,
        }}
      />
      <span style={{ color: c.fg, fontSize: 11 }}>{c.label}</span>
    </span>
  )
}

function ErrorBox({ children }: { children: React.ReactNode }): React.ReactElement {
  return (
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
      {children}
    </div>
  )
}

function Skeleton(): React.ReactElement {
  return (
    <div className="cosmic-card" style={{ padding: 0, overflow: 'hidden' }}>
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          style={{
            height: 44,
            borderBottom: '1px solid var(--border-faint)',
            background:
              'linear-gradient(110deg, rgba(15,15,34,0.6) 25%, rgba(34,211,238,0.05) 50%, rgba(15,15,34,0.6) 75%)',
            backgroundSize: '200% 100%',
            animation: 'cosmic-shimmer 2s linear infinite',
          }}
        />
      ))}
    </div>
  )
}

function formatRelative(iso: string): string {
  const d = new Date(iso)
  const diffH = (Date.now() - d.getTime()) / (3600 * 1000)
  if (diffH < 1) return '刚刚'
  if (diffH < 24) return `${Math.round(diffH)}h 前`
  if (diffH < 24 * 14) return `${Math.round(diffH / 24)}d 前`
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}
