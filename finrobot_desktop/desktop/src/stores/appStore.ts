import { create } from 'zustand'

interface Settings {
  fmpApiKey: string
  finnhubApiKey: string
  anthropicApiKey: string
  deepseekApiKey: string
  openaiApiKey: string
  modelName: string
  secUserAgent: string
  dataSourcePriority: string[]
}

interface AppState {
  // Current analysis
  ticker: string
  setTicker: (ticker: string) => void

  // Settings
  settings: Settings
  updateSettings: (partial: Partial<Settings>) => void

  // Analysis history
  analysisHistory: Array<{ ticker: string; timestamp: number; type: string }>
  addToHistory: (entry: { ticker: string; type: string }) => void

  // Theme
  theme: 'dark' | 'light'
  toggleTheme: () => void
}

const defaultSettings: Settings = {
  fmpApiKey: '',
  finnhubApiKey: '',
  anthropicApiKey: '',
  deepseekApiKey: '',
  openaiApiKey: '',
  modelName: 'claude-sonnet-4-20250514',
  secUserAgent: '',
  dataSourcePriority: ['fmp', 'finnhub', 'yfinance'],
}

export const useAppStore = create<AppState>((set) => ({
  ticker: '',
  setTicker: (ticker) => set({ ticker }),

  settings: { ...defaultSettings },
  updateSettings: (partial) =>
    set((state) => ({ settings: { ...state.settings, ...partial } })),

  analysisHistory: [],
  addToHistory: (entry) =>
    set((state) => ({
      analysisHistory: [
        { ...entry, timestamp: Date.now() },
        ...state.analysisHistory.slice(0, 49), // Keep last 50
      ],
    })),

  theme: 'dark',
  toggleTheme: () =>
    set((state) => ({ theme: state.theme === 'dark' ? 'light' : 'dark' })),
}))
