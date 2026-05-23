/**
 * stocksStore — per-ticker UI state for the Stocks page.
 *
 * Manages active tab + the set of tools currently running (prevents
 * double-submit). The "recent tickers" list is no longer stored here —
 * /api/artifacts/studied-tickers is the authoritative source.
 */

import { create } from 'zustand'

export type StocksTab =
  | 'overview'
  | 'financials'
  | 'performance'
  | 'news'
  | 'valuation'
  | 'comps'
  | 'history'
  | 'research'

export type ToolName =
  | 'research'
  | 'dcf'
  | 'lbo'
  | 'comps'
  | 'catalysts'
  | 'ic-memo'
  | 'ddm'
  | 'earnings'
  | 'ask-ai'

const TICKER_RE = /^[A-Z0-9.\-]{1,12}$/

export function isValidTicker(ticker: string): boolean {
  return TICKER_RE.test(ticker.toUpperCase())
}

interface StocksState {
  activeTab: StocksTab
  runningTools: Set<ToolName>

  setActiveTab: (tab: StocksTab) => void
  startTool: (tool: ToolName) => void
  finishTool: (tool: ToolName) => void
}

export const useStocksStore = create<StocksState>((set) => ({
  // Default to overview — it has live data the moment a ticker is picked,
  // so the user always lands on something useful instead of an empty
  // "Run DCF first" placeholder. Tools (DCF/Comps) still switch the tab on
  // completion.
  activeTab: 'overview',
  runningTools: new Set(),

  setActiveTab: (tab) => set({ activeTab: tab }),

  startTool: (tool) =>
    set((s) => ({ runningTools: new Set([...s.runningTools, tool]) })),

  finishTool: (tool) =>
    set((s) => {
      const next = new Set(s.runningTools)
      next.delete(tool)
      return { runningTools: next }
    }),
}))
