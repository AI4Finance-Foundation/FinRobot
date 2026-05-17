/**
 * DiscoverChip — 一键随机跳到一只你没看过的股票。
 *
 * 鼓励探索（开源 stars 项目的留存关键：让用户每天都觉得"还有东西可看"）。
 *
 * 取自精选的 S&P 500 + 中概 + 港股大票，排除用户 watchlist 里已有的。
 * 不调后端，纯前端随机 — 极便宜。
 */

import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useStocksStore } from '../../stores/stocksStore'

// Curated list of ~40 well-known liquid tickers across sectors. Hand-picked,
// not algorithmically chosen — this is for "I want to learn about something new"
// not "best stock to buy".
const DISCOVERY_POOL = [
  // Tech mega
  'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA', 'TSLA', 'AVGO',
  // Tech mid
  'AMD', 'ORCL', 'CRM', 'ADBE', 'INTC', 'QCOM', 'NFLX',
  // Finance
  'JPM', 'BAC', 'V', 'MA', 'GS', 'BRKB',
  // Consumer
  'WMT', 'COST', 'HD', 'NKE', 'SBUX', 'KO', 'PEP', 'MCD',
  // Health
  'JNJ', 'UNH', 'PFE', 'LLY', 'ABBV',
  // Industrial / Energy
  'XOM', 'CVX', 'CAT', 'BA', 'GE',
  // China ADRs
  'BABA', 'PDD', 'JD', 'NIO', 'BIDU',
] as const

export function DiscoverChip(): React.ReactElement {
  const navigate = useNavigate()
  const watchlist = useStocksStore((s) => s.watchlist)
  const currentTicker = useStocksStore((s) => s.currentTicker)

  const handleDiscover = useCallback(() => {
    // Exclude watchlist + current ticker so the user always lands somewhere new
    const exclude = new Set([
      ...Array.from(watchlist),
      currentTicker?.toUpperCase() ?? '',
    ])
    const candidates = DISCOVERY_POOL.filter((t) => !exclude.has(t))
    const pool = candidates.length > 0 ? candidates : DISCOVERY_POOL
    const picked = pool[Math.floor(Math.random() * pool.length)]
    navigate(`/stocks/${picked}`)
  }, [navigate, watchlist, currentTicker])

  return (
    <button
      onClick={handleDiscover}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '5px 11px',
        background: 'transparent',
        border: '1px dashed var(--border)',
        borderRadius: 999,
        fontFamily: 'var(--font-ui)',
        fontSize: 11,
        color: 'var(--text-secondary)',
        cursor: 'pointer',
        transition: 'all 0.15s',
      }}
      onMouseEnter={(e) => {
        const el = e.currentTarget
        el.style.borderColor = 'var(--accent)'
        el.style.color = 'var(--accent)'
        el.style.borderStyle = 'solid'
      }}
      onMouseLeave={(e) => {
        const el = e.currentTarget
        el.style.borderColor = 'var(--border)'
        el.style.color = 'var(--text-secondary)'
        el.style.borderStyle = 'dashed'
      }}
      title="随机带你去一只 watchlist 之外的股票"
      aria-label="发现新股票"
      type="button"
    >
      🎲 随机看一只
    </button>
  )
}
