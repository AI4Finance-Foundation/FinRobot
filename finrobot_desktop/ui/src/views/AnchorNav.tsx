// v5 Anchor Nav — 5 grouped horizontal anchor list under the sticky hero
// (spec §3.3). IntersectionObserver lights up the section currently in
// view; clicking a label scrolls smoothly with the sticky-header offset.

import { useEffect, useState } from 'react'

interface AnchorGroup {
  label: string
  items: { id: string; label: string }[]
}

// Mirror of spec §3.3 — 5 groups, 14 sections total (sec-now hidden in cold
// state but listed here so the IntersectionObserver can latch onto it the
// moment data arrives).
const ANCHOR_GROUPS: AnchorGroup[] = [
  {
    label: '总览',
    items: [
      { id: 'sec-now', label: '当前判断' },
      { id: 'sec-score', label: '综合评分' },
      { id: 'sec-catalyst', label: '催化剂' },
      { id: 'sec-risk', label: '风险' },
    ],
  },
  {
    label: '估值',
    items: [
      { id: 'sec-football', label: '估值范围' },
      { id: 'sec-sensitivity', label: '敏感性' },
      { id: 'sec-band', label: '历史估值带' },
      { id: 'sec-monte-carlo', label: '蒙特卡洛' },
    ],
  },
  {
    label: '数据',
    items: [
      { id: 'sec-data', label: '快照' },
      { id: 'sec-price', label: '股价走势' },
      { id: 'sec-revenue', label: '营收 / EBITDA' },
      { id: 'sec-margins', label: '利润率' },
      { id: 'sec-cashflow', label: '现金流' },
      { id: 'sec-financials', label: '季度财务' },
      { id: 'sec-performance', label: '走势统计' },
    ],
  },
  {
    label: '市场',
    items: [
      { id: 'sec-peers', label: '同业表' },
      { id: 'sec-peer-radar', label: '同业雷达' },
      { id: 'sec-peer-bars', label: '同业倍数' },
      { id: 'sec-sniper', label: '阻力支撑' },
      { id: 'sec-news', label: '新闻' },
      { id: 'sec-sentiment', label: '散户情绪' },
      { id: 'sec-earnings', label: '财报会' },
    ],
  },
  {
    label: '我的',
    items: [{ id: 'sec-research', label: '我的研究' }],
  },
]

const STICKY_OFFSET = 110

export function AnchorNav(): React.ReactElement {
  const [activeId, setActiveId] = useState<string | null>(null)

  // IntersectionObserver — flag the section with the largest visible portion
  // as active. threshold 0.3 matches spec §3.3. JSDOM doesn't ship the API,
  // so we no-op there (test environment) and let click-to-scroll still work.
  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') {
      return
    }
    const ids = ANCHOR_GROUPS.flatMap((g) => g.items.map((i) => i.id))
    const observed: HTMLElement[] = ids
      .map((id) => document.getElementById(id))
      .filter((el): el is HTMLElement => el !== null)

    if (observed.length === 0) return

    const visibility = new Map<string, number>()
    const observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          visibility.set(e.target.id, e.intersectionRatio)
        }
        let best: { id: string; ratio: number } | null = null
        for (const [id, ratio] of visibility) {
          if (ratio > 0 && (!best || ratio > best.ratio)) {
            best = { id, ratio }
          }
        }
        setActiveId(best ? best.id : null)
      },
      { threshold: [0, 0.3, 0.6, 1] }
    )
    for (const el of observed) observer.observe(el)
    return () => observer.disconnect()
  }, [])

  function scrollTo(id: string) {
    const el = document.getElementById(id)
    if (!el) return
    const target = el.getBoundingClientRect().top + window.scrollY - STICKY_OFFSET
    window.scrollTo({ top: target, behavior: 'smooth' })
  }

  return (
    <nav
      data-testid="anchor-nav"
      style={{
        position: 'sticky',
        top: STICKY_OFFSET,
        zIndex: 9,
        background: 'var(--bg-card, #fff)',
        borderBottom: '1px solid var(--border)',
        overflowX: 'auto',
        overflowY: 'hidden',
        height: 42,
      }}
    >
      {/* No maxWidth here — let the row expand to its natural width so the
          nav's overflowX:auto kicks in instead of flex shrinking the labels
          into vertical 2-char columns. */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '0 24px',
          height: '100%',
          width: 'max-content',
          minWidth: '100%',
        }}
      >
        {ANCHOR_GROUPS.map((group, gi) => (
          <span
            key={group.label}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              flexShrink: 0,
              whiteSpace: 'nowrap',
            }}
          >
            <span
              aria-hidden="true"
              style={{
                color: 'var(--text-faint)',
                fontSize: 11,
                letterSpacing: 0.4,
                textTransform: 'uppercase',
                whiteSpace: 'nowrap',
                flexShrink: 0,
              }}
            >
              {group.label}
            </span>
            {group.items.map((item) => {
              const active = activeId === item.id
              return (
                <button
                  key={item.id}
                  type="button"
                  data-testid={`anchor-${item.id}`}
                  onClick={() => scrollTo(item.id)}
                  style={{
                    display: 'inline-block',
                    padding: '4px 8px',
                    borderRadius: 4,
                    border: 'none',
                    background: active ? 'rgba(16, 185, 129, 0.08)' : 'transparent',
                    color: active ? 'var(--green, #10B981)' : 'var(--text-soft)',
                    fontSize: 12,
                    fontWeight: active ? 600 : 400,
                    cursor: 'pointer',
                    whiteSpace: 'nowrap',
                    flexShrink: 0,
                  }}
                >
                  {item.label}
                </button>
              )
            })}
            {gi < ANCHOR_GROUPS.length - 1 && (
              <span
                aria-hidden="true"
                className="anchor-group-divider"
                style={{ width: 1, height: 16, background: 'var(--border)', flexShrink: 0 }}
              />
            )}
          </span>
        ))}
      </div>
    </nav>
  )
}
