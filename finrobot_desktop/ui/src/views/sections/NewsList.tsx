// v5 §6.11 新闻动态. Reads /api/data/{ticker}/news (existing endpoint).
// Falls back to the lighter shape when news_summary classification isn't
// available yet.

import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../../api/client'

interface NewsItem {
  title?: string
  source?: string
  url?: string
  published_at?: string
  sentiment?: 'positive' | 'negative' | 'neutral' | string
  summary?: string
}

interface NewsResponse {
  items?: NewsItem[]
  news?: NewsItem[]
  feed?: NewsItem[]
}

const SECTION_STYLE: React.CSSProperties = {
  border: '1px solid var(--border)',
  borderRadius: 12,
  padding: 20,
  margin: '12px 0',
  background: 'var(--bg-card, #fff)',
}

interface NewsListProps {
  ticker: string
}

export function NewsList({ ticker }: NewsListProps): React.ReactElement {
  const { data, isLoading, isError } = useQuery<NewsResponse, Error>({
    queryKey: ['ticker-news', ticker],
    queryFn: async () => {
      const r = await fetch(`${BASE_URL}/api/data/${ticker}/news`)
      if (!r.ok) throw new Error(`${r.status}`)
      return (await r.json()) as NewsResponse
    },
    enabled: !!ticker,
    staleTime: 30 * 60_000,
    refetchOnMount: false,
  })

  const items = (data?.items ?? data?.news ?? data?.feed ?? []).slice(0, 12)

  return (
    <section id="sec-news" style={SECTION_STYLE}>
      <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>📰 新闻动态</h2>
      {isLoading && (
        <p style={{ marginTop: 8, fontSize: 12, color: 'var(--text-faint)' }}>加载中…</p>
      )}
      {isError && (
        <p style={{ marginTop: 8, fontSize: 12, color: 'var(--red, #EF4444)' }}>新闻加载失败</p>
      )}
      {!isLoading && items.length === 0 && (
        <p style={{ marginTop: 8, fontSize: 12, color: 'var(--text-faint)' }}>
          近期无相关新闻。
        </p>
      )}
      <ul style={{ marginTop: 12, padding: 0, listStyle: 'none', display: 'grid', gap: 8 }}>
        {items.map((n, i) => (
          <li
            key={i}
            style={{
              display: 'flex',
              gap: 10,
              alignItems: 'flex-start',
              fontSize: 12.5,
              paddingBottom: 8,
              borderBottom: '1px solid var(--border-soft)',
            }}
          >
            <span
              aria-hidden
              style={{
                width: 8,
                height: 8,
                marginTop: 6,
                borderRadius: '50%',
                background: sentimentColor(n.sentiment),
                flexShrink: 0,
              }}
            />
            <span style={{ flex: 1 }}>
              {n.url ? (
                <a
                  href={n.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  style={{ color: 'var(--text)', textDecoration: 'none', fontWeight: 500 }}
                >
                  {n.title ?? '(untitled)'}
                </a>
              ) : (
                <span>{n.title ?? '(untitled)'}</span>
              )}
              <span style={{ marginLeft: 8, fontSize: 11, color: 'var(--text-faint)' }}>
                {n.source ?? ''} · {formatDate(n.published_at)}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}

function sentimentColor(sentiment?: string): string {
  if (sentiment === 'positive') return '#10B981'
  if (sentiment === 'negative') return '#EF4444'
  if (sentiment === 'neutral') return '#F59E0B'
  return 'var(--text-faint)'
}

function formatDate(iso?: string): string {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
  } catch {
    return ''
  }
}
