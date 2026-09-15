// The hosted case, in its own file because SETTINGS_ALLOWED is read once at
// module load — a vi.mock of the deployment config applies to a whole file, so
// it cannot share one with the desktop-mode tests next door.
//
// What this locks: a viewer served by a host that reserves Settings for
// administrators is never shown the "pick an AI model" overlay. They cannot act
// on it (there is no Settings route for them), so it would open over the data
// they came for with a button that navigates nowhere.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('../config/deployment', () => ({ SETTINGS_ALLOWED: false }))

const navigate = vi.fn()
vi.mock('react-router-dom', () => ({
  useNavigate: () => navigate,
  useLocation: () => ({ pathname: '/research' }),
}))

let health: Record<string, unknown>
vi.mock('../hooks/useHealth', () => ({
  useHealth: () => ({ data: health, isPlaceholderData: false }),
}))

vi.mock('../i18n', () => ({
  useI18n: () => ({ locale: 'en', t: (k: string) => k }),
}))

import { AiOnboardingGate } from './AiOnboardingGate'

beforeEach(() => {
  navigate.mockClear()
  // The exact state that opens the overlay on a desktop install.
  health = {
    backendReachable: true,
    modelConfigured: false,
    startupError: null,
    availableProviders: ['fmp'],
  }
})

describe('AiOnboardingGate — hosted (Settings reserved for admins)', () => {
  it('stays closed even with no model configured', () => {
    render(<AiOnboardingGate />)
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})
