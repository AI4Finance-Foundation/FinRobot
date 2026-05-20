import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { useAppStore } from '../stores/appStore'
import { relativeTime } from '../utils/time'

interface NewsItem {
  title: string
  source: string
  url: string
  published_at: string
  sentiment_score: number | null
  category: string | null
}

interface NewsFeedResponse {
  ticker: string
  items: NewsItem[]
  sources_used: string[]
  overall_sentiment: number
  fetched_at: string
  warnings: string[]
}

function sentimentDot(score: number | null): { color: string; label: string } {
  if (score == null) return { color: 'var(--text-muted)', label: '未评级' }
  if (score > 0.15) return { color: 'var(--positive)', label: '利好' }
  if (score < -0.15) return { color: 'var(--negative)', label: '利空' }
  return { color: 'var(--text-muted)', label: '中性' }
}

function formatPublished(isoStr: string): string {
  if (!isoStr) return ''
  try {
    const ts = new Date(isoStr).getTime()
    if (isNaN(ts)) return ''
    return relativeTime(ts)
  } catch {
    return ''
  }
}

export default function NewsFeed() {
  const ticker = useAppStore((s) => s.ticker)

  const { data, isLoading, isError } = useQuery<NewsFeedResponse>({
    queryKey: ['news', ticker],
    queryFn: async () => {
      const resp = await fetch(`${BASE_URL}/api/data/${ticker}/news`)
      if (!resp.ok) throw new Error('获取新闻失败')
      return resp.json()
    },
    enabled: !!ticker,
    staleTime: 5 * 60 * 1000, // 5 min
  })

  const items = data?.items ?? []
  const overall = data?.overall_sentiment ?? 0

  return (
    <div className="card news-feed">
      <div className="card-header">
        <span className="card-title">新闻</span>
        {data && items.length > 0 && (
          <span className="news-feed-meta">
            <span
              className="news-sentiment-dot"
              style={{ background: sentimentDot(overall).color }}
              title={`整体情绪：${sentimentDot(overall).label}（${overall.toFixed(2)}）`}
            />
            <span className="news-feed-count">{items.length} 条</span>
          </span>
        )}
      </div>
      <div className="card-body card-body--flush news-feed-body">
        {isLoading && (
          <div className="news-feed-loading">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="news-feed-skeleton">
                <div className="skeleton" style={{ width: '70%', height: 12 }} />
                <div className="skeleton" style={{ width: '30%', height: 10, marginTop: 4 }} />
              </div>
            ))}
          </div>
        )}
        {isError && (
          <div className="news-feed-empty">新闻暂不可用</div>
        )}
        {!isLoading && !isError && items.length === 0 && (
          <div className="news-feed-empty">近期暂无新闻</div>
        )}
        {!isLoading && items.length > 0 && (
          <ul className="news-feed-list">
            {items.map((item, i) => {
              const dot = sentimentDot(item.sentiment_score)
              return (
                <li key={i} className="news-feed-item">
                  <span
                    className="news-sentiment-dot"
                    style={{ background: dot.color }}
                    title={`${dot.label}（${item.sentiment_score?.toFixed(2) ?? '未评级'}）`}
                  />
                  <div className="news-feed-content">
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="news-feed-headline"
                      title={item.title}
                    >
                      {item.title}
                    </a>
                    <div className="news-feed-details">
                      <span className="news-source-badge">{item.source}</span>
                      {item.published_at && (
                        <span className="news-time">{formatPublished(item.published_at)}</span>
                      )}
                    </div>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
