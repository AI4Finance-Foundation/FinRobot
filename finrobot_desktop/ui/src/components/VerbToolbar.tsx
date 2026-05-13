/**
 * VerbToolbar — 6 verb-action buttons for the Stocks page.
 *
 * Each button:
 *  - Shows a tooltip on hover describing what the tool does
 *  - Has independent loading state (disabled while running, spinner icon)
 *  - Calls useRunTool to dispatch to the right backend endpoint
 *  - ask-ai is a UI-only action that opens the right-chat panel
 */

import { useCallback } from 'react'
import { useRunTool } from '../hooks/useRunTool'
import { useStocksStore, type ToolName } from '../stores/stocksStore'

// ── Tool config ───────────────────────────────────────────────────────────────

interface ToolConfig {
  name: ToolName
  label: string
  tooltip: string
  shortcut?: string
}

const TOOLS: ToolConfig[] = [
  {
    name: 'dcf',
    label: '跑 DCF',
    tooltip: 'Run discounted cash flow valuation using default assumptions + live financial data',
    shortcut: 'D',
  },
  {
    name: 'lbo',
    label: '跑 LBO',
    tooltip: 'Run leveraged buyout model: IRR, MOIC, debt schedule, sensitivity grid',
    shortcut: 'L',
  },
  {
    name: 'comps',
    label: '对比同业',
    tooltip: 'Run comparable company analysis — fetch peer multiples via AI pipeline',
    shortcut: 'C',
  },
  {
    name: 'catalysts',
    label: '找催化剂',
    tooltip: 'Extract upcoming catalysts from recent news and filings',
    shortcut: 'T',
  },
  {
    name: 'ic-memo',
    label: '跑 IC Memo',
    tooltip: 'Generate an Investment Committee memo with situation overview, thesis, risks and recommendation',
    shortcut: 'I',
  },
  {
    name: 'ask-ai',
    label: '问 AI',
    tooltip: 'Open the chat panel and ask a question about this stock',
    shortcut: 'A',
  },
]

// ── Spinner ───────────────────────────────────────────────────────────────────

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

// ── Props ─────────────────────────────────────────────────────────────────────

interface VerbToolbarProps {
  ticker: string
  /** Called when ask-ai is clicked — lets parent open the chat panel */
  onAskAi?: () => void
  /** Called when a tool completes — lets parent respond (e.g. switch tab) */
  onToolComplete?: (tool: ToolName) => void
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function VerbToolbar({
  ticker,
  onAskAi,
  onToolComplete,
}: VerbToolbarProps) {
  const runningTools = useStocksStore((s) => s.runningTools)

  const { mutate, isPending } = useRunTool({
    ticker,
    onSuccess: onToolComplete,
  })

  const handleClick = useCallback(
    (tool: ToolName) => {
      if (tool === 'ask-ai') {
        onAskAi?.()
        return
      }
      if (runningTools.has(tool)) return
      mutate(tool)
    },
    [runningTools, mutate, onAskAi],
  )

  return (
    <div
      className="verb-toolbar"
      role="toolbar"
      aria-label="Analysis tools"
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 6,
        padding: '8px 0',
      }}
    >
      {TOOLS.map((tool) => {
        const isRunning = runningTools.has(tool.name) || (isPending && runningTools.has(tool.name))
        const isDisabled = isRunning || !ticker

        return (
          <div
            key={tool.name}
            className="verb-btn-wrapper"
            style={{ position: 'relative' }}
          >
            <button
              className={`verb-btn${isRunning ? ' verb-btn--loading' : ''}`}
              aria-label={`${tool.label}: ${tool.tooltip}`}
              aria-busy={isRunning}
              aria-disabled={isDisabled}
              disabled={isDisabled}
              onClick={() => handleClick(tool.name)}
              title={tool.tooltip}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 5,
                padding: '5px 12px',
                fontSize: '0.78rem',
                fontWeight: 500,
                borderRadius: 4,
                border: '1px solid var(--border)',
                background: isRunning ? 'var(--gold-dim)' : 'var(--surface)',
                color: isRunning ? 'var(--gold)' : 'var(--text-secondary)',
                cursor: isDisabled ? 'not-allowed' : 'pointer',
                opacity: isDisabled && !isRunning ? 0.45 : 1,
                transition: 'background 0.15s, color 0.15s, border-color 0.15s',
                whiteSpace: 'nowrap',
              }}
            >
              {isRunning && <Spinner />}
              {tool.label}
            </button>
          </div>
        )
      })}

      {/* Global spin animation */}
      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  )
}
