import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { useAppStore } from '../stores/appStore'
import SettingsView from './SettingsView'

describe('SettingsView', () => {
  beforeEach(() => {
    useAppStore.setState({
      settings: {
        fmpApiKey: '', finnhubApiKey: '', anthropicApiKey: '',
        deepseekApiKey: '', openaiApiKey: '',
        modelName: 'claude-sonnet-4-20250514', secUserAgent: '',
        dataSourcePriority: ['fmp', 'finnhub', 'yfinance'],
      },
    })
  })

  it('renders settings title', () => {
    render(<SettingsView />)
    expect(screen.getByText('Settings')).toBeInTheDocument()
  })

  it('renders API key inputs', () => {
    render(<SettingsView />)
    expect(screen.getByPlaceholderText(/FMP/)).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/Finnhub/)).toBeInTheDocument()
  })

  it('renders model selector', () => {
    render(<SettingsView />)
    expect(screen.getByText('Model')).toBeInTheDocument()
  })
})
