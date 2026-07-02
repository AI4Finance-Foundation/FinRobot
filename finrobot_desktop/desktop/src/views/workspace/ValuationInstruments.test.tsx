import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { ArtifactSummaryV5 } from '../../types/v5'
import type { RunState } from '../../stores/runStreamStore'
import { ValuationInstruments } from './ValuationInstruments'

// Deterministic coverage of the four valuation INSTRUMENTS — the states a live
// screenshot can't pin reliably (the transient running tile) plus the
// no-fabrication guarantee (a method that returned None shows "withheld", never
// a number). The reading derivation (dcf/ddm from summary, lbo/comps from the
// full artifact) is exercised against the SAME field paths the detail page uses.

vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }))

// lbo/comps read the full artifact for their headline; mock it keyed on the id
// so an lbo id resolves IRR/MOIC and everything else returns no detail. An id
// containing 'burn' resolves a NON-self-financing deal (debt rises, returns are
// exit-multiple artifacts) so the reframing path is covered.
vi.mock('../../hooks/useV5Artifacts', () => ({
  useArtifactDetail: (id: string | null | undefined) => {
    if (!id || !id.includes('lbo')) return { data: undefined, isLoading: false }
    const structured = id.includes('burn')
      ? { irr: 0.166, moic: 2.15, self_financing: false }
      : { irr: 0.24, moic: 2.1 }
    return { data: { outputs: { structured } }, isLoading: false }
  },
}))

function summary(
  over: Partial<ArtifactSummaryV5> & { type: string; id: string },
): ArtifactSummaryV5 {
  return {
    ticker: 'T',
    cross_tickers: [],
    created_at: '2026-06-24T00:00:00Z',
    headline: 'h',
    source: 'pipeline',
    archived: false,
    primary_provider: 'fmp',
    ...over,
  } as ArtifactSummaryV5
}

const noop = () => {}

function renderInstruments(opts: {
  timeline?: ArtifactSummaryV5[]
  runState?: RunState | null
  livePrice?: number | null
}) {
  return render(
    <ValuationInstruments
      timeline={opts.timeline ?? []}
      runState={opts.runState ?? null}
      preflightBlocked={false}
      preflightReason={null}
      locale="en"
      livePrice={opts.livePrice ?? null}
      onLaunch={noop}
      onOpen={noop}
    />,
  )
}

describe('ValuationInstruments', () => {
  it('all four idle when the ticker has no valuation artifacts', () => {
    renderInstruments({ timeline: [] })
    for (const t of ['dcf', 'ddm', 'lbo', 'comps']) {
      expect(screen.getByTestId(`instrument-${t}`).getAttribute('data-state')).toBe('idle')
    }
  })

  it('dcf/ddm read their per-share value from the summary target_price + show the delta vs live price', () => {
    renderInstruments({
      timeline: [
        summary({ id: 'a_dcf', type: 'dcf', entry_price: 100, target_price: 120 }),
        summary({ id: 'a_ddm', type: 'ddm', entry_price: 100, target_price: 80 }),
      ],
      livePrice: 100,
    })
    const dcf = screen.getByTestId('instrument-dcf')
    expect(dcf.getAttribute('data-state')).toBe('value')
    expect(dcf.textContent).toContain('$120.00')
    expect(dcf.textContent).toContain('+20.0%') // (120-100)/100, green upside
    const ddm = screen.getByTestId('instrument-ddm')
    expect(ddm.textContent).toContain('$80.00')
    expect(ddm.textContent).toContain('-20.0%') // downside
  })

  it('NEVER fabricates: a computed-but-withheld method (target_price null) shows withheld, not a number', () => {
    renderInstruments({
      timeline: [summary({ id: 'a_dcf', type: 'dcf', entry_price: 100, target_price: null })],
    })
    const dcf = screen.getByTestId('instrument-dcf')
    expect(dcf.getAttribute('data-state')).toBe('withheld')
    expect(dcf.textContent).not.toMatch(/\$\d/)
  })

  it('lbo reads IRR/MOIC from the full artifact (no single price in the summary)', () => {
    renderInstruments({
      timeline: [summary({ id: 'art_lbo_1', type: 'lbo', target_price: null })],
    })
    const lbo = screen.getByTestId('instrument-lbo')
    expect(lbo.getAttribute('data-state')).toBe('value')
    expect(lbo.textContent).toContain('24% IRR')
    expect(lbo.textContent).toContain('2.10× MOIC')
  })

  it('lbo that does NOT self-finance leads with the verdict, never headlines the unearned IRR', () => {
    renderInstruments({
      timeline: [summary({ id: 'art_lbo_burn_1', type: 'lbo', target_price: null })],
    })
    const lbo = screen.getByTestId('instrument-lbo')
    expect(lbo.getAttribute('data-state')).toBe('value')
    // Verdict is the headline; the IRR is demoted + qualified, never a bare "17% IRR".
    expect(lbo.textContent).toContain('Not self-financing')
    expect(lbo.textContent).toContain('exit-multiple only')
    expect(lbo.textContent).not.toContain('2.15× MOIC')
  })

  it('an instrument run renders progress IN its own tile and locks the others (never the top panel)', () => {
    const runState = {
      pipelineType: 'dcf',
      status: 'running',
      steps: [
        { name: 'data_collection', status: 'completed' },
        { name: 'dcf_modeling', status: 'running' },
        { name: 'report', status: 'pending' },
      ],
    } as unknown as RunState
    renderInstruments({ runState })
    expect(screen.getByTestId('instrument-dcf').getAttribute('data-state')).toBe('running')
    expect(screen.getByTestId('instrument-dcf').textContent).toContain('1/3')
    // the other idle tiles are disabled while the single run slot is held
    expect((screen.getByTestId('instrument-ddm') as HTMLButtonElement).disabled).toBe(true)
  })

  it('a FAILED instrument run surfaces an explicit failed tile (never disguised as idle "not yet computed")', () => {
    const runState = {
      pipelineType: 'dcf',
      status: 'failed',
      error: 'provider timeout',
      steps: [],
    } as unknown as RunState
    renderInstruments({ runState })
    const dcf = screen.getByTestId('instrument-dcf')
    expect(dcf.getAttribute('data-state')).toBe('failed')
    expect(dcf.textContent).toContain('run failed')
    expect(dcf.textContent).toContain('provider timeout') // the real error, surfaced
    expect(dcf.textContent).not.toContain('not yet computed') // not disguised as never-run
    expect((dcf as HTMLButtonElement).disabled).toBe(false) // retryable — no run holds the slot
  })

  it('a failed re-run KEEPS the prior successful value (failure never erases a computed value)', () => {
    const runState = {
      pipelineType: 'dcf',
      status: 'failed',
      error: 'boom',
      steps: [],
    } as unknown as RunState
    renderInstruments({
      timeline: [summary({ id: 'a_dcf', type: 'dcf', entry_price: 100, target_price: 120 })],
      runState,
      livePrice: 100,
    })
    const dcf = screen.getByTestId('instrument-dcf')
    expect(dcf.getAttribute('data-state')).toBe('value')
    expect(dcf.textContent).toContain('$120.00')
  })

  it('a user-CANCELLED run falls back to idle, not failed (cancel is not an error)', () => {
    const runState = {
      pipelineType: 'dcf',
      status: 'cancelled',
      error: null,
      steps: [],
    } as unknown as RunState
    renderInstruments({ runState })
    expect(screen.getByTestId('instrument-dcf').getAttribute('data-state')).toBe('idle')
  })
})
