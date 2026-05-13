import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClientProvider, QueryClient } from '@tanstack/react-query'
import SettingsView from '../views/SettingsView'

// Mock the API client module
vi.mock('../api/client', () => ({
  api: {
    GET: vi.fn().mockResolvedValue({
      data: {
        model_name: 'deepseek:deepseek-chat',
        anthropic_api_key_set: false,
        deepseek_api_key_set: false,
        openai_api_key_set: false,
        fmp_api_key_set: false,
        finnhub_api_key_set: false,
        sec_user_agent: '',
        log_level: 'INFO',
        available_providers: ['yfinance'],
        valid_model_providers: ['deepseek', 'anthropic', 'openai'],
      },
      error: undefined,
    }),
    PUT: vi.fn().mockResolvedValue({ data: {}, error: undefined }),
  },
  BASE_URL: 'http://127.0.0.1:8321',
}))

function renderWithQuery(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
  )
}

describe('SettingsView', () => {
  it('renders settings title', async () => {
    renderWithQuery(<SettingsView onComplete={() => {}} />)
    expect(await screen.findByText('Settings')).toBeInTheDocument()
  })

  it('renders model selector', async () => {
    renderWithQuery(<SettingsView onComplete={() => {}} />)
    expect(await screen.findByText('LLM Provider')).toBeInTheDocument()
  })

  it('renders save button', async () => {
    renderWithQuery(<SettingsView onComplete={() => {}} />)
    expect(await screen.findByText('Save Settings')).toBeInTheDocument()
  })
})
