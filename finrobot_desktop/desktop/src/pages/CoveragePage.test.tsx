import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
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
    marketError: false,
    refetch: vi.fn(),
    refreshing: false,
    refreshNoop: false,
  },
}

vi.mock('../hooks/useCoverage', () => ({
  useCoverageGroups: () => hooks.groups,
  useCoverageOverview: () => hooks.overview,
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
      marketError: false,
      refetch: vi.fn(),
      refreshing: false,
      refreshNoop: false,
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
      marketError: false,
      refetch: vi.fn(),
      refreshing: false,
      refreshNoop: false,
    }
    renderPage()
    expect(screen.getByTestId('coverage-error')).toBeInTheDocument()
  })
})

describe('CoveragePage refresh control', () => {
  beforeEach(() => {
    hooks.groups = {
      data: [{ id: 'g1', name: 'Studied Tickers', member_count: 1, is_system: true }],
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    }
    hooks.overview = {
      data: {
        group_id: 'g1',
        group_name: 'Studied Tickers',
        rows: [],
        generated_at: '2026-06-08T09:00:00Z',
        partial: false,
        cache_only: false,
        refresh_noop: false,
      },
      isLoading: false,
      isError: false,
      marketPending: false,
      marketError: false,
      refetch: vi.fn(),
      refreshing: false,
      refreshNoop: false,
    }
  })

  it('renders the refresh button and re-runs the revalidate on click', () => {
    renderPage()
    const btn = screen.getByTestId('coverage-refresh-btn')
    expect(btn).toHaveTextContent('Refresh')
    fireEvent.click(btn)
    expect(hooks.overview.refetch).toHaveBeenCalledTimes(1)
  })
})
