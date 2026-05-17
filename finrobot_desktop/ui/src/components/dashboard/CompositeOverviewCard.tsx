/**
 * CompositeOverviewCard — Dashboard "最值得看的一只" 综合评分大卡
 *
 * 散户友好版本：取 watchlist 中综合评分最高的一只作为今日聚焦，显示
 *   - 综合评分（0-100）+ signal badge
 *   - 4 个子分进度条（基本面 / 估值 / 催化剂 / 情绪）
 *   - 每个子分点击 → 让 LLM 用人话解释
 *
 * 数据来自后端 POST /api/dashboard/scores-overview（30 分钟缓存，复用
 * DCF artifact + financials，不跑昂贵的 catalyst LLM 分类）。
 */

import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../../api/client'
import { useStocksStore } from '../../stores/stocksStore'
import { useUiStore } from '../../stores/uiStore'

type Signal = 'STRONG_BUY' | 'BUY' | 'HOLD' | 'SELL' | 'STRONG_SELL'

interface ScoreItem {
  ticker: string
  total: number | null
  signal: Signal | null
  fundamental: number | null
  valuation: number | null
  catalyst: number | null
  sentiment: number | null
  breakdown: Partial<Record<'fundamental' | 'valuation' | 'catalyst' | 'sentiment', string>>
  current_price: number | null
}

interface ScoresOverviewResponse {
  items: ScoreItem[]
  generated_at: number
}

