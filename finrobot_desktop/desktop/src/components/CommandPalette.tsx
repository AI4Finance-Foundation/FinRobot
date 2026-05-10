import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useAppStore } from '../stores/appStore'
import type { PipelineType } from '../stores/appStore'

interface CommandItem {
  id: string
  label: string
  description?: string
  section: 'ticker' | 'pipeline' | 'navigate'
  icon: 'search' | 'chart' | 'nav' | 'settings'
  action: () => void
  shortcut?: string
}

interface Props {
  open: boolean
  onClose: () => void
  onOpenSettings: () => void
}

const SECTION_LABELS: Record<string, string> = {
  ticker: 'Ticker',
  pipeline: 'Pipelines',
  navigate: 'Navigation',
}

export default function CommandPalette({ open, onClose, onOpenSettings }: Props) {
  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const {
    ticker,
    phase,
    setTicker,
    setPhase,
    setPipelineType,
    setView,
  } = useAppStore()

  // Build command list
  const commands = useMemo<CommandItem[]>(() => {
    const items: CommandItem[] = []

    // If query looks like a ticker (uppercase alpha, 1-5 chars), show "Load ticker" action
    const trimmed = query.trim().toUpperCase()
    if (trimmed && /^[A-Z]{1,5}$/.test(trimmed) && trimmed !== ticker) {
      items.push({
        id: `load-${trimmed}`,
        label: `Load ${trimmed}`,
        description: 'Fetch financials and start analysis',
        section: 'ticker',
        icon: 'search',
        action: () => {
          setTicker(trimmed)
          setPhase('loading_data')
          onClose()
        },
      })
    }

    // Pipeline commands (only when data is loaded)
    const canSwitchPipeline = phase === 'data_ready' || phase === 'pipeline_done' || phase === 'interactive'
    if (canSwitchPipeline) {
      const pipelines: { type: PipelineType; label: string; desc: string }[] = [
        { type: 'equity_research', label: 'Run Equity Research', desc: 'Full investment thesis + price target' },
        { type: 'dcf', label: 'Run DCF Analysis', desc: 'Discounted cash flow valuation' },
        { type: 'comps', label: 'Run Comps Analysis', desc: 'Peer comparison multiples' },
        { type: 'earnings', label: 'Run Earnings Analysis', desc: 'Beat/miss history + surprise metrics' },
      ]
      for (const p of pipelines) {
        items.push({
          id: `pipeline-${p.type}`,
          label: p.label,
          description: p.desc,
          section: 'pipeline',
          icon: 'chart',
          action: () => {
            setPipelineType(p.type)
            onClose()
          },
        })
      }
    }

    // Navigation
    items.push({
      id: 'nav-history',
      label: 'View Run History',
      description: 'See previous analysis runs',
      section: 'navigate',
      icon: 'nav',
      action: () => {
        setView('history')
        onClose()
      },
      shortcut: 'H',
    })
    items.push({
      id: 'nav-settings',
      label: 'Open Settings',
      description: 'Configure API keys and model',
      section: 'navigate',
      icon: 'settings',
      action: () => {
        onOpenSettings()
        onClose()
      },
      shortcut: ',',
    })
    items.push({
      id: 'nav-workspace',
      label: 'Go to Workspace',
      description: 'Return to main analysis view',
      section: 'navigate',
      icon: 'nav',
      action: () => {
        setView('workspace')
        onClose()
      },
    })

    return items
  }, [query, ticker, phase, setTicker, setPhase, setPipelineType, setView, onClose, onOpenSettings])

  // Filter by query
  const filtered = useMemo(() => {
    if (!query.trim()) return commands
    const q = query.toLowerCase()
    return commands.filter(
      (c) =>
        c.label.toLowerCase().includes(q) ||
        c.description?.toLowerCase().includes(q) ||
        c.section.includes(q)
    )
  }, [commands, query])

  // Group by section
  const grouped = useMemo(() => {
    const sections: { key: string; label: string; items: CommandItem[] }[] = []
    const seen = new Set<string>()
    for (const item of filtered) {
      if (!seen.has(item.section)) {
        seen.add(item.section)
        sections.push({
          key: item.section,
          label: SECTION_LABELS[item.section] || item.section,
          items: filtered.filter((i) => i.section === item.section),
        })
      }
    }
    return sections
  }, [filtered])

  // Reset on open/close
  useEffect(() => {
    if (open) {
      setQuery('')
      setSelectedIndex(0)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [open])

  // Clamp selected index
  useEffect(() => {
    if (selectedIndex >= filtered.length) {
      setSelectedIndex(Math.max(0, filtered.length - 1))
    }
  }, [filtered.length, selectedIndex])

  // Scroll active item into view
  useEffect(() => {
    if (!listRef.current) return
    const active = listRef.current.querySelector('[data-active="true"]')
    if (active) {
      active.scrollIntoView({ block: 'nearest' })
    }
  }, [selectedIndex])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault()
          setSelectedIndex((i) => Math.min(i + 1, filtered.length - 1))
          break
        case 'ArrowUp':
          e.preventDefault()
          setSelectedIndex((i) => Math.max(i - 1, 0))
          break
        case 'Enter':
          e.preventDefault()
          if (filtered[selectedIndex]) {
            filtered[selectedIndex].action()
          }
          break
        case 'Escape':
          e.preventDefault()
          onClose()
          break
      }
    },
    [filtered, selectedIndex, onClose]
  )

  if (!open) return null

  let flatIndex = -1

  return (
    <div className="cmd-overlay" onClick={onClose}>
      <div className="cmd-palette" onClick={(e) => e.stopPropagation()}>
        {/* Search input */}
        <div className="cmd-input-wrap">
          <svg className="cmd-input-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="7" cy="7" r="4.5" />
            <path d="M10.5 10.5L14 14" />
          </svg>
          <input
            ref={inputRef}
            className="cmd-input"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setSelectedIndex(0)
            }}
            onKeyDown={handleKeyDown}
            placeholder="Type a command or ticker..."
            spellCheck={false}
            autoComplete="off"
          />
          <kbd className="cmd-kbd">ESC</kbd>
        </div>

        {/* Results */}
        <div className="cmd-list" ref={listRef}>
          {filtered.length === 0 && (
            <div className="cmd-empty">No results found</div>
          )}
          {grouped.map((section) => (
            <div key={section.key} className="cmd-section">
              <div className="cmd-section-label">{section.label}</div>
              {section.items.map((item) => {
                flatIndex++
                const isActive = flatIndex === selectedIndex
                const currentFlatIndex = flatIndex
                return (
                  <div
                    key={item.id}
                    className={`cmd-item${isActive ? ' active' : ''}`}
                    data-active={isActive}
                    onClick={() => item.action()}
                    onMouseEnter={() => setSelectedIndex(currentFlatIndex)}
                  >
                    <CommandIcon type={item.icon} />
                    <div className="cmd-item-text">
                      <span className="cmd-item-label">{item.label}</span>
                      {item.description && (
                        <span className="cmd-item-desc">{item.description}</span>
                      )}
                    </div>
                    {item.shortcut && (
                      <kbd className="cmd-shortcut">{item.shortcut}</kbd>
                    )}
                  </div>
                )
              })}
            </div>
          ))}
        </div>

        {/* Footer hint */}
        <div className="cmd-footer">
          <span><kbd className="cmd-kbd-sm">&uarr;</kbd><kbd className="cmd-kbd-sm">&darr;</kbd> navigate</span>
          <span><kbd className="cmd-kbd-sm">&crarr;</kbd> select</span>
          <span><kbd className="cmd-kbd-sm">esc</kbd> close</span>
        </div>
      </div>
    </div>
  )
}

function CommandIcon({ type }: { type: string }) {
  switch (type) {
    case 'search':
      return (
        <svg className="cmd-item-icon" width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3">
          <circle cx="6" cy="6" r="4" />
          <path d="M9.5 9.5L12.5 12.5" />
        </svg>
      )
    case 'chart':
      return (
        <svg className="cmd-item-icon" width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3">
          <rect x="1" y="5" width="3" height="8" rx="0.5" />
          <rect x="5.5" y="2" width="3" height="11" rx="0.5" />
          <rect x="10" y="7" width="3" height="6" rx="0.5" />
        </svg>
      )
    case 'nav':
      return (
        <svg className="cmd-item-icon" width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3">
          <path d="M5 3l4 4-4 4" />
        </svg>
      )
    case 'settings':
      return (
        <svg className="cmd-item-icon" width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3">
          <circle cx="7" cy="7" r="2" />
          <path d="M7 1v2m0 8v2M1 7h2m8 0h2" />
        </svg>
      )
    default:
      return null
  }
}
