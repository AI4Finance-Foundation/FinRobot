import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

// First-run onboarding overlay: shows when a launch has no LLM model configured,
// stays closed for the rest of THAT session once dismissed, and never shows once
// a model is set. Dismissal is session-only (in-memory) on purpose — a relaunch
// with still no model re-prompts. These lock the AND-ed trigger conditions so a
// future refactor can't silently nag configured users or hide it from fresh ones.

const navigate = vi.fn()
let pathname = '/research'
vi.mock('react-router-dom', () => ({
  useNavigate: () => navigate,
  useLocation: () => ({ pathname }),
}))

let health: Record<string, unknown>
let isPlaceholderData = false
vi.mock('../hooks/useHealth', () => ({
  useHealth: () => ({ data: health, isPlaceholderData }),
}))

vi.mock('../i18n', () => ({
  useI18n: () => ({ locale: 'en', t: (k: string) => k }),
}))

import { AiOnboardingGate } from './AiOnboardingGate'

const NO_MODEL = {
  backendReachable: true,
  modelConfigured: false,
  startupError: null,
  availableProviders: ['fmp'],
}

beforeEach(() => {
  navigate.mockClear()
  pathname = '/research'
  isPlaceholderData = false
  health = { ...NO_MODEL }
})
afterEach(() => localStorage.clear())

function shown(): boolean {
  return screen.queryByRole('dialog') != null
}

describe('AiOnboardingGate', () => {
  it('shows on a fresh install with no model configured', () => {
    render(<AiOnboardingGate />)
    expect(shown()).toBe(true)
  })

  it('hides once a model is configured', () => {
    health = { ...NO_MODEL, modelConfigured: true }
    render(<AiOnboardingGate />)
    expect(shown()).toBe(false)
  })

  it('hides while the health probe is still the seeded placeholder', () => {
    isPlaceholderData = true
    render(<AiOnboardingGate />)
    expect(shown()).toBe(false)
  })

  it('hides while the backend is unreachable (no nag over offline)', () => {
    health = { ...NO_MODEL, backendReachable: false }
    render(<AiOnboardingGate />)
    expect(shown()).toBe(false)
  })

  it('hides on the Settings page (it has its own notice there)', () => {
    pathname = '/settings'
    render(<AiOnboardingGate />)
    expect(shown()).toBe(false)
  })

  it('re-prompts on a fresh mount (relaunch) while still no model — no persistence', () => {
    // A prior session's dismissal must NOT leak across launches: dismissal is
    // in-memory only, so a stale persisted flag can never suppress a fresh mount.
    localStorage.setItem('finrobot-ai-onboarding-dismissed', 'true')
    render(<AiOnboardingGate />)
    expect(shown()).toBe(true)
  })

  it('"Pick an AI model" navigates to Settings and dismisses for the session', () => {
    render(<AiOnboardingGate />)
    fireEvent.click(screen.getByText('Pick an AI model'))
    expect(navigate).toHaveBeenCalledWith('/settings')
    expect(shown()).toBe(false)
  })

  it('"Explore data first" dismisses for the session without navigating', () => {
    render(<AiOnboardingGate />)
    fireEvent.click(screen.getByText('Explore data first'))
    expect(navigate).not.toHaveBeenCalled()
    expect(shown()).toBe(false)
  })

  it('stays dismissed across re-renders within the same session (route changes)', () => {
    const { rerender } = render(<AiOnboardingGate />)
    fireEvent.click(screen.getByText('Explore data first'))
    expect(shown()).toBe(false)
    // Simulate a route change re-render of the still-mounted component.
    pathname = '/coverage'
    rerender(<AiOnboardingGate />)
    expect(shown()).toBe(false)
  })
})
