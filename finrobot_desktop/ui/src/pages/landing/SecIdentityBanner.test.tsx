// Vitest for the SEC identity nudge banner on /stocks landing.
// Contract: the banner reflects the backend's own gate (sec_identity_active),
// NOT a client-side re-derivation. Covers: inactive → shows; active → hides;
// settings fetch failure (boot-race) → hides (never false-nag); localStorage
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

function setActive(active: boolean) {
  vi.mocked(api.GET).mockResolvedValue({
    data: { sec_identity_active: active } as never,
    error: undefined as never,
    response: new Response(),
  } as never)
}

/** Simulate the boot-race: /api/settings unreachable (sidecar not up yet). */
function setFetchError() {
  vi.mocked(api.GET).mockResolvedValue({
    data: undefined as never,
    error: { detail: 'ECONNREFUSED' } as never,
    response: new Response(null, { status: 502 }),
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
  it('shows the banner when SEC identity is not active', async () => {
    setActive(false)
    renderBanner()
    await waitFor(() => {
      expect(screen.getByTestId('sec-identity-banner')).toBeInTheDocument()
    })
    expect(screen.getByRole('link', { name: /Open Settings/i })).toHaveAttribute(
      'href',
      '/settings',
    )
  })

  it('hides the banner when SEC identity is active', async () => {
    setActive(true)
    renderBanner()
    // Wait for the query to settle (avoid false-positive hide-before-fetch).
    await waitFor(() => expect(api.GET).toHaveBeenCalled())
    expect(screen.queryByTestId('sec-identity-banner')).not.toBeInTheDocument()
  })

  it('hides the banner when the settings fetch fails — never false-nag on boot-race', async () => {
    // Regression: a failed /api/settings used to be swallowed into null and
    // cached as "unconfigured", so the banner stuck even with a valid identity.
    setFetchError()
    renderBanner()
    await waitFor(() => expect(api.GET).toHaveBeenCalled())
    expect(screen.queryByTestId('sec-identity-banner')).not.toBeInTheDocument()
  })

  it('hides the banner after dismiss + persists in localStorage', async () => {
    setActive(false)
    renderBanner()
    await waitFor(() => expect(screen.getByTestId('sec-identity-banner')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /Dismiss notification/i }))
    expect(screen.queryByTestId('sec-identity-banner')).not.toBeInTheDocument()
    expect(localStorage.getItem(DISMISS_KEY)).not.toBeNull()
  })

  it('honours recent dismiss across re-mounts (within 30-day window)', async () => {
    setActive(false)
    localStorage.setItem(DISMISS_KEY, String(Date.now() - 7 * 24 * 60 * 60 * 1000))
    renderBanner()
    await waitFor(() => expect(api.GET).toHaveBeenCalled())
    expect(screen.queryByTestId('sec-identity-banner')).not.toBeInTheDocument()
  })

  it('re-prompts when previous dismiss is older than 30 days', async () => {
    setActive(false)
    localStorage.setItem(DISMISS_KEY, String(Date.now() - 40 * 24 * 60 * 60 * 1000))
    renderBanner()
    await waitFor(() => expect(screen.getByTestId('sec-identity-banner')).toBeInTheDocument())
  })
})
