import { describe, it, expect, beforeEach } from 'vitest'
import { useAppStore } from './appStore'

describe('appStore', () => {
  beforeEach(() => {
    useAppStore.setState({
      ticker: '',
      settings: {
        fmpApiKey: '',
        finnhubApiKey: '',
        anthropicApiKey: '',
        deepseekApiKey: '',
        openaiApiKey: '',
        modelName: 'claude-sonnet-4-20250514',
        secUserAgent: '',
        dataSourcePriority: ['fmp', 'finnhub', 'yfinance'],
      },
      analysisHistory: [],
      theme: 'dark',
    })
  })

  it('sets ticker', () => {
    useAppStore.getState().setTicker('AAPL')
    expect(useAppStore.getState().ticker).toBe('AAPL')
  })

  it('updates settings partially', () => {
    useAppStore.getState().updateSettings({ fmpApiKey: 'test-key' })
    expect(useAppStore.getState().settings.fmpApiKey).toBe('test-key')
    expect(useAppStore.getState().settings.modelName).toBe('claude-sonnet-4-20250514')
  })

  it('adds to history', () => {
    useAppStore.getState().addToHistory({ ticker: 'AAPL', type: 'research' })
    const history = useAppStore.getState().analysisHistory
    expect(history).toHaveLength(1)
    expect(history[0].ticker).toBe('AAPL')
  })

  it('toggles theme', () => {
    useAppStore.getState().toggleTheme()
    expect(useAppStore.getState().theme).toBe('light')
  })
})
