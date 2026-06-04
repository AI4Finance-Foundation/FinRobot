// coverageStore — UI-only state for the Coverage archive: which group is open,
// per-group sort, and card density. The authoritative coverage data (groups,
// members, overview) lives in the backend SQLite store and is fetched via
// TanStack Query (useCoverage); localStorage here holds ONLY view-state.

import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import type { CoverageSort } from '../components/coverage/coverageSort'

export type CoverageDensity = 'comfort' | 'compact'

interface CoverageUiState {
  selectedGroupId: string | null
  // Per-group card sort, persisted: each universe remembers its last sort.
  sortByGroup: Record<string, CoverageSort>
  // Card density — a global view preference (not per-group), persisted.
  density: CoverageDensity
  setSelectedGroup: (id: string | null) => void
  setSort: (groupId: string, sort: CoverageSort | null) => void
  setDensity: (density: CoverageDensity) => void
}

export const useCoverageStore = create<CoverageUiState>()(
  persist(
    (set) => ({
      selectedGroupId: null,
      sortByGroup: {},
      density: 'comfort',
      setSelectedGroup: (id) => set({ selectedGroupId: id }),
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
      // Persist only durable view preferences.
      partialize: (s) => ({
        selectedGroupId: s.selectedGroupId,
        sortByGroup: s.sortByGroup,
        density: s.density,
      }),
    },
  ),
)
