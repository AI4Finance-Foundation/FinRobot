/**
 * Sidebar — discoverability + stable-nav tests (BUG-20260602-018).
 *
 * The primary nav used to jump to a "memory path" (running ticker > last
 * stocks path > landing) with a hidden ⌘-click escape hatch, which made the
 * top icon's destination unpredictable. After the Coverage-home refactor the
 * primary item is a single, stable /coverage door. These tests lock in:
 *   - every nav icon is a labelled button with a stable href-like destination
 *   - clicking the primary icon always navigates to /coverage (no modifier
 *     branching, no memory path)
 *   - the icon-only rail exposes its name on keyboard focus (a discoverability
 *     path the native `title` attribute never provides)
 */

import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { useUiPrefs } from '../i18n'
import { useRunStreamStore, type RunState, type RunStatus } from '../stores/runStreamStore'

function makeRun(ticker: string, status: RunStatus): RunState {
  return {
    runId: `run-${ticker}`,
    ticker,
    pipelineType: 'equity_research',
    steps: [],
    status,
    progress: status === 'completed' ? 100 : 50,
    error: null,
    startedAt: Date.now(),
    dismissed: false,
    artifactId: null,
    artifactType: null,
  }
}

function LocationProbe(): React.ReactElement {
  const loc = useLocation()
  return <div data-testid="loc">{loc.pathname}</div>
}

function renderSidebar(initialPath = '/coverage'): void {
  render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Sidebar />
      <LocationProbe />
    </MemoryRouter>,
  )
}

describe('Sidebar', () => {
  beforeEach(() => {
    act(() => {
      // setLocale (not setState) activates the Lingui catalog so t() returns
      // the right language — raw setState only updates the store snapshot.
      useUiPrefs.getState().setLocale('en')
      useRunStreamStore.setState({ runs: {} })
    })
  })

  it('renders every nav item as a labelled button', () => {
    renderSidebar()
    // Coverage (primary) + Settings (bottom) — both must be discoverable by name.
    expect(screen.getByRole('button', { name: 'Coverage' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Settings' })).toBeInTheDocument()
  })

  it('marks the active route with aria-current=page', () => {
    renderSidebar('/coverage/AAPL')
    // isActive is a startsWith match, so a drill-down path keeps Coverage active.
    expect(screen.getByRole('button', { name: 'Coverage' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('button', { name: 'Settings' })).not.toHaveAttribute('aria-current')
  })

  it('primary icon always navigates to the stable /coverage home (no memory path)', () => {
    renderSidebar('/settings')
    expect(screen.getByTestId('loc')).toHaveTextContent('/settings')
    fireEvent.click(screen.getByRole('button', { name: 'Coverage' }))
    expect(screen.getByTestId('loc')).toHaveTextContent('/coverage')
  })

  it('reveals the destination name on keyboard focus (title-attr gap)', () => {
    renderSidebar()
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
    fireEvent.focus(screen.getByRole('button', { name: 'Coverage' }))
    const tip = screen.getByRole('tooltip')
    expect(tip).toHaveTextContent('Coverage')
    fireEvent.blur(screen.getByRole('button', { name: 'Coverage' }))
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })

  it('shows a running-count badge on the primary icon when runs are active', () => {
    act(() => {
      useRunStreamStore.setState({
        runs: {
          AAPL: makeRun('AAPL', 'running'),
          MSFT: makeRun('MSFT', 'running'),
          NVDA: makeRun('NVDA', 'completed'),
        },
      })
    })
    renderSidebar()
    // 2 running → badge announces the count via aria-label.
    expect(screen.getByLabelText('2 analysis running')).toBeInTheDocument()
    // Hover surfaces the same info in the flyout for sighted users.
    fireEvent.mouseEnter(screen.getByRole('button', { name: 'Coverage' }))
    expect(screen.getByRole('tooltip')).toHaveTextContent('2 analysis running')
  })

  it('localises the flyout active suffix in Chinese', () => {
    act(() => {
      useUiPrefs.getState().setLocale('zh')
    })
    renderSidebar('/coverage')
    fireEvent.focus(screen.getByRole('button', { name: '覆盖池' }))
    expect(screen.getByRole('tooltip')).toHaveTextContent('当前页')
  })
})
