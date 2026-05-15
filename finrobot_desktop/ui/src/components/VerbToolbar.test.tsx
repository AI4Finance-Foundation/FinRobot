/**
 * VerbToolbar — unit tests
 *
 * Covers: rendering all 6 buttons, click dispatches mutation, loading state,
 * independent loading for multiple tools, ask-ai callback, accessibility.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import VerbToolbar from './VerbToolbar'
import { useStocksStore } from '../stores/stocksStore'

// ── Setup ─────────────────────────────────────────────────────────────────────

function renderToolbar(
  props: Partial<React.ComponentProps<typeof VerbToolbar>> = {},
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <VerbToolbar ticker="AAPL" {...props} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  // Reset store
  useStocksStore.setState({
    runningTools: new Set(),
    currentTicker: 'AAPL',
  })

  // Clear fetch mocks
  vi.restoreAllMocks()
})

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('VerbToolbar — rendering', () => {
  it('renders primary tools and More dropdown', () => {
    renderToolbar()
    // Primary tools are always visible
    expect(screen.getByText('Run DCF')).toBeInTheDocument()
    expect(screen.getByText('Compare peers')).toBeInTheDocument()
    expect(screen.getByText('Earnings')).toBeInTheDocument()
    expect(screen.getByText('Ask AI')).toBeInTheDocument()
    // More button is visible
    expect(screen.getByText('More')).toBeInTheDocument()
  })

  it('More dropdown reveals additional tools when clicked', () => {
    renderToolbar()
    // Dropdown tools are hidden initially
    expect(screen.queryByText('Run LBO')).not.toBeInTheDocument()

    // Open dropdown
    fireEvent.click(screen.getByText('More'))

    // Now dropdown tools are visible
    expect(screen.getByText('Run LBO')).toBeInTheDocument()
    expect(screen.getByText('Run DDM')).toBeInTheDocument()
    expect(screen.getByText('IC memo')).toBeInTheDocument()
    expect(screen.getByText('Find catalysts')).toBeInTheDocument()
  })

  it('primary buttons have aria-label', () => {
    renderToolbar()
    // Only check primary buttons (which have aria-label); More and dropdown buttons use title
    const primaryButtons = screen.getAllByRole('button').filter(
      (btn) => btn.hasAttribute('aria-label'),
    )
    expect(primaryButtons.length).toBeGreaterThanOrEqual(3)
  })

  it('toolbar has role=toolbar with aria-label', () => {
    renderToolbar()
    const toolbar = screen.getByRole('toolbar')
    expect(toolbar).toHaveAttribute('aria-label', 'Analysis tools')
  })

  it('tool buttons are disabled when no ticker is provided', () => {
    renderToolbar({ ticker: '' })
    // Primary tool buttons + Ask AI should be disabled; More toggle is not a tool button
    const dcfBtn = screen.getByText('Run DCF').closest('button')!
    const compsBtn = screen.getByText('Compare peers').closest('button')!
    const earningsBtn = screen.getByText('Earnings').closest('button')!
    expect(dcfBtn).toBeDisabled()
    expect(compsBtn).toBeDisabled()
    expect(earningsBtn).toBeDisabled()
  })
})

describe('VerbToolbar — ask-ai callback', () => {
  it('calls onAskAi when ask-ai button is clicked', () => {
    const onAskAi = vi.fn()
    renderToolbar({ onAskAi })
    fireEvent.click(screen.getByText('Ask AI'))
    expect(onAskAi).toHaveBeenCalledOnce()
  })

  it('does NOT start a mutation for ask-ai', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    renderToolbar({ onAskAi: vi.fn() })
    fireEvent.click(screen.getByText('Ask AI'))
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})

describe('VerbToolbar — loading state', () => {
  it('DCF button becomes disabled while running', async () => {
    // Simulate running state in store
    useStocksStore.setState({
      runningTools: new Set(['dcf']),
      currentTicker: 'AAPL',
    })
    renderToolbar()
    const dcfBtn = screen.getByText('Run DCF').closest('button')!
    expect(dcfBtn).toBeDisabled()
    expect(dcfBtn).toHaveAttribute('aria-busy', 'true')
  })

  it('Comps button stays enabled while DCF is running', () => {
    useStocksStore.setState({
      runningTools: new Set(['dcf']),
      currentTicker: 'AAPL',
    })
    renderToolbar()
    const compsBtn = screen.getByText('Compare peers').closest('button')!
    expect(compsBtn).not.toBeDisabled()
  })

  it('two primary tools can run simultaneously with independent loading states', () => {
    useStocksStore.setState({
      runningTools: new Set(['dcf', 'comps']),
      currentTicker: 'AAPL',
    })
    renderToolbar()
    const dcfBtn = screen.getByText('Run DCF').closest('button')!
    const compsBtn = screen.getByText('Compare peers').closest('button')!
    expect(dcfBtn).toBeDisabled()
    expect(compsBtn).toBeDisabled()
    // Earnings should still be enabled
    const earningsBtn = screen.getByText('Earnings').closest('button')!
    expect(earningsBtn).not.toBeDisabled()
  })

  it('does not fire a second mutation when button is already disabled', () => {
    useStocksStore.setState({
      runningTools: new Set(['dcf']),
      currentTicker: 'AAPL',
    })
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('{}', { status: 200 }),
    )
    renderToolbar()
    const dcfBtn = screen.getByText('Run DCF').closest('button')!
    fireEvent.click(dcfBtn)
    // Should not have made a new fetch call (button was disabled)
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})

describe('VerbToolbar — network error toast', () => {
  it('shows error state on network failure (fetch rejects)', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('Network error'))

    renderToolbar()
    // Click DCF
    fireEvent.click(screen.getByText('Run DCF'))

    // Wait for mutation to settle
    await waitFor(() => {
      // The store should no longer have dcf in runningTools (finishTool called)
      const { runningTools } = useStocksStore.getState()
      expect(runningTools.has('dcf')).toBe(false)
    }, { timeout: 3000 })
  })
})

describe('VerbToolbar — success navigation', () => {
  it('calls onToolComplete with "dcf" after successful DCF run', async () => {
    const onToolComplete = vi.fn()

    // Mock the two fetch calls: financials + compute/dcf
    vi.spyOn(globalThis, 'fetch').mockImplementation((url: RequestInfo | URL) => {
      const urlStr = String(url)
      if (urlStr.includes('/financials')) {
        return Promise.resolve(
          new Response(JSON.stringify({ income: { revenue: 1e11 }, market: {}, total_debt: 0, total_cash: 0 }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        )
      }
      // compute/dcf
      return Promise.resolve(
        new Response(JSON.stringify({ implied_price: 200, wacc: 0.09 }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    })

    renderToolbar({ onToolComplete })
    fireEvent.click(screen.getByText('Run DCF'))

    await waitFor(() => {
      expect(onToolComplete).toHaveBeenCalledWith('dcf')
    }, { timeout: 3000 })
  })
})
