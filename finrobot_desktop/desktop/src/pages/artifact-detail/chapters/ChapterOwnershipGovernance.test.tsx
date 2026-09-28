// Vitest coverage for chapter 12 (Ownership & Governance).
// Covers: empty (no ownership_governance at all), degraded sub-block,
// populated state across all four sub-blocks (insiders / institutions /
// compensation / 13D-G alerts).

import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import { ChapterOwnershipGovernance } from './ChapterOwnershipGovernance'
import type {
  FilingProvenanceShape,
  InsiderTransactionShape,
  InstitutionalHoldingShape,
  OwnershipGovernanceShape,
  ProxyCompensationShape,
  ScheduleThirteenAlertShape,
} from './types'

function wrap(node: React.ReactElement) {
  return <MemoryRouter>{node}</MemoryRouter>
}

const baseProv = (form: string): FilingProvenanceShape => ({
  form,
  filing_date: '2026-02-15',
  accession_no: '0001234567-26-000123',
  source_url: 'https://www.sec.gov/cgi-bin/browse-edgar',
})

describe('ChapterOwnershipGovernance', () => {
  it('renders settings CTA when ownership_governance is absent', () => {
    render(wrap(<ChapterOwnershipGovernance ownership={null} reportingCurrency="USD" />))
    expect(screen.getByText(/SEC EDGAR identity required/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Open Settings/i })).toHaveAttribute(
      'href',
      '/settings',
    )
  })

  it('renders insider transactions table when populated', () => {
    const insider: InsiderTransactionShape = {
      filing_date: '2026-04-12',
      accession_no: '0001234567-26-000456',
      insider_name: 'Jensen Huang',
      insider_position: 'CEO',
      transaction_type: 'sale',
      code: 'S',
      shares: 240000,
      value: 28800000,
      price_per_share: 120,
      provenance: baseProv('4'),
    }
    const ownership: OwnershipGovernanceShape = {
      insider_transactions: [insider],
      generated_at: '2026-05-27T09:00:00Z',
      degraded_sections: [],
    }
    render(wrap(<ChapterOwnershipGovernance ownership={ownership} reportingCurrency="USD" />))
    expect(screen.getByText('Jensen Huang')).toBeInTheDocument()
    expect(screen.getByText(/Insider Transactions/i)).toBeInTheDocument()
    // Sale label rendered from i18n catalog (en), not raw "sale"
    expect(screen.getByText('Sale')).toBeInTheDocument()
  })

  it('renders institutional holdings sorted by value descending', () => {
    const small: InstitutionalHoldingShape = {
      holder_name: 'Small Fund',
      cusip: '67066G104',
      name_of_issuer: 'NVIDIA CORP',
      shares: 100_000,
      value_usd: 12_000_000,
      period_end: '2026-03-31',
      provenance: baseProv('13F-HR'),
    }
    const big: InstitutionalHoldingShape = {
      holder_name: 'BlackRock',
      cusip: '67066G104',
      name_of_issuer: 'NVIDIA CORP',
      shares: 100_000_000,
      value_usd: 12_000_000_000,
      period_end: '2026-03-31',
      shares_change_pct: 4.2,
      provenance: baseProv('13F-HR'),
    }
    const ownership: OwnershipGovernanceShape = {
      institutional_holdings: [small, big],
      generated_at: '2026-05-27T09:00:00Z',
      degraded_sections: [],
    }
    render(wrap(<ChapterOwnershipGovernance ownership={ownership} reportingCurrency="USD" />))
    const rows = screen.getAllByRole('row')
    // First row = header; second row = highest-value (BlackRock)
    expect(rows[1].textContent).toContain('BlackRock')
    expect(rows[2].textContent).toContain('Small Fund')
  })

  it('labels institutional rows by 13F share class when the same holder files multiple classes (GOOGL/GOOG)', () => {
    const classA: InstitutionalHoldingShape = {
      holder_name: 'BlackRock, Inc.',
      cusip: '02079K305',
      name_of_issuer: 'ALPHABET INC',
      title_of_class: 'CAP STK CL A',
      shares: 446_980_992,
      value_usd: 80_000_000_000,
      period_end: '2026-03-31',
      provenance: baseProv('13F-HR'),
    }
    const classC: InstitutionalHoldingShape = {
      holder_name: 'BlackRock, Inc.',
      cusip: '02079K107',
      name_of_issuer: 'ALPHABET INC',
      title_of_class: 'CAP STK CL C',
      shares: 364_758_302,
      value_usd: 65_000_000_000,
      period_end: '2026-03-31',
      provenance: baseProv('13F-HR'),
    }
    const ownership: OwnershipGovernanceShape = {
      institutional_holdings: [classA, classC],
      generated_at: '2026-05-27T09:00:00Z',
      degraded_sections: [],
    }
    render(wrap(<ChapterOwnershipGovernance ownership={ownership} reportingCurrency="USD" />))
    // Both rows keep the same holder name (real, distinct 13F filings —
    // never merged) but each carries a distinct, SEC-sourced class badge so
    // the two "BlackRock, Inc." rows don't read as a duplicate-data bug.
    expect(screen.getAllByText('BlackRock, Inc.')).toHaveLength(2)
    expect(screen.getByText('Class A')).toBeInTheDocument()
    expect(screen.getByText('Class C')).toBeInTheDocument()
  })

  it('omits the share-class badge when every row shares the same class (single-class ticker)', () => {
    const rowA: InstitutionalHoldingShape = {
      holder_name: 'Vanguard',
      cusip: '037833100',
      name_of_issuer: 'APPLE INC',
      title_of_class: 'COM',
      shares: 1_000_000,
      value_usd: 200_000_000,
      period_end: '2026-03-31',
      provenance: baseProv('13F-HR'),
    }
    const rowB: InstitutionalHoldingShape = {
      holder_name: 'BlackRock',
      cusip: '037833100',
      name_of_issuer: 'APPLE INC',
      title_of_class: 'COM',
      shares: 900_000,
      value_usd: 180_000_000,
      period_end: '2026-03-31',
      provenance: baseProv('13F-HR'),
    }
    const ownership: OwnershipGovernanceShape = {
      institutional_holdings: [rowA, rowB],
      generated_at: '2026-05-27T09:00:00Z',
      degraded_sections: [],
    }
    render(wrap(<ChapterOwnershipGovernance ownership={ownership} reportingCurrency="USD" />))
    expect(screen.queryByText('Class', { exact: false })).not.toBeInTheDocument()
  })

  it('renders cold-state placeholder for degraded sub-section', () => {
    const ownership: OwnershipGovernanceShape = {
      institutional_holdings: [],
      generated_at: '2026-05-27T09:00:00Z',
      degraded_sections: ['institutional_holdings'],
    }
    render(wrap(<ChapterOwnershipGovernance ownership={ownership} reportingCurrency="USD" />))
    // Honest cold-state copy: the old text promised a "background sync" that
    // never runs (auto-refresh is off by default). It now tells the user the
    // sync must be enabled/triggered in Settings, with a CTA to get there.
    expect(screen.getByText(/13F holdings cache not built/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Open Settings/i })).toBeInTheDocument()
  })

  it('renders proxy compensation KvGrid with CEO totals', () => {
    const comp: ProxyCompensationShape = {
      filing_date: '2025-12-15',
      accession_no: '0001234567-25-000789',
      ceo_name: 'Tim Cook',
      ceo_total_compensation: 63_209_845,
      ceo_yoy_change_pct: 18.4,
      ceo_pay_ratio: 1447,
      provenance: baseProv('DEF 14A'),
    }
    const ownership: OwnershipGovernanceShape = {
      proxy_compensation: comp,
      generated_at: '2026-05-27T09:00:00Z',
      degraded_sections: [],
    }
    render(wrap(<ChapterOwnershipGovernance ownership={ownership} reportingCurrency="USD" />))
    expect(screen.getByText('Tim Cook')).toBeInTheDocument()
    expect(screen.getByText('1447:1')).toBeInTheDocument()
  })

  it('does not render stale proxy payloads with title-as-name and revenue-sized comp', () => {
    const comp: ProxyCompensationShape = {
      filing_date: '2026-01-08',
      accession_no: '0001308179-26-000008',
      ceo_name: 'Chief Executive Officer',
      ceo_total_compensation: 416_200_000_000,
      provenance: baseProv('DEF 14A'),
    }
    const ownership: OwnershipGovernanceShape = {
      proxy_compensation: comp,
      generated_at: '2026-05-28T01:21:46Z',
      degraded_sections: [],
    }
    render(wrap(<ChapterOwnershipGovernance ownership={ownership} reportingCurrency="USD" />))
    expect(screen.queryByText('Chief Executive Officer')).not.toBeInTheDocument()
    expect(screen.queryByText(/\$416/)).not.toBeInTheDocument()
    expect(screen.getByText(/CEO compensation unavailable/i)).toBeInTheDocument()
  })

  it('uses reason-specific message when backend supplies degraded_reasons', () => {
    // Backend emits `no_recent_filings` when SEC identity is configured but the
    // ticker simply has no Form 4 in the last 90 days (small caps, post-grant
    // quiet periods, etc). UI must NOT show "check SEC identity" — that blames
    // the user for a perfectly valid backend state.
    const ownership: OwnershipGovernanceShape = {
      insider_transactions: [],
      generated_at: '2026-05-27T09:00:00Z',
      degraded_sections: ['insider_transactions'],
      degraded_reasons: { insider_transactions: 'no_recent_filings' },
    }
    render(wrap(<ChapterOwnershipGovernance ownership={ownership} reportingCurrency="USD" />))
    expect(
      screen.getByText(/no insider transactions filed in the past 90 days/i),
    ).toBeInTheDocument()
  })

  it('falls back to generic degraded message when reason is missing', () => {
    const ownership: OwnershipGovernanceShape = {
      insider_transactions: [],
      generated_at: '2026-05-27T09:00:00Z',
      degraded_sections: ['insider_transactions'],
      // No degraded_reasons supplied → fallback to generic message
    }
    render(wrap(<ChapterOwnershipGovernance ownership={ownership} reportingCurrency="USD" />))
    expect(screen.getByText(/older report has no specific reason/i)).toBeInTheDocument()
    expect(screen.queryByText(/verify SEC identity/i)).not.toBeInTheDocument()
  })

  it('renders Schedule 13D as activist with warning tone', () => {
    const alert: ScheduleThirteenAlertShape = {
      filer_name: 'Pershing Square',
      filing_date: '2026-04-30',
      accession_no: '0001234567-26-000999',
      schedule_type: '13D',
      shares: 25_000_000,
      pct_of_class: 6.8,
      transaction_summary: 'Activist position — engaging with management.',
    }
    const ownership: OwnershipGovernanceShape = {
      schedule13_alerts: [alert],
      generated_at: '2026-05-27T09:00:00Z',
      degraded_sections: [],
    }
    render(wrap(<ChapterOwnershipGovernance ownership={ownership} reportingCurrency="USD" />))
    expect(screen.getByText('Pershing Square')).toBeInTheDocument()
    expect(screen.getByText('13D')).toBeInTheDocument()
    expect(screen.getByText(/Activist position/)).toBeInTheDocument()
  })
})

