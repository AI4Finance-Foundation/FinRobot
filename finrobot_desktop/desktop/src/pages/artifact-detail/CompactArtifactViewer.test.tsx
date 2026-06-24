import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { CompactArtifactViewer } from './CompactArtifactViewer'
import type { ArtifactDetail } from '../../hooks/useV5Artifacts'

function compsArtifact(structured: Record<string, unknown>): ArtifactDetail {
  return {
    id: 'art-comps',
    ticker: 'JPM',
    type: 'comps',
    created_at: '2026-06-01T00:00:00Z',
    outputs: { structured, summary_text: '', warnings: [] },
    inputs: { data_source: 'FMP', data_fetched_at: '2026-06-01T00:00:00Z', raw_data: {} },
    assumptions: { parameters: { peers: ['BAC', 'WFC'] } },
    meta: { created_at: '2026-06-01T00:00:00Z', source: 'pipeline:comps' },
  } as unknown as ArtifactDetail
}

// The comps headline must surface P/B (the lead relative multiple for cyclicals &
// financials) when present, and must NOT show EV/EBITDA once the backend has nulled
// it for a financial-sector target (build_comps_artifact suppression) — so a bank's
// standalone comps never headlines the EV/EBITDA category error.
describe('CompactArtifactViewer — comps headline multiples', () => {
  it('surfaces Peer Median P/B alongside P/E and EV/EBITDA when all are present', () => {
    render(
      <CompactArtifactViewer
        artifact={compsArtifact({ median_pe: 11, median_pb: 1.3, median_ev_ebitda: 9 })}
      />,
    )
    expect(screen.getByText('Peer Median P/E')).toBeTruthy()
    expect(screen.getByText('Peer Median P/B')).toBeTruthy()
    expect(screen.getByText('Peer Median EV/EBITDA')).toBeTruthy()
    // P/B value rendered as a multiple.
    expect(screen.getByText('1.3×')).toBeTruthy()
  })

  it('omits EV/EBITDA when the backend nulled it for a financial-sector target', () => {
    render(
      <CompactArtifactViewer
        artifact={compsArtifact({ median_pe: 11, median_pb: 1.3, median_ev_ebitda: null })}
      />,
    )
    // Banks lead with P/E + P/B — both still shown…
    expect(screen.getByText('Peer Median P/E')).toBeTruthy()
    expect(screen.getByText('Peer Median P/B')).toBeTruthy()
    // …and the suppressed EV/EBITDA category error never reaches the headline.
    expect(screen.queryByText('Peer Median EV/EBITDA')).toBeNull()
  })
})
