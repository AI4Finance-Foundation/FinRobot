// Vitest for the SEC identity nudge banner on /stocks landing.
// Covers: invalid identity → shows; valid identity → hides; localStorage
// dismiss persists; dismissed > 30 days ago re-prompts.

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

import { SecIdentityBanner } from './SecIdentityBanner'

vi.mock('../../api/client', () => ({
  api: { GET: vi.fn() },
  BASE_URL: '',
}))

import { api } from '../../api/client'

const DISMISS_KEY = 'finrobot-sec-banner-dismissed-at'

function setIdentity(value: string | null) {
  vi.mocked(api.GET).mockResolvedValue({
    data: { sec_user_agent: value } as never,
    error: undefined as never,
    response: new Response(),
  } as never)
}

function renderBanner() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <SecIdentityBanner />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.removeItem(DISMISS_KEY)
  vi.clearAllMocks()
})

describe('SecIdentityBanner', () => {
  it('shows the banner when sec_user_agent is empty', async () => {
    setIdentity('')
    renderBanner()
    await waitFor(() => {
      expect(screen.getByTestId('sec-identity-banner')).toBeInTheDocument()
    })
    expect(screen.getByRole('link', { name: /Open Settings/i })).toHaveAttribute(
      'href',
      '/settings',
    )
  })

  it('shows the banner when sec_user_agent is the placeholder default', async () => {
    setIdentity('FinRobot admin@example.com')
    renderBanner()
    await waitFor(() => {
      expect(screen.getByTestId('sec-identity-banner')).toBeInTheDocument()
    })
  })

  it('hides the banner when sec_user_agent is configured properly', async () => {
    setIdentity('Jane Doe jane@example.com')
    renderBanner()
    // Wait for the query to settle (avoid false-positive hide-before-fetch).
    await waitFor(() => expect(api.GET).toHaveBeenCalled())
    expect(screen.queryByTestId('sec-identity-banner')).not.toBeInTheDocument()
  })

  it('hides the banner after dismiss + persists in localStorage', async () => {
    setIdentity('')
    renderBanner()
    await waitFor(() => expect(screen.getByTestId('sec-identity-banner')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /Dismiss notification/i }))
    expect(screen.queryByTestId('sec-identity-banner')).not.toBeInTheDocument()
    expect(localStorage.getItem(DISMISS_KEY)).not.toBeNull()
  })

  it('honours recent dismiss across re-mounts (within 30-day window)', async () => {
    setIdentity('')
    localStorage.setItem(DISMISS_KEY, String(Date.now() - 7 * 24 * 60 * 60 * 1000))
    renderBanner()
    await waitFor(() => expect(api.GET).toHaveBeenCalled())
    expect(screen.queryByTestId('sec-identity-banner')).not.toBeInTheDocument()
  })

  it('re-prompts when previous dismiss is older than 30 days', async () => {
    setIdentity('')
    localStorage.setItem(DISMISS_KEY, String(Date.now() - 40 * 24 * 60 * 60 * 1000))
    renderBanner()
    await waitFor(() => expect(screen.getByTestId('sec-identity-banner')).toBeInTheDocument())
  })
})
