import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

import { CompactArtifactViewer } from './CompactArtifactViewer'
import type { ArtifactDetail } from '../../hooks/useV5Artifacts'

// The reused chapter bodies pull in Recharts charts (WaterfallField / heatmap /
// peer bar + radar). They're irrelevant to these render assertions and don't lay
// out in jsdom, so stub them to no-ops. i18n is NOT mocked — the tool page reuses
// the report's real compiled catalog (`t(...)`) + the `T(locale,…)` helper, and we
// assert the real English strings (default locale = en), so a mock would defeat
// the point.
vi.mock('../../components/charts/WaterfallChart', () => ({ default: () => null }))
vi.mock('../../components/charts/FootballField', () => ({ default: () => null }))
vi.mock('../../components/charts/SensitivityHeatmap', () => ({ default: () => null }))
vi.mock('../../components/charts/PeerComparisonChart', () => ({ default: () => null }))
vi.mock('../../components/charts/CompanyRadarChart', () => ({ default: () => null }))

function artifact(
  type: string,
  structured: Record<string, unknown>,
  extra?: Partial<ArtifactDetail>,
): ArtifactDetail {
  return {
    id: `art-${type}`,
    ticker: 'KO',
    type,
    created_at: '2026-07-02T00:00:00Z',
    outputs: { structured, summary_text: '', warnings: [] },
    inputs: { data_source: 'FMP', data_fetched_at: '2026-07-02T00:00:00Z', raw_data: {} },
    assumptions: { parameters: {} },
    meta: { created_at: '2026-07-02T00:00:00Z', source: `pipeline:${type}` },
    ...extra,
  } as unknown as ArtifactDetail
}

const seq = (n: number, base: number): number[] =>
  Array.from({ length: n }, (_, i) => base * (1 + i))

// ── Existing comps-headline contract (unchanged) ─────────────────────────────

describe('CompactArtifactViewer — comps headline multiples', () => {
  it('surfaces Peer Median P/B alongside P/E and EV/EBITDA when all are present', () => {
    render(
      <CompactArtifactViewer
        artifact={artifact('comps', { median_pe: 11, median_pb: 1.3, median_ev_ebitda: 9 })}
      />,
    )
    expect(screen.getByText('Peer Median P/E')).toBeTruthy()
    expect(screen.getByText('Peer Median P/B')).toBeTruthy()
    expect(screen.getByText('Peer Median EV/EBITDA')).toBeTruthy()
    expect(screen.getByText('1.3×')).toBeTruthy()
  })

  it('omits EV/EBITDA when the backend nulled it for a financial-sector target', () => {
    render(
      <CompactArtifactViewer
        artifact={artifact('comps', { median_pe: 11, median_pb: 1.3, median_ev_ebitda: null })}
      />,
    )
    expect(screen.getByText('Peer Median P/E')).toBeTruthy()
    expect(screen.getByText('Peer Median P/B')).toBeTruthy()
    expect(screen.queryByText('Peer Median EV/EBITDA')).toBeNull()
  })
})

// ── Reused chapter panels: DCF / DDM / LBO / Comps ───────────────────────────
// Each asserts (1) the report panel is reused, (2) no "N fields" dead text, and
// (3) arrays render in full (no silent slice@8).

