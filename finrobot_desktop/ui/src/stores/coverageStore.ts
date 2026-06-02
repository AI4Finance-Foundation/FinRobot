// coverageStore — UI-only state for the Coverage Desk: which group is open and
// which rows are selected for a batch action. The authoritative coverage data
// (groups, members, overview) lives in the backend SQLite store and is fetched
// via TanStack Query (useCoverage); localStorage here holds ONLY the last-open
// group id — the research universe never lives in localStorage (CoverageDesk
// plan M5). Selection is ephemeral (not persisted) — it resets on group switch.

import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import type { CoverageSort } from '../components/coverage/coverageSort'

interface CoverageUiState {
  selectedGroupId: string | null
  selectedTickers: string[]
  // Per-group column sort, persisted: each universe remembers how the analyst
  // last sorted it (view-state — belongs client-side, not a backend table).
  sortByGroup: Record<string, CoverageSort>
  // Hidden data columns — a global view preference (not per-group), persisted.
  hiddenColumns: string[]
  setSelectedGroup: (id: string | null) => void
  toggleTicker: (ticker: string) => void
  setSelected: (tickers: string[]) => void
  clearSelection: () => void
  setSort: (groupId: string, sort: CoverageSort | null) => void
  toggleColumn: (key: string) => void
}

export const useCoverageStore = create<CoverageUiState>()(
  persist(
    (set) => ({
      selectedGroupId: null,
      selectedTickers: [],
      sortByGroup: {},
      hiddenColumns: [],
      setSelectedGroup: (id) => set({ selectedGroupId: id, selectedTickers: [] }),
      toggleTicker: (ticker) =>
        set((s) => ({
          selectedTickers: s.selectedTickers.includes(ticker)
            ? s.selectedTickers.filter((t) => t !== ticker)
            : [...s.selectedTickers, ticker],
        })),
      setSelected: (tickers) => set({ selectedTickers: [...new Set(tickers)] }),
      clearSelection: () => set({ selectedTickers: [] }),
      setSort: (groupId, sort) =>
        set((s) => {
          const next = { ...s.sortByGroup }
          if (sort === null) delete next[groupId]
          else next[groupId] = sort
          return { sortByGroup: next }
        }),
      toggleColumn: (key) =>
        set((s) => ({
          hiddenColumns: s.hiddenColumns.includes(key)
            ? s.hiddenColumns.filter((k) => k !== key)
            : [...s.hiddenColumns, key],
        })),
    }),
    {
      name: 'finrobot-coverage-ui',
      storage: createJSONStorage(() => localStorage),
      // Persist last-open group + per-group sort + hidden columns; selection
      // stays per-session.
      partialize: (s) => ({
        selectedGroupId: s.selectedGroupId,
        sortByGroup: s.sortByGroup,
        hiddenColumns: s.hiddenColumns,
      }),
    },
  ),
)
