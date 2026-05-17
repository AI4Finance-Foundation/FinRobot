/**
 * ValuationOutliersCard — Dashboard 估值偏离卡片
 *
 * FinAgent 跟 Yahoo Finance / Robinhood 最大的差异点：自选股一眼能看出
 * 哪只在 DCF 模型下「便宜」（current < implied）或「贵」（current > implied）。
 *
 * 用现有的 DCF artifact —— 不触发新计算（贵），鼓励用户去 Playground 跑。
 * 有诚实兜底：没 DCF 的 ticker 显示 [跑 DCF] 按钮直接跳到 Playground。
 */

import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../../api/client'
import { useStocksStore } from '../../stores/stocksStore'
import { TermTip } from '../TermTip'

interface ValuationItem {
  ticker: string
  current_price: number | null
  implied_price: number | null
  offset_pct: number | null
  dcf_age_h: number | null
  artifact_id: string | null
}

interface ValuationOverview {
  items: ValuationItem[]
  generated_at: number
}

async function fetchOverview(watchlist: string[]): Promise<ValuationOverview> {
  const r = await fetch(`${BASE_URL}/api/dashboard/valuation-overview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ watchlist }),
  })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json() as Promise<ValuationOverview>
}

function fmtPrice(v: number | null | undefined): string {
  if (v == null) return '—'
  return `$${v.toFixed(2)}`
}

function fmtOffset(v: number | null): string {
  if (v == null) return '—'
  const sign = v >= 0 ? '+' : ''
  return `${sign}${v.toFixed(1)}%`
}

function ageLabel(h: number | null): string {
  if (h == null) return ''
  if (h < 1) return `${Math.round(h * 60)}m`
  if (h < 24) return `${Math.round(h)}h`
  return `${Math.round(h / 24)}d`
}

function offsetColor(v: number | null): string {
  if (v == null) return 'var(--text-muted)'
  if (v >= 10) return 'var(--positive)'   // implied >> current → cheap
  if (v <= -10) return 'var(--negative)'  // implied << current → expensive
  return 'var(--text-secondary)'
}

export function ValuationOutliersCard(): React.ReactElement | null {
  const navigate = useNavigate()
  const watchlist = useStocksStore((s) => s.watchlist)
  const watchlistArr = useMemo(() => Array.from(watchlist).sort(), [watchlist])

  const { data, isLoading, isError } = useQuery<ValuationOverview>({
    queryKey: ['dashboard-valuation-overview', watchlistArr.join(',')],
    queryFn: () => fetchOverview(watchlistArr),
    enabled: watchlistArr.length > 0,
    staleTime: 5 * 60_000, // 5 min
    retry: 1,
  })

  // Hide entirely when no watchlist (sidebar already nudges user to add)
  if (watchlistArr.length === 0) return null

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
          估值偏离 (<TermTip term="DCF">DCF</TermTip>)
        </span>
        <span
          style={{
            fontSize: 10,
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-mono)',
          }}
        >
          基于最近的 DCF 快照
        </span>
      </div>

      {isLoading && !data && (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
          }}
        >
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              style={{
                height: 38,
                background: 'var(--bg-3)',
                borderRadius: 'var(--r-sm)',
                animation: 'skeleton-pulse 1.5s ease infinite',
              }}
            />
          ))}
        </div>
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
          估值数据暂不可用
        </div>
      )}

      {data && data.items.length === 0 && (
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
          自选股暂无估值数据
        </div>
      )}

      {data && data.items.length > 0 && (
        <div
          style={{
            background: 'var(--bg-1)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--r-md)',
            overflow: 'hidden',
          }}
        >
          {data.items.map((it, idx) => (
            <ValuationRow
              key={it.ticker}
              item={it}
              isLast={idx === data.items.length - 1}
              onView={() => navigate(`/stocks/${it.ticker}`)}
              onRunDCF={() => navigate(`/playground/${it.ticker}`)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function ValuationRow({
  item,
  isLast,
  onView,
  onRunDCF,
}: {
  item: ValuationItem
  isLast: boolean
  onView: () => void
  onRunDCF: () => void
}): React.ReactElement {
  const hasOffset = item.offset_pct != null
  const color = offsetColor(item.offset_pct)
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '10px 14px',
        borderBottom: isLast ? 'none' : '1px solid var(--border)',
      }}
    >
      <button
        onClick={onView}
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 12,
          fontWeight: 700,
          color: 'var(--accent)',
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          padding: 0,
          width: 56,
          textAlign: 'left',
          flexShrink: 0,
        }}
        type="button"
        title={`查看 ${item.ticker}`}
      >
        {item.ticker}
      </button>

      {hasOffset ? (
        <>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: 'var(--text-muted)',
              flexShrink: 0,
              minWidth: 60,
            }}
          >
            {fmtPrice(item.current_price)} → {fmtPrice(item.implied_price)}
          </span>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 13,
              fontWeight: 700,
              color,
              flex: 1,
              textAlign: 'right',
              fontVariantNumeric: 'tabular-nums',
            }}
            title={
              item.offset_pct! >= 0
                ? 'DCF 隐含价高于市价 → 模型认为偏便宜'
                : 'DCF 隐含价低于市价 → 模型认为偏贵'
            }
          >
            {fmtOffset(item.offset_pct)}
          </span>
          {item.dcf_age_h != null && (
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 9,
                color: 'var(--text-muted)',
                flexShrink: 0,
                minWidth: 28,
                textAlign: 'right',
              }}
              title={`DCF 快照于 ${item.dcf_age_h} 小时前`}
            >
              {ageLabel(item.dcf_age_h)}
            </span>
          )}
        </>
      ) : (
        <>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: 'var(--text-muted)',
              flexShrink: 0,
              minWidth: 60,
            }}
          >
            {fmtPrice(item.current_price)}
          </span>
          <span
            style={{
              fontSize: 11,
              color: 'var(--text-muted)',
              flex: 1,
              fontStyle: 'italic',
            }}
          >
            暂无 DCF
          </span>
          <button
            onClick={onRunDCF}
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              color: 'var(--accent)',
              background: 'var(--accent-dim)',
              border: 'none',
              borderRadius: 3,
              padding: '3px 8px',
              cursor: 'pointer',
              flexShrink: 0,
            }}
            type="button"
            title={`在估值推演页跑 ${item.ticker} 的 DCF`}
          >
            跑 DCF →
          </button>
        </>
      )}
    </div>
  )
}
