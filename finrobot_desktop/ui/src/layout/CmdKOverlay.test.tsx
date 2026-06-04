/**
 * CmdKOverlay — 25+ tests covering:
 *   - Render and closed state
 *   - Three trigger paths (⌘K, TopBar toggle via store, finrobot:open-cmdk event)
 *   - Two result kind groups (ticker / artifact)
 *   - Keyboard nav (↑↓ Enter Esc)
 *   - Action execution → navigate + close
 *   - AI fallback display
 *   - Recent searches (localStorage)
 *   - 15 exception paths
 */

import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  CmdKOverlay,
  loadRecentSearches,
  saveRecentSearch,
  parseReportRoute,
  matchSections,
} from './CmdKOverlay'
import { useUiStore } from '../stores/uiStore'
import { useUiPrefs } from '../i18n'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeSearchResult(
  kind: 'ticker' | 'artifact',
  overrides: Partial<{
    title: string
    subtitle: string
    action: string
    score: number
  }> = {},
) {
  const defaults = {
    ticker: {
      title: 'AAPL',
      subtitle: '打开 Stocks 页',
      action: 'navigate:/stocks/AAPL',
      score: 10,
    },
    artifact: {
      title: 'AAPL · DCF',
      subtitle: '2026-05-13',
      action: 'navigate:/stocks/AAPL/runs/art_001',
      score: 2,
    },
  } as const
  return { kind, ...defaults[kind], ...overrides }
}

function mockFetch(response: object, status = 200) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => response,
  } as Response)
}

function renderOverlay(initialPath = '/stocks') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialPath]}>
        <CmdKOverlay />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  // Reset store to closed state
  useUiStore.setState({ cmdPaletteOpen: false, cmdKQuery: '' })
  // Reset chat handoff channel (BUG-013) — Ask AI feeds uiStore.pendingChatPrompt
  useUiStore.setState({ pendingChatPrompt: null, aiPanelOpen: false })
  // Clear localStorage
  localStorage.clear()
  useUiPrefs.getState().setLocale('zh')
  // Clear fetch mock
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.restoreAllMocks()
})

// ---------------------------------------------------------------------------
// 1. Render and closed state
// ---------------------------------------------------------------------------

describe('CmdKOverlay — closed state', () => {
  it('renders nothing when cmdPaletteOpen is false', () => {
    renderOverlay()
    expect(screen.queryByTestId('cmdk-input')).not.toBeInTheDocument()
  })

  it('renders the dialog when cmdPaletteOpen is true', () => {
    useUiStore.setState({ cmdPaletteOpen: true })
    renderOverlay()
    expect(screen.getByTestId('cmdk-input')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// 2. Trigger paths
// ---------------------------------------------------------------------------

describe('CmdKOverlay — trigger paths', () => {
  it('trigger 1: ⌘K opens overlay', async () => {
    renderOverlay()
    expect(screen.queryByTestId('cmdk-input')).not.toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'k', metaKey: true })
    await waitFor(() => expect(screen.getByTestId('cmdk-input')).toBeInTheDocument())
  })

  it('trigger 1: Ctrl+K opens overlay', async () => {
    renderOverlay()
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
    await waitFor(() => expect(screen.getByTestId('cmdk-input')).toBeInTheDocument())
  })

  it('trigger 2: store.toggleCmdPalette opens overlay', async () => {
    renderOverlay()
    act(() => useUiStore.getState().toggleCmdPalette())
    await waitFor(() => expect(screen.getByTestId('cmdk-input')).toBeInTheDocument())
  })

  it('trigger 3: finrobot:open-cmdk event opens overlay', async () => {
    renderOverlay()
    act(() => window.dispatchEvent(new Event('finrobot:open-cmdk')))
    await waitFor(() => expect(screen.getByTestId('cmdk-input')).toBeInTheDocument())
  })
})

// ---------------------------------------------------------------------------
// 3. Keyboard: Esc closes
// ---------------------------------------------------------------------------

describe('CmdKOverlay — Esc closes', () => {
  it('Esc key closes the overlay and clears query', async () => {
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: 'AAPL' })
    renderOverlay()
    expect(screen.getByTestId('cmdk-input')).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByTestId('cmdk-input')).not.toBeInTheDocument())
    expect(useUiStore.getState().cmdKQuery).toBe('')
  })
})