describe('ChapterOwnershipGovernance signal strip', () => {
  const tx = (transaction_type: string, code: string, value: number): InsiderTransactionShape => ({
    filing_date: '2026-04-01',
    accession_no: '0001234567-26-000001',
    insider_name: 'Insider',
    transaction_type,
    code,
    shares: 1000,
    value,
    provenance: baseProv('4'),
  })
  const hold = (value_usd: number, holder_name: string): InstitutionalHoldingShape => ({
    holder_name,
    cusip: '000000000',
    name_of_issuer: 'ACME',
    shares: 1,
    value_usd,
    period_end: '2026-03-31',
    provenance: baseProv('13F-HR'),
  })

  const ownership: OwnershipGovernanceShape = {
    insider_transactions: [
      tx('purchase', 'P', 5_000_000),
      tx('sale', 'S', 2_000_000),
      tx('grant', 'A', 99_000_000), // compensation — must NEVER enter the net
      tx('tax_withholding', 'F', 1_000_000), // compensation mechanics — excluded
    ],
    institutional_holdings: [
      hold(30e9, 'A'),
      hold(25e9, 'B'),
      hold(20e9, 'C'),
      hold(10e9, 'D'),
      hold(10e9, 'E'),
      hold(5e9, 'F'),
    ], // total 100e9, top-5 = 95e9 → 95%
    generated_at: '2026-05-27T09:00:00Z',
    degraded_sections: [],
  }

  it('nets only open-market P/S — grants and tax-withholding never enter the flow', () => {
    const { container } = render(
      wrap(<ChapterOwnershipGovernance ownership={ownership} reportingCurrency="USD" />),
    )
    const strip = container.querySelector('[data-testid="ownership-signal-strip"]')
    expect(strip).not.toBeNull()
    const text = strip?.textContent ?? ''
    expect(text).toMatch(/Insider open-market flow/i)
    // net = $5M buy − $2M sell = +$3.0M; the $99M grant + $1M tax stay out of it.
    expect(text).toMatch(/net \+\$3/)
    expect(text).toMatch(/2 non-market excluded/)
    // The grant's $99M must not leak into the strip (it shows in the table below).
    expect(text).not.toMatch(/99/)
  })

  it('shows institutional top-5 concentration share', () => {
    const { container } = render(
      wrap(<ChapterOwnershipGovernance ownership={ownership} reportingCurrency="USD" />),
    )
    const text =
      container.querySelector('[data-testid="ownership-signal-strip"]')?.textContent ?? ''
    expect(text).toMatch(/Institutional concentration/i)
    expect(text).toMatch(/95%/) // top 5 of 6 holders = 95e9 / 100e9
  })
})
