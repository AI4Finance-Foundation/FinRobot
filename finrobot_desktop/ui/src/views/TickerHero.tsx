// v5 Ticker Hero — sticky top bar with symbol / live price / 自选 toggle /
// + 跑分析 dropdown / ↻ 重跑 button (spec §3.2). The dropdown content is a
// PR8 deliverable; this file only renders the trigger so the hero can ship
// without blocking on the run-analysis menu.

import { useState } from 'react'
import { useTickerPrice } from '../hooks/useTickerData'
import { useStocksStore } from '../stores/stocksStore'
import { RunAnalysisDropdown } from './RunAnalysisDropdown'

// Inline icons — PR16 will swap the whole codebase to lucide-react SVG.
// Until then we keep dependency-light inline strokes; visual close enough
// for the placeholder hero.
function StarIcon({ filled, size = 16 }: { filled?: boolean; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={filled ? '#F59E0B' : 'none'}
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
    </svg>
  )
}

function RefreshIcon({ size = 13 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="23 4 23 10 17 10" />
      <polyline points="1 20 1 14 7 14" />
      <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
    </svg>
  )
}

function ChevronDownIcon({ size = 14 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  )
}

const STICKY_HEIGHT = 110

interface TickerHeroProps {
  ticker: string
}

export function TickerHero({ ticker }: TickerHeroProps): React.ReactElement {
  const { data: price } = useTickerPrice(ticker)
  const watchlist = useStocksStore((s) => s.watchlist)
  const toggleWatchlist = useStocksStore((s) => s.toggleWatchlist)
  const isWatched = watchlist.has(ticker)
  const [dropdownOpen, setDropdownOpen] = useState(false)

  const current = price?.current_price
  const changePct = price?.change_pct
  const isUp = typeof changePct === 'number' && changePct >= 0

  return (
    <header
      data-testid="ticker-hero"
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 10,
        background: 'var(--bg-card, #fff)',
        borderBottom: '1px solid var(--border)',
        padding: '12px 24px 0',
        height: STICKY_HEIGHT,
        boxSizing: 'border-box',
      }}
    >
      <div
        style={{
          maxWidth: 960,
          margin: '0 auto',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 16,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
          <span style={{ fontSize: 18, fontWeight: 700, letterSpacing: 0.2 }}>{ticker}</span>
          {current !== undefined && (
            <>
              <span style={{ fontSize: 17, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                ${current.toFixed(2)}
              </span>
              {typeof changePct === 'number' && (
                <span
                  style={{
                    fontSize: 11.5,
                    color: isUp ? 'var(--green, #10B981)' : 'var(--red, #EF4444)',
                    fontVariantNumeric: 'tabular-nums',
                  }}
                >
                  {isUp ? '↑' : '↓'} {Math.abs(changePct).toFixed(2)}%
                </span>
              )}
            </>
          )}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            type="button"
            data-testid="watchlist-toggle"
            title={isWatched ? '从自选股移除' : '加入自选股'}
            onClick={() => toggleWatchlist(ticker)}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: 6,
              borderRadius: 6,
              border: '1px solid var(--border)',
              background: isWatched ? 'rgba(245, 158, 11, 0.10)' : 'transparent',
              color: isWatched ? '#F59E0B' : 'var(--text-soft)',
              cursor: 'pointer',
            }}
          >
            <StarIcon filled={isWatched} size={16} />
          </button>

          <div style={{ position: 'relative' }}>
            <button
              type="button"
              data-testid="run-analysis-trigger"
              onClick={() => setDropdownOpen((v) => !v)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                padding: '6px 12px',
                borderRadius: 6,
                background: 'var(--green, #10B981)',
                color: 'white',
                border: 'none',
                fontSize: 13,
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              + 跑分析 <ChevronDownIcon size={14} />
            </button>
            {dropdownOpen && (
              <div
                style={{
                  position: 'absolute',
                  right: 0,
                  top: 'calc(100% + 4px)',
                }}
              >
                <RunAnalysisDropdown
                  ticker={ticker}
                  onLaunched={() => setDropdownOpen(false)}
                />
              </div>
            )}
          </div>

          <button
            type="button"
            data-testid="rerun-latest"
            title="重跑最新分析"
            disabled
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              padding: '6px 10px',
              borderRadius: 6,
              border: '1px solid var(--border)',
              background: 'transparent',
              color: 'var(--text-faint)',
              fontSize: 12,
              cursor: 'not-allowed',
            }}
          >
            <RefreshIcon size={13} /> 重跑
          </button>
        </div>
      </div>
    </header>
  )
}