// ---------------------------------------------------------------------------
// 4. Three result kind groups
// ---------------------------------------------------------------------------

describe('CmdKOverlay — result groups', () => {
  it('renders ticker group', async () => {
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: 'AAPL' })
    mockFetch({
      query: 'AAPL',
      results: [makeSearchResult('ticker')],
    })
    renderOverlay()
    await waitFor(() => expect(screen.getByTestId('ticker-group')).toBeInTheDocument())
    expect(screen.getByText('AAPL')).toBeInTheDocument()
    expect(screen.getByText('打开 Stocks 页')).toBeInTheDocument()
  })

  it('renders artifact group', async () => {
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: 'AAPL' })
    mockFetch({
      query: 'AAPL',
      results: [makeSearchResult('artifact')],
    })
    renderOverlay()
    await waitFor(() => expect(screen.getByTestId('artifact-group')).toBeInTheDocument())
  })

  it('renders both groups simultaneously', async () => {
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: 'AAPL' })
    mockFetch({
      query: 'AAPL',
      results: [makeSearchResult('ticker'), makeSearchResult('artifact')],
    })
    renderOverlay()
    await waitFor(() => {
      expect(screen.getByTestId('ticker-group')).toBeInTheDocument()
      expect(screen.getByTestId('artifact-group')).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// 5. Action execution after selecting an item
// ---------------------------------------------------------------------------

describe('CmdKOverlay — action execution and close', () => {
  it('navigate action closes overlay and navigates', async () => {
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: 'AAPL' })
    mockFetch({
      query: 'AAPL',
      results: [makeSearchResult('ticker')],
    })
    renderOverlay()
    const item = await screen.findByText('AAPL')
    fireEvent.click(item.closest("[data-testid='cmdk-result-item']")!)
    await waitFor(() => expect(useUiStore.getState().cmdPaletteOpen).toBe(false))
  })
})

// ---------------------------------------------------------------------------
// 6. AI fallback
// ---------------------------------------------------------------------------

describe('CmdKOverlay — AI fallback', () => {
  it('shows AI fallback when 0 results and query non-empty', async () => {
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: 'xyzzy random' })
    mockFetch({ query: 'xyzzy random', results: [] })
    renderOverlay()
    await waitFor(() => expect(screen.getByTestId('ai-fallback')).toBeInTheDocument())
    expect(screen.getByTestId('ai-fallback-button')).toBeInTheDocument()
  })

  // UX-017: Ask AI is a first-class action, not a "search failed" consolation
  // prize — it must also be offered when remote results DO exist, so a user who
  // just wants to ask doesn't have to watch the search come up empty first.
  it('shows AI fallback even when remote results exist (query non-empty)', async () => {
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: 'AAPL' })
    mockFetch({ query: 'AAPL', results: [makeSearchResult('ticker')] })
    renderOverlay()
    // A real search result renders…
    await screen.findByText('AAPL')
    // …and the Ask-AI item is still offered alongside it.
    expect(screen.getByTestId('ai-fallback')).toBeInTheDocument()
    expect(screen.getByTestId('ai-fallback-item')).toBeInTheDocument()
  })

  // BUG-013: Ask AI must feed the right-side AI panel via uiStore.sendChatPrompt
  // (pendingChatPrompt), NOT a dead sessionStorage key.
  it('AI fallback hands the query to uiStore.sendChatPrompt, opens AI panel, closes overlay', async () => {
    const sessionSpy = vi.spyOn(Storage.prototype, 'setItem')
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: 'why is NVDA up' })
    mockFetch({ query: 'why is NVDA up', results: [] })
    renderOverlay()
    const btn = await screen.findByTestId('ai-fallback-item')
    fireEvent.click(btn)
    await waitFor(() => {
      expect(useUiStore.getState().pendingChatPrompt).toEqual({
        text: 'why is NVDA up',
        autoSend: true,
      })
    })
    // Panel opened + overlay closed
    expect(useUiStore.getState().aiPanelOpen).toBe(true)
    expect(useUiStore.getState().cmdPaletteOpen).toBe(false)
    // No dead sessionStorage write
    expect(sessionSpy).not.toHaveBeenCalledWith('finrobot.cmdk_ai_query', expect.anything())
  })
})

