import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useAppStore } from '../stores/appStore'
import type { PipelineType } from '../stores/appStore'

interface CommandItem {
  id: string
  label: string
  description?: string
  section: 'recent' | 'ticker' | 'pipeline' | 'navigate'
  icon: 'search' | 'chart' | 'nav' | 'settings' | 'clock'
  action: () => void
  shortcut?: string
}

interface FuzzyMatch {
  item: CommandItem
  score: number
  indices: number[] // matched char positions in label
  descIndices: number[] // matched char positions in description
}

interface Props {
  open: boolean
  onClose: () => void
  onOpenSettings: () => void
}

const SECTION_LABELS: Record<string, string> = {
  recent: 'Recent',
  ticker: 'Ticker',
  pipeline: 'Pipelines',
  navigate: 'Navigation',
}

const SECTION_ORDER: Record<string, number> = {
  recent: 0,
  ticker: 1,
  pipeline: 2,
  navigate: 3,
}

const RECENT_KEY = 'finrobot:cmd-recent'
const MAX_RECENT = 5

/* ── Fuzzy scoring ──────────────────────────────── */

function fuzzyScore(query: string, target: string): { score: number; indices: number[] } | null {
  const q = query.toLowerCase()
  const t = target.toLowerCase()
  const indices: number[] = []
  let qi = 0
  let score = 0
  let prevMatchIdx = -2

  for (let ti = 0; ti < t.length && qi < q.length; ti++) {
    if (t[ti] === q[qi]) {
      indices.push(ti)

      // Consecutive match bonus
      if (ti === prevMatchIdx + 1) {
        score += 8
      }

      // Word boundary bonus (start of word)
      if (ti === 0 || t[ti - 1] === ' ' || t[ti - 1] === '-' || t[ti - 1] === '_') {
        score += 10
      }

      // Exact case match bonus
      if (target[ti] === query[qi]) {
        score += 1
      }

      score += 3 // base match score
      prevMatchIdx = ti
      qi++
    }
  }

  // All query chars must be matched
  if (qi < q.length) return null

  // Penalty for longer targets (prefer shorter, more precise matches)
  score -= Math.floor(t.length / 8)

  return { score, indices }
}

/* ── Recent commands ───────────────────────────── */

function getRecent(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.slice(0, MAX_RECENT) : []
  } catch {
    return []
  }
}

function pushRecent(id: string): void {
  const list = getRecent().filter((x) => x !== id)
  list.unshift(id)
  localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, MAX_RECENT)))
}

/* ── Highlighted label ─────────────────────────── */

function HighlightedText({ text, indices }: { text: string; indices: number[] }) {
  if (indices.length === 0) return <>{text}</>

  const set = new Set(indices)
  const parts: React.ReactElement[] = []
  let run = ''
  let inMatch = false

  for (let i = 0; i < text.length; i++) {
    const isMatch = set.has(i)
    if (isMatch !== inMatch) {
      if (run) {
        parts.push(
          inMatch ? (
            <mark key={i} className="cmd-match">
              {run}
            </mark>
          ) : (
            <span key={i}>{run}</span>
          ),
        )
      }
      run = ''
      inMatch = isMatch
    }
    run += text[i]
  }
  if (run) {
    parts.push(
      inMatch ? (
        <mark key={text.length} className="cmd-match">
          {run}
        </mark>
      ) : (
        <span key={text.length}>{run}</span>
      ),
    )
  }

  return <>{parts}</>
}

/* ── Component ─────────────────────────────────── */

