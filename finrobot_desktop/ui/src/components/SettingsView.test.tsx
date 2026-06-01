import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClientProvider, QueryClient } from '@tanstack/react-query'
import SettingsView, { isValidSecIdentity, secHeaderIdentityPreview } from '../views/SettingsView'

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
        sec_identity_active: false,
        sec_holdings_auto_refresh: true,
        log_level: 'INFO',
        log_to_file: false,
        log_retention_days: 7,
        available_providers: ['yfinance'],
        valid_model_providers: ['deepseek', 'anthropic', 'openai'],
        field_sources: {},
      },
      error: undefined,
    }),
    PUT: vi.fn().mockResolvedValue({ data: {}, error: undefined }),
  },
  BASE_URL: 'http://127.0.0.1:8321',
  exportDiagnosticsLogs: vi.fn().mockResolvedValue(new Blob(['test'], { type: 'application/zip' })),
}))

function renderWithQuery(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

describe('SettingsView', () => {
  it('renders AI 模型 section', async () => {
    renderWithQuery(<SettingsView onComplete={() => {}} />)
    expect(await screen.findByText('AI Model')).toBeInTheDocument()
  })

  it('renders 数据源 section', async () => {
    renderWithQuery(<SettingsView onComplete={() => {}} />)
    expect(await screen.findByText('Data Sources')).toBeInTheDocument()
  })

  it('renders 通知通道 section', async () => {
    renderWithQuery(<SettingsView onComplete={() => {}} />)
    expect(await screen.findByText('Notification Channels')).toBeInTheDocument()
  })

  // 外观 section removed in v5; theme controls are outside this settings surface.

  it('renders logging controls and export button', async () => {
    renderWithQuery(<SettingsView onComplete={() => {}} />)
    expect(await screen.findByText('Logging / Diagnostics')).toBeInTheDocument()
    expect(
      await screen.findByRole('button', { name: /导出诊断日志|export.*log/i }),
    ).toBeInTheDocument()
  })
})

describe('isValidSecIdentity', () => {
  it('rejects empty / nullish input', () => {
    expect(isValidSecIdentity('')).toBe(false)
    expect(isValidSecIdentity(null)).toBe(false)
    expect(isValidSecIdentity(undefined)).toBe(false)
  })

  it('rejects strings missing space or @', () => {
    expect(isValidSecIdentity('just-a-string')).toBe(false)
    expect(isValidSecIdentity('no@spacehere')).toBe(false)
    expect(isValidSecIdentity('two words but no at sign')).toBe(false)
  })

  it('rejects the backend placeholder default', () => {
    expect(isValidSecIdentity('FinRobot admin@example.com')).toBe(false)
  })

  it('accepts the SEC-canonical Name email format', () => {
    expect(isValidSecIdentity('Jane Doe jane@example.com')).toBe(true)
    expect(isValidSecIdentity('Acme Capital alpha@acme.com')).toBe(true)
  })

  it('accepts Chinese display names because the backend preserves the contact email', () => {
    expect(isValidSecIdentity('郭嘉祺 17696026747@163.com')).toBe(true)
  })

  it('rejects a name with a malformed email', () => {
    expect(isValidSecIdentity('Jane Doe jane@example')).toBe(false)
  })

  it('trims whitespace before checking', () => {
    expect(isValidSecIdentity('  Jane Doe jane@example.com  ')).toBe(true)
  })

  it('previews the ASCII SEC header sent for Chinese display names', () => {
    expect(secHeaderIdentityPreview('郭嘉祺 17696026747@163.com')).toBe(
      'FinRobot 17696026747@163.com',
    )
  })
})
