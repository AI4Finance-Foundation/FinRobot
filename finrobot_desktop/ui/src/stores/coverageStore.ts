// coverageStore — UI-only state for the Coverage Desk: which group is open and
// which rows are selected for a batch action. The authoritative coverage data
// (groups, members, overview) lives in the backend SQLite store and is fetched
// via TanStack Query (useCoverage); localStorage here holds ONLY the last-open
// group id — the research universe never lives in localStorage (CoverageDesk
// plan M5). Selection is ephemeral (not persisted) — it resets on group switch.

import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

interface CoverageUiState {
  selectedGroupId: string | null
  selectedTickers: string[]
  setSelectedGroup: (id: string | null) => void
  toggleTicker: (ticker: string) => void
  setSelected: (tickers: string[]) => void
  clearSelection: () => void
}

export const useCoverageStore = create<CoverageUiState>()(
  persist(
    (set) => ({
      selectedGroupId: null,
      selectedTickers: [],
      setSelectedGroup: (id) => set({ selectedGroupId: id, selectedTickers: [] }),
      toggleTicker: (ticker) =>
        set((s) => ({
          selectedTickers: s.selectedTickers.includes(ticker)
            ? s.selectedTickers.filter((t) => t !== ticker)
            : [...s.selectedTickers, ticker],
        })),
      setSelected: (tickers) => set({ selectedTickers: [...new Set(tickers)] }),
      clearSelection: () => set({ selectedTickers: [] }),
    }),
    {
      name: 'finrobot-coverage-ui',
      storage: createJSONStorage(() => localStorage),
      // Persist only the last-open group — selection is per-session.
      partialize: (s) => ({ selectedGroupId: s.selectedGroupId }),
    },
  ),
)
