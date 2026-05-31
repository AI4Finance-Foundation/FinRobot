import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ToolCard } from './ToolCard'
import type { ToolCardProps } from './ToolCard'

function renderCard(props: Partial<ToolCardProps> = {}) {
  const defaults: ToolCardProps = {
    toolCallId: 'call_001',
    toolName: 'run_dcf_valuation',
    args: { ticker: 'AAPL' },
    state: 'pending',
    ...props,
  }
  return render(<ToolCard {...defaults} />)
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

  it('shows artifact link when artifact_id and ticker present', () => {
    renderCard({
      state: 'complete',
      result: { summary: 'done', artifact_id: 'art_abc', ticker: 'AAPL' },
    })
    const link = screen.getByTestId('artifact-link')
    expect(link).toBeInTheDocument()
    expect(link).toHaveAttribute('href', '/stocks/AAPL?artifact=art_abc')
  })

  it('shows artifact link without ticker (falls back to /stocks?artifact=...)', () => {
    renderCard({
      state: 'complete',
      result: { summary: 'done', artifact_id: 'art_xyz' },
    })
    const link = screen.getByTestId('artifact-link')
    expect(link).toHaveAttribute('href', '/stocks?artifact=art_xyz')
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

describe('ToolCard — data-state attribute', () => {
  it.each(['pending', 'running', 'complete', 'error'] as const)('has data-state="%s"', (state) => {
    renderCard({ state })
    expect(screen.getByTestId('tool-card')).toHaveAttribute('data-state', state)
  })
})
