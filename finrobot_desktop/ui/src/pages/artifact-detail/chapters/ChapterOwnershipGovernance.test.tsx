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
    render(wrap(<ChapterOwnershipGovernance ownership={null} />))
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
    render(wrap(<ChapterOwnershipGovernance ownership={ownership} />))
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
    render(wrap(<ChapterOwnershipGovernance ownership={ownership} />))
    const rows = screen.getAllByRole('row')
    // First row = header; second row = highest-value (BlackRock)
    expect(rows[1].textContent).toContain('BlackRock')
    expect(rows[2].textContent).toContain('Small Fund')
  })

  it('renders cold-state placeholder for degraded sub-section', () => {
    const ownership: OwnershipGovernanceShape = {
      institutional_holdings: [],
      generated_at: '2026-05-27T09:00:00Z',
      degraded_sections: ['institutional_holdings'],
    }
    render(wrap(<ChapterOwnershipGovernance ownership={ownership} />))
    expect(screen.getByText(/13F holdings cache empty/i)).toBeInTheDocument()
  })

  it('renders proxy compensation KvGrid with CEO totals', () => {
    const comp: ProxyCompensationShape = {
      filing_date: '2025-12-15',
      accession_no: '0001234567-25-000789',
      ceo_name: 'Tim Cook',
      ceo_total_compensation: 63_209_845,
      ceo_yoy_change_pct: 18.4,
      ceo_pay_ratio: 1447,
      peer_percentile: 92,
      provenance: baseProv('DEF 14A'),
    }
    const ownership: OwnershipGovernanceShape = {
      proxy_compensation: comp,
      generated_at: '2026-05-27T09:00:00Z',
      degraded_sections: [],
    }
    render(wrap(<ChapterOwnershipGovernance ownership={ownership} />))
    expect(screen.getByText('Tim Cook')).toBeInTheDocument()
    expect(screen.getByText('1447:1')).toBeInTheDocument()
    expect(screen.getByText('92th')).toBeInTheDocument()
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
    render(wrap(<ChapterOwnershipGovernance ownership={ownership} />))
    expect(screen.queryByText('Chief Executive Officer')).not.toBeInTheDocument()
    expect(screen.queryByText(/\$416/)).not.toBeInTheDocument()
    expect(screen.getByText(/DEF 14A parse failed/i)).toBeInTheDocument()
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
    render(wrap(<ChapterOwnershipGovernance ownership={ownership} />))
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
    render(wrap(<ChapterOwnershipGovernance ownership={ownership} />))
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
    render(wrap(<ChapterOwnershipGovernance ownership={ownership} />))
    expect(screen.getByText('Pershing Square')).toBeInTheDocument()
    expect(screen.getByText('13D')).toBeInTheDocument()
    expect(screen.getByText(/Activist position/)).toBeInTheDocument()
  })
})
