import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

// First-run onboarding overlay: shows ONCE when a fresh install has no LLM model
// configured, and never again once a model is set or the user dismisses it. These
// lock the several AND-ed trigger conditions so a future refactor can't silently
// start nagging configured users (or hiding the gate from fresh ones).

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
  localStorage.clear()
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

  it('stays hidden after a previous dismissal this install', () => {
    localStorage.setItem('finrobot-ai-onboarding-dismissed', 'true')
    render(<AiOnboardingGate />)
    expect(shown()).toBe(false)
  })

  it('"Pick an AI model" navigates to Settings and remembers the dismissal', () => {
    render(<AiOnboardingGate />)
    fireEvent.click(screen.getByText('Pick an AI model'))
    expect(navigate).toHaveBeenCalledWith('/settings')
    expect(localStorage.getItem('finrobot-ai-onboarding-dismissed')).toBe('true')
  })

  it('"Explore data first" dismisses without navigating', () => {
    render(<AiOnboardingGate />)
    fireEvent.click(screen.getByText('Explore data first'))
    expect(navigate).not.toHaveBeenCalled()
    expect(shown()).toBe(false)
  })
})
