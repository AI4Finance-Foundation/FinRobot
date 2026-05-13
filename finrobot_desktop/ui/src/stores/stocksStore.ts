/**
 * stocksStore — per-ticker UI state for the new Stocks page.
 *
 * Manages:
 *  - Current ticker (URL-driven, synced via useParams)
 *  - Per-tool loading flags (prevents double-submit)
 *  - Recently-visited ticker list (persisted to localStorage)
 *  - Active stocks tab
 */

import { create } from 'zustand'

// ── Types ─────────────────────────────────────────────────────────────────────

export type StocksTab =
  | 'valuation'
  | 'financials'
  | 'peers'
  | 'performance'
  | 'news'
  | 'history'

export type ToolName = 'dcf' | 'lbo' | 'comps' | 'catalysts' | 'ic-memo' | 'ask-ai'

// ── Constants ─────────────────────────────────────────────────────────────────

const RECENT_KEY = 'finagent:recentTickers'
const MAX_RECENT = 10

const TICKER_RE = /^[A-Z0-9.\-]{1,12}$/

// ── Persistence helpers ───────────────────────────────────────────────────────

function loadRecent(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return (parsed as unknown[]).filter((x): x is string => typeof x === 'string')
  } catch {
    return []
  }
}

function saveRecent(tickers: string[]): void {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(tickers))
  } catch {
    // ignore write errors (private browsing, quota)
  }
}

function addToRecent(ticker: string, current: string[]): string[] {
  const upper = ticker.toUpperCase()
  const next = [upper, ...current.filter((t) => t !== upper)].slice(0, MAX_RECENT)
  saveRecent(next)
  return next
}

// ── Validation ────────────────────────────────────────────────────────────────

export function isValidTicker(ticker: string): boolean {
  return TICKER_RE.test(ticker.toUpperCase())
}

// ── Store ─────────────────────────────────────────────────────────────────────

interface StocksState {
  /** Current ticker being viewed. Empty string = no ticker selected. */
  currentTicker: string

  /** Active tab */
  activeTab: StocksTab

  /** Set of tool names currently running — prevents double-submit */
  runningTools: Set<ToolName>

  /** Watchlist tickers (in-memory; full persistence is a future concern) */
  watchlist: Set<string>

  /** Recent tickers, newest first, persisted to localStorage */
  recentTickers: string[]

  // ── Actions ──

  setCurrentTicker: (ticker: string) => void
  setActiveTab: (tab: StocksTab) => void
  startTool: (tool: ToolName) => void
  finishTool: (tool: ToolName) => void
  toggleWatchlist: (ticker: string) => void
  clearRecent: () => void
}

export const useStocksStore = create<StocksState>((set, get) => ({
  currentTicker: '',
  activeTab: 'valuation',
  runningTools: new Set(),
  watchlist: new Set(),
  recentTickers: loadRecent(),

  setCurrentTicker: (ticker) => {
    const upper = ticker.toUpperCase()
    const prev = get().currentTicker
    if (upper === prev) return
    const recentTickers = upper ? addToRecent(upper, get().recentTickers) : get().recentTickers
    set({ currentTicker: upper, recentTickers })
  },

  setActiveTab: (tab) => set({ activeTab: tab }),

  startTool: (tool) =>
    set((s) => ({ runningTools: new Set([...s.runningTools, tool]) })),

  finishTool: (tool) =>
    set((s) => {
      const next = new Set(s.runningTools)
      next.delete(tool)
      return { runningTools: next }
    }),

  toggleWatchlist: (ticker) =>
    set((s) => {
      const next = new Set(s.watchlist)
      if (next.has(ticker)) {
        next.delete(ticker)
      } else {
        next.add(ticker)
      }
      return { watchlist: next }
    }),

  clearRecent: () => {
    saveRecent([])
    set({ recentTickers: [] })
  },
}))
