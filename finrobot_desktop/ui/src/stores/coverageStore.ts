// coverageStore — UI-only state for the Coverage Desk: which group is open,
// which rows are selected for a batch action, which one ticker is focused in
// the inspector, and the card density. The authoritative coverage data
// (groups, members, overview) lives in the backend SQLite store and is fetched
// via TanStack Query (useCoverage); localStorage here holds ONLY view-state —
// the research universe never lives in localStorage (CoverageDesk plan M5).
//
// Two SEPARATE selections, never conflated (Coverage redesign §4):
//   • selectedTickers — the multi-select set for batch actions (Run / Compare).
//     Ephemeral; resets on group switch.
//   • focusedTicker   — the single ticker open in the right Inspector.
//     Ephemeral; resets to the first card on group switch (page resolves the
//     "first card" — the store only nulls it so a stale id can't leak across).

import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import type { CoverageSort } from '../components/coverage/coverageSort'

export type CoverageDensity = 'comfort' | 'compact'

interface CoverageUiState {
  selectedGroupId: string | null
  // Multi-select for batch actions (Run Selected / Compare). Distinct from
  // focusedTicker — selecting rows must never move the inspector, and focusing
  // a card must never tick a batch checkbox.
  selectedTickers: string[]
  // The single ticker shown in the right Inspector. Null = inspector empty.
  focusedTicker: string | null
  // Per-group card sort, persisted: each universe remembers its last sort.
  sortByGroup: Record<string, CoverageSort>
  // Card density — a global view preference (not per-group), persisted.
  density: CoverageDensity
  setSelectedGroup: (id: string | null) => void
  toggleTicker: (ticker: string) => void
  setSelected: (tickers: string[]) => void
  clearSelection: () => void
  setFocusedTicker: (ticker: string | null) => void
  setSort: (groupId: string, sort: CoverageSort | null) => void
  setDensity: (density: CoverageDensity) => void
}

export const useCoverageStore = create<CoverageUiState>()(
  persist(
    (set) => ({
      selectedGroupId: null,
      selectedTickers: [],
      focusedTicker: null,
      sortByGroup: {},
      density: 'comfort',
      // Switching group resets BOTH ephemeral selections: a batch set / inspector
      // focus from the previous universe must not bleed into the next.
      setSelectedGroup: (id) =>
        set({ selectedGroupId: id, selectedTickers: [], focusedTicker: null }),
      toggleTicker: (ticker) =>
        set((s) => ({
          selectedTickers: s.selectedTickers.includes(ticker)
            ? s.selectedTickers.filter((t) => t !== ticker)
            : [...s.selectedTickers, ticker],
        })),
      setSelected: (tickers) => set({ selectedTickers: [...new Set(tickers)] }),
      clearSelection: () => set({ selectedTickers: [] }),
      setFocusedTicker: (ticker) => set({ focusedTicker: ticker }),
      setSort: (groupId, sort) =>
        set((s) => {
          const next = { ...s.sortByGroup }
          if (sort === null) delete next[groupId]
          else next[groupId] = sort
          return { sortByGroup: next }
        }),
      setDensity: (density) => set({ density }),
    }),
    {
      name: 'finrobot-coverage-ui',
      storage: createJSONStorage(() => localStorage),
      // Persist last-open group + per-group sort + density; the two selections
      // (selectedTickers / focusedTicker) stay per-session.
      partialize: (s) => ({
        selectedGroupId: s.selectedGroupId,
        sortByGroup: s.sortByGroup,
        density: s.density,
      }),
    },
  ),
)