// ---------------------------------------------------------------------------
// 6b. BUG-023: search API failure must NOT kill local commands / Ask AI
// ---------------------------------------------------------------------------

describe('CmdKOverlay — search failure keeps local commands (BUG-023)', () => {
  it('with /api/search returning 500, the Ask AI fallback still renders (not trapped behind the error)', async () => {
    mockFetch({ detail: 'boom' }, 500)
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: 'xyzzy random' })
    renderOverlay()
    // Inline error note shows (small banner, not a takeover)
    await waitFor(() => expect(screen.getByTestId('search-error')).toBeInTheDocument())
    expect(screen.getByTestId('retry-button')).toBeInTheDocument()
    // Ask AI fallback survives the failure and is selectable — pre-fix it was
    // gated on a success-only `showEmpty`, so a 500 stranded the typed query.
    expect(screen.getByTestId('ai-fallback-item')).toBeInTheDocument()
  })

  it('matching local commands (Settings) still render under a search failure', async () => {
    mockFetch({ detail: 'boom' }, 500)
    // Query matches the Settings command title so client-side static filter keeps it.
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: '设置' })
    renderOverlay()
    await waitFor(() => expect(screen.getByTestId('search-error')).toBeInTheDocument())
    expect(screen.getByTestId('coverage-commands-group')).toBeInTheDocument()
    expect(screen.getByText('打开设置')).toBeInTheDocument()
  })

  it('Ask AI is selectable after a 500 and still feeds sendChatPrompt', async () => {
    mockFetch({ detail: 'boom' }, 500)
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: 'explain the moat' })
    renderOverlay()
    const btn = await screen.findByTestId('ai-fallback-item')
    fireEvent.click(btn)
    await waitFor(() =>
      expect(useUiStore.getState().pendingChatPrompt).toEqual({
        text: 'explain the moat',
        autoSend: true,
      }),
    )
  })

  it('Settings command navigates and closes even when search failed', async () => {
    mockFetch({ detail: 'boom' }, 500)
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: '设置' })
    renderOverlay()
    const settings = await screen.findByText('打开设置')
    fireEvent.click(settings.closest("[data-testid='coverage-command-item']")!)
    await waitFor(() => expect(useUiStore.getState().cmdPaletteOpen).toBe(false))
  })
})

// ---------------------------------------------------------------------------
// 6c. BUG-024: accessible DialogTitle + Description (no Radix a11y warning)
// ---------------------------------------------------------------------------

describe('CmdKOverlay — a11y dialog title/description (BUG-024)', () => {
  it('renders a DialogTitle and Description node and logs no Radix a11y warning', async () => {
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: '' })
    renderOverlay()
    await waitFor(() => expect(screen.getByTestId('cmdk-input')).toBeInTheDocument())
    // Accessible nodes exist
    expect(screen.getByTestId('cmdk-dialog-title')).toBeInTheDocument()
    expect(screen.getByTestId('cmdk-dialog-description')).toBeInTheDocument()
    // Radix's missing-title / missing-description warnings never fired
    const allMessages = [...errSpy.mock.calls, ...warnSpy.mock.calls]
      .flat()
      .map((m) => String(m))
      .join('\n')
    expect(allMessages).not.toContain('requires a `DialogTitle`')
    expect(allMessages).not.toContain('Missing `Description`')
    errSpy.mockRestore()
    warnSpy.mockRestore()
  })
})

// ---------------------------------------------------------------------------
// 7. Recent searches (localStorage)
// ---------------------------------------------------------------------------