describe('CompactArtifactViewer — DCF reuses the valuation + sensitivity panels', () => {
  const dcf = {
    wacc: 0.0864,
    cost_of_equity: 0.0877,
    projection_years: 10,
    projected_revenue: seq(10, 5e11),
    projected_ebitda: seq(10, 1.7e11),
    projected_fcf: seq(10, 1.2e11),
    terminal_value: 3.9e12,
    pv_terminal: 1.7e12,
    pv_fcf_total: 1.0e12,
    enterprise_value: 2.78e12,
    equity_value: 2.76e12,
    implied_price: 188.3,
    currency: 'USD',
    sensitivity_table: {
      wacc_values: [0.08, 0.085, 0.09],
      tg_values: [0.02, 0.03, 0.04],
      implied_prices: [
        [200, 210, 220],
        [180, 188, 196],
        [160, 168, 176],
      ],
    },
    market_implied: null,
    inputs: {
      revenue_base: 4.5e11,
      revenue_growth_rates: seq(10, 0.05),
      ebitda_margin: 0.344,
      terminal_growth_rate: 0.03,
      tax_rate: 0.17,
      beta: 1.06,
      risk_free_rate: 0.043,
      assumption_provenance: {
        revenue_base: 'latest TTM revenue (trailing 12 months)',
        ebitda_margin: '34.4% (trailing 3yr EBITDA margin median)',
      },
    },
  }

  it('renders the DCF inputs module + full 10-year forecast + readable provenance', () => {
    const { container } = render(<CompactArtifactViewer artifact={artifact('dcf', dcf)} />)
    // Reused ValuationBody panel.
    expect(screen.getByText('DCF Inputs & Implied Value')).toBeTruthy()
    // Full projection: the 10th year column renders (old viewer truncated arrays @8).
    expect(screen.getByText('Year +10')).toBeTruthy()
    // Readable provenance (humanized key, prose value) — not raw snake_case.
    expect(screen.getByText('34.4% (trailing 3yr EBITDA margin median)')).toBeTruthy()
    // No "N fields" / "N 项" dead text anywhere.
    expect(container.textContent ?? '').not.toMatch(/\d+ fields/)
    expect(container.textContent ?? '').not.toMatch(/\d+ 字段/)
    expect(container.textContent ?? '').not.toContain('assumption_provenance')
  })
})

describe('CompactArtifactViewer — DDM reuses shared primitives', () => {
  const ddm = {
    cost_of_equity: 0.058,
    projected_dividends: seq(10, 2.4),
    pv_dividends: seq(10, 2.2),
    pv_dividends_total: 27.2,
    terminal_dividend: 5.07,
    terminal_value: 181.2,
    pv_terminal: 103.2,
    equity_value_per_share: 130.4,
    inputs: {
      dividend_per_share: 2.08,
      dividend_growth_rates: seq(10, 0.05),
      payout_ratio: 0.65,
      beta: 0.35,
      terminal_growth_rate: 0.03,
      current_price: 81.29,
      assumption_provenance: { dividend_per_share: '$2.08 (provider-reported annualized DPS)' },
    },
  }

  it('renders the DDM inputs module + full dividend projection', () => {
    const { container } = render(<CompactArtifactViewer artifact={artifact('ddm', ddm)} />)
    expect(screen.getByText('DDM Inputs & Value / Share')).toBeTruthy()
    // 10-year dividend projection renders in full.
    expect(screen.getByText('Y+10')).toBeTruthy()
    expect(screen.getByText('$2.08 (provider-reported annualized DPS)')).toBeTruthy()
    expect(container.textContent ?? '').not.toMatch(/\d+ fields/)
    expect(container.textContent ?? '').not.toMatch(/\d+ 字段/)
  })
})

