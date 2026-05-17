/**
 * LearningCarousel — Dashboard 学习卡片轮播
 *
 * 散户最大痛点：不懂 DCF/PE/10-K/WACC。这块就是给他们一个低门槛入口。
 * 点击任意卡片 → 通过 sendChatPrompt 把问题打到 RightChatPanel 让 LLM 解释。
 *
 * 内容是固定的（精挑细选的"必懂概念"），但提问通过 LLM 现写，所以解释总是新鲜的。
 */

import { useState, useEffect, useRef } from 'react'
import { useUiStore } from '../../stores/uiStore'

interface LearningTopic {
  /** Card title shown on hover */
  title: string
  /** Short hook visible on card face */
  hook: string
  /** What gets sent to the LLM when clicked */
  prompt: string
}

const TOPICS: LearningTopic[] = [
  {
    title: 'DCF 是什么',
    hook: '30 秒讲清 DCF',
    prompt: '用一段简单的中文给我解释 DCF（折现现金流估值法），假设我是金融新手。说清楚：核心思想、3 个关键输入、最大的局限。控制在 200 字以内。',
  },
  {
    title: 'PE 怎么用',
    hook: '市盈率高 = 贵？',
    prompt: '高 PE 一定意味着股票贵吗？用一段中文解释市盈率的正确使用方法：什么时候 PE 有用、什么时候没用、要跟什么对比。控制在 200 字以内。',
  },
  {
    title: 'WACC 凭什么',
    hook: 'WACC 8% 是怎么来的',
    prompt: '加权平均资本成本 WACC 是怎么算出来的？为什么不同公司差别很大？用一段中文给金融新手讲清楚，控制在 200 字以内。',
  },
  {
    title: '10-K 怎么读',
    hook: '300 页年报抓重点',
    prompt: '美股 10-K 年报有几百页，散户该怎么快速抓重点？告诉我 5 个必看的部分和每个的关键问题。控制在 250 字以内。',
  },
  {
    title: 'FCF vs 净利润',
    hook: '为什么 FCF 更重要',
    prompt: '自由现金流 FCF 和净利润有什么区别？为什么估值时大家更看 FCF？用一段中文给金融新手解释，控制在 200 字以内。',
  },
  {
    title: '蒙特卡洛',
    hook: '为什么估值要跑 10000 次',
    prompt: '蒙特卡洛模拟在估值里是干什么用的？跟普通的 DCF 比有什么优势？用一段中文给金融新手解释，控制在 200 字以内。',
  },
]

export function LearningCarousel(): React.ReactElement {
  const sendChatPrompt = useUiStore((s) => s.sendChatPrompt)
  const scrollerRef = useRef<HTMLDivElement>(null)
  const [canLeft, setCanLeft] = useState(false)
  const [canRight, setCanRight] = useState(true)

  const updateButtons = (): void => {
    const el = scrollerRef.current
    if (!el) return
    setCanLeft(el.scrollLeft > 4)
    setCanRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 4)
  }

  useEffect(() => {
    updateButtons()
    const el = scrollerRef.current
    if (!el) return
    el.addEventListener('scroll', updateButtons, { passive: true })
    const ro = new ResizeObserver(updateButtons)
    ro.observe(el)
    return () => {
      el.removeEventListener('scroll', updateButtons)
      ro.disconnect()
    }
  }, [])

  function scrollBy(delta: number): void {
    scrollerRef.current?.scrollBy({ left: delta, behavior: 'smooth' })
  }

  return (
    <section data-testid="learning-carousel">
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 8,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
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
            30 秒学一个
          </span>
          <span
            style={{
              fontSize: 10,
              color: 'var(--text-muted)',
              fontStyle: 'italic',
            }}
          >
            · 点击任一卡片让 FinAgent 给你讲清
          </span>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          <ArrowButton dir="left" disabled={!canLeft} onClick={() => scrollBy(-320)} />
          <ArrowButton dir="right" disabled={!canRight} onClick={() => scrollBy(320)} />
        </div>
      </div>

      <div
        ref={scrollerRef}
        style={{
          display: 'flex',
          gap: 10,
          overflowX: 'auto',
          paddingBottom: 4,
          scrollSnapType: 'x mandatory',
          scrollbarWidth: 'none',
        }}
        // hide webkit scrollbar
        className="hide-scrollbar"
      >
        {TOPICS.map((t) => (
          <button
            key={t.title}
            onClick={() => sendChatPrompt(t.prompt, true)}
            style={{
              flexShrink: 0,
              width: 200,
              padding: '14px 16px',
              background: 'var(--bg-1)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--r-md)',
              cursor: 'pointer',
              textAlign: 'left',
              transition: 'all 0.18s',
              scrollSnapAlign: 'start',
            }}
            onMouseEnter={(e) => {
              const el = e.currentTarget
              el.style.borderColor = 'var(--accent)'
              el.style.transform = 'translateY(-1px)'
              el.style.boxShadow = '0 2px 12px rgba(59,130,246,0.10)'
            }}
            onMouseLeave={(e) => {
              const el = e.currentTarget
              el.style.borderColor = 'var(--border)'
              el.style.transform = 'translateY(0)'
              el.style.boxShadow = 'none'
            }}
            aria-label={`让 FinAgent 讲讲: ${t.title}`}
            title={`让 FinAgent 讲讲: ${t.title}`}
          >
            <div
              style={{
                fontSize: 12,
                fontWeight: 600,
                color: 'var(--text-primary)',
                marginBottom: 6,
                fontFamily: 'var(--font-ui)',
              }}
            >
              {t.title}
            </div>
            <div
              style={{
                fontSize: 11,
                color: 'var(--text-muted)',
                lineHeight: 1.5,
                fontFamily: 'var(--font-ui)',
              }}
            >
              {t.hook}
            </div>
          </button>
        ))}
      </div>
    </section>
  )
}

function ArrowButton({
  dir,
  disabled,
  onClick,
}: {
  dir: 'left' | 'right'
  disabled: boolean
  onClick: () => void
}): React.ReactElement {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      aria-label={dir === 'left' ? '向左滚动' : '向右滚动'}
      style={{
        width: 22,
        height: 22,
        borderRadius: 4,
        border: '1px solid var(--border)',
        background: 'var(--bg-2)',
        color: disabled ? 'var(--text-muted)' : 'var(--text-secondary)',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.4 : 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: 14,
        lineHeight: 1,
        transition: 'all 0.15s',
      }}
      onMouseEnter={(e) => {
        if (!disabled) (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--accent)'
      }}
      onMouseLeave={(e) => {
        if (!disabled) (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--border)'
      }}
      type="button"
    >
      {dir === 'left' ? '‹' : '›'}
    </button>
  )
}
