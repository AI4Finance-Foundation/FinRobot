/**
 * TermTip — hover tooltip for financial jargon, with optional "ask LLM" deep dive.
 *
 * 散户痛点：屏幕上一堆 WACC / P/E / EBITDA / FCF / DCF 看不懂。
 * 这里给 1 句话兜底解释 + 点击让 RightChatPanel 详细讲。
 *
 * Why a local glossary instead of always asking LLM?
 *   - 即时显示，hover 不需要网络
 *   - 一致性，每次都一样的简短解释
 *   - 用户想深入时再点击触发 LLM 段
 */

import { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { useUiStore } from '../stores/uiStore'

const GLOSSARY: Record<string, { short: string; askPrompt: string }> = {
  DCF: {
    short: '折现现金流估值法：把未来现金流折回今天的价值',
    askPrompt:
      '用一段中文给我解释 DCF（折现现金流估值法），假设我是金融新手。说清楚核心思想、3 个关键输入、最大的局限。',
  },
  WACC: {
    short: '加权平均资本成本，DCF 里的"折现率"',
    askPrompt:
      'WACC（加权平均资本成本）是什么？怎么算出来的？为什么 DCF 模型最敏感的参数就是它？用一段中文给金融新手解释。',
  },
  'P/E': {
    short: '市盈率 = 股价 / 每股收益。多少年回本',
    askPrompt: 'P/E 市盈率怎么用？高 PE 一定贵吗？给我一段中文解释正确用法。',
  },
  PE: {
    short: '市盈率 = 股价 / 每股收益。多少年回本',
    askPrompt: 'P/E 市盈率怎么用？高 PE 一定贵吗？给我一段中文解释正确用法。',
  },
  EBITDA: {
    short: '息税折旧摊销前利润，剥离财务和会计影响的"经营盈利"',
    askPrompt: 'EBITDA 是什么？为什么估值时常用 EV/EBITDA 而不是 PE？用一段中文给金融新手解释。',
  },
  FCF: {
    short: '自由现金流 = 经营现金流 - 资本开支。真正能分给股东的钱',
    askPrompt:
      '自由现金流 FCF 和净利润有什么区别？为什么估值时大家更看 FCF？用一段中文给金融新手解释。',
  },
  EV: {
    short: '企业价值 = 市值 + 净债务。代表收购公司要付的总钱',
    askPrompt:
      'Enterprise Value（企业价值，EV）是什么？为什么不直接用市值？用一段中文给金融新手解释。',
  },
  IRR: {
    short: '内部收益率：让 NPV = 0 的折现率，常用于 LBO',
    askPrompt: 'IRR（内部收益率）是什么意思？LBO 里 18% IRR 算高还是低？用一段中文给金融新手解释。',
  },
  LBO: {
    short: '杠杆收购：借大量债务买下公司、还债、卖出获利',
    askPrompt: 'LBO（杠杆收购）模型在干什么？跟 DCF 有什么区别？用一段中文给金融新手解释。',
  },
  DDM: {
    short: '股息折现模型：把未来股息折现成股权价值',
    askPrompt:
      'DDM（股息折现模型）适合什么样的公司？为什么科技股不常用？用一段中文给金融新手解释。',
  },
  Beta: {
    short: '股票相对市场的波动倍数，beta=1 跟市场同步',
    askPrompt:
      'Beta 在 CAPM 里是干什么用的？Beta 0.8 vs 1.5 意味着什么？用一段中文给金融新手解释。',
  },
  ROE: {
    short: '净资产收益率 = 净利润 / 股东权益。股东资本的"赚钱效率"',
    askPrompt: 'ROE（净资产收益率）多少算优秀？跟 ROA、ROIC 有什么区别？用一段中文给金融新手解释。',
  },
  'Terminal Value': {
    short: '终值：永续期之后所有现金流的现值，DCF 里通常占总价值 60-80%',
    askPrompt:
      'Terminal Value（终值）在 DCF 里是怎么算的？为什么它对结果影响这么大？用一段中文给金融新手解释。',
  },
  'PV of FCF': {
    short: '预测期内自由现金流的现值之和（折现回今天）',
    askPrompt:
      'PV of FCF（自由现金流现值）是什么？为什么 DCF 要把未来的钱折回今天？用一段中文给金融新手解释。',
  },
  'Enterprise Value': {
    short: '企业价值 = 股权 + 净债务。代表买下整个公司要付的钱',
    askPrompt:
      'Enterprise Value（企业价值）和市值有什么区别？为什么估值时常用 EV 而不是 Market Cap？用一段中文给金融新手解释。',
  },
  'Equity Value': {
    short: '股权价值 = 企业价值 - 净债务。归股东的那部分',
    askPrompt:
      'Equity Value（股权价值）和 Enterprise Value 怎么换算？这两个值哪个对散户更有用？用一段中文给金融新手解释。',
  },
  'EV/EBITDA': {
    short: '企业价值 / 经营盈利。看几年能用经营利润回本',
    askPrompt:
      'EV/EBITDA 这个估值倍数怎么用？多少算便宜？跟 P/E 有什么区别？用一段中文给金融新手解释。',
  },
  Beat: {
    short: '超预期：实际 EPS 高于分析师一致预期',
    askPrompt:
      '财报 Beat（超预期）一定意味着股价会涨吗？应该看哪些细节？用一段中文给金融新手解释。',
  },
  Miss: {
    short: '不及预期：实际 EPS 低于分析师一致预期',
    askPrompt: '财报 Miss（不及预期）后该追跌还是抄底？应该看哪些细节？用一段中文给金融新手解释。',
  },
}

export function isKnownTerm(term: string): boolean {
  return term in GLOSSARY
}

interface Props {
  /** Term to look up (case-sensitive, must be in GLOSSARY) */
  term: string
  /** Optional display text — defaults to `term`. Useful for `WACC %` etc. */
  children?: React.ReactNode
}

export function TermTip({ term, children }: Props): React.ReactElement {
  const entry = GLOSSARY[term]
  const [open, setOpen] = useState(false)
  const [coords, setCoords] = useState<{ x: number; y: number } | null>(null)
  const anchorRef = useRef<HTMLSpanElement>(null)
  const sendChatPrompt = useUiStore((s) => s.sendChatPrompt)

  // Reposition on open so the popover sits below the anchor.
  useEffect(() => {
    if (!open || !anchorRef.current) return
    const rect = anchorRef.current.getBoundingClientRect()
    setCoords({ x: rect.left, y: rect.bottom + 6 })
  }, [open])

  // Unknown terms render plain text (no tooltip, no errors)
  if (!entry) {
    return <span>{children ?? term}</span>
  }

  return (
    <>
      <span
        ref={anchorRef}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        tabIndex={0}
        style={{
          borderBottom: '1px dotted var(--text-muted)',
          cursor: 'help',
          fontStyle: 'normal',
        }}
        aria-label={`术语：${term}`}
      >
        {children ?? term}
      </span>

      {open &&
        coords &&
        createPortal(
          <div
            style={{
              position: 'fixed',
              left: coords.x,
              top: coords.y,
              zIndex: 9999,
              maxWidth: 320,
              background: 'var(--bg-1)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--r-md)',
              padding: '10px 12px',
              boxShadow: '0 6px 24px rgba(0,0,0,0.18)',
              fontFamily: 'var(--font-ui)',
              fontSize: 12,
              lineHeight: 1.55,
              color: 'var(--text-primary)',
              pointerEvents: 'auto',
            }}
            onMouseEnter={() => setOpen(true)}
            onMouseLeave={() => setOpen(false)}
          >
            <div style={{ marginBottom: 8, color: 'var(--text-primary)' }}>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontWeight: 700,
                  color: 'var(--accent)',
                  marginRight: 6,
                }}
              >
                {term}
              </span>
              <span style={{ color: 'var(--text-secondary)' }}>{entry.short}</span>
            </div>
            <button
              onClick={() => {
                sendChatPrompt(entry.askPrompt, true)
                setOpen(false)
              }}
              style={{
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
              让 FinAgent 详细讲讲 →
            </button>
          </div>,
          document.body,
        )}
    </>
  )
}