async function fetchScores(watchlist: string[]): Promise<ScoresOverviewResponse> {
  const r = await fetch(`${BASE_URL}/api/dashboard/scores-overview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ watchlist }),
  })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json() as Promise<ScoresOverviewResponse>
}

function signalColor(signal: Signal | null): string {
  switch (signal) {
    case 'STRONG_BUY':
    case 'BUY':
      return 'var(--positive)'
    case 'HOLD':
      return 'var(--accent, #f59e0b)'
    case 'SELL':
    case 'STRONG_SELL':
      return 'var(--negative)'
    default:
      return 'var(--text-muted)'
  }
}

function signalBg(signal: Signal | null): string {
  switch (signal) {
    case 'STRONG_BUY':
    case 'BUY':
      return 'var(--positive-bg, rgba(34,197,94,0.12))'
    case 'HOLD':
      return 'rgba(245,158,11,0.12)'
    case 'SELL':
    case 'STRONG_SELL':
      return 'var(--negative-bg, rgba(239,68,68,0.12))'
    default:
      return 'var(--surface)'
  }
}

function signalLabel(signal: Signal | null): string {
  switch (signal) {
    case 'STRONG_BUY':
      return '强烈买入'
    case 'BUY':
      return '买入'
    case 'HOLD':
      return '持有'
    case 'SELL':
      return '卖出'
    case 'STRONG_SELL':
      return '强烈卖出'
    default:
      return '—'
  }
}

function barColor(v: number): string {
  if (v >= 60) return 'var(--positive)'
  if (v >= 40) return 'var(--accent, #f59e0b)'
  return 'var(--negative)'
}

export function CompositeOverviewCard(): React.ReactElement | null {
  const navigate = useNavigate()
  const sendChatPrompt = useUiStore((s) => s.sendChatPrompt)
  const watchlist = useStocksStore((s) => s.watchlist)
  const watchlistArr = useMemo(() => Array.from(watchlist).sort(), [watchlist])

  const { data, isLoading, isError } = useQuery<ScoresOverviewResponse>({
    queryKey: ['dashboard-scores-overview', watchlistArr.join(',')],
    queryFn: () => fetchScores(watchlistArr),
    enabled: watchlistArr.length > 0,
    staleTime: 30 * 60_000, // 30 min — matches backend cache TTL
    retry: 1,
  })

  // Hide entirely when no watchlist (sidebar already nudges user to add)
  if (watchlistArr.length === 0) return null

  const top = data?.items.find((it) => it.total !== null) ?? null

  const subScores: Array<{ key: 'fundamental' | 'valuation' | 'catalyst' | 'sentiment'; label: string }> = [
    { key: 'fundamental', label: '基本面' },
    { key: 'valuation', label: '估值' },
    { key: 'catalyst', label: '催化剂' },
    { key: 'sentiment', label: '情绪' },
  ]

  function askWhy(label: string, value: number, breakdown: string): void {
    if (!top) return
    const prompt =
      `${top.ticker} 的「${label}」评分为 ${value} 分（100 分制）。` +
      `系统简短依据：「${breakdown || '暂无具体依据'}」。请用一段中文（200 字以内）展开解释：` +
      `这个分数偏高/偏低意味着什么？投资人应该重点关注什么？`
    sendChatPrompt(prompt, true)
  }

  return (
    <div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 12,
        }}
      >
        <span
          style={{
            fontSize: 11,
            fontFamily: 'var(--font-mono)',
            fontWeight: 600,
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            color: 'var(--text-muted)',
          }}
        >
          自选股最高分
        </span>
        <span
          style={{
            fontSize: 10,
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-mono)',
          }}
        >
          基本面 / 估值 / 催化剂 / 情绪 加权
        </span>
      </div>

      {isLoading && !data && (
        <div
          style={{
            height: 220,
            background: 'var(--bg-3)',
            borderRadius: 'var(--r-md)',
            animation: 'skeleton-pulse 1.5s ease infinite',
          }}
        />
      )}

      {isError && (
        <div
          style={{
            padding: '10px 12px',
            background: 'var(--bg-2)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--r-sm)',
            fontSize: 11,
            color: 'var(--text-muted)',
          }}
        >
          评分数据暂不可用
        </div>
      )}

      {data && !top && (
        <div
          style={{
            padding: '10px 12px',
            background: 'var(--bg-2)',
            border: '1px dashed var(--border)',
            borderRadius: 'var(--r-sm)',
            fontSize: 11,
            color: 'var(--text-muted)',
          }}
        >
          自选股暂无足够数据生成综合评分 — 去个股页跑一次 DCF / 拉一次财报
        </div>
      )}

      {top && (
        <div
          style={{
            background: 'var(--bg-1)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--r-md)',
            padding: '16px 18px',
          }}
        >
          {/* Header */}
          <div
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              justifyContent: 'space-between',
              marginBottom: 16,
              gap: 12,
            }}
          >
            <div>
              <button
                onClick={() => navigate(`/stocks/${top.ticker}`)}
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 13,
                  fontWeight: 700,
                  color: 'var(--accent)',
                  background: 'transparent',
                  border: 'none',
                  cursor: 'pointer',
                  padding: 0,
                  marginBottom: 6,
                  letterSpacing: '0.04em',
                }}
                type="button"
                title={`查看 ${top.ticker} 详情`}
              >
                {top.ticker} →
              </button>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                <span
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 36,
                    fontWeight: 700,
                    color: signalColor(top.signal),
                    lineHeight: 1,
                  }}
                >
                  {top.total}
                </span>
                <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>/100</span>
              </div>
            </div>
            <span
              style={{
                display: 'inline-block',
                padding: '4px 10px',
                borderRadius: 4,
                background: signalBg(top.signal),
                color: signalColor(top.signal),
                fontFamily: 'var(--font-mono)',
                fontSize: 12,
                fontWeight: 700,
                letterSpacing: '0.06em',
                border: `1px solid ${signalColor(top.signal)}`,
                flexShrink: 0,
              }}
            >
              {signalLabel(top.signal)}
            </span>
          </div>

          {/* Sub-score bars */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {subScores.map(({ key, label }) => {
              const value = top[key]
              if (value === null) return null
              const breakdown = top.breakdown[key] ?? ''
              return (
                <button
                  key={key}
                  onClick={() => askWhy(label, value, breakdown)}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    padding: 0,
                    cursor: 'pointer',
                    textAlign: 'left',
                    width: '100%',
                    borderRadius: 4,
                    transition: 'background 0.12s',
                  }}
                  onMouseEnter={(e) => {
                    ;(e.currentTarget as HTMLButtonElement).style.background = 'var(--bg-3)'
                  }}
                  onMouseLeave={(e) => {
                    ;(e.currentTarget as HTMLButtonElement).style.background = 'transparent'
                  }}
                  title={`点击让 FinAgent 解释 ${top.ticker} 的${label}评分`}
                  type="button"
                >
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'baseline',
                      padding: '0 4px',
                    }}
                  >
                    <span style={{ fontSize: 12, color: 'var(--text-secondary)', fontWeight: 500 }}>
                      {label}
                    </span>
                    <span
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: 12,
                        fontWeight: 700,
                        color: barColor(value),
                      }}
                    >
                      {value}
                    </span>
                  </div>
                  <div
                    style={{
                      height: 6,
                      background: 'var(--bg-3)',
                      borderRadius: 3,
                      marginTop: 4,
                      overflow: 'hidden',
                    }}
                  >
                    <div
                      style={{
                        height: '100%',
                        width: `${value}%`,
                        background: barColor(value),
                        transition: 'width 0.3s ease',
                      }}
                    />
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
