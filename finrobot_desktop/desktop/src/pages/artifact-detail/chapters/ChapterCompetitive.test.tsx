// Guards the comps-table heat-shading: each numeric cell is tinted by its signed
// deviation from THIS table's peer median (multiples: lower = green; margins:
// higher = green), with the exact deviation in the cell `title`. The shading is a
// scannability aid over data the report already froze — never a verdict.
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

import { ChapterCompetitive } from './ChapterCompetitive'
import type { PeerCompsShape } from './types'

// Recharts panels are noise here; the table is the unit under test.
vi.mock('../../../components/charts/PeerComparisonChart', () => ({ default: () => null }))
vi.mock('../../../components/charts/CompanyRadarChart', () => ({ default: () => null }))

function co(ticker: string, pe: number, core: number, ev: number, gross: number, op: number): any {
  return {
    ticker,
    name: ticker,
    revenue: 1e9,
    ebitda: 1e8,
    net_income: 1e8,
    market_cap: 1e10,
    gross_margin: gross,
    operating_margin: op,
    pe_ratio: pe,
    core_pe_ratio: core,
    ev_ebitda: ev,
  }
}

// Multiples shade vs the BACKEND median (NM-capped, == the footer's "Peer median"
// + the radar). Margins (no backend median) shade vs the frontend median over the
// visible peers: op-margin [.10,.30,.40] → median .30.
const PEERS: PeerCompsShape = {
  target: co('TGT', 10, 11, 12, 0.5, 0.2),
  peers: [
    co('P1', 20, 22, 24, 0.4, 0.1),
    co('P2', 30, 33, 36, 0.3, 0.3),
    co('P3', 40, 44, 48, 0.5, 0.4),
  ],
  // Authoritative (NM-capped) medians the page advertises; deliberately NOT the
  // naive median of the visible peers — the shading must track THESE.
  median_pe: 30,
  median_core_pe: 33,
  median_ev_ebitda: 36,
}

describe('ChapterCompetitive comps heat-shading', () => {
  it('tints a cheaper-than-backend-median multiple green with the deviation in its title', () => {
    render(<ChapterCompetitive peers={PEERS} thesis={null} />)
    const cell = screen.getByText('10.0') // target P/E 10 vs BACKEND median_pe 30 → -67%
    expect(cell.getAttribute('title')).toBe('-67% vs peer median')
    expect(cell.getAttribute('style') ?? '').toContain('--success')
  })

  it('tints a below-peer margin red (margins: higher is favorable, frontend median)', () => {
    render(<ChapterCompetitive peers={PEERS} thesis={null} />)
    const cell = screen.getByText('20.0%') // target op-margin 20% vs peer median 30% → -33%
    expect(cell.getAttribute('title')).toBe('-33% vs peer median')
    expect(cell.getAttribute('style') ?? '').toContain('--danger')
  })

  it('leaves a cell sitting at the backend peer median un-shaded (deadband)', () => {
    render(<ChapterCompetitive peers={PEERS} thesis={null} />)
    const cell = screen.getByText('30.0') // P2 P/E == backend median_pe 30
    expect(cell.getAttribute('title')).toBeNull()
  })

  it('uses the BACKEND median, never a frontend re-median — un-shaded when it is absent', () => {
    // The defect: shading off a frontend median (here naive ≈ 30) that contradicts
    // the advertised backend median. With median_* omitted there is NO fallback —
    // the multiple columns stay un-shaded rather than inventing a divergent anchor.
    const noBackendMedian: PeerCompsShape = { target: PEERS.target, peers: PEERS.peers }
    render(<ChapterCompetitive peers={noBackendMedian} thesis={null} />)
    expect(screen.getByText('10.0').getAttribute('title')).toBeNull() // target P/E un-shaded
  })

  it('does not shade MARGIN columns with fewer than 3 peers (unstable frontend median)', () => {
    const thin: PeerCompsShape = {
      target: PEERS.target,
      peers: PEERS.peers?.slice(0, 2),
      median_pe: 30, // backend median present → multiples still shade…
    }
    render(<ChapterCompetitive peers={thin} thesis={null} />)
    expect(screen.getByText('50.0%').getAttribute('title')).toBeNull() // …but target gross margin does not
  })
})