export default function CommandPalette({ open, onClose, onOpenSettings }: Props) {
  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [recentIds, setRecentIds] = useState<string[]>([])
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const { ticker, phase, setTicker, setPhase, setPipelineType, setView } = useAppStore()

  // Load recent on open
  useEffect(() => {
    if (open) {
      setRecentIds(getRecent())
    }
  }, [open])

  // Execute command and record to recent
  const execCommand = useCallback((item: CommandItem) => {
    // Don't record ticker-specific dynamic commands
    if (!item.id.startsWith('load-')) {
      pushRecent(item.id)
    }
    item.action()
  }, [])

  // Build base command list (excluding recent section)
  const commands = useMemo<CommandItem[]>(() => {
    const items: CommandItem[] = []

    // If query looks like a ticker, show "Load ticker" action
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
    const canSwitchPipeline =
      phase === 'data_ready' || phase === 'pipeline_done' || phase === 'interactive'
    if (canSwitchPipeline) {
      const pipelines: { type: PipelineType; label: string; desc: string }[] = [
        {
          type: 'research',
          label: 'Run Equity Research',
          desc: 'Full investment thesis + price target',
        },
        { type: 'dcf', label: 'Run DCF Analysis', desc: 'Discounted cash flow valuation' },
        { type: 'comps', label: 'Run Comps Analysis', desc: 'Peer comparison multiples' },
        {
          type: 'earnings',
          label: 'Run Earnings Analysis',
          desc: 'Beat/miss history + surprise metrics',
        },
        { type: 'lbo', label: 'Run LBO Analysis', desc: 'Leveraged buyout returns (IRR/MOIC)' },
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

  // Fuzzy filter + score + sort
  const matches = useMemo<FuzzyMatch[]>(() => {
    const q = query.trim()

    if (!q) {
      // No query — show recent section (if any) + all commands
      const recentItems: FuzzyMatch[] = []
      if (recentIds.length > 0) {
        for (const rid of recentIds) {
          const cmd = commands.find((c) => c.id === rid)
          if (cmd) {
            recentItems.push({
              item: { ...cmd, section: 'recent', icon: 'clock' },
              score: 100,
              indices: [],
              descIndices: [],
            })
          }
        }
      }

      const regular = commands.map((c) => ({
        item: c,
        score: 0,
        indices: [],
        descIndices: [],
      }))

      return [...recentItems, ...regular]
    }

    // Fuzzy match against label and description
    const results: FuzzyMatch[] = []
    for (const cmd of commands) {
      const labelMatch = fuzzyScore(q, cmd.label)
      const descMatch = cmd.description ? fuzzyScore(q, cmd.description) : null

      if (labelMatch || descMatch) {
        const labelScore = labelMatch?.score ?? -100
        const descScore = descMatch ? descMatch.score - 5 : -100 // prefer label matches
        results.push({
          item: cmd,
          score: Math.max(labelScore, descScore),
          indices: labelMatch?.indices ?? [],
          descIndices: descMatch?.indices ?? [],
        })
      }
    }

    // Sort by score descending
    results.sort((a, b) => b.score - a.score)
    return results
  }, [commands, query, recentIds])

  // Group by section (preserving order)
  const grouped = useMemo(() => {
    const sectionMap = new Map<string, { key: string; label: string; items: FuzzyMatch[] }>()

    for (const match of matches) {
      const sec = match.item.section
      if (!sectionMap.has(sec)) {
        sectionMap.set(sec, {
          key: sec,
          label: SECTION_LABELS[sec] || sec,
          items: [],
        })
      }
      const section = sectionMap.get(sec)
      if (section) section.items.push(match)
    }

    return Array.from(sectionMap.values()).sort(
      (a, b) => (SECTION_ORDER[a.key] ?? 99) - (SECTION_ORDER[b.key] ?? 99),
    )
  }, [matches])

  const flatItems = useMemo(() => matches, [matches])

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
    if (selectedIndex >= flatItems.length) {
      setSelectedIndex(Math.max(0, flatItems.length - 1))
    }
  }, [flatItems.length, selectedIndex])

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
          setSelectedIndex((i) => Math.min(i + 1, flatItems.length - 1))
          break
        case 'ArrowUp':
          e.preventDefault()
          setSelectedIndex((i) => Math.max(i - 1, 0))
          break
        case 'Enter':
          e.preventDefault()
          if (flatItems[selectedIndex]) {
            execCommand(flatItems[selectedIndex].item)
          }
          break
        case 'Escape':
          e.preventDefault()
          onClose()
          break
      }
    },
    [flatItems, selectedIndex, onClose, execCommand],
  )

  if (!open) return null

  let flatIndex = -1

  return (
    <div className="cmd-overlay" onClick={onClose}>
      <div className="cmd-palette" onClick={(e) => e.stopPropagation()}>
        {/* Search input */}
        <div className="cmd-input-wrap">
          <svg
            className="cmd-input-icon"
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          >
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
          {query && (
            <span className="cmd-result-count">
              {flatItems.length} result{flatItems.length !== 1 ? 's' : ''}
            </span>
          )}
          <kbd className="cmd-kbd">ESC</kbd>
        </div>

        {/* Results */}
        <div className="cmd-list" ref={listRef}>
          {flatItems.length === 0 && (
            <div className="cmd-empty">
              <span className="cmd-empty-icon">?</span>
              No matching commands
            </div>
          )}
          {grouped.map((section) => (
            <div key={section.key} className="cmd-section">
              <div className="cmd-section-label">{section.label}</div>
              {section.items.map((match) => {
                flatIndex++
                const isActive = flatIndex === selectedIndex
                const currentFlatIndex = flatIndex
                const item = match.item
                return (
                  <div
                    key={`${section.key}-${item.id}`}
                    className={`cmd-item${isActive ? ' active' : ''}`}
                    data-active={isActive}
                    onClick={() => execCommand(item)}
                    onMouseEnter={() => setSelectedIndex(currentFlatIndex)}
                  >
                    <CommandIcon type={item.icon} />
                    <div className="cmd-item-text">
                      <span className="cmd-item-label">
                        <HighlightedText text={item.label} indices={match.indices} />
                      </span>
                      {item.description && (
                        <span className="cmd-item-desc">
                          <HighlightedText text={item.description} indices={match.descIndices} />
                        </span>
                      )}
                    </div>
                    {item.shortcut && <kbd className="cmd-shortcut">{item.shortcut}</kbd>}
                  </div>
                )
              })}
            </div>
          ))}
        </div>

        {/* Footer hint */}
        <div className="cmd-footer">
          <span>
            <kbd className="cmd-kbd-sm">&uarr;</kbd>
            <kbd className="cmd-kbd-sm">&darr;</kbd> navigate
          </span>
          <span>
            <kbd className="cmd-kbd-sm">&crarr;</kbd> select
          </span>
          <span>
            <kbd className="cmd-kbd-sm">esc</kbd> close
          </span>
        </div>
      </div>
    </div>
  )
}

