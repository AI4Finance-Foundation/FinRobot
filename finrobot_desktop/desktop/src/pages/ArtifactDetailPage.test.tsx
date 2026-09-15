import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

// BUG-014: the artifact id is the real identity; the URL ticker is only
// routing context. Visiting /stocks/AAPL/runs/<NVDA-artifact-id> must
// canonicalize to /stocks/NVDA/runs/<id> so no AAPL chrome wraps NVDA chapters.

const navigateSpy = vi.fn()
const params = { ticker: 'AAPL', artifactId: 'art-nvda-1' }

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return {
    ...actual,
    useNavigate: () => navigateSpy,
    useParams: () => params,
    useLocation: () => ({
      pathname: '/stocks/AAPL/runs/art-nvda-1',
      hash: '',
      search: '',
      state: null,
      key: 'x',
    }),
  }
})

const detail = {
  data: undefined as unknown,
  isLoading: false,
  isError: false,
  error: null as unknown,
}

vi.mock('../hooks/useV5Artifacts', () => ({
  useArtifactDetail: () => detail,
  useV5ArtifactTimeline: () => ({ data: [] }),
}))

// i18n + heavy shell/chapter children are irrelevant to the redirect logic.
vi.mock('../i18n', () => ({ useI18n: () => ({ locale: 'en', t: (k: string) => k }) }))
vi.mock('../stores/navMemoryStore', () => ({
  useNavMemoryStore: (sel: (s: { setLastStocksPath: () => void }) => unknown) =>
    sel({ setLastStocksPath: () => {} }),
}))
vi.mock('../stores/toastStore', () => ({
  useToastStore: (sel: (s: { addToast: () => void }) => unknown) => sel({ addToast: () => {} }),
}))
vi.mock('../api/client', () => ({ markArtifactViewed: vi.fn().mockResolvedValue(undefined) }))
vi.mock('../api/queryClient', () => ({ queryClient: { invalidateQueries: vi.fn() } }))
// Keep the real module (readerFacingComputeWarnings et al. — CompactArtifactViewer
// consumes them) and override only deriveReportData, so the mock can't drift from
// the implementation's export surface.
vi.mock('./artifact-detail/reportData', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./artifact-detail/reportData')>()),
  deriveReportData: () => ({ thesis: null, dcf: null, createdAt: null, versionLabel: 'v1' }),
}))
vi.mock('../components/VersionDiffBanner', () => ({ VersionDiffBanner: () => null }))
// Render identifiable sentinels (not null) so the type-branch test can assert
// which chrome / body actually mounts for equity_research vs a dcf artifact.
vi.mock('./artifact-detail/shell/ReportToolbar', () => ({
  ReportToolbar: () => <div data-testid="mock-toolbar" />,
}))
vi.mock('./artifact-detail/shell/ReportLeftRail', () => ({
  ReportLeftRail: () => <div data-testid="mock-left-rail" />,
}))
vi.mock('./artifact-detail/ReportChapters', () => ({
  ReportChapters: () => <div data-testid="mock-report-chapters" />,
}))
vi.mock('./artifact-detail/chapters/labels', () => ({ allChapterLabels: () => [] }))

import { ArtifactDetailPage } from './ArtifactDetailPage'

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ArtifactDetailPage />
    </QueryClientProvider>,
  )
}

describe('ArtifactDetailPage ticker canonicalization (BUG-014)', () => {
  beforeEach(() => {
    navigateSpy.mockClear()
    params.ticker = 'AAPL'
    detail.data = undefined
    detail.isLoading = false
    detail.isError = false
  })

  it('redirects (replace) to the artifact ticker when the URL ticker mismatches', () => {
    detail.data = {
      id: 'art-nvda-1',
      ticker: 'NVDA',
      type: 'equity_research',
      created_at: '',
      outputs: {},
      inputs: {},
      assumptions: {},
      meta: {},
    }
    renderPage()
    expect(navigateSpy).toHaveBeenCalledWith('/stocks/NVDA/runs/art-nvda-1', { replace: true })
  })

  it('does not redirect when the URL ticker already matches the artifact', () => {
    params.ticker = 'NVDA'
    detail.data = {
      id: 'art-nvda-1',
      ticker: 'NVDA',
      type: 'equity_research',
      created_at: '',
      outputs: {},
      inputs: {},
      assumptions: {},
      meta: {},
    }
    renderPage()
    expect(navigateSpy).not.toHaveBeenCalled()
  })
})