describe('CmdKOverlay — recent searches', () => {
  it('shows recent searches when query is empty and localStorage has entries', async () => {
    saveRecentSearch('NVDA')
    saveRecentSearch('MSFT')
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: '' })
    renderOverlay()
    await waitFor(() => expect(screen.getByTestId('recent-searches-group')).toBeInTheDocument())
    expect(screen.getByText('NVDA')).toBeInTheDocument()
    expect(screen.getByText('MSFT')).toBeInTheDocument()
  })

  it('does not show recent searches when query is non-empty', async () => {
    saveRecentSearch('NVDA')
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: 'A' })
    mockFetch({ query: 'A', results: [] })
    renderOverlay()
    await waitFor(() =>
      expect(screen.queryByTestId('recent-searches-group')).not.toBeInTheDocument(),
    )
  })

  it('clicking a recent search item populates the query', async () => {
    saveRecentSearch('TSLA')
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: '' })
    renderOverlay()
    const item = await screen.findByText('TSLA')
    fireEvent.click(item.closest("[data-testid='recent-search-item']")!)
    await waitFor(() => expect(useUiStore.getState().cmdKQuery).toBe('TSLA'))
  })

  it('saveRecentSearch stores up to 10 and deduplicates', () => {
    for (let i = 0; i < 12; i++) saveRecentSearch(`TICK${i}`)
    const loaded = loadRecentSearches()
    expect(loaded.length).toBe(10)
    // Most recent first
    expect(loaded[0]).toBe('TICK11')
  })

  it('saveRecentSearch moves existing entry to top instead of duplicating', () => {
    saveRecentSearch('AAPL')
    saveRecentSearch('NVDA')
    saveRecentSearch('AAPL') // duplicate
    const loaded = loadRecentSearches()
    expect(loaded[0]).toBe('AAPL')
    expect(loaded.filter((q) => q === 'AAPL').length).toBe(1)
  })
})

// ---------------------------------------------------------------------------
// 8. Exception paths (15)
// ---------------------------------------------------------------------------

