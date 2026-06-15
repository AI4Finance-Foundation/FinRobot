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

// Peer P/E [20,30,40] → median 30; op-margin [.10,.30,.40] → median .30.
const PEERS: PeerCompsShape = {
  target: co('TGT', 10, 11, 12, 0.5, 0.2),
  peers: [
    co('P1', 20, 22, 24, 0.4, 0.1),
    co('P2', 30, 33, 36, 0.3, 0.3),
    co('P3', 40, 44, 48, 0.5, 0.4),
  ],
}

describe('ChapterCompetitive comps heat-shading', () => {
  it('tints a cheaper-than-peer multiple green with the deviation in its title', () => {
    render(<ChapterCompetitive peers={PEERS} thesis={null} />)
    const cell = screen.getByText('10.0') // target P/E 10 vs peer median 30 → -67%
    expect(cell.getAttribute('title')).toBe('-67% vs peer median')
    expect(cell.getAttribute('style') ?? '').toContain('--success')
  })

  it('tints a below-peer margin red (margins: higher is favorable)', () => {
    render(<ChapterCompetitive peers={PEERS} thesis={null} />)
    const cell = screen.getByText('20.0%') // target op-margin 20% vs peer median 30% → -33%
    expect(cell.getAttribute('title')).toBe('-33% vs peer median')
    expect(cell.getAttribute('style') ?? '').toContain('--danger')
  })

  it('leaves a cell sitting at the peer median un-shaded (deadband)', () => {
    render(<ChapterCompetitive peers={PEERS} thesis={null} />)
    const cell = screen.getByText('30.0') // P2 P/E == peer median 30
    expect(cell.getAttribute('title')).toBeNull()
  })

  it('does not shade when there are fewer than 3 peers (unstable median)', () => {
    const thin: PeerCompsShape = { target: PEERS.target, peers: PEERS.peers?.slice(0, 2) }
    render(<ChapterCompetitive peers={thin} thesis={null} />)
    expect(screen.getByText('10.0').getAttribute('title')).toBeNull()
  })
})