// BUG-20260602-039: only equity_research gets the 13-chapter shell. A dcf (or
// any other) artifact must render the compact viewer — NOT the empty equity
// shell with its TOC / right-rail (Version Timeline) / scroll-spy.
describe('ArtifactDetailPage type branch (BUG-039)', () => {
  beforeEach(() => {
    navigateSpy.mockClear()
    params.ticker = 'AAPL'
    params.artifactId = 'art-aapl-dcf'
    detail.data = undefined
    detail.isLoading = false
    detail.isError = false
  })

  it('renders the compact viewer (inputs + result) for a dcf artifact, not the 13-chapter shell', () => {
    params.ticker = 'AAPL'
    detail.data = {
      id: 'art-aapl-dcf',
      ticker: 'AAPL',
      type: 'dcf',
      created_at: '2026-06-01T00:00:00Z',
      outputs: {
        structured: { implied_price: 187.4, wacc: 0.082, enterprise_value: 3.1e12 },
        summary_text: 'DCF implied $187.40 / WACC 8.2%',
        warnings: [],
      },
      inputs: { data_source: 'FMP', data_fetched_at: '2026-06-01T00:00:00Z', raw_data: {} },
      assumptions: { parameters: { terminal_growth_rate: 0.025, tax_rate: 0.21 } },
      meta: { created_at: '2026-06-01T00:00:00Z', source: 'pipeline:dcf' },
    }

    renderPage()

    // Compact viewer mounts with the artifact's real numbers. The implied price
    // now surfaces both in the headline and in the reused DCF valuation panel.
    expect(screen.getByTestId('compact-artifact-viewer')).toBeTruthy()
    expect(screen.getByText('DCF Implied Price')).toBeTruthy()
    expect(screen.getAllByText('$187.40').length).toBeGreaterThan(0)
    // Inputs surfaced via the reused ValuationBody DCF-inputs module (the tool page
    // now shares the report's chapter primitives instead of a flat K-V dump).
    expect(screen.getByText('DCF Inputs & Implied Value')).toBeTruthy()
    // Audit trail surfaced.
    expect(screen.getByText('pipeline:dcf')).toBeTruthy()

    // The 13-chapter equity shell must be ABSENT — neither the chapter body nor
    // the left-rail chrome mounts for a dcf artifact (the left rail is the only
    // shell sentinel that exists post-redesign; the old TOC / right-rail mocks
    // were removed when those components were merged into ReportLeftRail).
    expect(screen.queryByTestId('mock-report-chapters')).toBeNull()
    expect(screen.queryByTestId('mock-left-rail')).toBeNull()
  })

  it('still renders the 13-chapter shell for equity_research', () => {
    params.ticker = 'AAPL'
    detail.data = {
      id: 'art-aapl-eq',
      ticker: 'AAPL',
      type: 'equity_research',
      created_at: '2026-06-01T00:00:00Z',
      outputs: {},
      inputs: {},
      assumptions: {},
      meta: {},
    }
    params.artifactId = 'art-aapl-eq'

    renderPage()

    expect(screen.getByTestId('mock-report-chapters')).toBeTruthy()
    expect(screen.getByTestId('mock-left-rail')).toBeTruthy()
    expect(screen.queryByTestId('compact-artifact-viewer')).toBeNull()
  })
})

// Switching versions in the left-rail VERSIONS tab changes the URL artifactId;
// the next version is usually not cached. useArtifactDetail uses
// placeholderData:keepPreviousData so `data` keeps serving the PREVIOUS artifact
// while the new one loads — and the page must therefore keep the full report
// shell mounted, NOT tear it down to the bare full-screen loader. Tearing it
// down unmounts ReportLeftRail, resetting its local tab+scroll-spy state, which
// bounced the reader from the VERSIONS tab back to CONTENTS/chapter-1 on every
// switch (the "切版本把左侧版本和目录都切回去了" regression introduced by the
// f77ecd16 TOC↔timeline rail merge). The full-screen loader is reserved for the
// genuine cold load where there is no data at all.
describe('ArtifactDetailPage version switch — report shell survives an in-flight fetch', () => {
  beforeEach(() => {
    navigateSpy.mockClear()
    params.ticker = 'AAPL'
    params.artifactId = 'art-aapl-eq'
    detail.data = undefined
    detail.isLoading = false
    detail.isError = false
  })

  it('keeps the left rail + chapters mounted (no full-screen loader) while fetching the next version but retaining previous data', () => {
    detail.data = {
      id: 'art-aapl-eq',
      ticker: 'AAPL',
      type: 'equity_research',
      created_at: '2026-06-01T00:00:00Z',
      outputs: {},
      inputs: {},
      assumptions: {},
      meta: {},
    }
    // A version switch is in flight (RQ reports loading) but keepPreviousData
    // keeps the previous artifact in `data`.
    detail.isLoading = true

    renderPage()

    // Shell stays up so the rail keeps its VERSIONS tab + scroll position.
    expect(screen.getByTestId('mock-left-rail')).toBeTruthy()
    expect(screen.getByTestId('mock-report-chapters')).toBeTruthy()
    // The bare loader (which would unmount the rail) must NOT take over.
    expect(screen.queryByText('report.load.loading')).toBeNull()
  })

  it('still shows the full-screen loader on a genuine cold load (no data yet)', () => {
    detail.data = undefined
    detail.isLoading = true

    renderPage()

    expect(screen.getByText('report.load.loading')).toBeTruthy()
    expect(screen.queryByTestId('mock-left-rail')).toBeNull()
  })
})
