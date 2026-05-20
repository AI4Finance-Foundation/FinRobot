/**
 * VerbToolbar — unit tests
 *
 * Post 2026-05 simplification: the toolbar carries only two buttons,
 * 「一键全面分析」 and 「问 AI」. Per-tool buttons moved into individual tabs.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import VerbToolbar from './VerbToolbar'

function renderToolbar(
  props: Partial<React.ComponentProps<typeof VerbToolbar>> = {},
) {
  return render(<VerbToolbar ticker="AAPL" {...props} />)
}

beforeEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('VerbToolbar — rendering', () => {
  it('renders the full-analysis hero and ask-ai button', () => {
    renderToolbar()
    expect(screen.getByText(/一键全面分析/)).toBeInTheDocument()
    expect(screen.getByText('问 AI')).toBeInTheDocument()
  })

  it('toolbar exposes role=toolbar with aria-label', () => {
    renderToolbar()
    const toolbar = screen.getByRole('toolbar')
    expect(toolbar).toHaveAttribute('aria-label', 'Analysis tools')
  })

  it('renders only two action buttons (no per-tool buttons)', () => {
    renderToolbar()
    const buttons = screen.getAllByRole('button')
    expect(buttons).toHaveLength(2)
  })

  it('disables both buttons when no ticker is provided', () => {
    renderToolbar({ ticker: '' })
    const heroBtn = screen.getByText(/一键全面分析/).closest('button')!
    const askAiBtn = screen.getByText('问 AI').closest('button')!
    expect(heroBtn).toBeDisabled()
    expect(askAiBtn).toBeDisabled()
  })
})

describe('VerbToolbar — full-analysis state', () => {
  it('shows running label when fullAnalysisRunning=true', () => {
    renderToolbar({ fullAnalysisRunning: true })
    expect(screen.getByText('分析中...')).toBeInTheDocument()
  })

  it('disables the hero while a run is in flight', () => {
    renderToolbar({ fullAnalysisRunning: true })
    const heroBtn = screen.getByText('分析中...').closest('button')!
    expect(heroBtn).toBeDisabled()
  })

  it('shows rerun label with relative time when lastRunAt is set', () => {
    const twoMinutesAgo = Date.now() - 2 * 60 * 1000
    renderToolbar({ lastRunAt: twoMinutesAgo })
    expect(screen.getByText(/重新分析/)).toBeInTheDocument()
    expect(screen.getByText(/2 分钟前/)).toBeInTheDocument()
  })

  it('uses seconds-ago wording for very recent runs', () => {
    const tenSecondsAgo = Date.now() - 10_000
    renderToolbar({ lastRunAt: tenSecondsAgo })
    expect(screen.getByText(/秒前/)).toBeInTheDocument()
  })
})

describe('VerbToolbar — callbacks', () => {
  it('calls onFullAnalysis when the hero button is clicked', () => {
    const onFullAnalysis = vi.fn()
    renderToolbar({ onFullAnalysis })
    fireEvent.click(screen.getByText(/一键全面分析/))
    expect(onFullAnalysis).toHaveBeenCalledOnce()
  })

  it('does not fire onFullAnalysis when a run is already in flight', () => {
    const onFullAnalysis = vi.fn()
    renderToolbar({ onFullAnalysis, fullAnalysisRunning: true })
    fireEvent.click(screen.getByText('分析中...'))
    expect(onFullAnalysis).not.toHaveBeenCalled()
  })

  it('calls onAskAi when the ask-ai button is clicked', () => {
    const onAskAi = vi.fn()
    renderToolbar({ onAskAi })
    fireEvent.click(screen.getByText('问 AI'))
    expect(onAskAi).toHaveBeenCalledOnce()
  })
})