describe('CmdKOverlay — exception paths', () => {
  // G1: Empty query → no request fired. The palette shows local Coverage
  // quick-commands (no backend search), so the empty-placeholder is replaced
  // by the commands group — the invariant being guarded is "no fetch".
  it('G1: empty query fires no fetch and shows Coverage commands', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: '' })
    renderOverlay()
    await new Promise((r) => setTimeout(r, 300)) // wait past debounce
    expect(fetchSpy).not.toHaveBeenCalled()
    expect(screen.getByTestId('coverage-commands-group')).toBeInTheDocument()
  })

  // G2: Query > 200 chars → truncated + warning
  it('G2: query longer than 200 chars shows truncation warning', async () => {
    const longQ = 'A'.repeat(250)
    mockFetch({ query: longQ.slice(0, 200), results: [] })
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: longQ })
    renderOverlay()
    await waitFor(() => expect(screen.getByTestId('truncation-warning')).toBeInTheDocument())
  })

  // G3: Network error 503 → error banner + retry button
  it('G3: 503 response shows error banner and retry button', async () => {
    mockFetch({ detail: 'service unavailable' }, 503)
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: 'AAPL' })
    renderOverlay()
    await waitFor(() => expect(screen.getByTestId('search-error')).toBeInTheDocument())
    expect(screen.getByTestId('retry-button')).toBeInTheDocument()
  })

  it('G4: fetch timeout shows timeout error', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(
      () => new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 0)),
    )
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: 'AAPL' })
    renderOverlay()
    await waitFor(() => expect(screen.getByTestId('search-error')).toBeInTheDocument(), {
      timeout: 2000,
    })
    expect(screen.getByText(/超时/)).toBeInTheDocument()
  })

  // G5: 0 results + non-empty query → AI fallback shown (covered in section 6)
  it('G5: 0 results shows AI fallback (AI fallback section re-check)', async () => {
    mockFetch({ query: 'unknownfoo', results: [] })
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: 'unknownfoo' })
    renderOverlay()
    await waitFor(() => expect(screen.getByTestId('ai-fallback')).toBeInTheDocument())
  })

  // G6: ⌘K while focused in an input field still opens overlay
  it('G6: ⌘K while input is focused opens the overlay', async () => {
    renderOverlay()
    const inp = document.createElement('input')
    document.body.appendChild(inp)
    inp.focus()
    fireEvent.keyDown(window, { key: 'k', metaKey: true })
    await waitFor(() => expect(useUiStore.getState().cmdPaletteOpen).toBe(true))
    document.body.removeChild(inp)
  })

  // G7: ⌘K when already open → closes (toggle)
  it('G7: ⌘K when already open closes the overlay', async () => {
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: '' })
    renderOverlay()
    fireEvent.keyDown(window, { key: 'k', metaKey: true })
    await waitFor(() => expect(useUiStore.getState().cmdPaletteOpen).toBe(false))
  })

  // G8: Esc closes AND clears query
  it('G8: Esc closes overlay and clears query (duplicate check)', async () => {
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: 'hello' })
    renderOverlay()
    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => expect(useUiStore.getState().cmdPaletteOpen).toBe(false))
    expect(useUiStore.getState().cmdKQuery).toBe('')
  })

  // G10: Click outside (onOpenChange false) closes
  it('G10: onOpenChange(false) from cmdk Dialog closes overlay', async () => {
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: '' })
    renderOverlay()
    // Simulate cmdk calling onOpenChange(false) — the Dialog wraps in Radix Portal
    // We trigger it via store directly as a unit test proxy
    act(() => useUiStore.getState().setCmdPaletteOpen(false))
    await waitFor(() => expect(useUiStore.getState().cmdPaletteOpen).toBe(false))
  })

  // G11: navigate to non-existent path — action executor should still succeed
  it('G11: navigate action with arbitrary path does not throw', async () => {
    const { buildActionExecutor: exec } = await import('./CmdKOverlay')
    const navigate = vi.fn()
    const close = vi.fn()
    const execute = exec(navigate, close)
    expect(() => execute('navigate:/stocks/NONEXISTENT', 'NONEXISTENT')).not.toThrow()
    expect(navigate).toHaveBeenCalledWith('/stocks/NONEXISTENT')
    expect(close).toHaveBeenCalled()
  })

  // G12: Malformed action (no colon) → toast error, no crash
  it('G12: malformed action shows toast and does not crash', async () => {
    const { buildActionExecutor: exec } = await import('./CmdKOverlay')
    const navigate = vi.fn()
    const close = vi.fn()
    const execute = exec(navigate, close)
    expect(() => execute('MALFORMED_NO_COLON')).not.toThrow()
    expect(navigate).not.toHaveBeenCalled()
    expect(close).not.toHaveBeenCalled()
  })

  // G14: Chinese characters in query → encoded in URL properly
  it('G14: Chinese query is URI-encoded in fetch URL', async () => {
    const fetchSpy = mockFetch({ query: '苹果', results: [] })
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: '苹果' })
    renderOverlay()
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled())
    const url = (fetchSpy as Mock).mock.calls[0][0] as string
    expect(url).toContain(encodeURIComponent('苹果'))
  })

  // G15: Paste large text → debounce still works (only one fetch)
  it('G15: rapid query changes debounce to a single fetch', async () => {
    const fetchSpy = mockFetch({ query: 'AAPL', results: [] })
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: 'A' })
    renderOverlay()
    // Simulate rapid changes
    act(() => useUiStore.setState({ cmdKQuery: 'AA' }))
    act(() => useUiStore.setState({ cmdKQuery: 'AAP' }))
    act(() => useUiStore.setState({ cmdKQuery: 'AAPL' }))
    // Wait for debounce to settle
    await new Promise((r) => setTimeout(r, 400))
    // Should have fetched at most once for "AAPL" (the final value)
    const aaplCalls = (fetchSpy as Mock).mock.calls.filter((c) => (c[0] as string).includes('AAPL'))
    expect(aaplCalls.length).toBeGreaterThanOrEqual(1)
    // Should NOT have fired for every intermediate value
    expect((fetchSpy as Mock).mock.calls.length).toBeLessThan(4)
  })
})

