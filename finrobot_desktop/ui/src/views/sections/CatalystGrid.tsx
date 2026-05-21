// v5 §6.2 催化剂. Six categories from compute/catalyst.py; UI shows the
// top-four by impact magnitude with a "全部催化剂 ▸" disclosure for the
// rest. Endpoint is the existing GET /api/data/{ticker}/catalysts
// (no new backend required).

import { useTickerCatalysts } from '../../hooks/useTickerData'

interface CatalystEvent {
  category?: string
  type?: string
  title?: string
  headline?: string
  date?: string
  impact_direction?: 'up' | 'down' | 'neutral'
  impact_magnitude?: 'high' | 'med' | 'low'
  expected_impact_magnitude?: number
  source?: string
}

const CATEGORY_LABELS: Record<string, { icon: string; label: string }> = {
  earnings: { icon: '📅', label: '财报' },
  product_launch: { icon: '🚀', label: '新品' },
  regulatory: { icon: '⚖️', label: '监管' },
  m_a: { icon: '🤝', label: '并购' },
  acquisition: { icon: '🤝', label: '并购' },
  executive_change: { icon: '👤', label: '高管' },
  management: { icon: '👤', label: '高管' },
  market: { icon: '📊', label: '市场' },
}

const SECTION_STYLE: React.CSSProperties = {
  border: '1px solid var(--border)',
  borderRadius: 12,
  padding: 20,
  margin: '12px 0',
  background: 'var(--bg-card, #fff)',
}

interface CatalystGridProps {
  ticker: string
}

export function CatalystGrid({ ticker }: CatalystGridProps): React.ReactElement {
  const { data, isLoading, isError } = useTickerCatalysts(ticker)

  const events = (data as CatalystEvent[] | undefined) ?? []
  const topFour = [...events]
    .sort(
      (a, b) =>
        magnitudeWeight(b.impact_magnitude ?? null) -
        magnitudeWeight(a.impact_magnitude ?? null),
    )
    .slice(0, 4)

  return (
    <section id="sec-catalyst" style={SECTION_STYLE}>
      <header
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
      >
        <div>
          <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>🔥 催化剂</h2>
          <p style={{ margin: '2px 0 0', fontSize: 11, color: 'var(--text-faint)' }}>
            6 类 catalyst · 展示影响力 top 4
          </p>
        </div>
        {events.length > 4 && (
          <a
            href="#"
            onClick={(e) => e.preventDefault()}
            style={{
              fontSize: 11,
              color: 'var(--text-faint)',
              textDecoration: 'none',
              cursor: 'not-allowed',
            }}
            title="全部催化剂抽屉 - PR15 接入"
          >
            全部催化剂 ▸
          </a>
        )}
      </header>

      {isLoading && (
        <p style={{ marginTop: 12, fontSize: 12, color: 'var(--text-faint)' }}>
          ⏳ 催化剂识别中（首次加载 ~10s · 二次访问走 24h cache）
        </p>
      )}
      {isError && (
        <p style={{ marginTop: 12, fontSize: 12, color: 'var(--red, #EF4444)' }}>
          催化剂加载失败 — 检查数据源
        </p>
      )}
      {!isLoading && events.length === 0 && (
        <p style={{ marginTop: 12, fontSize: 12, color: 'var(--text-faint)' }}>
          暂无催化剂事件 — 财报 / 监管 / 新品发布等出现时会在此展示
        </p>
      )}

      {topFour.length > 0 && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
            gap: 10,
            marginTop: 12,
          }}
        >
          {topFour.map((ev, idx) => {
            const cat = ev.category || ev.type || 'market'
            const meta = CATEGORY_LABELS[cat] || CATEGORY_LABELS.market
            return (
              <article
                key={idx}
                data-testid={`catalyst-card-${idx}`}
                data-category={cat}
                style={{
                  border: '1px solid var(--border-soft)',
                  borderRadius: 8,
                  padding: 12,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 6,
                }}
              >
                <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>
                  {meta.icon} {meta.label}
                </span>
                <span style={{ fontSize: 13, fontWeight: 600 }}>
                  {ev.title || ev.headline || '(未命名事件)'}
                </span>
                <span style={{ fontSize: 11, color: 'var(--text-soft)' }}>
                  {ev.date ?? ''}
                </span>
                <span
                  style={{
                    fontSize: 11,
                    color: impactColor(ev.impact_direction, ev.impact_magnitude),
                  }}
                >
                  {impactLabel(ev.impact_direction, ev.impact_magnitude)}
                </span>
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}

function magnitudeWeight(magnitude: string | null): number {
  if (magnitude === 'high') return 3
  if (magnitude === 'med') return 2
  if (magnitude === 'low') return 1
  return 0
}

function impactColor(dir?: string, mag?: string): string {
  if (dir === 'down') return '#EF4444'
  if (dir === 'up' && mag === 'high') return '#10B981'
  if (dir === 'up') return '#16A34A'
  return 'var(--text-faint)'
}

function impactLabel(dir?: string, mag?: string): string {
  if (!dir) return ''
  const arrow = dir === 'up' ? '↑' : dir === 'down' ? '↓' : '→'
  const magText = mag === 'high' ? '高影响' : mag === 'med' ? '中影响' : mag === 'low' ? '低影响' : ''
  return `${arrow} ${magText}`.trim()
}
