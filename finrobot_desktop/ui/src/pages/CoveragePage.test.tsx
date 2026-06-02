import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

// CoverageHero pulls in SplineHero (remote <script>) — stub it.
vi.mock('../components/coverage/CoverageHero', () => ({ CoverageHero: () => null }))

const hooks = {
  groups: { data: undefined as unknown, isLoading: false, isError: false, refetch: vi.fn() },
  overview: {
    data: undefined as unknown,
    isLoading: false,
    isError: false,
    marketPending: false,
    refetch: vi.fn(),
  },
}

vi.mock('../hooks/useCoverage', () => ({
  useCoverageGroups: () => hooks.groups,
  useCoverageOverview: () => hooks.overview,
  useCreateGroup: () => ({ mutate: vi.fn(), isPending: false }),
  useAddMembers: () => ({ mutate: vi.fn() }),
  useBatchRun: () => ({ mutate: vi.fn(), isPending: false }),
}))

import { CoveragePage } from './CoveragePage'

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CoveragePage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('CoveragePage error states (BUG-051)', () => {
  beforeEach(() => {
    hooks.groups = { data: undefined, isLoading: false, isError: false, refetch: vi.fn() }
    hooks.overview = {
      data: undefined,
      isLoading: false,
      isError: false,
      marketPending: false,
      refetch: vi.fn(),
    }
  })

  it('shows an error (not the starter) when the groups request fails', () => {
    hooks.groups = { data: undefined, isLoading: false, isError: true, refetch: vi.fn() }
    renderPage()
    expect(screen.getByTestId('coverage-error')).toBeInTheDocument()
    // The empty-state starter must NOT appear on a failure.
    expect(screen.queryByTestId('coverage-empty')).not.toBeInTheDocument()
  })

  it('shows an error (not "empty group") when the overview request fails', () => {
    hooks.groups = {
      data: [{ id: 'g1', name: 'AI', member_count: 1 }],
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    }
    hooks.overview = {
      data: undefined,
      isLoading: false,
      isError: true,
      marketPending: false,
      refetch: vi.fn(),
    }
    renderPage()
    expect(screen.getByTestId('coverage-error')).toBeInTheDocument()
  })
})
