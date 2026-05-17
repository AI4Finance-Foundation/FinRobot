/**
 * WhyMovingPopover — 「今日为啥动」一句话解释，浮窗显示。
 *
 * 用在 Sidebar WatchlistItem / StockHeader 等地方。点击触发懒加载（不要 hover
 * 就 fetch，会烧钱）。
 *
 * 后端 POST /api/dashboard/explain-move/{ticker}：取价格 + 新闻 + 催化剂 →
 * LLM 1-2 句中文。30 分钟缓存。
 */

import { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { useUiStore } from '../stores/uiStore'
import { BASE_URL } from '../api/client'

interface WhyMovingResponse {
  ticker: string
  change_pct: number | null
  explanation: string
  sources: string[]
  model: string
  generated_at: number
}

async function fetchExplain(ticker: string): Promise<WhyMovingResponse> {
  const r = await fetch(`${BASE_URL}/api/dashboard/explain-move/${ticker}`, {
    method: 'POST',
  })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json() as Promise<WhyMovingResponse>
}

interface Props {
  ticker: string
  /** Element that triggers the popover (clickable wrapper). */
  children: (props: { onClick: (e: React.MouseEvent) => void; ariaExpanded: boolean }) => React.ReactNode
}

export function WhyMovingPopover({ ticker, children }: Props): React.ReactElement {
  const sendChatPrompt = useUiStore((s) => s.sendChatPrompt)
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<WhyMovingResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [coords, setCoords] = useState<{ x: number; y: number } | null>(null)
  const triggerRef = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    if (data || loading) return
    setLoading(true)
    setError(null)
    fetchExplain(ticker)
      .then((res) => setData(res))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [open, ticker, data, loading])

  // Close on click outside / Esc
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') setOpen(false)
    }
    const onClick = (e: MouseEvent): void => {
      const t = e.target as Node
      if (triggerRef.current?.contains(t)) return
      const popover = document.getElementById(`why-popover-${ticker}`)
      if (popover?.contains(t)) return
      setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('mousedown', onClick)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('mousedown', onClick)
    }
  }, [open, ticker])

  const handleClick = (e: React.MouseEvent): void => {
    e.preventDefault()
    e.stopPropagation()
    if (!open && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect()
      setCoords({ x: Math.max(8, rect.right - 280), y: rect.bottom + 6 })
    }
    setOpen((v) => !v)
  }

  const fmtPct = (v: number | null): string => {
    if (v == null) return '—'
    return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
  }

  return (
    <>
      <span ref={triggerRef}>
        {children({ onClick: handleClick, ariaExpanded: open })}
      </span>
      {open && coords && createPortal(
        <div
          id={`why-popover-${ticker}`}
          role="dialog"
          aria-label={`${ticker} 今日动向`}
          style={{
            position: 'fixed',
            left: coords.x,
            top: coords.y,
            zIndex: 9999,
            width: 280,
            background: 'var(--bg-1)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--r-md)',
            padding: '12px 14px',
            boxShadow: '0 8px 28px rgba(0,0,0,0.22)',
            fontFamily: 'var(--font-ui)',
            fontSize: 12,
            lineHeight: 1.55,
            color: 'var(--text-primary)',
          }}
        >
          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 8 }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--accent)', fontSize: 13 }}>
              {ticker}
            </span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
              今日 {fmtPct(data?.change_pct ?? null)}
            </span>
          </div>

          {/* Body */}
          {loading && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  style={{
                    height: 10,
                    background: 'var(--bg-3)',
                    borderRadius: 3,
                    width: i === 2 ? '70%' : '100%',
                    animation: 'skeleton-pulse 1.5s ease infinite',
                  }}
                />
              ))}
            </div>
          )}

          {error && (
            <div style={{ color: 'var(--negative)', fontSize: 11 }}>
              获取失败：{error}
            </div>
          )}

          {data && !loading && (
            <>
              <p style={{ margin: 0, color: 'var(--text-primary)' }}>
                {data.explanation}
              </p>

              {data.sources.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.06em', fontFamily: 'var(--font-mono)' }}>
                    数据来源
                  </div>
                  <ul style={{ margin: 0, padding: '0 0 0 14px', color: 'var(--text-secondary)' }}>
                    {data.sources.slice(0, 3).map((s, i) => (
                      <li key={i} style={{ fontSize: 11, marginBottom: 2 }}>
                        {s.length > 60 ? `${s.slice(0, 60)}…` : s}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <button
                onClick={() => {
                  sendChatPrompt(
                    `${ticker} 今天 ${fmtPct(data.change_pct)}，请深入分析驱动因素：相关新闻 / 板块联动 / 估值变化 / 后续催化剂。中文回答，控制 300 字内。`,
                    true,
                  )
                  setOpen(false)
                }}
                style={{
                  marginTop: 10,
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--accent)',
                  fontSize: 11,
                  cursor: 'pointer',
                  padding: 0,
                  fontFamily: 'var(--font-ui)',
                  textDecoration: 'underline',
                }}
                type="button"
              >
                让 FinAgent 深入分析 →
              </button>
            </>
          )}
        </div>,
        document.body,
      )}
    </>
  )
}
