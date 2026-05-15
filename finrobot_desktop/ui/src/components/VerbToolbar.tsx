/**
 * VerbToolbar — action buttons for the Stocks page.
 *
 * Primary row: Research, DCF, Comps, Earnings (4 buttons)
 * More dropdown: LBO, DDM, IC Memo
 * Ask AI button on the right side
 */

import { useCallback, useState, useRef, useEffect } from 'react'
import { useRunTool } from '../hooks/useRunTool'
import { useStocksStore, type ToolName } from '../stores/stocksStore'
import { useI18n } from '../i18n'

// ── Tool groups ──────────────────────────────────────────────────────────────

interface ToolConfig {
  name: ToolName
  labelKey: string
  tooltipKey: string
}

const PRIMARY_TOOLS: ToolConfig[] = [
  { name: 'dcf',       labelKey: 'verb.dcf',       tooltipKey: 'verb.dcf.tooltip' },
  { name: 'comps',     labelKey: 'verb.comps',     tooltipKey: 'verb.comps.tooltip' },
  { name: 'earnings',  labelKey: 'verb.earnings',  tooltipKey: 'verb.earnings.tooltip' },
]

const MORE_TOOLS: ToolConfig[] = [
  { name: 'lbo',       labelKey: 'verb.lbo',       tooltipKey: 'verb.lbo.tooltip' },
  { name: 'ddm',       labelKey: 'verb.ddm',       tooltipKey: 'verb.ddm.tooltip' },
  { name: 'ic-memo',   labelKey: 'verb.ic-memo',   tooltipKey: 'verb.ic-memo.tooltip' },
  { name: 'catalysts', labelKey: 'verb.catalysts', tooltipKey: 'verb.catalysts.tooltip' },
]

// ── Spinner ──────────────────────────────────────────────────────────────────

function Spinner() {
  return (
    <svg
      className="verb-btn-spinner"
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      aria-hidden="true"
      style={{ animation: 'spin 0.8s linear infinite' }}
    >
      <circle cx="6" cy="6" r="4" stroke="currentColor" strokeWidth="2" strokeDasharray="20 8" />
    </svg>
  )
}

// ── Props ────────────────────────────────────────────────────────────────────

interface VerbToolbarProps {
  ticker: string
  onAskAi?: () => void
  onToolComplete?: (tool: ToolName) => void
}

// ── Component ────────────────────────────────────────────────────────────────

export default function VerbToolbar({
  ticker,
  onAskAi,
  onToolComplete,
}: VerbToolbarProps) {
  const runningTools = useStocksStore((s) => s.runningTools)
  const { t } = useI18n()
  const [moreOpen, setMoreOpen] = useState(false)
  const moreRef = useRef<HTMLDivElement>(null)

  const { mutate, isPending } = useRunTool({
    ticker,
    onSuccess: onToolComplete,
  })

  // Close dropdown on outside click
  useEffect(() => {
    if (!moreOpen) return
    const handler = (e: MouseEvent) => {
      if (moreRef.current && !moreRef.current.contains(e.target as Node)) {
        setMoreOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [moreOpen])

  const handleClick = useCallback(
    (tool: ToolName) => {
      if (tool === 'ask-ai') {
        onAskAi?.()
        return
      }
      if (runningTools.has(tool)) return
      mutate(tool)
      setMoreOpen(false)
    },
    [runningTools, mutate, onAskAi],
  )

  function renderBtn(tool: ToolConfig, variant: 'primary' | 'dropdown' = 'primary') {
    const isRunning = runningTools.has(tool.name)
    const isDisabled = isRunning || !ticker
    const label = t(tool.labelKey)
    const tooltip = t(tool.tooltipKey)

    if (variant === 'dropdown') {
      return (
        <button
          key={tool.name}
          onClick={() => handleClick(tool.name)}
          disabled={isDisabled}
          title={tooltip}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            width: '100%',
            padding: '8px 14px',
            background: 'transparent',
            border: 'none',
            color: isRunning ? 'var(--gold)' : 'var(--text-primary)',
            cursor: isDisabled ? 'not-allowed' : 'pointer',
            opacity: isDisabled && !isRunning ? 0.45 : 1,
            fontSize: '0.87rem',
            textAlign: 'left',
            transition: 'background 0.1s',
          }}
          onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = 'var(--elevated)' }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = 'transparent' }}
        >
          {isRunning && <Spinner />}
          {label}
        </button>
      )
    }

    return (
      <button
        key={tool.name}
        className={`verb-btn${isRunning ? ' verb-btn--loading' : ''}`}
        aria-label={`${label}: ${tooltip}`}
        aria-busy={isRunning}
        disabled={isDisabled}
        onClick={() => handleClick(tool.name)}
        title={tooltip}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 5,
          padding: '6px 14px',
          fontSize: '0.87rem',
          fontWeight: 500,
          borderRadius: 'var(--r-sm)',
          border: '1px solid var(--border)',
          background: isRunning ? 'var(--gold-dim)' : 'var(--base)',
          color: isRunning ? 'var(--gold)' : 'var(--text-secondary)',
          cursor: isDisabled ? 'not-allowed' : 'pointer',
          opacity: isDisabled && !isRunning ? 0.45 : 1,
          transition: 'background 0.15s, color 0.15s, border-color 0.15s',
          whiteSpace: 'nowrap',
        }}
      >
        {isRunning && <Spinner />}
        {label}
      </button>
    )
  }

  return (
    <div
      className="verb-toolbar"
      role="toolbar"
      aria-label="Analysis tools"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        padding: '8px 0',
        flexWrap: 'wrap',
      }}
    >
      {/* Primary tools */}
      {PRIMARY_TOOLS.map((tool) => renderBtn(tool))}

      {/* More dropdown */}
      <div ref={moreRef} style={{ position: 'relative' }}>
        <button
          onClick={() => setMoreOpen((v) => !v)}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            padding: '6px 12px',
            fontSize: '0.87rem',
            fontWeight: 500,
            borderRadius: 'var(--r-sm)',
            border: '1px solid var(--border)',
            background: moreOpen ? 'var(--elevated)' : 'var(--base)',
            color: 'var(--text-muted)',
            cursor: 'pointer',
            transition: 'all 0.15s',
            whiteSpace: 'nowrap',
          }}
        >
          {t('verb.more') || 'More'}
          <span style={{ fontSize: '0.7rem' }}>{moreOpen ? '▲' : '▼'}</span>
        </button>

        {moreOpen && (
          <div
            style={{
              position: 'absolute',
              top: '100%',
              left: 0,
              marginTop: 4,
              background: 'var(--base)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--r-md)',
              boxShadow: 'var(--shadow-md)',
              minWidth: 160,
              overflow: 'hidden',
              zIndex: 100,
            }}
          >
            {MORE_TOOLS.map((tool) => renderBtn(tool, 'dropdown'))}
          </div>
        )}
      </div>

      {/* Spacer */}
      <div style={{ flex: 1 }} />

      {/* Ask AI — separated to the right */}
      <button
        onClick={() => onAskAi?.()}
        disabled={!ticker}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 5,
          padding: '6px 16px',
          fontSize: '0.87rem',
          fontWeight: 600,
          borderRadius: 'var(--r-sm)',
          border: 'none',
          background: 'var(--gold)',
          color: '#fff',
          cursor: !ticker ? 'not-allowed' : 'pointer',
          opacity: !ticker ? 0.45 : 1,
          transition: 'background 0.15s',
          whiteSpace: 'nowrap',
        }}
        title={t('verb.ask-ai.tooltip')}
      >
        {t('verb.ask-ai')}
      </button>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  )
}
