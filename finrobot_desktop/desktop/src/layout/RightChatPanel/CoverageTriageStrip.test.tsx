import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

// Mock the coverage data hooks so the strip renders deterministic triage rows
// without a backend (same pattern as CoveragePage.test.tsx).
const hooks = {
  groups: { data: [{ id: 'g1', is_system: true }] as unknown },
  overview: { data: undefined as unknown },
}
vi.mock('../../hooks/useCoverage', () => ({
  useCoverageGroups: () => hooks.groups,
  useCoverageOverview: () => hooks.overview,
}))

import { CoverageTriageStrip } from './CoverageTriageStrip'

// One mover (|1d| ≥ 3.0) → exactly one triage card.
const OVERVIEW = {
  data: {
    generated_at: '2026-06-08T14:00:00Z',
    rows: [
      {
        ticker: 'NVDA',
        company: 'NVIDIA',
        price: 1024.5,
        change_pct_1d: 5.2,
        currency: 'USD',
        latest_verdict: 'BUY',
        target_price: 1200,
        upside_to_target_live: 0.17,
      },
    ],
  },
}

function strip(collapsed: boolean): React.ReactElement {
  return (
    <MemoryRouter>
      <CoverageTriageStrip defaultCollapsed={collapsed} />
    </MemoryRouter>
  )
}

describe('CoverageTriageStrip — auto-collapse when a conversation starts', () => {
  beforeEach(() => {
    hooks.groups = { data: [{ id: 'g1', is_system: true }] }
    hooks.overview = OVERVIEW
  })

  it('renders expanded (full cards) when there is no conversation yet', () => {
    render(strip(false))
    expect(screen.getByText('Needs your eyes')).toBeInTheDocument()
    expect(screen.getByText('1d anomaly')).toBeInTheDocument()
  })

  it('collapses to the one-line summary when defaultCollapsed flips false→true', () => {
    // The bug: useState read the prop only at mount, so the strip stayed
    // expanded through the whole chat and kept shoving the thread down.
    const { rerender } = render(strip(false))
    expect(screen.getByText('Needs your eyes')).toBeInTheDocument()

    // A conversation begins — AiChatTab flips defaultCollapsed to true.
    rerender(strip(true))

    expect(screen.queryByText('Needs your eyes')).not.toBeInTheDocument()
    expect(screen.queryByText('1d anomaly')).not.toBeInTheDocument()
    expect(screen.getByText(/needs? a look/i)).toBeInTheDocument()
  })
})
