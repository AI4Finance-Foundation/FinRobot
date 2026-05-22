// v5 §6.2 催化剂. Six categories from compute/catalyst.py; UI shows the
// top-four by impact magnitude with a "全部催化剂 ▸" disclosure for the
// rest. Endpoint is the existing GET /api/data/{ticker}/catalysts
// (no new backend required).

import { useTickerCatalysts } from '../../hooks/useTickerData'
import type { CatalystEventData as CatalystEvent } from '../../hooks/useTickerData'

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
  background: 'var(--bg-card)',
}

interface CatalystGridProps {
  ticker: string
}

export function CatalystGrid({ ticker }: CatalystGridProps): React.ReactElement {
  const { data, isLoading, isError } = useTickerCatalysts(ticker)

  const events: CatalystEvent[] = data ?? []
  // Backend emits a numeric impact_score (1..5); sort desc so the largest
  // shocks bubble to top 4. magnitudeWeight is kept as a fallback for any
  // string-based legacy payload.
  const topFour = [...events]
    .sort((a, b) => (b.impact_score ?? 0) - (a.impact_score ?? 0))
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
          <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>
            共 {events.length} 条 · 展示影响力 top 4
          </span>
        )}
      </header>

      {isLoading && (
        <p style={{ marginTop: 12, fontSize: 12, color: 'var(--text-faint)' }}>
          ⏳ 催化剂识别中（首次加载 ~20s · LLM 在分类新闻 · 二次访问走 24h cache）
        </p>
      )}
      {isError && (
        <p style={{ marginTop: 12, fontSize: 12, color: 'var(--danger)' }}>
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
            const cat = ev.category || 'market'
            const meta = CATEGORY_LABELS[cat] || CATEGORY_LABELS.market
            const display = deriveCatalystDisplay(ev)
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
                  {ev.headline ?? '(未命名事件)'}
                </span>
                {ev.reasoning && (
                  <span style={{ fontSize: 11, color: 'var(--text-soft)', lineHeight: 1.45 }}>
                    {ev.reasoning.slice(0, 100)}
                    {ev.reasoning.length > 100 ? '…' : ''}
                  </span>
                )}
                <span style={{ fontSize: 11, color: display.color }}>
                  {display.label}
                </span>
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}

function deriveCatalystDisplay(ev: CatalystEvent): { color: string; label: string } {
  const score = ev.impact_score ?? 0
  const magText = score >= 4 ? '高影响' : score >= 2 ? '中影响' : score >= 1 ? '低影响' : ''
  if (ev.sentiment === 'negative') {
    return { color: '#EF4444', label: `↓ ${magText}`.trim() }
  }
  if (ev.sentiment === 'positive') {
    const color = score >= 4 ? '#10B981' : '#16A34A'
    return { color, label: `↑ ${magText}`.trim() }
  }
  if (ev.sentiment === 'neutral') {
    return { color: 'var(--text-soft)', label: `→ ${magText}`.trim() }
  }
  return { color: 'var(--text-faint)', label: magText }
}
