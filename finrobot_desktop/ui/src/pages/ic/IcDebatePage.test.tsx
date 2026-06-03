import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { vi } from 'vitest'

// BUG-20260602-015: an IC debate is ephemeral — never persisted as an artifact.
// The page must say so out loud so the analyst doesn't assume it survives a
// refresh. This locks the visible ephemeral notice into place.

const params = { ticker: 'aapl' }
const search = new URLSearchParams('artifact_id=art-1')

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    useParams: () => params,
    useSearchParams: () => [search, vi.fn()],
  }
})

vi.mock('../../i18n', () => ({ useI18n: () => ({ locale: 'en', t: (k: string) => k }) }))
vi.mock('../../stores/toastStore', () => ({
  useToastStore: (sel: (s: { addToast: () => void }) => unknown) => sel({ addToast: () => {} }),
}))

// Heavy debate children are irrelevant to the notice.
vi.mock('../../components/debate/VerdictCard', () => ({ VerdictCard: () => null }))
vi.mock('../../components/debate/DebateColumn', () => ({ DebateColumn: () => null }))
vi.mock('../../components/debate/MarketImpliedPanel', () => ({ MarketImpliedPanel: () => null }))

import { IcDebatePage } from './IcDebatePage'
import { useDebateStore, type DebateState } from '../../stores/debateStore'

function seedCompleted(): DebateState {
  return {
    runId: 'run_1',
    artifactId: 'art-1',
    evidence: {},
    current_price: null,
    reliable: true,
    bull: [],
    bear: [],
    verdict: { call: 'BUY', conviction: 7, swing_factor: 's', change_my_mind: 'c' },
    status: 'completed',
    error: null,
  }
}

describe('IcDebatePage ephemeral notice (BUG-20260602-015)', () => {
  beforeEach(() => {
    useDebateStore.setState({ debates: { 'AAPL::art-1': seedCompleted() } })
  })

  it('renders a notice telling the analyst the debate is not saved', () => {
    render(<IcDebatePage />)
    const notice = screen.getByTestId('ic-ephemeral-notice')
    expect(notice).toBeInTheDocument()
    expect(notice.textContent).toMatch(/not saved/i)
  })

  it('does not show the notice before a debate has started (idle state)', () => {
    useDebateStore.setState({ debates: {} })
    render(<IcDebatePage />)
    expect(screen.queryByTestId('ic-ephemeral-notice')).toBeNull()
  })
})