describe('ChapterCompetitive heat-shading legend', () => {
  it('renders a legend whose semantics match heat(): green = cheaper/stronger, red = richer/weaker, ±5% in-line', () => {
    render(<ChapterCompetitive peers={PEERS} thesis={null} />)
    // green chip == heat() favorable side (lowerFavorable multiples / higher margins)
    expect(screen.getByText('cheaper / stronger')).toBeInTheDocument()
    // red chip == heat() unfavorable side
    expect(screen.getByText('richer / weaker')).toBeInTheDocument()
    // deadband: heat() returns {} when |dev| < 0.05 → "no tint"
    expect(screen.getByText(/within ±5% = in-line/)).toBeInTheDocument()
    // anchored to the same peer median the shading uses
    expect(screen.getByText(/Cell shading vs peer median/)).toBeInTheDocument()
  })

  it('omits the legend entirely when there are no comparables (no table to explain)', () => {
    render(<ChapterCompetitive peers={{ target: undefined, peers: [] }} thesis={null} />)
    expect(screen.queryByText('cheaper / stronger')).toBeNull()
  })
})

describe('ChapterCompetitive bank branch (financial_sector → P/B, not EV/EBITDA)', () => {
  const BANK: PeerCompsShape = {
    target: { ...co('BNK', 12, 13, 8, 0.0, 0.35), pb_ratio: 1.8 },
    peers: [
      { ...co('B1', 14, 15, 9, 0.0, 0.3), pb_ratio: 1.2 },
      { ...co('B2', 16, 17, 10, 0.0, 0.3), pb_ratio: 1.5 },
      { ...co('B3', 18, 19, 11, 0.0, 0.3), pb_ratio: 2.0 },
    ],
    median_pe: 15,
    median_pb: 1.5,
    median_ev_ebitda: 10, // present but must be IGNORED for a bank
  }

  it('leads the primary multiple column on P/B and hides EV/EBITDA', () => {
    render(<ChapterCompetitive peers={BANK} thesis={null} financialSector />)
    expect(screen.getByText('P/B')).toBeInTheDocument()
    expect(screen.queryByText('EV/EBITDA')).toBeNull()
    // Target's P/B (1.8), NOT its EV/EBITDA (8.0), fills the primary cell.
    expect(screen.getByText('1.8')).toBeInTheDocument()
    // Median line advertises P/B, not EV/EBITDA.
    expect(screen.getByText(/P\/B 1\.5/)).toBeInTheDocument()
    // Calm caliber note explains why EV/EBITDA is dropped.
    expect(screen.getByText(/category error/i)).toBeInTheDocument()
  })

  it('non-bank control keeps EV/EBITDA and shows no P/B column', () => {
    render(<ChapterCompetitive peers={BANK} thesis={null} financialSector={false} />)
    expect(screen.getByText('EV/EBITDA')).toBeInTheDocument()
    expect(screen.queryByText('P/B')).toBeNull()
    // EV/EBITDA target value 8.0 fills the primary cell (not P/B 1.8).
    expect(screen.getByText('8.0')).toBeInTheDocument()
  })
})

describe('ChapterCompetitive target (subject) row emphasis', () => {
  it('marks the target row with the EQRV subject accent rail, leaving peers unmarked', () => {
    const { container } = render(<ChapterCompetitive peers={PEERS} thesis={null} />)
    // exactly one row carries the subject marker
    const marked = container.querySelectorAll('tr[data-target]')
    expect(marked).toHaveLength(1)
    const targetRow = marked[0] as HTMLElement
    // it IS the target row (TGT ticker appears in its first cell)
    expect(targetRow.textContent).toContain('TGT')
    // the cyan left rail is drawn via an inset box-shadow on the row
    expect(targetRow.getAttribute('style') ?? '').toContain('inset 3px 0 0 0 var(--accent-cyan)')
    // a peer row is NOT marked as the subject (fixture sets name == ticker, so
    // "P1" appears twice in the row — either node resolves to the same <tr>).
    const peerRow = screen.getAllByText('P1')[0].closest('tr')!
    expect(peerRow.getAttribute('data-target')).toBeNull()
  })
})
