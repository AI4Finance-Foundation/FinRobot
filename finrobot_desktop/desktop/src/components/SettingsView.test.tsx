import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClientProvider, QueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import SettingsView, { isValidSecIdentity, secHeaderIdentityPreview } from '../views/SettingsView'

const OK_SETTINGS = {
  model_name: 'deepseek:deepseek-chat',
  anthropic_api_key_set: false,
  deepseek_api_key_set: false,
  openai_api_key_set: false,
  fmp_api_key_set: false,
  finnhub_api_key_set: false,
  sec_user_agent: 'Acme Capital alpha@acme.com',
  sec_identity_active: true,
  sec_holdings_auto_refresh: true,
  log_level: 'INFO',
  log_to_file: false,
  log_retention_days: 7,
  available_providers: ['yfinance'],
  valid_model_providers: ['deepseek', 'anthropic', 'openai'],
}

// Mock the API client module. Default GET succeeds; individual tests override
// `api.GET` to simulate a load failure (BUG-026).
vi.mock('../api/client', () => ({
  api: {
    GET: vi.fn(),
    PUT: vi.fn().mockResolvedValue({ data: {}, error: undefined }),
  },
  BASE_URL: 'http://127.0.0.1:8321',
}))

const SEC_HOLDINGS_STATUS = {
  populated: false,
  row_count: 0,
  latest_period_end: null,
  distinct_tickers: 0,
  identity_configured: true,
  auto_refresh: true,
  refresh: {
    status: 'idle',
    period_end: null,
    started_at: null,
    finished_at: null,
    error: null,
  },
}

const PROVIDER_HEALTH = {
  providers: [
    {
      name: 'fmp',
      key_required: true,
      key_configured: true,
      available: true,
      circuit_state: 'closed',
      cooldown_until: null,
      consecutive_failures: 0,
      last_success: '2026-06-10T12:00:00Z',
      last_failure: null,
      last_rate_limited: false,
    },
    {
      name: 'yfinance',
      key_required: false,
      key_configured: null,
      available: false,
      circuit_state: 'open',
      cooldown_until: '2026-06-10T12:10:00Z',
      consecutive_failures: 1,
      last_success: null,
      last_failure: '2026-06-10T12:01:00Z',
      last_rate_limited: true,
    },
  ],
}

beforeEach(() => {
  vi.mocked(api.GET).mockResolvedValue({ data: OK_SETTINGS, error: undefined } as never)
  // SecHoldingsSection / provider-health rows / reset mutation use raw fetch;
  // dispatch on URL so each consumer gets its own payload shape.
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: RequestInfo | URL) => ({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () =>
        String(url).includes('/api/settings/provider-health')
          ? PROVIDER_HEALTH
          : SEC_HOLDINGS_STATUS,
    })) as unknown as typeof fetch,
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

function renderWithQuery(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

describe('SettingsView', () => {
  // The section title and the left-nav item share the same label, so target
  // the section heading (h2) specifically rather than the ambiguous text.
  it('renders AI 模型 section', async () => {
    renderWithQuery(<SettingsView onComplete={() => {}} />)
    expect(await screen.findByRole('heading', { name: 'AI Model' })).toBeInTheDocument()
  })

  it('renders unified data-source rows: live circuit state + inline key config', async () => {
    renderWithQuery(<SettingsView onComplete={() => {}} />)
    // fmp row: name + inline key input + test button on the same row.
    expect(await screen.findByText('FMP')).toBeInTheDocument()
    expect(screen.getByLabelText('FMP API Key')).toBeInTheDocument()
    // yfinance row: tripped breaker surfaces a cooldown badge, never a green
    // dot — and the always-on baseline badge lives on the same row now.
    expect(screen.getByText('Cooldown')).toBeInTheDocument()
    expect(screen.getByText('Always on')).toBeInTheDocument()
  })

  it('renders 数据源 section', async () => {
    renderWithQuery(<SettingsView onComplete={() => {}} />)
    expect(await screen.findByRole('heading', { name: 'Data Sources' })).toBeInTheDocument()
  })

  // 外观 section removed in v5; theme controls are outside this settings surface.
  // 通知通道 section removed 2026-06; multi-channel push had no trigger wired.
  // 日志/诊断 section removed 2026-06; log config is .env-only, not user-facing.

  // BUG-026: a failed settings load must NOT show the editable key form (which
  // would silently never save) — it must show an error + retry state instead.
  it('shows an error/retry state and hides the key form when settings fail to load', async () => {
    vi.mocked(api.GET).mockResolvedValue({
      data: undefined,
      error: { detail: 'backend down' },
    } as never)

    renderWithQuery(<SettingsView onComplete={() => {}} />)

    // Error state visible…
    expect(await screen.findByText("Can't load settings")).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    // …and the editable form is NOT rendered.
    expect(screen.queryByText('Data Sources')).not.toBeInTheDocument()
    expect(screen.queryByText('AI Model')).not.toBeInTheDocument()
  })

  // BUG-009: clicking the 13F sync button must surface a confirmation BEFORE
  // firing the heavy multi-hour refresh request.
  it('requires confirmation before calling the 13F refresh endpoint', async () => {
    renderWithQuery(<SettingsView onComplete={() => {}} />)

    const syncBtn = await screen.findByRole('button', { name: /Sync now/i })

    const fetchMock = vi.mocked(fetch)
    const refreshCalls = () =>
      fetchMock.mock.calls.filter(
        (c) => typeof c[0] === 'string' && (c[0] as string).includes('/api/sec-holdings/refresh'),
      )

    // Click the button → a confirm dialog appears, but no refresh POST yet.
    fireEvent.click(syncBtn)
    expect(await screen.findByText('Start 13F sync?')).toBeInTheDocument()
    expect(refreshCalls()).toHaveLength(0)

    // Confirm → the refresh endpoint is finally called.
    fireEvent.click(screen.getByRole('button', { name: 'Start sync' }))
    await waitFor(() => expect(refreshCalls()).toHaveLength(1))
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