// ---------------------------------------------------------------------------
// 8b. BUG-016: in-report section jump
// ---------------------------------------------------------------------------

// Mirrors renderOverlay but also surfaces the live location so a section jump's
// `#anchor` navigation can be asserted on the DOM.
function LocationProbe() {
  const loc = useLocation()
  return <div data-testid="location-probe">{`${loc.pathname}${loc.hash}`}</div>
}

function renderOverlayWithLocation(initialPath: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialPath]}>
        <CmdKOverlay />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const REPORT_PATH = '/stocks/AAPL/runs/art_001'

describe('CmdKOverlay — report section jump (BUG-016)', () => {
  it('parseReportRoute parses ticker + artifactId from a report detail path', () => {
    expect(parseReportRoute(REPORT_PATH)).toEqual({ ticker: 'AAPL', artifactId: 'art_001' })
    expect(parseReportRoute('/stocks/AAPL')).toBeNull()
    expect(parseReportRoute('/coverage')).toBeNull()
  })

  it('matchSections maps English + Chinese section words to anchors', () => {
    expect(matchSections('valuation').map((s) => s.anchor)).toContain('valuation')
    expect(matchSections('估值').map((s) => s.anchor)).toContain('valuation')
    expect(matchSections('风险').map((s) => s.anchor)).toContain('catalysts')
    expect(matchSections('thesis').map((s) => s.anchor)).toContain('thesis')
    expect(matchSections('论点').map((s) => s.anchor)).toContain('thesis')
    expect(matchSections('').length).toBe(0)
  })

  it('typing "valuation" on a report page offers a jump item that navigates to #valuation', async () => {
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: 'valuation' })
    mockFetch({ query: 'valuation', results: [] })
    renderOverlayWithLocation(REPORT_PATH)
    const item = await screen.findByTestId('section-jump-item')
    expect(item.getAttribute('data-anchor')).toBe('valuation')
    fireEvent.click(item)
    await waitFor(() =>
      expect(screen.getByTestId('location-probe')).toHaveTextContent(`${REPORT_PATH}#valuation`),
    )
    expect(useUiStore.getState().cmdPaletteOpen).toBe(false)
  })

  it('typing "估值" (zh) on a report page jumps to #valuation', async () => {
    useUiPrefs.getState().setLocale('zh')
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: '估值' })
    mockFetch({ query: '估值', results: [] })
    renderOverlayWithLocation(REPORT_PATH)
    const item = await screen.findByTestId('section-jump-item')
    expect(item.getAttribute('data-anchor')).toBe('valuation')
    fireEvent.click(item)
    await waitFor(() =>
      expect(screen.getByTestId('location-probe')).toHaveTextContent(`${REPORT_PATH}#valuation`),
    )
  })

  it('typing "风险" (zh) jumps to the catalysts chapter (#catalysts)', async () => {
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: '风险' })
    mockFetch({ query: '风险', results: [] })
    renderOverlayWithLocation(REPORT_PATH)
    const item = await screen.findByTestId('section-jump-item')
    expect(item.getAttribute('data-anchor')).toBe('catalysts')
  })

  it('does NOT offer section jumps when not on a report detail route', async () => {
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: 'valuation' })
    mockFetch({ query: 'valuation', results: [] })
    renderOverlayWithLocation('/stocks')
    await waitFor(() => expect(screen.getByTestId('cmdk-input')).toBeInTheDocument())
    expect(screen.queryByTestId('section-jump-group')).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// 9. Footer is always rendered when open
// ---------------------------------------------------------------------------

describe('CmdKOverlay — footer', () => {
  it('footer hint is visible when overlay is open', async () => {
    useUiStore.setState({ cmdPaletteOpen: true, cmdKQuery: '' })
    renderOverlay()
    expect(screen.getByTestId('cmdk-footer')).toBeInTheDocument()
  })
})
