/**
 * TermTip — hover tooltip for financial jargon, with optional "ask LLM" deep dive.
 *
 * 高要求但非投行背景的读者(分析师助理 / 跨界研究员)碰到密集的
 * WACC / NOPAT / EV-EBITDA / FCFF / 13F / DEF 14A,需要就地一句话口径解释,
 * 想深挖再点 "ask FinRobot" 让 RightChatPanel 展开。不做散户化简化,只补口径。
 *
 * Why a local glossary instead of always asking LLM?
 *   - 即时显示,hover 不需要网络
 *   - 一致性,每次都一样的简短、口径准确的解释
 *   - 用户想深入时再点击触发 LLM 段
 */

import { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { useUiStore } from '../stores/uiStore'
import { useI18n } from '../i18n'
import { lookupTerm } from './termDictionary'

// Short definitions + "ask LLM" prompts live in ./termDictionary (locale-keyed),
// so the full zh/en pair for a term is one editable block a sell-side reviewer
// can vet — rather than 4 scattered Lingui .po msgids. Only the tooltip chrome
// (aria label, "ask more" link) stays in the .po catalog.

interface Props {
  /** Term to look up (case-sensitive, must be an alias in termDictionary) */
  term: string
  /** Optional display text — defaults to `term`. Useful for `WACC %` etc. */
  children?: React.ReactNode
}

export function TermTip({ term, children }: Props): React.ReactElement {
  const { t, locale } = useI18n()
  const def = lookupTerm(term, locale)
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
  if (!def) {
    return <span>{children ?? term}</span>
  }

  const short = def.short
  const askPrompt = def.ask

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
              boxShadow: '0 6px 24px var(--shadow-drop-18)',
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
