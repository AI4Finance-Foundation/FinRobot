// coverageStore — UI-only state for the Coverage archive: which group is open
// and card density. The authoritative coverage data (groups, members, overview)
// lives in the backend SQLite store and is fetched via TanStack Query
// (useCoverage); localStorage here holds ONLY view-state. (The research-library
// wall has no sort UI — it renders one fixed order — so no per-group sort is
// persisted.)

import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

export type CoverageDensity = 'comfort' | 'compact'

interface CoverageUiState {
  selectedGroupId: string | null
  // Card density — a global view preference (not per-group), persisted.
  density: CoverageDensity
  setSelectedGroup: (id: string | null) => void
  setDensity: (density: CoverageDensity) => void
}

export const useCoverageStore = create<CoverageUiState>()(
  persist(
    (set) => ({
      selectedGroupId: null,
      density: 'comfort',
      setSelectedGroup: (id) => set({ selectedGroupId: id }),
      setDensity: (density) => set({ density }),
    }),
    {
      name: 'finrobot-coverage-ui',
      storage: createJSONStorage(() => localStorage),
      // Persist only durable view preferences.
      partialize: (s) => ({
        selectedGroupId: s.selectedGroupId,
        density: s.density,
      }),
    },
  ),
)
