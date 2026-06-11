import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AppShell } from './AppShell'

// Stub Tauri modules so tests run in jsdom without Tauri APIs.
vi.mock('../lib/tauri', () => ({
  pickDirectory: vi.fn().mockResolvedValue(null),
  isTauri: vi.fn().mockReturnValue(false),
  openExternal: vi.fn().mockResolvedValue(undefined),
  DEFAULT_WORKSPACE_PATH: '~/finrobot',
}))

function renderWithProviders(initialPath = '/') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/*" element={<AppShell />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('AppShell — simplified shell structure', () => {
  it('renders core shell regions', () => {
    renderWithProviders()
    expect(screen.getByTestId('titlebar')).toBeInTheDocument()
  })

  it('renders the three product-door nav buttons in the titlebar', () => {
    renderWithProviders()
    // Nav moved from the retired left Sidebar into the TitleBar; the doors
    // expose their accessible name via button text (no aria-label needed).
    expect(screen.getByRole('button', { name: 'Research' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Coverage' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Settings' })).toBeInTheDocument()
  })

  it('keeps release-hidden AI chat out of the shell without affecting nav', () => {
    renderWithProviders()

    expect(screen.queryByRole('button', { name: /AI Assistant/i })).not.toBeInTheDocument()
    expect(screen.queryByTestId('right-chat-panel')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Research' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Coverage' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Settings' })).toBeInTheDocument()
  })
})

describe('AppShell — body.app-bg pause class for cosmic animations', () => {
  // jsdom's document.hasFocus() returns false by default, which would make
  // the "fresh render" case look identical to "blurred"; pin both signals
  // to "visible + focused" so we can prove the transitions instead.
  beforeEach(() => {
    document.body.classList.remove('app-bg')
    vi.spyOn(document, 'hasFocus').mockReturnValue(true)
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      get: () => false,
    })
  })
  afterEach(() => {
    vi.restoreAllMocks()
    document.body.classList.remove('app-bg')
  })

  it('adds app-bg when the window blurs and removes it on focus', () => {
    renderWithProviders()
    expect(document.body.classList.contains('app-bg')).toBe(false)

    // Simulate window blur → CSS animations should pause via the .app-bg gate
    vi.mocked(document.hasFocus).mockReturnValue(false)
    act(() => {
      window.dispatchEvent(new Event('blur'))
    })
    expect(document.body.classList.contains('app-bg')).toBe(true)

    // Refocus
    vi.mocked(document.hasFocus).mockReturnValue(true)
    act(() => {
      window.dispatchEvent(new Event('focus'))
    })
    expect(document.body.classList.contains('app-bg')).toBe(false)
  })

  it('adds app-bg when document.hidden flips true', () => {
    renderWithProviders()
    expect(document.body.classList.contains('app-bg')).toBe(false)

    Object.defineProperty(document, 'hidden', {
      configurable: true,
      get: () => true,
    })
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    expect(document.body.classList.contains('app-bg')).toBe(true)

    Object.defineProperty(document, 'hidden', {
      configurable: true,
      get: () => false,
    })
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    expect(document.body.classList.contains('app-bg')).toBe(false)
  })
})
