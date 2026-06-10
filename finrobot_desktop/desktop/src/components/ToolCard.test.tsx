import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ToolCard } from './ToolCard'
import type { ToolCardProps } from './ToolCard'

// ToolCard's artifact link is a react-router <Link>, so it needs a Router in the
// tree. MemoryRouter renders the same <a href> a real route would.
function renderCard(props: Partial<ToolCardProps> = {}) {
  const defaults: ToolCardProps = {
    toolCallId: 'call_001',
    toolName: 'run_dcf_valuation',
    args: { ticker: 'AAPL' },
    state: 'pending',
    ...props,
  }
  return render(
    <MemoryRouter>
      <ToolCard {...defaults} />
    </MemoryRouter>,
  )
}

describe('ToolCard — state display', () => {
  it('renders with pending state and shows pending icon', () => {
    renderCard({ state: 'pending' })
    expect(screen.getByTestId('tool-card')).toBeInTheDocument()
    expect(screen.getByLabelText('pending')).toBeInTheDocument()
  })

  it('renders with running state and shows spinner', () => {
    renderCard({ state: 'running' })
    expect(screen.getByLabelText('running')).toBeInTheDocument()
  })

  it('renders with complete state, shows check icon and badge', () => {
    renderCard({ state: 'complete', result: { summary: 'DCF done' } })
    expect(screen.getByLabelText('complete')).toBeInTheDocument()
    expect(screen.getByText(/Code-Computed/)).toBeInTheDocument()
  })

  it('renders with error state and shows error icon', () => {
    renderCard({ state: 'error', errorText: '数据获取失败' })
    expect(screen.getByLabelText('error')).toBeInTheDocument()
    expect(screen.getByText('数据获取失败')).toBeInTheDocument()
  })

  // The retry label comes from i18n (toolcard.retry → "Retry" in the test's en
  // locale, "重试" in zh), so query the button by role with a locale-agnostic
  // accessible-name match instead of a hardcoded string.
  const RETRY_NAME = /retry|重试/i

  it('shows retry button on error when onRetry provided', () => {
    const onRetry = vi.fn()
    renderCard({ state: 'error', onRetry })
    fireEvent.click(screen.getByRole('button', { name: RETRY_NAME }))
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('does not show retry button when onRetry not provided', () => {
    renderCard({ state: 'error' })
    expect(screen.queryByRole('button', { name: RETRY_NAME })).not.toBeInTheDocument()
  })
})

describe('ToolCard — result display', () => {
  it('shows result summary when complete', () => {
    renderCard({
      state: 'complete',
      result: { summary: 'AAPL implied price $198-$224' },
    })
    expect(screen.getByText('AAPL implied price $198-$224')).toBeInTheDocument()
  })

  it('a short summary renders inline with no collapse toggle', () => {
    renderCard({ state: 'complete', result: { summary: 'DCF: $198–$224' } })
    expect(screen.queryByTestId('summary-toggle')).not.toBeInTheDocument()
    expect(screen.getByTestId('tool-summary')).toBeInTheDocument()
  })

  it('a long summary (a full report body) stays collapsed; expanding reveals a scroll box', () => {
    const longReport = `# FinRobot Analysis Report\n\n${'Apple Inc. equity research. '.repeat(40)}`
    expect(longReport.length).toBeGreaterThan(360)
    renderCard({ state: 'complete', result: { summary: longReport } })

    // Collapsed by default: the report body is NOT in the thread at all (no flood).
    const toggle = screen.getByTestId('summary-toggle')
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByTestId('tool-summary')).not.toBeInTheDocument()

    // Expanding renders the body (markdown-aware) inside a bounded scroll box.
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    const body = screen.getByTestId('tool-summary')
    expect(body).toBeInTheDocument()
    expect(body).toHaveStyle({ maxHeight: '320px', overflowY: 'auto' })
  })

  it('shows artifact link when artifact_id and ticker present', () => {
    renderCard({
      state: 'complete',
      result: { summary: 'done', artifact_id: 'art_abc', ticker: 'AAPL' },
    })
    const link = screen.getByTestId('artifact-link')
    expect(link).toBeInTheDocument()
    expect(link).toHaveAttribute('href', '/stocks/AAPL/runs/art_abc')
  })

  it('does not show artifact link when ticker is missing (avoids a dead link)', () => {
    renderCard({
      state: 'complete',
      result: { summary: 'done', artifact_id: 'art_xyz' },
    })
    expect(screen.queryByTestId('artifact-link')).not.toBeInTheDocument()
  })

  it('does not show artifact link when no artifact_id', () => {
    renderCard({
      state: 'complete',
      result: { summary: 'done' },
    })
    expect(screen.queryByTestId('artifact-link')).not.toBeInTheDocument()
  })

  it('does not show artifact link when state is not complete', () => {
    renderCard({
      state: 'running',
      result: { summary: 'in progress', artifact_id: 'art_abc', ticker: 'AAPL' },
    })
    expect(screen.queryByTestId('artifact-link')).not.toBeInTheDocument()
  })
})

describe('ToolCard — args expand/collapse', () => {
  it('starts collapsed — args JSON not visible', () => {
    renderCard({ args: { ticker: 'AAPL', years: 5 } })
    // The JSON block is hidden initially
    expect(screen.queryByText(/"ticker": "AAPL"/)).not.toBeInTheDocument()
  })

  it('expands args on button click', () => {
    renderCard({ args: { ticker: 'AAPL', years: 5 } })
    const btn = screen.getByTitle(/run_dcf_valuation/)
    fireEvent.click(btn)
    expect(screen.getByText(/"ticker": "AAPL"/)).toBeInTheDocument()
  })

  it('collapses args on second click', () => {
    renderCard({ args: { ticker: 'AAPL' } })
    const btn = screen.getByTitle(/run_dcf_valuation/)
    fireEvent.click(btn)
    fireEvent.click(btn)
    expect(screen.queryByText(/"ticker": "AAPL"/)).not.toBeInTheDocument()
  })
})

describe('ToolCard — tool identity', () => {
  it('shows a human action label, not the raw func() name', () => {
    renderCard({ toolName: 'run_equity_research' })
    expect(screen.getByText('Equity Research')).toBeInTheDocument()
    // The raw call survives only as the title tooltip (hover affordance).
    expect(screen.queryByText('run_equity_research')).not.toBeInTheDocument()
  })

  it('humanises an unknown tool name (run_foo_bar → "Foo Bar")', () => {
    renderCard({ toolName: 'run_foo_bar' })
    expect(screen.getByText('Foo Bar')).toBeInTheDocument()
  })

  it('renders the ticker chip from args when result has none yet (running)', () => {
    renderCard({ toolName: 'run_dcf_valuation', state: 'running', args: { ticker: 'nvda' } })
    expect(screen.getByText('NVDA')).toBeInTheDocument()
  })
})

describe('ToolCard — data-state attribute', () => {
  it.each(['pending', 'running', 'complete', 'error'] as const)('has data-state="%s"', (state) => {
    renderCard({ state })
    expect(screen.getByTestId('tool-card')).toHaveAttribute('data-state', state)
  })
})