describe('CompactArtifactViewer — LBO reuses shared primitives', () => {
  const scheduleYear = (year: number) => ({
    year,
    revenue: 5e10 * year,
    ebitda: 1.4e10 * year,
    da: 1e9,
    ebit: 1.2e10,
    interest_expense: 4e9,
    ebt: 8e9,
    taxes: 1.6e9,
    net_income: 6e9,
    capex: 2e9,
    delta_nwc: 2e8,
    fcf: 4e9 * year,
    mandatory_amort: 8e8,
    cash_sweep_amount: 3e9,
    total_debt_paydown: 3.8e9,
    revolver_draw: 0,
    ending_debt: 7e10 - 3e9 * year,
  })
  const lbo = {
    entry_ev: 124e9,
    entry_debt: 77e9,
    entry_equity: 46e9,
    schedule: [1, 2, 3, 4, 5].map(scheduleYear),
    exit_ebitda: 17e9,
    exit_ev: 140e9,
    exit_equity: 97e9,
    moic: 2.09,
    irr: 0.159,
    sensitivity: {
      entry_multiples: [6.5, 7, 7.5],
      exit_multiples: [6, 7, 8],
      irr_grid: [
        [0.1, 0.15, 0.2],
        [0.08, 0.13, 0.18],
        [0.05, 0.1, 0.15],
      ],
      moic_grid: [
        [1.5, 2, 2.5],
        [1.4, 1.9, 2.4],
        [1.2, 1.7, 2.2],
      ],
    },
    capital_structure_warning: 'Simplified sources & uses: entry debt is modeled as new debt.',
  }
  const inputs = {
    leverage_multiple: 5,
    entry_ev_ebitda: 8,
    exit_ev_ebitda: 8,
    holding_period_years: 5,
    assumption_provenance: { leverage_multiple: '5.0× (PE-convention leverage)' },
  }

  it('renders entry/exit modules + full debt schedule + IRR sensitivity', () => {
    const { container } = render(
      <CompactArtifactViewer
        artifact={artifact('lbo', lbo, {
          assumptions: { parameters: inputs },
        } as Partial<ArtifactDetail>)}
      />,
    )
    expect(screen.getByText('Entry')).toBeTruthy()
    expect(screen.getByText('Exit')).toBeTruthy()
    expect(screen.getByText('Debt Schedule')).toBeTruthy()
    // All 5 schedule years render (no truncation) — the table's body has 5 rows.
    const scheduleTable = container.querySelector('table')
    expect(scheduleTable?.querySelectorAll('tbody tr').length).toBe(5)
    expect(screen.getByText('5.0× (PE-convention leverage)')).toBeTruthy()
    expect(container.textContent ?? '').not.toMatch(/\d+ fields/)
    expect(container.textContent ?? '').not.toMatch(/\d+ 字段/)
  })

  it('badges the headline IRR when the deal does NOT self-finance (MU peak-EBITDA)', () => {
    render(
      <CompactArtifactViewer
        artifact={artifact('lbo', { ...lbo, self_financing: false }, {
          assumptions: { parameters: inputs },
        } as Partial<ArtifactDetail>)}
      />,
    )
    // The IRR still renders, but the not-self-financing caveat sits beside it so
    // the exit-multiple artifact can't be read as an achievable return.
    expect(screen.getByText('not self-financing')).toBeInTheDocument()
  })

  it('shows no self-financing badge when the flag is absent (self-financing / legacy)', () => {
    render(
      <CompactArtifactViewer
        artifact={artifact('lbo', lbo, {
          assumptions: { parameters: inputs },
        } as Partial<ArtifactDetail>)}
      />,
    )
    expect(screen.queryByText('not self-financing')).toBeNull()
  })

  it('degrades gracefully when the LBO step did not resolve (no schedule)', () => {
    const { container } = render(
      <CompactArtifactViewer
        artifact={artifact(
          'lbo',
          {
            numeric_audit: {
              findings: [],
              artifact_status: 'publishable',
              withhold_valuation: false,
            },
          },
          { assumptions: { parameters: inputs } } as Partial<ArtifactDetail>,
        )}
      />,
    )
    // No crash, no empty shell — a calm "did not resolve" note + the provenance.
    expect(screen.getByText(/did not resolve to a feasible capital structure/)).toBeTruthy()
    expect(screen.getByText('5.0× (PE-convention leverage)')).toBeTruthy()
    expect(container.textContent ?? '').not.toMatch(/\d+ fields/)
  })
})

describe('CompactArtifactViewer — comps reuses the competitive peer table', () => {
  const company = (ticker: string, name: string, pe: number) => ({
    ticker,
    name,
    revenue: 5e10,
    ebitda: 1.5e10,
    net_income: 1.3e10,
    market_cap: 3.4e11,
    gross_margin: 0.61,
    operating_margin: 0.29,
    pe_ratio: pe,
    ev_ebitda: 24.8,
    ev_revenue: 7.8,
    core_pe_ratio: 29.1,
    pb_ratio: 10.4,
  })
  const comps = {
    target: company('KO', 'Coca-Cola', 25.5),
    peers: [company('PEP', 'PepsiCo', 22.1), company('MDLZ', 'Mondelez', 20.3)],
    median_pe: 24.6,
    median_pb: 5.3,
    median_ev_ebitda: 13.7,
    median_core_pe: 17,
    median_ev_revenue: 2.4,
    peer_justification: 'Deterministic screen: candidate pool 51 firms -> high-affinity peers.',
    positioning_narrative: '',
  }

  it('renders the peer table (target + every peer row), no "N fields" dump', () => {
    const { container } = render(<CompactArtifactViewer artifact={artifact('comps', comps)} />)
    // Reused CompetitiveBody peer table: the target + every peer row renders.
    expect(screen.getByText('PEP')).toBeTruthy()
    expect(screen.getByText('MDLZ')).toBeTruthy()
    // Peer-median line surfaces the backend median (not a re-computed one).
    expect(screen.getByText(/Peer median/)).toBeTruthy()
    expect(container.textContent ?? '').not.toMatch(/\d+ fields/)
    expect(container.textContent ?? '').not.toMatch(/\d+ 字段/)
  })
})
