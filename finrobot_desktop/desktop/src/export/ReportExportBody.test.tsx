import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

// ReportChapters pulls router/query providers + heavy chapter children that are
// irrelevant to which body the export chooses; mock it to a sentinel (mirrors
// ArtifactDetailPage.test.tsx) so we assert the type branch, not the report
// internals. CompactArtifactViewer renders for real — it only needs the i18n
// store (test-setup pins locale=en), no providers.
vi.mock('../pages/artifact-detail/ReportChapters', () => ({
  ReportChapters: () => <div data-testid="mock-report-chapters" />,
}))

import { ReportExportBody } from './ReportExportBody'
import type { ArtifactDetail } from '../hooks/useV5Artifacts'

function dcfArtifact(): ArtifactDetail {
  return {
    id: 'art-aapl-dcf',
    ticker: 'AAPL',
    type: 'dcf',
    created_at: '2026-06-01T00:00:00Z',
    outputs: {
      structured: { implied_price: 187.4, wacc: 0.082 },
      summary_text: 'DCF implied $187.40 / WACC 8.2%',
      warnings: [],
    },
    inputs: { data_source: 'FMP', data_fetched_at: '2026-06-01T00:00:00Z', raw_data: {} },
    assumptions: { parameters: { terminal_growth_rate: 0.025 } },
    meta: { created_at: '2026-06-01T00:00:00Z', source: 'pipeline:dcf' },
  } as unknown as ArtifactDetail
}

function researchArtifact(): ArtifactDetail {
  return {
    id: 'art-aapl-eq',
    ticker: 'AAPL',
    type: 'equity_research',
    created_at: '2026-06-01T00:00:00Z',
    outputs: {},
    inputs: {},
    assumptions: {},
    meta: {},
  } as unknown as ArtifactDetail
}

// BUG-20260602-039 (export path): the standalone HTML export must render the
// SAME body the in-app page does. A dcf/ddm/lbo/comps artifact exports the
// compact viewer with its real numbers, NOT the empty 13-chapter shell.
describe('ReportExportBody — export body mirrors the in-app page', () => {
  it('renders the compact viewer for a dcf artifact, not the 13-chapter shell', () => {
    render(<ReportExportBody artifact={dcfArtifact()} timeline={[]} />)
    expect(screen.getByTestId('compact-artifact-viewer')).toBeTruthy()
    // The artifact's real headline + inputs surface (not an empty equity cover).
    // "DCF Implied Price" + "$187.40" show in the headline AND the reused DCF
    // valuation panel (hero number + the inputs/implied module).
    expect(screen.getAllByText('DCF Implied Price').length).toBeGreaterThan(0)
    expect(screen.getAllByText('$187.40').length).toBeGreaterThan(0)
    expect(screen.getByText('DCF Inputs & Implied Value')).toBeTruthy()
    // The 13-chapter shell must be absent.
    expect(screen.queryByTestId('mock-report-chapters')).toBeNull()
  })

  it('still renders the 13-chapter report for equity_research', () => {
    render(<ReportExportBody artifact={researchArtifact()} timeline={[]} />)
    expect(screen.getByTestId('mock-report-chapters')).toBeTruthy()
    expect(screen.queryByTestId('compact-artifact-viewer')).toBeNull()
  })
})
