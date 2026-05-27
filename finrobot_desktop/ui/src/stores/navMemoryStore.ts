// navMemoryStore — remembers the last deep path the user visited inside
// each top-level section so the sidebar can restore context after the
// user detours through /settings. Mirrors the pattern Plane / Linear /
// VS Code use: per-section "where I was" stored in localStorage so it
// also survives app restart.
//
// Currently only tracks /stocks. /settings is contextless. Future sections
// (e.g. /screener, /portfolio) plug in the same way.

import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

interface NavMemoryState {
  /** Last deep path under /stocks, e.g. "/stocks/TSLA/runs/abc123". */
  lastStocksPath: string | null
  setLastStocksPath: (path: string) => void
  clearLastStocksPath: () => void
}

export const useNavMemoryStore = create<NavMemoryState>()(
  persist(
    (set) => ({
      lastStocksPath: null,
      setLastStocksPath: (lastStocksPath) => set({ lastStocksPath }),
      clearLastStocksPath: () => set({ lastStocksPath: null }),
    }),
    {
      name: 'finrobot-nav-memory',
      storage: createJSONStorage(() => localStorage),
    },
  ),
)