function CommandIcon({ type }: { type: string }) {
  switch (type) {
    case 'search':
      return (
        <svg
          className="cmd-item-icon"
          width="14"
          height="14"
          viewBox="0 0 14 14"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.3"
        >
          <circle cx="6" cy="6" r="4" />
          <path d="M9.5 9.5L12.5 12.5" />
        </svg>
      )
    case 'chart':
      return (
        <svg
          className="cmd-item-icon"
          width="14"
          height="14"
          viewBox="0 0 14 14"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.3"
        >
          <rect x="1" y="5" width="3" height="8" rx="0.5" />
          <rect x="5.5" y="2" width="3" height="11" rx="0.5" />
          <rect x="10" y="7" width="3" height="6" rx="0.5" />
        </svg>
      )
    case 'nav':
      return (
        <svg
          className="cmd-item-icon"
          width="14"
          height="14"
          viewBox="0 0 14 14"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.3"
        >
          <path d="M5 3l4 4-4 4" />
        </svg>
      )
    case 'settings':
      return (
        <svg
          className="cmd-item-icon"
          width="14"
          height="14"
          viewBox="0 0 14 14"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.3"
        >
          <circle cx="7" cy="7" r="2" />
          <path d="M7 1v2m0 8v2M1 7h2m8 0h2" />
        </svg>
      )
    case 'clock':
      return (
        <svg
          className="cmd-item-icon"
          width="14"
          height="14"
          viewBox="0 0 14 14"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.3"
        >
          <circle cx="7" cy="7" r="5.5" />
          <path d="M7 4v3.5l2.5 1.5" />
        </svg>
      )
    default:
      return null
  }
}
