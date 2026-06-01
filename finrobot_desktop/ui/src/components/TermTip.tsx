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
import { useI18n } from '../i18n'

// Each glossary entry maps a term to its i18n key suffix. The actual short
// definition and "ask LLM" prompt live in the catalogs under
// `term.<key>.short` / `term.<key>.ask`, so they translate + re-render on
// locale change (resolved inside the component via useI18n).
const GLOSSARY: Record<string, string> = {
  DCF: 'dcf',
  WACC: 'wacc',
  'P/E': 'pe',
  PE: 'pe',
  EBITDA: 'ebitda',
  FCF: 'fcf',
  EV: 'ev',
  IRR: 'irr',
  LBO: 'lbo',
  DDM: 'ddm',
  Beta: 'beta',
  ROE: 'roe',
  'Terminal Value': 'terminalValue',
  'PV of FCF': 'pvOfFcf',
  'Enterprise Value': 'enterpriseValue',
  'Equity Value': 'equityValue',
  'EV/EBITDA': 'evEbitda',
  Beat: 'beat',
  Miss: 'miss',
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
  const keySuffix = GLOSSARY[term]
  const { t } = useI18n()
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
  if (!keySuffix) {
    return <span>{children ?? term}</span>
  }

  const short = t(`term.${keySuffix}.short`)
  const askPrompt = t(`term.${keySuffix}.ask`)

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
        aria-label={t('term.ariaLabel', { term })}
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
              <span style={{ color: 'var(--text-secondary)' }}>{short}</span>
            </div>
            <button
              onClick={() => {
                sendChatPrompt(askPrompt, true)
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
              {t('term.askMore')}
            </button>
          </div>,
          document.body,
        )}
    </>
  )
}
