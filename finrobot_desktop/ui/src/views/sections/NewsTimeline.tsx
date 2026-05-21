// v5 §6.x 新闻时间线 — replaces the flat ul list with a chronological
// timeline. Each row shows: date column (left), sentiment-colored bubble
// sized by absolute sentiment magnitude (the "loudness" of the story),
// then headline + source. Items pulled from /api/data/{ticker}/news with
// no pipeline run required (provider direct).

import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../../api/client'

interface NewsItem {
  title?: string
  source?: string
  url?: string
  published_at?: string
  sentiment_score?: number | null
  category?: string | null
}

interface NewsResponse {
  ticker?: string
  items?: NewsItem[]
  overall_sentiment?: number
  sources_used?: string[]
}

const SECTION_STYLE: React.CSSProperties = {
  border: '1px solid var(--border)',
  borderRadius: 12,
  padding: 20,
  margin: '12px 0',
  background: 'var(--bg-card, #fff)',
}

interface NewsTimelineProps {
  ticker: string
}

export function NewsTimeline({ ticker }: NewsTimelineProps): React.ReactElement {
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

  const items = (data?.items ?? []).slice(0, 16)
  const overall = data?.overall_sentiment ?? null

  return (
    <section id="sec-news" style={SECTION_STYLE}>
      <header style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 10 }}>
        <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>📰 新闻时间线</h2>
        {overall !== null && (
          <span
            style={{
              fontSize: 11,
              color: 'var(--text-faint)',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            综合情感{' '}
            <strong
              data-testid="news-overall-sentiment"
              style={{ color: sentimentColor(overall), fontWeight: 600 }}
            >
              {overall >= 0 ? '+' : ''}
              {overall.toFixed(2)}
            </strong>
          </span>
        )}
        {data?.sources_used?.length && (
          <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>
            · 源：{data.sources_used.slice(0, 4).join(' · ')}
          </span>
        )}
      </header>

      {isLoading && (
        <p style={{ fontSize: 12, color: 'var(--text-faint)' }}>加载中…</p>
      )}
      {isError && (
        <p style={{ fontSize: 12, color: 'var(--red, #EF4444)' }}>新闻加载失败</p>
      )}
      {!isLoading && items.length === 0 && (
        <p style={{ fontSize: 12, color: 'var(--text-faint)' }}>近期无相关新闻。</p>
      )}

      {items.length > 0 && (
        <ol
          data-testid="news-timeline"
          style={{
            position: 'relative',
            margin: 0,
            padding: 0,
            listStyle: 'none',
          }}
        >
          {/* Spine */}
          <div
            aria-hidden
            style={{
              position: 'absolute',
              left: 78,
              top: 8,
              bottom: 8,
              width: 1,
              background: 'var(--border-soft, var(--border))',
            }}
          />
          {items.map((n, i) => (
            <TimelineRow key={n.url ?? i} item={n} />
          ))}
        </ol>
      )}
    </section>
  )
}

function TimelineRow({ item }: { item: NewsItem }): React.ReactElement {
  const score = typeof item.sentiment_score === 'number' ? item.sentiment_score : null
  const magnitude = score === null ? 0 : Math.min(1, Math.abs(score))
  const bubbleSize = 10 + magnitude * 8 // 10–18px
  const color = sentimentColor(score)

  return (
    <li
      style={{
        position: 'relative',
        display: 'grid',
        gridTemplateColumns: '70px 24px 1fr',
        gap: 8,
        padding: '8px 0',
        borderBottom: '1px solid var(--border-soft, var(--border))',
        fontSize: 12.5,
      }}
    >
      <span
        style={{
          textAlign: 'right',
          fontSize: 11,
          color: 'var(--text-faint)',
          paddingTop: 4,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {formatDate(item.published_at)}
      </span>
      <span
        style={{
          position: 'relative',
          width: 24,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <span
          data-sentiment={score === null ? 'neutral' : score >= 0.1 ? 'pos' : score <= -0.1 ? 'neg' : 'neutral'}
          style={{
            width: bubbleSize,
            height: bubbleSize,
            borderRadius: '50%',
            background: color,
            boxShadow: `0 0 0 3px ${color}22`,
          }}
        />
      </span>
      <span style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {item.url ? (
          <a
            href={item.url}
            target="_blank"
            rel="noreferrer noopener"
            style={{
              color: 'var(--text)',
              textDecoration: 'none',
              fontWeight: 500,
              lineHeight: 1.4,
            }}
          >
            {item.title ?? '(untitled)'}
          </a>
        ) : (
          <span style={{ lineHeight: 1.4 }}>{item.title ?? '(untitled)'}</span>
        )}
        <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>
          {[item.source, item.category]
            .filter(Boolean)
            .join(' · ')}
          {score !== null && (
            <span
              style={{
                marginLeft: 8,
                color,
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {score >= 0 ? '+' : ''}
              {score.toFixed(2)}
            </span>
          )}
        </span>
      </span>
    </li>
  )
}

function sentimentColor(score: number | null | undefined): string {
  if (typeof score !== 'number') return 'var(--text-faint)'
  if (score >= 0.1) return '#10B981'
  if (score <= -0.1) return '#EF4444'
  return '#F59E0B'
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
